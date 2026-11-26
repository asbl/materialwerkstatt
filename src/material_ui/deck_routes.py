from __future__ import annotations

import hashlib
import json
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import NotFound, ServiceUnavailable

from material_core.filesystem import atomic_write_text
from material_ui.errors import InvalidInput
from material_ui.http import required_arg
from material_ui.storage import RevisionConflict
from material_ui.slides import annotations_path, deck_lock, frame_mapping, mapped_annotations

PRESENT_DIST = Path(__file__).resolve().parents[1] / "excalideck" / "present" / "dist"


def _revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _deck_path(config, value: str) -> Path:
    source = config.safe_path(value)
    if source.suffix != ".excalidraw" or not source.is_file():
        raise NotFound("Deck nicht gefunden.")
    if not config.is_visible(source):
        raise NotFound("Deck nicht gefunden.")
    legacy_root = config.root / 'build' / 'artefakte'
    if (source.name == 'besprechung.excalidraw' and source.is_relative_to(legacy_root)
            and (source.parent / '.besprechung-migriert').exists()):
        raise RevisionConflict('Die Besprechung wurde dauerhaft ins Archiv übernommen. Bitte über „Canvas öffnen“ am Arbeitsblatt erneut öffnen; lokale Änderungen vorher herunterladen.')
    return source


def _annotations_path(source: Path) -> Path:
    """Sidecar-Datei fuer Anmerkungen; der Ordner ist versteckt und abgeleitet."""
    return annotations_path(source)


def _deck_backup(source: Path) -> Path | None:
    """Juengste Rebuild-Sicherung der Deck-Datei (Namenssortierung = Zeitfolge)."""
    candidates = sorted(source.parent.glob(f"{source.name}.bak-*"))
    return candidates[-1] if candidates else None


def _parse_scene(value) -> dict:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput("Szene fehlt.")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise InvalidInput("Szene ist kein gueltiges JSON.") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("elements"), list):
        raise InvalidInput("Ungueltige Excalidraw-Szene.")
    return parsed


def _present_built() -> bool:
    return (PRESENT_DIST / "index.html").is_file()


