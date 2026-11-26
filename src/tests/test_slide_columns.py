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


COLUMNS_MD = """\
::: {.columns}
::: {.column width="55%"}
Linke Spalte

- Punkt A
:::
::: {.column}
Rechte Spalte
:::
:::
"""


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_columns_place_content_side_by_side(target):
    result = render(COLUMNS_MD, target)
    assert result.returncode == 0, result.stderr
    assert "Linke Spalte" in result.stdout
    assert "Rechte Spalte" in result.stdout
    if target == "typst":
        assert "#grid(columns: (55fr, 45fr), column-gutter: 10pt, align: top," in result.stdout
        assert result.stdout.index("Linke Spalte") < result.stdout.index("Rechte Spalte")
    else:
        assert "\\noindent\\begin{minipage}[t]{0.5390\\linewidth}" in result.stdout
        assert "\\noindent\\begin{minipage}[t]{0.4410\\linewidth}" in result.stdout
        assert result.stdout.index("Linke Spalte") < result.stdout.index("Rechte Spalte")


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_columns_without_widths_split_equally(target):
    source = """\
::: {.columns}
::: {.column}
Eins
:::
::: {.column}
Zwei
:::
:::
"""
    result = render(source, target)
    assert result.returncode == 0, result.stderr
    if target == "typst":
        assert "#grid(columns: (50fr, 50fr), column-gutter: 10pt, align: top," in result.stdout
    else:
        assert "\\begin{minipage}[t]{0.4900\\linewidth}" in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_columns_partial_widths_share_remainder(target):
    source = """\
::: {.columns}
::: {.column width="60%"}
Eins
:::
::: {.column}
Zwei
:::
::: {.column}
Drei
:::
:::
"""
    result = render(source, target)
    assert result.returncode == 0, result.stderr
    if target == "typst":
        assert "#grid(columns: (60fr, 20fr, 20fr), column-gutter: 10pt, align: top," in result.stdout
    else:
        assert "\\begin{minipage}[t]{0.5760\\linewidth}" in result.stdout
        assert "\\begin{minipage}[t]{0.1920\\linewidth}" in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_columns_accept_german_aliases(target):
    source = """\
::: {.spalten}
::: {.spalte breite="60%"}
Eins
:::
::: {.spalte}
Zwei
:::
:::
"""
    result = render(source, target)
    assert result.returncode == 0, result.stderr
    if target == "typst":
        assert "#grid(columns: (60fr, 40fr), column-gutter: 10pt, align: top," in result.stdout
    else:
        assert "\\begin{minipage}[t]{0.5880\\linewidth}" in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_columns_with_single_column_stays_plain_div(target):
    source = """\
::: {.columns}
::: {.column}
Einzeln
:::
:::
"""
    result = render(source, target)
    assert result.returncode == 0, result.stderr
    assert "Einzeln" in result.stdout
    if target == "typst":
        assert "#grid(" not in result.stdout
    else:
        assert "\\begin{minipage}" not in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_columns_reject_widths_summing_to_100(target):
    source = """\
::: {.columns}
::: {.column width="70%"}
Eins
:::
::: {.column width="40%"}
Zwei
:::
:::
"""
    result = render(source, target)
    assert result.returncode != 0
    assert "unter 100 Prozent" in result.stderr


def test_columns_latex_keeps_hfill_glued_across_multi_paragraph_cells():
    # Separate RawBlocks around \end{minipage}/\hfill/\begin{minipage} make
    # Pandoc insert a blank line, which LaTeX reads as \par and breaks the
    # \hfill out of the horizontal list -- columns stack instead of sitting
    # side by side. Only reproduces with >1 block per cell (real content),
    # not the single-paragraph cells used in the other tests here.
    source = """\
::: {.columns}
::: {.column}
Erster Absatz links.

Zweiter Absatz links.
:::
::: {.column}
Rechts.
:::
:::
"""
    result = render(source, "latex")
    assert result.returncode == 0, result.stderr
    assert "\\end{minipage}\n\\hfill\n\\noindent\\begin{minipage}" in result.stdout


def test_columns_trennlinien_errors_on_latex_instead_of_silently_dropping():
    # trennlinien is only drawn for Typst (column_separator is never called
    # in the LaTeX branch). Rather than silently ignore the attribute on
    # LaTeX builds, it must fail loudly so an author notices the gap.
    source = """\
::: {.columns trennlinien="gestrichelt"}
::: {.column}
Eins
:::
::: {.column}
Zwei
:::
:::
"""
    result = render(source, "latex")
    assert result.returncode != 0
    assert "trennlinien wird bisher nur fuer Typst gezeichnet" in result.stderr


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_columns_reject_invalid_width(target):
    source = """\
::: {.columns}
::: {.column width="7cm"}
Eins
:::
::: {.column}
Zwei
:::
:::
"""
    result = render(source, target)
    assert result.returncode != 0
    assert "Prozentwert" in result.stderr
