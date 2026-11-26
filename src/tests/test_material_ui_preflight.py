from __future__ import annotations

import pytest

from material_ui.app import create_app
from material_ui.config import AppConfig
from material_ui.diagnostics import PreflightFailure, preflight
from test_material_ui import LiveServer, free_port, sync_playwright, replace_editor_text

HEADER = '---\ntitle: Blatt\n---\n\n'


@pytest.fixture
def app(tmp_path):
    (tmp_path / 'ab.qmd').write_text(HEADER + 'Text\n')
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    yield app
    app.extensions['material_runtime'].close()


@pytest.mark.parametrize('text, title, line', [
    ('---\ntitle: [broken\n---\n', 'YAML-Header ungültig', 2),
    ('---\ntitle: Blatt\n', 'YAML-Header nicht geschlossen', 1),
    (HEADER + '```{python}\nprint(1)\n', 'Codeblock nicht geschlossen', 5),
    (HEADER + '$$\nx = 1\n', 'Formel nicht geschlossen', 5),
    (HEADER + r'\begin{align}' + '\nx = 1\n', 'LaTeX-Umgebung nicht geschlossen', 5),
    (HEADER + r'\end{align}', 'LaTeX-Umgebung falsch geschlossen', 5),
    (HEADER + '```{=latex}\n\\begin{align}\n```\n', 'LaTeX-Umgebung nicht geschlossen', 6),
    (HEADER + '![Bild](missing.png)', 'Bild fehlt', 5),
    ('---\ntitle: Blatt\nformat:\n  typst:\n    template: missing.typst\n---\n', 'Template nicht gefunden', 5),
    ('---\ntitle: Blatt\noutput-file: ../../outside.pdf\n---\n', 'Ausgabepfad ungültig', 1),
])
def test_preflight_blocks_before_any_job_or_build(app, tmp_path, monkeypatch, text, title, line):
    source = tmp_path / 'ab.qmd'
    source.write_text(text)
    runtime = app.extensions['material_runtime']
    monkeypatch.setattr(runtime.services.render, 'submit', lambda *args: pytest.fail('Must not submit'))
    response = app.test_client().post('/api/render', json={'path': 'ab.qmd'})
    assert response.status_code == 422
    assert response.json['error']['code'] == 'preflight_failed'
    issue = next(item for item in response.json['issues'] if item['title'] == title)
    assert issue['level'] == 'error'
    assert issue['line'] >= line
    assert not runtime.jobs.records


def test_warnings_do_not_block_and_fixed_source_can_render(app, tmp_path, monkeypatch):
    renderer = app.extensions['material_runtime'].services.render
    submitted = []
    monkeypatch.setattr(renderer, 'submit', lambda *args: submitted.append(args))
    source = tmp_path / 'ab.qmd'
    source.write_text(HEADER + '$$\nx = 1\n')
    with pytest.raises(PreflightFailure):
        renderer.start(source)
    source.write_text(HEADER + '$$\nx = 1\n$$\n')
    response = app.test_client().post('/api/render', json={'path': 'ab.qmd'})
    assert response.status_code == 202
    assert len(submitted) == 1


def test_queued_document_is_checked_again_before_building(app, tmp_path, monkeypatch):
    runtime = app.extensions['material_runtime']
    renderer = runtime.services.render
    monkeypatch.setattr(renderer, 'submit', lambda *args: None)
    monkeypatch.setattr(renderer.builds, 'build_document', lambda *args, **kwargs: pytest.fail('Must not build'))
    first = tmp_path / 'ab.qmd'
    queued = tmp_path / 'queued.qmd'
    queued.write_text(HEADER + 'Text\n')
    renderer.start(first)
    identifier = renderer.start(queued)
    queued.write_text(HEADER + '$$\nx = 1\n')
    renderer.finish(True, 'Fertig', None)
    renderer.worker(queued)
    record = runtime.jobs.get(identifier)
    assert record['ok'] is False
    assert record['running'] is False
    assert any(issue['title'] == 'Formel nicht geschlossen' for issue in record['detail']['preflight_issues'])
    assert record['detail']['source_revision'] == runtime.documents.read(queued)['revision']


