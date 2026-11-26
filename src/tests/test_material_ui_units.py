from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from material_ui.config import AppConfig
from material_ui.errors import InvalidInput
from material_ui.storage import RevisionConflict
from material_ui.units import UnitService, FILENAME


def open_unit_menu(page, selector):
    menu = page.locator(selector)
    if menu.get_attribute('open') is None:
        menu.locator(':scope > summary').click()


def expand_unit(card):
    if card.get_attribute('open') is None:
        card.locator(':scope > summary').click()


@pytest.fixture
def units(tmp_path):
    folder = tmp_path / 'unterricht/mathematik/klasse-05/arithmetik/multiplikation'
    folder.mkdir(parents=True)
    (folder / 'ab_bibi.qmd').write_text('---\ntitle: Bibi & Tina\n---\n', encoding='utf-8')
    docs = SimpleNamespace(repository=SimpleNamespace(lock=threading.RLock()),
                           qmd_sources=lambda: [folder / 'ab_bibi.qmd'])
    return UnitService(AppConfig(tmp_path), docs), folder


def test_overview_excludes_class_planning_but_keeps_child_units(units):
    service, folder = units
    class_folder = folder.parent.parent
    planning = class_folder / 'reihenplanung.qmd'
    planning.write_text('---\ntitle: Reihenplanung\n---\n', encoding='utf-8')
    service.documents.qmd_sources = lambda: [planning, folder / 'ab_bibi.qmd']
    summary = service.read(class_folder)
    service.save(summary['path'], summary['data'], summary['revision'])

    overview = service.overview()
    assert not overview['errors']
    assert [unit['path'] for unit in overview['units']] == [
        folder.relative_to(service.config.root).as_posix()]
    assert (class_folder / FILENAME).is_file()
    assert planning.is_file()


def test_repeated_use_survives_roundtrip_and_conflict(units):
    service, folder = units
    original = service.overview()['units'][0]
    data = {'titel': 'Bibi & Tina', 'thema': 'Arithmetik / Multiplikation',
            'kurzbeschreibung': 'Multiplikation mit dem Malkreuz.',
            'einsatz': [{'datum': '2026-11-06', 'material': 'ab_bibi.qmd', 'lerngruppe': '5a'},
                        {'datum': '2027-11-05', 'material': 'ab_bibi.qmd'}]}
    saved = service.save(original['path'], data, original['revision'])
    assert saved['data']['einsatz'] == data['einsatz']
    assert (folder / FILENAME).exists()
    assert service.overview()['units'][0]['data'] == data
    with pytest.raises(RevisionConflict):
        service.save(original['path'], data, original['revision'])


@pytest.mark.parametrize('use', [{'datum': '2026-02-30'}, {'datum': '06.11.2026'},
                                {'datum': '2026-11-06', 'material': '../missing.qmd'}])
def test_invalid_uses_are_not_written(units, use):
    service, folder = units
    unit = service.overview()['units'][0]
    unit['data']['einsatz'] = [use]
    with pytest.raises(InvalidInput):
        service.save(unit['path'], unit['data'], unit['revision'])
    assert not (folder / FILENAME).exists()


def test_invalid_summary_does_not_hide_other_units(units):
    service, folder = units
    (folder / FILENAME).write_text('titel: [broken', encoding='utf-8')
    overview = service.overview()
    assert not overview['units']
    assert FILENAME in overview['errors'][0]


def test_rejects_summary_symlink_outside_project(units, tmp_path):
    service, folder = units
    outside = tmp_path.parent / (tmp_path.name + '-outside.yaml')
    outside.write_text('private', encoding='utf-8')
    try:
        (folder / FILENAME).symlink_to(outside)
        assert service.overview()['errors']
        with pytest.raises(InvalidInput):
            service.save(str(folder.relative_to(tmp_path)), {}, '')
        assert outside.read_text() == 'private'
    finally:
        outside.unlink()


