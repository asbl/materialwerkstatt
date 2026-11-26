from __future__ import annotations

from flask import Blueprint

from .calendar_interface import CalendarInterface
from .service import KalenderService


def register(ctx) -> None:
    service = KalenderService(ctx)
    ctx.service = service
    # Interface @calendar: hier registrieren sich auch Plugins, die Termine beisteuern;
    # seit 0.3.0 liest das Interface auch Termine/TODOs des Kalenders (z. B. Erinnerungen).
    interface = CalendarInterface(service)
    service.calendar_interface = interface
    interface.register_source(service.planning_marker_events, source_id=ctx.manifest.id, name=ctx.manifest.name)
    ctx.register_service("calendar", interface)
    bp = Blueprint("kalender_routes", __name__)

    @bp.get("/api/plugins/kalender/settings")
    def settings():
        return service.settings_payload()

    @bp.post("/api/plugins/kalender/settings")
    def replace_settings():
        from flask import request

        return service.replace_settings(request.get_json(force=True))

    @bp.get("/api/plugins/kalender/status")
    def status():
        return service.status()

    @bp.get("/api/plugins/kalender/events")
    def events():
        from flask import request

        return service.events(  # noqa: B009
            request.args.get("from", ""), request.args.get("to", ""))

    @bp.post('/api/plugins/kalender/events')
    def create_event():
        from flask import request
        return service.create_event(request.get_json(force=True)), 201

    @bp.patch('/api/plugins/kalender/events')
    def update_event():
        from flask import request
        return service.update_event(request.get_json(force=True))

    @bp.get('/api/plugins/kalender/lessons')
    def lessons():
        from flask import request

        return service.lessons(request.args.get("date", ""))

    @bp.get('/api/plugins/kalender/visibility')
    def visibility():
        return service.visibility_payload()

    @bp.post('/api/plugins/kalender/visibility')
    def update_visibility():
        from flask import request
        return service.update_visibility(request.get_json(force=True))

    @bp.get('/api/plugins/kalender/tasks')
    def tasks():
        return service.tasks()

    @bp.post('/api/plugins/kalender/tasks')
    def update_task():
        from flask import request
        return service.update_task(request.get_json(force=True))

    @bp.get('/api/plugins/kalender/unit-groups')
    def unit_groups():
        return {'rows': service.group_defaults()}

    @bp.post('/api/plugins/kalender/unit-groups')
    def save_unit_groups():
        from flask import request
        return service.save_group_defaults(request.get_json(force=True))

    @bp.post("/api/plugins/kalender/sync")
    def sync():
        channel = ctx.jobs.channel("kalender-sync")
        identifier = channel.start("kalender", "cal-sync", service.sync_now)
        return {"job_id": identifier}, 202

    @bp.get("/api/plugins/kalender/calendars")
    def calendars():
        return service.discover_calendars()

    @bp.post('/api/plugins/kalender/lesson-cancellation')
    def cancel_lesson():
        from flask import request
        return service.cancel_lesson(request.get_json(force=True))

    @bp.get('/api/plugins/kalender/planning-markers')
    def planning_markers():
        return service.planning_markers()

    @bp.post('/api/plugins/kalender/planning-markers')
    def save_planning_marker():
        from flask import request
        return service.save_planning_marker(request.get_json(force=True))

    @bp.get("/api/plugins/kalender/holidays")
    def holidays():
        from flask import request

        return service.holidays(
            request.args.get("from", ""), request.args.get("to", ""))

    ctx.register_routes(bp)

    interval = service.settings().get("syncIntervalMinutes")
    service.start_interval_worker(ctx.workers, int(interval) if interval else 60)
