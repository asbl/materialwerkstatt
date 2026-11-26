import pytest

from material_ui.app import create_app
from material_ui.config import AppConfig
from test_material_ui import LiveServer, free_port, sync_playwright
from test_material_ui_robustness import replace_editor_text


@pytest.fixture()
def folder_app(tmp_path):
    folder = tmp_path / 'unterricht' / 'alt'
    (folder / 'unterordner').mkdir(parents=True)
    (folder / 'blatt.qmd').write_text('---\ntitle: Blatt\n---\n\nInhalt\n')
    (folder / 'unterordner' / 'zweites.qmd').write_text('Zweites Blatt\n')
    (folder / 'bild.png').write_bytes(b'asset')
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        yield app, tmp_path
    finally:
        app.extensions['material_runtime'].close()


def test_folder_rename_preserves_contents_and_refreshes_index(folder_app):
    app, root = folder_app
    client = app.test_client()
    client.get('/api/qmds')
    response = client.post('/api/folder/rename', json={'path': 'unterricht/alt', 'name': 'Neuer Ordner'})
    assert response.status_code == 200
    assert response.json['path'] == 'unterricht/Neuer Ordner'
    assert not (root / 'unterricht/alt').exists()
    assert (root / 'unterricht/Neuer Ordner/bild.png').read_bytes() == b'asset'
    assert {entry['path'] for entry in response.json['qmds']} == {
        'unterricht/Neuer Ordner/blatt.qmd', 'unterricht/Neuer Ordner/unterordner/zweites.qmd'
    }


@pytest.mark.parametrize('name', ['', ' ', '.', '..', '../neu', 'neu/ordner', 'neu\\ordner', '.intern'])
def test_folder_rename_rejects_invalid_names(folder_app, name):
    app, root = folder_app
    assert app.test_client().post('/api/folder/rename', json={'path': 'unterricht/alt', 'name': name}).status_code == 400
    assert (root / 'unterricht/alt/blatt.qmd').is_file()


@pytest.mark.parametrize(('path', 'name', 'status'), [
    ('.', 'neu', 400), ('..', 'neu', 400), ('fehlt', 'neu', 404),
    ('unterricht/alt/blatt.qmd', 'neu', 404), ('unterricht/alt', 'alt', 409),
    ('unterricht/alt', 'belegt', 409), ('unterricht/alt', 'datei', 409),
    ('.intern', 'neu', 400),
])
def test_folder_rename_rejects_invalid_source_and_collisions(folder_app, path, name, status):
    app, root = folder_app
    (root / 'unterricht/belegt').mkdir()
    (root / 'unterricht/datei').write_text('erhalten')
    (root / '.intern').mkdir()
    assert app.test_client().post('/api/folder/rename', json={'path': path, 'name': name}).status_code == status
    assert (root / 'unterricht/alt/blatt.qmd').is_file()
    assert (root / 'unterricht/datei').read_text() == 'erhalten'


def test_browser_folder_rename_updates_active_document_and_nested_tabs(folder_app):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    app, root = folder_app
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1500, 'height': 1000})
        page.add_init_script('''
localStorage.setItem('material-ui:auto-render', 'false'); if (!localStorage.getItem('material-ui:active-view')) localStorage.setItem('material-ui:active-view', 'folder');
localStorage.setItem('material-ui:auto-save', 'false');
localStorage.setItem('material-ui:open-tabs', JSON.stringify([
  'unterricht/alt/blatt.qmd', 'unterricht/alt/unterordner/zweites.qmd'
]));
''')
        page.goto(f'{url}?path=unterricht/alt/blatt.qmd', wait_until='networkidle')
        page.locator('[data-tab="unterricht/alt/unterordner/zweites.qmd"]').wait_for()
        replace_editor_text(page, 'Geänderter Inhalt\n')
        row = page.locator('summary[data-folder="unterricht/alt"]')
        row.hover()
        row.locator('[data-rename-folder]').click()
        assert page.locator('#fileActionTitle').inner_text() == 'Ordner bearbeiten'
        assert page.locator('#fileActionName').input_value() == 'alt'
        page.locator('#fileActionName').fill('neu')
        page.locator('#fileActionConfirm').click()
        page.wait_for_function("!document.getElementById('fileActionModal').classList.contains('open')")
        page.locator('[data-tab="unterricht/neu/blatt.qmd"][aria-current="true"]').wait_for()
        assert page.locator('[data-tab="unterricht/neu/unterordner/zweites.qmd"]').count() == 1
        assert 'unterricht%2Fneu%2Fblatt.qmd' in page.url or 'unterricht/neu/blatt.qmd' in page.url
        assert page.locator('#navigationFolder').input_value() == 'unterricht/neu'
        assert (root / 'unterricht/neu/blatt.qmd').is_file()
        assert (root / 'unterricht/neu/blatt.qmd').read_text() == 'Geänderter Inhalt\n'
        page.locator('[data-tab="unterricht/neu/unterordner/zweites.qmd"]').click()
        page.wait_for_function("window.materialEditor.getText() === 'Zweites Blatt\\n'")
        browser.close()


