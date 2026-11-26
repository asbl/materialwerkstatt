from pathlib import Path
import shutil
import subprocess

import pytest


FILTER = Path(__file__).resolve().parents[2] / "src/quarto/filters/exam.lua"
pytestmark = pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")


def render(marker, target):
    return subprocess.run(
        ["quarto", "pandoc", "--from", "markdown", "--to", target,
         "--lua-filter", str(FILTER)],
        input=marker, text=True, capture_output=True, timeout=30,
    )


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("name", ["Schülerfelder", "Schuelerfelder"])
@pytest.mark.parametrize("distance,normalized", [
    ("1cm", "1cm"), ("0,5cm", "0.5cm"), ("2.5 cm", "2.5cm"), ("0cm", "0cm"),
])
def test_student_fields_spacing_precedes_fields(target, name, distance, normalized):
    result = render(f"[{name} {distance}]", target)
    assert result.returncode == 0, result.stderr
    spacing = (f"\\par\\vspace*{{{normalized}}}" if target == "latex"
               else f"#v({normalized}, weak: false)")
    fields = "\\studentfields" if target == "latex" else "#student_fields()"
    assert spacing in result.stdout
    assert fields in result.stdout
    assert result.stdout.index(spacing) < result.stdout.index(fields)
    assert f"[{name}" not in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("name", ["Schülerfelder", "Schuelerfelder"])
def test_student_fields_without_spacing_preserves_output(target, name):
    result = render(f"[{name}]", target)
    assert result.returncode == 0, result.stderr
    expected = "\\studentfields" if target == "latex" else "#student_fields()"
    assert result.stdout.strip() == expected


@pytest.mark.parametrize("distance", ["-1cm", "abc", "1mm", "1.2.3cm"])
def test_invalid_student_fields_spacing_produces_helpful_error(distance):
    result = render(f"[Schülerfelder {distance}]", "typst")
    assert result.returncode != 0
    assert "Schülerfelder: Bitte einen nicht negativen Abstand in cm" in result.stderr
