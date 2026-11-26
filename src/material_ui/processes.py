from __future__ import annotations

import os
import signal
import subprocess
import threading
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

from material_ui.jobs import JobBusy


class ProcessRunner:
    def __init__(self, output_limit: int = 16 * 1024 * 1024, tail_bytes: int = 64 * 1024, max_processes: int = 4) -> None:
        self.lock = threading.Lock()
        self.processes: set[subprocess.Popen] = set()
        self.closed = False
        self.output_limit = output_limit
        self.tail_bytes = tail_bytes
        self.max_processes = max_processes
        self.persistent: set[ManagedProcess] = set()

    def start(self, command: list[str], *, log_path: Path, **kwargs):
        with self.lock:
            if self.closed:
                raise RuntimeError("Prozessverwaltung ist beendet.")
            if len(self.processes) >= self.max_processes:
                raise JobBusy("Zu viele laufende Prozesse. Bitte später erneut versuchen.")
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       start_new_session=True, **kwargs)
            self.processes.add(process)
            managed = ManagedProcess(self, process, log_path)
            self.persistent.add(managed)
            try:
                managed.start()
            except BaseException:
                self.terminate(process)
                process.wait()
                process.stdout.close()
                self.processes.discard(process)
                self.persistent.discard(managed)
                raise
            return managed

    def release(self, managed) -> None:
        with self.lock:
            self.processes.discard(managed.process)
            self.persistent.discard(managed)

    def stop(self, process) -> None:
        with self.lock:
            managed = next((item for item in self.persistent if item.process is process), None)
        if managed is not None:
            managed.close()

    def run(self, command: list[str], *, timeout: float, check: bool = False,
            capture_output: bool = False, input=None, full_output: bool = False, **kwargs):
        with ExitStack() as stack:
            if capture_output:
                if "stdout" in kwargs or "stderr" in kwargs:
                    raise ValueError("capture_output darf nicht mit stdout/stderr kombiniert werden.")
                kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if input is not None:
                if "stdin" in kwargs:
                    raise ValueError("input darf nicht mit stdin kombiniert werden.")
                stdin = stack.enter_context(tempfile.TemporaryFile())
                stdin.write(input.encode(kwargs.get("encoding") or "utf-8") if isinstance(input, str) else input)
                stdin.seek(0)
                kwargs["stdin"] = stdin
            captures = {}
            for stream in ("stdout", "stderr"):
                if kwargs.get(stream) == subprocess.PIPE:
                    captures[stream] = stack.enter_context(tempfile.TemporaryFile())
                    kwargs[stream] = captures[stream]
            return self._run(command, timeout, check, captures, kwargs, full_output)

    def _run(self, command, timeout, check, captures, kwargs, full_output=False):
        with self.lock:
            if self.closed:
                raise RuntimeError("Prozessverwaltung ist beendet.")
            if len(self.processes) >= self.max_processes:
                raise JobBusy("Zu viele laufende Prozesse. Bitte später erneut versuchen.")
            process = subprocess.Popen(command, start_new_session=True, **kwargs)
            self.processes.add(process)
        try:
            try:
                deadline = time.monotonic() + timeout
                while True:
                    if any(os.fstat(handle.fileno()).st_size > self.output_limit for handle in captures.values()):
                        raise RuntimeError("Prozessausgabe überschreitet das erlaubte Log-Limit.")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    try:
                        process.wait(timeout=min(remaining, 0.1))
                        if any(os.fstat(handle.fileno()).st_size > self.output_limit for handle in captures.values()):
                            raise RuntimeError("Prozessausgabe überschreitet das erlaubte Log-Limit.")
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException as error:
                self.terminate(process)
                process.wait()
                if isinstance(error, subprocess.TimeoutExpired):
                    error.output = self.read_tail(captures.get("stdout"), kwargs)
                    error.stderr = self.read_tail(captures.get("stderr"), kwargs)
                raise
            self.terminate(process)
            limit = self.output_limit if full_output else self.tail_bytes
            stdout = self.read_tail(captures.get("stdout"), kwargs, limit)
            stderr = self.read_tail(captures.get("stderr"), kwargs, limit)
            result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            if check:
                result.check_returncode()
            return result
        finally:
            with self.lock:
                self.processes.discard(process)

    def read_tail(self, handle, options, limit=None):
        if handle is None:
            return None
        limit = self.tail_bytes if limit is None else limit
        size = os.fstat(handle.fileno()).st_size
        handle.seek(max(0, size - limit))
        data = handle.read(limit)
        if size > limit:
            data = b"[Ausgabe gekuerzt; letzte Protokollbytes folgen]\n" + data
        if options.get("text") or options.get("universal_newlines") or options.get("encoding"):
            return data.decode(options.get("encoding") or "utf-8", errors="replace")
        return data

    def terminate(self, process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def close(self) -> None:
        with self.lock:
            self.closed = True
            persistent = list(self.persistent)
            short = self.processes - {managed.process for managed in persistent}
            for process in short:
                self.terminate(process)
        for managed in persistent:
            managed.close()


class ManagedProcess:
    def __init__(self, owner: ProcessRunner, process, log_path: Path) -> None:
        self.owner = owner
        self.process = process
        self.log_path = log_path
        self.log_lock = threading.Lock()
        self.close_lock = threading.Lock()
        self.capture_error = None
        self.reader = threading.Thread(target=self._capture, name="material-ui-process-log", daemon=True)

    def start(self) -> None:
        self.reader.start()

    def _capture(self) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("w+b") as output:
                while chunk := self.process.stdout.read1(65536):
                    with self.log_lock:
                        if output.tell() + len(chunk) > self.owner.output_limit:
                            output.seek(max(0, output.tell() - self.owner.tail_bytes))
                            previous = output.read(self.owner.tail_bytes)
                            output.seek(0)
                            output.truncate()
                            output.write((previous + chunk)[-self.owner.output_limit:])
                        else:
                            output.write(chunk[-self.owner.output_limit:])
                        output.flush()
            self.process.wait()
        except OSError as error:
            self.capture_error = f"Prozessprotokoll konnte nicht geschrieben werden: {error}"
            self.owner.terminate(self.process)
            self.process.wait()
        finally:
            self.process.stdout.close()
            self.owner.release(self)

    def tail(self, lines: int = 20) -> str:
        if self.capture_error:
            return self.capture_error
        try:
            with self.log_lock, self.log_path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - self.owner.tail_bytes))
                return "\n".join(handle.read(self.owner.tail_bytes).decode("utf-8", errors="replace").splitlines()[-lines:])
        except FileNotFoundError:
            return ""

    def close(self) -> None:
        with self.close_lock:
            try:
                if self.process.poll() is None:
                    os.killpg(self.process.pid, signal.SIGINT)
                    try:
                        self.process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        self.owner.terminate(self.process)
                self.owner.terminate(self.process)
                self.process.wait(timeout=5)
            except ProcessLookupError:
                pass
            self.reader.join(timeout=5)
            self.owner.release(self)
