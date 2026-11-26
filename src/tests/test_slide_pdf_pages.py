from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pymupdf
import pytest

from excalideck.outline import parse_outline
from material_core.builds import BuildService
from material_core.metadata import set_template
from material_core.template_roots import template_path
from material_ui.documents import WORKSHEET_DESIGNS

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which('quarto') is None, reason='Quarto fehlt')
@pytest.mark.parametrize('filename', ['slide-template.typst', 'slide-retro.typst', 'slide-foerdermaterial.typst'])
def test_standalone_slides_include_dependencies_and_keep_sections_together(tmp_path, filename):
    source = tmp_path / 'slide.qmd'
    text = '---\ntitle: Entdecken\n---\n\n## Einstieg\n\n### Wie viele Punkte?\n\n[Modell vierhundertfeld | zeilen=14 | spalten=13]\n\nWie zerlegst du das Produkt?\n\n## Gemeinsam entdecken\n\n[Infobox: Hinweis]\n\nDenke an vier Teilprodukte.\n\n[/Infobox]\n'
    source.write_text(set_template(text, str(template_path(filename)), 'typst'))
    before = source.read_bytes()
    result = BuildService(tmp_path, subprocess.run).build_document(source)
    assert source.read_bytes() == before
    with pymupdf.open(result.pdf_path) as pdf:
        assert len(pdf) == 3
        assert 'Wie viele Punkte?' in pdf[1].get_text()
        assert 'Wie zerlegst du' in pdf[1].get_text()
        assert 'Hinweis' in pdf[2].get_text()
        assert '[Modell' not in ''.join(page.get_text() for page in pdf)
        assert all(abs(page.rect.width / page.rect.height - 16 / 9) < .01 for page in pdf)


@pytest.mark.skipif(shutil.which('quarto') is None, reason='Quarto fehlt')
@pytest.mark.parametrize('design', WORKSHEET_DESIGNS, ids=lambda design: design['id'])
def test_all_worksheet_designs_render_without_project_configuration(tmp_path, design):
    source = tmp_path / 'ab.qmd'
    source.write_text(set_template('---\ntitle: Blatt\n---\n\n## Aufgabe\n\nBerechne $2^3$.\n\n[Infobox: Hinweis]\n\nDenke an die Faktoren.\n\n[/Infobox]\n', str(template_path(f'worksheet-{design["id"]}.typst')), 'typst'))
    original = source.read_bytes()
    result = BuildService(tmp_path, subprocess.run).build_document(source)
    assert source.read_bytes() == original
    with pymupdf.open(result.pdf_path) as pdf:
        text = ''.join(page.get_text() for page in pdf)
        assert 'Aufgabe' in text
        assert 'Hinweis' in text
        assert 'Faktoren' in text
        assert '[Infobox' not in text


@pytest.mark.skipif(shutil.which('quarto') is None, reason='Quarto fehlt')
@pytest.mark.parametrize('filename', ['slide-template.typst', 'slide-retro.typst', 'slide-foerdermaterial.typst'])
@pytest.mark.parametrize('body', [
    '# Mein Titel\n\nUntertitel aus Markdown\n\n## Einstieg\n\nEine Frage\n',
    '---\ntitle: Titel aus YAML\n---\n\n# Mein Titel\n\n## Einstieg\n\nEine Frage\n',
    '## Einstieg\n\nEine Frage\n',
])
def test_markdown_titles_match_deck_structure(tmp_path, filename, body):
    source = tmp_path / 'slide.md'
    source.write_text(set_template(body, str(template_path(filename)), 'typst'))
    expected = parse_outline(source)
    result = BuildService(tmp_path, subprocess.run).build_document(source)
    with pymupdf.open(result.pdf_path) as pdf:
        assert len(pdf) == len(expected.slides)
        if expected.title:
            assert 'Mein Titel' in pdf[0].get_text()
            assert 'Titel aus YAML' not in pdf[0].get_text()
        else:
            assert 'Einstieg' in pdf[0].get_text()
        if 'Untertitel aus Markdown' in body:
            assert 'Untertitel aus Markdown' in pdf[0].get_text()