@pytest.mark.parametrize('path', ['unterricht/link', 'unterricht/link/unterordner'])
def test_folder_rename_rejects_symlinks_in_source_path(folder_app, path):
    app, root = folder_app
    (root / 'unterricht/link').symlink_to(root / 'unterricht/alt', target_is_directory=True)
    response = app.test_client().post('/api/folder/rename', json={'path': path, 'name': 'neu'})
    assert response.status_code == 400
    assert (root / 'unterricht/alt/unterordner').is_dir()
    assert (root / 'unterricht/link').is_dir()
    assert not (root / 'unterricht/neu').exists()


def saved_slides(app, root, extension='qmd', current=True):
    import json
    from material_core.metadata import set_template
    from material_ui.slides import annotations_path

    source = root / f'unterricht/alt/unterordner/slide.{extension}'
    source.write_text(set_template('## Bild\n\n![](bild.svg)\n', 'src/quarto/templates/slide-template.typst', 'typst'))
    (source.parent / 'bild.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
    slides = app.extensions['material_runtime'].services.slides
    deck = slides.deck_path(source)
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text('{"elements": [{"id": "bearbeitete-szene"}]}')
    annotations = annotations_path(deck)
    annotations.parent.mkdir()
    annotations.write_text('{"elements": [{"id": "handschrift"}]}')
    stamp = slides.source_stamp(deck)
    stamp.parent.mkdir()
    stamp.write_text(json.dumps({'signature': slides.signature(source) if current else 'veraltet'}))
    backup = deck.with_name(deck.name + '.bak-test')
    backup.write_text('Frühere Szene')
    return slides, source, deck, annotations, stamp, backup


@pytest.mark.parametrize('extension', ['qmd', 'md'])
def test_folder_rename_keeps_saved_slides_current_with_images(folder_app, monkeypatch, extension):
    app, root = folder_app
    slides, source, deck, annotations, stamp, backup = saved_slides(app, root, extension)
    contents = {path: path.read_bytes() for path in (deck, annotations, backup)}
    old_signature = slides.signature(source)
    response = app.test_client().post('/api/folder/rename', json={'path': 'unterricht/alt', 'name': 'neu'})
    assert response.status_code == 200
    renamed_source = root / f'unterricht/neu/unterordner/slide.{extension}'
    assert slides.signature(renamed_source) != old_signature
    for path, content in contents.items():
        renamed = root / str(path.relative_to(root)).replace('/alt/', '/neu/')
        assert renamed.read_bytes() == content
        assert not path.exists()
    assert slides.is_current(renamed_source)

    def fail_rebuild(*args, **kwargs):
        pytest.fail('Gespeicherte Präsentation darf nach Umbenennen nicht neu gebaut werden')

    monkeypatch.setattr(slides, 'rebuild', fail_rebuild)
    assert slides.ensure(renamed_source) == (slides.deck_path(renamed_source), False)
    client = app.test_client()
    deck_path = slides.deck_path(renamed_source).relative_to(root).as_posix()
    assert client.get('/api/deck/annotations', query_string={'path': deck_path}).json['elements'] == [{'id': 'handschrift'}]


def test_folder_rename_does_not_mark_stale_deck_current(folder_app):
    app, root = folder_app
    slides, _, _, _, _, _ = saved_slides(app, root, current=False)
    assert app.test_client().post('/api/folder/rename', json={'path': 'unterricht/alt', 'name': 'neu'}).status_code == 200
    source = root / 'unterricht/neu/unterordner/slide.qmd'
    assert not slides.is_current(source)
    assert 'veraltet' in slides.source_stamp(slides.deck_path(source)).read_text()


def test_folder_rename_rejects_artifact_collision_without_moving(folder_app):
    app, root = folder_app
    saved_slides(app, root)
    target = root / 'build/artefakte/unterricht/neu'
    target.mkdir(parents=True)
    (target / 'erhalten').write_text('Bestehende Daten')
    response = app.test_client().post('/api/folder/rename', json={'path': 'unterricht/alt', 'name': 'neu'})
    assert response.status_code == 409
    assert (root / 'unterricht/alt/blatt.qmd').is_file()
    assert not (root / 'unterricht/neu').exists()
    assert (target / 'erhalten').read_text() == 'Bestehende Daten'


@pytest.mark.parametrize('failure', ['move', 'stamp'])
def test_folder_rename_rolls_back_source_and_slides_on_failure(folder_app, monkeypatch, failure):
    from pathlib import Path
    import material_ui.folders as folders_module

    app, root = folder_app
    _, source, deck, annotations, stamp, _ = saved_slides(app, root)
    snapshots = {path: path.read_bytes() for path in (source, deck, annotations, stamp)}
    if failure == 'move':
        original = Path.rename

        def fail_move(path, target):
            if path == root / 'build/artefakte/unterricht/alt':
                raise OSError('Verschieben fehlgeschlagen')
            return original(path, target)

        monkeypatch.setattr(Path, 'rename', fail_move)
    else:
        def fail_stamp(*args, **kwargs):
            raise OSError('Stempel fehlgeschlagen')

        monkeypatch.setattr(folders_module, 'atomic_write_text', fail_stamp)
    service = app.extensions['material_runtime'].services.folders
    with pytest.raises(OSError):
        service.rename('unterricht/alt', 'neu')
    for path, contents in snapshots.items():
        assert path.read_bytes() == contents
    assert not (root / 'unterricht/neu').exists()
    assert not (root / 'build/artefakte/unterricht/neu').exists()


def test_folder_rename_restores_already_updated_stamps_on_later_failure(folder_app, monkeypatch):
    import material_ui.folders as folders_module

    app, root = folder_app
    slides, source, deck, _, stamp, _ = saved_slides(app, root)
    second_source = source.with_name('zweite.qmd')
    second_source.write_bytes(source.read_bytes())
    second_deck = slides.deck_path(second_source)
    second_deck.write_bytes(deck.read_bytes())
    second_stamp = slides.source_stamp(second_deck)
    second_stamp.write_bytes(stamp.read_bytes())
    snapshots = {path: path.read_bytes() for path in (stamp, second_stamp)}
    original = folders_module.atomic_write_text
    updates = []

    def fail_second_stamp(path, text):
        updates.append(path)
        if len(updates) == 2:
            raise OSError('Zweiter Stempel fehlgeschlagen')
        original(path, text)

    monkeypatch.setattr(folders_module, 'atomic_write_text', fail_second_stamp)
    with pytest.raises(OSError):
        app.extensions['material_runtime'].services.folders.rename('unterricht/alt', 'neu')
    assert len(updates) == 2
    for path, content in snapshots.items():
        assert path.read_bytes() == content
    assert slides.is_current(source)
    assert slides.is_current(second_source)
    assert not (root / 'unterricht/neu').exists()


def test_folder_rename_rejects_symlinked_artifact_tree(folder_app):
    app, root = folder_app
    original = root / 'saved-artifacts'
    original.mkdir()
    (original / 'notiz').write_text('Erhalten')
    alias = root / 'build/artefakte/unterricht/alt'
    alias.parent.mkdir(parents=True)
    alias.symlink_to(original, target_is_directory=True)
    response = app.test_client().post('/api/folder/rename', json={'path': 'unterricht/alt', 'name': 'neu'})
    assert response.status_code == 400
    assert (root / 'unterricht/alt').is_dir()
    assert (original / 'notiz').read_text() == 'Erhalten'
    assert alias.is_symlink()


def test_folder_reorder_renumbers_siblings_and_preserves_assets(folder_app):
    app, root = folder_app
    for name in ['01_eins', '02_zwei', '03_drei']:
        folder = root / 'unterricht' / name
        folder.mkdir()
        (folder / 'blatt.qmd').write_text(name)
        artifact = root / 'build/artefakte/unterricht' / name
        artifact.mkdir(parents=True)
        (artifact / 'asset.txt').write_text(name)
    response = app.test_client().post('/api/folder/reorder', json={'path': 'unterricht/03_drei', 'position': 1})
    assert response.status_code == 200
    for old, new in [('01_eins', '02_eins'), ('02_zwei', '03_zwei'), ('03_drei', '01_drei')]:
        assert response.json['paths'][f'unterricht/{old}'] == f'unterricht/{new}'
        assert (root / 'unterricht' / new / 'blatt.qmd').read_text() == old
        assert (root / 'build/artefakte/unterricht' / new / 'asset.txt').read_text() == old
    assert (root / 'unterricht/alt').is_dir()


@pytest.mark.parametrize('position', [0, -1, 3, '1', True, 1.5, None])
def test_folder_reorder_rejects_invalid_positions(folder_app, position):
    app, root = folder_app
    (root / 'unterricht/01_eins').mkdir()
    response = app.test_client().post('/api/folder/reorder', json={'path': 'unterricht/01_eins', 'position': position})
    assert response.status_code == 400
    assert (root / 'unterricht/01_eins').is_dir()


def test_folder_reorder_rolls_back_on_artifact_collision(folder_app):
    app, root = folder_app
    for name in ['01_eins', '02_zwei']:
        (root / 'unterricht' / name).mkdir()
    (root / 'build/artefakte/unterricht/01_zwei').mkdir(parents=True)
    response = app.test_client().post('/api/folder/reorder', json={'path': 'unterricht/02_zwei', 'position': 1})
    assert response.status_code == 409
    assert sorted(p.name for p in (root / 'unterricht').iterdir()) == ['01_eins', '02_zwei', 'alt']


def test_browser_folder_drag_reorder(folder_app):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    app, root = folder_app
    for name in ['01_eins', '02_zwei', '03_drei']:
        folder = root / 'unterricht' / name
        folder.mkdir()
        (folder / 'blatt.qmd').write_text(f'---\ntitle: {name}\n---\n\n{name}\n')
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1500, 'height': 1000})
        page.add_init_script("localStorage.setItem('material-ui:auto-render', 'false'); if (!localStorage.getItem('material-ui:active-view')) localStorage.setItem('material-ui:active-view', 'folder');")
        page.goto(f'{url}?path=unterricht/03_drei/blatt.qmd', wait_until='networkidle')
        source = page.locator('summary[data-folder="unterricht/03_drei"]')
        target = page.locator('summary[data-folder="unterricht/01_eins"]')
        source.drag_to(target)
        page.locator('#fileActionName').wait_for(state='visible')
        assert page.locator('#fileActionName').input_value() == '1'
        page.locator('#fileActionConfirm').click()
        page.locator('[data-tab="unterricht/01_drei/blatt.qmd"][aria-current="true"]').wait_for()
        assert (root / 'unterricht/02_eins/blatt.qmd').is_file()
        assert (root / 'unterricht/03_zwei/blatt.qmd').is_file()
        browser.close()


