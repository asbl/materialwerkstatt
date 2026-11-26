"""Lesewerkzeuge fuer das Chat-Panel: Suche in der Wissensbasis und Dateizugriff.

Alle drei Tools sind reine Funktionen ohne Subprozess- oder Netzwerkzugriff und
bewusst auf Lesezugriff unter ``wissen/`` und ``unterricht/`` beschraenkt -
``safe_knowledge_path`` ist die einzige Stelle, die Pfade fuer das Chat-Panel
entgegennimmt.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

import material_suche
from material_ui.config import AppConfig
from material_ui.errors import InvalidInput

KNOWLEDGE_ROOTS = {"wissen", "unterricht"}
MAX_READ_BYTES = 20_000
DEFAULT_SEARCH_LIMIT = 10

_index_cache: dict[Path, tuple[float, dict]] = {}


def _load_index_cached(root: Path) -> dict | None:
    """Wie material_suche.lade_index, aber ueber die Dauer einer Chat-Sitzung (ein MCP-Server-
    Prozess pro Sitzung) gecacht - mtime-basiert, damit ein neu gebauter Index sofort greift."""
    index_path = material_suche.index_pfad(root)
    try:
        mtime = index_path.stat().st_mtime
    except OSError:
        return None
    cached = _index_cache.get(root)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    index = material_suche.lade_index(root)
    if index is not None:
        _index_cache[root] = (mtime, index)
    return index


def safe_knowledge_path(config: AppConfig, value: str) -> Path:
    """Wie ``AppConfig.safe_visible_path``, zusaetzlich auf wissen/+unterricht/ beschraenkt."""
    candidate = config.safe_visible_path(value)
    parts = candidate.relative_to(config.root).parts
    if not parts or parts[0] not in KNOWLEDGE_ROOTS:
        raise InvalidInput("Pfad muss unter wissen/ oder unterricht/ liegen.")
    return candidate


def search_wissen(config: AppConfig, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict[str, Any]]:
    index = _load_index_cached(config.root)
    if index is None:
        raise InvalidInput(
            "Kein Wissensindex gefunden. Bitte zuerst `inv material-index` ausführen."
        )
    treffer = material_suche.suche(index, query, limit=limit)
    return [{"pfad": t.pfad, "seite": t.seite, "ausschnitt": t.ausschnitt} for t in treffer]


def search_unterricht(base_url: str, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict[str, Any]]:
    """Fragt die bereits laufende Material-UI (``/api/search``) ab statt den Such-Stack zu duplizieren.

    Laeuft als eigener Prozess (vom Chat-Provider-Subprozess gestartet), daher kein
    direkter Zugriff auf ``SearchService`` moeglich - die laufende App ist die einzige
    Instanz, die ``DocumentService``/``BuildService`` bereits aufgebaut hat.
    """
    response = httpx.get(f"{base_url.rstrip('/')}/api/search", params={"q": query}, timeout=10.0)
    response.raise_for_status()
    return response.json().get("results", [])[:limit]


def read_file(config: AppConfig, path: str, max_bytes: int = MAX_READ_BYTES) -> dict[str, Any]:
    target = safe_knowledge_path(config, path)
    if not target.is_file():
        raise InvalidInput(f"Datei nicht gefunden: {path}")
    # Nur bis max_bytes (+1 zur Truncation-Erkennung) von der Platte lesen, statt die ganze
    # Datei in den Speicher zu laden - relevant bei sehr grossen Dateien unter wissen/.
    with target.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    try:
        text = data[:max_bytes].decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidInput("Datei enthält keinen lesbaren Text (kein UTF-8).") from None
    return {"path": config.relative(target), "text": text, "truncated": truncated}


# -- Konventionspruefung, Einheiten, Vorlagen, neue Dateien ----------------------------------------

EDITABLE_SUFFIXES = {".qmd", ".md", ".tex"}
MAX_DOCUMENT_BYTES = 200_000
UNIT_FILE = "einheit.yaml"
MAX_FINDINGS = 25


def convention_findings(path: str, text: str, limit: int = MAX_FINDINGS) -> list[dict[str, Any]]:
    """Mechanische Konventionspruefung (``material_core.conventions``) auf beliebigem Text.

    Regeln, die den Dokumentkopf betreffen (z. B. Untertitel), greifen nur bei vollstaendigem Text."""
    from material_core.conventions import check_conventions, check_file_name, position

    findings = [*check_file_name(path), *check_conventions(path, text)]
    result = []
    for finding in findings[:limit]:
        line, column = position(text, finding.offset) if finding.offset else (1, 1)
        result.append({
            "code": finding.code, "level": finding.level, "title": finding.title,
            "detail": finding.detail, "line": line, "column": column,
        })
    return result


def new_findings(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nur Befunde, die durch eine Aenderung hinzukommen (je Regel und Titel gezaehlt)."""
    remaining = Counter((item["code"], item["title"]) for item in before)
    added = []
    for item in after:
        key = (item["code"], item["title"])
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            added.append(item)
    return added


