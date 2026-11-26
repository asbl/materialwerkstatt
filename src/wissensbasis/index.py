from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

import yaml

from .config import CACHE, INDEX_DB, WISSEN, Fach
from .extract import cache_path, load_pages
from .notes import load_notes, load_templates
from .text import flat, is_reference_page

SCHEMA_VERSION = 2
SCHEMA = """
create table if not exists stand (dok text primary key, sha256 text, stamp integer);
create table if not exists dok (dok text primary key, fach text, pfad text, quellenart text, einheit text);
create virtual table if not exists seiten using fts5(dok unindexed, nr unindexed, lit unindexed, text, tokenize='trigram');
create virtual table if not exists notizen using fts5(art unindexed, ref unindexed, dok unindexed, titel, text, tokenize='trigram');
"""


def connect() -> sqlite3.Connection:
    CACHE.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(INDEX_DB)
    if connection.execute("pragma user_version").fetchone()[0] != SCHEMA_VERSION:
        for table in ("stand", "dok", "seiten", "notizen"):
            connection.execute(f"drop table if exists {table}")
        connection.execute(f"pragma user_version = {SCHEMA_VERSION}")
    connection.executescript(SCHEMA)
    return connection


def _remove_pages(connection: sqlite3.Connection, dok: str) -> None:
    connection.execute("delete from seiten where dok = ?", (dok,))
    connection.execute("delete from stand where dok = ?", (dok,))
    connection.execute("delete from dok where dok = ?", (dok,))


def sync(fach: Fach, manifest: dict) -> dict[str, int]:
    """Bring the search index in line with the manifest; only touch what changed."""
    counts = {"indexiert": 0, "entfernt": 0}
    connection = connect()
    with connection:
        prefix = f"{fach.name}/"
        indexed = {
            row[0]: (row[1], row[2])
            for row in connection.execute("select dok, sha256, stamp from stand where dok like ?", (prefix + "%",))
        }
        current = {f"{prefix}{doc['id']}": doc for doc in manifest["dokumente"] if doc.get("text", {}).get("status") in {"ok", "needs_ocr"}}
        for dok in set(indexed) - set(current):
            _remove_pages(connection, dok)
            counts["entfernt"] += 1
        for dok, doc in current.items():
            path = cache_path(doc["sha256"])
            if not path.exists():
                continue
            stamp = path.stat().st_mtime_ns
            if indexed.get(dok) == (doc["sha256"], stamp):
                connection.execute(
                    "update dok set pfad = ?, quellenart = ? where dok = ?", (doc["pfad"], doc["quellenart"], dok)
                )
                continue
            _remove_pages(connection, dok)
            connection.executemany(
                "insert into seiten (dok, nr, lit, text) values (?, ?, ?, ?)",
                [
                    (dok, page["p"], int(is_reference_page(page["t"])), flat(page["t"]))
                    for page in load_pages(doc["sha256"]) if page["t"].strip()
                ],
            )
            connection.execute(
                "insert into dok values (?, ?, ?, ?, ?)",
                (dok, fach.name, doc["pfad"], doc["quellenart"], doc["text"].get("einheit")),
            )
            connection.execute("insert into stand values (?, ?, ?)", (dok, doc["sha256"], stamp))
            counts["indexiert"] += 1
        # LIKE/GLOB on trigram tables is answered from the index and silently misses unindexed columns.
        connection.execute(
            "delete from notizen where rowid in (select rowid from notizen where substr(ref, 1, ?) = ?)",
            (len(prefix), prefix),
        )
        for note in [*load_notes(fach), *load_templates(fach)]:
            connection.execute(
                "insert into notizen (art, ref, dok, titel, text) values (?, ?, ?, ?, ?)",
                (note.art, f"{prefix}{note.ref}", f"{prefix}{note.dok}", note.titel, flat(f"{note.body} {_tags(note)}")),
            )
    connection.close()
    return counts


def _tags(note) -> str:
    """Tags are searchable too, so a search for 'fehlerkultur' finds cards carrying that tag."""
    values: list[str] = []
    for key in ("typ", "format", "modell", "themen", "prinzipien", "kompetenzen", "kuerzel"):
        value = note.meta.get(key) or []
        values += [value] if isinstance(value, str) else list(value)
    later = note.meta.get("nach") or []
    extra = f" Nach: {' '.join(map(str, later))}." if later else ""
    citation = f" {note.meta['zitierweise']}" if note.meta.get("zitierweise") else ""
    return "Schlagworte: " + " ".join(values) + extra + citation


def make_snippet(text: str, terms: list[str], width: int = 110) -> str:
    """Context around the first occurrence of any search term, terms marked with « »."""
    lowered = text.lower()
    positions = [lowered.find(term.lower()) for term in terms]
    positions = [position for position in positions if position >= 0]
    start = max(min(positions, default=0) - width, 0)
    excerpt = text[start:start + 2 * width + 40]
    if terms:
        pattern = "|".join(re.escape(term) for term in sorted(set(terms), key=len, reverse=True))
        excerpt = re.sub(pattern, lambda match: f"«{match.group(0)}»", excerpt, flags=re.IGNORECASE)
    return ("… " if start else "") + excerpt + (" …" if start + 2 * width + 40 < len(text) else "")


def purge_missing(names: list[str]) -> int:
    """Drop index rows of subjects whose source folder no longer exists."""
    connection = connect()
    removed = 0
    with connection:
        for (dok,) in connection.execute("select dok from stand").fetchall():
            if dok.split("/", 1)[0] not in names:
                _remove_pages(connection, dok)
                removed += 1
        for (rowid, ref) in connection.execute("select rowid, ref from notizen").fetchall():
            if ref.split("/", 1)[0] not in names:
                connection.execute("delete from notizen where rowid = ?", (rowid,))
    connection.close()
    return removed


