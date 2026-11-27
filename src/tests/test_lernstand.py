from pathlib import Path
import copy
import json
import zipfile
import pymupdf

import pytest
from ruamel.yaml import YAML
from material_core import lernstand as ls
from material_ui.plugins.lernstand import export as publication


def stamp_pdf(root, source):
    from material_core.builds import BuildService
    service = BuildService(root, None)
    pdf = ls.pdf_path(source, root)
    stat = pdf.stat()
    stamp = service.render_stamp(source)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps({'pdf': pdf.relative_to(root).as_posix(), 'mtime_ns': stat.st_mtime_ns,
        'size': stat.st_size, 'signature': service.render_signature(source, source.read_text())}))


@pytest.fixture
def unit(tmp_path):
    folder = tmp_path / 'unterricht/mathematik/klasse-06/brueche/vergleichen'
    folder.mkdir(parents=True)
    for name in ('test', 'blatt', 'loesung'):
        (folder / (name + '.qmd')).write_text('---\ntitle: Test\n---\n')
        pdf = tmp_path / 'build/pdf' / folder.relative_to(tmp_path) / (name + '.pdf')
        pdf.parent.mkdir(parents=True, exist_ok=True)
        with pymupdf.open() as document:
            document.new_page().insert_text((72, 72), name)
            document.save(pdf)
        stamp_pdf(tmp_path, folder / (name + '.qmd'))
    data = {'schema': 1, 'id': 'mathe-06-brueche', 'version': '1',
            'kompetenzen': [{'id': 'vergleichen', 'titel': 'Brüche vergleichen', 'stufen': [{'id': 'basis', 'beschreibung': 'Gleiche Nenner'}]}],
            'materialien': [
                {'id': 'test', 'rolle': 'diagnose', 'quelle': 'test.qmd', 'online': True},
                {'id': 'blatt', 'rolle': 'foerdermaterial', 'quelle': 'blatt.qmd', 'loesung': 'loesung.qmd', 'kompetenz': 'vergleichen', 'stufe': 'basis', 'online': True, 'loesung_online': False}],
            'aufgaben': [{'id': 'a1', 'diagnose': 'test', 'kompetenz': 'vergleichen', 'empfehlung': ['blatt']}]}
    return tmp_path, folder, data


def save(folder, data):
    with (folder / 'einheit.yaml').open('w') as out:
        YAML().dump({'titel': 'Brüche', 'lernstand': data}, out)


def test_export_second_grade_explicit_release_and_portable_paths(unit):
    root, folder, data = unit
    save(folder, data)
    target = publication.export(folder, root, solutions=True)
    catalog = json.loads((target / 'katalog.json').read_text())
    assert catalog['aufgaben'][0]['empfehlung'] == ['blatt']
    assert all('loesung' not in item for item in catalog['materialien'])
    assert str(root) not in (target / 'katalog.json').read_text()
    with zipfile.ZipFile(target / 'paket.zip') as archive:
        assert 'index.html' in archive.namelist()
        assert not any('loesung' in name for name in archive.namelist())
    data['materialien'][1]['loesung_online'] = True
    save(folder, data)
    assert 'loesung' in json.loads((publication.export(folder, root, solutions=True) / 'katalog.json').read_text())['materialien'][1]


@pytest.mark.parametrize('change', ['duplicate', 'traversal', 'recommendation', 'stage', 'path', 'bool'])
def test_invalid_metadata(unit, change):
    root, folder, data = unit
    if change == 'duplicate': data['materialien'][1]['id'] = 'test'
    if change == 'traversal': data['id'] = '../private'
    if change == 'recommendation': data['aufgaben'][0]['empfehlung'] = ['missing']
    if change == 'stage': data['materialien'][1]['stufe'] = 'unknown'
    if change == 'path': data['materialien'][1]['quelle'] = '../../../../../../etc/passwd.qmd'
    if change == 'bool': data['materialien'][1]['online'] = 'yes'
    with pytest.raises(ls.LernstandError): ls.validate(data, folder, root)


def test_failed_build_preserves_existing_package(unit):
    root, folder, data = unit
    save(folder, data)
    target = publication.export(folder, root)
    before = (target / 'paket.zip').read_bytes()
    def fail(source): raise RuntimeError('render failed')
    with pytest.raises(RuntimeError): publication.export(folder, root, build=fail)
    assert (target / 'paket.zip').read_bytes() == before


