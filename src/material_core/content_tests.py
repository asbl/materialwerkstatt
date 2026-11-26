"""Tests, die zu den Inhalten gehoeren: je Kurs `tests/` und die privaten Vorlagentests.

Sie liegen im Inhaltsordner (`unterricht/kurse/<kurs>/tests/`, `src/quarto/_local/tests/`) und
laufen mit dem Code aus dem Programmverzeichnis.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from material_core import workspace


def directories(root: Path, course: str = "") -> list[Path]:
    if course:
        found = [root / "unterricht" / "kurse" / course / "tests"]
    else:
        found = [*sorted(root.glob("unterricht/kurse/*/tests")), root / "src" / "quarto" / "_local" / "tests"]
    return [path for path in found if path.is_dir()]


def command(root: Path, targets: list[Path], python: str = sys.executable) -> list[str]:
    # Eigene Konfiguration: gleiche Dateinamen in verschiedenen Kursen sind erlaubt,
    # temporaere Dateien bleiben auf der Platte (nie /tmp).
    return [python, "-m", "pytest", *map(str, targets), "-q", "-c", os.devnull, f"--rootdir={root}",
            "--import-mode=importlib", "-p", "no:cacheprovider",
            f"--basetemp={root / 'build' / '.pytest-basetemp'}"]


def environment(root: Path) -> dict[str, str]:
    # Private Vorlagentests duerfen Helfer aus den Werkzeugtests importieren.
    paths = [str(workspace.CODE_SRC), str(workspace.CODE_SRC / "tests"), os.environ.get("PYTHONPATH", "")]
    return {**os.environ, workspace.ENV: str(root), "PYTHONPATH": os.pathsep.join(p for p in paths if p),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}


def run(root: Path, course: str = "", python: str = sys.executable) -> int:
    """Inhaltstests ausfuehren; 0 auch dann, wenn es keine gibt."""
    targets = directories(root, course)
    if not targets:
        print("Keine Inhaltstests gefunden.")
        return 0
    (root / "build").mkdir(exist_ok=True)
    return subprocess.run(command(root, targets, python), cwd=root, env=environment(root)).returncode
