"""Regression coverage for document switching and dependency caching."""
import hashlib
import os

import pytest

from material_core.builds import BuildService
from material_ui.app import create_app
from material_ui.config import AppConfig


def test_dependency_hash_reuses_reads_and_detects_preserved_mtime(tmp_path, monkeypatch):
    asset = tmp_path / 'asset.png'
    asset.write_bytes(b'first')
    builds = BuildService(tmp_path, None)
    original = hashlib.file_digest
    calls = []

    def digest(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(hashlib, 'file_digest', digest)
    first = builds.dependency_digest(asset)
    assert builds.dependency_digest(asset) == first
    assert len(calls) == 1
    stat = asset.stat()
    asset.write_bytes(b'other')
    os.utime(asset, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert builds.dependency_digest(asset) != first
    assert len(calls) == 2
    asset.unlink()
    asset.write_bytes(b'first')
    assert builds.dependency_digest(asset) == first
    assert len(calls) == 3


def test_pdf_cache_requires_current_version_and_rejects_old_version(tmp_path):
    source = tmp_path / 'ab.qmd'
    source.write_text('---\ntitle: Test\n---\n\nAufgabe\n')
    pdf = tmp_path / 'ab.pdf'
    pdf.write_bytes(b'%PDF first')
    app = create_app(config=AppConfig(tmp_path))
    try:
        client = app.test_client()
        version = client.get('/api/document?path=ab.qmd').json['pdfVersion']
        url = f'/api/pdf?path=ab.pdf&v={version}'
        assert client.get(url).headers['Cache-Control'] == 'private, max-age=31536000, immutable'
        assert client.get('/api/pdf?path=ab.pdf').headers['Cache-Control'] == 'no-store'
        assert client.get(url, headers={'Range': 'bytes=0-3'}).status_code == 206
        stat = pdf.stat()
        pdf.write_bytes(b'%PDF other')
        os.utime(pdf, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert client.get(url).headers['Cache-Control'] == 'no-store'
        assert client.get('/api/document?path=ab.qmd').json['pdfVersion'] != version
    finally:
        app.extensions['material_runtime'].close()


def test_browser_switch_reuses_pdf_version_and_restores_undo(tmp_path):
    import pytest
    import pymupdf
    from test_material_ui import LiveServer, free_port, sync_playwright

    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    for name in ('a', 'b'):
        (tmp_path / f'{name}.qmd').write_text(f'Original {name}\n')
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((72, 72), name)
            pdf.save(tmp_path / f'{name}.pdf')
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('''
localStorage.setItem('material-ui:auto-render', 'false');
localStorage.setItem('material-ui:auto-save', 'false');
''')
            page.goto(f'{url}?path=a.qmd', wait_until='domcontentloaded')
            page.wait_for_function("window.materialEditor?.getText() === 'Original a\\n'")
            page.wait_for_function("document.querySelector('#pdfPreview').getAttribute('src')?.includes('/api/pdf?')")
            first_pdf_url = page.locator('#pdfPreview').get_attribute('src')
            assert first_pdf_url and '/api/pdf?' in first_pdf_url
            content = page.locator('.editor-host .cm-content')
            content.click()
            page.keyboard.press('Control+End')
            page.keyboard.insert_text('Ergaenzung')
            page.keyboard.press('Control+s')
            page.wait_for_function("!document.querySelector('#saveDoc')?.hasAttribute('data-dirty')")
            # Use the same selection path as the tab buttons, without depending
            # on the folder tree or available tabs in this minimal repository.
            page.evaluate("import('/static/app.js').then(m => m.selectDocument('b.qmd'))")
            page.wait_for_function("window.materialEditor.getText() === 'Original b\\n'")
            assert page.locator('#pdfPreview').get_attribute('src') != first_pdf_url
            content.focus()
            page.keyboard.press('Control+z')
            assert page.evaluate('window.materialEditor.getText()') == 'Original b\n'
            page.evaluate("import('/static/app.js').then(m => m.selectDocument('a.qmd'))")
            page.wait_for_function("window.materialEditor.getText().includes('Ergaenzung')")
            assert page.locator('#pdfPreview').get_attribute('src') == first_pdf_url
            content.click()
            page.keyboard.press('Control+z')
            page.wait_for_function("window.materialEditor.getText() === 'Original a\\n'")
            # A cached state must be discarded when the file changed externally.
            page.evaluate("import('/static/app.js').then(m => m.selectDocument('b.qmd'))")
            (tmp_path / 'a.qmd').write_text('Extern geaendert\n')
            page.evaluate("import('/static/app.js').then(m => m.selectDocument('a.qmd'))")
            page.wait_for_function("window.materialEditor.getText() === 'Extern geaendert\\n'")
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_read_metadata_fast_matches_roundtrip_for_plain_frontmatter():
    from material_core.metadata import read_metadata, read_metadata_fast
    text = ('---\n'
            'title: "Bruchrechnung: Arbeitsblatt"\n'
            'subject: mathematik\n'
            'grade: "05"\n'
            'kind: Arbeitsblatt\n'
            'tags: [Bruchrechnung, "Übung 2"]\n'
            'solution: false\n'
            'format:\n'
            '  typst:\n'
            '    template: worksheet.typst\n'
            '---\n\nBody\n')
    assert dict(read_metadata_fast(text)) == dict(read_metadata(text))
    assert read_metadata_fast('Kein Frontmatter\n') == {}
    for broken in ('---\ntitle: a: b\n---\n', '---\n- liste\n---\n'):
        with pytest.raises(ValueError):
            read_metadata_fast(broken)


def test_warm_index_builds_payload_and_swallows_errors(tmp_path, monkeypatch):
    import material_ui.index_payload as index_payload
    from material_ui import app as material_app
    from material_ui.config import AppConfig
    from material_ui.runtime import RuntimeState

    runtime = RuntimeState(config=AppConfig(tmp_path))
    material_app.initialize_runtime(runtime)
    try:
        calls = []
        monkeypatch.setattr(index_payload, 'qmds_payload', lambda *args: calls.append(args) or {'qmds': []})
        material_app.warm_index(runtime)
        assert len(calls) == 1
        assert calls[0] == (runtime.config, runtime.services.documents)

        def broken(*args):
            raise RuntimeError('Warmup kaputt')

        monkeypatch.setattr(index_payload, 'qmds_payload', broken)
        material_app.warm_index(runtime)  # darf nicht hochwerfen
    finally:
        runtime.close()


def test_catalog_excludes_personal_directory_and_aliases(tmp_path):
    from material_ui.catalog import SourceCatalog

    private = tmp_path / 'foerderempfehlungen'
    private.mkdir()
    (private / 'private.qmd').write_text('Privat')
    (tmp_path / 'alias').symlink_to(private, target_is_directory=True)
    public = tmp_path / 'public.qmd'
    public.write_text('Material')
    catalog = SourceCatalog(AppConfig(tmp_path))
    assert catalog.sources('.qmd') == [public]
    assert private not in catalog.directories
    assert tmp_path / 'alias' not in catalog.directories


def test_discover_sources_excludes_individual_symlinked_md_alias(tmp_path):
    from material_ui.documents import DocumentService
    from material_ui.storage import DocumentRepository
    from material_core.builds import BuildService as CoreBuildService

    private = tmp_path / 'foerderempfehlungen'
    private.mkdir()
    (private / 'privat.md').write_text('---\nkind: Notiz\n---\nGeheim')
    public_dir = tmp_path / 'unterricht'
    public_dir.mkdir()
    (public_dir / 'offen.md').write_text('---\nkind: Notiz\n---\nOffen')
    # Not a symlinked directory (covered above), but a symlinked individual file inside
    # an otherwise visible directory: scan_result_visible() must still catch this.
    (public_dir / 'alias.md').symlink_to(private / 'privat.md')

    documents = DocumentService(AppConfig(tmp_path), DocumentRepository(), CoreBuildService(tmp_path, None))
    sources, warnings = documents.discover_sources()
    assert [path.name for path in sources] == ['offen.md']
    assert warnings == []


def test_catalog_head_cache_respects_requested_length(tmp_path):
    from material_ui.catalog import SourceCatalog

    source = tmp_path / 'source.md'
    source.write_text('abcdefgh')
    catalog = SourceCatalog(AppConfig(tmp_path))
    assert catalog.read_head(source, 2) == 'ab'
    assert catalog.read_head(source, 8) == 'abcdefgh'
    assert catalog.read_head(source, 2) == 'ab'


@pytest.mark.parametrize('header', ['{kind: Notiz}', '? kind\n: Notiz', '"k\\u0069nd": Notiz'])
def test_note_detection_accepts_yaml_key_syntax(tmp_path, header):
    from material_ui.documents import DocumentService
    from material_ui.storage import DocumentRepository

    source = tmp_path / 'planung.md'
    source.write_text(f'---\n{header}\n---\nNotiz\n')
    documents = DocumentService(AppConfig(tmp_path), DocumentRepository(), BuildService(tmp_path, None))
    sources, warnings = documents.discover_sources()
    assert sources == [source]
    assert warnings == []