def test_unpublished_references_removed_from_public_catalog(unit):
    root, folder, data = unit
    data['materialien'][1]['online'] = False
    save(folder, data)
    target = publication.export(folder, root)
    catalog = json.loads((target / 'katalog.json').read_text())
    assert catalog['aufgaben'][0]['empfehlung'] == []
    assert len(catalog['materialien']) == 1


def test_missing_material_is_reported(unit):
    root, folder, data = unit
    (folder / 'blatt.qmd').unlink()
    assert ls.audit(data, folder, root)['fehler']


def test_unit_ownership_rename_and_export_endpoint(unit, monkeypatch):
    from material_ui.app import create_app
    from material_ui.config import AppConfig
    from material_ui.units import UnitService
    root, folder, data = unit
    (folder / 'diagnose').mkdir()
    (folder / 'test.qmd').rename(folder / 'diagnose/test.qmd')
    pdf = root / 'build/pdf' / folder.relative_to(root)
    (pdf / 'diagnose').mkdir()
    (pdf / 'test.pdf').rename(pdf / 'diagnose/test.pdf')
    data['materialien'][0]['quelle'] = 'diagnose/test.qmd'
    unit_data = {'titel': 'Brüche vergleichen', 'thema': 'Brüche', 'kurzbeschreibung': '', 'datumsneutral': True, 'lernstand': data}
    with (folder / 'einheit.yaml').open('w') as out: YAML().dump(unit_data, out)
    app = create_app(config=AppConfig(root))
    app.testing = True
    runtime = app.extensions['material_runtime']
    service = UnitService(runtime.config, runtime.services.documents)
    try:
        overview = service.overview()
        assert not overview['errors']
        assert len(overview['units']) == 1
        assert 'diagnose/test.qmd' in overview['units'][0]['materials']
        service.rename_material(folder / 'blatt.qmd', folder / 'ab_neu.qmd')
        assert service.read(folder)['data']['lernstand']['materialien'][1]['quelle'] == 'ab_neu.qmd'
        (pdf / 'blatt.pdf').rename(pdf / 'ab_neu.pdf')
        for source in (folder / 'ab_neu.qmd', folder / 'diagnose/test.qmd'):
            stamp_pdf(root, source)
        monkeypatch.setattr(publication, 'ensure_pdf', lambda *args: None)
        response = app.test_client().post('/api/plugins/lernstand/export', json={'path': folder.relative_to(root).as_posix()})
        assert response.status_code == 200
        assert response.mimetype == 'application/zip'
    finally:
        runtime.close()


def test_lernstand_panel_and_download_in_browser(unit, monkeypatch):
    from material_ui.app import create_app
    from material_ui.config import AppConfig
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None: pytest.skip('Playwright fehlt')
    root, folder, data = unit
    with (folder / 'einheit.yaml').open('w') as out:
        YAML().dump({'titel': 'Brüche vergleichen', 'thema': 'Brüche', 'kurzbeschreibung': '', 'datumsneutral': True, 'lernstand': data}, out)
    app = create_app(config=AppConfig(root))
    monkeypatch.setattr(publication, 'ensure_pdf', lambda *args: None)
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='domcontentloaded')
            page.locator('#viewButton-units').click()
            card = page.locator('.unit-card')
            card.evaluate("card => { card.open = true; card.dispatchEvent(new Event('toggle')); }")
            panel = page.locator('.unit-lernstand')
            if panel.get_attribute('open') is None:
                panel.locator(':scope > summary').click()
            panel.get_by_role('button', name='Kompetenzen und Förderwege öffnen').click()
            assert panel.locator('caption').inner_text() == 'Förderwege nach Kompetenz und Stufe'
            assert panel.locator('tbody').inner_text().startswith('Brüche vergleichen')
            with page.expect_download(lambda download: download.suggested_filename == 'mathe-06-brueche.zip') as download:
                panel.get_by_role('button', name='Veröffentlichungspaket herunterladen').click()
            assert download.value.suggested_filename == 'mathe-06-brueche.zip'
            panel.get_by_role('button', name='Förderzuordnungen bearbeiten').click()
            panel.get_by_role('checkbox', name='Blatt veröffentlichen').last.uncheck()
            with page.expect_response(lambda response: response.url.endswith('/api/units') and response.request.method == 'POST') as saved:
                panel.get_by_role('button', name='Förderzuordnungen speichern').click()
            assert saved.value.status == 200
            assert YAML(typ='safe').load((folder / 'einheit.yaml').read_text())['lernstand']['materialien'][1]['online'] is False
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_initialize_is_opt_in_and_preserves_unit_metadata(unit, monkeypatch):
    import lernstand_tasks as tasks
    root, folder, _ = unit
    manifest = folder / 'einheit.yaml'
    manifest.write_text('titel: Brüche\nthema: Zahlen\nkurzbeschreibung: Erhalten\neinsatz: []\n')
    monkeypatch.setattr(tasks, 'ROOT', root)
    tasks.initialize.body(None, str(folder), 'mathe-06-brueche')
    unit_data, data = ls.load(folder, root)
    assert unit_data['kurzbeschreibung'] == 'Erhalten'
    assert not ls.audit(data, folder, root)['fehler']
    assert all(item['online'] is False for item in data['materialien'])
    with pytest.raises(ValueError): tasks.initialize.body(None, str(folder), 'mathe-06-brueche')