@pytest.mark.parametrize('external', [False, True])
@pytest.mark.parametrize('drag_link', [False, True])
def test_folder_reorder_rejects_symlinks_without_moving_targets(folder_app, tmp_path, external, drag_link):
    app, root = folder_app
    parent = root / 'unterricht'
    (parent / '01_eins').mkdir()
    (parent / '01_eins/blatt.qmd').write_text('Eins')
    target = tmp_path.parent / f'{tmp_path.name}-external' if external else parent / 'alt'
    target.mkdir(exist_ok=True)
    (target / 'erhalten').write_text('Original')
    link = parent / '02_link'
    link.symlink_to(target, target_is_directory=True)
    artifact = root / 'build/artefakte/unterricht/01_eins'
    artifact.mkdir(parents=True)
    (artifact / 'asset.txt').write_text('Artefakt')
    original_names = sorted(p.name for p in parent.iterdir())
    response = app.test_client().post('/api/folder/reorder', json={
        'path': 'unterricht/02_link' if drag_link else 'unterricht/01_eins',
        'position': 1 if drag_link else 2,
    })
    assert response.status_code == 400
    assert sorted(p.name for p in parent.iterdir()) == original_names
    assert link.is_symlink() and link.resolve() == target.resolve()
    assert (target / 'erhalten').read_text() == 'Original'
    assert (parent / '01_eins/blatt.qmd').read_text() == 'Eins'
    assert (artifact / 'asset.txt').read_text() == 'Artefakt'
