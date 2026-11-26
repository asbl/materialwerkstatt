"""Notes participate in lesson planning without generating teaching artifacts."""
from pathlib import Path

import pytest
from material_ui.app import create_app
from material_ui.config import AppConfig
from material_ui.units import UnitService


@pytest.fixture
def notes_app(tmp_path):
    app = create_app(config=AppConfig(tmp_path))
    folder = tmp_path / 'unterricht/mathematik/klasse-10/potenzen'
    folder.mkdir(parents=True)
    try:
        yield app, folder
    finally:
        app.extensions['material_runtime'].close()


def test_note_lifecycle_and_capabilities(notes_app):
    app, folder = notes_app
    runtime = app.extensions['material_runtime']
    client = app.test_client()
    client.environ_base["HTTP_X_MATERIAL_TOKEN"] = app.config["MATERIAL_CSRF_TOKEN"]
    relative = runtime.config.relative(folder)
    payload = {'kind': 'Notiz', 'title': 'Buchaufgaben', 'folder': relative}
    preview = client.get('/api/document/new-preview', query_string=payload).get_json()
    response = client.post('/api/document/new', json=payload)
    assert response.status_code == 200, response.get_json()
    path = response.get_json()['path']
    assert path == preview['path'] == f'{relative}/notiz_buchaufgaben.md'
    assert 'template' not in (folder / 'notiz_buchaufgaben.md').read_text()
    (folder / 'hinweise.md').write_text('# Allgemeine Hinweise')
    (folder / 'README.md').write_text('# Dokumentation')
    documents = runtime.services.documents
    assert documents.qmd_sources() == [runtime.config.root / path]
    assert documents.qmd_entry(runtime.config.root / path)['kind'] == 'Notiz'
    service = UnitService(runtime.config, documents)
    unit = service.overview()['units'][0]
    unit['data']['einsatz'] = [{'datum': '2026-11-11', 'material': 'notiz_buchaufgaben.md'}]
    service.save(unit['path'], unit['data'], unit['revision'])
    opened = client.get('/api/document', query_string={'path': path}).get_json()
    assert opened['capabilities'] == {'edit': True, 'render': False, 'present': False}
    assert opened['pdf'] is None and not opened['hasSlides']
    saved = client.post('/api/document', json={'path': path, 'revision': opened['revision'], 'text': opened['text'] + '\nS. 42 Nr. 3\n'})
    assert saved.status_code == 200
    assert saved.get_json()['renderNeeded'] is False
    assert client.post('/api/document', json={'path': path, 'revision': opened['revision'], 'text': 'stale'}).status_code == 409
    for endpoint in ['/api/render', '/api/slides/ensure', '/api/slides/rebuild', '/api/worksheet/start']:
        assert client.post(endpoint, json={'path': path}).status_code == 400
    assert client.get('/api/search?q=42').get_json()['results'][0]['path'] == path
    issues = documents.document_issues(runtime.config.root / path)
    assert not any('PDF' in issue['title'] for issue in issues)
    renamed = client.post('/api/file/rename', json={'path': path, 'name': 'notiz_buch.md'})
    assert renamed.status_code == 200, renamed.get_json()
    assert service.read(folder)['data']['einsatz'][0]['material'] == 'notiz_buch.md'
    assert client.post('/api/document/new', json={**payload, 'filename': 'buch'}).status_code >= 400
    destination = folder.parent / 'wiederholung'
    destination.mkdir()
    moved = client.post('/api/file/move', json={'path': renamed.get_json()['path'], 'destination': runtime.config.relative(destination)})
    assert moved.status_code == 200, moved.get_json()
    assert (destination / 'notiz_buch.md').is_file()
    assert service.read(folder)['data']['einsatz'][0].get('material', '') == ''


