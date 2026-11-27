"""Regenerierbarer, lokaler Volltextindex für Material und PDF-Seiten."""
from __future__ import annotations

from contextlib import contextmanager, suppress
import json
import logging
import sqlite3
import stat


SCHEMA = """
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY, scope TEXT NOT NULL, path TEXT NOT NULL,
        stamp TEXT NOT NULL, metadata TEXT NOT NULL, links TEXT,
        UNIQUE(scope, path)
    );
    CREATE TABLE IF NOT EXISTS texts (
        id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files ON DELETE CASCADE,
        page INTEGER NOT NULL, body TEXT NOT NULL, normalized TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS text_files ON texts(file_id);
"""

FTS_SCHEMA = """
    CREATE VIRTUAL TABLE IF NOT EXISTS trigrams USING fts5(
        normalized, content='texts', content_rowid='id', tokenize='trigram case_sensitive 1'
    );
    CREATE TRIGGER IF NOT EXISTS text_insert AFTER INSERT ON texts BEGIN
        INSERT INTO trigrams(rowid, normalized) VALUES (new.id, new.normalized);
    END;
    CREATE TRIGGER IF NOT EXISTS text_delete AFTER DELETE ON texts BEGIN
        INSERT INTO trigrams(trigrams, rowid, normalized) VALUES ('delete', old.id, old.normalized);
    END;
"""


def file_stamp(info):
    return f"{info.st_dev}:{info.st_ino}:{info.st_mtime_ns}:{info.st_ctime_ns}:{info.st_size}"


class SearchIndex:
    def __init__(self, config):
        self.config = config
        self.db = None
        self.fts = False
        # Vor dem ersten Katalogdurchlauf anlegen: ein späteres mkdir ändert den
        # Stempel der Wurzel und erzwingt einen zweiten Durchlauf.
        with suppress(OSError):
            (config.root / ".material-ui").mkdir(exist_ok=True)

    def connection(self):
        if self.db is None:
            try:
                path = self.config.root / ".material-ui" / "search-v1.sqlite3"
                if path.parent.is_symlink() or path.is_symlink():
                    raise ValueError("Verlinkter Suchindex")
                path.parent.mkdir(exist_ok=True)
                self.open(path)
            except (OSError, ValueError, sqlite3.DatabaseError) as error:
                self.close()
                logging.getLogger(__name__).warning("Suchindex bleibt für diese Sitzung im Speicher: %s", error)
                self.open(":memory:")
        return self.db

    def open(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.executescript(SCHEMA)
        try:
            self.db.executescript(FTS_SCHEMA)
            self.db.execute("SELECT rowid FROM trigrams LIMIT 0")
        except sqlite3.OperationalError as error:
            if "no such module" not in str(error) and "no such tokenizer" not in str(error):
                raise
            # A database indexed by another SQLite build can still be read.
            self.db.executescript("DROP TRIGGER IF EXISTS text_insert; DROP TRIGGER IF EXISTS text_delete;")
        else:
            self.fts = True
            with self.db:
                # Backfill if the previous SQLite build had no trigram tokenizer.
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 0:
                    self.db.execute("INSERT INTO trigrams(trigrams) VALUES ('rebuild')")
                    self.db.execute("PRAGMA user_version = 1")
            return
        self.db.execute("PRAGMA user_version = 0")

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        self.fts = False

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            # Two runtimes can open the same workspace. Serialize the snapshot
            # and its updates so both cannot insert the same new file.
            db.execute("BEGIN IMMEDIATE")
            yield

    def refresh(self, scope, paths, load, normalize, *, max_bytes=None, stop=None):
        """Reconcile file stamps and replace only changed text rows in the caller's transaction."""
        old = {path: (key, stamp, links) for key, path, stamp, links in self.db.execute(
            "SELECT id, path, stamp, links FROM files WHERE scope = ?", (scope,)
        )}
        links_by_path = {}
        for path in paths:
            if stop is not None and stop.is_set():
                return links_by_path
            name = path.relative_to(self.config.root).as_posix()
            previous = old.pop(name, None)
            try:
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    info = self.config.safe_visible_path(str(path)).stat()
                stamp = file_stamp(info)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("Keine reguläre Datei")
                if previous and previous[1] == stamp:
                    if previous[2]:
                        links_by_path[name] = json.loads(previous[2])
                    continue
                if max_bytes is not None and info.st_size > max_bytes:
                    metadata, texts, links = {}, (), ()
                else:
                    source = self.config.safe_visible_path(str(path))
                    metadata, texts, links = load(source)
                    if file_stamp(path.stat()) != stamp:
                        raise ValueError("Datei während der Indexierung geändert")
            except (OSError, ValueError, RuntimeError) as error:
                logging.getLogger(__name__).debug("Suchquelle %s übersprungen: %s", name, error)
                if previous:
                    self.db.execute("DELETE FROM files WHERE id = ?", (previous[0],))
                continue
            if previous:
                self.db.execute("DELETE FROM files WHERE id = ?", (previous[0],))
            key = self.db.execute(
                "INSERT INTO files(scope, path, stamp, metadata, links) VALUES (?, ?, ?, ?, ?)",
                (scope, name, stamp, json.dumps(metadata), json.dumps(links) if links else None),
            ).lastrowid
            self.db.executemany(
                "INSERT INTO texts(file_id, page, body, normalized) VALUES (?, ?, ?, ?)",
                ((key, page, body, normalize(body)) for page, body in texts),
            )
            if links:
                links_by_path[name] = links
        if old:
            self.db.executemany("DELETE FROM files WHERE id = ?", ((record[0],) for record in old.values()))
        return links_by_path

    def hits(self, scopes, terms):
        query = """
            SELECT f.path, f.metadata, t.page, t.body, t.normalized
            FROM texts AS t JOIN files AS f ON f.id = t.file_id
        """
        # Restrict the SQL expression size regardless of input length.
        indexed_terms = terms[:32]
        remaining_terms = terms[32:]
        long_terms = [term for term in indexed_terms if len(term) >= 3 and "\0" not in term]
        args = []
        clauses = ["f.scope IN (" + ", ".join("?" for _ in scopes) + ")"]
        args.extend(scopes)
        if self.fts and long_terms:
            query += " JOIN trigrams ON trigrams.rowid = t.id"
            clauses.append("trigrams MATCH ?")
            args.append(" AND ".join('"' + term.replace('"', '""') + '"' for term in long_terms))
        clauses.extend("instr(t.normalized, ?) > 0" for _ in indexed_terms)
        args.extend(indexed_terms)
        for name, metadata, page, body, normalized in self.db.execute(query + " WHERE " + " AND ".join(clauses), args):
            if all(term in normalized for term in remaining_terms):
                yield name, json.loads(metadata), page, body, normalized

    def metadata(self, scope, path):
        row = self.db.execute("SELECT metadata FROM files WHERE scope = ? AND path = ?", (scope, path)).fetchone()
        return json.loads(row[0]) if row else {}