@dataclass
class Hit:
    kind: str
    dok: str
    pfad: str
    nr: str
    text: str
    literatur: bool = False
    einheit: str = "seite"

    @property
    def fundstelle(self) -> str:
        """„S. 4“ bei PDFs, „Abschnitt 2“ bei Web- und Textquellen, „Folie 3“ bei Präsentationen."""
        if not self.nr:
            return self.kind
        return {"seite": "S.", "abschnitt": "Abschnitt", "folie": "Folie", "bild": "Bild"}.get(
            self.einheit, self.einheit.capitalize()) + f" {self.nr}"


@dataclass
class SearchResult:
    hits: list[Hit]
    skipped: list[str]
    expanded: dict[str, list[str]]


STOPWORDS = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "einen", "und", "oder", "ist", "sind", "wird",
    "von", "mit", "für", "auf", "bei", "als", "auch", "nicht", "zum", "zur", "wie", "was", "the", "and",
}
TAXONOMY_GROUPS = ("themen", "prinzipien", "kompetenzen", "formate", "modelle")


def load_synonyms() -> dict[str, set[str]]:
    """Map every known word (tag id, single-word label, listed synonym) to all words of its taxonomy entry."""
    mapping: dict[str, set[str]] = {}
    for path in sorted(WISSEN.glob("*/_config/taxonomie.yaml")):
        taxonomy = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for group in TAXONOMY_GROUPS:
            for tag, entry in (taxonomy.get(group) or {}).items():
                entry = entry or {}
                words = {tag.lower(), *(str(word).lower() for word in entry.get("synonyme") or [])}
                label = str(entry.get("label", "")).lower()
                if label and " " not in label:
                    words.add(label)
                for word in words:
                    mapping.setdefault(word, set()).update(words)
    return mapping


def split_terms(query: str) -> tuple[list[str], list[str]]:
    terms = [quoted or plain for quoted, plain in re.findall(r'"([^"]+)"|(\S+)', query)]
    usable = [term for term in terms if len(term) >= 3 and term.lower() not in STOPWORDS]
    return usable, [term for term in terms if len(term) < 3]


def expand_terms(query: str) -> tuple[list[list[str]], list[str], dict[str, list[str]]]:
    """Each query term becomes a group of alternatives (the term plus taxonomy synonyms); "quoted" terms stay exact."""
    usable, skipped = split_terms(query)
    exact = {quoted for quoted, _ in re.findall(r'"([^"]+)"|(\S+)', query) if quoted}
    synonyms = load_synonyms()
    groups: list[list[str]] = []
    expanded: dict[str, list[str]] = {}
    for term in usable:
        extra = [] if term in exact else sorted(
            word for word in synonyms.get(term.lower(), ()) if word != term.lower() and len(word) >= 3
        )
        if extra:
            expanded[term] = extra
        groups.append([term, *extra])
    return groups, skipped, expanded


def build_match(groups: list[list[str]], mode: str) -> str:
    def phrase(word: str) -> str:
        return '"' + word.replace('"', '""') + '"'

    parts = ["(" + " OR ".join(phrase(word) for word in group) + ")" if len(group) > 1 else phrase(group[0]) for group in groups]
    return f" {mode.upper()} ".join(parts)


def search(query: str, fach: str | None = None, quellenart: str | None = None, limit: int = 10,
           only_notes: bool = False, per_doc: int = 2, without_references: bool = False) -> SearchResult:
    """AND over the terms first, OR as fallback. Bibliography pages rank after all other pages."""
    groups, skipped, expanded = expand_terms(query)
    connection = connect()
    hits: list[Hit] = []
    highlight = [word for group in groups for word in group]
    if groups:
        for mode in ("and", "or"):
            hits = _run_search(connection, build_match(groups, mode), highlight, fach, quellenart, limit,
                               only_notes, per_doc, without_references)
            if hits:
                break
    connection.close()
    return SearchResult(hits, skipped, expanded)


def _run_search(connection, match, terms, fach, quellenart, limit, only_notes, per_doc, without_references) -> list[Hit]:
    hits: list[Hit] = []
    filters, params = "", []
    if fach:
        filters += " and d.fach = ?"
        params.append(fach)
    if quellenart:
        filters += " and d.quellenart = ?"
        params.append(quellenart)
    for art, ref, dok, titel, snippet in connection.execute(
        "select n.art, n.ref, n.dok, n.titel, n.text "
        "from notizen n join dok d on d.dok = n.dok where notizen match ?" + filters + " order by bm25(notizen) limit ?",
        [match, *params, limit],
    ):
        hits.append(Hit(art, dok, ref, "", f"{titel} — {make_snippet(snippet, terms)}"))
    if only_notes:
        return hits
    reference_filter = " and s.lit = 0" if without_references else ""
    counts: dict[str, int] = {}
    rows = connection.execute(
        "select s.dok, d.pfad, s.nr, s.text, s.lit, d.einheit "
        "from seiten s join dok d on d.dok = s.dok where seiten match ?" + filters + reference_filter
        + " order by s.lit, bm25(seiten) limit ?",
        [match, *params, limit * 6],
    )
    for dok, pfad, nr, snippet, literature, unit in rows:
        if counts.get(dok, 0) >= per_doc:
            continue
        counts[dok] = counts.get(dok, 0) + 1
        hits.append(Hit("seite", dok, pfad, str(nr), make_snippet(snippet, terms), bool(literature), unit or "seite"))
        if sum(counts.values()) >= limit:
            break
    return hits
