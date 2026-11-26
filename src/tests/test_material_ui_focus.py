"""Visible actions follow document type; search has one visible input."""
from material_ui.app import create_app
from material_ui.config import AppConfig
from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
import pytest


def test_presentation_action_distinguishes_worksheet_templates(tmp_path):
    for name, template, presentation in [
        ('ab_test', 'worksheet-retro.typst', False),
        ('slide', 'slide-retro.typst', True),
        ('notiz', 'exam-template.typst', False),
    ]:
        write_qmd(tmp_path / 'unterricht' / f'{name}.qmd', f'---\ntitle: Test\nformat:\n  typst:\n    template: src/quarto/templates/{template}\n---\n\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    try:
        client = app.test_client()
        for name, expected in [('ab_test', False), ('slide', True), ('notiz', False)]:
            result = client.get(f'/api/document?path=unterricht/{name}.qmd')
            assert result.status_code == 200
            assert result.json['isPresentation'] is expected
        assert client.get('/api/document?path=unterricht/ab_test.qmd').json['hasSlides']
    finally:
        app.extensions['material_runtime'].close()


def test_browser_document_controls_and_shared_search(tmp_path):
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    for name, template in [('ab_test', 'worksheet-retro.typst'), ('slide', 'slide-retro.typst')]:
        write_qmd(tmp_path / 'unterricht' / f'{name}.qmd', f'---\ntitle: {name}\ntags: [mathe]\nformat:\n  typst:\n    template: src/quarto/templates/{template}\n---\n\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    try:
        assert app.test_client().post('/api/worksheet/start', json={'path': 'unterricht/ab_test.qmd'},
                                      headers={'X-Material-Token': app.config['MATERIAL_CSRF_TOKEN']}).status_code == 200
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1500, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:active-view", "folder")')
            page.goto(url + '/?path=unterricht/ab_test.qmd', wait_until='networkidle')
            from playwright.sync_api import expect
            expect(page.get_by_role('button', name='Besprechen', exact=True)).to_be_visible()
            expect(page.locator('#slidesPlay')).to_be_hidden()
            expect(page.locator('#documentInfo')).to_be_hidden()
            expect(page.locator('#showHistory')).to_be_hidden()
            page.locator('.document-settings > summary').click()
            expect(page.locator('#showHistory')).to_be_visible()
            expect(page.locator('#editMetadata')).to_be_visible()
            expect(page.locator('#checkDoc')).to_be_visible()
            expect(page.locator('#showRenderPanel')).to_be_visible()
            expect(page.locator('#showGit')).to_be_visible()
            expect(page.locator('#documentDetails')).to_be_hidden()
            expect(page.locator('#documentDetails')).to_be_empty()
            expect(page.locator('#deleteOpenDocument')).to_be_visible()
            expect(page.locator('#documentDetails')).not_to_contain_text('Zeilen')
            expect(page.locator('#documentDetails')).not_to_contain_text('Zeichen')
            expect(page.locator('.advanced-options')).to_be_hidden()
            for button, modal in [('#showGit', '#gitModal'), ('#editMetadata', '#metadataModal')]:
                page.locator(button).click()
                expect(page.locator(modal)).to_have_attribute('aria-hidden', 'false')
                page.keyboard.press('Escape')
                expect(page.locator('.document-settings > summary')).to_be_focused()
                page.locator('.document-settings > summary').click()
            for width in (1500, 1100, 900, 650, 420, 320):
                page.set_viewport_size({'width': width, 'height': 1000})
                page.wait_for_function('''() => {
                    const panel = document.querySelector('.document-settings > .document-settings-panel');
                    const box = panel.getBoundingClientRect();
                    return box.left >= 0 && box.right <= innerWidth && box.bottom <= innerHeight;
                }''')
            page.set_viewport_size({'width': 1500, 'height': 1000})
            page.locator('#toggleFocusMode').click()
            page.locator('#editMetadata').focus()
            page.keyboard.press('Escape')
            expect(page.locator('.document-settings')).not_to_have_attribute('open', '')
            expect(page.locator('.document-settings > summary')).to_be_focused()
            expect(page.locator('#workspace')).to_have_class(__import__('re').compile('focus-mode'))
            expect(page.locator('.document-details .document-path')).to_be_hidden()
            page.locator('.document-settings > summary').click()
            expect(page.locator('#documentDetails')).to_be_hidden()
            expect(page.locator('#documentDetails')).to_be_empty()
            page.locator('.discussion-menu > summary').click()
            expect(page.get_by_role('button', name='Weitere Besprechung anlegen', exact=True).first).to_be_visible()
            page.get_by_role('button', name='Weitere Besprechung anlegen', exact=True).first.focus()
            page.keyboard.press('Escape')
            expect(page.locator('.discussion-menu')).not_to_have_attribute('open', '')
            expect(page.locator('.discussion-menu > summary')).to_be_focused()
            expect(page.locator('#workspace')).to_have_class(__import__('re').compile('focus-mode'))
            page.locator('#toggleFocusMode').click()
            page.locator('#tagTreeViewButton').click()
            expect(page.locator('#tagSearch')).to_be_hidden()
            page.locator('#documentSearch').fill('ab_test')
            expect(page.locator('#searchOverlay')).to_be_hidden()
            expect(page.locator('#tagResults')).to_contain_text('ab_test')
            expect(page.locator('#tagResults')).not_to_contain_text('slide')
            page.locator('[data-tab-close]').click()
            expect(page.locator('#documentInfo')).to_be_visible()
            expect(page.locator('#documentInfo')).to_contain_text('Kein Dokument geöffnet')
            expect(page.locator('#documentSearch')).to_have_value('ab_test')
            expect(page.locator('#tagSearch')).to_have_value('ab_test')
            expect(page.locator('#tagResults')).to_contain_text('ab_test')
            page.locator('#tagResults [data-document="unterricht/ab_test.qmd"]').click()
            expect(page.get_by_role('button', name='Besprechen', exact=True)).to_be_visible()
            page.locator('#folderViewButton').click()
            page.locator('#documentSearch').fill('slide')
            expect(page.locator('#searchOverlay')).to_be_visible()
            page.keyboard.press('Escape')
            expect(page.locator('#searchOverlay')).to_be_hidden()
            page.keyboard.press('ArrowDown')
            expect(page.locator('#searchOverlay')).to_be_visible()
            page.locator('#documentResults [data-path="unterricht/slide.qmd"]').click()
            expect(page.locator('#slidesPlay')).to_be_visible()
            expect(page.get_by_role('button', name='Besprechen', exact=True)).to_be_hidden()
            assert not errors
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_api_rejects_missing_or_invalid_presentation_flags():
    import json
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which('node')
    if not node:
        pytest.skip('Node fehlt')
    module = (Path(__file__).resolve().parents[1] / 'material_ui/static/api.js').as_uri()
    script = '''
import assert from 'node:assert/strict';
import { api } from MODULE;
globalThis.document = { querySelector: () => null };
const contract = { apiVersion: 3, capabilities: [] };
let payload;
globalThis.fetch = async url => ({ ok: true, json: async () =>
  ['/static/api-contract.json', '/api/protocol'].includes(url) ? contract : payload });
for (const endpoint of ['/api/document?path=slide.qmd', '/api/document', '/api/document/metadata']) {
  for (const invalid of [{hasSlides: true}, {isPresentation: true},
    {hasSlides: true, isPresentation: 'false'}, {hasSlides: null, isPresentation: true}]) {
    payload = invalid;
    await assert.rejects(api(endpoint), error => error.status === 426 && !error.retryable
      && error.message.includes('Server neu starten'));
  }
  for (const isPresentation of [true, false]) {
    payload = { hasSlides: true, isPresentation };
    assert.deepEqual(await api(endpoint), payload);
  }
}
// Restart remains available even with the old response shape.
payload = {ok: true};
assert.deepEqual(await api('/api/server/restart', {method: 'POST'}), payload);
'''.replace('MODULE', json.dumps(module))
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
