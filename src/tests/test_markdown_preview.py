"""Markdown preview and local language checks do not require the blog builder."""
import pytest

from material_ui.markdown_preview import markdown_html
from material_ui.language_check import check_language
from material_ui.errors import InvalidInput
from test_material_ui_notes import notes_app


def test_markdown_is_readable_and_isolates_active_content():
    html = markdown_html('---\ntitle: Test\n---\n# Abschnitt\n\n**Text**\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))')
    assert '<h1>Test</h1>' in html and '<strong>Text</strong>' in html
    assert '<script>' not in html and 'href="javascript:' not in html
    assert 'Content-Security-Policy' in html
    assert '<hr' not in html


def test_language_tool_is_optional_and_local(monkeypatch):
    monkeypatch.delenv('MATERIAL_LANGUAGETOOL_URL', raising=False)
    assert check_language('Text')['issues'] == []
    monkeypatch.setenv('MATERIAL_LANGUAGETOOL_URL', 'https://example.org')
    with pytest.raises(InvalidInput):
        check_language('Text')


def test_language_offsets_preserve_unicode_and_mask_metadata(monkeypatch):
    from material_ui import language_check
    monkeypatch.setenv('MATERIAL_LANGUAGETOOL_URL', 'http://localhost:8081')
    text = '---\ntitle: 😀\n---\n😀 Das ist falsch.'
    offset = len(text[:text.index('falsch')].encode('utf-16-le')) // 2
    def post(url, *, data, **kwargs):
        assert url == 'http://localhost:8081/v2/check'
        assert 'title' not in data['text'] and 'Das ist falsch.' in data['text']
        assert kwargs['trust_env'] is False
        class Result:
            def raise_for_status(self): pass
            def json(self):
                return {'matches': [{'offset': offset, 'length': 6, 'message': 'Hinweis', 'replacements': [{'value': 'richtig'}]}]}
        return Result()
    monkeypatch.setattr(language_check.httpx, 'post', post)
    issue = check_language(text)['issues'][0]
    assert (issue['line'], issue['column'], issue['length']) == (4, 11, 6)
    assert 'richtig' in issue['detail']


def test_markdown_preview_route(notes_app):
    app, folder = notes_app
    source = folder / 'notiz_test.md'
    source.write_text('Gespeichert')
    client = app.test_client()
    client.environ_base['HTTP_X_MATERIAL_TOKEN'] = app.config['MATERIAL_CSRF_TOKEN']
    path = app.extensions['material_runtime'].config.relative(source)
    result = client.post('/api/document/preview', json={'path': path, 'text': '**Ungespeichert**'})
    assert result.status_code == 200
    assert '<strong>Ungespeichert</strong>' in result.json['html']
    assert source.read_text() == 'Gespeichert'
    assert client.post('/api/document/preview', json={'path': '../outside.md', 'text': 'x'}).status_code == 400


def test_renderable_markdown_keeps_pdf_workspace(notes_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, folder = notes_app
    source = folder / 'blatt.md'
    source.write_text('---\ntitle: Blatt\nformat: pdf\n---\nText')
    path = app.extensions['material_runtime'].config.relative(source)
    with LiveServer(app, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.add_init_script('if (window.top === window) localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(f'{url}/?path={path}', wait_until='networkidle')
            page.wait_for_function("window.materialEditor?.getText().includes('format: pdf')")
            assert page.locator('#renderDoc').is_visible()
            assert page.locator('#pdfPreview').is_visible()
            assert page.locator('#markdownPreviewHost').is_hidden()
            assert page.locator('#markdownPreview').count() == 0
            page.locator('.cm-content').click()
            page.keyboard.press('Control+End')
            page.keyboard.type(' Mehr Text')
            page.wait_for_function("window.materialEditor.getText().includes('Mehr Text')")
            assert page.locator('#renderDoc').is_visible()
            assert page.locator('#markdownPreviewHost').is_hidden()
        finally:
            browser.close()
