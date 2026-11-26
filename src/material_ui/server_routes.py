from __future__ import annotations

import os

from flask import jsonify, request

from material_ui.errors import InvalidInput
from material_ui.protocol import API_VERSION, CAPABILITIES
from material_core import workspace


def register_server_routes(app, runtime, desktop_version: str):
    config = runtime.config

    @app.get("/")
    def index():
        from flask import render_template

        return render_template("index.html", csrf_token=app.config["MATERIAL_CSRF_TOKEN"])

    @app.get("/api/protocol")
    def protocol():
        return jsonify({"apiVersion": API_VERSION, "capabilities": CAPABILITIES})

    @app.get("/api/desktop-status")
    def desktop_status():
        return jsonify({
            "application": "material-ui",
            "root": str(config.root),
            "code": str(workspace.CODE_ROOT),
            "version": desktop_version,
            "pid": os.getpid(),
            "windows": runtime.services.windows.count(),
        })

    @app.post("/api/server/restart")
    def server_restart():
        host, separator, port = request.host.rpartition(":")
        if not separator or not port.isdigit():
            raise InvalidInput("Die Server-Adresse konnte nicht bestimmt werden.")
        from material_ui.desktop import spawn_restart_helper

        spawn_restart_helper(host, int(port))
        return jsonify({"ok": True})
