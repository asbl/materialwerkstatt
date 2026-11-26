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
@pytest.mark.parametrize("name", ["Punkte", "punkte"])
@pytest.mark.parametrize("amount,label", [("1", "1"), ("2", "2"), ("0", "0"),
                                          ("0,5", "0,5"), ("1.5", "1,5")])
def test_points_preserve_surrounding_text_and_punctuation(target, name, amount, label):
    result = render(f"**a)** 56 [{name} {amount}], danach [Punkte 2].", target)
    assert result.returncode == 0, result.stderr
    assert f"{label} P." in result.stdout
    assert "2 P." in result.stdout
    assert ", danach" in " ".join(result.stdout.split())
    assert result.stdout.rstrip().endswith(".")
    assert f"[{name}" not in result.stdout
    if target == "typst":
        assert 'fill: rgb("#1565c0"), weight: "bold"' in result.stdout
    else:
        assert "\\textcolor[HTML]{1565C0}{\\textbf{" in result.stdout


@pytest.mark.parametrize("source", ["[Punkte]", "[Punkte -1]", "[Punkte abc]",
                                    "[Punkte 1.2.3]", "[Punkte 1pt]"])
def test_invalid_points_explain_valid_syntax(source):
    result = render(source, "typst")
    assert result.returncode != 0
    assert "Punkte: Bitte eine nicht negative Zahl" in result.stderr
