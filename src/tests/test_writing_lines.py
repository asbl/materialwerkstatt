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
@pytest.mark.parametrize("marker,count", [("[Schreiblinien]", 1), ("[Schreiblinien 2]", 2)])
def test_writing_lines_use_available_width_and_requested_count(target, marker, count):
    result = render(marker, target)
    assert result.returncode == 0, result.stderr
    assert "[Schreiblinien" not in result.stdout
    if target == "typst":
        assert f"range({count})" in result.stdout
        assert "length: 100%" in result.stdout
        assert "height: 8mm" in result.stdout
    else:
        assert result.stdout.count("\\vbox to 8mm") == count
        assert "{\\linewidth}" in result.stdout


@pytest.mark.parametrize("count", ["0", "31", "-2", "1.5", "abc"])
def test_invalid_line_counts_produce_helpful_error(count):
    result = render(f"[Schreiblinien {count}]", "typst")
    assert result.returncode != 0
    assert "Schreiblinien: Bitte 1 bis 30 Zeilen" in result.stderr
