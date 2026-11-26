from pathlib import Path
import shutil
import subprocess

import pytest


FILTER = Path(__file__).resolve().parents[1] / "quarto/filters/exam.lua"
TEMPLATES = Path(__file__).resolve().parents[1] / "quarto/templates"
pytestmark = pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")


def render(source, target):
    return subprocess.run(
        ["quarto", "pandoc", "--from", "markdown", "--to", target,
         "--lua-filter", str(FILTER)],
        input=source, text=True, capture_output=True, timeout=30,
    )


@pytest.mark.parametrize("target", ["typst", "latex"])
def test_input_table_without_height_keeps_previous_call(target):
    result = render("[Eingabetabelle]\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n[/Eingabetabelle]", target)
    assert result.returncode == 0, result.stderr
    assert ("#input_table()[" if target == "typst" else "\\begin{inputtable}") in result.stdout
    assert ("]" if target == "typst" else "\\end{inputtable}") in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("distance,typst_arg,latex_arg", [
    ("1.2cm", "row-height: 1.2cm", "[17.14pt]"),
    ("1,5cm", "row-height: 1.5cm", "[25.68pt]"),
    ("20 mm", "row-height: 20mm", "[39.91pt]"),
    ("30pt", "row-height: 30pt", "[13.00pt]"),
])
def test_input_table_height_is_passed_through(target, distance, typst_arg, latex_arg):
    result = render(f"[Eingabetabelle {distance}]\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n[/Eingabetabelle]", target)
    assert result.returncode == 0, result.stderr
    expected = (f"#input_table({typst_arg})[" if target == "typst"
                else f"\\begin{{inputtable}}{latex_arg}")
    assert expected in result.stdout


@pytest.mark.parametrize("distance", ["2m", "abc", "0cm", "-1cm", "1"])
def test_invalid_input_table_height_produces_helpful_error(distance):
    result = render(f"[Eingabetabelle {distance}]", "typst")
    assert result.returncode != 0
    assert "Eingabetabelle: Bitte eine positive Zeilenhöhe" in result.stderr


@pytest.mark.skipif(shutil.which("typst") is None, reason="Typst fehlt")
def test_input_table_row_height_renders_real_rows(tmp_path):
    body = render(
        "[Eingabetabelle 1cm]\n\n| Term | Lösung |\n|---|---|\n"
        "| $2^3$ | 8 |\n| $3^2$ | 9 |\n\n[/Eingabetabelle]",
        "typst",
    )
    assert body.returncode == 0, body.stderr
    design_header = (
        '#let ink = black\n#let primary = red\n#let primary-light = luma(240)\n'
        "#let light-gray = luma(240)\n#let mid-gray = luma(200)\n"
        "#let rule-gray = luma(170)\n#let warn = orange\n#let tip = green\n"
        '#let heading-font = "DejaVu Sans"\n#let body-font = "DejaVu Sans"\n'
        '#let mono-font = "DejaVu Sans Mono"\n'
    )
    (tmp_path / "exam-functions.typst").write_text(
        design_header + (TEMPLATES / "exam-functions.typst").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    main = tmp_path / "main.typ"
    main.write_text(
        '#import "exam-functions.typst": input_table\n'
        "#set page(width: 15cm, height: 6cm, margin: 1cm)\n"
        + body.stdout,
        encoding="utf-8",
    )
    compile_result = subprocess.run(
        ["typst", "compile", str(main), str(tmp_path / "main.pdf")],
        capture_output=True, text=True, timeout=60,
    )
    assert compile_result.returncode == 0, compile_result.stderr

    import pymupdf
    doc = pymupdf.open(tmp_path / "main.pdf")
    page = doc[0]
    borders = sorted({
        round(min(item[1].y, item[2].y), 1)
        for drawing in page.get_drawings()
        for item in drawing["items"]
        if item[0] == "l" and abs(item[1].y - item[2].y) < 0.5 and abs(item[1].x - item[2].x) > 50
    })
    heights = [round(bottom - top, 1) for top, bottom in zip(borders, borders[1:])]
    assert heights, "Keine Tabellenlinien gefunden"
    assert all(27.8 <= height <= 28.9 for height in heights), heights
