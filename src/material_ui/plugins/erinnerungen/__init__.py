"""Erinnerungen-Plugin: Desktop-Benachrichtigungen bei geschlossener UI.

Abhaengigkeit ``@calendar >= 0.3.0``: Termine/TODOs und Zeitzone kommen ueber das
Interface, nicht ueber das Kalender-Plugin direkt.
"""

from __future__ import annotations

from flask import Blueprint

from .service import ReminderService


def register(ctx) -> None:
    calendar = ctx.require_service("calendar")
    service = ReminderService(ctx, calendar)
    ctx.service = service

    bp = Blueprint("erinnerungen_routes", __name__)

    @bp.get("/api/plugins/erinnerungen/settings")
    def settings():
        return service.settings_payload()

    @bp.post("/api/plugins/erinnerungen/settings")
    def replace_settings():
        from flask import request

        return service.replace_settings(request.get_json(force=True))

    @bp.get("/api/plugins/erinnerungen/status")
    def status():
        return {"sentToday": service.sent_today()}

    ctx.register_routes(bp)
    service.start_worker(ctx.workers, ctx.windows)
