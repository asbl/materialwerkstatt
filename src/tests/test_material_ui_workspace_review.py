"""Regression coverage for workspace views, search ranking and creation flow."""
import json

import pytest
from material_ui.app import create_app
from material_ui.config import AppConfig
from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
from test_material_ui_search_index import write_original_pdf


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


def test_picker_opens_original_pdf_at_page_and_links_worksheet(tmp_path):
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    path = 'unterricht/mathematik/klasse-05/bruch/ab_brueche.qmd'
    write_qmd(tmp_path / path, '---\ntitle: Brüche üben\n---\n\nBrüche addieren.\n')
    target = tmp_path / 'unterricht/mathematik/klasse-06/wiederholung'
    target.mkdir(parents=True)
    (target / 'einheit.yaml').write_text('titel: Wiederholung\nthema: Brüche\nkurzbeschreibung: ""\n')
    write_original_pdf(tmp_path, 'Original & Kopie.pdf', 'Deckblatt', 'Brüche addieren')
    (tmp_path / 'wissen/_pdf-erschliessung.json').write_text(json.dumps({
        'eintraege': {'original': {'pfad': 'Original & Kopie.pdf'}},
    }))
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            from playwright.sync_api import expect

            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.add_init_script('''
                localStorage.setItem("material-ui:auto-render", "false");
                window.open = url => { window.openedSearchPdf = url; };
            ''')
            page.goto(url, wait_until='networkidle')
            search = page.locator('#documentSearch')
            search.fill('brueche')
            original = page.get_by_role('option').filter(has_text='Original & Kopie')
            expect(original).to_contain_text('Seite 2')
            original.click()
            assert page.evaluate('window.openedSearchPdf') == '/api/pdf?path=wissen%2FOriginal%20%26%20Kopie.pdf#page=2'
            search.fill('Brüche')
            page.get_by_role('button', name='Brüche üben zu Einheit hinzufügen').click()
            dialog = page.get_by_role('dialog', name='Arbeitsblatt zu Einheit hinzufügen')
            select = dialog.get_by_label('Unterrichtseinheit')
            select.select_option(target.relative_to(tmp_path).as_posix())
            dialog.get_by_role('button', name='Hinzufügen', exact=True).click()
            expect(dialog).to_be_hidden()
            page.locator('#viewButton-units').click()
            page.locator('[data-show-undated]').check()
            page.get_by_role('button', name='Klasse 6', exact=True).click()
            card = page.locator('.unit-card').filter(has_text='Wiederholung')
            card.locator('summary').first.click()
            link = card.get_by_role('link', name='Arbeitsblatt: Brüche üben')
            expect(link).to_have_attribute('data-document-path', path)
            link.click()
            expect(page.locator('#documentInfo')).to_contain_text('Brüche üben')
            expect(card).to_have_attribute('open', '')
            browser.close()
    finally:
        app.extensions['material_runtime'].close()
