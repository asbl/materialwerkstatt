from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from . import office_import
from material_ui.assets import sanitize_stem
from material_ui.errors import InvalidInput
from material_ui.http import required_value


def build_blueprint(ctx, max_office_bytes: int) -> Blueprint:
    """Office-Import-Routen des Plugins; stable Pfade unter /api/document/import/office/."""
    bp = Blueprint("office_import_routes", __name__)
    config = ctx.config
    document_service = ctx.documents

    def chat_service():
        """Chat-Interface des chat-Plugins (provides: chat) für den KI-Umbau."""
        try:
            return ctx.require_service("chat")
        except LookupError as error:
            raise InvalidInput("KI-Umbau nicht verfügbar: Das Chat-Plugin ist nicht aktiv.") from error

    @bp.post("/api/document/import/office")
    def office_import_upload():
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            raise InvalidInput("Datei fehlt.")
        payload = upload.read(max_office_bytes + 1)
        if len(payload) > max_office_bytes:
            raise InvalidInput(f"Die Datei darf höchstens {max_office_bytes // (1024 * 1024)} MiB groß sein.")
        record = office_import.stage_office_upload(payload, upload.filename, root=config.root)
        suggested = record.suggested
        subject = sanitize_stem(suggested.get("subject") or "material")
        grade = suggested.get("grade") or "05"
        thema = sanitize_stem(suggested.get("thema") or record.slug)
        stem = sanitize_stem(suggested.get("title") or record.slug)
        project_target, wissen_ziel = office_import.default_targets(
            subject=subject,
            grade=grade,
            thema=thema,
            kind=suggested.get("kind") or "Arbeitsblatt",
            stem=stem,
        )
        return jsonify(
            {
                "token": record.token,
                "name": record.name,
                "kind": record.origin_kind,
                "pages": record.pages,
                "preview": record.text[:4000],
                "duplicateOf": record.duplicate_of,
                "suggested": suggested,
                "projectTarget": project_target,
                "wissenZiel": wissen_ziel,
            }
        )

    @bp.delete("/api/document/import/office/<token>")
    def office_import_cancel(token):
        office_import.discard_office_import(token, root=config.root)
        return jsonify({"ok": True})

    @bp.post("/api/document/import/office/<token>/draft")
    def office_import_draft(token):
        """Erster KI-Umbau-Schritt: wandelt den rohen Extraktionstext in einen AB-Entwurf um.

        Streamt dieselben ChatEvents wie der normale Chat (Wiederverwendung des
        Provider-Codes); das akkumulierte Textergebnis wird am Ende als neuer
        Entwurfstext im Staging-Auftrag gespeichert, bevor commit() ihn liest.
        """
        data = request.get_json(force=True)
        provider_id = required_value(data.get("provider"))
        fields = data.get("fields") or {}
        if not isinstance(fields, dict):
            raise InvalidInput("fields muss ein Objekt sein.")
        record = office_import.office_staging_record(token, root=config.root)
        prompt = office_import.conversion_prompt(
            record,
            title=str(fields.get("title") or record.suggested.get("title") or record.name),
            subject=str(fields.get("subject") or ""),
            grade=str(fields.get("grade") or ""),
            thema=str(fields.get("thema") or ""),
            kind=str(fields.get("kind") or ""),
        )
        chat = chat_service()
        chat.set_base_url(request.host_url)
        session_id = chat.create_session(provider_id)

        def stream():
            collected = []
            try:
                for event in chat.send_message(session_id, prompt):
                    if event.type == "text" and event.text:
                        collected.append(event.text)
                    yield event.to_sse()
            finally:
                chat.close_session(session_id)
            text = "".join(collected).strip()
            if text:
                try:
                    office_import.update_staged_text(token, text, root=config.root)
                except FileNotFoundError:
                    pass  # Import wurde waehrend des KI-Umbaus abgebrochen; nichts mehr zu speichern.

        response = Response(stream(), mimetype="text/event-stream")
        response.headers["X-Accel-Buffering"] = "no"
        return response

    @bp.post("/api/document/import/office/<token>")
    def office_import_confirm(token):
        data = request.get_json(force=True)
        target = config.safe_visible_path(required_value(data.get("projectTarget")))
        if target.suffix != ".qmd":
            raise InvalidInput("Zielpfad muss auf eine sichtbare .qmd-Datei im Repository zeigen.")
        wissen_ziel = required_value(data.get("wissenZiel"))
        fields = data.get("fields")
        if not isinstance(fields, dict):
            raise InvalidInput("fields muss ein Objekt sein.")
        tags = fields.get("tags")
        if tags is not None and not (isinstance(tags, list) and all(isinstance(item, str) for item in tags)):
            raise InvalidInput("fields.tags muss eine Liste von Zeichenketten sein.")
        body = data.get("body")
        if body is not None:
            if not isinstance(body, str):
                raise InvalidInput("body muss eine Zeichenkette sein.")
            if len(body.encode("utf-8")) > office_import.MAX_OFFICE_BYTES:
                raise InvalidInput(f"body darf höchstens {office_import.MAX_OFFICE_BYTES // (1024 * 1024)} MiB groß sein.")
        with ctx.documents.lock:
            result = office_import.finalize_office_import(
                token,
                root=config.root,
                target=target,
                wissen_ziel=wissen_ziel,
                fields=fields,
                body=body,
            )
        document_service.invalidate_qmd_cache()
        return jsonify(
            {
                "ok": True,
                "path": config.relative(result["path"]),
                "wissenPath": result["wissen_path"],
                "duplicate": result["duplicate"],
                "qmds": document_service.all_entries(),
            }
        )

    return bp