def _editable_target(config: AppConfig, path: str) -> Path:
    target = safe_knowledge_path(config, path)
    if target.suffix.lower() not in EDITABLE_SUFFIXES:
        raise InvalidInput("Dieser Dateityp wird nicht geprüft (nur .qmd, .md, .tex).")
    return target


def check_document(config: AppConfig, path: str, text: str) -> dict[str, Any]:
    target = _editable_target(config, path)
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise InvalidInput("Text fehlt oder ist zu groß (max. 200 KB).")
    relative = config.relative(target)
    findings = convention_findings(relative, text)
    return {"path": relative, "findings": findings,
            "summary": "Keine Regelverstöße gefunden." if not findings else f"{len(findings)} Hinweis(e) zu den Projektregeln."}


def unit_folder(config: AppConfig, path: str) -> Path | None:
    """Naechster Ordner oberhalb von ``path`` (unter unterricht/) mit einheit.yaml."""
    target = safe_knowledge_path(config, path)
    base = config.root / "unterricht"
    current = target if target.is_dir() else target.parent
    while current != base and current.is_relative_to(base):
        if (current / UNIT_FILE).is_file():
            return current
        current = current.parent
    return None


def read_unit(config: AppConfig, path: str) -> dict[str, Any]:
    folder = unit_folder(config, path)
    if folder is None:
        raise InvalidInput("Für diesen Pfad wurde keine Einheit (einheit.yaml) gefunden.")
    data = (folder / UNIT_FILE).read_bytes()[:MAX_READ_BYTES + 1]
    files = sorted(
        entry.name + ("/" if entry.is_dir() else "")
        for entry in folder.iterdir()
        if not entry.name.startswith(".") and entry.name != UNIT_FILE
    )[:60]
    return {
        "unit_path": config.relative(folder),
        "einheit_yaml": data[:MAX_READ_BYTES].decode("utf-8", errors="replace"),
        "truncated": len(data) > MAX_READ_BYTES,
        "files": files,
    }


_TEMPLATE_KEYS = ("id", "name", "title", "label", "path", "kind", "description", "design")


def _trim_template(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    trimmed = {key: entry[key] for key in _TEMPLATE_KEYS if isinstance(entry.get(key), (str, int, bool))}
    return trimmed or None


def list_templates(base_url: str) -> dict[str, list[dict[str, Any]]]:
    """Vorlagenkatalog der laufenden Material-UI (nur Name/Art/Beschreibung, begrenzt)."""
    response = httpx.get(f"{base_url.rstrip('/')}/api/templates", timeout=10.0)
    response.raise_for_status()
    data = response.json()
    result = {}
    for key in ("templates", "slideTemplates"):
        entries = [trimmed for trimmed in map(_trim_template, data.get(key) or []) if trimmed]
        result[key] = entries[:60]
    return result


def validate_new_document(config: AppConfig, path: str, text: str) -> str:
    """Prueft einen Vorschlag fuer eine NEUE Datei und liefert den normalisierten relativen Pfad."""
    target = safe_knowledge_path(config, path)
    relative = config.relative(target)
    if not relative.startswith("unterricht/"):
        raise InvalidInput("Neue Dateien dürfen nur unter unterricht/ angelegt werden.")
    if target.suffix.lower() not in EDITABLE_SUFFIXES:
        raise InvalidInput("Nur .qmd-, .md- und .tex-Dateien können angelegt werden.")
    if any(part.startswith(".") for part in PurePosixPath(relative).parts):
        raise InvalidInput("Versteckte Pfade sind nicht erlaubt.")
    if target.exists():
        raise FileExistsError(f"Die Datei existiert bereits: {relative}")
    if not isinstance(text, str) or not text.strip():
        raise InvalidInput("Der Dateiinhalt fehlt.")
    if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise InvalidInput("Der Dateiinhalt ist zu groß (max. 200 KB).")
    return relative