@pytest.mark.parametrize('text', [
    HEADER + '```markdown\n![Beispiel](missing.png)\n$$\n\\begin{align}\n```\n',
    HEADER + '<!-- ![Kommentar](missing.png) $$ -->\n`$$` und `\\begin{align}`\n',
    HEADER + '$$x = 1$$\n\\begin{align}\nx &= 1\n\\end{align}\n',
    HEADER + '````markdown\n```python\nprint(1)\n```\n````\n',
    HEADER + '```{=latex}\n% \\begin{align}\n\\begin{align}\nx = 1 % \\end{other}\n\\end{align}\n```\n',
    'Markdown ohne YAML ist renderbar.\n',
])
def test_examples_and_valid_structures_are_not_blocked(app, tmp_path, text):
    builds = app.extensions['material_runtime'].services.builds
    preflight(builds, tmp_path / 'ab.qmd', text)


def test_generated_tikz_svg_is_not_reported_missing(app, tmp_path):
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets/bild.tex').write_text(r'\documentclass{standalone}')
    preflight(app.extensions['material_runtime'].services.builds, tmp_path / 'ab.qmd', HEADER + '![Bild](assets/bild.svg)')


@pytest.mark.parametrize('automatic', [False, True])
def test_browser_blocks_rendering_until_source_is_fixed(app, tmp_path, monkeypatch, automatic):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    source = tmp_path / 'ab.qmd'
    source.write_text(HEADER + ('$$\nx = 1\n' if automatic else 'Text\n'))
    submitted = []
    monkeypatch.setattr(app.extensions['material_runtime'].services.render, 'submit', lambda *args: submitted.append(args))
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        requests = []
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append(request.url) if request.url.endswith('/api/render') else None)
        page.add_init_script(f'localStorage.setItem("material-ui:auto-render", "{str(automatic).lower()}"); localStorage.setItem("material-ui:auto-save", "{str(automatic).lower()}");')
        page.goto(f'{url}?path=ab.qmd', wait_until='domcontentloaded')
        page.wait_for_function('window.materialEditor && window.materialEditor.getText().includes("title: Blatt")')
        replace_editor_text(page, HEADER + '$$\nx = 2\n')
        page.wait_for_selector('.cm-material-diagnostic-error')
        if not automatic:
            page.locator('#renderDoc').click()
        page.wait_for_function('document.querySelector("#renderStatus").textContent.includes("Rendern gesperrt")')
        assert not submitted
        assert not requests
        if not automatic:
            assert source.read_text() == HEADER + 'Text\n'
        assert page.locator('#editorDiagnostics').evaluate('node => node.open')
        replace_editor_text(page, HEADER + '$$\nx = 2\n$$\n')
        if not automatic:
            page.locator('#renderDoc').click()
        page.wait_for_function('document.querySelector("#renderStatus").textContent.includes("Render läuft")')
        assert len(submitted) == 1
        assert len(requests) == 1
        assert '$$\nx = 2\n$$' in source.read_text()
        assert errors == []
        browser.close()


@pytest.mark.parametrize('shortcut', [False, True])
def test_manual_render_reloads_external_changes_first(app, tmp_path, monkeypatch, shortcut):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    source = tmp_path / 'ab.qmd'
    submitted = []
    monkeypatch.setattr(app.extensions['material_runtime'].services.render, 'submit', lambda *args: submitted.append(args))
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:auto-save", "false");')
        page.goto(f'{url}?path=ab.qmd', wait_until='domcontentloaded')
        page.wait_for_function('window.materialEditor && window.materialEditor.getText().includes("title: Blatt")')
        if shortcut:
            page.locator('.cm-content').click()
            page.wait_for_timeout(300)
        source.write_text(HEADER + 'Von außen geändert\n')
        if shortcut:
            page.keyboard.press('Control+Enter')
        else:
            page.locator('#renderDoc').click()
        page.wait_for_function('document.querySelector("#renderStatus").textContent.includes("Render läuft")')
        assert page.evaluate('window.materialEditor.getText()') == HEADER + 'Von außen geändert\n'
        assert len(submitted) == 1
        assert source.read_text() == HEADER + 'Von außen geändert\n'
        if shortcut:
            assert page.evaluate('document.querySelector("#editorHost").contains(document.activeElement)')
        assert errors == []
        browser.close()
