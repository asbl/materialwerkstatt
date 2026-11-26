from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from material_core import workspace

# WISSENSBASIS_ROOT lets the tests run against a throw-away project tree.
ROOT = Path(os.environ.get("WISSENSBASIS_ROOT") or workspace.root())
WISSEN = ROOT / "wissen"
CACHE = WISSEN / ".cache"
TEXT_CACHE = CACHE / "text"
INDEX_DB = CACHE / "index.sqlite"
SOURCE_PREFIX = "quellen-"
STRUCTURED_SOURCES = Path("ressourcen") / "quellen"


@dataclass(frozen=True)
class Fach:
    name: str

    @property
    def quellen(self) -> Path:
        structured = ROOT / STRUCTURED_SOURCES / self.name
        if structured.exists():
            return structured
        return ROOT / f"{SOURCE_PREFIX}{self.name}"

    @property
    def wissen(self) -> Path:
        return WISSEN / self.name

    @property
    def manifest(self) -> Path:
        return self.wissen / "_system" / "manifest.json"

    @property
    def quellenarten(self) -> Path:
        return self.wissen / "_config" / "quellenarten.yaml"

    @property
    def taxonomie(self) -> Path:
        return self.wissen / "_config" / "taxonomie.yaml"

    @property
    def dossiers(self) -> Path:
        return self.wissen / "quellen"

    @property
    def karten(self) -> Path:
        return self.wissen / "karten"

    @property
    def vorlagen(self) -> Path:
        return self.wissen / "vorlagen"

    @property
    def bilder(self) -> Path:
        return self.wissen / "bilder"


def discover(only: str | None = None) -> list[Fach]:
    """Every folder ressourcen/quellen/<fach>/ or quellen-<fach>/ is one subject."""
    names = {
        path.name
        for path in sorted((ROOT / STRUCTURED_SOURCES).glob("*"))
        if path.is_dir()
    }
    names.update(
        path.name.removeprefix(SOURCE_PREFIX)
        for path in sorted(ROOT.glob(f"{SOURCE_PREFIX}*"))
        if path.is_dir()
    )
    faecher = [Fach(name) for name in sorted(names)]
    if only is None:
        return faecher
    selected = [fach for fach in faecher if fach.name == only]
    if not selected:
        known = ", ".join(fach.name for fach in faecher) or "keine"
        raise SystemExit(f"Unbekanntes Fach '{only}'. Vorhanden: {known}")
    return selected
