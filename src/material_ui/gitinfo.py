from __future__ import annotations

import subprocess
import threading
from pathlib import Path

MAX_DIFF_BYTES = 64 * 1024


class GitService:
    """Liest Status, Diff und letzten Commit einer Datei aus dem Repository-Git."""

    def __init__(self, config, processes) -> None:
        self.config = config
        self.processes = processes
        self._inside_lock = threading.Lock()
        self._inside_work_tree: bool | None = None

    def _run(self, arguments: list[str], timeout: float = 5.0):
        return self.processes.run(
            ["git", *arguments],
            timeout=timeout,
            cwd=str(self.config.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def _is_inside_work_tree(self) -> bool:
        """Ob config.root ein Git-Arbeitsverzeichnis ist, aendert sich nicht waehrend
        die App laeuft; einmal pro Prozess pruefen statt bei jeder Dateiauswahl."""
        with self._inside_lock:
            if self._inside_work_tree is None:
                result = self._run(["rev-parse", "--is-inside-work-tree"])
                self._inside_work_tree = result.returncode == 0 and result.stdout.strip() == "true"
            return self._inside_work_tree

    def document_info(self, source: Path) -> dict:
        relative = self.config.relative(source)
        if not self._is_inside_work_tree():
            return {"available": False, "reason": "Das Repository ist kein Git-Arbeitsverzeichnis."}
        status = self._run(["status", "--porcelain", "--", relative])
        changed = bool(status.stdout.strip())
        # Ohne Statusaenderung ist ein Diff garantiert leer; den Subprozess dafuer sparen.
        diff_stdout = self._run(["diff", "--", relative]).stdout if changed else ""
        last = self._run(["log", "-1", "--format=%h %ad %s", "--date=short", "--", relative])
        return {
            "available": True,
            "path": relative,
            "status": status.stdout.strip(),
            "changed": changed,
            "diff": diff_stdout[:MAX_DIFF_BYTES],
            "diff_truncated": len(diff_stdout) > MAX_DIFF_BYTES,
            "last_commit": last.stdout.strip() if last.returncode == 0 else "",
        }
