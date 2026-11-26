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


KARTEN = (
    "[Karten: Paare gesucht]\n\n"
    "Finde die Paare.\n\n"
    "- A: $a^2 \\cdot a^3$\n"
    "- B: $(a \\cdot b)^3$\n"
    "- C: $a^5$\n"
    "- D: $b^7$\n\n"
    "[/Karten]"
)


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_kartensatz_mit_titel_und_grid(target):
    result = render(KARTEN, target)
    assert result.returncode == 0, result.stderr
    if target == "latex":
        assert "\\begin{kartensatz}{Paare gesucht}" in result.stdout
        assert "\\end{kartensatz}" in result.stdout
        assert "\\begin{tabularx}{\\linewidth}{@{}*{3}{X}@{}}" in result.stdout
        assert "\\kartezelle{A}{\\(a^2 \\cdot a^3\\)}" in result.stdout
        assert "\\kartezelle{B}{\\((a \\cdot b)^3\\)}" in result.stdout
        assert " \\\\\n\\kartezelle{D}" in result.stdout
    else:
        assert '#kartensatz("Paare gesucht")[' in result.stdout
        assert result.stdout.rstrip().endswith("]")
        assert "#kartengrid(3," in result.stdout
        assert 'karte("A", [$a^2 dot.op a^3$])' in result.stdout
        assert 'karte("D", [$b^7$])' in result.stdout
    assert "Finde die Paare." in result.stdout
    assert "[Karten" not in result.stdout
    assert "[/Karten]" not in result.stdout
    assert "- A:" not in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_kartensatz_ohne_titel(target):
    result = render("[Karten]\n\n- A: $x^2$\n\n[/Karten]", target)
    assert result.returncode == 0, result.stderr
    if target == "latex":
        assert "\\begin{kartensatz}{}" in result.stdout
        assert "\\kartezelle{A}" in result.stdout
    else:
        assert "#kartensatz(none)[" in result.stdout
        assert 'karte("A", [$x^2$])' in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_karte_ohne_label_ist_ganze_karte(target):
    result = render("[Karten]\n\n- Karte ohne Label: $x^2$\n\n[/Karten]", target)
    assert result.returncode == 0, result.stderr
    if target == "latex":
        assert "\\kartezelle{}{Karte ohne Label: \\(x^2\\)}" in result.stdout
    else:
        assert "karte(none, [Karte ohne Label: $x^2$])" in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_karten_spalten_option(target):
    result = render("[Karten | spalten=4]\n\n- A: $x^2$\n\n[/Karten]", target)
    assert result.returncode == 0, result.stderr
    if target == "latex":
        assert "\\begin{tabularx}{\\linewidth}{@{}*{4}{X}@{}}" in result.stdout
    else:
        assert "#kartengrid(4," in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_karten_unbekannte_option_meldet_fehler(target):
    result = render("[Karten | farbe=rot]\n\n- A: $x^2$\n\n[/Karten]", target)
    assert result.returncode != 0
    assert "Unbekannte Option farbe" in result.stderr


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_karten_spalten_ausserhalb_meldet_fehler(target):
    result = render("[Karten | spalten=9]\n\n- A: $x^2$\n\n[/Karten]", target)
    assert result.returncode != 0
    assert "spalten" in result.stderr
