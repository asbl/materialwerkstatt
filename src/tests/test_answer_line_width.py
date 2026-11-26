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
@pytest.mark.parametrize("name", ["antwortlinie", "Antwortlinie"])
@pytest.mark.parametrize("distance,normalized", [
    ("1cm", "1cm"), ("1,5cm", "1.5cm"), ("15 mm", "15mm"), ("12pt", "12pt"),
])
def test_answer_line_width_inside_text(target, name, distance, normalized):
    result = render(f"Vorher [{name} {distance}], danach [{name} 2cm].", target)
    assert result.returncode == 0, result.stderr
    expected = (f"\\antwortlinie[{normalized}]" if target == "latex"
                else f"#antwortlinie(width: {normalized})")
    assert expected in result.stdout
    assert ", danach" in result.stdout
    assert result.stdout.rstrip().endswith(".")
    assert result.stdout.index("Vorher") < result.stdout.index(expected) < result.stdout.index("danach")
    assert ("\\antwortlinie[2cm]" if target == "latex" else "#antwortlinie(width: 2cm)") in result.stdout
    assert f"[{name}" not in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("name", ["antwortlinie", "Antwortlinie"])
def test_answer_line_without_width_preserves_default(target, name):
    result = render(f"[{name}]", target)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("\\antwortlinie" if target == "latex" else "#antwortlinie()")


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("name", ["antwortlinie", "Antwortlinie"])
@pytest.mark.parametrize("keyword", ["füllend", "fuellend"])
def test_answer_line_fill_keyword_inside_text(target, name, keyword):
    result = render(f"Vorher [{name} {keyword}], danach [{name} 2cm].", target)
    assert result.returncode == 0, result.stderr
    expected = ("\\antwortlinie[\\linewidth]" if target == "latex"
                else "#antwortlinie(width: 100%)")
    assert expected in result.stdout
    assert ", danach" in result.stdout
    assert result.stdout.index("Vorher") < result.stdout.index(expected) < result.stdout.index("danach")
    assert (("\\antwortlinie[2cm]" if target == "latex" else "#antwortlinie(width: 2cm)")) in result.stdout
    assert f"[{name}" not in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_answer_line_fill_keyword_inside_table_cell(target):
    source = (
        "| Aufgabe | Lösung |\n"
        "|---|---|\n"
        "| a) $2^3$ | [Antwortlinie füllend] |\n"
    )
    result = render(source, target)
    assert result.returncode == 0, result.stderr
    expected = ("\\antwortlinie[\\linewidth]" if target == "latex"
                else "#antwortlinie(width: 100%)")
    assert expected in result.stdout


@pytest.mark.parametrize("distance", ["-1cm", "0cm", "abc", "1", "1.2.3cm", "1in", "füllend2"])
def test_invalid_answer_line_width_produces_helpful_error(distance):
    result = render(f"[antwortlinie {distance}]", "typst")
    assert result.returncode != 0
    assert "Antwortlinie: Bitte eine positive Breite" in result.stderr
