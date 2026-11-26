"""Stdio-MCP-Server, der die Chat-Werkzeuge fuer Claude/Codex/Vibe exportiert.

Jede Provider-CLI startet diesen Server selbst als eigenen Subprozess (siehe
``chat/providers.py``). Das bedeutet: kein gemeinsamer Python-Prozess mit der
laufenden Material-UI, deshalb kommen Repo-Root und Basis-URL der laufenden
App ueber Umgebungsvariablen statt per Dependency-Injection.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import tools
from material_ui.config import AppConfig
from material_ui.errors import InvalidInput

ROOT_ENV = "MATERIAL_UI_ROOT"
BASE_URL_ENV = "MATERIAL_UI_BASE_URL"
DEFAULT_BASE_URL = "http://127.0.0.1:8765"

server = MCPServer("material-wissen")


def _config() -> AppConfig:
    root = os.environ.get(ROOT_ENV)
    if not root:
        raise RuntimeError(f"{ROOT_ENV} ist nicht gesetzt.")
    return AppConfig(Path(root))


def _base_url() -> str:
    return os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL)


@server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))
def search_wissen(query: str, limit: int = tools.DEFAULT_SEARCH_LIMIT) -> list[dict]:
    """Durchsucht die erschlossenen PDFs der fachdidaktischen Wissensbasis (wissen/) nach einem Begriff."""
    try:
        return tools.search_wissen(_config(), query, limit)
    except InvalidInput as error:
        raise ToolError(str(error)) from error


@server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))
def search_unterricht(query: str, limit: int = tools.DEFAULT_SEARCH_LIMIT) -> list[dict]:
    """Durchsucht die Unterrichtsmaterialien (QMD-Quellen und Excalidraw-Decks) nach einem Begriff."""
    try:
        return tools.search_unterricht(_base_url(), query, limit)
    except httpx.HTTPError as error:
        raise ToolError(f"Suche nicht erreichbar: {error}") from error


@server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))
def read_file(path: str, max_bytes: int = tools.MAX_READ_BYTES) -> dict:
    """Liest den Textinhalt einer Datei unter wissen/ oder unterricht/ (projektrelativer Pfad)."""
    try:
        return tools.read_file(_config(), path, max_bytes)
    except InvalidInput as error:
        raise ToolError(str(error)) from error


@server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))
def propose_document_edit(path: str, old_text: str, new_text: str) -> dict:
    """Schlaegt einen exakten Textersatz im aktuellen Editor vor. Die UI zeigt vorher/nachher
    und uebernimmt erst auf Klick. old_text muss im aktuellen Editor genau einmal vorkommen.
    Nutze mehrere Aufrufe fuer unabhaengige Abschnitte. Schreibt selbst keine Datei."""
    try:
        tools.safe_knowledge_path(_config(), path)
        if not old_text or old_text == new_text:
            raise InvalidInput("Ein nichtleerer Abschnitt und eine Änderung sind erforderlich.")
    except InvalidInput as error:
        raise ToolError(str(error)) from error
    return {"status": "proposed", "path": path}


@server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))
def check_document(path: str, text: str) -> dict:
    """Prueft Text gegen die Material-Konventionen (Aufgabenkennzeichnung, Ueberschriften, Untertitel,
    Bearbeitungshinweise u. a.) und liefert die Befunde. `text` ist das ganze Dokument nach deiner Aenderung
    (oder der neue Abschnitt; Kopf-Regeln wie Untertitel greifen nur bei vollstaendigem Text). Rufe das vor
    jedem Aenderungsvorschlag auf und behebe die Befunde, soweit sie nicht ausdruecklich gewuenscht sind."""
    try:
        return tools.check_document(_config(), path, text)
    except InvalidInput as error:
        raise ToolError(str(error)) from error


@server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))
def read_unit(path: str) -> dict:
    """Liefert die Unterrichtseinheit (einheit.yaml und Dateiliste) zu einem Pfad unter unterricht/ -
    Ziel, Klasse, Thema, Einsaetze. Nutze das, wenn Aufgaben zum Rahmen der Einheit passen sollen."""
    try:
        return tools.read_unit(_config(), path)
    except InvalidInput as error:
        raise ToolError(str(error)) from error


@server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))
def list_templates() -> dict:
    """Listet die verfuegbaren Dokument- und Folienvorlagen der Material-UI (Name, Art, Beschreibung)."""
    try:
        return tools.list_templates(_base_url())
    except httpx.HTTPError as error:
        raise ToolError(f"Vorlagen nicht erreichbar: {error}") from error


@server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))
def propose_new_document(path: str, text: str) -> dict:
    """Schlaegt eine NEUE Datei unter unterricht/ vor (.qmd, .md, .tex; z. B. die Loesung zu einem Blatt).
    Die UI zeigt Inhalt und Regelhinweise und legt die Datei erst auf Klick an. Schreibt selbst nichts;
    existiert der Pfad schon, wird der Vorschlag abgelehnt."""
    try:
        relative = tools.validate_new_document(_config(), path, text)
    except FileExistsError as error:
        raise ToolError(str(error)) from error
    except InvalidInput as error:
        raise ToolError(str(error)) from error
    return {"status": "proposed", "path": relative, "findings": tools.convention_findings(relative, text)}


@server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False))
def show_task_image(token: str) -> Image:
    """Zeigt das Bild einer einzelnen Aufgabe (z. B. Schulbuch-Screenshot), die per Einfuegen aus
    der Zwischenablage als Code importiert werden soll. `token` ist der Staging-Token der Material-UI,
    kein freier Dateipfad. Das Bild holt der Server per HTTP von der laufenden App (Route des
    importe-Plugins), damit dieser Subprozess kein fremdes Plugin importieren muss."""
    try:
        response = httpx.get(f"{_base_url().rstrip('/')}/api/document/import/task-image/{token}/image", timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ToolError(f"Aufgabenbild nicht erreichbar (importe-Plugin aktiv?): {error}") from error
    media = response.headers.get("Content-Type", "image/png").split("/")[-1].split(";")[0] or "png"
    return Image(data=response.content, format=media)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
