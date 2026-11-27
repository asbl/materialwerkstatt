from __future__ import annotations

import threading

from flask import Flask, jsonify, request

from material_core import updates
from material_ui.errors import InvalidInput
from material_ui.jobs import JobBusy


def register_update_routes(app: Flask, runtime) -> None:
    """Auf neue Releases pruefen und einen Git-Klon auf Wunsch aktualisieren."""
    cache = runtime.config.root / ".material-ui" / "update.json"
    # Stand beim Serverstart: weicht der Programmordner davon ab, fehlt ein Neustart.
    running = updates.current_version()
    lock = threading.Lock()

    def overview(refresh: bool = False, message: str = ""):
        installed = updates.current_version()
        checking = updates.enabled()
        data = updates.latest_cached(cache, refresh=refresh) if checking else {}
        latest = data.get("latest")
        return jsonify({
            "enabled": checking, "current": running, "latest": latest,
            "updateAvailable": updates.is_newer(latest, installed),
            "restartRequired": installed != running,
            "kind": updates.install_kind(), "url": updates.source_url(),
            "checkedAt": data.get("checkedAt"), "error": data.get("error", ""), "message": message,
        })

    @app.get("/api/update")
    def update_status():
        return overview(refresh=request.args.get("refresh") == "1")

    @app.post("/api/update/apply")
    def update_apply():
        data = request.get_json(silent=True)
        version = data.get("version") if isinstance(data, dict) else None
        if not isinstance(version, str) or updates.parse_release(version) is None:
            raise InvalidInput("version fehlt oder ist ungültig.")
        # Nur das angebotene Release, nie ein beliebiger Stand aus der Anfrage.
        if not updates.enabled() or version != updates.latest_cached(cache).get("latest"):
            raise InvalidInput("Diese Version wird nicht angeboten. Bitte erneut prüfen.")
        with runtime.jobs.lock:
            if any(job.get("running") for job in runtime.jobs.records.values()):
                raise JobBusy("Es laufen noch Aufträge. Bitte danach aktualisieren.")
        if not lock.acquire(blocking=False):
            raise JobBusy("Ein Update läuft bereits.")
        try:
            message = updates.apply(version)
        except updates.UpdateError as error:
            raise InvalidInput(str(error)) from error
        finally:
            lock.release()
        return overview(message=message)
