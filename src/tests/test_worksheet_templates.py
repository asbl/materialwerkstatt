from pathlib import Path
import re
import shutil
import subprocess

import pymupdf
import pytest

from material_core.builds import BuildService
from material_core.template_roots import all_template_files, all_template_names, find_template, is_private, template_path
from material_ui.documents import TEMPLATE_DEFINITIONS, WORKSHEET_DESIGNS


ROOT = Path(__file__).resolve().parents[2]


def private_names(pattern: str) -> list[str]:
    """Nicht eingebaute (private) Vorlagen, die zum Muster passen; ohne private Vorlagen leer."""
    return sorted(name for name in all_template_names()
                  if re.fullmatch(pattern, name) and not name.endswith(("-layout.typst", "-functions.typst"))
                  and is_private(find_template(name)))


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
@pytest.mark.parametrize("template", [
    *(f"worksheet-{design['id']}.typst" for design in WORKSHEET_DESIGNS),
    "selbstdiagnose-template.typst", "exam-template.typst", "math-test-template.typst", "nachpruefung-template.typst",
    *(name for name in private_names(r"(?:exam|worksheet)-[\w-]+\.typst")
      if name not in {f"worksheet-{design['id']}.typst" for design in WORKSHEET_DESIGNS}
      and not name.startswith("worksheet-mini")),
])
def test_worksheet_designs_and_legacy_templates_render(tmp_path, template):
    for source in [path for path in all_template_files() if path.suffix == ".typst"]:
        shutil.copy(source, tmp_path)
    shutil.copy(ROOT / "src/quarto/filters/exam.lua", tmp_path)
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: default\nfilters:\n  - exam.lua\n"
        "template-partials:\n  - student-fields.typst\n  - exam-functions.typst\n  - worksheet-design.typst\n  - slide-layout.typst\n", encoding="utf-8"
    )
    fields = "[Schülerfelder]\n\n"
    answer_space = "" if template in {"math-test-template.typst", "selbstdiagnose-template.typst"} else "[Antwortkasten: 1cm]\n\n"
    source = tmp_path / "arbeitsblatt.qmd"
    source.write_text(
        f"---\ntitle: Lernmission\nformat:\n  typst:\n    template: {template}\n---\n\n"
        f"{fields}# Zahlen entdecken\n\nBerechne $2^3$.\n\n"
        "[Infobox: Merke]\n\nPotenzen sind Produkte gleicher Faktoren.\n\n[/Infobox]\n\n"
        f"{answer_space}[Seitenumbruch]\n\n"
        "## Weiterdenken\n\nBerechne $3^2$.\n",
        encoding="utf-8",
    )

    result = BuildService(tmp_path, subprocess.run).build_document(source, error_summary=lambda output: output)

    assert result.returncode == 0, result.stdout
    with pymupdf.open(result.pdf_path) as document:
        assert document.page_count == 2
        assert "Zahlen entdecken" in document[0].get_text()
        assert "Weiterdenken" in document[1].get_text()
        if fields:
            assert "Name:" in document[0].get_text()
            names = document[0].search_for("Name:")
            dates = document[0].search_for("Datum:")
            assert len(names) == len(dates) == 1
            titles = document[0].search_for("Lernmission") or document[0].search_for("Zahlen entdecken")
            assert names[0].y0 >= 12, "Namensfeld liegt zu nah am Papierrand"
            assert max(names[0].y1, dates[0].y1) < min(item.y0 for item in titles), "Schülerfelder müssen über dem Titel liegen"
            writing_lines = [
                abs(item[2].x - item[1].x)
                for drawing in document[0].get_drawings() for item in drawing["items"]
                if item[0] == "l" and abs(item[2].y - item[1].y) < 0.1
                and names[0].y0 <= item[1].y <= names[0].y1 + 6
            ]
            assert any(width > 200 for width in writing_lines), "Namenslinie muss mindestens 7 cm breit sein"
            assert sum(width >= 100 for width in writing_lines) >= 2, "Eigene Schreiblinie fürs Datum fehlt"
        design = next((item for item in WORKSHEET_DESIGNS if template == f"worksheet-{item['id']}.typst"), None)
        if design and not is_private(find_template(template)):
            if design.get("hides_label"):
                # Symbolfreie Titel: das Design nennt sich nicht im Text, Namensfeld steht auch auf Seite 2.
                assert design["label"] not in "".join(page.get_text() for page in document)
                assert "Name:" in document[1].get_text()
            else:
                assert design["label"] in document[1].get_text()
            for page in document:
                footer = page.get_text(clip=pymupdf.Rect(0, page.rect.height - 45, page.rect.width, page.rect.height))
                assert design["label"] not in footer
                assert str(page.number + 1) in footer


