from __future__ import annotations

import hashlib
import errno
import os
import shutil
from pathlib import Path

from .filesystem import atomic_copy_file


def safe_member(directory: Path, relative: str) -> Path:
    member = Path(relative)
    if not relative or not member.parts or member.is_absolute() or any(part in {".", ".."} for part in member.parts):
        raise ValueError(f"Unsicherer Manifestpfad: {relative}")
    target = directory / member
    if not target.resolve().is_relative_to(directory.resolve()):
        raise ValueError(f"Manifestpfad liegt außerhalb des Exportordners: {relative}")
    for parent in (target, *target.parents):
        if parent == directory:
            break
        if parent.is_symlink():
            raise ValueError(f"Symlink im Exportpfad: {relative}")
    return target


def same_content(first: Path, second: Path) -> bool:
    first_stat, second_stat = first.stat(), second.stat()
    if (first_stat.st_dev, first_stat.st_ino) == (second_stat.st_dev, second_stat.st_ino):
        return True
    if first_stat.st_size != second_stat.st_size:
        return False
    with first.open("rb") as first_handle, second.open("rb") as second_handle:
        return hashlib.file_digest(first_handle, "sha256").digest() == hashlib.file_digest(second_handle, "sha256").digest()


def publish_files(staging: Path, destination: Path, previous: set[str], current: set[str], manifest: str) -> None:
    replacements = []
    stale = previous - current
    for relative in sorted(current | {manifest}):
        source = safe_member(staging, relative)
        target = safe_member(destination, relative)
        if not source.is_file():
            raise ValueError(f"Exportdatei fehlt: {relative}")
        if target.exists() and relative not in previous and relative != manifest:
            raise ValueError(f"Export würde eine fremde Datei überschreiben: {relative}")
        if target.exists() and not target.is_file():
            raise ValueError(f"Exportziel ist keine Datei: {relative}")
        if not target.exists() or source.stat().st_mode & 0o777 != target.stat().st_mode & 0o777 or not same_content(source, target):
            replacements.append(relative)
    replacements.sort(key=lambda relative: (relative == manifest, relative.endswith("index.html"), relative))
    backup = staging.parent / "backup"
    for relative in [*replacements, *sorted(stale)]:
        target = safe_member(destination, relative)
        if target.is_file():
            saved = safe_member(backup, relative)
            saved.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(target, saved)
            except OSError:
                shutil.copy2(target, saved)
    changed = []
    try:
        for relative in replacements:
            changed.append(relative)
            atomic_copy_file(safe_member(staging, relative), safe_member(destination, relative))
        for relative in sorted(stale):
            target = safe_member(destination, relative)
            if target.is_file():
                changed.append(relative)
                target.unlink()
    except BaseException:
        for relative in reversed(changed):
            target = safe_member(destination, relative)
            saved = safe_member(backup, relative)
            if saved.is_file():
                try:
                    saved.replace(target)
                except OSError as error:
                    if error.errno != errno.EXDEV:
                        raise
                    atomic_copy_file(saved, target)
            else:
                target.unlink(missing_ok=True)
        raise
    for relative in stale:
        parent = safe_member(destination, relative).parent
        while parent != destination:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
