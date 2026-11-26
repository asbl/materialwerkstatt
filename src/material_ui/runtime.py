from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

from flask import current_app, has_app_context

from material_ui.jobs import JobRegistry
from material_ui.storage import DocumentRepository
from material_ui.processes import ProcessRunner


class RuntimeState:
    def __init__(self, config=None, *, documents=None, processes=None, jobs=None) -> None:
        self.config = config
        self.documents = documents if documents is not None else DocumentRepository()
        self.processes = processes if processes is not None else ProcessRunner()
        self.jobs = jobs if jobs is not None else JobRegistry()
        self.services = None
        self.closing = threading.Event()
        self.worker_lock = threading.RLock()
        self.workers: set[threading.Thread] = set()
        self.close_lock = threading.Lock()
        self.course_application = None
        self.plugins = None

    def start_worker(self, target, args: tuple) -> None:
        def worker():
            try:
                with runtime_scope(self):
                    target(*args)
            finally:
                with self.worker_lock:
                    self.workers.discard(threading.current_thread())

        with self.worker_lock:
            if self.closing.is_set():
                raise RuntimeError("Anwendung wird beendet.")
            thread = threading.Thread(target=worker, name="material-ui-worker", daemon=True)
            self.workers.add(thread)
            try:
                thread.start()
            except BaseException:
                self.workers.discard(thread)
                raise

    def close(self, timeout: float = 10.0) -> None:
        with self.close_lock:
            if self.closing.is_set():
                return
            with self.worker_lock:
                self.closing.set()
            if self.services is not None:
                self.services.render.close()
                self.services.slides.close()
            if self.plugins is not None:
                self.plugins.close()
            self.processes.close()
            deadline = time.monotonic() + timeout
            with self.worker_lock:
                workers = list(self.workers)
            for worker in workers:
                if worker is not threading.current_thread():
                    worker.join(timeout=max(0, deadline - time.monotonic()))


_runtime = ContextVar("material_runtime", default=None)


def current_runtime() -> RuntimeState:
    if has_app_context():
        return current_app.extensions["material_runtime"]
    runtime = _runtime.get()
    if runtime is None:
        raise RuntimeError("Material-UI benötigt einen expliziten Anwendungszustand.")
    return runtime


@contextmanager
def runtime_scope(runtime: RuntimeState):
    token = _runtime.set(runtime)
    try:
        yield runtime
    finally:
        _runtime.reset(token)


def start_worker(target, args: tuple) -> None:
    current_runtime().start_worker(target, args)
