from __future__ import annotations

import json
import os
import re
import sys
import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from material_ui.assets import parse_tags, tag_path_matches
from material_ui.errors import InvalidInput

MAX_SEARCH_BYTES = 2 * 1024 * 1024
MAX_RESULTS = 50
MAX_INDEX_BYTES = 64 * 1024 * 1024
SNIPPET_RADIUS = 60
MAX_PROVIDERS = 16
SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


def normalize_query(value: str) -> str:
    value = (
        value.lower()
        .casefold()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))


def query_terms(query: str) -> list[str]:
    return [term for term in normalize_query(query).split() if len(term) >= 2]


def deck_texts(scene: Any) -> str:
    """Textelemente einer Excalidraw-Szene als durchsuchbarer Text (eine Zeile je Element)."""
    if not isinstance(scene, dict) or not isinstance(scene.get("elements"), list):
        return ""
    lines = []
    for element in scene["elements"]:
        if isinstance(element, dict) and element.get("type") == "text" and not element.get("isDeleted") and isinstance(element.get("text"), str):
            lines.append(element["text"])
    return "\n".join(lines)


@dataclass
class IndexedSource:
    fingerprint: tuple[int, int, int, int]
    entry: dict[str, Any]
    text: str
    normalized: str
    pdf_candidates: tuple[Path, ...] = ()
    deck_candidates: tuple[Path, ...] = ()

    @property
    def size(self) -> int:
        return sys.getsizeof(self.text) + sys.getsizeof(self.normalized)


