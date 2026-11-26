from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
FILTER = ROOT / "src/quarto/filters/exam.lua"
TEMPLATE = ROOT / "src/quarto/templates/exam-functions.typst"
pytestmark = pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")


def render(marker, target):
    return subprocess.run(
        ["quarto", "pandoc", "--from", "markdown", "--to", target,
         "--lua-filter", str(FILTER)],
        input=marker, text=True, capture_output=True, timeout=30,
    )


ROTATED_HINT = "::: {.hinweis-gedreht}\nLösungen: 1) 110; 2) 70\n:::\n"


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_rotated_hint_keeps_content_and_uses_dedicated_macro(target):
    result = render(ROTATED_HINT, target)
    assert result.returncode == 0, result.stderr
    assert "hinweis-gedreht" not in result.stdout
    assert "Lösungen: 1) 110; 2) 70" in result.stdout
    if target == "typst":
        assert "#hinweis_gedreht()[" in result.stdout
    else:
        assert "\\begin{hinweis}" in result.stdout


def test_normal_hint_stays_unrotated():
    result = render("::: {.hinweis}\nLösungen: 1) 110\n:::\n", "typst")
    assert result.returncode == 0, result.stderr
    assert "#hinweis()[" in result.stdout
    assert "hinweis_gedreht" not in result.stdout


def test_template_rotates_hint_text_upside_down():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "#let hinweis_gedreht(body)" in template
    assert "rotate(180deg)" in template
