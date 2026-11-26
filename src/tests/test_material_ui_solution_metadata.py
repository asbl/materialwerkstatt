from pathlib import Path
import json
import subprocess

import pytest

from material_ui.metadata import ensure_solution_metadata, read_metadata
from material_ui.storage import DocumentRepository, RevisionConflict, revision
from test_material_ui import material_root, write_qmd
from material_ui import app as material_app


@pytest.mark.parametrize('name', ['ab_Lösungen.qmd', 'AB-LOESUNG.qmd', 'Musterlösung.qmd', 'ab_musterloesungen.qmd'])
def test_filename_metadata_preserves_body_and_existing_tags(name):
    text = '---\ntitle: "Original" # behalten\ntags: [Mathematik]\nkind: Arbeitsblatt\n---\n\n## Aufgabe\n'
    result = ensure_solution_metadata(Path(name), text)
    metadata = read_metadata(result)
    assert metadata['kind'] == 'Lösung'
    assert metadata['tags'] == ['Mathematik', 'Lösung']
    assert '# behalten' in result
    assert result.endswith('\n\n## Aufgabe\n')
    assert ensure_solution_metadata(Path(name), result) == result
    assert ensure_solution_metadata(Path('ab_test.qmd'), text) == text


def test_repository_save_returns_normalized_text_and_checks_revision(tmp_path):
    source = write_qmd(tmp_path / 'ab_loesungen.qmd')
    repository = DocumentRepository()
    original = source.read_text()
    result = repository.save(source, original, revision(original))
    assert result['text'] == source.read_text()
    assert result['revision'] == revision(result['text'])
    assert read_metadata(result['text'])['tags'] == ['Lösung']
    with pytest.raises(RevisionConflict):
        repository.save(source, original, revision(original))


def test_index_is_read_only_and_explicit_repair_and_filters(material_root):
    source = write_qmd(material_root / 'unterricht/ab_Lösungen.qmd')
    client = material_app.create_app().test_client()
    original = source.read_bytes()
    response = client.get('/api/qmds')
    assert response.status_code == 200
    assert source.read_bytes() == original
    assert not (source.parent / '.material-history').exists()
    repaired = client.post('/api/materials/repair-solution-metadata')
    assert repaired.json['changed'] == ['unterricht/ab_Lösungen.qmd']
    assert client.post('/api/materials/repair-solution-metadata').json['changed'] == []
    assert read_metadata(source.read_text())['kind'] == 'Lösung'
    assert read_metadata(source.read_text())['tags'] == ['Lösung']
    assert source.read_text().count('Lösung') == 2
    before = source.stat().st_mtime_ns
    client.get('/api/qmds')
    assert source.stat().st_mtime_ns == before
    other = write_qmd(material_root / 'unterricht/ab_test.qmd')
    result = client.post('/api/file/rename', json={'path': 'unterricht/ab_test.qmd', 'name': 'ab_test-loesung.qmd'})
    assert result.status_code == 200
    renamed = other.with_name('ab_test-loesung.qmd')
    assert 'tags' not in read_metadata(renamed.read_text())
    assert next(entry for entry in result.json['qmds'] if entry['path'].endswith('ab_test-loesung.qmd'))['tags'] == ['Lösung']
    response = client.get('/api/search', query_string={'tags': 'Lösung'})
    assert response.status_code == 200
    assert {entry['path'] for entry in response.json['results']} == {'unterricht/ab_Lösungen.qmd', 'unterricht/ab_test-loesung.qmd'}


def test_material_icons_distinguish_types_and_prioritize_solutions():
    module = (Path(__file__).resolve().parents[1] / 'material_ui/static/ui-utils.js').as_uri()
    script = '''
import assert from 'node:assert/strict';
import {materialIcon} from MODULE;
assert.equal(materialIcon({kind:'Arbeitsblatt'}), 'worksheet');
assert.equal(materialIcon({name:'ab_uebung.qmd'}), 'worksheet');
assert.equal(materialIcon({kind:'Arbeitsblatt', deck:'slide.excalidraw'}), 'worksheet');
assert.equal(materialIcon({kind:'Arbeitsblatt', solution:true}), 'solution');
assert.equal(materialIcon({name:'ab_Lösungen.qmd'}), 'solution');
assert.equal(materialIcon({name:'01 slide.qmd'}), 'slides');
assert.equal(materialIcon({kind:'Praesentation'}), 'slides');
assert.equal(materialIcon({kind:'Deck'}), 'slides');
assert.equal(materialIcon({name:'readme.md'}), 'file');
'''.replace('MODULE', json.dumps(module))
    result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_incomplete_solution_header_remains_editable(tmp_path):
    source = write_qmd(tmp_path / 'loesung.qmd')
    repository = DocumentRepository()
    incomplete = '---\ntags: [\n---\nAufgabe\n'
    repository.save(source, incomplete)
    assert source.read_text() == incomplete
    repository.save(source, '---\ntitle: Korrigiert\n---\nAufgabe\n')
    assert read_metadata(source.read_text())['kind'] == 'Lösung'


def test_browser_solution_save_syncs_editor_and_type_icons(material_root):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    source = write_qmd(material_root / 'ab_loesungen.qmd')
    write_qmd(material_root / 'ab_uebung.qmd')
    write_qmd(material_root / 'slide.qmd')
    app = material_app.create_app()
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:auto-save", "false")')
        page.goto(url + '?path=ab_loesungen.qmd', wait_until='networkidle')
        page.wait_for_function('window.materialEditor && window.materialEditor.getText().includes("title:")')
        for name, icon in [('ab_loesungen.qmd', 'solution'), ('ab_uebung.qmd', 'worksheet'), ('slide.qmd', 'slides')]:
            assert page.locator(f'[data-document="{name}"] use').first.get_attribute('href') == '/static/icons.svg#' + icon
        page.evaluate('window.materialEditor.setText("---\\ntitle: Neu\\n---\\n\\nGeändert\\n")')
        page.click('#saveDoc')
        page.wait_for_function('window.materialEditor.getText().includes("kind: Lösung")')
        page.wait_for_function('document.querySelector("#docSaveFeedback").textContent.includes("Gespeichert")')
        assert source.read_text() == page.evaluate('window.materialEditor.getText()')
        browser.close()
