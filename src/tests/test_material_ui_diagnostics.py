from __future__ import annotations

from pathlib import Path

import pytest

from material_ui.app import create_app
from material_ui.config import AppConfig
from test_material_ui import LiveServer, free_port, sync_playwright, replace_editor_text


@pytest.fixture
def app(tmp_path):
    (tmp_path / 'ab.qmd').write_text('---\ntitle: Blatt\n---\n\nText\n<!-- material-ui -->\n')
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    yield app
    app.extensions['material_runtime'].close()


def test_checks_unsaved_text_with_exact_image_and_template_positions(app, tmp_path):
    source = tmp_path / 'ab.qmd'
    original = source.read_text()
    text = '---\ntitle: Blatt\nformat:\n  typst:\n    template: missing.typst\n---\n\n😀 ![Bild](assets/fehlt.png)\n![Wiederholung](assets/fehlt.png)\n'
    response = app.test_client().post('/api/check', json={'path': 'ab.qmd', 'text': text})
    assert response.status_code == 200
    issues = response.json['issues']
    images = [issue for issue in issues if issue['title'] == 'Bild fehlt']
    assert [(issue['line'], issue['column']) for issue in images] == [(8, 11), (9, 17)]
    template = next(issue for issue in issues if issue['title'] == 'Template nicht gefunden')
    assert template['line'] == 5
    assert source.read_text() == original


def test_malformed_yaml_is_a_positioned_diagnostic(app):
    response = app.test_client().post('/api/check', json={'path': 'ab.qmd', 'text': '---\ntitle: [broken\n---\nText\n'})
    assert response.status_code == 200
    error = next(issue for issue in response.json['issues'] if issue['title'] == 'YAML-Header ungültig')
    assert error['level'] == 'error'
    assert error['line'] >= 2
    assert error['column'] >= 1


def test_saved_invalid_yaml_can_still_be_opened_and_checked(app, tmp_path):
    text = '---\ntitle: [broken\n---\nText\n'
    (tmp_path / 'ab.qmd').write_text(text)
    client = app.test_client()
    response = client.get('/api/document?path=ab.qmd')
    assert response.status_code == 200
    assert response.json['text'] == text
    assert any(issue['title'] == 'YAML-Header ungültig' for issue in client.post('/api/check', json={'path': 'ab.qmd'}).json['issues'])


def test_invalid_metadata_and_excalidraw_output(app):
    client = app.test_client()
    issues = client.post('/api/check', json={'path': 'ab.qmd', 'text': '---\ntitle: [Text]\n---\n'}).json['issues']
    assert any(issue['title'] == 'Metadaten ungültig' for issue in issues)
    issues = client.post('/api/check', json={'path': 'ab.qmd', 'text': '---\ntitle: Folien\nmaterial-output: excalidraw\n---\n<!-- material-ui -->\n'}).json['issues']
    assert not any(issue['title'].startswith('PDF') for issue in issues)


def test_diagnostics_reject_invalid_snapshot_and_external_path(app):
    client = app.test_client()
    assert client.post('/api/check', json={'path': 'ab.qmd', 'text': 123}).status_code == 400
    assert client.post('/api/check', json={'path': '../outside.qmd', 'text': 'Text'}).status_code == 400


def test_image_markdown_titles_do_not_produce_false_positive(app, tmp_path):
    (tmp_path / 'bild mit leerzeichen.png').write_bytes(b'PNG')
    text = '---\ntitle: Blatt\n---\n![Bild](<bild mit leerzeichen.png> "Beschreibung")\n![Bild](bild.png "Beschreibung")\n'
    (tmp_path / 'bild.png').write_bytes(b'PNG')
    issues = app.test_client().post('/api/check', json={'path': 'ab.qmd', 'text': text}).json['issues']
    assert not any(issue['title'] == 'Bild fehlt' for issue in issues)


def test_browser_displays_diagnostics_for_unsaved_text_and_clears_them(app, tmp_path):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    original = (tmp_path / 'ab.qmd').read_text()
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:auto-save", "false");')
        page.goto(f'{url}?path=ab.qmd', wait_until='domcontentloaded')
        page.wait_for_function('window.materialEditor && window.materialEditor.getText().includes("title: Blatt")')
        replace_editor_text(page, '---\ntitle: Blatt\n---\n\n![Bild](fehlt.png)\n')
        page.wait_for_selector('.cm-material-diagnostic-error')
        assert page.locator('.material-diagnostic-error').count() >= 1
        page.locator('.document-settings > summary').click()
        page.locator('#checkDoc').click()
        page.wait_for_function('document.querySelector("#editorDiagnostics").open')
        page.get_by_role('button', name='Zeile 5: Bild fehlt – Nicht gefunden: fehlt.png').click()
        assert page.locator('.cm-content').evaluate('node => node.contains(document.activeElement)')
        assert (tmp_path / 'ab.qmd').read_text() == original
        replace_editor_text(page, '---\ntitle: [kaputt\n---\n')
        page.wait_for_function('document.querySelector("#diagnosticsList").textContent.includes("YAML-Header ungültig")')
        replace_editor_text(page, original)
        page.wait_for_function('!document.querySelector("#diagnosticsList").textContent.includes("YAML-Header ungültig")')
        page.wait_for_timeout(800)
        assert page.locator('.cm-material-diagnostic-error').count() == 0
        assert errors == []
        browser.close()
