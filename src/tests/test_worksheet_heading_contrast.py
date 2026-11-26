from pathlib import Path
import shutil
import subprocess

import pymupdf
import pytest

from material_core.builds import BuildService
from material_core.template_roots import all_template_files


ROOT = Path(__file__).resolve().parents[2]


def render_design(tmp_path, template):
    for source in all_template_files():
        shutil.copy(source, tmp_path)
    shutil.copy(ROOT / "src/quarto/filters/exam.lua", tmp_path / "exam.lua")
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: default\nfilters:\n  - exam.lua\n"
        "template-partials:\n  - student-fields.typst\n  - exam-functions.typst\n  - worksheet-design.typst\n",
        encoding="utf-8",
    )
    source = tmp_path / "arbeitsblatt.qmd"
    source.write_text(
        f"---\ntitle: Lernmission\nformat:\n  typst:\n    template: {template}\n---\n\n"
        "# Zahlen entdecken\n\nBerechne $2^3$.\n",
        encoding="utf-8",
    )
    return BuildService(tmp_path, subprocess.run).build_document(
        source, error_summary=lambda output: output
    )


def heading_color(pdf_path):
    with pymupdf.open(pdf_path) as document:
        for block in document[0].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if "Zahlen entdecken" in span["text"]:
                        return span["color"]
    pytest.fail("Überschrift nicht im PDF gefunden")


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
@pytest.mark.skipif(shutil.which("typst") is None, reason="Typst fehlt")
@pytest.mark.parametrize("template,expected", [
    ("worksheet-foerdermaterial.typst", 0x1E1B3A),
    ("worksheet-retro.typst", 0x29213E),
])
def test_pixel_design_heading_ink_matches_accent_contrast(tmp_path, template, expected):
    result = render_design(tmp_path, template)
    assert result.returncode == 0, result.stdout
    assert heading_color(result.pdf_path) == expected
