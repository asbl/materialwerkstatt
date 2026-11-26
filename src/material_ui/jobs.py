from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from collections import OrderedDict


class JobBusy(ValueError):
    pass


class ResourceJobQueue:
    """One worker, bounded pending resources, and stable IDs for duplicate requests."""

    def __init__(self, jobs, submit, limit=32):
        self.jobs, self.submit, self.limit = jobs, submit, limit
        self.lock = threading.RLock()
        self.pending = OrderedDict()
        self.active = None
        self.closed = False

    def start(self, resource, operation, work):
        with self.lock:
            if self.closed:
                raise JobBusy("Auftragsverwaltung ist beendet.")
            if self.active and self.active[0] == resource and self.active[1] == operation:
                return self.active[2]
            if resource in self.pending:
                identifier, previous_operation, _ = self.pending[resource]
                # A forced rebuild must not be downgraded by an ensure request.
                if operation == "slides-rebuild" or previous_operation != "slides-rebuild":
                    self.pending[resource] = (identifier, operation, work)
                    self.jobs.update(identifier, operation=operation)
                return identifier
            if len(self.pending) >= self.limit:
                raise JobBusy("Auftragswarteschlange ist voll. Bitte später erneut versuchen.")
            identifier = self.jobs.create(resource, operation, "queued")
            self.jobs.retain(identifier)
            self.pending[resource] = (identifier, operation, work)
            if self.active is None:
                self._submit_next()
            return identifier

    def _submit_next(self):
        resource, (identifier, operation, work) = self.pending.popitem(last=False)
        self.active = (resource, operation, identifier)
        self.jobs.update(identifier, status="running")
        try:
            self.submit(self._run, (identifier, work))
        except Exception as error:
            self.jobs.update(identifier, running=False, ok=False, status="failed", message=str(error))
            self.jobs.release(identifier)
            self.active = None
            raise

    def _run(self, identifier, work):
        result = {"ok": False, "message": "Auftrag wurde beendet."}
        try:
            with self.lock:
                if self.closed:
                    return
            result = work()
        except Exception as error:
            result = {"ok": False, "message": str(error)}
        finally:
            with self.lock:
                if not self.closed:
                    self.jobs.update(identifier, **result, running=False,
                                     status="succeeded" if result.get("ok") else "failed")
                self.jobs.release(identifier)
                self.active = None
                while self.pending and not self.closed:
                    try:
                        self._submit_next()
                        break
                    except Exception:
                        continue

    def close(self):
        with self.lock:
            self.closed = True
            identifiers = [item[0] for item in self.pending.values()]
            if self.active:
                identifiers.append(self.active[2])
            for identifier in identifiers:
                self.jobs.update(identifier, running=False, ok=False, status="failed", message="Anwendung beendet.")
                self.jobs.release(identifier)
            self.pending.clear()