def test_catalog_keeps_legacy_paths_and_plain_names():
    for filename in ["latex-template.tex", "slides-template.tex", "exam-template.typst",
                     "math-test-template.typst", "nachpruefung-template.typst", "foerderplan-template.typst"]:
        assert any(entry["path"] == f"src/quarto/templates/{filename}" for entry in TEMPLATE_DEFINITIONS)
    for entry in TEMPLATE_DEFINITIONS:
        assert "Typst" not in entry["label"]
        assert "LaTeX" not in entry["label"]
        assert template_path(entry["path"]).is_file()


# Templates ohne eigene Box-Definitionen brechen beim Rendern von
# [Infobox: ...]-Markern mit "unknown variable: infobox" ab; der
# exam.lua-Filter ruft die Makros fuer jede Typst-Vorlage auf.
BOX_TEMPLATES = [
    *private_names(r"slide-[\w-]+\.typst"),
    "slide-template.typst",
    "deck-template.typst",
    "selbstdiagnose-template.typst",
    "feedbackbogen-template.typst",
    "foerderplan-template.typst",
]


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
@pytest.mark.parametrize("template", BOX_TEMPLATES)
def test_box_templates_render_infobox(tmp_path, template):
    for source in [path for path in all_template_files() if path.suffix == ".typst"]:
        shutil.copy(source, tmp_path)
    shutil.copy(ROOT / "src/quarto/filters/exam.lua", tmp_path)
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: default\nfilters:\n  - exam.lua\n"
        "template-partials:\n  - student-fields.typst\n  - exam-functions.typst\n  - worksheet-design.typst\n  - slide-layout.typst\n", encoding="utf-8"
    )
    source = tmp_path / "kasten.qmd"
    source.write_text(
        f"---\ntitle: Kasten\nformat:\n  typst:\n    template: {template}\n---\n\n"
        "[Infobox: Wichtiger Hinweis]\n\nText im Kasten\n\n[/Infobox]\n",
        encoding="utf-8",
    )

    result = BuildService(tmp_path, subprocess.run).build_document(source, error_summary=lambda output: output)

    assert result.returncode == 0, result.stdout
    with pymupdf.open(result.pdf_path) as document:
        text = "".join(page.get_text() for page in document)
        assert "Wichtiger Hinweis" in text
        assert "Text im Kasten" in text


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
@pytest.mark.parametrize("template,diagnosis", [
    ("worksheet-mini.typst", False),
    *((name, False) for name in private_names(r"worksheet-mini-[\w-]+\.typst")),
    ("worksheet-mini.typst", True),
])
@pytest.mark.parametrize("fontsize", [11, 14])
def test_mini_layout_preserves_font_and_prints_clean_cut_and_answer_areas(tmp_path, template, diagnosis, fontsize):
    for partial in [path for path in all_template_files() if path.suffix == ".typst"]:
        shutil.copy(partial, tmp_path)
    shutil.copy(ROOT / "src/quarto/filters/exam.lua", tmp_path)
    (tmp_path / "_quarto.yml").write_text("project:\n  type: default\nfilters:\n  - exam.lua\n", encoding="utf-8")
    source = tmp_path / "ab_mini_probe.qmd"
    source.write_text(
        f"---\nformat:\n  typst:\n    template: {template}\nfontsize: {fontsize}pt\n"
        f"mini-diagnose: {'true' if diagnosis else 'false'}\n---\n\n"
        "[Mini-AB]\n\n# Lernmission\n\n## Aufgabe 1\n\n"
        "Berechne und begründe.\n\n[Antwortkasten: 1cm]\n\n[/Mini-AB]\n",
        encoding="utf-8",
    )
    result = BuildService(tmp_path, subprocess.run).build_document(source, error_summary=lambda output: output)
    assert result.returncode == 0, result.stdout
    with pymupdf.open(result.pdf_path) as pdf:
        assert len(pdf) == 1
        page = pdf[0]
        middle = page.rect.height / 2
        spans = [span for block in page.get_text("dict")["blocks"] for line in block.get("lines", []) for span in line["spans"]]
        body = [span for span in spans if "Berechne und begründe." in span["text"]]
        assert len(body) == 2
        assert all(span["size"] == pytest.approx(fontsize) for span in body)
        assert body[0]["bbox"][3] < middle < body[1]["bbox"][1]
        assert all(span["size"] >= fontsize - 0.01 for span in spans)
        drawings = page.get_drawings()
        answers = [item for item in drawings if item["fill"] and all(abs(channel - 238 / 255) < 0.01 for channel in item["fill"])]
        assert len(answers) == 2
        assert all(item["color"] is None for item in answers)
        cut = [item for item in drawings if abs(item["rect"].y0 - middle) < 1 and item["rect"].width > page.rect.width * 0.8]
        assert len(cut) == 1
        assert cut[0]["rect"].height < 1
        # The strip around the cutting line contains no mascot paths.
        assert not [item for item in drawings if item not in cut and item["rect"].y0 < middle + 2 and item["rect"].y1 > middle - 2]


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
@pytest.mark.parametrize("template,diagnosis", [
    ("worksheet-mini.typst", False),
    *((name, False) for name in private_names(r"worksheet-mini-[\w-]+\.typst")),
    ("worksheet-mini.typst", True),
])
def test_mini_duplex_sides_have_distinct_headers_on_both_copies(tmp_path, template, diagnosis):
    for partial in [path for path in all_template_files() if path.suffix == ".typst"]:
        shutil.copy(partial, tmp_path)
    shutil.copy(ROOT / "src/quarto/filters/exam.lua", tmp_path)
    (tmp_path / "_quarto.yml").write_text("project:\n  type: default\nfilters:\n  - exam.lua\n", encoding="utf-8")
    source = tmp_path / "ab_mini_duplex.qmd"
    source.write_text(
        f"---\nfontsize: 14pt\nformat:\n  typst:\n    template: {template}\n"
        f"mini-diagnose: {'true' if diagnosis else 'false'}\n---\n\n"
        "[Mini-AB]\n\n# Potenzen entdecken\n\nAufgaben im Heft.\n\n[/Mini-AB]\n\n"
        "[Seitenumbruch]\n\n[Mini-AB]\n\n# Potenzen entdecken\n\nLösungen prüfen.\n\n[/Mini-AB]\n",
        encoding="utf-8",
    )
    result = BuildService(tmp_path, subprocess.run).build_document(source, error_summary=lambda output: output)
    with pymupdf.open(result.pdf_path) as pdf:
        assert len(pdf) == 2
        for index, label in enumerate(["Vorderseite", "Rückseite"]):
            page = pdf[index]
            labels = page.search_for(label)
            assert len(labels) == 2
            assert labels[0].y1 < page.rect.height / 2 < labels[1].y0
            assert len(page.search_for("Potenzen entdecken")) == 2
            other = "Rückseite" if index == 0 else "Vorderseite"
            assert other not in page.get_text()
        # Front title bands are tinted; back title bands have white fill and a border.
        def title_bands(page):
            return [d for d in page.get_drawings() if d["rect"].width > page.rect.width * .8 and d["rect"].height > 10]
        front = [d for d in title_bands(pdf[0]) if d["fill"] is not None]
        back = [d for d in title_bands(pdf[1]) if d["fill"] is not None]
        borders = [d for d in title_bands(pdf[1]) if d["color"] is not None]
        assert len(front) == len(back) == len(borders) == 2
        assert all(d["fill"] != (1, 1, 1) for d in front)
        assert all(d["fill"] == (1, 1, 1) for d in back)
