from pathlib import Path
import shutil
import subprocess

import pymupdf
import pytest

from material_core.builds import BuildService


ROOT = Path(__file__).resolve().parents[2]
FILTER = ROOT / "src/quarto/filters/exam.lua"
TEMPLATES = ROOT / "src/quarto/templates"


def render_filter(source, target):
    return subprocess.run(
        ["quarto", "pandoc", "--from", "markdown", "--to", target,
         "--lua-filter", str(FILTER)],
        input=source, text=True, capture_output=True, timeout=30,
    )


@pytest.mark.parametrize("target,begin,end", [
    ("latex", "\\begin{miniab}", "\\end{miniab}"),
    ("typst", "#mini_ab()[", "]"),
])
def test_mini_ab_marker_translates_for_both_targets(target, begin, end):
    result = render_filter("[Mini-AB]\n\nText\n\n[/Mini-AB]", target)
    assert result.returncode == 0, result.stderr
    assert begin in result.stdout
    assert end in result.stdout


MINI_QMD = """---
title: Kopfübung
lang: de
format:
  {format}
---

[Mini-AB]

[Schülerfelder]

# Kopfübung: Potenzen

Berechne im Kopf.

[Eingabetabelle 0.6cm]

| $f(x) = x^2$ | $f(3) =$ [Antwortlinie füllend] | $f(10) =$ [Antwortlinie füllend] |
|---|---|---|
| $g(a) = a^3$ | $g(2) =$ [Antwortlinie füllend] | $g(10) =$ [Antwortlinie füllend] |

[/Eingabetabelle]

[/Mini-AB]
"""


def _write_project(tmp_path, format_block):
    shutil.copy(FILTER, tmp_path / "exam.lua")
    source = tmp_path / "ab_mini_test.qmd"
    source.write_text(MINI_QMD.format(format=format_block), encoding="utf-8")
    return source


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex fehlt")
def test_mini_ab_pdf_renders_content_twice_on_one_page(tmp_path):
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: default\n  render: ['*.qmd']\nfilters:\n  - exam.lua\n"
        "format:\n  pdf:\n    toc: false\n    keep-tex: true\n    pdf-engine: pdflatex\n"
        "    papersize: a4\n"
        f"    template: {TEMPLATES / 'latex-template.tex'}\n"
        f"    include-in-header: {TEMPLATES / 'exam-header.tex'}\n",
        encoding="utf-8",
    )
    source = _write_project(tmp_path, "pdf: {}")

    result = BuildService(tmp_path, subprocess.run).build_document(
        source, error_summary=lambda output: output
    )

    assert result.returncode == 0, result.stdout
    with pymupdf.open(result.pdf_path) as document:
        assert document.page_count == 1
        text = document[0].get_text()
        assert text.count("Kopfübung: Potenzen") == 2
        assert text.count("Name:") == 2
        assert text.count("g(10) =") == 2


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
@pytest.mark.skipif(shutil.which("typst") is None, reason="Typst fehlt")
@pytest.mark.parametrize("template_name", ["exam-template.typst", "worksheet-mini.typst"])
def test_mini_ab_typst_renders_content_twice_on_one_page(tmp_path, template_name):
    for template in (TEMPLATES).glob("*.typst"):
        shutil.copy(template, tmp_path)
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: default\nfilters:\n  - exam.lua\n"
        "template-partials:\n  - student-fields.typst\n  - exam-functions.typst\n  - worksheet-design.typst\n",
        encoding="utf-8",
    )
    source = _write_project(
        tmp_path, f"typst:\n    template: {TEMPLATES / template_name}"
    )

    result = BuildService(tmp_path, subprocess.run).build_document(
        source, error_summary=lambda output: output
    )

    assert result.returncode == 0, result.stdout
    with pymupdf.open(result.pdf_path) as document:
        assert document.page_count == 1
        text = document[0].get_text()
        assert text.count("Kopfübung: Potenzen") == 2
        assert text.count("Name:") == 2
