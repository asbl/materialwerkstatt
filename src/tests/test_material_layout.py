import json
from pathlib import Path

import pymupdf

from material_core.layout import check_layout


def test_pdf_check_reports_small_body_and_clipped_text_but_not_footer(tmp_path):
    path = tmp_path / 'slide.pdf'
    pdf = pymupdf.open()
    page = pdf.new_page(width=453.54, height=255.12)
    page.insert_text((20, 70), 'Zu klein gesetzter Inhalt', fontsize=5)
    page.insert_text((430, 100), 'Diese Zeile ist zu lang fuer die Seite', fontsize=12)
    page.insert_text((20, 248), 'Absichtlich kleine Fusszeile', fontsize=7)
    pdf.save(path)
    pdf.close()
    issues = check_layout(path, slides=True)
    assert {item['code'] for item in issues} >= {'small-font', 'overflow'}
    assert all(item['target'] == 'pdf' and item['page'] == 1 for item in issues)
    assert len([item for item in issues if item['code'] == 'small-font']) == 1
    assert 'Zu klein' in next(item['detail'] for item in issues if item['code'] == 'small-font')


def test_pdf_rotation_does_not_report_clipping(tmp_path):
    path = tmp_path / 'rotated.pdf'
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=300)
    page.insert_text((400, 80), 'Lesbarer Inhalt', fontsize=14)
    page.set_rotation(90)
    pdf.save(path)
    pdf.close()
    assert check_layout(path) == []


def test_slide_check_reports_overflow_small_font_and_ignores_notes_and_footer(tmp_path):
    path = tmp_path / 'slide.excalidraw'
    elements = [
        {'id': 'frame', 'type': 'frame', 'x': 0, 'y': 0, 'width': 1600, 'height': 900, 'name': 'Einstieg'},
        {'id': 'text', 'type': 'text', 'frameId': 'frame', 'x': 1500, 'y': 80, 'width': 300, 'height': 60, 'text': 'Zu lange Zeile', 'fontSize': 36},
        {'id': 'small', 'type': 'text', 'frameId': 'frame', 'x': 20, 'y': 200, 'width': 100, 'height': 20, 'text': 'Zu klein', 'fontSize': 12},
        {'id': 'footer', 'type': 'text', 'frameId': 'frame', 'x': 20, 'y': 850, 'width': 100, 'height': 20, 'text': '1', 'fontSize': 20},
        {'id': 'note', 'type': 'freedraw', 'frameId': 'frame', 'x': -200, 'y': 100, 'width': 150, 'height': 30, 'customData': {'presenterAnnotation': True}},
    ]
    path.write_text(json.dumps({'elements': elements, 'files': {}}))
    issues = check_layout(deck=path)
    assert {item['code'] for item in issues} == {'overflow', 'small-font'}
    assert all(item['target'] == 'slides' and item['page'] == 1 for item in issues)
    assert '1 Element(e)' in next(item['detail'] for item in issues if item['code'] == 'overflow')


def test_browser_shows_pdf_and_slide_layout_findings(tmp_path):
    import pytest
    from material_core.metadata import set_template
    from material_core.builds import BuildService
    from material_ui.app import create_app
    from material_ui.config import AppConfig
    from material_ui.slides import SlidesService
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    template = Path(__file__).resolve().parents[1] / 'quarto/templates/slide-template.typst'
    source = tmp_path / 'slide.qmd'
    source.write_text(set_template('---\ntitle: Layouttest\n---\n\n## Einstieg\n\nText\n<!-- material-ui -->\n', str(template), 'typst'))
    config = AppConfig(tmp_path)
    pdf_path = BuildService(tmp_path, None).pdf_dir(source) / 'slide.pdf'
    pdf_path.parent.mkdir(parents=True)
    pdf = pymupdf.open()
    page = pdf.new_page(width=453.54, height=255.12)
    page.insert_text((20, 80), 'Kleiner Inhalt', fontsize=5)
    pdf.save(pdf_path)
    pdf.close()
    deck = SlidesService(config).deck_path(source)
    deck.parent.mkdir(parents=True)
    deck.write_text(json.dumps({'elements': [
        {'id': 'f', 'type': 'frame', 'x': 0, 'y': 0, 'width': 1600, 'height': 900, 'name': 'Einstieg'},
        {'id': 't', 'type': 'text', 'frameId': 'f', 'x': 1550, 'y': 200, 'width': 200, 'height': 40, 'text': 'Zu lange Zeile', 'fontSize': 36},
    ], 'files': {}}))
    app = create_app(config=config)
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='domcontentloaded')
            page.wait_for_function("document.querySelector('#diagnosticsList').textContent.includes('Inhalt außerhalb der Folie')")
            page.locator('#editorDiagnostics').evaluate('element => element.open = true')
            assert 'Kleine Schrift' in page.locator('#diagnosticsList').inner_text()
            page.locator('#diagnosticsList button').filter(has_text='PDF, Seite 1').click()
            assert '#page=1' in page.locator('#pdfPreview').get_attribute('src')
            browser.close()
    finally:
        app.extensions['material_runtime'].close()
