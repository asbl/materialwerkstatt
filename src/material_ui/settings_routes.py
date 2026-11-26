from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, request

from material_core import workspace
from material_ui.errors import InvalidInput


def register_settings_routes(app: Flask, runtime) -> None:
    """Einstellungen: Inhaltsordner dieses Rechners (getrennt vom Programm)."""

    def overview(message: str = ""):
        try:
            configured = workspace.configured()
            chosen = workspace.selected()
        except workspace.WorkspaceError as error:
            raise InvalidInput(str(error)) from error
        current = Path(runtime.config.root)
        if not chosen.is_dir():
            state = "missing"
        elif chosen != current:
            state = "restart"
        else:
            state = "default" if current == workspace.default_home() else "active"
        return jsonify({
            "code": str(workspace.CODE_ROOT), "current": str(current), "state": state,
            "default": str(workspace.default_home()),
            "path": str(configured) if configured else "",
            # Eine Umgebungsvariable hat Vorrang vor der Einstellung.
            "fixed": bool(os.environ.get(workspace.ENV)),
            "configFile": str(workspace.config_path()), "message": message,
        })

    @app.get("/api/settings/workspace")
    def workspace_overview():
        return overview()

    @app.put("/api/settings/workspace")
    def save_workspace():
        data = request.get_json(silent=True)
        value = data.get("path") if isinstance(data, dict) else None
        if not isinstance(value, str):
            raise InvalidInput("path muss ein Text sein.")
        try:
            workspace.save(value, create=data.get("create") is True)
        except (workspace.WorkspaceError, OSError) as error:
            raise InvalidInput(str(error)) from error
        return overview("Gespeichert.")
