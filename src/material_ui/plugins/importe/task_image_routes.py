from __future__ import annotations

from flask import Blueprint, Response, jsonify, request, send_file

from . import task_image_import
from material_ui.errors import InvalidInput
from material_ui.http import required_value


def build_blueprint(ctx, max_task_image_bytes: int) -> Blueprint:
    """Aufgabenbild-Import-Routen des Plugins; stable Pfade unter /api/document/import/task-image/."""
    bp = Blueprint("task_image_import_routes", __name__)
    config = ctx.config
    document_service = ctx.documents
    builds = ctx.builds

    def _default_wissen_ziel(document_path: str) -> str:
        source = config.safe_path(document_path)
        parts = (config.relative(source) or "").split("/")
        subject = parts[1] if len(parts) > 1 else "material"
        grade, thema = document_service.klasse_thema_for(source)
        grade = grade.removeprefix("klasse-") or "05"
        return f"aufgaben/{subject}/klasse-{grade}/{thema or 'material'}"

    @bp.post("/api/document/import/task-image")
    def task_image_upload():
        upload = request.files.get("file")
        if upload is None:
            raise InvalidInput("Bild fehlt.")
        payload = upload.read(max_task_image_bytes + 1)
        if len(payload) > max_task_image_bytes:
            raise InvalidInput(f"Das Bild darf höchstens {max_task_image_bytes // (1024 * 1024)} MiB groß sein.")
        document_path = required_value(request.form.get("documentPath"))
        record = task_image_import.stage_task_image(payload, upload.mimetype or "image/png", root=config.root)
        return jsonify(
            {
                "token": record.token,
                "prompt": task_image_import.conversion_prompt(record.token),
                "wissenZiel": _default_wissen_ziel(document_path),
            }
        )

    @bp.delete("/api/document/import/task-image/<token>")
    def task_image_cancel(token):
        task_image_import.discard_task_image(token, root=config.root)
        return jsonify({"ok": True})

    @bp.post("/api/document/import/task-image/<token>/render")
    def task_image_render(token):
        data = request.get_json(force=True)
        code = required_value(data.get("code"))
        task_image_import.update_code(token, code, root=config.root)
        preview_png = task_image_import.render_preview(builds, token, code, root=config.root)
        response = Response(preview_png.read_bytes(), mimetype="image/png")
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.get("/api/document/import/task-image/<token>/image")
    def task_image_image(token):
        """Liefert das gestagte Aufgabenbild; wird vom MCP-Server des chat-Plugins per HTTP gelesen."""
        record = task_image_import.task_image_record(token, root=config.root)
        return send_file(record.image_path)

    @bp.post("/api/document/import/task-image/<token>")
    def task_image_commit(token):
        data = request.get_json(force=True)
        code = required_value(data.get("code"))
        wissen_ziel = required_value(data.get("wissenZiel"))
        with ctx.documents.lock:
            result = task_image_import.commit_task_image(token, root=config.root, wissen_ziel=wissen_ziel, code=code)
        return jsonify({"ok": True, "wissenPath": result["wissen_path"], "markdown": result["markdown"]})

    return bp
