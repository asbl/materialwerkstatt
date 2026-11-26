"""Regression coverage for workspace views, search ranking and creation flow."""
import pytest
from material_ui.app import create_app
from material_ui.config import AppConfig
from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd


def test_workspace_search_and_creation(tmp_path):
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    write_qmd(tmp_path / 'unterricht/mathematik/klasse-05/ab_brueche.qmd',
              '---\ntitle: Brüche üben\n---\n\nBrüche addieren.\n')
    write_qmd(tmp_path / 'unterricht/mathematik/klasse-05/ab_zahlen.qmd',
              '---\ntitle: Zahlen\n---\n\n' + 'Brüche ' * 100)
    write_qmd(tmp_path / 'src/beispiel.qmd', '---\ntitle: Brüche Beispiel\n---\n\nBrüche\n')
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1024, 'height': 768})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:active-view", "folder")')
            page.goto(url, wait_until='networkidle')
            from playwright.sync_api import expect
            expect(page.locator('#workspace')).to_have_attribute('data-view', 'edit')
            expect(page.locator('.preview-pane')).to_be_hidden()
            assert page.locator('.editor-pane').bounding_box()['width'] > 950
            expect(page.locator('.workspace-index')).to_be_hidden()
            page.locator('#workspaceNavigation').click()
            expect(page.locator('.workspace-index')).to_be_visible()
            page.keyboard.press('Escape')
            expect(page.locator('.workspace-index')).to_be_hidden()
            page.locator('[data-workspace-view="preview"]').click()
            expect(page.locator('.editor-pane')).to_be_hidden()
            expect(page.locator('.preview-pane')).to_be_visible()
            page.reload(wait_until='networkidle')
            expect(page.locator('#workspace')).to_have_attribute('data-view', 'preview')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.locator('[data-workspace-view="split"]').click()
            expect(page.locator('.editor-pane')).to_be_visible()
            expect(page.locator('.preview-pane')).to_be_visible()
            page.locator('#documentSearch').fill('Brüche')
            expect(page.locator('#documentResults .document-option').first).to_contain_text('Brüche üben')
            page.wait_for_timeout(650)
            expect(page.locator('#documentResults .document-option').first).to_contain_text('Brüche üben')
            expect(page.locator('#documentResults')).not_to_contain_text('Brüche Beispiel')
            expect(page.locator('#subjectFilter')).to_contain_text('Alle Fächer')
            page.locator('[data-filter="everything"]').click()
            expect(page.locator('#documentResults')).to_contain_text('Brüche Beispiel')
            page.keyboard.press('Escape')
            page.locator('#newDoc').click()
            expect(page.locator('#newTitle')).to_be_focused()
            expect(page.locator('#newFilename')).to_be_hidden()
            expect(page.locator('#newDocStatus')).to_be_hidden()
            expect(page.locator('#newMini')).to_be_visible()
            checkbox = page.locator('#newMini').bounding_box()
            label = page.locator('#newMiniField span').bounding_box()
            assert abs(checkbox['y'] - label['y']) < 10
            page.locator('#newTitle').fill('Neue Brüche')
            page.locator('#newTopic').fill('brueche')
            page.locator('#createNewDoc').click()
            expect(page.locator('#newDocModal')).not_to_have_class(__import__('re').compile(r'\bopen\b'))
            expect(page.locator('#documentInfo')).to_contain_text('Neue Brüche')
            assert not errors
            browser.close()
    finally:
        app.extensions['material_runtime'].close()
