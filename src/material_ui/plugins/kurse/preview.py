from __future__ import annotations

import socket
import subprocess
import sys
import threading


def port_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


class PreviewService:
    def __init__(self, config, processes, environment, submit, ensure_runtime):
        self.config = config
        self.processes = processes
        self.environment = environment
        self.submit = submit
        self.ensure_runtime = ensure_runtime
        self.lock = threading.RLock()
        self.process = None
        self.slug = None
        self.runtime_process = None
        self.closed = False

    def start(self, slug: str) -> None:
        with self.lock:
            if self.closed:
                raise RuntimeError("Vorschauverwaltung ist beendet.")
            if self.slug == slug and self.process and self.process.process.poll() is None:
                return
            self.stop()
            self.process = self.processes.start(
                [sys.executable, "-m", "course_sync.scoped_preview", slug, "--port", str(self.config.preview_port)],
                log_path=self.config.root / ".h5p-runtime" / "material-ui-preview.log",
                cwd=self.config.root, env=self.environment(),
            )
            self.slug = slug

    def stop(self) -> None:
        with self.lock:
            if self.process is not None:
                self.process.close()
            self.process = None
            self.slug = None

    def payload(self) -> dict:
        with self.lock:
            managed, slug = self.process, self.slug
            if managed is None:
                return {"running": False, "slug": None, "port": None, "ready": False, "url": None, "error": None}
            exited = managed.process.poll() is not None
            ready = not exited and port_ready(self.config.preview_port)
            error = managed.tail() if exited and managed.process.returncode != 0 else None
            return {"running": not exited, "slug": slug, "port": self.config.preview_port,
                    "ready": ready, "url": f"http://127.0.0.1:{self.config.preview_port}/courses/{slug}" if ready else None,
                    "error": error or None}

    def prewarm(self) -> None:
        def worker():
            try:
                process = self.ensure_runtime()
            except Exception:
                return
            with self.lock:
                if self.closed:
                    self._stop_runtime(process)
                else:
                    self.runtime_process = process
        self.submit(worker, ())

    def _stop_runtime(self, process) -> None:
        if process is not None:
            self.processes.stop(process)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            self.stop()
            self._stop_runtime(self.runtime_process)