def test_upload_is_scoped_and_records_success_only(unit, monkeypatch):
    import lernstand_tasks as tasks
    root, folder, data = unit
    save(folder, data)
    monkeypatch.setattr(tasks, 'ROOT', root)
    calls = []
    from material_ui.plugins.lernstand import upload as deployment
    monkeypatch.setattr(deployment.subprocess, 'run', lambda command, **kwargs: calls.append(command))
    tasks.upload.body(None, str(folder), ziel='host:/srv/einheiten', trocken=True)
    assert calls == []
    tasks.upload.body(None, str(folder), ziel='host:/srv/einheiten')
    assert calls[0][-1] == 'host:/srv/einheiten/mathe-06-brueche/'
    assert '--delete-delay' in calls[0]
    assert (root / 'build/lernstand/mathe-06-brueche-upload.json').is_file()


def test_duplicate_unit_id_cannot_overwrite_export(unit):
    root, folder, data = unit
    save(folder, data)
    other = folder.parent / 'andere-einheit'
    other.mkdir()
    save(other, data)
    with pytest.raises(ls.LernstandError, match='bereits verwendet'):
        publication.export(folder, root)


def test_stale_pdf_is_rejected(unit):
    import os
    root, folder, data = unit
    save(folder, data)
    pdf = ls.pdf_path(folder / 'blatt.qmd', root)
    os.utime(pdf, (1, 1))
    with pytest.raises(ls.LernstandError, match='veraltet'):
        publication.export(folder, root)


def test_concurrent_manifest_edit_keeps_previous_export(unit):
    root, folder, data = unit
    save(folder, data)
    target = publication.export(folder, root)
    previous = (target / 'paket.zip').read_bytes()
    def edit_manifest(source):
        changed = copy.deepcopy(data)
        changed['version'] = '2'
        save(folder, changed)
    with pytest.raises(ls.LernstandError, match='während des Exports geändert'):
        publication.export(folder, root, build=edit_manifest)
    assert (target / 'paket.zip').read_bytes() == previous


def test_legacy_export_accepts_manifest_in_another_grade(unit):
    import foerder_online
    root, folder, data = unit
    data['materialien'][1]['online_pfad'] = 'brueche/Basis/arbeitsblatt.pdf'
    data['materialien'][1]['loesung_online'] = True
    save(folder, data)
    target = root / 'build/foerder-online'
    plan = foerder_online.plane(root, target, loesungen=True)
    assert {entry.ziel.relative_to(target).as_posix() for entry in plan.eintraege} == {
        'brueche/Basis/arbeitsblatt.pdf', 'brueche/Basis/Loesungen/loesung.pdf'}
    assert not plan.uebersprungen