def test_sidebar_edits_and_filters_uses(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    folder = tmp_path / 'unterricht/mathematik/klasse-05/multiplikation'
    write_qmd(folder / 'ab_bibi.qmd', '---\ntitle: Bibi & Tina\n---\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.locator('#viewButton-units').click()
            page.locator('[data-show-undated]').check()
            expand_unit(page.locator('.unit-card'))
            page.locator('[data-edit]').click()
            page.locator('input[name=titel]').fill('Bibi & Tina')
            for day in ['2027-11-05', '2026-11-06']:
                page.locator('.units-view [data-add]').click()
                row = page.locator('[data-uses] fieldset').last
                row.locator('input[name=datum]').fill(day)
                row.locator('select[name=material]').select_option('ab_bibi.qmd')
            page.locator('button[type=submit]').filter(has_text='Speichern').click()
            page.wait_for_function("document.querySelector('.unit-card > summary')?.textContent.startsWith('Bibi & Tina') && !document.querySelector('.unit-card > summary').textContent.includes('noch ohne')")
            expand_unit(page.locator('.unit-card'))
            assert page.locator('.unit-card time').all_text_contents() == ['06.11.2026', '05.11.2027']
            open_unit_menu(page, '.unit-filters')
            page.locator('[data-year]').select_option('2027/2028')
            expand_unit(page.locator('.unit-card'))
            assert page.locator('.unit-card time').all_text_contents() == ['05.11']
            page.reload(wait_until='networkidle')
            page.wait_for_selector('.unit-card')
            assert page.locator('#viewButton-units').get_attribute('aria-pressed') == 'true'
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_missing_material_keeps_history_readable_and_editable(units):
    service, folder = units
    unit = service.overview()['units'][0]
    unit['data']['einsatz'] = [{'datum': '2026-11-06', 'material': 'ab_bibi.qmd'}]
    saved = service.save(unit['path'], unit['data'], unit['revision'])
    (folder / 'ab_bibi.qmd').unlink()
    overview = service.overview()
    assert not overview['errors']
    assert overview['units'][0]['missingMaterials'] == ['ab_bibi.qmd']
    saved['data']['kurzbeschreibung'] = 'Auch ohne Quelldatei bearbeitbar.'
    assert service.save(unit['path'], saved['data'], saved['revision'])['data']['einsatz'] == unit['data']['einsatz']


def test_parent_includes_nested_materials_even_with_child_summary(units):
    service, folder = units
    child = service.overview()['units'][0]
    service.save(child['path'], child['data'], child['revision'])
    parent = service.read(folder.parent)
    service.save(parent['path'], parent['data'], parent['revision'])
    overview = {unit['path']: unit for unit in service.overview()['units']}
    assert overview[parent['path']]['materials'] == ['multiplikation/ab_bibi.qmd']
    assert overview[child['path']]['materials'] == ['ab_bibi.qmd']


def test_rename_updates_child_and_parent_references(units):
    service, folder = units
    for current in (folder, folder.parent):
        unit = service.read(current)
        unit['data']['einsatz'] = [{'datum': '2026-11-06', 'material': (folder / 'ab_bibi.qmd').relative_to(current).as_posix()}]
        service.save(unit['path'], unit['data'], unit['revision'])
    service.rename_material(folder / 'ab_bibi.qmd', folder / 'ab_neu.qmd')
    assert service.read(folder)['data']['einsatz'][0]['material'] == 'ab_neu.qmd'
    assert service.read(folder.parent)['data']['einsatz'][0]['material'] == 'multiplikation/ab_neu.qmd'
    assert service.read(folder)['missingMaterials'] == []


def test_failed_rename_restores_material_and_summaries(units, monkeypatch):
    import material_ui.units as module
    service, folder = units
    for current in (folder, folder.parent):
        unit = service.read(current)
        unit['data']['einsatz'] = [{'datum': '2026-11-06', 'material': (folder / 'ab_bibi.qmd').relative_to(current).as_posix()}]
        service.save(unit['path'], unit['data'], unit['revision'])
    original = module.atomic_write_text
    calls = 0
    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('simulated write failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'atomic_write_text', fail_second)
    with pytest.raises(OSError):
        service.rename_material(folder / 'ab_bibi.qmd', folder / 'ab_neu.qmd')
    assert (folder / 'ab_bibi.qmd').is_file()
    assert not (folder / 'ab_neu.qmd').exists()
    assert service.read(folder)['data']['einsatz'][0]['material'] == 'ab_bibi.qmd'
    assert service.read(folder.parent)['data']['einsatz'][0]['material'] == 'multiplikation/ab_bibi.qmd'


def test_drafts_survive_filters_refresh_other_save_and_reload(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    for name in ('a', 'b'):
        write_qmd(tmp_path / f'unterricht/mathematik/klasse-05/arithmetik/{name}/ab.qmd', '---\ntitle: Test\n---\nText\n')
    write_qmd(tmp_path / 'unterricht/mathematik/klasse-10/test/ab.qmd', '---\ntitle: Test\n---\nText\n')
    write_qmd(tmp_path / 'unterricht/deutsch/klasse-05/lesen/ab.qmd', '---\ntitle: Lesen\n---\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.locator('#viewButton-units').click()
            page.locator('[data-show-undated]').check()
            page.locator('[data-class="klasse-05"]').click()
            a = page.locator('[data-unit-path="unterricht/mathematik/klasse-05/arithmetik/a"]')
            b = page.locator('[data-unit-path="unterricht/mathematik/klasse-05/arithmetik/b"]')
            for card, title in ((a, 'Entwurf A'), (b, 'Entwurf B')):
                expand_unit(card)
                card.locator('[data-edit]').click()
                card.locator('[name=titel]').fill(title)
            # Both complete and incomplete uses must survive reconstruction.
            b.locator('[data-add]').click()
            b.locator('[name=notiz]').fill('Noch ohne Datum')
            page.locator('[data-class="klasse-10"]').click()
            page.locator('[data-class="klasse-05"]').click()
            assert b.locator('[name=titel]').input_value() == 'Entwurf B'
            assert b.locator('[name=notiz]').input_value() == 'Noch ohne Datum'
            open_unit_menu(page, '.unit-filters')
            page.locator('[data-year]').select_option('')
            page.locator('[data-subject-filter]').select_option('deutsch')
            assert b.count() == 0
            page.locator('[data-subject-filter]').select_option('mathematik')
            assert b.locator('[name=notiz]').input_value() == 'Noch ohne Datum'
            open_unit_menu(page, '.unit-filters')
            page.locator('.unit-filters > summary').click()
            assert a.locator('[name=titel]').input_value() == 'Entwurf A'
            expand_unit(a)
            a.locator('[type=submit]').click()
            page.wait_for_function("[...document.querySelectorAll('.unit-card > summary')].some(s => s.textContent.startsWith('Entwurf A'))")
            assert b.locator('[name=titel]').input_value() == 'Entwurf B'
            assert not (tmp_path / 'unterricht/mathematik/klasse-05/arithmetik/b/einheit.yaml').exists()
            with page.expect_response(lambda r: r.url.endswith('/api/units')):
                open_unit_menu(page, '[data-options-menu]')
                page.locator('[data-refresh]').click()
            assert b.locator('[name=titel]').input_value() == 'Entwurf B'
            page.locator('#folderViewButton').click()
            page.locator('#viewButton-units').click()
            assert b.locator('[name=notiz]').input_value() == 'Noch ohne Datum'
            page.reload(wait_until='networkidle')
            assert page.locator('.units-view [name=titel]').input_value() == 'Entwurf B'
            expand_unit(b)
            page.once('dialog', lambda dialog: dialog.dismiss())
            page.locator('.units-view [data-cancel]').click()
            assert page.locator('.units-view form').count() == 1
            page.once('dialog', lambda dialog: dialog.accept())
            page.locator('.units-view [data-cancel]').click()
            assert page.locator('.units-view form').count() == 0
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_nested_topics_and_parent_material_selection(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    folder = tmp_path / 'unterricht/mathematik/klasse-05/arithmetik/multiplikation'
    write_qmd(folder / 'ab.qmd', '---\ntitle: Test\n---\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    service = UnitService(app.extensions['material_runtime'].config, app.extensions['material_runtime'].services.documents)
    for current in (folder, folder.parent):
        unit = service.read(current)
        unit['data']['thema'] = 'Arithmetik / Multiplikation'
        unit['data']['einsatz'] = [{'datum': '2026-11-06', 'material': 'entfernt.qmd'}]
        service.save(unit['path'], unit['data'], unit['revision'])
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.locator('#viewButton-units').click()
            page.locator('.unit-topic > summary').wait_for(state='visible')
            assert page.locator('.unit-topic > summary').all_text_contents() == ['Arithmetik / Multiplikation']
            parent = page.locator('.unit-card').filter(has=page.locator('summary')).first
            expand_unit(parent)
            assert parent.locator('.unit-history').count() == 0
            parent.locator('[data-edit]').click()
            assert 'multiplikation/ab.qmd' in parent.locator('select[name=material] option').all_text_contents()
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_file_routes_update_references_and_keep_deleted_history(tmp_path):
    from material_ui.app import create_app
    folder = tmp_path / 'unterricht/mathematik/klasse-05/multiplikation'
    folder.mkdir(parents=True)
    (folder / 'ab.qmd').write_text('---\ntitle: Test\n---\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        client = app.test_client()
        unit = client.get('/api/units').json['units'][0]
        unit['data']['einsatz'] = [{'datum': '2026-11-06', 'material': 'ab.qmd'}]
        assert client.post('/api/units', json=unit).status_code == 200
        renamed = client.post('/api/file/rename', json={'path': unit['path'] + '/ab.qmd', 'name': 'ab_neu.qmd'})
        assert renamed.status_code == 200
        updated = client.get('/api/units').json['units'][0]
        assert updated['data']['einsatz'][0]['material'] == 'ab_neu.qmd'
        assert client.delete('/api/file', query_string={'path': updated['path'] + '/ab_neu.qmd'}).status_code == 200
        overview = client.get('/api/units').json
        assert not overview['errors']
        assert overview['units'][0]['missingMaterials'] == ['ab_neu.qmd']
    finally:
        app.extensions['material_runtime'].close()


@pytest.fixture
def unit_app(tmp_path):
    from material_ui.app import create_app
    parent = tmp_path / 'unterricht/mathematik/klasse-05/arithmetik'
    for name in ('01_einstieg', '02_uebung'):
        child = parent / name
        child.mkdir(parents=True)
        (child / 'ab.qmd').write_text('---\ntitle: Test\n---\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    runtime = app.extensions['material_runtime']
    service = UnitService(runtime.config, runtime.services.documents)
    for folder in (parent, parent / '01_einstieg'):
        unit = service.read(folder)
        unit['data']['einsatz'] = [{'datum': '2026-11-06', 'material': (parent / '01_einstieg/ab.qmd').relative_to(folder).as_posix()}]
        service.save(unit['path'], unit['data'], unit['revision'])
    try:
        app.extensions['material_runtime'].plugins.contexts['kalender'].service.save_group_defaults([{'year': '2027/2028', 'grade': '05', 'group': '5b'}])
        yield app, service, parent
    finally:
        runtime.close()


@pytest.mark.parametrize('operation', ['rename', 'reorder'])
def test_folder_operations_update_parent_references(unit_app, operation):
    app, service, parent = unit_app
    source = parent / '01_einstieg'
    relative = source.relative_to(service.config.root).as_posix()
    if operation == 'rename':
        response = app.test_client().post('/api/folder/rename', json={'path': relative, 'name': '01_neu'})
        name = '01_neu'
    else:
        response = app.test_client().post('/api/folder/reorder', json={'path': relative, 'position': 2})
        name = '02_einstieg'
    assert response.status_code == 200, response.json
    assert service.read(parent)['data']['einsatz'][0]['material'] == f'{name}/ab.qmd'
    assert service.read(parent)['missingMaterials'] == []
    assert service.read(parent / name)['data']['einsatz'][0]['material'] == 'ab.qmd'
    assert service.read(parent / name)['missingMaterials'] == []


def test_folder_rename_rolls_back_if_reference_write_fails(unit_app, monkeypatch):
    import material_ui.units as module
    app, service, parent = unit_app
    source = parent / '01_einstieg'
    relative = source.relative_to(service.config.root).as_posix()
    artifact = service.config.root / 'build/artefakte' / relative
    artifact.mkdir(parents=True)
    (artifact / 'keep.txt').write_text('Original')
    before = (parent / FILENAME).read_text()
    def fail(*args, **kwargs):
        raise OSError('simulated failure')
    monkeypatch.setattr(module, 'atomic_write_text', fail)
    with pytest.raises(OSError):
        app.extensions['material_runtime'].services.folders.rename(relative, 'neu')
    assert (source / 'ab.qmd').exists()
    assert not (parent / 'neu').exists()
    assert (artifact / 'keep.txt').read_text() == 'Original'
    assert (parent / FILENAME).read_text() == before


@pytest.mark.parametrize('operation', ['file', 'folder'])
def test_invalid_ancestor_summary_returns_actionable_error(unit_app, operation):
    app, service, parent = unit_app
    summary = parent / FILENAME
    summary.write_text('titel: [kaputt')
    relative = (parent / '01_einstieg').relative_to(service.config.root).as_posix()
    if operation == 'file':
        response = app.test_client().post('/api/file/rename', json={'path': relative + '/ab.qmd', 'name': 'neu.qmd'})
    else:
        response = app.test_client().post('/api/folder/rename', json={'path': relative, 'name': 'neu'})
    assert response.status_code == 400
    assert str(summary.relative_to(service.config.root)) in response.json['error']['message']
    assert 'korrigieren' in response.json['error']['message']
    assert (parent / '01_einstieg/ab.qmd').exists()


def test_last_year_removed_resets_filter_in_browser(unit_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, parent = unit_app
    # Only the parent has a dated use.
    child = service.read(parent / '01_einstieg')
    child['data']['einsatz'] = []
    service.save(child['path'], child['data'], child['revision'])
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until='networkidle')
        page.locator('#viewButton-units').click()
        open_unit_menu(page, '.unit-filters')
        page.locator('[data-year]').select_option('2026/2027')
        expand_unit(page.locator('.unit-card'))
        page.locator('[data-edit]').click()
        page.locator('.units-view fieldset button').click()
        with page.expect_response(lambda r: r.url.endswith('/api/units') and r.request.method == 'GET'):
            page.locator('.units-view [type=submit]').click()
        page.wait_for_function("document.querySelectorAll('.unit-card').length === 0")
        assert page.locator('[data-year]').input_value() == ''
        browser.close()


@pytest.mark.parametrize('choice', ['independent', 'local', 'remote'])
def test_conflict_merge_is_saveable_and_keeps_both_versions_until_choice(unit_app, choice):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, parent = unit_app
    path = parent.relative_to(service.config.root).as_posix()
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until='networkidle')
        page.locator('#viewButton-units').click()
        card = page.locator(f'[data-unit-path="{path}"]')
        expand_unit(card)
        card.locator('[data-edit]').click()
        card.locator('[name=titel]').fill('Mein Titel')
        latest = service.read(parent)
        latest['data']['kurzbeschreibung'] = 'Externe Ergänzung'
        if choice != 'independent':
            latest['data']['titel'] = 'Externer Titel'
        service.save(path, latest['data'], latest['revision'])
        with page.expect_response(lambda r: r.url.endswith('/api/units') and r.request.method == 'POST') as conflict:
            card.locator('[type=submit]').click()
        assert conflict.value.status == 409
        # Reloading must keep the draft and offer conflict resolution.
        page.reload(wait_until='networkidle')
        assert card.locator('[name=titel]').input_value() == 'Mein Titel'
        card.locator('[data-merge]').click()
        if choice != 'independent':
            card.locator('[data-choice]').wait_for()
            comparison = card.locator('[data-conflicts]').inner_text()
            assert 'Mein Titel' in comparison and 'Externer Titel' in comparison
            # No file changes before a deliberate choice and subsequent save.
            assert service.read(parent)['data']['titel'] == 'Externer Titel'
            card.locator('[data-choice]').select_option(choice)
            card.locator('[data-apply-merge]').click()
        page.wait_for_function("document.querySelector('.units-view [name=kurzbeschreibung]')?.value === 'Externe Ergänzung'")
        assert card.locator('[name=titel]').input_value() == ('Externer Titel' if choice == 'remote' else 'Mein Titel')
        with page.expect_response(lambda r: r.url.endswith('/api/units') and r.request.method == 'POST') as saved:
            card.locator('[type=submit]').click()
        assert saved.value.status == 200
        data = service.read(parent)['data']
        assert data['titel'] == ('Externer Titel' if choice == 'remote' else 'Mein Titel')
        assert data['kurzbeschreibung'] == 'Externe Ergänzung'
        browser.close()


def test_reorder_failure_rolls_back_preceding_moves_and_references(unit_app, monkeypatch):
    import material_ui.units as module
    app, service, parent = unit_app
    original = module.atomic_write_text
    before = (parent / FILENAME).read_text()
    calls = 0
    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('failure during second reference update')
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'atomic_write_text', fail_second)
    relative = (parent / '01_einstieg').relative_to(service.config.root).as_posix()
    with pytest.raises(OSError):
        app.extensions['material_runtime'].services.folders.reorder(relative, 2)
    assert sorted(p.name for p in parent.iterdir() if p.is_dir()) == ['01_einstieg', '02_uebung']
    assert (parent / FILENAME).read_text() == before
    assert service.read(parent)['missingMaterials'] == []


@pytest.mark.parametrize('value', ['true', 1, None])
def test_dateless_flag_requires_boolean(units, value):
    service, folder = units
    unit = service.read(folder)
    unit['data']['datumsneutral'] = value
    with pytest.raises(InvalidInput, match='datumsneutral'):
        service.save(unit['path'], unit['data'], unit['revision'])


def test_class_timeline_is_flat_dated_and_supports_recurring_units(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    base = tmp_path / 'unterricht/mathematik/klasse-10'
    examples = [
        ('potenzen/01-einfuehrung', 'Einführung', 'Potenzen', ['2026-10-28'], False),
        ('potenzen/03-ganzzahlige', 'Ganzzahlige Exponenten', 'Potenzen', ['2026-11-03', '2026-11-04'], False),
        ('potenzen/02-rechengesetze', 'Rechengesetze', 'Potenzen', ['2026-11-10'], False),
        ('potenzen/unbenutzt', 'Ohne Termin', 'Potenzen', [], False),
        ('trigonometrie/unbenutzt', 'Altes Thema', 'Trigonometrie', [], False),
        ('kopfübungen', 'Kopfübungen', 'Kopfübungen', [], True),
        ('rituale', 'Rechenrituale', 'Warmups', [], True),
    ]
    for folder, *_ in examples:
        write_qmd(base / folder / 'ab.qmd', '---\ntitle: Test\n---\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    runtime = app.extensions['material_runtime']
    service = UnitService(runtime.config, runtime.services.documents)
    for folder, title, topic, dates, recurring in examples:
        unit = service.read(base / folder)
        unit['data'].update(titel=title, thema=topic, einsatz=[{'datum': value} for value in dates], datumsneutral=recurring)
        service.save(unit['path'], unit['data'], unit['revision'])
    # A later reuse must remain available through the school-year filter.
    unit = service.read(base / 'potenzen/01-einfuehrung')
    unit['data']['einsatz'].append({'datum': '2027-10-20'})
    service.save(unit['path'], unit['data'], unit['revision'])
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.locator('#viewButton-units').click()
            page.locator('[data-class="klasse-10"]').click()
            open_unit_menu(page, '.unit-filters')
            page.locator('[data-year]').select_option('2026/2027')
            assert page.locator('.unit-topic > summary').all_text_contents() == ['Potenzen']
            assert page.locator('.unit-topic .unit-topic').count() == 0
            rows = page.locator('.unit-topic .unit-card > summary').all_text_contents()
            assert rows == ['EinführungIn Bearbeitung28.10', 'Ganzzahlige ExponentenIn Bearbeitung03.11 · 04.11', 'RechengesetzeIn Bearbeitung10.11']
            assert page.locator('.unit-recurring .unit-card').count() == 2
            assert 'Ohne Termin' not in page.locator('[data-groups]').inner_text()
            assert 'Altes Thema' not in page.locator('[data-groups]').inner_text()
            open_unit_menu(page, '.unit-filters')
            page.locator('[data-year]').select_option('2027/2028')
            assert page.locator('.unit-topic .unit-card > summary').all_text_contents() == ['EinführungIn Bearbeitung20.10']
            assert page.locator('.unit-recurring .unit-card').count() == 2
            open_unit_menu(page, '.unit-filters')
            page.locator('[data-year]').select_option('')
            page.locator('[data-show-undated]').check()
            undated = page.locator(f'[data-unit-path="{(base / "potenzen/unbenutzt").relative_to(tmp_path).as_posix()}"]')
            expand_unit(undated)
            undated.locator('[data-edit]').click()
            undated.locator('[name=datumsneutral]').check()
            with page.expect_response(lambda r: r.url.endswith('/api/units') and r.request.method == 'GET'):
                undated.locator('[type=submit]').click()
            page.locator('[data-show-undated]').uncheck()
            assert page.locator('.unit-recurring .unit-card').count() == 3
            page.reload(wait_until='networkidle')
            assert not page.locator('[data-show-undated]').is_checked()
            assert page.locator('.unit-recurring .unit-card').count() == 3
            assert 'Altes Thema' not in page.locator('[data-groups]').inner_text()
            browser.close()
    finally:
        runtime.close()


def test_compact_unit_material_rows_pair_solutions_and_open_sources(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    folder = tmp_path / 'unterricht/mathematik/klasse-10/potenzen/02-rechengesetze'
    files = {
        'ab_mini_paare-karten.qmd': 'Paare gesucht · Kartenmaterial',
        'ab_mini_paare-kopfuebung.qmd': 'Kopfübung: Paare gesucht',
        'ab_mini_paare-kopfuebung-loesung.qmd': 'Lösungen: Kopfübung Paare gesucht',
        'ab_rechengesetze.qmd': 'Rechenregeln für Potenzen',
        'ab_rechengesetze-loesung.qmd': 'Lösungen: Rechenregeln für Potenzen',
        'ab_vertiefung.qmd': 'Rechengesetze bei Potenzen – Teil 2',
        'ab_vertiefung-loesung.qmd': 'Potenzen – Lösungen',
        'slide.qmd': 'Slides: Rechenregeln für Potenzen',
    }
    for name, title in files.items():
        write_qmd(folder / name, f'---\ntitle: "{title}"\n---\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    runtime = app.extensions['material_runtime']
    service = UnitService(runtime.config, runtime.services.documents)
    unit = service.read(folder)
    unit['data'].update(titel='Rechengesetze', thema='Potenzen',
                        kurzbeschreibung='Materialien: ' + '; '.join(files.values()),
                        einsatz=[{'datum': '2026-11-10'}])
    service.save(unit['path'], unit['data'], unit['revision'])
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.locator('#viewButton-units').click()
            card = page.locator('.unit-card')
            expand_unit(card)
            assert card.locator('.unit-material-row').count() == 5
            assert card.locator('.unit-material-link').count() == len(files)
            assert card.locator('[data-delete-material]').count() == len(files) - 3
            assert card.locator('.unit-solution-link').count() == 3
            assert 'Slide:' not in card.inner_text()
            assert 'Slides:' not in card.inner_text()
            assert card.locator('.unit-material-title').last.inner_text() == 'Rechenregeln für Potenzen'
            assert card.locator('.unit-material-row').evaluate_all('(rows) => rows.every(row => row.scrollWidth <= row.clientWidth)')
            assert card.locator('.unit-history').count() == 0
            assert 'Materialien:' not in card.inner_text()
            assert '2026/2027' not in card.inner_text()
            assert '.qmd' not in card.inner_text()
            assert card.locator('time').get_attribute('datetime') == '2026-11-10'
            assert card.locator('.unit-material-link').first.evaluate('(link) => getComputedStyle(link).backgroundColor') == 'rgba(0, 0, 0, 0)'
            assert card.locator('[data-edit]').evaluate('(button) => getComputedStyle(button).backgroundColor') == 'rgba(0, 0, 0, 0)'
            primary = card.get_by_role('link', name='Arbeitsblatt: Rechenregeln für Potenzen', exact=True)
            solution = primary.locator('..').locator('.unit-solution-link')
            assert solution.get_attribute('href').endswith('ab_rechengesetze-loesung.qmd')
            assert card.get_by_role('link', name='Präsentation: Rechenregeln für Potenzen').locator('use').get_attribute('href').endswith('#slides')
            with page.expect_response(lambda r: '/api/document?path=' in r.url and 'ab_rechengesetze-loesung.qmd' in r.url):
                solution.click()
            # The editing form still contains the complete original summary.
            card.locator('[data-edit]').click()
            assert card.locator('[name=kurzbeschreibung]').input_value().startswith('Materialien:')
            card.locator('[data-cancel]').click()
            assert card.locator('[data-delete-material="ab_rechengesetze-loesung.qmd"]').count() == 0
            page.locator('.document-settings > summary').click()
            delete_solution = page.locator('#deleteOpenDocument')
            delete_solution.click()
            page.locator('#fileActionCancel').click()
            assert (folder / 'ab_rechengesetze-loesung.qmd').exists()
            page.locator('.document-settings > summary').click()
            delete_solution.click()
            with page.expect_response(lambda r: r.url.endswith('/api/units') and r.request.method == 'GET'):
                page.locator('#fileActionConfirm').click()
            assert not (folder / 'ab_rechengesetze-loesung.qmd').exists()
            assert (folder / 'ab_rechengesetze.qmd').exists()
            from playwright.sync_api import expect
            expect(card.locator('[data-delete-material]')).to_have_count(len(files) - 3)
            browser.close()
    finally:
        runtime.close()


def test_material_navigation_survives_invalid_qmd_frontmatter(units):
    service, folder = units
    (folder / 'ab_bibi.qmd').write_text('---\ntitle: [broken\n---\nText\n')
    overview = service.overview()
    assert not overview['errors']
    entry = overview['units'][0]['materialEntries'][0]
    assert entry['path'] == 'ab_bibi.qmd'
    assert entry['kind'] == 'Arbeitsblatt'
    assert entry['title']


def test_create_unit_does_not_scan_material_index(units):
    service, _ = units
    def unexpected_scan():
        raise AssertionError('Creating an empty unit must not scan all materials')
    service.documents.qmd_sources = unexpected_scan
    created = service.create({'fach': 'mathematik', 'klasse': '10',
                              'thema': 'Potenzen', 'titel': 'Wurzeln'})
    assert created['materials'] == created['materialEntries'] == []
    assert '_worksheets' not in created
    assert (service.config.root / created['path'] / FILENAME).is_file()


def test_create_unit_in_empty_project_and_preserve_existing(tmp_path):
    from material_ui.app import create_app
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        client = app.test_client()
        payload = {'fach': 'mathematik', 'klasse': '10', 'thema': 'Potenzen', 'titel': 'Erste Übungen', 'datum': '2026-11-12'}
        response = client.post('/api/units/new', json=payload)
        assert response.status_code == 201, response.json
        path = response.json['path']
        assert path == 'unterricht/mathematik/klasse-10/potenzen/erste-uebungen'
        summary = tmp_path / path / FILENAME
        before = summary.read_text()
        assert response.json['data']['einsatz'] == [{'datum': '2026-11-12'}]
        assert client.post('/api/units/new', json=payload).status_code == 409
        assert summary.read_text() == before
        assert client.get('/api/units').json['units'][0]['path'] == path
    finally:
        app.extensions['material_runtime'].close()


@pytest.mark.parametrize('patch', [{'klasse': '../10'}, {'klasse': '99'}, {'thema': '../Potenzen'}, {'titel': ''}, {'datum': '2026-02-30'}, {'datumsneutral': 'true'}])
def test_create_unit_rejects_invalid_values_before_creating_folder(units, patch):
    service, folder = units
    payload = {'fach': 'mathematik', 'klasse': '10', 'thema': 'Potenzen', 'titel': 'Neu', **patch}
    with pytest.raises(InvalidInput):
        service.create(payload)
    assert not (service.config.root / 'unterricht/mathematik/klasse-10').exists()


def test_create_unit_and_worksheet_from_sidebar(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.locator('#viewButton-units').click()
            open_unit_menu(page, '[data-add-menu]')
            page.locator('[data-new-unit]').click()
            form = page.locator('.unit-create-form')
            form.locator('[name=titel]').fill('Wurzeln')
            form.locator('[name=thema-new]').fill('Potenzen')
            form.locator('[data-create-context] > summary').click()
            form.locator('[name=klasse]').fill('10')
            overview_requests = []
            page.on('request', lambda request: overview_requests.append(request.url)
                    if request.url.endswith('/api/units') else None)
            with page.expect_response(lambda r: r.url.endswith('/api/units/new')) as created:
                form.locator('[type=submit]').click()
            assert created.value.status == 201
            card = page.locator('[data-unit-path="unterricht/mathematik/klasse-10/potenzen/wurzeln"]')
            card.wait_for(state='visible')
            assert page.locator('[data-class][aria-pressed="true"]').get_attribute('data-class') == 'klasse-10'
            assert card.get_attribute('open') is not None
            assert not overview_requests
            # New undated units stay accessible without exposing every old undated unit.
            assert not page.locator('[data-show-undated]').is_checked()
            card.locator('[data-new-worksheet]').click()
            page.locator('#newDocModal.open').wait_for()
            assert page.locator('#newKind').input_value() == 'Arbeitsblatt'
            assert page.locator('#newTargetFolder').input_value() == 'unterricht/mathematik/klasse-10/potenzen/wurzeln'
            assert page.locator('#newSubject').input_value() == 'mathematik'
            assert page.locator('#newGrade').input_value() == '10'
            assert page.locator('#newTopic').input_value() == 'Potenzen'
            page.locator('#newTitle').fill('Wurzeln üben')
            with page.expect_response(lambda r: r.url.endswith('/api/document/new')) as worksheet:
                page.locator('#createNewDoc').click()
            assert worksheet.value.status == 200
            path = worksheet.value.json()['path']
            assert path == 'unterricht/mathematik/klasse-10/potenzen/wurzeln/ab_wurzeln-ueben.qmd'
            assert (tmp_path / path).is_file()
            link = card.locator('.unit-material-link').first
            link.wait_for(state='visible')
            assert link.locator('.unit-material-kind').inner_text() == 'Arbeitsblatt'
            assert 'Wurzeln üben' in link.inner_text()
            assert link.get_attribute('href').endswith('ab_wurzeln-ueben.qmd')
            # No duplicate unit or misplaced per-file material folder was created.
            assert len(list(tmp_path.rglob(FILENAME))) == 1
            assert len(list(tmp_path.rglob('ab_*.qmd'))) == 1
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_attach_existing_folder_keeps_material_and_usage_history(units):
    service, folder = units
    source = folder / 'ab_bibi.qmd'
    original = source.read_bytes()
    unit = service.read(folder)
    payload = {'path': unit['path'], 'revision': unit['revision'], 'titel': 'Multiplikation',
               'thema': 'Arithmetik / Multiplikation', 'datum': '2026-11-06', 'lerngruppe': '5a'}
    first = service.attach(payload)
    assert first['data']['einsatz'] == [{'datum': '2026-11-06', 'lerngruppe': '5a'}]
    assert source.read_bytes() == original
    assert first['gespeichert']
    first['data']['kurzbeschreibung'] = 'Diese Notizen behalten.'
    first['data']['datumsneutral'] = True
    first['data']['eigene_angabe'] = 'behalten'
    saved = service.save(first['path'], first['data'], first['revision'])
    next_use = service.attach({**payload, 'revision': saved['revision'], 'datum': '2027-11-05'})
    assert [use['datum'] for use in next_use['data']['einsatz']] == ['2026-11-06', '2027-11-05']
    assert next_use['data']['kurzbeschreibung'] == 'Diese Notizen behalten.'
    assert next_use['data']['datumsneutral'] is True
    assert next_use['data']['eigene_angabe'] == 'behalten'
    repeated = service.attach({**payload, 'datum': '2027-11-05', 'revision': next_use['revision']})
    assert len(repeated['data']['einsatz']) == 2
    with pytest.raises(RevisionConflict):
        service.attach(payload)
    assert source.read_bytes() == original


def test_folder_candidates_include_parent_folders_and_skip_hidden_and_links(units):
    service, folder = units
    (folder / '.intern').mkdir()
    (folder / 'assets').mkdir()
    (folder.parent / 'verlinkt').symlink_to(folder, target_is_directory=True)
    candidates = service.folder_candidates('klasse-05')
    paths = [entry['path'] for entry in candidates['folders']]
    assert service.config.relative(folder) in paths
    assert service.config.relative(folder.parent) in paths
    assert not any('.intern' in path or 'assets' in path or 'verlinkt' in path for path in paths)
    assert not service.folder_candidates('klasse-10')['folders']
    assert not candidates['errors']


def test_attach_folder_rejects_missing_dates_and_invalid_paths(units):
    service, folder = units
    unit = service.read(folder)
    payload = {'path': unit['path'], 'revision': unit['revision'], 'titel': 'Test', 'thema': 'Potenzen'}
    for patch in ({}, {'datum': '2026-02-30'}, {'datum': '2026-11-06', 'path': '../outside'}, {'datum': '2026-11-06', 'path': 'unterricht'}):
        with pytest.raises(InvalidInput):
            service.attach({**payload, **patch})
    assert not (folder / FILENAME).exists()


def test_attach_folder_from_picker_and_folder_tree(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    folder = tmp_path / 'unterricht/mathematik/klasse-10/potenzen/04-wurzeln'
    write_qmd(folder / 'ab_wurzeln.qmd', '---\ntitle: Wurzeln üben\n---\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.locator('#viewButton-units').click()
            assert page.locator('.unit-card').count() == 0
            open_unit_menu(page, '[data-add-menu]')
            page.locator('[data-attach-folder]').click()
            form = page.locator('.unit-attach-form')
            form.locator('[data-folder-search]').fill('04-wurzeln')
            assert form.locator('[data-folder-picker] option').count() == 1
            path = folder.relative_to(tmp_path).as_posix()
            form.locator('[data-folder-picker]').select_option(path)
            assert form.locator('[name=titel]').input_value() == 'Wurzeln'
            assert form.locator('[name=thema]').evaluate('element => element.value') == 'potenzen'
            # Thema ist eine Auswahl mit bestehenden Themen der Jahrgangsstufe und
            # der Option, ein neues Thema einzutragen.
            form.locator('[name=thema]').select_option(label='+ Neues Thema…')
            form.locator('[name=thema-new]').fill('Potenzen')
            form.locator('[name=datum]').fill('2026-11-12')
            with page.expect_response(lambda response: response.url.endswith('/api/units/attach')) as attached:
                form.locator('[type=submit]').click()
            assert attached.value.status == 200
            card = page.locator(f'[data-unit-path="{path}"]')
            card.wait_for(state='visible')
            assert card.locator('time').get_attribute('datetime') == '2026-11-12'
            assert card.get_by_role('link', name='Arbeitsblatt: Wurzeln üben').count() == 1
            # The direct action on a folder reuses existing metadata and appends a later use.
            # Der Ordnerbaum kann unter Last erst nach dem Ansichtswechsel nachgeladen
            # werden; das Warten bekommt ein grosszuegiges Budget, statt unter dem
            # 30-Sekunden-Standardlimit zu flaken.
            page.locator('#folderViewButton').click()
            row = page.locator(f'summary[data-folder="{path}"]')
            row.wait_for(state='visible', timeout=60000)
            row.locator('.index-label').click()
            if row.locator('..').get_attribute('open') is None:
                row.locator('.index-label').click()
            row.locator('..').locator(':scope > [data-unit-folder]').click()
            form.locator('[name=datum]').wait_for(state='visible')
            assert form.locator('[name=titel]').input_value() == 'Wurzeln'
            assert form.locator('[name=thema]').evaluate('element => element.value') == 'Potenzen'
            assert '12.11.2026' in form.locator('[data-existing-uses]').inner_text()
            form.locator('[name=datum]').fill('2027-11-10')
            # A concurrent edit must survive, and reloading must retain the entered date.
            runtime = app.extensions['material_runtime']
            service = UnitService(runtime.config, runtime.services.documents)
            current = service.read(folder)
            current['data']['kurzbeschreibung'] = 'Zwischenzeitlich ergänzt'
            service.save(path, current['data'], current['revision'])
            with page.expect_response(lambda response: response.url.endswith('/api/units/attach')) as conflict:
                form.locator('[type=submit]').click()
            assert conflict.value.status == 409
            form.get_by_role('button', name='Ordnerdaten neu laden').click()
            form.locator('[name=datum]').wait_for(state='visible')
            assert form.locator('[name=datum]').input_value() == '2027-11-10'
            with page.expect_response(lambda response: response.url.endswith('/api/units/attach')) as appended:
                form.locator('[type=submit]').click()
            assert appended.value.status == 200
            assert [use['datum'] for use in appended.value.json()['data']['einsatz']] == ['2026-11-12', '2027-11-10']
            page.wait_for_function("document.querySelector('[data-year]').value === '2027/2028'")
            assert page.locator('[data-year]').input_value() == '2027/2028'
            assert card.locator('time').get_attribute('datetime') == '2027-11-10'
            assert appended.value.json()['data']['kurzbeschreibung'] == 'Zwischenzeitlich ergänzt'
            assert len(list(tmp_path.rglob('ab_wurzeln.qmd'))) == 1
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


@pytest.mark.parametrize('tags', ['vertretung', [None], [''], [3]])
def test_invalid_unit_tags_are_rejected(units, tags):
    service, folder = units
    unit = service.read(folder)
    unit['data']['tags'] = tags
    with pytest.raises(InvalidInput, match='tags'):
        service.save(unit['path'], unit['data'], unit['revision'])
    assert not (folder / FILENAME).exists()


def test_unit_tags_survive_uses_and_metadata_changes(units):
    service, folder = units
    unit = service.read(folder)
    unit['data']['tags'] = [' vertretung ', 'multiplikation', 'vertretung']
    saved = service.save(unit['path'], unit['data'], unit['revision'])
    assert saved['data']['tags'] == ['vertretung', 'multiplikation']
    saved['data']['einsatz'] = [{'datum': '2026-11-06', 'material': 'ab_bibi.qmd'}]
    service.save(saved['path'], saved['data'], saved['revision'])
    assert service.read(folder)['data']['tags'] == ['vertretung', 'multiplikation']


def test_sidebar_edits_displays_and_filters_tags(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    folder = tmp_path / 'unterricht/mathematik/klasse-05/multiplikation/uebungen'
    write_qmd(folder / 'ab.qmd', '---\ntitle: Üben\n---\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.locator('#viewButton-units').click()
            page.locator('[data-show-undated]').check()
            expand_unit(page.locator('.unit-card'))
            page.locator('[data-edit]').click()
            page.locator('input[name=tags]').fill('vertretung, multiplikation, vertretung')
            page.locator('button[type=submit]').filter(has_text='Speichern').click()
            page.wait_for_function("document.querySelectorAll('.unit-tags .tag-chip').length === 2")
            open_unit_menu(page, '.unit-filters')
            search = page.locator('[data-tag-filter]')
            search.fill('vertretung, multiplikation')
            search.press('Tab')
            assert page.locator('.unit-card').count() == 1
            open_unit_menu(page, '.unit-filters')
            search = page.locator('[data-tag-filter]')
            search.fill('vertretungsrueckblick')
            search.press('Tab')
            page.wait_for_function("document.querySelectorAll('.unit-card').length === 0")
            open_unit_menu(page, '.unit-filters')
            search = page.locator('[data-tag-filter]')
            search.fill('')
            search.press('Tab')
            page.wait_for_function("document.querySelectorAll('.unit-card').length === 1")
            expand_unit(page.locator('.unit-card'))
            page.locator('[data-edit]').click()
            assert page.locator('input[name=tags]').input_value() == 'vertretung, multiplikation'
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_inline_editing_of_tags_and_notes(unit_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, parent = unit_app
    path = parent.relative_to(service.config.root).as_posix()
    unit = service.read(parent)
    unit['data'].update(kurzbeschreibung='Multiplikation mit dem Malkreuz üben.', tags=['arithmetik'])
    service.save(unit['path'], unit['data'], unit['revision'])
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.locator('#viewButton-units').click()
            card = page.locator(f'[data-unit-path="{path}"]')
            expand_unit(card)
            assert card.locator('[data-tags-row] .tag-chip').all_text_contents() == ['arithmetik']
            # Abbrechen stellt die Tags zurück; der Stift wirkt danach ohne Neuladen erneut.
            card.locator('[data-edit-tags]').click()
            card.locator('[data-tags-row] input[name=tags]').fill('vertretung')
            page.once('dialog', lambda dialog: dialog.accept())
            card.locator('[data-tags-row] [data-inline-cancel]').click()
            assert card.locator('[data-tags-row] form').count() == 0
            assert card.locator('[data-tags-row] .tag-chip').all_text_contents() == ['arithmetik']
            # Speichern schreibt dedupliziert über die normale Einheiten-API.
            card.locator('[data-edit-tags]').click()
            card.locator('[data-tags-row] input[name=tags]').fill('arithmetik, multiplikation, arithmetik')
            with page.expect_response(lambda r: r.url.endswith('/api/units') and r.request.method == 'POST') as saved:
                card.locator('[data-tags-row] [type=submit]').click()
            assert saved.value.status == 200
            assert service.read(parent)['data']['tags'] == ['arithmetik', 'multiplikation']
            page.wait_for_function("document.querySelectorAll('.unit-tags .tag-chip').length === 2")
            assert card.locator('[data-tags-row] .tag-chip').all_text_contents() == ['arithmetik', 'multiplikation']
            # Der Notizen-Stift liegt in der Überschrift und bearbeitet die Kurzbeschreibung.
            assert card.locator('.unit-notes').get_attribute('open') is None
            card.locator('[data-edit-notes]').click()
            assert card.locator('.unit-notes').get_attribute('open') is not None
            assert card.locator('.unit-notes textarea[name=kurzbeschreibung]').input_value() == 'Multiplikation mit dem Malkreuz üben.'
            card.locator('.unit-notes textarea[name=kurzbeschreibung]').fill('Malkreuz und schriftliches Verfahren.')
            with page.expect_response(lambda r: r.url.endswith('/api/units') and r.request.method == 'POST') as saved_notes:
                card.locator('.unit-notes [type=submit]').click()
            assert saved_notes.value.status == 200
            assert service.read(parent)['data']['kurzbeschreibung'] == 'Malkreuz und schriftliches Verfahren.'
            page.wait_for_function("document.querySelector('.unit-notes [data-notes-text]')?.textContent === 'Malkreuz und schriftliches Verfahren.'")
            # Ein offener Entwurf des großen Editors blockiert die Inline-Bearbeitung.
            expand_unit(card)
            card.locator('[data-edit]').click()
            card.locator('[name=titel]').fill('Entwurf im großen Editor')
            card.locator('[data-edit-tags]').click()
            assert card.locator('[data-tags-row] form').count() == 0
            assert 'Bitte zuerst' in page.locator('[data-status]').inner_text()
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_append_dates_preserves_metadata_deduplicates_and_checks_revision(units):
    service, folder = units
    unit = service.read(folder)
    unit['data'].update(kurzbeschreibung='Notizen behalten', tags=['wiederholung'], eigenes_feld='behalten',
                        einsatz=[{'datum': '2026-11-06', 'material': 'ab_bibi.qmd'}])
    saved = service.save(unit['path'], unit['data'], unit['revision'])
    payload = {'path': unit['path'], 'revision': saved['revision'], 'dates': ['2027-11-10', '2027-11-11', '2027-11-10'], 'lerngruppe': '5a'}
    updated = service.append_dates(payload)
    assert updated['data']['einsatz'] == [{'datum': '2026-11-06', 'material': 'ab_bibi.qmd'},
                                         {'datum': '2027-11-10', 'lerngruppe': '5a'},
                                         {'datum': '2027-11-11', 'lerngruppe': '5a'}]
    assert updated['data']['kurzbeschreibung'] == 'Notizen behalten'
    assert updated['data']['tags'] == ['wiederholung']
    assert updated['data']['eigenes_feld'] == 'behalten'
    repeated = service.append_dates({**payload, 'revision': updated['revision']})
    assert len(repeated['data']['einsatz']) == 3
    with pytest.raises(RevisionConflict):
        service.append_dates(payload)


def test_append_dates_assigns_material_and_removes_only_the_named_use(units):
    service, folder = units
    unit = service.read(folder)
    base = {'path': unit['path'], 'lerngruppe': '5a'}
    whole = service.append_dates({**base, 'revision': unit['revision'], 'dates': ['2026-11-06']})
    with_material = service.append_dates({**base, 'revision': whole['revision'], 'dates': ['2026-11-06'], 'material': 'ab_bibi.qmd'})
    # Gleiches Datum mit anderem Material ist ein eigener Einsatz, dasselbe Material nicht doppelt.
    assert with_material['data']['einsatz'] == [{'datum': '2026-11-06', 'lerngruppe': '5a'},
                                                {'datum': '2026-11-06', 'lerngruppe': '5a', 'material': 'ab_bibi.qmd'}]
    again = service.append_dates({**base, 'revision': with_material['revision'], 'dates': ['2026-11-06'], 'material': 'ab_bibi.qmd'})
    assert len(again['data']['einsatz']) == 2
    removed = service.append_dates({**base, 'revision': again['revision'],
                                    'remove': [{'datum': '2026-11-06', 'lerngruppe': '5a'}]})
    assert removed['data']['einsatz'] == [{'datum': '2026-11-06', 'lerngruppe': '5a', 'material': 'ab_bibi.qmd'}]
    # Entfernen ist idempotent: ein fehlender Einsatz ändert nichts.
    repeated = service.append_dates({**base, 'revision': removed['revision'],
                                     'remove': [{'datum': '2026-11-06', 'lerngruppe': '5a'}]})
    assert repeated['data']['einsatz'] == removed['data']['einsatz']
    with pytest.raises(RevisionConflict):
        service.append_dates({**base, 'revision': whole['revision'], 'remove': [{'datum': '2026-11-06', 'lerngruppe': '5a'}]})


@pytest.mark.parametrize('extra', [{'remove': 'x'}, {'remove': [{'datum': ''}]}, {'remove': [{'datum': '2026-11-06', 'material': 3}]},
                                   {'dates': ['2026-11-06'], 'material': 3}, {'dates': ['2026-11-06'], 'material': '../aussen.qmd'}])
def test_append_dates_rejects_invalid_removals_and_material(units, extra):
    service, folder = units
    unit = service.read(folder)
    with pytest.raises(InvalidInput):
        service.append_dates({'path': unit['path'], 'revision': unit['revision'], **extra})
    assert not (folder / FILENAME).exists()


@pytest.mark.parametrize('dates', [[], ['2026-02-30'], ['06.11.2026'], [None], '2026-11-06'])
def test_invalid_quick_dates_do_not_modify_summary(units, dates):
    service, folder = units
    unit = service.read(folder)
    with pytest.raises(InvalidInput):
        service.append_dates({'path': unit['path'], 'revision': unit['revision'], 'dates': dates})
    assert not (folder / FILENAME).exists()


def test_picker_clears_filtered_selection_and_forms_survive_reload(unit_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, parent = unit_app
    path = parent.relative_to(service.config.root).as_posix()
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until='networkidle')
        page.locator('#viewButton-units').click()
        open_unit_menu(page, '[data-add-menu]')
        page.locator('[data-new-unit]').click()
        new_form = page.locator('[data-new-unit-form] form')
        new_form.locator('[name=titel]').fill('Mein neuer Entwurf')
        new_form.locator('[name=thema-new]').fill('Neues Thema')
        open_unit_menu(page, '[data-add-menu]')
        page.locator('[data-attach-folder]').click()
        attach = page.locator('.unit-attach-form')
        attach.locator('[data-folder-picker]').select_option(path)
        attach.locator('[name=datum]').fill('2027-11-10')
        attach.locator('[name=lerngruppe]').select_option('5b')
        page.reload(wait_until='networkidle')
        assert new_form.locator('[name=titel]').input_value() == 'Mein neuer Entwurf'
        assert new_form.locator('[name=thema-new]').input_value() == 'Neues Thema'
        assert attach.locator('[data-folder-picker]').input_value() == path
        assert attach.locator('[name=datum]').input_value() == '2027-11-10'
        assert attach.locator('[name=lerngruppe]').input_value() == '5b'
        before = (parent / FILENAME).read_text()
        attach.locator('[data-folder-search]').fill('KeineTrefferXYZ')
        assert attach.locator('[data-folder-picker]').is_disabled()
        assert attach.locator('[data-folder-picker]').input_value() == ''
        assert attach.locator('[type=submit]').is_disabled()
        # Even an explicit submit event cannot bind the formerly selected folder.
        attach.evaluate("form => form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))")
        assert (parent / FILENAME).read_text() == before
        attach.locator('[data-folder-search]').fill('')
        assert attach.locator('[type=submit]').is_disabled()
        attach.locator('[data-folder-picker]').select_option(path)
        assert attach.locator('[type=submit]').is_enabled()
        browser.close()


def test_view_filters_expansion_and_scroll_survive_refresh_and_reload(unit_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, parent = unit_app
    for number in range(25):
        service.create({'fach': 'mathematik', 'klasse': '10', 'titel': f'Einheit {number:02d}', 'thema': 'Potenzen', 'datum': '2027-11-10'})
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 700})
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until='networkidle')
        page.locator('#viewButton-units').click()
        open_unit_menu(page, '.unit-filters')
        page.locator('[data-year]').select_option('2027/2028')
        page.locator('[data-class="klasse-10"]').click()
        card = page.locator('.unit-card').first
        expand_unit(card)
        open_unit_menu(page, '[data-options-menu]')
        with page.expect_response(lambda r: r.url.endswith('/api/units')):
            page.locator('#reloadIndex').click()
        page.wait_for_function("document.querySelector('.unit-card').open")
        assert page.locator('#viewButton-units').get_attribute('aria-pressed') == 'true'
        assert page.locator('[data-class][aria-pressed="true"]').get_attribute('data-class') == 'klasse-10'
        assert page.locator('[data-year]').input_value() == '2027/2028'
        page.locator('.units-view').evaluate('pane => { pane.scrollTop = 240; }')
        page.wait_for_function("document.querySelector('.units-view').scrollTop >= 230")
        with page.expect_response(lambda r: r.url.endswith('/api/units')):
            page.locator('#reloadIndex').click()
        page.wait_for_function("document.getElementById('reloadIndex').disabled === false")
        page.wait_for_function("document.querySelector('.units-view').scrollTop >= 230")
        page.reload(wait_until='networkidle')
        assert page.locator('[data-class][aria-pressed="true"]').get_attribute('data-class') == 'klasse-10'
        assert page.locator('[data-year]').input_value() == '2027/2028'
        assert card.get_attribute('open') is not None
        page.wait_for_function("document.querySelector('.units-view').scrollTop >= 230")
        # A closed topic must also remain closed after a refresh.
        page.locator('.unit-topic > summary').click()
        open_unit_menu(page, '[data-options-menu]')
        with page.expect_response(lambda r: r.url.endswith('/api/units')):
            page.locator('#reloadIndex').click()
        page.wait_for_function("!document.querySelector('.unit-topic').open")
        browser.close()


def test_quick_dates_survive_reload_and_append_multiple_dates(unit_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, parent = unit_app
    path = parent.relative_to(service.config.root).as_posix()
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until='networkidle')
        page.locator('#viewButton-units').click()
        card = page.locator(f'[data-unit-path="{path}"]')
        expand_unit(card)
        card.locator('[data-quick-date]').click()
        form = card.locator('.unit-quick-dates')
        assert form.locator('[data-existing-date-rows] input').first.input_value() == '2026-11-06'
        form.locator('[data-more-date]').click()
        form.locator('[data-date-rows] input').fill('2027-11-10')
        form.locator('[data-more-date]').click()
        form.locator('[data-date-rows] input').last.fill('2027-11-11')
        form.locator('[name=lerngruppe]').select_option('5b')
        page.reload(wait_until='networkidle')
        assert form.locator('[data-date-rows] input').evaluate_all('(inputs) => inputs.map(input => input.value)') == ['2027-11-10', '2027-11-11']
        assert form.locator('[name=lerngruppe]').input_value() == '5b'
        current = service.read(parent)
        current['data']['kurzbeschreibung'] = 'Externe Notizen behalten'
        service.save(path, current['data'], current['revision'])
        with page.expect_response(lambda r: r.url.endswith('/api/units/dates')) as conflict:
            form.locator('[type=submit]').click()
        assert conflict.value.status == 409
        with page.expect_response(lambda r: r.url.endswith('/api/units')):
            form.get_by_role('button', name='Aktuelle Einheit laden').click()
        form.get_by_role('button', name='Aktuelle Einheit laden').wait_for(state='hidden')
        assert form.locator('[data-date-rows] input').evaluate_all('(inputs) => inputs.map(input => input.value)') == ['2027-11-10', '2027-11-11']
        with page.expect_response(lambda r: r.url.endswith('/api/units/dates')) as saved:
            form.locator('[type=submit]').click()
        assert saved.value.status == 200
        page.wait_for_function("!document.querySelector('.unit-quick-dates')")
        assert page.locator('[data-year]').input_value() == '2027/2028'
        assert card.locator('time').all_text_contents() == ['10.11', '11.11']
        assert [use['datum'] for use in service.read(parent)['data']['einsatz']] == ['2026-11-06', '2027-11-10', '2027-11-11']
        assert service.read(parent)['data']['kurzbeschreibung'] == 'Externe Notizen behalten'
        browser.close()


def test_edit_existing_date_preserves_use_details_and_other_dates(units):
    service, folder = units
    unit = service.read(folder)
    original = {'datum': '2026-11-06', 'lerngruppe': '5a', 'material': 'ab_bibi.qmd', 'notiz': 'Behalten', 'eigene_angabe': 7}
    unit['data']['einsatz'] = [original, {'datum': '2025-10-10', 'lerngruppe': '5b'}]
    saved = service.save(unit['path'], unit['data'], unit['revision'])
    edited = service.append_dates({'path': unit['path'], 'revision': saved['revision'], 'dates': [], 'updates': [{'index': 0, 'datum': '2026-11-07'}]})
    assert edited['data']['einsatz'] == [{**original, 'datum': '2026-11-07'}, {'datum': '2025-10-10', 'lerngruppe': '5b'}]
    with pytest.raises(RevisionConflict):
        service.append_dates({'path': unit['path'], 'revision': saved['revision'], 'updates': [{'index': 0, 'datum': '2026-11-08'}]})


@pytest.mark.parametrize('updates', [[{'index': -1, 'datum': '2026-11-07'}], [{'index': True, 'datum': '2026-11-07'}],
                                     [{'index': 20, 'datum': '2026-11-07'}], [{'index': 0, 'datum': '2026-02-30'}],
                                     [{'index': 0, 'datum': '2026-11-07'}, {'index': 0, 'datum': '2026-11-08'}]])
def test_invalid_date_edits_do_not_change_summary(units, updates):
    service, folder = units
    unit = service.read(folder)
    unit['data']['einsatz'] = [{'datum': '2026-11-06'}]
    saved = service.save(unit['path'], unit['data'], unit['revision'])
    before = (folder / FILENAME).read_text()
    with pytest.raises(InvalidInput):
        service.append_dates({'path': unit['path'], 'revision': saved['revision'], 'updates': updates})
    assert (folder / FILENAME).read_text() == before


def test_existing_date_shown_and_editable_without_adding_duplicate(unit_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, parent = unit_app
    path = parent.relative_to(service.config.root).as_posix()
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until='networkidle')
        page.locator('#viewButton-units').click()
        card = page.locator(f'[data-unit-path="{path}"]')
        expand_unit(card)
        card.get_by_role('button', name='Termine anzeigen und bearbeiten').click()
        form = card.locator('.unit-quick-dates')
        assert form.locator('[data-existing-date-rows] input').input_value() == '2026-11-06'
        assert form.locator('[data-date-rows] input').count() == 0
        assert form.locator('[type=submit]').is_disabled()
        assert not form.locator('[data-new-date-group]').is_visible()
        form.locator('[data-existing-date-rows] input').fill('2026-11-07')
        with page.expect_response(lambda response: response.url.endswith('/api/units/dates')) as edited:
            form.locator('[type=submit]').click()
        assert edited.value.status == 200
        page.wait_for_function("!document.querySelector('.unit-quick-dates')")
        assert card.locator('time').get_attribute('datetime') == '2026-11-07'
        assert service.read(parent)['data']['einsatz'] == [{'datum': '2026-11-07', 'material': '01_einstieg/ab.qmd'}]
        card.get_by_role('button', name='Termine anzeigen und bearbeiten').click()
        assert form.locator('[data-existing-date-rows] input').input_value() == '2026-11-07'
        browser.close()


def test_selected_unit_tracks_open_material_and_tab_switches(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    base = tmp_path / 'unterricht/mathematik/klasse-05/multiplikation'
    for name in ('zerlegen', 'malkreuz'):
        write_qmd(base / name / f'ab_{name}.qmd', f'---\ntitle: {name}\n---\nText\n')
    write_qmd(base / "zerlegen/ab_zweite.qmd", "---\ntitle: Zweites AB\n---\nText\n")
    app = create_app(config=AppConfig(tmp_path))
    runtime = app.extensions['material_runtime']
    service = UnitService(runtime.config, runtime.services.documents)
    for name in ('zerlegen', 'malkreuz'):
        unit = service.read(base / name)
        unit['data']['einsatz'] = [{'datum': '2026-11-06'}]
        service.save(unit['path'], unit['data'], unit['revision'])
    a_path = (base / 'zerlegen').relative_to(tmp_path).as_posix()
    b_path = (base / 'malkreuz').relative_to(tmp_path).as_posix()
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url + '/?path=' + b_path + '/ab_malkreuz.qmd', wait_until='networkidle')
            page.locator('#viewButton-units').click()
            a = page.locator(f'[data-unit-path="{a_path}"]')
            b = page.locator(f'[data-unit-path="{b_path}"]')
            a.wait_for(state='visible')
            page.evaluate('window.navigationGroups = document.querySelector("[data-groups]")')
            expand_unit(a)
            a.locator('.unit-material-link').first.click()
            page.wait_for_function("document.querySelector('.unit-selected')?.dataset.unitPath.endsWith('/zerlegen')")
            assert a.locator(':scope > summary').get_attribute('aria-current') == 'location'
            page.wait_for_function("document.querySelector('.unit-selected a[aria-current=page]')?.dataset.documentPath.endsWith('/ab_zerlegen.qmd')")
            assert a.locator('.unit-material-link').first.get_attribute('aria-current') == 'page'
            assert a.evaluate('(card) => getComputedStyle(card).borderLeftColor') != b.evaluate('(card) => getComputedStyle(card).borderLeftColor')
            assert page.evaluate('window.navigationGroups === document.querySelector("[data-groups]")')
            a.evaluate('(card) => { window.navigationCard = card; }')
            a.locator('.unit-material-link').nth(1).click()
            page.wait_for_function("document.querySelector('.unit-selected a[aria-current=page]')?.dataset.documentPath.endsWith('/ab_zweite.qmd')")
            assert a.evaluate('(card) => card === window.navigationCard')
            assert page.evaluate('window.navigationGroups === document.querySelector("[data-groups]")')
            page.locator('#folderViewButton').click()
            page.locator(f'[data-tab="{b_path}/ab_malkreuz.qmd"]').click()
            page.locator('#viewButton-units').click()
            page.wait_for_function("document.querySelector('.unit-selected')?.dataset.unitPath.endsWith('/malkreuz')")
            b.wait_for(state='visible')
            page.wait_for_function("document.querySelector('.unit-selected')?.open === true")
            assert b.get_attribute('open') is not None
            assert b.locator('.unit-material-link').get_attribute('aria-current') == 'page'
            assert a.locator(':scope > summary').get_attribute('aria-current') is None
            page.reload(wait_until='networkidle')
            assert b.locator(':scope > summary').get_attribute('aria-current') == 'location'
            browser.close()
    finally:
        runtime.close()


def test_class_badges_filter_school_year_and_split_upper_school_terms(unit_app):
    from datetime import datetime, timezone
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, _ = unit_app
    for grade, title, dates in [
        ('06', 'Alte Einheit', ['2026-07-31']),
        ('07', 'Januar', ['2027-01-15']),
        ('08', 'Entwurf', []),
        ('10', 'Potenzen', ['2026-11-03']),
        ('11', 'Einführungsphase', ['2026-11-04']),
        ('12', 'Erstes Halbjahr', ['2026-11-04']),
        ('12', 'Zweites Halbjahr', ['2027-02-04']),
        ('13', 'Drittes Halbjahr', ['2026-11-04']),
        ('13', 'Viertes Halbjahr', ['2027-02-04']),
    ]:
        created = service.create({'fach': 'mathematik', 'klasse': grade, 'titel': title, 'thema': 'Test'})
        created['data']['einsatz'] = [{'datum': date} for date in dates]
        service.save(created['path'], created['data'], created['revision'])
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 800})
        page.clock.install(time=datetime(2026, 11, 5, 12, tzinfo=timezone.utc))
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until='networkidle')
        page.locator('#viewButton-units').click()
        badges = page.locator('.unit-class-badges button')
        badges.first.wait_for(state='visible')
        assert badges.all_text_contents() == ['5', '7', '10', 'E', 'Q1', 'Q2', 'Q3', 'Q4']
        assert page.locator('select[data-class]').count() == 0
        page.get_by_role('button', name='Klasse 10', exact=True).click()
        selected = page.locator('.unit-class-badges [aria-pressed="true"]')
        assert selected.inner_text() == '10'
        assert selected.count() == 1
        page.reload(wait_until='networkidle')
        assert selected.inner_text() == '10'
        page.get_by_role('button', name='Q2', exact=True).click()
        assert page.locator('.unit-card > summary').all_text_contents() == ['Zweites HalbjahrIn Bearbeitung04.02']
        page.reload(wait_until='networkidle')
        assert selected.inner_text() == 'Q2'
        assert page.locator('.unit-card > summary').all_text_contents() == ['Zweites HalbjahrIn Bearbeitung04.02']
        page.get_by_role('button', name='Q1', exact=True).click()
        assert page.locator('.unit-card > summary').all_text_contents() == ['Erstes HalbjahrIn Bearbeitung04.11']
        page.get_by_role('button', name='Q4', exact=True).click()
        assert page.locator('.unit-card > summary').all_text_contents() == ['Viertes HalbjahrIn Bearbeitung04.02']
        open_unit_menu(page, '.unit-filters')
        page.locator('[data-year]').select_option('2025/2026')
        assert badges.all_text_contents() == ['6']
        assert selected.inner_text() == '6'
        page.locator('[data-show-undated]').check()
        assert '8' in badges.all_text_contents()
        browser.close()


def test_move_material_keeps_dates_and_parent_references(unit_app):
    app, service, parent = unit_app
    source = parent / '01_einstieg/ab.qmd'
    target = parent / '02_uebung/ab.qmd'
    target.unlink()
    response = app.test_client().post('/api/file/move', json={
        'path': service.config.relative(source),
        'destination': service.config.relative(target.parent),
    })
    assert response.status_code == 200, response.json
    assert target.is_file() and not source.exists()
    assert service.read(source.parent)['data']['einsatz'] == [{'datum': '2026-11-06'}]
    assert service.read(parent)['data']['einsatz'][0]['material'] == '02_uebung/ab.qmd'
    assert response.json['path'] == service.config.relative(target)


def test_move_material_refuses_collision(unit_app):
    app, service, parent = unit_app
    source = parent / '01_einstieg/ab.qmd'
    before = (source.parent / FILENAME).read_text()
    response = app.test_client().post('/api/file/move', json={
        'path': service.config.relative(source),
        'destination': service.config.relative(parent / '02_uebung'),
    })
    assert response.status_code == 409
    assert source.exists()
    assert (source.parent / FILENAME).read_text() == before


@pytest.mark.parametrize('inactive_tab', [False, True])
def test_drag_material_to_closed_unit_in_browser(unit_app, inactive_tab):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, parent = unit_app
    source = parent / '01_einstieg/ab_mini_test.qmd'
    (source.parent / 'ab.qmd').rename(source)
    target = parent / '02_uebung/ab_mini_test.qmd'
    (target.parent / 'ab.qmd').unlink()
    other = source.with_name('zz_other.qmd')
    if inactive_tab:
        other.write_text('---\ntitle: Anderes AB\n---\nText')
    unit = service.read(target.parent)
    unit['data']['einsatz'] = [{'datum': '2026-11-06'}]
    service.save(unit['path'], unit['data'], unit['revision'])
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1400})
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url + '/?path=' + service.config.relative(source), wait_until='networkidle')
        page.locator('#viewButton-units').click()
        origin = page.locator(f'.unit-card[data-unit-path="{service.config.relative(source.parent)}"]')
        destination = page.locator(f'.unit-card[data-unit-path="{service.config.relative(target.parent)}"]')
        expand_unit(origin)
        if inactive_tab:
            origin.locator(f'[data-document-path="{service.config.relative(other)}"]').click()
        link = origin.locator(f'[data-document-path="{service.config.relative(source)}"]')
        with page.expect_response(lambda r: r.url.endswith('/api/file/move'), timeout=10000) as response:
            link.scroll_into_view_if_needed()
            start = link.locator('.unit-material-kind').bounding_box()
            end = destination.locator(':scope > summary').bounding_box()
            page.mouse.move(start['x'] + 12, start['y'] + start['height'] / 2)
            page.mouse.down()
            page.mouse.move(end['x'] + 30, end['y'] + end['height'] / 2, steps=20)
            assert 'unit-drop-target' in destination.get_attribute('class')
            assert link.evaluate('(a) => a.hasPointerCapture(1)')
            page.mouse.up()
        assert response.value.status == 200
        page.wait_for_function("document.querySelector('.units-view [data-status]').textContent.includes('verschoben')")
        assert target.exists() and not source.exists()
        assert destination.locator('.unit-material-link').count() == 1
        assert page.locator(f'[data-tab="{service.config.relative(source)}"]').count() == 0
        assert page.locator(f'[data-tab="{service.config.relative(target)}"]').count() == 1
        browser.close()


@pytest.mark.parametrize('content', [
    '![](assets/bild.svg)', '[Quelle](hinweise.md)',
    '![Bild][bild]\n\n[bild]: assets/bild.svg',
    '{{< include fragment.qmd >}}',
    '```{=typst}\n#image("assets/bild.svg")\n```',
    '---\ntitle: Test\nresources: [assets/*]\n---\nText',
    '<img src="assets/bild.svg">',
])
def test_move_blocks_relative_resources_before_changes(unit_app, content):
    app, service, parent = unit_app
    source = parent / '01_einstieg/ab.qmd'
    source.write_text(content)
    target = parent / '02_uebung/ab.qmd'
    target.unlink()
    before = (source.parent / FILENAME).read_bytes()
    response = app.test_client().post('/api/file/move', json={
        'path': service.config.relative(source), 'destination': service.config.relative(target.parent)})
    assert response.status_code == 400, response.json
    assert 'relative Ressourcen' in response.json['error']['message']
    assert source.read_text() == content and not target.exists()
    assert (source.parent / FILENAME).read_bytes() == before


@pytest.mark.parametrize('content', [
    '[Quelle](https://example.org/bild.svg)', '![](https://example.org/bild.svg)',
    '[Abschnitt](#aufgabe)', '![](/assets/bild.svg)',
])
def test_move_allows_location_independent_links(unit_app, content):
    app, service, parent = unit_app
    source = parent / '01_einstieg/ab.qmd'
    source.write_text(content)
    target = parent / '02_uebung/ab.qmd'
    target.unlink()
    response = app.test_client().post('/api/file/move', json={
        'path': service.config.relative(source), 'destination': service.config.relative(target.parent)})
    assert response.status_code == 200, response.json
    assert target.read_text() == content and not source.exists()


def test_calendar_unit_navigation_selects_target_before_showing_view(unit_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, folder = unit_app
    path = folder.relative_to(service.config.root).as_posix()
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until='networkidle')
        page.evaluate('''path => {
          window.unitNavigationFrames = [];
          const sectionVisible = () => {
            const section = document.querySelector('#viewSection-units');
            if (section && !section.hidden) window.unitNavigationFrames.push(
              section.querySelector('.unit-selected')?.dataset.unitPath || '');
            requestAnimationFrame(sectionVisible);
          };
          requestAnimationFrame(sectionVisible);
          document.dispatchEvent(new CustomEvent('material-ui:open-unit', {detail: path}));
        }''', path)
        card = page.locator(f'[data-unit-path="{path}"]')
        card.wait_for(state='visible')
        page.wait_for_function("document.activeElement?.getAttribute('aria-current') === 'location'")
        assert card.get_attribute('open') is not None
        assert card.locator(':scope > summary').get_attribute('aria-current') == 'location'
        assert page.evaluate('(path) => window.unitNavigationFrames.every(value => value === path)', path)
        # Following the link again from the already active view preserves selection and focus.
        page.evaluate("path => document.dispatchEvent(new CustomEvent('material-ui:open-unit', {detail: path}))", path)
        assert card.locator(':scope > summary').evaluate('(summary) => summary === document.activeElement')
        browser.close()


def test_completion_status_roundtrip_and_legacy_default(units):
    service, folder = units
    unit = service.read(folder)
    assert not unit['data'].get('fertig', False)
    for done in (True, False):
        unit['data']['fertig'] = done
        unit = service.save(unit['path'], unit['data'], unit['revision'])
        assert service.overview()['units'][0]['data']['fertig'] is done


@pytest.mark.parametrize('value', ['false', 'fertig', 1, None])
def test_completion_requires_boolean(units, value):
    service, folder = units
    unit = service.read(folder)
    unit['data']['fertig'] = value
    with pytest.raises(InvalidInput, match='fertig'):
        service.save(unit['path'], unit['data'], unit['revision'])
    assert not (folder / FILENAME).exists()


@pytest.mark.parametrize('quick_action', [False, True, 'worksheet'])
def test_completion_editor_badge_and_filter(unit_app, quick_action):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, folder = unit_app
    path = service.config.relative(folder)
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until='networkidle')
        page.locator('#viewButton-units').click()
        page.locator('[data-show-undated]').check()
        card = page.locator(f'[data-unit-path="{path}"]')
        expand_unit(card)
        card.evaluate('(card) => { window.completionCard = card; window.completionGroups = document.querySelector("[data-groups]"); }')
        overview_requests = []
        page.on('request', lambda request: overview_requests.append(request.url)
                if request.method == 'GET' and request.url.endswith('/api/units') else None)
        if quick_action == 'worksheet':
            for name in ('01_einstieg/ab.qmd', '02_uebung/ab.qmd'):
                card.locator(f'[data-worksheet-done="{name}"]').check()
                page.wait_for_function("() => !document.querySelector('[data-worksheet-done]:disabled')")
        elif quick_action:
            card.get_by_role('button', name='Als fertig markieren', exact=True).click()
        else:
            card.locator('[data-edit]').click()
            card.locator('[name=fertig]').check()
            card.get_by_role('button', name='Speichern', exact=True).click()
        page.wait_for_function("path => [...document.querySelectorAll('.unit-card')].find(c => c.dataset.unitPath === path)?.querySelector('.unit-completion').textContent === 'Fertig'", arg=path)
        if quick_action:
            assert overview_requests == [], 'Completion must use the save response without reloading all units'
            assert card.evaluate('(card) => card === window.completionCard'), 'Keep the existing card and its controls'
            assert page.evaluate('window.completionGroups === document.querySelector("[data-groups]")'), 'Keep the sidebar and calendar DOM'
        assert service.read(folder)['data']['fertig'] is True
        assert card.locator('[data-worksheet-done]').count() == 2
        assert all(toggle.is_checked() for toggle in card.locator('[data-worksheet-done]').all())
        assert card.locator('[data-unit-done]').is_disabled()
        open_unit_menu(page, '.unit-filters')
        page.locator('[data-completion-filter]').select_option('open')
        assert card.count() == 0
        page.locator('[data-completion-filter]').select_option('done')
        assert card.count() == 1
        page.reload(wait_until='networkidle')
        assert page.locator('[data-completion-filter]').input_value() == 'done'
        assert card.locator('.unit-completion').inner_text() == 'Fertig'
        browser.close()

def test_presentation_done_toggle_in_material_list(unit_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    app, service, folder = unit_app
    (folder / '01_einstieg/slide.qmd').write_text('---\ntitle: Folien\n---\nText\n')
    path = service.config.relative(folder)
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until='networkidle')
        page.locator('#viewButton-units').click()
        page.locator('[data-show-undated]').check()
        card = page.locator(f'[data-unit-path="{path}"]')
        expand_unit(card)
        deck = card.locator('[data-worksheet-done="01_einstieg/slide.qmd"]')
        assert deck.count() == 1 and not deck.is_checked()
        # Notizen bleiben Arbeitsblättern vorbehalten.
        assert deck.locator('xpath=ancestor::li').locator('[data-worksheet-note]').count() == 0
        for name in ('01_einstieg/ab.qmd', '02_uebung/ab.qmd'):
            card.locator(f'[data-worksheet-done="{name}"]').check()
            page.wait_for_function("() => !document.querySelector('[data-worksheet-done]:disabled')")
        assert card.locator('.unit-completion').inner_text() == 'In Bearbeitung'
        deck.check()
        page.wait_for_function("path => [...document.querySelectorAll('.unit-card')].find(c => c.dataset.unitPath === path)?.querySelector('.unit-completion').textContent === 'Fertig'", arg=path)
        assert service.read(folder)['data']['arbeitsblaetter_fertig']['01_einstieg/slide.qmd'] is True
        deck.uncheck()
        page.wait_for_function("path => [...document.querySelectorAll('.unit-card')].find(c => c.dataset.unitPath === path)?.querySelector('.unit-completion').textContent === 'In Bearbeitung'", arg=path)
        assert service.read(folder)['data']['fertig'] is False
        browser.close()


@pytest.mark.parametrize('kind', ['unterrichtsstunde', 'klausur'])
def test_unit_type_roundtrip(units, kind):
    service, folder = units
    unit = service.read(folder)
    unit['data']['typ'] = kind
    service.save(unit['path'], unit['data'], unit['revision'])
    assert service.read(folder)['data']['typ'] == kind


@pytest.mark.parametrize('kind', ['', None, [], 'unbekannt'])
def test_unit_type_validation(units, kind):
    service, folder = units
    unit = service.read(folder)
    unit['data']['typ'] = kind
    with pytest.raises(InvalidInput, match='Einheitentyp'):
        service.save(unit['path'], unit['data'], unit['revision'])


def test_browser_planning_sorts_exam_between_free_days(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    base = tmp_path / 'unterricht/mathematik/klasse-10/potenzen'
    for name in ['einstieg', 'klausur']:
        write_qmd(base / name / 'ab.qmd', '---\ntitle: Test\n---\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    runtime = app.extensions['material_runtime']
    service = UnitService(runtime.config, runtime.services.documents)
    for name, day in [('einstieg', '2026-11-10'), ('klausur', '2026-12-16')]:
        unit = service.read(base / name)
        unit['data'].update(thema='Potenzen', typ='klausur' if name == 'klausur' else 'unterrichtsstunde', einsatz=[{'datum': day}])
        service.save(unit['path'], unit['data'], unit['revision'])
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.clock.set_fixed_time('2026-11-07T12:00:00+01:00')
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.route('**/api/plugins/kalender/events?*', lambda route: route.fulfill(json={'events': [
            {'startDate': day, 'teaching': {'klasse': 'klasse-10'}, 'units': [], 'title': 'Mathematik', 'lessonId': day}
            for day in ['2026-11-17', '2026-12-22']]}))
        page.route('**/api/plugins/kalender/holidays?*', lambda route: route.fulfill(json={'days': []}))
        page.route('**/api/plugins/kalender/planning-markers', lambda route: route.fulfill(json={'rows': []}))
        page.goto(url, wait_until='networkidle')
        page.locator('#viewButton-units').click()
        page.locator('[data-class="klasse-10"]').click()
        page.wait_for_selector('.unit-plan-day')
        assert page.locator('[data-groups]').evaluate('host => [...host.querySelectorAll(".unit-card, :scope > .unit-plan-day")].map(n => n.dataset.sortDate)') == ['2026-11-10', '2026-11-17', '2026-12-16', '2026-12-22']
        exam = page.locator('.unit-exam')
        assert exam.locator('.unit-type').inner_text() == 'Klausur'
        expand_unit(exam)
        exam.locator('[data-edit]').click()
        assert exam.locator('[name=typ]').input_value() == 'klausur'
        browser.close()


@pytest.mark.parametrize('failed_endpoint', [None, 'events', 'holidays', 'planning-markers'])
def test_browser_planning_rebuilds_topics_and_survives_api_failures(failed_endpoint):
    from test_material_ui import sync_playwright
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    static = Path(__file__).parents[1] / 'material_ui/static'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.clock.set_fixed_time('2026-11-07T12:00:00+01:00')

        def serve(route):
            name = route.request.url.rsplit('/', 1)[-1]
            if name.endswith('.js'):
                route.fulfill(body=(static / name).read_text(), content_type='text/javascript')
            else:
                route.fulfill(body='<div id="host"></div>', content_type='text/html')

        page.route('http://planning.test/**', serve)
        page.goto('http://planning.test/')
        result = page.evaluate('''async failed => {
          const {renderUnitPlanning} = await import('/unit-planning.js');
          const host = document.querySelector('#host');
          const states = new Map();
          const watchDetails = (node, key, fallback) => {
            node.dataset.stateKey = key;
            node.open = states.get(key) ?? fallback;
            node.addEventListener('toggle', () => { if (node.isConnected) states.set(key, node.open); });
          };
          const setup = () => {
            host.innerHTML = `<details class="unit-topic" data-topic-key="potenzen" open><summary>Potenzen</summary>
              <details class="unit-card" data-unit-path="intro" data-sort-date="2026-11-10"><summary>Einführung</summary></details>
              <details class="unit-card" data-unit-path="exam" data-sort-date="2026-12-16"><summary>Klausur</summary></details>
              </details><details class="unit-topic" data-topic-key="other" open><summary>Anderes Thema</summary>
              <details class="unit-card" data-unit-path="other" data-sort-date="2026-11-24"><summary>Andere Einheit</summary></details></details>`;
          };
          let markers = [{datum: '2026-11-17', titel: 'Trenner', farbe: '#d99a36'}];
          const api = async url => {
            if (failed && url.includes('/' + failed)) throw Error('offline');
            return url.includes('/events?') ? {events: []} : url.includes('/holidays?') ? {days: []} : {rows: markers};
          };
          const options = {host, api, schoolClass: 'klasse-10', schoolYear: '2026/2027', schoolTerm: '', watchDetails, create: () => {}};
          setup(); await renderUnitPlanning(options);
          const dates = [...host.querySelectorAll('.unit-card')].map(n => n.dataset.sortDate);
          const examSection = host.querySelector('[data-unit-path="exam"]').parentElement;
          const key = examSection.dataset.stateKey;
          examSection.open = false;
          await new Promise(resolve => setTimeout(resolve, 30));
          await renderUnitPlanning(options);
          const closedOnRefresh = !host.querySelector('[data-unit-path="exam"]').parentElement.open;
          setup(); await renderUnitPlanning(options);
          const closedOnRebuild = !host.querySelector('[data-unit-path="exam"]').parentElement.open;
          // Remove the intervening unit and marker: both topic runs must coalesce.
          host.querySelector('[data-unit-path="other"]').parentElement.remove();
          markers = []; await renderUnitPlanning(options);
          return {dates, key, closedOnRefresh, closedOnRebuild,
            topics: host.querySelectorAll('.unit-topic').length,
            cards: host.querySelectorAll('.unit-card').length,
            status: host.querySelector('[role="status"]').textContent};
        }''', failed_endpoint)
        assert result['dates'] == ['2026-11-10', '2026-11-24', '2026-12-16']
        assert result['key'] == 'section:potenzen:exam'
        assert result['closedOnRefresh']
        assert result['closedOnRebuild']
        assert result['topics'] == 1
        assert result['cards'] == 2
        assert bool(result['status']) == bool(failed_endpoint)
        browser.close()


def test_planning_unlocks_next_year_only_after_final_lesson():
    import subprocess
    script = r'''
      import assert from 'node:assert/strict';
      import { readFileSync } from 'node:fs';
      const url = text => 'data:text/javascript;base64,' + Buffer.from(text).toString('base64');
      const utils = url(readFileSync('src/material_ui/static/ui-utils.js', 'utf8'));
      const source = readFileSync('src/material_ui/static/unit-planning.js', 'utf8').replace("'./ui-utils.js'", JSON.stringify(utils));
      const { teachingYearFinished } = await import(url(source));
      const lesson = (day, end, extra = {}) => ({ startDate: day, endDate: day,
        end: `${day}T${end}:00+02:00`, teaching: { klasse: 'klasse-10' }, ...extra });
      const lessons = [lesson('2027-07-02', '12:45'), lesson('2027-07-01', '13:30',
        { teaching: { klasse: 'klasse-05' } }), lesson('2027-09-01', '13:30')];
      const at = time => new Date(`2027-07-02T${time}:00+02:00`);
      assert.equal(teachingYearFinished(lessons, new Set(), at('12:44')), false);
      assert.equal(teachingYearFinished(lessons, new Set(), at('12:45')), false);
      assert.equal(teachingYearFinished(lessons, new Set(), at('12:46')), true);
      const later = [...lessons, lesson('2027-07-05', '13:30')];
      assert.equal(teachingYearFinished(later, new Set(), at('12:46')), false);
      assert.equal(teachingYearFinished(later, new Set(['2027-07-05']), at('12:46')), true);
      assert.equal(teachingYearFinished([...lessons, lesson('2027-07-05', '13:30', {cancelled: true})], new Set(), at('12:46')), true);
      assert.equal(teachingYearFinished([], new Set(), at('12:46')), false);
      assert.equal(teachingYearFinished([lesson('2027-07-02', '12:45', {end: 'invalid'})], new Set(), at('12:46')), false);
      // Q1 and another class finishing early must not hide remaining Q2 lessons.
      assert.equal(teachingYearFinished(lessons, new Set(), new Date('2027-02-01T12:00:00+01:00')), false);
    '''
    result = subprocess.run(['node', '--input-type=module', '-e', script],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_worksheet_completion_aggregates_and_reopens(units):
    service, folder = units
    paths = [folder / name for name in ('ab_bibi.qmd', 'ab_zwei.qmd', 'ab_zwei-loesung.qmd', 'slide.qmd')]
    for path in paths[1:]:
        path.write_text('---\ntitle: Test\n---\n', encoding='utf-8')
    service.documents.qmd_sources = lambda: paths
    tracked = {'ab_bibi.qmd', 'ab_zwei.qmd', 'slide.qmd'}
    unit = service.read(folder)
    unit['data']['arbeitsblaetter_fertig'] = {'ab_bibi.qmd': True}
    unit = service.save(unit['path'], unit['data'], unit['revision'])
    assert unit['data']['fertig'] is False
    unit['data']['arbeitsblaetter_fertig']['ab_zwei.qmd'] = True
    unit = service.save(unit['path'], unit['data'], unit['revision'])
    # Die offene Präsentation hält die Einheit in Bearbeitung; die Lösung zählt nicht mit.
    assert unit['data']['fertig'] is False
    assert set(unit['data']['arbeitsblaetter_fertig']) == tracked
    unit['data']['arbeitsblaetter_fertig']['slide.qmd'] = True
    unit = service.save(unit['path'], unit['data'], unit['revision'])
    assert unit['data']['fertig'] is True
    unit['data']['arbeitsblaetter_fertig']['slide.qmd'] = False
    unit = service.save(unit['path'], unit['data'], unit['revision'])
    assert unit['data']['fertig'] is False
    unit['data']['fertig'] = True
    unit = service.save(unit['path'], unit['data'], unit['revision'])
    assert all(unit['data']['arbeitsblaetter_fertig'].values())
    entries = service.overview()['units'][0]['materialEntries']
    assert {entry['path'] for entry in entries if entry['worksheet']} == {'ab_bibi.qmd', 'ab_zwei.qmd'}
    assert {entry['path'] for entry in entries if entry['presentation']} == {'slide.qmd'}
    assert all(entry['fertig'] for entry in entries if entry['worksheet'] or entry['presentation'])


def test_presentation_without_entry_inherits_unit_status(units):
    """Einheiten, die vor dem Präsentations-Schalter fertig waren, bleiben fertig."""
    service, folder = units
    paths = [folder / 'ab_bibi.qmd', folder / 'slide.qmd', folder / 'ab_neu.qmd']
    paths[1].write_text('---\ntitle: Folien\n---\n', encoding='utf-8')
    service.documents.qmd_sources = lambda: paths[:2]
    (folder / FILENAME).write_text(
        'titel: Test\nthema: Test\nkurzbeschreibung: \'\'\neinsatz: []\n'
        'fertig: true\narbeitsblaetter_fertig:\n  ab_bibi.qmd: true\n', encoding='utf-8')
    unit = service.read(folder)
    assert unit['data']['fertig'] is True
    entries = {entry['path']: entry for entry in service.overview()['units'][0]['materialEntries']}
    assert entries['slide.qmd']['presentation'] and entries['slide.qmd']['fertig'] is True
    # Speichern ohne Deck-Eintrag (z. B. aus dem Einheiteneditor) schreibt den geerbten Status fest.
    unit['data']['kurzbeschreibung'] = 'geändert'
    unit = service.save(unit['path'], unit['data'], unit['revision'])
    assert unit['data']['fertig'] is True
    assert unit['data']['arbeitsblaetter_fertig'] == {'ab_bibi.qmd': True, 'slide.qmd': True}
    # Das Deck lässt sich einzeln wieder öffnen …
    unit['data']['arbeitsblaetter_fertig']['slide.qmd'] = False
    unit = service.save(unit['path'], unit['data'], unit['revision'])
    assert unit['data']['fertig'] is False
    unit['data']['arbeitsblaetter_fertig']['slide.qmd'] = True
    unit = service.save(unit['path'], unit['data'], unit['revision'])
    # … und ein neues AB öffnet die Einheit weiterhin.
    paths[2].write_text('---\ntitle: Neu\n---\n', encoding='utf-8')
    service.documents.qmd_sources = lambda: paths
    assert service.read(folder)['data']['fertig'] is False


def test_presentation_only_unit_keeps_free_status_until_toggled(units):
    service, folder = units
    deck = folder / 'slide.qmd'
    deck.write_text('---\ntitle: Folien\n---\n', encoding='utf-8')
    service.documents.qmd_sources = lambda: [deck]
    unit = service.read(folder)
    assert not unit['data'].get('fertig', False)
    unit['data']['arbeitsblaetter_fertig'] = {'slide.qmd': True}
    unit = service.save(unit['path'], unit['data'], unit['revision'])
    assert unit['data']['fertig'] is True


@pytest.mark.parametrize('name, text, expected', [
    ('ab_x.qmd', '---\ntitle: AB\n---\n', 'worksheet'),
    ('slide.qmd', '---\ntitle: Deck\n---\n', 'presentation'),
    ('01 slide.qmd', '---\ntitle: Deck\n---\n', 'presentation'),
    ('slides.qmd', '---\ntitle: Deck\n---\n', 'presentation'),
    ('folien_einstieg.qmd', '---\ntitle: F\nkind: Praesentation\n---\n', 'presentation'),
    ('umlaut.qmd', '---\ntitle: U\nkind: Präsentation\n---\n', 'presentation'),
    ('slides_overview.qmd', '---\ntitle: Übersicht\n---\n', None),
    ('material.qmd', '---\ntitle: Sonst\n---\n', None),
    ('slide-loesung.qmd', '---\ntitle: Lösung\n---\n', None),
])
def test_completion_material_kinds(units, name, text, expected):
    service, folder = units
    (folder / name).write_text(text, encoding='utf-8')
    service.documents.qmd_sources = lambda: [folder / name]
    found = service.completion_materials(folder, [folder / name])
    assert (found[name]['kind'] if name in found else None) == expected


def test_new_presentation_in_finished_unit_counts_as_finished(units):
    """Festgeschriebene Asymmetrie: ein neues AB öffnet die Einheit, ein neues Deck nicht."""
    service, folder = units
    ab, deck = folder / 'ab_bibi.qmd', folder / 'slide.qmd'
    deck.write_text('---\ntitle: Folien\n---\n', encoding='utf-8')
    service.documents.qmd_sources = lambda: [ab]
    unit = service.read(folder)
    unit['data']['arbeitsblaetter_fertig'] = {'ab_bibi.qmd': True}
    unit = service.save(unit['path'], unit['data'], unit['revision'])
    assert unit['data']['fertig'] is True
    service.documents.qmd_sources = lambda: [ab, deck]
    reread = service.read(folder)
    assert reread['data']['fertig'] is True
    entries = {e['path']: e for e in service.overview()['units'][0]['materialEntries']}
    assert entries['slide.qmd']['presentation'] and entries['slide.qmd']['fertig'] is True


def test_presentation_key_follows_rename(units):
    service, folder = units
    ab, deck = folder / 'ab_bibi.qmd', folder / 'slide.qmd'
    deck.write_text('---\ntitle: Folien\n---\n', encoding='utf-8')
    service.documents.qmd_sources = lambda: sorted(folder.glob('*.qmd'))
    unit = service.read(folder)
    unit['data']['arbeitsblaetter_fertig'] = {'ab_bibi.qmd': True, 'slide.qmd': False}
    unit = service.save(unit['path'], unit['data'], unit['revision'])
    assert unit['data']['fertig'] is False
    service.rename_material(deck, folder / 'slides.qmd')
    states = service.read(folder)['data']['arbeitsblaetter_fertig']
    assert states == {'ab_bibi.qmd': True, 'slides.qmd': False}


@pytest.mark.parametrize('states', [[], {'ab_bibi.qmd': 'true'}, {'ab_bibi.qmd': 1}])
def test_worksheet_completion_validates_states(units, states):
    service, folder = units
    unit = service.read(folder)
    unit['data']['arbeitsblaetter_fertig'] = states
    with pytest.raises(InvalidInput, match='arbeitsblaetter_fertig'):
        service.save(unit['path'], unit['data'], unit['revision'])


def write_summary(folder, thema):
    from io import StringIO
    from ruamel.yaml import YAML
    summary = {'titel': folder.name, 'thema': thema, 'kurzbeschreibung': '', 'einsatz': []}
    stream = StringIO()
    YAML().dump(summary, stream)
    (folder / FILENAME).write_text(stream.getvalue(), encoding='utf-8')


def read_summary_thema(folder):
    from ruamel.yaml import YAML
    return YAML(typ='safe').load((folder / FILENAME).read_text(encoding='utf-8'))['thema']


def test_delete_theme_merges_all_matching_summaries(units):
    service, folder = units
    write_summary(folder, 'Multiplikation')
    second = folder.parent.parent / 'division' / 'schriftlich'
    second.mkdir(parents=True)
    (second / 'ab_div.qmd').write_text('---\ntitle: Division\n---\n', encoding='utf-8')
    write_summary(second, 'multiplikation')
    other = folder.parent.parent / 'subtraktion' / 'zahlen'
    other.mkdir(parents=True)
    (other / 'ab_sub.qmd').write_text('---\ntitle: Subtraktion\n---\n', encoding='utf-8')
    write_summary(other, 'Subtraktion')
    service.documents.qmd_sources = lambda: [folder / 'ab_bibi.qmd', second / 'ab_div.qmd', other / 'ab_sub.qmd']

    result = service.delete_theme({'fach': 'mathematik', 'klasse': 'klasse-05',
                                   'thema': 'Multiplikation', 'ersatz': 'Grundrechenarten'})

    root = service.config.root
    assert sorted(result['updated']) == [folder.relative_to(root).as_posix(), second.relative_to(root).as_posix()]
    assert read_summary_thema(folder) == read_summary_thema(second) == 'Grundrechenarten'
    assert read_summary_thema(other) == 'Subtraktion'
    overview = service.overview()
    assert all(unit['data']['thema'] != 'Multiplikation' for unit in overview['units'])


def test_delete_theme_reports_folders_deriving_their_theme(units):
    service, folder = units  # Fixture-Ordner ohne einheit.yaml, Thema aus Pfad: Arithmetik
    planned = folder.parent.parent / 'zahlen' / 'kreis'
    planned.mkdir(parents=True)
    (planned / 'ab_z.qmd').write_text('---\ntitle: Z\n---\n', encoding='utf-8')
    write_summary(planned, 'Arithmetik')
    service.documents.qmd_sources = lambda: [folder / 'ab_bibi.qmd', planned / 'ab_z.qmd']

    with pytest.raises(InvalidInput, match=folder.relative_to(service.config.root).as_posix()):
        service.delete_theme({'fach': 'mathematik', 'klasse': '05',
                              'thema': 'Arithmetik', 'ersatz': 'Zahlen'})
    assert read_summary_thema(planned) == 'Arithmetik'


def test_delete_theme_rejects_unknown_and_equal_replacement(units):
    service, folder = units
    write_summary(folder, 'Multiplikation')
    payload = {'fach': 'mathematik', 'klasse': '05', 'thema': 'Multiplikation', 'ersatz': 'Zahlen'}
    with pytest.raises(InvalidInput, match='Ersatzthema'):
        service.delete_theme({**payload, 'ersatz': 'Multiplikation'})
    with pytest.raises(InvalidInput, match='Keine Einheiten'):
        service.delete_theme({**payload, 'thema': 'Geometrie'})
    with pytest.raises(InvalidInput, match='Klassenordner'):
        service.delete_theme({**payload, 'klasse': '07'})
    assert read_summary_thema(folder) == 'Multiplikation'


def test_delete_theme_rolls_back_when_summary_changes_in_between(units, monkeypatch):
    import material_ui.units as units_module
    from material_core.filesystem import atomic_write_text as real_write
    service, folder = units
    write_summary(folder, 'Multiplikation')
    second = folder.parent.parent / 'division' / 'schriftlich'
    second.mkdir(parents=True)
    (second / 'ab_div.qmd').write_text('---\ntitle: Division\n---\n', encoding='utf-8')
    write_summary(second, 'Multiplikation')
    service.documents.qmd_sources = lambda: [folder / 'ab_bibi.qmd', second / 'ab_div.qmd']
    calls = []
    def fake_write(path, text, *, overwrite=True, before_replace=None, mode=None):
        calls.append(Path(path))
        if len(calls) == 2:
            (second / FILENAME).write_text('titel: Extern geaendert\n', encoding='utf-8')
        real_write(path, text, overwrite=overwrite, before_replace=before_replace, mode=mode)
    monkeypatch.setattr(units_module, 'atomic_write_text', fake_write)

    with pytest.raises(RevisionConflict, match='zwischenzeitlich'):
        service.delete_theme({'fach': 'mathematik', 'klasse': '05',
                              'thema': 'Multiplikation', 'ersatz': 'Grundrechenarten'})
    assert read_summary_thema(folder) == 'Multiplikation'
    assert 'Extern geaendert' in (second / FILENAME).read_text(encoding='utf-8')


@pytest.mark.parametrize('content,match', [
    ('titel: [kaputt\n', 'unlesbar'),
    ('titel: Zahlen\nthema: Multiplikation\nkurzbeschreibung: x\neinsatz: keine-liste\n', 'einsatz'),
])
def test_delete_theme_rejects_broken_summaries_with_actionable_errors(units, content, match):
    service, folder = units
    broken = folder.parent.parent / 'zahlen' / 'kreis'
    broken.mkdir(parents=True)
    (broken / 'ab_z.qmd').write_text('---\ntitle: Z\n---\n', encoding='utf-8')
    (broken / FILENAME).write_text(content, encoding='utf-8')
    write_summary(folder, 'Multiplikation')
    service.documents.qmd_sources = lambda: [folder / 'ab_bibi.qmd', broken / 'ab_z.qmd']

    with pytest.raises(InvalidInput, match=match):
        service.delete_theme({'fach': 'mathematik', 'klasse': '05',
                              'thema': 'Multiplikation', 'ersatz': 'Zahlen'})
    assert read_summary_thema(folder) == 'Multiplikation'


def test_theme_dropdown_precedes_title_and_theme_delete(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    from io import StringIO
    from ruamel.yaml import YAML
    potenzen = tmp_path / 'unterricht/mathematik/klasse-05/potenzen/einfuehrung'
    potenzen.mkdir(parents=True)
    path = potenzen.relative_to(tmp_path).as_posix()
    (potenzen / 'ab_potenzen.qmd').write_text('---\ntitle: Potenzen einfuehren\n---\n', encoding='utf-8')
    zahlen = tmp_path / 'unterricht/mathematik/klasse-05/zahlen/zahlengerade'
    zahlen.mkdir(parents=True)
    for folder, thema in [(potenzen, 'Potenzen'), (zahlen, 'Zahlen')]:
        summary = {'titel': folder.name, 'thema': thema, 'kurzbeschreibung': '', 'einsatz': [{'datum': '2026-11-02'}]}
        stream = StringIO()
        YAML().dump(summary, stream)
        (folder / FILENAME).write_text(stream.getvalue(), encoding='utf-8')
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.on('dialog', lambda dialog: dialog.accept())
            page.goto(url, wait_until='networkidle')
            page.locator('#viewButton-units').click()
            page.locator('[data-class="klasse-05"]').click()
            card = page.locator('[data-unit-path="unterricht/mathematik/klasse-05/potenzen/einfuehrung"]')
            card.wait_for(state='visible')
            expand_unit(card)
            card.locator('[data-edit]').click()
            editor = card.locator('[data-editor] form')
            editor.locator('[name=thema]').wait_for(state='visible')
            # Thema steht vor dem Titel; beide Themen der Jahrgangsstufe stehen zur Wahl.
            assert editor.evaluate('''form => {
              const thema = form.querySelector('[name=thema]');
              const titel = form.querySelector('[name=titel]');
              return thema && titel && (thema.compareDocumentPosition(titel) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
            }''')
            options = editor.locator('[name=thema] option').all_inner_texts()
            assert 'Potenzen' in options and 'Zahlen' in options and '+ Neues Thema…' in options
            editor.locator('[name=thema]').select_option(label='+ Neues Thema…')
            editor.locator('[name=thema-new]').fill('Grundrechenarten')
            with page.expect_response(lambda response: response.url.endswith('/api/units')) as saved:
                editor.locator('[type=submit]').click()
            assert saved.value.status == 200
            assert read_summary_thema(potenzen) == 'Grundrechenarten'
            # Nach dem Speichern laedt die Ansicht neu auf; Karte und Editor
            # sind danach bewusst erneut zu oeffnen. Die Wartefunktion greift
            # erst, wenn der wieder aufgebaute Editor leer ist.
            page.wait_for_function(
                f"() => {{ const editor = document.querySelector(`[data-unit-path='{path}'] [data-editor]`); return editor && editor.childElementCount === 0; }}")
            expand_unit(card)
            card.locator('[data-edit]').click()
            editor.locator('[data-theme-delete]').wait_for(state='visible')
            editor.locator('[data-theme-delete]').click()
            dialog = page.locator('.unit-theme-delete-form')
            dialog.locator('[name=thema]').wait_for(state='visible')
            assert dialog.locator('[name=fach]').input_value() == 'mathematik'
            assert dialog.locator('[name=klasse]').input_value() == 'klasse-05'
            assert dialog.locator('[data-theme-count]').inner_text().strip() == '1 Einheit gehört zu diesem Thema.'
            dialog.locator('[name=ersatz]').select_option('Zahlen')
            with page.expect_response(lambda response: response.url.endswith('/api/units/theme-delete')) as deleted:
                dialog.locator('[type=submit]').click()
            assert deleted.value.status == 200
            result = deleted.value.json()
            assert result['updated'] == ['unterricht/mathematik/klasse-05/potenzen/einfuehrung']
            assert result['ersatz'] == 'Zahlen'
            assert read_summary_thema(potenzen) == read_summary_thema(zahlen) == 'Zahlen'
            card.wait_for(state='visible')
            page.wait_for_function("document.querySelector('[data-status]')?.textContent.includes('jetzt zu')")
            assert 'jetzt zu „Zahlen"' in page.locator('[data-status]').inner_text()
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def write_dated_summary(folder, thema, datum='2026-11-02'):
    from io import StringIO
    from ruamel.yaml import YAML
    summary = {'titel': folder.name, 'thema': thema, 'kurzbeschreibung': '', 'einsatz': [{'datum': datum}]}
    stream = StringIO()
    YAML().dump(summary, stream)
    (folder / FILENAME).write_text(stream.getvalue(), encoding='utf-8')


def test_theme_delete_route_roundtrip(tmp_path):
    from material_ui.app import create_app
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        client = app.test_client()
        payload = {'fach': 'mathematik', 'klasse': '05', 'datum': '2026-11-06'}
        created = client.post('/api/units/new', json={**payload, 'thema': 'Potenzen', 'titel': 'Eins'})
        other = client.post('/api/units/new', json={**payload, 'thema': 'Zahlen', 'titel': 'Zwei'})
        assert created.status_code == 201, created.get_json()
        assert other.status_code == 201, other.get_json()
        assert client.post('/api/units/theme-delete', json={}).status_code == 400

        response = client.post('/api/units/theme-delete', json={'fach': 'mathematik', 'klasse': '05',
                                                                 'thema': 'Potenzen', 'ersatz': 'Zahlen'})
        assert response.status_code == 200
        body = response.get_json()
        assert (body['removed'], body['ersatz']) == ('Potenzen', 'Zahlen')
        assert body['updated'] == [created.get_json()['path']]
        assert client.post('/api/units/theme-delete', json={'fach': 'mathematik', 'klasse': '05',
                                                            'thema': 'Potenzen', 'ersatz': 'Zahlen'}).status_code == 400
        units = {unit['path']: unit for unit in client.get('/api/units').get_json()['units']}
        assert units[created.get_json()['path']]['data']['thema'] == 'Zahlen'
    finally:
        app.extensions['material_runtime'].close()


def test_theme_delete_dialog_survives_api_error(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright
    from material_ui.app import create_app
    if sync_playwright is None:
        pytest.skip('Playwright fehlt')
    potenzen = tmp_path / 'unterricht/mathematik/klasse-05/potenzen/einfuehrung'
    potenzen.mkdir(parents=True)
    (potenzen / 'ab.qmd').write_text('---\ntitle: Einführung\n---\n', encoding='utf-8')
    write_dated_summary(potenzen, 'Potenzen')
    zahlen = tmp_path / 'unterricht/mathematik/klasse-05/zahlen/zahlengerade'
    zahlen.mkdir(parents=True)
    (zahlen / 'ab.qmd').write_text('---\ntitle: Gerade Zahlen\n---\n', encoding='utf-8')
    write_dated_summary(zahlen, 'Zahlen', '2026-11-03')
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.on('dialog', lambda dialog: dialog.accept())
            intercepted = {'count': 0}
            def block_once(route):
                if intercepted['count'] == 0:
                    intercepted['count'] += 1
                    route.fulfill(status=500, json={'error': {'message': 'Löschen testweise blockiert'}})
                else:
                    route.continue_()
            page.route('**/api/units/theme-delete', block_once)
            page.goto(url, wait_until='networkidle')
            page.locator('#viewButton-units').click()
            page.locator('[data-class="klasse-05"]').click()
            open_unit_menu(page, '[data-add-menu]')
            page.locator('[data-new-unit]').click()
            page.locator('.unit-create-form [data-theme-delete]').click()
            dialog = page.locator('.unit-theme-delete-form')
            dialog.locator('[name=thema]').wait_for(state='visible')
            dialog.locator('[name=thema]').select_option('Potenzen')
            dialog.locator('[name=ersatz]').select_option('Zahlen')
            dialog.locator('[type=submit]').click()

            # Ein Serverfehler sperrt den Dialog nicht: Meldung erscheint und ein
            # erneuter Versuch bleibt moeglich (Audit F01).
            dialog.locator('[role=status]').wait_for(state='visible')
            page.wait_for_function("document.querySelector('.unit-theme-delete-form [role=status]')?.textContent.includes('blockiert')")
            assert dialog.locator('[type=submit]').is_enabled()
            assert read_summary_thema(potenzen) == 'Potenzen'

            dialog.locator('[type=submit]').click()
            page.wait_for_function("document.querySelector('[data-status]')?.textContent.includes('jetzt zu')")
            assert read_summary_thema(potenzen) == 'Zahlen'
            browser.close()
    finally:
        app.extensions['material_runtime'].close()
