from pathlib import Path
import shutil
import subprocess

import pytest


FILTER = Path(__file__).resolve().parents[1] / "quarto/filters/exam.lua"
pytestmark = pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")


def render(source, target):
    return subprocess.run(
        ["quarto", "pandoc", "--from", "markdown", "--to", target,
         "--lua-filter", str(FILTER)],
        input=source, text=True, capture_output=True, timeout=30,
    )


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("source", [
    "Text direkt vor dem Marker.\n[abstand 0.5cm]\n[Eingabetabelle 0.6cm]",
    "Einleitung\n\n[abstand 0.5cm]\n[Eingabetabelle 0.6cm]",
    "Siehe [Seitenumbruch] im Text.",
    "Erklärung [Schülerfelder] mitten im Absatz.",
])
def test_block_marker_inside_text_paragraph_produces_helpful_error(target, source):
    result = render(source, target)
    assert result.returncode != 0
    assert "eigenen Absatz" in result.stderr
    assert "Leerzeilen" in result.stderr


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_inline_answer_line_still_works_in_text(target):
    result = render("Ergebnis: [Antwortlinie 1.5cm] im Fließtext.", target)
    assert result.returncode == 0, result.stderr
    assert ("\\antwortlinie[1.5cm]" if target == "latex" else "#antwortlinie(width: 1.5cm)") in result.stdout
