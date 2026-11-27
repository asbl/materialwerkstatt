from __future__ import annotations

import json
import re
import threading
import unicodedata
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from material_core.pdf_sources import manifest_pfad, page_texts, read_manifest
from material_ui.assets import parse_tags, tag_path_matches
from material_ui.catalog import fingerprint
from material_ui.errors import InvalidInput
from material_ui.search_index import SearchIndex, file_stamp

MAX_SEARCH_BYTES = 2 * 1024 * 1024
MAX_RESULTS = 50
SNIPPET_RADIUS = 60
MAX_PROVIDERS = 16
PDF_SOURCE = "original-pdf"
PDF_SOURCE_NAME = "Original-PDFs"
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


class SearchService:
    def __init__(self, config, documents) -> None:
        self.config = config
        self.documents = documents
        self.lock = threading.RLock()
        self.index = SearchIndex(config)
        self.pdf_manifest = manifest_pfad(config.root)
        self.pdf_stamp = None
        self.pdf_paths = ()
        self.providers: OrderedDict[str, tuple[str, Callable[[str, dict[str, Any]], list[dict[str, Any]]]]] = OrderedDict()

    def close(self):
        with self.lock:
            self.index.close()

    def warm_documents(self, stop):
        with self.lock:
            if not stop.is_set():
                with self.index.transaction():
                    self.refresh_documents(stop=stop)

    # -- Such-Provider (Plugin-Schnittstelle) ------------------------------------------------------

    def register_provider(self, provider, source_id: str, name: str = "") -> Callable[[], None]:
        """Registriert einen externen Such-Provider; liefert eine idempotente Abmeldefunktion.

        Der Provider erhaelt (query, filters) und liefert eine Liste von Treffern (je Dict mit
        mindestens ``path`` und ``title``). Fehler einer Quelle werden isoliert und landen als
        ``sourceErrors`` in der Antwort, ohne die Kernsuche zu beeintraechtigen.
        """
        if not callable(provider):
            raise ValueError("Provider muss aufrufbar sein.")
        if not isinstance(source_id, str) or not SOURCE_ID_PATTERN.fullmatch(source_id):
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

    def active_providers(self):
        with self.lock:
            providers = self.providers.copy()
        if self.pdf_manifest.is_file():
            providers.setdefault(PDF_SOURCE, (PDF_SOURCE_NAME, self.search_pdfs))
        return providers

    def provider_sources(self) -> list[tuple[str, str]]:
        return [(source_id, name) for source_id, (name, _) in self.active_providers().items()]

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
        page = entry.get("page")
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
            **({"page": page} if type(page) is int and page > 0 else {}),
        }

    def _run_providers(self, query: str, filters: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for source_id, (name, provider) in self.active_providers().items():
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

    def load_source(self, path):
        stamp = fingerprint(path)
        text = self.documents.catalog.read_text(path)
        entry, pdfs, decks = self.documents.source_details(path, text=text, expected_fingerprint=stamp)
        entry["pdf_candidates"] = [str(candidate.relative_to(self.config.root)) for candidate in pdfs]
        return entry, [(0, text)], [str(candidate.relative_to(self.config.root)) for candidate in decks]

    def load_deck(self, path):
        text = deck_texts(json.loads(self.documents.catalog.read_text(path)))
        return self.deck_entry(path), [(0, text)], ()

    def refresh_documents(self, *, stop=None):
        root = self.config.root
        sources = self.documents.qmd_sources()
        links = self.index.refresh("document", sources, self.load_source, normalize_query,
                                   max_bytes=MAX_SEARCH_BYTES, stop=stop)
        owners = {}
        if stop is not None and stop.is_set():
            return owners
        generated = root / "build" / "artefakte"
        if generated.is_dir():
            folders = {}
            for source in sources:
                relative = source.relative_to(root)
                folder = generated / relative.parent
                if folder not in folders:
                    folders[folder] = folder.is_dir()
                if folders[folder]:
                    deck = folder / source.with_suffix(".excalidraw").name
                    if deck.is_file():
                        owners[deck] = relative.as_posix()
        for source, candidates in links.items():
            for candidate in candidates:
                deck = root / candidate
                if deck.is_file():
                    owners[deck] = source
        decks = sorted(set(self.documents.catalog.sources(".excalidraw")) | owners.keys())
        self.index.refresh("deck", decks, self.load_deck, normalize_query,
                           max_bytes=MAX_SEARCH_BYTES, stop=stop)
        return owners

    def registered_pdfs(self):
        base = self.pdf_manifest.parent
        manifest = self.config.safe_visible_path(str(self.pdf_manifest))
        if not manifest.is_relative_to(base):
            raise InvalidInput("Erschließungsmanifest liegt außerhalb von wissen/.")
        stamp = file_stamp(manifest.stat())
        if self.pdf_stamp != stamp:
            paths = set()
            for record in read_manifest(manifest)["eintraege"].values():
                relative = record.get("pfad") if isinstance(record, dict) else None
                if not isinstance(relative, str):
                    continue
                path = Path(relative)
                if path.is_absolute() or any(part.startswith(".") for part in path.parts):
                    continue
                if path.suffix.lower() == ".pdf":
                    paths.add(base / path)
            self.pdf_paths = sorted(paths)
            self.pdf_stamp = stamp
        return self.pdf_paths

    def load_pdf(self, path):
        base = self.pdf_manifest.parent
        if not path.is_relative_to(base) or path.suffix.lower() != ".pdf":
            raise ValueError("Original-PDF liegt außerhalb von wissen/.")
        parts = path.relative_to(base).parts
        grade = self.documents.grade_part(parts)
        subject = parts[1] if parts[0] == "arbeitsblatt" and grade and len(parts) > 3 else parts[0]
        name = path.relative_to(self.config.root).as_posix()
        title = path.stem.replace("_", " ").replace("-", " ")
        entry = {"path": name, "pdf": name, "title": title, "kind": "Original-PDF",
                 "area": "wissen", "subject": subject, "grade": grade, "mtime": path.stat().st_mtime}
        return entry, [(0, title), *enumerate(page_texts(path), start=1)], ()

    def search_pdfs(self, query, filters):
        terms = query_terms(query)
        if filters["pdf"] == "without-pdf" or filters["solution"] or filters["tags"]:
            return []
        if filters["area"] not in ("", "wissen") or filters["kind"] not in ("", "Original-PDF"):
            return []
        best = {}
        base = self.pdf_manifest.parent
        with self.lock, self.index.transaction():
            self.index.refresh("pdf", self.registered_pdfs(), self.load_pdf, normalize_query)
            for name, entry, page, body, normalized in self.index.hits(("pdf",), terms):
                if any(filters[key] and entry[key] != filters[key] for key in ("subject", "grade")):
                    continue
                prev = best.get(entry["path"])
                if prev and not terms:
                    continue
                try:
                    path = self.config.safe_visible_path(name)
                except (OSError, ValueError):
                    continue
                if not path.is_relative_to(base) or path.suffix.lower() != ".pdf":
                    continue
                score = sum(normalized.count(term) for term in terms)
                if prev and (prev["score"], bool(prev["snippet"]), -prev["page"]) >= (score, page > 0, -(page or 1)):
                    continue
                best[entry["path"]] = {
                    **entry, "page": page or 1, "score": score,
                    "snippet": self.snippet(body, terms) if page and terms else "",
                }
        return self.sort_results(list(best.values()), filters["sort"])[:MAX_RESULTS]

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
        filters = {"subject": subject, "grade": grade, "kind": kind, "tags": tags,
                   "pdf": pdf, "area": area, "solution": solution, "sort": sort}
        with self.lock, self.index.transaction():
            owners = self.refresh_documents()
            for name, entry, _, body, normalized in self.index.hits(("document", "deck"), terms):
                path = self.config.root / name
                owner = owners.get(path)
                if owner:
                    source = self.index.metadata("document", owner)
                    entry.update({key: source.get(key, "") for key in ("subject", "grade", "area", "tags", "solution")})
                    entry["source_path"] = source.get("path")
                if not self.matches_facets(entry, filters, required_tags):
                    continue
                try:
                    path = self.config.safe_visible_path(name)
                    entry["pdf"] = self.current_pdf(entry) if path.suffix == ".qmd" else None
                except (OSError, ValueError):
                    continue
                if (pdf == "with-pdf" and not entry["pdf"]) or (pdf == "without-pdf" and entry["pdf"]):
                    continue
                line, snippet = self.first_match(body, terms) if terms else (None, "")
                score = sum(normalized.count(term) for term in terms)
                results.append(self.result(entry, path, score, snippet, line))
        # Treffer registrierter Such-Quellen (Plugins) vor dem Sortieren und Limit einhaengen.
        provider_results, errors = self._run_providers(query, filters)
        if _provider_errors is not None:
            _provider_errors.extend(errors)
        results.extend(provider_results)
        return self.sort_results(results, sort)[:MAX_RESULTS]

    @staticmethod
    def sort_results(results, sort):
        if sort == "recent":
            results.sort(key=lambda item: (-item["mtime"], -item["score"], item["path"]))
        elif sort == "title":
            results.sort(key=lambda item: (normalize_query(item["title"]), -item["score"], item["path"]))
        else:
            results.sort(key=lambda item: (-item["score"], item["path"]))
        return results

    @staticmethod
    def matches_facets(entry, filters, tags):
        return (
            all(not filters[key] or entry.get(key) == filters[key] for key in ("subject", "grade", "kind", "area"))
            and (not filters["solution"] or entry.get("solution"))
            and all(any(tag_path_matches(tag, scope) for tag in entry.get("tags", [])) for scope in tags)
        )

    def current_pdf(self, entry):
        for name in entry.get("pdf_candidates", ()):
            path = self.config.root / name
            if path.suffix.lower() == ".pdf" and path.is_file():
                return self.config.relative(self.config.safe_visible_path(name))
        return None

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