def test_browser_create_note_and_switch_workspace(notes_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, folder = notes_app
    runtime = app.extensions['material_runtime']
    service = UnitService(runtime.config, runtime.services.documents)
    unit = service.read(folder)
    service.save(unit['path'], {'titel': 'Potenzen', 'thema': 'Potenzen', 'kurzbeschreibung': '', 'einsatz': [{'datum': '2026-11-11'}]}, unit['revision'])
    (folder / 'ab_test.qmd').write_text('---\ntitle: Übungen\n---\nText\n')
    with LiveServer(app, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.clock.set_fixed_time('2026-11-09T12:00:00+01:00')
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        renders = []
        page.on('request', lambda request: renders.append(request.url) if request.url.endswith(('/api/render', '/api/slides/ensure')) else None)
        page.goto(url, wait_until='networkidle')
        page.locator('#viewButton-units').click()
        card = page.locator('.unit-card')
        if card.get_attribute('open') is None:
            card.locator(':scope > summary').click()
        page.locator('[data-new-note]').click()
        assert not page.locator('#newTemplate').is_visible()
        page.locator('#newTitle').fill('Buchaufgaben')
        page.locator('#createNewDoc').click()
        page.wait_for_selector('body.note-document')
        assert page.locator('.preview-pane').is_visible()
        page.frame_locator('#markdownPreview').locator('h1').wait_for()
        assert page.locator('.cm-content').get_attribute('spellcheck') == 'true'
        assert not page.locator('#slidesPlay').is_visible()
        assert not page.locator('.discussion-actions').is_visible()
        assert not page.locator('#changeTemplate').is_visible()
        page.locator('#headerMenuToggle').click()
        page.locator('#autoRender').check()
        page.locator('#headerMenuToggle').click()
        page.locator('.editor-host .cm-content').click()
        page.keyboard.press('Control+End')
        page.keyboard.type('Buch S. 42 Nr. 3')
        page.frame_locator('#markdownPreview').get_by_text('Buch S. 42 Nr. 3', exact=False).wait_for()
        page.wait_for_function("document.querySelector('#renderStatus').textContent.includes('Notiz gespeichert')")
        page.keyboard.press('Control+Enter')
        assert renders == []
        page.locator('#headerMenuToggle').click()
        page.locator('#autoRender').uncheck()
        page.locator('#headerMenuToggle').click()
        page.locator('.unit-material-link').filter(has_text='Übungen').click()
        page.wait_for_selector('body:not(.note-document)')
        assert page.locator('.preview-pane').is_visible()
        assert page.locator('#changeTemplate').is_visible()
        assert renders == []
        browser.close()


def test_notes_remain_separate_from_folder_hints(tmp_path):
    from material_ui.document_types import is_note
    from material_ui.folder_notes import is_folder_note, read_notes
    note = tmp_path / 'notiz_hinweise.md'
    note.write_text('---\nkind: Notiz\n---\nBuchaufgaben')
    hints = tmp_path / 'hinweise.md'
    hints.write_text('---\nkind: Notiz\n---\nOrdnerhinweise')
    assert is_note(note) and not is_folder_note(note.name)
    assert not is_note(hints) and is_folder_note(hints.name)
    assert 'Buchaufgaben' not in read_notes(tmp_path)['text']


def test_unreadable_markdown_does_not_block_materials(notes_app, monkeypatch):
    app, folder = notes_app
    runtime = app.extensions['material_runtime']
    root = runtime.config.root
    (folder / 'notiz_buch.md').write_text('---\ntitle: Buchaufgaben\nkind: Notiz\n---\nBuchaufgaben')
    (folder / 'ab_test.qmd').write_text('---\ntitle: Übungen\n---\nBuchaufgaben')
    (root / 'README.md').write_bytes(b'\xff')
    blocked = root / 'blocked.md'
    blocked.write_text('Not readable')
    (root / 'missing.md').symlink_to(root / 'absent.md')
    documents = runtime.services.documents
    read_text = documents.catalog.read_text
    read_head = documents.catalog.read_head

    def read(path):
        if path == blocked:
            raise PermissionError('Cannot read blocked.md')
        return read_text(path)

    def head(path, limit=16 * 1024):
        # Das Kopf-Lesen ist der erste IO-Zugriff; unlesbare Dateien fallen hier auf.
        if path == blocked:
            raise PermissionError('Cannot read blocked.md')
        return read_head(path, limit)

    monkeypatch.setattr(documents.catalog, 'read_text', read)
    monkeypatch.setattr(documents.catalog, 'read_head', head)
    client = app.test_client()
    response = client.get('/api/qmds')
    assert response.status_code == 200
    payload = response.get_json()
    assert {entry['name'] for entry in payload['qmds']} == {'notiz_buch.md', 'ab_test.qmd'}
    assert {warning['path'] for warning in payload['warnings']} == {'README.md', 'blocked.md', 'missing.md'}
    response = client.get('/api/units')
    assert response.status_code == 200
    assert len(response.get_json()['units']) == 1
    response = client.get('/api/search?q=Buchaufgaben')
    assert response.status_code == 200
    assert len(response.get_json()['results']) == 2


def test_folder_metadata_keeps_notes_and_filters_nonmaterials(notes_app):
    app, folder = notes_app
    runtime = app.extensions['material_runtime']
    for name in ['notiz_buch.md', 'planung.md']:
        (folder / name).write_text('---\ntitle: Buchaufgaben\nkind: Notiz\ntags: [buch]\n---\n')
    (folder / 'ab_test.qmd').write_text('---\ntitle: Übungen\n---\n')
    (folder / 'ab_test-old.qmd').write_text('---\ntitle: Alte Übungen\n---\n')
    (folder / 'README.md').write_text('Dokumentation')
    (folder / 'hinweise.md').write_text('Ordnerhinweise')
    (folder / 'bild.png').write_bytes(b'\xff')
    (folder / 'broken.md').write_bytes(b'\xff')
    client = app.test_client()
    global_entries = client.get('/api/qmds').get_json()['qmds']
    response = client.get('/api/folder', query_string={'path': runtime.config.relative(folder), 'metadata': '1'})
    assert response.status_code == 200
    payload = response.get_json()
    assert {entry['path'] for entry in payload['qmds']} == {entry['path'] for entry in global_entries}
    assert {entry['name'] for entry in payload['qmds']} == {'notiz_buch.md', 'planung.md', 'ab_test.qmd'}
    assert [warning['path'] for warning in payload['warnings']] == [runtime.config.relative(folder / 'broken.md')]


def test_note_rename_preserves_type_and_references(notes_app):
    app, folder = notes_app
    runtime = app.extensions['material_runtime']
    documents = runtime.services.documents
    source = documents.create_document({'folder': runtime.config.relative(folder), 'kind': 'Notiz', 'title': 'Buch'})
    service = UnitService(runtime.config, documents)
    unit = service.read(folder)
    unit['data']['einsatz'] = [{'datum': '2026-11-11', 'material': source.name}]
    service.save(unit['path'], unit['data'], unit['revision'])
    original_text = source.read_bytes()
    original_unit = (folder / 'einheit.yaml').read_bytes()
    client = app.test_client()
    client.environ_base['HTTP_X_MATERIAL_TOKEN'] = app.config['MATERIAL_CSRF_TOKEN']
    for name in ['hinweise.md', 'allgemeine-hinweise.md', 'buch.qmd', 'buch.txt', 'buch.MD']:
        response = client.post('/api/file/rename', json={'path': runtime.config.relative(source), 'name': name})
        assert response.status_code == 400, (name, response.get_json())
        assert source.read_bytes() == original_text
        assert (folder / 'einheit.yaml').read_bytes() == original_unit
        assert not (folder / name).exists()
    response = client.post('/api/file/rename', json={'path': runtime.config.relative(source), 'name': 'buch.md'})
    assert response.status_code == 200
    opened = client.get('/api/document', query_string={'path': response.get_json()['path']}).get_json()
    assert opened['capabilities']['render'] is False
    assert service.read(folder)['data']['einsatz'][0]['material'] == 'buch.md'


def test_note_without_valid_header_cannot_lose_filename_marker(tmp_path):
    from material_ui.document_types import ensure_note_rename
    from material_ui.errors import InvalidInput
    source = tmp_path / 'notiz_buch.md'
    source.write_text('---\nkind: [\n---\nBuchaufgaben')
    with pytest.raises(InvalidInput):
        ensure_note_rename(source, tmp_path / 'buch.md')
    ensure_note_rename(source, tmp_path / 'notiz_aufgaben.md')


def test_browser_note_chat_layout():
    from pathlib import Path
    from test_material_ui import host_css, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    ui = Path(__file__).resolve().parents[1] / 'material_ui'
    core_css = host_css()
    chat_css = (ui / 'plugins/chat/assets/chat-panel.css').read_text()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        for styles in [core_css + chat_css, chat_css + core_css]:
            page.set_content('<style>' + styles + '</style><main class="workspace chat-open" style="width:1200px;height:700px"><aside class="workspace-index">Index</aside><section class="editor-pane">Editor</section><section class="preview-pane">Preview</section><aside class="chat-dock">Chat</aside></main>')
            for mode in ['', 'index-collapsed', 'focus-mode', 'index-collapsed focus-mode']:
                pane = page.locator('.workspace')
                pane.evaluate('(node, mode) => node.className = `workspace chat-open ${mode}`', mode)
                editor = page.locator('.editor-pane').bounding_box()
                chat = page.locator('.chat-dock').bounding_box()
                workspace = pane.bounding_box()
                assert page.locator('.preview-pane').is_visible()
                assert chat['width'] == 340
                preview = page.locator('.preview-pane').bounding_box()
                assert abs(editor['x'] + editor['width'] + 10 - preview['x']) < 1
                assert abs(preview['x'] + preview['width'] + 10 - chat['x']) < 1
                assert abs(chat['x'] + chat['width'] + 10 - workspace['x'] - workspace['width']) < 1
                assert editor['y'] == chat['y']
        browser.close()


def test_note_detection_scans_header_only_for_plain_markdown(tmp_path, monkeypatch):
    """Markdown ohne Top-Level-kind im Frontmatter wird nicht volltext-gelesen/parst."""
    app = create_app(config=AppConfig(tmp_path))
    try:
        runtime = app.extensions['material_runtime']
        documents = runtime.services.documents
        # wissen/ ist auf Root-Ebene vom Katalog-Scan ausgeschlossen (39b6ab92): Die
        # Testdateien liegen deshalb in einem beliebigen, nicht ausgeschlossenen Ordner.
        folder = tmp_path / 'notizen' / 'mathe'
        folder.mkdir(parents=True)
        plain = folder / 'readme.md'
        plain.write_text('# Doku\n\n' + 'Langtext ohne Frontmatter\n' * 2000, encoding='utf-8')
        stem_note = folder / 'notiz_lernen.md'
        stem_note.write_text('# Lernen\n', encoding='utf-8')
        kind_note = folder / 'probe.md'
        kind_note.write_text('---\ntitle: Probe\nkind: Notiz\n---\n\nBody\n', encoding='utf-8')
        read_texts = []
        original_read_text = documents.catalog.read_text

        def recording_read_text(path):
            read_texts.append(Path(path))
            return original_read_text(path)

        monkeypatch.setattr(documents.catalog, 'read_text', recording_read_text)
        sources, warnings = documents.discover_sources()
        assert warnings == []
        assert sorted(path.name for path in sources) == ['notiz_lernen.md', 'probe.md']
        # Nur die kind-Notiz braucht den Volltext; die Stem-Notiz und die Doku nicht.
        assert plain not in read_texts
        assert stem_note not in read_texts
        assert set(read_texts) == {kind_note}
    finally:
        app.extensions['material_runtime'].close()


def test_note_detection_falls_back_to_full_read_on_truncated_or_damaged_header(tmp_path):
    """Abgeschnittener/unlesbarer Kopf und kaputte Dateien verhalten sich wie bisher."""
    app = create_app(config=AppConfig(tmp_path))
    try:
        runtime = app.extensions['material_runtime']
        documents = runtime.services.documents
        folder = tmp_path / 'notizen'
        folder.mkdir()
        truncated = folder / 'gross.md'
        truncated.write_text('---\n' + ''.join(f'feld{i}: wert\n' for i in range(3000)) + 'kind: Notiz\n---\n\nBody\n', encoding='utf-8')
        corrupt = folder / 'kaputt.md'
        corrupt.write_bytes(b'---\nkind: Notiz\n---\n\n' + b'\xff\xfe kaputt')
        sources, warnings = documents.discover_sources()
        # Header reicht ueber den 16-KiB-Kopf hinaus: Volltext-Fallback findet kind: Notiz.
        assert truncated in sources
        # Kaputte Datei: Lesefehler als Warning, Index bleibt nutzbar.
        assert corrupt not in sources
        assert [warning['path'] for warning in warnings] == [runtime.config.relative(corrupt)]
        # Nochmaliger Lauf nutzt den Fingerprint-Cache und meldet dieselbe Warning.
        documents.invalidate_qmd_cache()
        _, warnings_again = documents.discover_sources()
        assert warnings_again == warnings
    finally:
        app.extensions['material_runtime'].close()


def test_worksheet_note_creates_and_opens_beside_ab(notes_app):
    """Notiz zu einem AB anlegen: Name, Frontmatter, Faehigkeiten, Idempotenz."""
    app, folder = notes_app
    runtime = app.extensions['material_runtime']
    client = app.test_client()
    client.environ_base["HTTP_X_MATERIAL_TOKEN"] = app.config["MATERIAL_CSRF_TOKEN"]
    (folder / 'ab_bruchrechnen.qmd').write_text(
        '---\ntitle: Bruchrechnen\nkind: Arbeitsblatt\ntags: [Arbeitsblatt]\n---\n\n::: aufgabe\nAddieren.\n:::\n', encoding='utf-8')
    relative = f'{runtime.config.relative(folder)}/ab_bruchrechnen.qmd'
    response = client.post('/api/document/note', json={'path': relative})
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    note_path = f'{runtime.config.relative(folder)}/ab_bruchrechnen-notizen.md'
    assert data['created'] is True and data['path'] == note_path
    text = (folder / 'ab_bruchrechnen-notizen.md').read_text(encoding='utf-8')
    assert 'title: "Notizen zu Bruchrechnen"' in text
    assert 'kind: Notiz' in text
    assert '## Gut gelaufen' in text
    entry = next(item for item in data['qmds'] if item['path'] == note_path)
    assert entry['kind'] == 'Notiz' and not entry['solution']
    opened = client.get('/api/document', query_string={'path': note_path}).get_json()
    assert opened['capabilities'] == {'edit': True, 'render': False, 'present': False}
    assert client.post('/api/render', json={'path': note_path}).status_code == 400
    # Der zweite Aufruf oeffnet die bestehende Notiz, ohne sie anzufassen.
    (folder / 'ab_bruchrechnen-notizen.md').write_text(
        text + '\nGut gelaufen: Einstieg ueber Platten.\n', encoding='utf-8')
    second = client.post('/api/document/note', json={'path': relative}).get_json()
    assert second['created'] is False and second['path'] == note_path
    assert (folder / 'ab_bruchrechnen-notizen.md').read_text(encoding='utf-8').endswith('Platten.\n')
    # Notizen haengen an QMD-Dateien; Notizen und fehlende Dateien werden abgelehnt.
    assert client.post('/api/document/note', json={'path': note_path}).status_code == 400
    assert client.post('/api/document/note', json={'path': f'{runtime.config.relative(folder)}/ab_fehlt.qmd'}).status_code == 400


def test_worksheet_note_title_falls_back_to_stem(notes_app):
    """Ohne Frontmatter-Titel im AB liefert der Dateistamm den Notiztitel."""
    app, folder = notes_app
    runtime = app.extensions['material_runtime']
    client = app.test_client()
    client.environ_base["HTTP_X_MATERIAL_TOKEN"] = app.config["MATERIAL_CSRF_TOKEN"]
    (folder / 'ab_05.qmd').write_text('Nur Text ohne Frontmatter.\n', encoding='utf-8')
    data = client.post('/api/document/note', json={'path': f'{runtime.config.relative(folder)}/ab_05.qmd'}).get_json()
    text = (folder / 'ab_05-notizen.md').read_text(encoding='utf-8')
    assert 'title: "Notizen zu ab 05"' in text
    assert data['created'] is True


def test_browser_worksheet_note_button_creates_and_pairs(notes_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, folder = notes_app
    runtime = app.extensions['material_runtime']
    service = UnitService(runtime.config, runtime.services.documents)
    unit = service.read(folder)
    service.save(unit['path'], {'titel': 'Potenzen', 'thema': 'Potenzen', 'kurzbeschreibung': '', 'einsatz': [{'datum': '2026-11-11'}]}, unit['revision'])
    (folder / 'ab_test.qmd').write_text('---\ntitle: Übungen\nkind: Arbeitsblatt\ntags: [Arbeitsblatt]\n---\nText\n', encoding='utf-8')
    ab_path = f'{runtime.config.relative(folder)}/ab_test.qmd'
    note_path = f'{runtime.config.relative(folder)}/ab_test-notizen.md'
    with LiveServer(app, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.clock.set_fixed_time('2026-11-09T12:00:00+01:00')
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(f'{url}/?path={ab_path}', wait_until='networkidle')
        # Notiz-Knopf an der AB-Zeile der Ordneransicht legt die Datei an und oeffnet sie.
        page.locator(f'#folderEntries button[data-document="{ab_path}"]').hover()
        create_note = page.locator(f'#folderEntries button[data-worksheet-note="{ab_path}"]')
        assert create_note.inner_text() == 'Neue Notiz anlegen'
        create_note.click()
        page.wait_for_selector('body.note-document')
        assert (folder / 'ab_test-notizen.md').is_file()
        page.wait_for_function("window.materialEditor.getText().includes('Gut gelaufen')")
        # Die gepaarte Notiz steht direkt unter dem AB, wie eine Loesung.
        page.wait_for_selector(f'.folder-paired-note button[data-document="{note_path}"]')
        assert page.locator('.folder-paired-note .folder-paired-label').inner_text() == 'Notizen'
        assert page.locator(f'#folderEntries button[data-worksheet-note="{ab_path}"]').count() == 0
        assert page.locator(f'#folderEntries button[data-delete="{note_path}"]').count() == 0
        # In der Einheitenansicht ist die Notiz ebenfalls an das AB gepaart.
        page.locator('#viewButton-units').click()
        card = page.locator('.unit-card')
        if card.get_attribute('open') is None:
            card.locator(':scope > summary').click()
        page.wait_for_selector('.unit-note-link')
        assert page.locator('.unit-note-link .unit-note-label').inner_text() == 'Notizen'
        assert card.locator('[data-worksheet-note]').count() == 0
        assert card.locator('[data-delete-material="ab_test-notizen.md"]').count() == 0
        page.locator('.document-settings > summary').click()
        page.locator('#deleteOpenDocument').click()
        assert page.locator('#fileActionModal').is_visible()
        page.locator('#fileActionConfirm').click()
        page.locator('#fileActionModal').wait_for(state='hidden')
        assert not (folder / 'ab_test-notizen.md').exists()
        assert card.locator('[data-worksheet-note]').inner_text() == 'Notiz'
        browser.close()


@pytest.mark.parametrize('stem,suffix', [
    ('ab_test', '-notiz'), ('ab_test', '_notizen'),
    ('ab_test-loesung', '-notizen'), ('ab_test-loesung', '_notiz'),
])
def test_note_action_reuses_existing_note_variants(notes_app, stem, suffix):
    app, folder = notes_app
    runtime = app.extensions['material_runtime']
    source = folder / f'{stem}.qmd'
    source.write_text('---\ntitle: Test\n---\nText\n', encoding='utf-8')
    note = folder / f'{stem}{suffix}.md'
    text = '---\nkind: Notiz\n---\nMeine vorhandenen Notizen\n'
    note.write_text(text, encoding='utf-8')
    client = app.test_client()
    client.environ_base['HTTP_X_MATERIAL_TOKEN'] = app.config['MATERIAL_CSRF_TOKEN']
    response = client.post('/api/document/note', json={'path': runtime.config.relative(source)})
    assert response.status_code == 200
    assert response.json['created'] is False
    assert response.json['path'] == runtime.config.relative(note)
    assert note.read_text(encoding='utf-8') == text
    assert list(folder.glob('*.md')) == [note]


@pytest.mark.parametrize('stem,suffix', [
    ('ab_test', '-notiz'), ('ab_test-loesung', '-notizen'),
    ('ab_test-loesung', '_notiz'),
])
def test_browser_note_toolbar_opens_existing_note(notes_app, stem, suffix):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    from playwright.sync_api import expect
    app, folder = notes_app
    runtime = app.extensions['material_runtime']
    source = folder / f'{stem}.qmd'
    source.write_text('---\ntitle: Test\n---\nText\n', encoding='utf-8')
    note = folder / f'{stem}{suffix}.md'
    note.write_text('---\nkind: Notiz\n---\nMeine vorhandenen Notizen\n', encoding='utf-8')
    with LiveServer(app, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(f'{url}/?path={runtime.config.relative(source)}', wait_until='networkidle')
            button = page.locator('.discussion-actions').get_by_role('button', name='Notizen', exact=True)
            expect(button).to_be_visible()
            expect(page.locator('.discussion-actions')).not_to_contain_text('Neue Notiz anlegen')
            button.click()
            expect(page.locator('body')).to_have_class(__import__('re').compile('note-document'))
            page.wait_for_function("window.materialEditor.getText().includes('Meine vorhandenen Notizen')")
            assert list(folder.glob('*.md')) == [note]
        finally:
            browser.close()
