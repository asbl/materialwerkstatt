from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import json
import time
import uuid
import re
from pathlib import Path

from material_core.filesystem import atomic_write_bytes, atomic_write_text
from material_ui.errors import InvalidInput
from material_ui.metadata import ensure_solution_metadata


class RevisionConflict(ValueError):
    pass


def revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocumentRepository:
    def __init__(self, history_limit: int = 20, history_bytes: int = 64 * 1024 * 1024) -> None:
        self.lock = threading.RLock()
        self.history_limit = history_limit
        self.history_bytes = history_bytes

    def read(self, path: Path) -> dict[str, str]:
        with self.lock:
            text = path.read_text(encoding="utf-8")
            return {"text": text, "revision": revision(text)}

    def check_revision(self, path: Path, expected: str | None) -> None:
        if expected is not None and self.read(path)["revision"] != expected:
            raise RevisionConflict("Die Datei wurde zwischenzeitlich geändert. Bitte neu laden.")

    def save(self, path: Path, text: str, expected: str | None = None) -> dict[str, str]:
        with self.lock:
            snapshot = self.read(path)
            if expected is not None and snapshot["revision"] != expected:
                raise RevisionConflict("Die Datei wurde zwischenzeitlich geändert. Bitte neu laden.")
            submitted = text
            try:
                text = ensure_solution_metadata(path, text)
            except ValueError:
                # Auch unvollständiges YAML muss während der Bearbeitung speicherbar bleiben.
                pass
            if text == snapshot["text"]:
                return {"revision": snapshot["revision"], **({"text": text} if text != submitted else {})}
            self.archive(path, snapshot)

            def validate():
                latest = self.read(path)
                if latest["revision"] != snapshot["revision"]:
                    self.archive(path, latest)
                    raise RevisionConflict("Die Datei wurde während des Speicherns extern geändert. Bitte Fassungen vergleichen.")

            atomic_write_text(path, text, before_replace=validate)
            return {"revision": revision(text), **({"text": text} if text != submitted else {})}

    def history_dir(self, path: Path) -> Path:
        directory = path.parent / ".material-history" / path.name
        if not directory.resolve().is_relative_to(path.parent.resolve()):
            raise InvalidInput("Ungültiger Versionsordner.")
        return directory

    def archive(self, path: Path, snapshot: dict[str, str]) -> None:
        directory = self.history_dir(path)
        identifier = f"{time.time_ns()}-{uuid.uuid4().hex}"
        atomic_write_text(directory / f"{identifier}.json", json.dumps({**snapshot, "created": time.time()}))
        used = 0
        for index, entry in enumerate(sorted(directory.glob("*.json"), reverse=True)):
            used += entry.stat().st_size
            if index >= self.history_limit or (index > 0 and used > self.history_bytes):
                entry.unlink()

    def history(self, path: Path) -> list[dict]:
        with self.lock:
            entries = []
            for entry in sorted(self.history_dir(path).glob("*.json"), reverse=True):
                snapshot = self.history_snapshot(path, entry.stem)
                entries.append({"id": entry.stem, "created": snapshot["created"], "revision": snapshot["revision"]})
            return entries

    def history_snapshot(self, path: Path, identifier: str) -> dict:
        if not re.fullmatch(r"\d+-[a-f0-9]{32}", identifier):
            raise InvalidInput("Ungültige Version.")
        source = self.history_dir(path) / f"{identifier}.json"
        if source.is_symlink():
            raise InvalidInput("Ungültige Versionsdatei.")
        return json.loads(source.read_text(encoding="utf-8"))

    def insert(self, path: Path, markdown: str, expected: str | None = None) -> dict[str, str]:
        with self.lock:
            self.check_revision(path, expected)
            text = self.read(path)["text"]
            marker = "<!-- material-ui -->"
            if marker in text:
                text = text.replace(marker, markdown.rstrip() + "\n\n" + marker, 1)
            else:
                text = text + ("" if text.endswith("\n") else "\n") + markdown.lstrip()
            return self.save(path, text)