def test_shared_material_reference_follows_move_in_other_unit(unit):
    from material_ui.app import create_app
    from material_ui.config import AppConfig
    from material_ui.units import UnitService
    root, folder, data = unit
    shared = folder.parent / 'gemeinsam'
    shared.mkdir()
    (folder / 'blatt.qmd').rename(shared / 'blatt.qmd')
    data['materialien'][1]['quelle'] = '../gemeinsam/blatt.qmd'
    with (folder / 'einheit.yaml').open('w') as out:
        YAML().dump({'titel': 'Brüche', 'thema': 'Zahlen', 'kurzbeschreibung': '', 'lernstand': data}, out)
    app = create_app(config=AppConfig(root))
    runtime = app.extensions['material_runtime']
    try:
        service = UnitService(runtime.config, runtime.services.documents)
        service.rename_material(shared / 'blatt.qmd', shared / 'ab_neu.qmd')
        assert service.read(folder)['data']['lernstand']['materialien'][1]['quelle'] == '../gemeinsam/ab_neu.qmd'
    finally:
        runtime.close()


def test_disabled_publication_plugin_keeps_unit_and_cli_usable(unit, monkeypatch):
    import lernstand_tasks as tasks
    from material_ui.app import create_app
    from material_ui.config import AppConfig
    from material_ui.plugins.storage import PluginEnabledStore
    root, folder, data = unit
    with (folder / 'einheit.yaml').open('w') as out:
        YAML().dump({'titel': 'Brüche', 'thema': 'Zahlen', 'kurzbeschreibung': '', 'datumsneutral': True, 'lernstand': data}, out)
    PluginEnabledStore(root / 'daten/plugins.json').set_enabled('lernstand', False)
    app = create_app(config=AppConfig(root))
    app.testing = True
    try:
        client = app.test_client()
        plugin = next(p for p in client.get('/api/plugins').json['plugins'] if p['id'] == 'lernstand')
        assert plugin['status'] == 'disabled' and plugin['jsUrl'] is None
        assert client.get('/api/units').json['units'][0]['data']['lernstand'] == data
        payload = {'path': folder.relative_to(root).as_posix()}
        for endpoint in ('/api/plugins/lernstand/export', '/api/units/lernstand/export'):
            assert client.post(endpoint, json=payload).status_code == 404
        monkeypatch.setattr(tasks, 'ROOT', root)
        assert (tasks.export_cmd.body(None, str(folder)) / 'paket.zip').is_file()
    finally:
        app.extensions['material_runtime'].close()


def test_disabled_export_controls_preserve_diagnosis_editor_in_browser(unit):
    from material_ui.app import create_app
    from material_ui.config import AppConfig
    from material_ui.plugins.storage import PluginEnabledStore
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None: pytest.skip('Playwright fehlt')
    root, folder, data = unit
    with (folder / 'einheit.yaml').open('w') as out:
        YAML().dump({'titel': 'Brüche', 'thema': 'Zahlen', 'kurzbeschreibung': '', 'datumsneutral': True, 'lernstand': data}, out)
    PluginEnabledStore(root / 'daten/plugins.json').set_enabled('lernstand', False)
    app = create_app(config=AppConfig(root))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='domcontentloaded')
            page.locator('#viewButton-units').click()
            card = page.locator('.unit-card')
            card.evaluate("card => { card.open = true; card.dispatchEvent(new Event('toggle')); }")
            page.get_by_role('button', name='Kompetenzen und Förderwege öffnen').click()
            assert page.locator('.unit-lernstand tbody tr').count() == 1
            assert page.get_by_role('button', name='Veröffentlichungspaket herunterladen').count() == 0
            page.get_by_role('button', name='Förderzuordnungen bearbeiten').click()
            assert page.get_by_role('button', name='Förderzuordnungen speichern').is_visible()
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_upload_pins_package_against_parallel_export(unit, monkeypatch):
    from material_ui.plugins.lernstand import upload as deployment
    root, folder, data = unit
    data['materialien'][1]['loesung_online'] = True
    save(folder, data)
    seen = []
    def transfer(command, **kwargs):
        pinned = Path(command[-2].rstrip('/'))
        before = (pinned / 'paket.zip').read_bytes()
        publication.export(folder, root, solutions=True)
        assert (pinned / 'paket.zip').read_bytes() == before
        assert all('loesung' not in item for item in json.loads((pinned / 'katalog.json').read_text())['materialien'])
        seen.append(pinned)
    monkeypatch.setattr(deployment.subprocess, 'run', transfer)
    deployment.upload(folder, root, destination='host:/unused', solutions=False)
    assert seen and not seen[0].exists()
    assert json.loads((root / 'build/lernstand' / (data['id'] + '-upload.json')).read_text())['paket_sha256']


