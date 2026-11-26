from __future__ import annotations

import json
import queue
import threading

from flask import jsonify, Response
from werkzeug.exceptions import NotFound

JOB_LIST_FIELDS = ("job_id", "resource", "operation", "status", "running", "ok", "updated", "message")


def project_job_record(record):
    """Listenfelder eines Auftrags fuer Uebersicht und Eventstrom.

    `detail` enthaelt komplette Render- und Auditprotokolle; es geht nur fuer
    Render-Auftraege auf den Stream, weil die Renderstatusanzeige Protokoll,
    Kommando und Exit-Code live zeigt. Die Uebersicht liefert es nie.
    """
    fields = JOB_LIST_FIELDS + ("current", "queued", "pdf")
    if record.get("operation") == "render":
        fields += ("detail",)
    return {field: record.get(field) for field in fields}


def register_job_routes(app, runtime):
    @app.get("/api/jobs")
    def jobs_list():
        """Zuletzt aktualisierte Auftraege fuer die Auftragsuebersicht der UI.

        Projiziert bewusst nur die Listenfelder: `detail` enthaelt komplette
        Render- und Auditprotokolle, die in der Uebersicht ungenutzt blieben.
        """
        with runtime.jobs.lock:
            records = sorted(
                runtime.jobs.records.values(),
                key=lambda record: record.get("updated") or 0,
                reverse=True,
            )
            return jsonify({"jobs": [project_job_record(record) for record in records[:50]]})

    @app.get("/api/jobs/<identifier>")
    def job_status(identifier):
        try:
            return jsonify(runtime.jobs.get(identifier))
        except KeyError:
            raise NotFound("Auftrag nicht gefunden.") from None

    @app.get("/api/jobs/stream")
    def jobs_stream():
        """Server-Events fuer Auftragsaktualisierungen; Browser duerfen weiterhin pollen."""
        updates: queue.Queue = queue.Queue(maxsize=100)
        closed = threading.Event()

        def listener(record):
            if closed.is_set() or record is None:
                return
            try:
                updates.put_nowait(project_job_record(record))
            except queue.Full:
                pass

        unsubscribe = runtime.jobs.subscribe(listener)

        def stream():
            try:
                yield "retry: 3000\n\n"
                while True:
                    try:
                        record = updates.get(timeout=15)
                    except queue.Empty:
                        yield ": keep-alive\n\n"
                        continue
                    yield f"data: {json.dumps(record, ensure_ascii=False)}\n\n"
            finally:
                closed.set()
                unsubscribe()

        response = Response(stream(), mimetype="text/event-stream")
        response.headers["X-Accel-Buffering"] = "no"
        return response
