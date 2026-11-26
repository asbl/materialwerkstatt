from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import time
from pathlib import Path

from material_ui.desktop import state_home
from material_ui.errors import InvalidInput


MAX_QMD_BYTES = 24 * 1024 * 1024
IMPORT_TTL = 24 * 60 * 60


def pending_path(token: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{48}", token):
        raise InvalidInput("Ungültiger Importauftrag.")
    return state_home() / "imports" / f"{token}.json"


def stage_import(source: Path) -> str:
    with source.open("rb") as handle:
        content = handle.read(MAX_QMD_BYTES + 1)
    if len(content) > MAX_QMD_BYTES:
        raise InvalidInput("Die QMD darf höchstens 24 MiB groß sein.")
    text = content.decode("utf-8")
    token = secrets.token_hex(24)
    destination = pending_path(token)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for candidate in destination.parent.glob("*.json"):
        try:
            if time.time() - candidate.stat().st_mtime > IMPORT_TTL:
                candidate.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"source": str(source), "name": source.name, "text": text}, handle)
    return token


def pending_import(token: str) -> dict[str, str]:
    source = pending_path(token)
    if not source.exists() or time.time() - source.stat().st_mtime > IMPORT_TTL:
        raise FileNotFoundError("Der Importauftrag ist abgelaufen. Bitte die QMD erneut öffnen.")
    return json.loads(source.read_text(encoding="utf-8"))


def commit_import(token: str, destination: Path) -> None:
    data = pending_import(token)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".qmd-import-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data["text"].encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    pending_path(token).unlink(missing_ok=True)
