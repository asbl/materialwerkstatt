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
@pytest.mark.parametrize("name", ["abstand", "Abstand"])
@pytest.mark.parametrize("distance,normalized", [
    ("1cm", "1cm"), ("0,5cm", "0.5cm"), ("2.5 mm", "2.5mm"),
    ("12pt", "12pt"), ("0cm", "0cm"),
])
def test_vertical_spacing_between_paragraphs(target, name, distance, normalized):
    result = render(f"Davor\n\n[{name} {distance}]\n\nDanach", target)
    assert result.returncode == 0, result.stderr
    expected = (f"\\par\\vspace*{{{normalized}}}" if target == "latex"
                else f"#v({normalized}, weak: false)")
    assert expected in result.stdout
    assert result.stdout.index("Davor") < result.stdout.index(expected) < result.stdout.index("Danach")
    assert f"[{name}" not in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("marker", [
    "[abstand]", "[abstand -1cm]", "[abstand abc]", "[abstand 1]",
    "[abstand 1.2.3cm]", "[abstand 1in]",
])
def test_invalid_vertical_spacing_produces_helpful_error(target, marker):
    result = render(marker, target)
    assert result.returncode != 0
    assert "Abstand: Bitte einen nicht negativen Abstand" in result.stderr
