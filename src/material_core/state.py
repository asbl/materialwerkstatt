"""Ablage der Programmdaten im Inhaltsordner. Nur Standardbibliothek.

`daten/` traegt, was auf allen Rechnern gleich sein soll (Stundenplan, Planung, Tags) und
deshalb mitsynchronisiert wird. `.material-ui/` bleibt rechnerlokal (Job-Verlauf, Caches,
Zugangsdaten, Locks).
"""
from __future__ import annotations

import os
from pathlib import Path

SHARED_DIR = "daten"
LOCAL_DIR = ".material-ui"


def adopt(legacy: Path, target: Path) -> None:
    """Uebernimmt eine frueher lokal abgelegte Datei; Vorhandenes in `target` hat Vorrang."""
    if target.exists() or legacy.is_symlink() or not legacy.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(legacy, target)
    except FileNotFoundError:  # ein anderer Thread oder Prozess war schneller
        pass


def shared_file(root: Path, *parts: str) -> Path:
    """Pfad einer gemeinsamen Datei unter `<root>/daten/`, samt Uebernahme aus `.material-ui/`."""
    target = root.joinpath(SHARED_DIR, *parts)
    adopt(root.joinpath(LOCAL_DIR, *parts), target)
    return target