class JobRegistry:
    def __init__(self, history_limit: int = 200, persist_path=None) -> None:
        self.lock = threading.RLock()
        self.records: dict[str, dict] = {}
        self.history_limit = history_limit
        self.retained: set[str] = set()
        self.persist_path = persist_path
        self.listeners: list = []
        if persist_path is not None:
            self._load_persisted()

    def configure_persistence(self, persist_path) -> None:
        """Aktiviert das Laden und Sichern der Auftragsregisterdatei ab jetzt."""
        with self.lock:
            if self.persist_path is not None:
                raise ValueError("Die Auftragspersistenz ist bereits konfiguriert.")
            self.persist_path = persist_path
            self._load_persisted()

    def subscribe(self, listener) -> object:
        """Meldet einen Rueckruf fuer Auftragsaktualisierungen an; liefert die Abmeldung."""
        with self.lock:
            self.listeners.append(listener)

        def unsubscribe() -> None:
            with self.lock:
                if listener in self.listeners:
                    self.listeners.remove(listener)

        return unsubscribe

    def _notify(self, identifier: str) -> None:
        with self.lock:
            listeners = list(self.listeners)
            record = copy.deepcopy(self.records.get(identifier))
        for listener in listeners:
            try:
                listener(record)
            except Exception:
                continue

    def _load_persisted(self) -> None:
        try:
            data = json.loads(self.persist_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for identifier, record in data.items():
            if not isinstance(record, dict) or record.get("job_id") != identifier:
                continue
            if record.get("running"):
                record.update(running=False, ok=False, status="failed",
                              message="Auftrag wurde durch einen Serverneustart beendet.")
            self.records[identifier] = record

    def _persist(self) -> None:
        if self.persist_path is None:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.persist_path.with_name(f".{self.persist_path.name}.tmp")
            temporary.write_text(json.dumps(self.records, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.persist_path)
        except OSError:
            return

    def create(self, resource: str, operation: str, status: str = "running") -> str:
        with self.lock:
            identifier = uuid.uuid4().hex
            self.records[identifier] = {
                "job_id": identifier, "resource": resource, "operation": operation,
                "status": status, "running": True, "ok": None, "updated": time.time(),
            }
            completed = [key for key, job in self.records.items() if not job["running"] and key not in self.retained]
            for key in completed[:max(0, len(self.records) - self.history_limit)]:
                del self.records[key]
            self._persist()
            return identifier

    def retain(self, identifier: str, previous: str | None = None) -> None:
        with self.lock:
            if previous is not None:
                self.retained.discard(previous)
            self.retained.add(identifier)

    def release(self, identifier: str) -> None:
        with self.lock:
            self.retained.discard(identifier)

    def update(self, identifier: str | None, **payload) -> None:
        if identifier is None:
            return
        with self.lock:
            if identifier not in self.records:
                return
            self.records[identifier].update(copy.deepcopy(payload), updated=time.time())
            self._persist()
        self._notify(identifier)

    def get(self, identifier: str) -> dict:
        with self.lock:
            if identifier not in self.records:
                raise KeyError(identifier)
            return copy.deepcopy(self.records[identifier])


class OperationChannel:
    def __init__(self, jobs: JobRegistry, submit) -> None:
        self.jobs = jobs
        self.submit = submit
        self.lock = threading.RLock()
        self.latest_id = None
        self.closed = False

    def start(self, resource: str, operation: str, worker, **payload) -> str:
        with self.lock:
            if self.closed:
                raise JobBusy("Auftragsverwaltung ist beendet.")
            if self.latest_id and self.jobs.get(self.latest_id)["running"]:
                raise JobBusy("Es läuft bereits eine Aktion in diesem Ausführungskanal.")
            identifier = self.jobs.create(resource, operation)
            self.jobs.retain(identifier, self.latest_id)
            self.latest_id = identifier
            self.jobs.update(identifier, **payload)
            try:
                self.submit(self._run, (identifier, worker))
            except Exception as error:
                self.jobs.update(identifier, running=False, ok=False, status="failed", message=str(error))
                raise
            return identifier

    def _run(self, identifier, worker) -> None:
        with self.lock:
            if self.closed:
                return
        try:
            result = worker()
            with self.lock:
                if not self.closed:
                    self.jobs.update(identifier, **result, running=False, status="succeeded" if result["ok"] else "failed")
        except Exception as error:
            with self.lock:
                if not self.closed:
                    self.jobs.update(identifier, running=False, ok=False, status="failed", message=f"{type(error).__name__}: {error}")

    def payload(self) -> dict:
        with self.lock:
            return self.jobs.get(self.latest_id) if self.latest_id else {"running": False, "ok": None}

    def close(self) -> None:
        with self.lock:
            self.closed = True
            if self.latest_id and self.jobs.get(self.latest_id)["running"]:
                self.jobs.update(self.latest_id, running=False, ok=False, status="failed", message="Anwendung beendet.")
