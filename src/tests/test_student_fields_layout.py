from pathlib import Path
import shutil
import subprocess

import pymupdf
import pytest

from material_core.builds import BuildService


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "src/quarto/templates"
pytestmark = pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")


def prepare_project(tmp_path):
    for template in TEMPLATES.glob("*.typst"):
        shutil.copy(template, tmp_path)
    shutil.copy(ROOT / "src/quarto/filters/exam.lua", tmp_path / "exam.lua")
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: default\nfilters:\n  - exam.lua\n"
        "template-partials:\n  - student-fields.typst\n  - exam-functions.typst\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("engine,position,markers", [
    ("pdf", "header", 1),
    ("typst", "body", 1),
    ("typst", "header", 0),
    ("typst", "header", 2),
])
def test_student_fields_position_and_local_exceptions(tmp_path, engine, position, markers):
    if engine == "pdf" and shutil.which("pdflatex") is None:
        pytest.skip("pdflatex fehlt")
    prepare_project(tmp_path)
    options = (
        f"  pdf:\n    template: {TEMPLATES / 'latex-template.tex'}\n"
        f"    include-in-header: {TEMPLATES / 'exam-header.tex'}\n    pdf-engine: pdflatex\n"
        if engine == "pdf" else "  typst:\n    template: exam-template.typst\n"
    )
    body = "# Lernmission\n\n" + "[Schülerfelder]\n\n" * markers + "Rechne im Heft.\n"
    source = tmp_path / "felder.qmd"
    source.write_text(
        f"---\nstudent-fields-position: {position}\nformat:\n{options}---\n\n{body}",
        encoding="utf-8",
    )
    result = BuildService(tmp_path, subprocess.run).build_document(source, error_summary=lambda output: output)
    with pymupdf.open(result.pdf_path) as document:
        assert len(document) == 1
        page = document[0]
        names, dates = page.search_for("Name:"), page.search_for("Datum:")
        assert len(names) == len(dates) == markers
        if not markers:
            return
        title = page.search_for("Lernmission")[0]
        if engine == "pdf":
            assert names[0].y0 >= 12
            assert max(names[0].y1, dates[0].y1) < title.y0
        else:
            assert all(name.y0 > title.y1 for name in names)


@pytest.mark.parametrize("filename,pages", [
    ("selbstdiagnose.qmd", 2),
    ("probeklausur.qmd", 4),
    ("ab_mathe-detektivwerkstatt.qmd", 4),
])
def test_real_worksheets_keep_pagination_with_fields_above_header(tmp_path, filename, pages):
    prepare_project(tmp_path)
    originals = ROOT / "unterricht/mathematik/klasse-05/lernstandsdiagnose/klassenarbeit-2026"
    if not (originals / filename).is_file():
        pytest.skip("Privates Unterrichtsbeispiel fehlt")
    for directory in ("src/quarto/template-releases", "src/quarto/_local/template-releases"):
        if (ROOT / directory).is_dir():
            shutil.copytree(ROOT / directory, tmp_path / directory)
    shutil.copytree(originals / "assets", tmp_path / "assets")
    source = tmp_path / filename
    source.write_text((originals / filename).read_text(encoding="utf-8"), encoding="utf-8")
    result = BuildService(tmp_path, subprocess.run).build_document(source, error_summary=lambda output: output)
    with pymupdf.open(result.pdf_path) as document:
        assert len(document) == pages
        assert len(document[0].search_for("Name:")) == 1
        assert len(document[0].search_for("Datum:")) == 1
        assert all(len(page.get_text()) > 100 for page in document), "Leere Überlaufseite"


def test_math_test_cover_keeps_fixed_date_above_title(tmp_path):
    prepare_project(tmp_path)
    source = tmp_path / "mathe-test.qmd"
    source.write_text(
        "---\nformat:\n  typst:\n    template: math-test-template.typst\n---\n\n"
        "[Mathe-Deckblatt: Lernmission | 31.10.2026]\n\nArbeite im Heft.\n\n[/Mathe-Deckblatt]\n",
        encoding="utf-8",
    )
    result = BuildService(tmp_path, subprocess.run).build_document(source, error_summary=lambda output: output)
    with pymupdf.open(result.pdf_path) as document:
        page = document[0]
        assert len(document) == 1
        assert page.search_for("Name:")[0].y1 < page.search_for("Lernmission")[0].y0
        assert page.search_for("31.10.2026")[0].y1 < page.search_for("Lernmission")[0].y0
