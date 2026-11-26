from pathlib import Path
import shutil
import subprocess

import pymupdf
import pytest

from material_core.builds import BuildService


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")


@pytest.mark.parametrize("marker", ["[Schülerfelder]", "[Schuelerfelder 1cm]"])
def test_foerderplan_template_renders_student_fields(tmp_path, marker):
    shutil.copy(ROOT / "src/quarto/templates/foerderplan-template.typst", tmp_path)
    shutil.copy(ROOT / "src/quarto/templates/student-fields.typst", tmp_path)
    shutil.copy(ROOT / "src/quarto/filters/exam.lua", tmp_path)
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: default\nfilters:\n  - exam.lua\ntemplate-partials:\n  - student-fields.typst\n", encoding="utf-8"
    )
    source = tmp_path / "arbeitsblatt.qmd"
    source.write_text(
        "---\ntitle: Testblatt\nformat:\n  typst:\n"
        "    template: foerderplan-template.typst\n---\n\n"
        f"{marker}\n\n# Potenzen\n\nBerechne $2^3$.\n\n"
        "[Seitenumbruch]\n\n## Weitere Aufgaben\n\nBerechne $3^2$.\n",
        encoding="utf-8",
    )

    result = BuildService(tmp_path, subprocess.run).build_document(source)

    assert result.returncode == 0, result.stdout
    with pymupdf.open(result.pdf_path) as document:
        assert document.page_count == 2
        text = document[0].get_text()
        assert "Name:" in text
        assert "Datum:" in text
        assert "Potenzen" in text
        assert "Weitere Aufgaben" in document[1].get_text()
