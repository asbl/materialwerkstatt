from __future__ import annotations

from flask import Blueprint, jsonify, request

from material_ui.errors import InvalidInput
from material_ui.http import moodle_target_args


def register_routes(ctx, service, preview, documents):
    """Registriert die Kurs-Endpunkte unter /api/kurse/… (stabile öffentliche Pfade)."""
    bp = Blueprint("kurse_routes", __name__)

    @bp.post("/api/kurse/new")
    def new_kurs():
        data = request.get_json(force=True)
        entry = service.create_kurs(data)
        return jsonify({"ok": True, "kurs": entry, "qmds": documents.all_entries()})

    @bp.get("/api/kurse/sync-overview")
    def kurs_sync_overview():
        return jsonify(service.sync_overview(refresh=request.args.get("refresh") == "1"))

    @bp.get("/api/kurse/<slug>/moodle/targets")
    def kurs_moodle_targets(slug):
        return jsonify(service.moodle_targets(slug))

    @bp.post("/api/kurse/<slug>/moodle/targets")
    def kurs_moodle_target_create(slug):
        data = request.get_json(force=True)
        target = service.save_moodle_target(slug, data.get("target"), data, create=True)
        return jsonify({"ok": True, "target": target, **service.moodle_targets(slug)}), 201

    @bp.put("/api/kurse/<slug>/moodle/targets/<target>")
    def kurs_moodle_target_update(slug, target):
        data = request.get_json(force=True)
        saved = service.save_moodle_target(slug, target, data, create=False)
        return jsonify({"ok": True, "target": saved, **service.moodle_targets(slug)})

    @bp.get("/api/kurse/<slug>/index")
    def kurs_index(slug):
        return jsonify(service.index(slug))

    @bp.route("/api/kurse/<slug>/activities/<identifier>", methods=["GET", "POST"])
    def kurs_activity(slug, identifier):
        data = request.get_json(force=True) if request.method == "POST" else None
        return jsonify(service.activity(slug, identifier, data))

    @bp.post("/api/kurse/<slug>/audit")
    def kurs_audit(slug):
        service.ensure_kurs(slug)
        identifier = service.start_audit(slug)
        return jsonify(ctx.jobs.get(identifier)), 202

    @bp.get("/api/kurse/<slug>/audit/status")
    def kurs_audit_status(slug):
        payload = service.audit_payload()
        return jsonify(payload if payload["current"] == slug else {"running": False, "current": slug, "ok": None})

    @bp.post("/api/kurse/<slug>/moodle/verify")
    def kurs_moodle_verify(slug):
        service.ensure_kurs(slug)
        data = request.get_json(silent=True) or {}
        identifier = service.start_moodle(slug, "verify", moodle_target_args(data))
        return jsonify(ctx.jobs.get(identifier)), 202

    @bp.post("/api/kurse/<slug>/moodle/upload-chapter")
    def kurs_moodle_upload_chapter(slug):
        course_dir = service.ensure_kurs(slug)
        data = request.get_json(force=True)
        chapter = str(data.get("chapter") or "").strip()
        valid_chapters = {item["slug"] for item in service.adapter.list_course_chapters(course_dir)}
        if chapter not in valid_chapters:
            raise InvalidInput(f"Unbekanntes Kapitel: {chapter}")
        extra_args = [f"--chapter={chapter}", *moodle_target_args(data)]
        identifier = service.start_moodle(slug, "upload-chapter", extra_args)
        return jsonify(ctx.jobs.get(identifier)), 202

    @bp.post("/api/kurse/<slug>/moodle/upload-course")
    def kurs_moodle_upload_course(slug):
        service.ensure_kurs(slug)
        data = request.get_json(silent=True) or {}
        identifier = service.start_moodle(slug, "upload-course", moodle_target_args(data))
        return jsonify(ctx.jobs.get(identifier)), 202

    @bp.post("/api/kurse/<slug>/moodle/publish")
    def kurs_moodle_publish(slug):
        service.ensure_kurs(slug)
        data = request.get_json(silent=True) or {}
        identifier = service.start_moodle(slug, "publish", moodle_target_args(data))
        return jsonify(ctx.jobs.get(identifier)), 202

    @bp.get("/api/kurse/<slug>/moodle/status")
    def kurs_moodle_status(slug):
        payload = service.moodle_payload()
        return jsonify(payload if payload["slug"] == slug else {"running": False, "slug": slug, "ok": None})

    @bp.post("/api/kurse/<slug>/preview")
    def kurs_preview_start(slug):
        service.ensure_kurs(slug)
        preview.start(slug)
        return jsonify(preview.payload())

    @bp.get("/api/kurse/preview/status")
    def kurs_preview_status():
        return jsonify(preview.payload())

    @bp.post("/api/kurse/preview/stop")
    def kurs_preview_stop():
        preview.stop()
        return jsonify(preview.payload())

    ctx.register_routes(bp)
