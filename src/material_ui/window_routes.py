from __future__ import annotations

from flask import Flask, jsonify, request

from material_ui.errors import InvalidInput
from material_ui.http import required_value
from material_ui.qmd_imports import pending_import


MAX_SESSION_LENGTH = 128


def register_window_routes(app: Flask, runtime) -> None:
    windows = runtime.services.windows

    @app.post("/api/window/heartbeat")
    def window_heartbeat():
        """Lebensmeldung eines Fensters; liefert wartende Öffnungswünsche aus."""
        data = request.get_json(force=True)
        session = required_value(data.get("session"))
        if len(session) > MAX_SESSION_LENGTH:
            raise InvalidInput("Sitzungskennung ist zu lang.")
        requests = windows.heartbeat(session)
        return jsonify({"windows": windows.count(), "requests": requests})

    @app.post("/api/window/close")
    def window_close():
        data = request.get_json(force=True)
        windows.close(required_value(data.get("session")))
        return jsonify({"ok": True})

    @app.post("/api/window/open")
    def window_open():
        """Öffnungswunsch des Starters für ein bereits laufendes Fenster."""
        data = request.get_json(force=True)
        path = data.get("path")
        token = data.get("import")
        if bool(path) == bool(token):
            raise InvalidInput("Genau ein Pfad oder ein Import-Token wird erwartet.")
        if token:
            pending_import(str(token))
        identifier = windows.enqueue({"path": path} if path else {"import": token})
        return jsonify({"id": identifier}), 202

    @app.get("/api/window/open/<int:identifier>")
    def window_open_status(identifier):
        return jsonify({"claimed": windows.claimed(identifier)})

    @app.delete("/api/window/open/<int:identifier>")
    def window_open_discard(identifier):
        windows.discard(identifier)
        return jsonify({"ok": True})
