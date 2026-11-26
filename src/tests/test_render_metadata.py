import os
import subprocess
from pathlib import Path

import pytest

from material_core.metadata import set_template
from material_core.render_inputs import render_content
from material_ui import app as material_app
from material_ui.slides import annotations_path
from test_material_ui import material_root, write_pdf, staged_pdf

TEMPLATE = Path(__file__).resolve().parents[1] / 'quarto/templates/slide-template.typst'


def test_index_fields_are_ignored_but_visible_fields_and_meta_shortcodes_are_not(tmp_path):
    source = tmp_path / 'slide.qmd'
    text = set_template('---\ntitle: Titel\ntags: [vorher]\n---\n\n## Einstieg\n\nText\n', str(TEMPLATE), 'typst')
    assert render_content(text, source) == render_content(text.replace('vorher', 'nachher'), source)
    assert render_content(text, source) != render_content(text.replace('Titel', 'Anderer Titel'), source)
    assert render_content(text, source) != render_content(text.replace('Text', 'Neuer Text'), source)
    used = text + '\n{{< meta tags >}}\n'
    assert render_content(used, source) != render_content(used.replace('vorher', 'nachher'), source)
    custom = tmp_path / 'custom.typst'
    custom.write_text('$for(tags)$$tags$$endfor$\n$body$')
    customized = set_template(text, str(custom), 'typst')
    assert render_content(customized, source) != render_content(customized.replace('vorher', 'nachher'), source)
    source.write_text('---\ntags: [vorher]\n---\nText\n')
    (tmp_path / '_quarto.yml').write_text('format:\n  typst:\n    template: custom.typst\n')
    assert render_content(source.read_text(), source) != render_content(source.read_text().replace('vorher', 'nachher'), source)


@pytest.fixture
def rendered_document(material_root, monkeypatch):
    source = material_root / 'slide.qmd'
    source.write_text(set_template('---\ntitle: Metatest\ntags: [vorher]\n---\n\n## Einstieg\n\nText\n<!-- material-ui -->\n' + '\n' * 16, str(TEMPLATE), 'typst'))
    services = material_app.services()
    def run(command, **kwargs):
        write_pdf(staged_pdf(command))
        return subprocess.CompletedProcess(command, 0, stdout='Fertig')
    monkeypatch.setattr(services.builds, 'run_process', run)
    monkeypatch.setattr(services.builds, 'build_tikz_assets', lambda directory: None)
    services.render.worker(source)
    assert services.render.state_payload()['ok'] is True
    return source, services


def test_metadata_save_keeps_pdf_deck_and_annotations_current(rendered_document):
    source, services = rendered_document
    client = material_app.create_app().test_client()
    deck = services.slides.deck_path(source)
    pdf = services.builds.find_pdf(source)
    before = (deck.read_bytes(), pdf.read_bytes(), pdf.stat().st_mtime_ns)
    sidecar = annotations_path(deck)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text('{"elements":[], "files":{}}')
    original = source.read_text()
    response = client.post('/api/document', json={'path': source.name, 'text': original.replace('vorher', 'nachher')})
    assert response.status_code == 200
    assert response.json['renderChanged'] is False
    assert response.json['renderNeeded'] is False
    loaded = client.get('/api/document', query_string={'path': source.name}).json
    assert loaded['pdfCurrent'] is True
    assert loaded['slidesCurrent'] is True
    assert services.slides.ensure(source) == (deck, False)
    assert sidecar.is_file()
    assert (deck.read_bytes(), pdf.read_bytes(), pdf.stat().st_mtime_ns) == before
    assert not list(deck.parent.glob(deck.name + '.bak-*'))
    changed = client.post('/api/document', json={'path': source.name, 'text': source.read_text().replace('## Einstieg', '## Neuer Einstieg')})
    assert changed.json['renderNeeded'] is True
    assert changed.json['renderChanged'] is True


def test_metadata_save_still_requests_render_when_output_is_missing(material_root):
    source = material_root / 'blatt.qmd'
    source.write_text('---\ntitle: Blatt\ntags: [alt]\n---\nText\n')
    result = material_app.create_app().test_client().post('/api/document', json={'path': source.name, 'text': source.read_text().replace('alt', 'neu')})
    assert result.json['renderChanged'] is False
    assert result.json['renderNeeded'] is True


def test_asset_change_is_not_hidden_by_metadata_only_save(rendered_document):
    source, services = rendered_document
    image = source.parent / 'bild.svg'
    image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="red"/></svg>')
    source.write_text(source.read_text() + '\n![](bild.svg)\n')
    services.render.worker(source)
    assert services.render.state_payload()['ok'] is True
    image.write_text(image.read_text().replace('red', 'tan'))
    response = material_app.create_app().test_client().post('/api/document', json={'path': source.name, 'text': source.read_text().replace('vorher', 'nachher')})
    assert response.json['renderChanged'] is False
    assert response.json['renderNeeded'] is True


def test_browser_skips_metadata_render_even_after_reload(rendered_document):
    from test_material_ui import LiveServer, free_port, sync_playwright, replace_editor_text
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    source, services = rendered_document
    before = source.read_text()
    deck = services.slides.deck_path(source)
    original = deck.read_bytes()
    renders = []
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.on('request', lambda request: renders.append(request.url) if request.method == 'POST' and request.url.endswith('/api/render') else None)
        page.goto(url, wait_until='domcontentloaded')
        page.wait_for_function("window.materialEditor.getText().includes('Metatest')")
        page.locator('.document-settings > summary').click()
        page.locator('#editMetadata').click()
        page.wait_for_function("document.querySelector('#metadataTags').value === 'vorher'")
        page.locator('#metadataTags').fill('nachher')
        with page.expect_response(lambda response: response.url.endswith('/api/document') and response.request.method == 'POST') as saved:
            page.locator('#applyMetadata').click()
        assert saved.value.json()['renderNeeded'] is False
        page.wait_for_timeout(1600)
        assert renders == []
        # Auch bei deutlich neuerem Quellzeitstempel zählt der Ausgabeinhalt.
        stamp = source.stat()
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 5_000_000_000))
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("window.materialEditor.getText().includes('nachher')")
        page.wait_for_timeout(1600)
        assert renders == []
        assert 'warning' not in (page.locator('#documentInfo').get_attribute('class') or '').split()
        assert deck.read_bytes() == original
        assert not list(deck.parent.glob(deck.name + '.bak-*'))
        browser.close()
