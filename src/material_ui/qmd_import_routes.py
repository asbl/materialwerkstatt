from __future__ import annotations

from flask import jsonify, request

from material_ui.errors import InvalidInput
from material_ui.http import required_value
from material_ui.qmd_imports import pending_import, pending_path, commit_import


def register_qmd_import_routes(app, runtime):
    config = runtime.config
    document_service = runtime.services.documents

    @app.get("/api/qmd-import/<token>")
    def qmd_import_details(token):
        data = pending_import(token)
        return jsonify({"name": data["name"], "source": data["source"]})

    @app.delete("/api/qmd-import/<token>")
    def qmd_import_cancel(token):
        pending_path(token).unlink(missing_ok=True)
        return jsonify({"ok": True})

    @app.post("/api/qmd-import/<token>")
    def qmd_import_confirm(token):
        data = request.get_json(force=True)
        target = config.safe_visible_path(required_value(data.get("path")))
        if target.suffix != ".qmd":
            raise InvalidInput("Bitte einen sichtbaren Zielpfad mit der Endung .qmd im Repository wählen.")
        with runtime.documents.lock:
            commit_import(token, target)
        document_service.invalidate_qmd_cache()
        return jsonify({"ok": True, "path": config.relative(target), "qmds": document_service.all_entries()})