def register_deck_routes(app: Flask, runtime) -> None:
    config = runtime.config

    def locked_deck_request(function):
        @wraps(function)
        def locked():
            data = request.get_json(silent=True) or {}
            path = config.safe_path(str(data.get("path") or request.args.get("path") or ""))
            with deck_lock(path):
                return function()
        return locked

    @app.get("/api/deck")
    @locked_deck_request
    def deck_data():
        """Excalidraw-Deck als JSON ausliefern (wird von der Present-App geladen)."""
        source = _deck_path(config, required_arg("path"))
        response = send_file(source, mimetype="application/json")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Material-Revision"] = _revision(source)
        return response

    @app.get("/api/deck/revision")
    def deck_revision():
        """Leichter Revisionsabgleich fuer die Present-App (externe Aenderungen)."""
        source = _deck_path(config, required_arg("path"))
        return jsonify({"revision": _revision(source), "mtime": source.stat().st_mtime})

    @app.post("/api/deck/save")
    @locked_deck_request
    def deck_save():
        """Bearbeitete Szene der Present-App zurueck in die .excalidraw-Datei schreiben."""
        data = request.get_json(force=True)
        source = _deck_path(config, str(data.get("path", "")))
        scene = data.get("scene")
        parsed = _parse_scene(scene)
        snapshot = _revision(source)
        expected_revision = data.get("revision")
        if expected_revision is not None and not isinstance(expected_revision, str):
            raise InvalidInput("revision muss eine Zeichenkette sein.")
        if expected_revision is not None and expected_revision != snapshot:
            raise RevisionConflict(
                "Die Datei wurde zwischenzeitlich geaendert. Bitte neu laden."
            )
        if scene.strip() == source.read_text(encoding="utf-8"):
            return jsonify(
                {
                    "ok": True,
                    "path": config.relative(source),
                    "mtime": source.stat().st_mtime,
                    "revision": snapshot,
                }
            )

        def validate_unchanged():
            if _revision(source) != snapshot:
                raise RevisionConflict(
                    "Die Datei wurde waehrend des Speicherns extern geaendert. Bitte Fassungen vergleichen."
                )

        # Vorherige Fassung in die Dateihistorie sichern (wie beim QMD-Speichern).
        runtime.documents.archive(source, {"text": source.read_text(encoding="utf-8"), "revision": snapshot})
        atomic_write_text(source, scene, before_replace=validate_unchanged)
        # Die Szene enthaelt jetzt auch bisherige Sidecar-Anmerkungen; der
        # Sidecar wuerde beim naechsten Laden doppelt erscheinen und entfaellt.
        _annotations_path(source).unlink(missing_ok=True)
        return jsonify(
            {
                "ok": True,
                "path": config.relative(source),
                "mtime": source.stat().st_mtime,
                "revision": _revision(source),
            }
        )

    @app.get("/api/deck/history")
    def deck_history():
        """Versionen der .excalidraw-Datei aus .material-history auflisten."""
        source = _deck_path(config, required_arg("path"))
        return jsonify({"versions": runtime.documents.history(source)})

    @app.get("/api/deck/history/<identifier>")
    def deck_history_snapshot(identifier):
        source = _deck_path(config, required_arg("path"))
        return jsonify(runtime.documents.history_snapshot(source, identifier))

    @app.get("/api/deck/annotations")
    @locked_deck_request
    def deck_annotations():
        """Gespeicherte Anmerkungen (Sidecar) zum Deck; fehlt die Datei, leer antworten."""
        source = _deck_path(config, required_arg("path"))
        sidecar = _annotations_path(source)
        if not sidecar.is_file():
            return jsonify({"elements": [], "files": {}, "revision": None})
        response = send_file(sidecar, mimetype="application/json")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Material-Revision"] = _revision(sidecar)
        return response

    @app.post("/api/deck/annotations/save")
    @locked_deck_request
    def deck_annotations_save():
        """Nur Anmerkungen in die Sidecar-Datei schreiben; das Deck bleibt unberuehrt."""
        data = request.get_json(force=True)
        source = _deck_path(config, str(data.get("path", "")))
        parsed = _parse_scene(data.get("scene"))
        sidecar = _annotations_path(source)
        exists = sidecar.is_file()
        current_revision = _revision(sidecar) if exists else None
        expected_revision = data.get("revision")
        if expected_revision is not None and not isinstance(expected_revision, str):
            raise InvalidInput("revision muss eine Zeichenkette sein.")
        expected_deck = data.get("deckRevision")
        if not isinstance(expected_deck, str):
            # Alte Present-Versionen ohne Deck-Revision duerfen den Schutz nicht
            # umgehen; ohne bekannte Basis ist keine Uebernahme moeglich.
            return jsonify({"error": {
                "code": "deck_changed",
                "message": "Das Deck wurde geändert oder neu gebaut. Bitte lokale Anmerkungen sichern und das Deck neu laden.",
            }}), 409
        current_deck_revision = _revision(source)
        if expected_deck != current_deck_revision:
            # Das Deck wurde neu gebaut: Der Folienbau vergibt frische
            # Element-IDs, die Folienstruktur (Titel und Reihenfolge) bleibt.
            # Anmerkungen aus dem laufenden Unterricht werden auf die neue
            # Fassung umgeschrieben statt abgewiesen; die Zuordnung alter und
            # neuer Frame-IDs liefert die Rebuild-Sicherung des Decks.
            mapped = None
            backup = _deck_backup(source)
            if backup is not None:
                try:
                    mapped = mapped_annotations(parsed["elements"], frame_mapping(
                        json.loads(backup.read_text(encoding="utf-8")),
                        json.loads(source.read_text(encoding="utf-8")),
                    ))
                except (OSError, ValueError, TypeError):
                    mapped = None
            if mapped is None:
                return jsonify({"error": {
                    "code": "deck_changed",
                    "message": "Das Deck wurde geändert oder neu gebaut. Bitte lokale Anmerkungen sichern und das Deck neu laden.",
                }}), 409
            # Strukturell passt alles: Die umgeschriebenen Anmerkungen schreiben
            # den Sidecar fort. Dabei gilt der anwesende Unterricht vor einer
            # zwischenzeitlichen Sidecar-Aenderung eines anderen Fensters.
            parsed = {**parsed, "elements": mapped}
        elif expected_revision != current_revision:
            raise RevisionConflict(
                "Die Anmerkungen wurden zwischenzeitlich geaendert. Bitte neu laden."
            )
        scene = json.dumps(parsed, ensure_ascii=False)
        if exists and scene.strip() == sidecar.read_text(encoding="utf-8"):
            return jsonify({"ok": True, "revision": current_revision, "deckRevision": current_deck_revision})
        atomic_write_text(sidecar, scene)
        return jsonify({"ok": True, "revision": _revision(sidecar), "deckRevision": current_deck_revision})

    @app.get("/present")
    @app.get("/present/")
    def present_index():
        if not _present_built():
            raise ServiceUnavailable(
                "Present-App ist noch nicht gebaut. Einmalig `inv deck-present` ausfuehren."
            )
        html = (PRESENT_DIST / "index.html").read_text(encoding="utf-8")
        token = json.dumps(app.config["MATERIAL_CSRF_TOKEN"])
        injection = f"<script>window.__MATERIAL_TOKEN__ = {token};</script>"
        # Vite-Builds enthalten immer </head>; der </body>-Fallback schuetzt
        # vor kuenftigen Build-Aenderungen, ohne den Token still zu verlieren.
        for marker in ("</head>", "</body>"):
            if marker in html:
                html = html.replace(marker, f"{injection}{marker}", 1)
                break
        else:
            raise ServiceUnavailable(
                "Present-Build unbrauchbar: index.html ohne </head> oder </body>."
            )
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    @app.get("/present/<path:filename>")
    def present_asset(filename):
        if not _present_built():
            raise ServiceUnavailable(
                "Present-App ist noch nicht gebaut. Einmalig `inv deck-present` ausfuehren."
            )
        return send_from_directory(PRESENT_DIST, filename)
