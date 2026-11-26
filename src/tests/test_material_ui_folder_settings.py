import pytest

from material_ui.app import create_app
from material_ui.config import AppConfig
from material_ui.folder_notes import read_notes, save_notes
from material_ui.storage import RevisionConflict


def test_notes_consolidate_without_losing_content(tmp_path):
    (tmp_path / 'hinweise.md').write_text('Allgemein', encoding='utf-8')
    (tmp_path / 'selbstdiagnose-hinweise.md').write_text('Diagnose', encoding='utf-8')
    (tmp_path / 'ab.md').write_text('Material', encoding='utf-8')
    notes = read_notes(tmp_path)
    save_notes(tmp_path, notes['text'], notes['revision'])
    assert (tmp_path / 'hinweise.md').read_text() == 'Allgemein\n\n## selbstdiagnose-hinweise\n\nDiagnose'
    assert not (tmp_path / 'selbstdiagnose-hinweise.md').exists()
    assert (tmp_path / 'ab.md').read_text() == 'Material'
    with pytest.raises(RevisionConflict):
        save_notes(tmp_path, 'stale', notes['revision'])


def test_folder_settings_create_unit_and_hide_support_files(tmp_path, request):
    folder = tmp_path / 'unterricht/mathematik/klasse-05/test'
    folder.mkdir(parents=True)
    (folder / 'selbstdiagnose-hinweise.md').write_text('Diagnose', encoding='utf-8')
    (folder / 'ab.md').write_text('Aufgaben', encoding='utf-8')
    app = create_app(config=AppConfig(tmp_path))
    request.addfinalizer(app.extensions["material_runtime"].close)
    app.testing = True
    client = app.test_client()
    path = folder.relative_to(tmp_path).as_posix()
    settings = client.get('/api/folder/settings', query_string={'path': path}).json
    unit = settings['unit']['data']
    unit['kurzbeschreibung'] = 'Beschreibung'
    response = client.post('/api/folder/settings', json={
        'path': path, 'unit': unit, 'unitRevision': settings['unit']['revision'],
        'notes': settings['notes']['text'], 'notesRevision': settings['notes']['revision'],
    })
    assert response.status_code == 200, response.json
    assert (folder / 'einheit.yaml').exists()
    listing = client.get('/api/folder', query_string={'path': path}).json
    assert [entry['name'] for entry in listing['entries']] == ['ab.md']
    assert 'Diagnose' in listing['notes']['text']
    assert client.post('/api/folder/settings', json={
        'path': path, 'unit': unit, 'unitRevision': settings['unit']['revision'],
        'notes': 'veraltet', 'notesRevision': settings['notes']['revision'],
    }).status_code == 409

