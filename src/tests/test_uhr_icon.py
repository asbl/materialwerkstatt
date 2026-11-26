from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
FILTER = ROOT / "src/quarto/filters/exam.lua"
pytestmark = pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")


def render(marker, target):
    return subprocess.run(
        ["quarto", "pandoc", "--from", "markdown", "--to", target,
         "--lua-filter", str(FILTER)],
        input=marker, text=True, capture_output=True, timeout=30,
    )


@pytest.mark.parametrize("target,expected", [("typst", "#uhr()"), ("latex", "\\uhr")])
def test_clock_marker_becomes_macro_and_keeps_heading_text(target, expected):
    result = render("## [Uhr] Kopf-Blitz 1 · Vor den Tricks", target)
    assert result.returncode == 0, result.stderr
    assert "[Uhr]" not in result.stdout
    assert expected in result.stdout
    assert "Kopf-Blitz 1" in result.stdout


def test_clock_marker_works_inline_in_text():
    result = render("Stoppe die Zeit: [Uhr] und vergleiche.", "typst")
    assert result.returncode == 0, result.stderr
    assert "[Uhr]" not in result.stdout
    assert "#uhr()" in result.stdout
    assert "vergleiche" in result.stdout
