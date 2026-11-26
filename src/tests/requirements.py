"""Voraussetzungen einzelner Tests, die nicht zum Werkzeugrepo gehoeren.

Inhalte liegen in eigenen (privaten) Repos (ihre Tests ebenfalls, siehe `inv test-inhalte`), H5P-Libraries werden nachgeladen und die
Praesentationsansicht wird erst mit npm gebaut. Fehlt etwas davon, werden die betroffenen
Tests mit Begruendung uebersprungen.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRESENT = ROOT / "src/excalideck/present"

needs_h5p_libraries = pytest.mark.skipif(
    not any((ROOT / ".h5p-runtime/libraries").glob("H5P.PythonQuestion-*")),
    reason="H5P-Libraries fehlen (inv kurse.update-h5p-libraries)",
)
needs_present_app = pytest.mark.skipif(
    not (PRESENT / "dist/index.html").is_file(),
    reason="Praesentationsansicht nicht gebaut (npm ci && npm run build in src/excalideck/present)",
)
needs_excalidraw_fonts = pytest.mark.skipif(
    not (PRESENT / "node_modules/@excalidraw/excalidraw").is_dir(),
    reason="Excalidraw-Schriften fehlen (npm ci in src/excalideck/present)",
)


def needs_content(relative: str):
    return pytest.mark.skipif(not (ROOT / relative).exists(), reason=f"Inhalte fehlen: {relative}")