class SearchService:
    """Incremental, bounded in-memory index; external changes are checked on each query."""

    def __init__(self, config, documents) -> None:
        self.config = config
        self.documents = documents
        self.lock = threading.RLock()
        self.index: OrderedDict[Path, IndexedSource] = OrderedDict()
        self.index_bytes = 0
        # Such-Provider anderer Plugins (ueber ctx.search.register): source_id -> (name, provider)
        self.providers: OrderedDict[str, tuple[str, Callable[[str, dict[str, Any]], list[dict[str, Any]]]]] = OrderedDict()

    # -- Such-Provider (Plugin-Schnittstelle) ------------------------------------------------------

    def register_provider(self, provider, source_id: str, name: str = "") -> Callable[[], None]:
        """Registriert einen externen Such-Provider; liefert eine idempotente Abmeldefunktion.

        Der Provider erhaelt (query, filters) und liefert eine Liste von Treffern (je Dict mit
        mindestens ``path`` und ``title``). Fehler einer Quelle werden isoliert und landen als
        ``sourceErrors`` in der Antwort, ohne die Kernsuche zu beeintraechtigen.
        """
        if not callable(provider):
            raise ValueError("Provider muss aufrufbar sein.")
        if not isinstance(source_id, str) or not SOURCE_ID_PATTERN.match(source_id):
            raise ValueError("Ungueltige source_id (nur [a-z0-9-], max. 32 Zeichen).")
        if not isinstance(name, str):
            raise ValueError("Ungueltiger Quellenname.")
        with self.lock:
            if len(self.providers) >= MAX_PROVIDERS and source_id not in self.providers:
                raise ValueError("Zu viele Such-Quellen registriert.")
            self.providers[source_id] = (name or source_id, provider)

        def unregister() -> None:
            with self.lock:
                self.providers.pop(source_id, None)

        return unregister

    def provider_sources(self) -> list[tuple[str, str]]:
        with self.lock:
            return [(source_id, name) for source_id, (name, _) in self.providers.items()]

    def _provider_result(self, entry: Any, source_id: str) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            return None
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            return None
        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            title = PurePosixPath(path).stem
        score = entry.get("score", 0)
        if type(score) is not int or score < 0:
            score = 0
        tags = entry.get("tags")
        line = entry.get("line")
        pdf = entry.get("pdf")
        snippet = entry.get("snippet")
        source_path = entry.get("source_path")
        mtime = entry.get("mtime", 0)
        return {
            "path": path.strip(),
            "title": title.strip()[:200],
            "kind": str(entry.get("kind") or ""),
            "subject": str(entry.get("subject") or ""),
            "grade": str(entry.get("grade") or ""),
            "tags": [str(tag) for tag in tags] if isinstance(tags, list) else [],
            "area": str(entry.get("area") or ""),
            "solution": bool(entry.get("solution")),
            "pdf": pdf if isinstance(pdf, str) else None,
            "mtime": mtime if isinstance(mtime, (int, float)) and not isinstance(mtime, bool) else 0,
            "source_path": source_path if isinstance(source_path, str) else None,
            "score": score,
            "line": line if type(line) is int else None,
            "snippet": (snippet if isinstance(snippet, str) else "")[:500],
            "source": source_id,
        }

    def _run_providers(self, query: str, filters: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        with self.lock:
            providers = list(self.providers.items())
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for source_id, (name, provider) in providers:
            try:
                raw = provider(query, filters) or []
                if not isinstance(raw, list):
                    raise ValueError("Provider lieferte keine Liste.")
                for entry in raw[:MAX_RESULTS]:
                    item = self._provider_result(entry, source_id)
                    if item is not None:
                        results.append(item)
            except Exception as error:  # Fehler einer Quelle isolieren, Kernsuche bleibt nutzbar
                errors.append({"source": source_id, "name": name, "message": str(error)[:240]})
        return results, errors

    def search_with_sources(self, query: str, **filters) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Wie ``search``, liefert zusaetzlich die Fehler der registrierten Such-Quellen."""
        errors: list[dict[str, str]] = []
        results = self.search(query, _provider_errors=errors, **filters)
        return results, errors

    @staticmethod
    def fingerprint(path: Path) -> tuple[int, int, int, int]:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino

    def indexed_source(self, path: Path) -> IndexedSource | None:
        with self.lock:
            return self._indexed_source(path)

    def _indexed_source(self, path: Path) -> IndexedSource | None:
        try:
            path = self.config.safe_visible_path(str(path))
            fingerprint = self.fingerprint(path)
            if fingerprint[2] > MAX_SEARCH_BYTES:
                self.discard(path)
                return None
            cached = self.index.get(path)
            if cached and cached.fingerprint == fingerprint:
                self.index.move_to_end(path)
                return cached
            text = self.documents.catalog.read_text(path)
            candidates, decks = (), ()
            if path.suffix == ".excalidraw":
                text = deck_texts(json.loads(text))
                entry = self.deck_entry(path)
            else:
                entry, candidates, decks = self.documents.source_details(path, text=text, expected_fingerprint=fingerprint)
            # Do not cache text and metadata from different filesystem versions.
            if self.fingerprint(path) != fingerprint:
                self.discard(path)
                return None
            item = IndexedSource(fingerprint, entry, text, normalize_query(text), candidates, decks)
            self.discard(path)
            self.index[path] = item
            self.index_bytes += item.size
            while self.index_bytes > MAX_INDEX_BYTES:
                oldest = next(iter(self.index))
                self.discard(oldest)
            return item
        except (OSError, ValueError):
            self.discard(path)
            return None

    def discard(self, path: Path) -> None:
        previous = self.index.pop(path, None)
        if previous:
            self.index_bytes -= previous.size

    def search(self, query: str, subject: str = "", grade: str = "", kind: str = "", tags: str = "",
               pdf: str = "", area: str = "", solution: bool = False, sort: str = "relevance",
               _provider_errors: list | None = None) -> list[dict[str, Any]]:
        terms = query_terms(query)
        required_tags = parse_tags(tags)
        if not terms and not (subject or grade or kind or required_tags or pdf or area or solution):
            raise InvalidInput("Bitte einen Suchbegriff oder einen Filter angeben.")
        if pdf not in {"", "with-pdf", "without-pdf"} or sort not in {"relevance", "title", "recent"}:
            raise InvalidInput("Unbekannter Suchfilter oder Sortierung.")
        results = []
        source_paths = self.documents.qmd_sources()
        linked_decks: dict[Path, dict[str, Any]] = {}
        live_paths = set()
        for path in source_paths:
            item = self.indexed_source(path)
            if item is None:
                continue
            live_paths.add(path.resolve())
            entry = dict(item.entry)
            # Generated decks are addressed directly, never by walking build/.
            relative = path.relative_to(self.config.root)
            candidates = [self.config.root / "build" / "artefakte" / relative.with_suffix(".excalidraw")]
            for candidate in item.deck_candidates:
                try:
                    candidates.append(self.config.safe_visible_path(str(candidate)))
                except InvalidInput:
                    pass
            for deck in candidates:
                if deck.is_file():
                    linked_decks[deck] = entry
            self.append_match(results, path, item, entry, terms, subject, grade, kind, required_tags, pdf, area, solution)
        for path in sorted(set(self.deck_sources()) | linked_decks.keys()):
            item = self.indexed_source(path)
            if item is None:
                continue
            live_paths.add(path.resolve())
            entry = dict(item.entry)
            owner = linked_decks.get(path)
            if owner:
                entry.update({key: owner.get(key, "") for key in ("subject", "grade", "area", "tags", "solution")})
                entry["source_path"] = owner["path"]
            self.append_match(results, path, item, entry, terms, subject, grade, kind, required_tags, pdf, area, solution)
        with self.lock:
            for path in list(self.index):
                if path not in live_paths:
                    self.discard(path)
        # Treffer registrierter Such-Quellen (Plugins) vor dem Sortieren und Limit einhaengen.
        filters = {"subject": subject, "grade": grade, "kind": kind, "tags": tags,
                   "pdf": pdf, "area": area, "solution": solution, "sort": sort}
        provider_results, errors = self._run_providers(query, filters)
        if _provider_errors is not None:
            _provider_errors.extend(errors)
        results.extend(provider_results)
        if sort == "recent":
            results.sort(key=lambda item: (-item["mtime"], -item["score"], item["path"]))
        elif sort == "title":
            results.sort(key=lambda item: (normalize_query(item["title"]), -item["score"], item["path"]))
        else:
            results.sort(key=lambda item: (-item["score"], item["path"]))
        # All candidates, including decks, participate before the result limit.
        return results[:MAX_RESULTS]

    def append_match(self, results, path, item, entry, terms, subject, grade, kind, tags, pdf, area, solution):
        if any(value and entry.get(key) != value for key, value in (("subject", subject), ("grade", grade), ("kind", kind), ("area", area))):
            return
        if solution and not entry.get("solution"):
            return
        if tags and not all(any(tag_path_matches(tag, scope) for tag in entry.get("tags", [])) for scope in tags):
            return
        if not all(term in item.normalized for term in terms):
            return
        if path.suffix == ".qmd":
            try:
                entry["pdf"] = self.config.relative(next((candidate for candidate in item.pdf_candidates if candidate.suffix.lower() == ".pdf" and candidate.is_file()), None))
            except (OSError, ValueError):
                return
        if (pdf == "with-pdf" and not entry.get("pdf")) or (pdf == "without-pdf" and entry.get("pdf")):
            return
        line, snippet = self.first_match(item.text, terms) if terms else (None, "")
        score = sum(item.normalized.count(term) for term in terms)
        results.append(self.result(entry, path, score, snippet, line))

    def deck_sources(self) -> list[Path]:
        return self.documents.catalog.sources(".excalidraw")

    def deck_entry(self, path: Path) -> dict[str, Any]:
        relative = self.config.relative(path) or ""
        parts = relative.split("/")
        return {
            "path": relative,
            "title": path.stem,
            "kind": "Deck",
            "area": parts[0] if parts else "",
            "subject": parts[1] if len(parts) > 1 else "",
            "grade": self.documents.grade_part(parts),
            "mtime": path.stat().st_mtime,
        }

    def first_match(self, text: str, terms: list[str]) -> tuple[int | None, str]:
        for number, line in enumerate(text.splitlines(), start=1):
            normalized = normalize_query(line)
            if any(term in normalized for term in terms):
                return number, self.snippet(line, terms)
        return None, ""

    @staticmethod
    def snippet(line: str, terms: list[str]) -> str:
        clean = line.strip()
        normalized = normalize_query(clean)
        index = min((normalized.find(term) for term in terms if term in normalized), default=-1)
        if index < 0 or len(clean) <= SNIPPET_RADIUS * 2:
            return clean[:SNIPPET_RADIUS * 2]
        # Normalization expands umlauts and ß; translate back to source offsets.
        normalized_offset = 0
        for source_offset, character in enumerate(clean):
            normalized_offset += len(normalize_query(character))
            if normalized_offset > index:
                index = source_offset
                break
        start = max(0, index - SNIPPET_RADIUS)
        return ("…" if start else "") + clean[start:start + SNIPPET_RADIUS * 2].strip() + "…"

    def result(self, entry: dict[str, Any], path: Path, score: int, snippet: str | None, line: int | None = None) -> dict[str, Any]:
        return {
            "path": entry.get("path") or self.config.relative(path),
            "title": entry.get("title") or path.stem,
            "kind": entry.get("kind", ""),
            "subject": entry.get("subject", ""),
            "grade": entry.get("grade", ""),
            "tags": list(entry.get("tags", [])),
            "area": entry.get("area", ""),
            "solution": bool(entry.get("solution")),
            "pdf": entry.get("pdf"),
            "mtime": entry.get("mtime", 0),
            "source_path": entry.get("source_path"),
            "score": score,
            "line": line,
            "snippet": snippet or "",
        }