@pytest.mark.parametrize('parent', [False, True])
def test_rename_complete_learning_unit(unit, parent):
    from material_ui.app import create_app
    from material_ui.config import AppConfig
    root, folder, data = unit
    with (folder / 'einheit.yaml').open('w') as out:
        YAML().dump({'titel': 'Brüche', 'thema': 'Zahlen', 'kurzbeschreibung': '', 'lernstand': data}, out)
    app = create_app(config=AppConfig(root)); app.testing = True
    try:
        source = folder.parent if parent else folder
        response = app.test_client().post('/api/folder/rename', json={'path':source.relative_to(root).as_posix(), 'name':'umbenannt'})
        assert response.status_code == 200, response.json
        moved = source.with_name('umbenannt') / folder.relative_to(source)
        assert ls.load(moved, root)[1] == data
        assert not ls.audit(data, moved, root)['fehler']
    finally: app.extensions['material_runtime'].close()


def test_no_stamp_rejects_old_header_pdf(unit):
    from material_core.builds import BuildService
    root, folder, data = unit
    save(folder, data)
    source = folder / 'blatt.qmd'
    source.write_text('---\nformat:\n  pdf:\n    include-in-header: header.tex\n---\nText\n')
    header = folder / 'header.tex'; header.write_text('% before')
    ls.pdf_path(source, root).write_bytes(b'%PDF old header')
    stamp_pdf(root, source)
    BuildService(root, None).render_stamp(source).unlink()
    header.write_text('% after')
    with pytest.raises(ls.LernstandError, match='Abhängigkeiten'):
        publication.export(folder, root)


def test_legacy_targets_are_unique_and_explicit_collisions_rejected(unit):
    import foerder_online
    root, folder, data = unit
    save(folder, data)
    other = folder.parent / 'zweite'; other.mkdir()
    other_data = copy.deepcopy(data); other_data['id'] = 'zweite'
    for item in other_data['materialien']:
        for key in ('quelle', 'loesung'):
            if key in item: (other / item[key]).write_text((folder / item[key]).read_text())
    save(other, other_data)
    plan = foerder_online.plane(root, root / 'build/legacy', alles=True)
    assert len({e.ziel for e in plan.eintraege}) == 2
    for d, f in ((data, folder), (other_data, other)):
        d['materialien'][1]['online_pfad'] = 'alt/blatt.pdf'; save(f, d)
    with pytest.raises(ValueError, match='Kollision'):
        foerder_online.plane(root, root / 'build/legacy')


def test_bad_reference_type_is_isolated_in_unit_overview(unit):
    from material_ui.app import create_app
    from material_ui.config import AppConfig
    root, folder, data = unit
    bad = folder.parent / 'kaputt'; bad.mkdir()
    invalid = copy.deepcopy(data); invalid['materialien'][1]['kompetenz'] = []
    for f, d in ((folder, data), (bad, invalid)):
        with (f / 'einheit.yaml').open('w') as out:
            YAML().dump({'titel':'Brüche', 'thema':'Zahlen', 'kurzbeschreibung':'', 'lernstand':d}, out)
    app = create_app(config=AppConfig(root))
    try:
        response = app.test_client().get('/api/units')
        assert response.status_code == 200
        assert len(response.json['errors']) == 1
        assert any(u['path'] == folder.relative_to(root).as_posix() for u in response.json['units'])
    finally: app.extensions['material_runtime'].close()


def test_initialize_failure_rolls_back_and_can_retry(unit, monkeypatch):
    import lernstand_tasks as tasks
    from material_core import filesystem
    root, folder, _ = unit
    manifest = folder / 'einheit.yaml'
    manifest.write_text('titel: Brüche\nthema: Zahlen\nkurzbeschreibung: Test\n')
    monkeypatch.setattr(tasks, 'ROOT', root)
    original = filesystem.atomic_write_text
    def fail(path, *args, **kwargs):
        if path == manifest: raise OSError('write failed')
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(filesystem, 'atomic_write_text', fail)
        with pytest.raises(OSError): tasks.initialize.body(None, str(folder), 'neu')
    assert not (folder / 'diagnose/ab_lernstand.qmd').exists()
    tasks.initialize.body(None, str(folder), 'neu')
    assert ls.load(folder, root)[1]['id'] == 'neu'
