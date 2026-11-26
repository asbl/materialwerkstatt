from __future__ import annotations

import os
import hashlib
import shutil
import tempfile
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes, *, overwrite: bool = True, before_replace=None, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            temporary.chmod(mode)
        if overwrite:
            if mode is None and path.exists():
                temporary.chmod(path.stat().st_mode & 0o777)
            if before_replace is not None:
                before_replace()
            temporary.replace(path)
        else:
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def text_revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, text: str, *, overwrite: bool = True, before_replace=None, mode: int | None = None) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), overwrite=overwrite, before_replace=before_replace, mode=mode)


def atomic_copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            with source.open("rb") as original:
                shutil.copyfileobj(original, handle)
            handle.flush()
            os.fsync(handle.fileno())
        shutil.copystat(source, temporary)
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
