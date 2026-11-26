from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from material_core.designs import DESIGNS, template_slide_design
from material_core.metadata import read_metadata, set_template
from material_ui import app as material_app
from material_ui.slides import SlidesService
from test_material_ui import material_root, staged_pdf, write_pdf


@pytest.mark.parametrize('design', DESIGNS, ids=lambda design: design['id'])
def test_template_controls_slide_design(tmp_path, design):
    from excalideck.outline import parse_outline

    text = set_template('---\ntitle: Test\ndeck-design: retro\n---\n\n## Einstieg\n\nEine Idee\n',
                        f'src/quarto/templates/slide-{design["id"]}.typst', 'typst')
    assert read_metadata(text)['deck-design'] == design['id']
    assert template_slide_design(text) == (True, design)
    # Direct header edits cannot leave the deck on the wrong design.
    source = tmp_path / 'slide.qmd'
    source.write_text(text.replace(f'deck-design: {design["id"]}', 'deck-design: foerdermaterial'))
    assert parse_outline(source).design_id == design['id']
    plain = set_template(text, 'src/quarto/templates/exam-template.typst', 'typst')
    assert template_slide_design(plain) == (False, None)
    assert 'deck-design' not in read_metadata(plain)


def test_slides_require_template_even_when_old_deck_exists(material_root):
    source = material_root / 'notiz.md'
    source.write_text('---\ndeck-design: retro\n---\n\n## Folie\n')
    service = SlidesService(material_app.current_runtime().config)
    deck = service.deck_path(source)
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text('Alte Folien')
    client = material_app.create_app().test_client()
    assert not client.get('/api/document?path=notiz.md').json['hasSlides']
    assert client.post('/api/slides/ensure', json={'path': 'notiz.md'}).status_code == 400
    assert client.post('/api/slides/rebuild', json={'path': 'notiz.md'}).status_code == 400
    assert deck.read_text() == 'Alte Folien'


@pytest.mark.parametrize('extension', ['qmd', 'md'])
def test_render_rebuilds_matching_slides_and_preserves_backup(material_root, monkeypatch, extension):
    import material_ui.slides as slides_module

    source = material_root / f'folie.{extension}'
    source.write_text(set_template('## Einstieg\n\nFrage\n', 'src/quarto/templates/worksheet-retro.typst', 'typst'))
    runtime = material_app.current_runtime()
    renderer = runtime.services.render
    deck = runtime.services.slides.deck_path(source)
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text('Altes Deck mit Anmerkungen')
    calls = []

    def generate(source, output_path):
        calls.append(source)
        output_path.write_text('Neue Folien')

    def render(command, **kwargs):
        write_pdf(staged_pdf(command))
        return subprocess.CompletedProcess(command, 0, stdout='PDF fertig')

    monkeypatch.setattr(slides_module, 'generate_deck', generate)
    monkeypatch.setattr(renderer.builds, 'run_process', render)
    monkeypatch.setattr(renderer.builds, 'build_tikz_assets', lambda directory: None)
    renderer.worker(source)
    assert renderer.state_payload()['ok'] is True
    assert deck.read_text() == 'Neue Folien'
    assert calls == [source]
    assert next(deck.parent.glob(deck.name + '.bak-*')).read_text() == 'Altes Deck mit Anmerkungen'
    assert renderer.state_payload()['pdf'].endswith('.pdf')


def test_failed_slide_render_restores_existing_deck(material_root, monkeypatch):
    import material_ui.slides as slides_module

    source = material_root / 'slide.qmd'
    source.write_text(set_template('## Einstieg\n', 'src/quarto/templates/slide-template.typst', 'typst'))
    service = material_app.services().slides
    deck = service.deck_path(source)
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text('Anmerkungen')

    def fail(*args, **kwargs):
        raise ValueError('Modell nicht darstellbar')

    monkeypatch.setattr(slides_module, 'generate_deck', fail)
    with pytest.raises(ValueError, match='Modell nicht darstellbar'):
        service.rebuild(source)
    assert deck.read_text() == 'Anmerkungen'


@pytest.mark.parametrize('template, succeeds', [('worksheet-retro.typst', True), ('slide-retro.typst', False)])
@pytest.mark.parametrize('failure', ['structure', 'dependency'])
def test_pdf_survives_optional_worksheet_deck_failure(material_root, monkeypatch, template, succeeds, failure):
    from excalideck.generator import DeckDependencyError
    from excalideck.outline import parse_outline

    source = material_root / 'blatt.qmd'
    source.write_text(set_template(
        '## Aufgaben\n\n:::: {.columns}\n::: {.column}\n## Ziffernkarten\n\nText\n:::\n::::\n',
        f'src/quarto/templates/{template}', 'typst'))
    runtime = material_app.current_runtime()
    renderer = runtime.services.render

    def render(command, **kwargs):
        write_pdf(staged_pdf(command))
        return subprocess.CompletedProcess(command, 0, stdout='PDF fertig')

    def rebuild(path):
        if failure == 'dependency':
            raise DeckDependencyError('Excaligen fehlt.')
        parse_outline(path)
        pytest.fail('Die verschachtelte Überschrift muss der Folienparser ablehnen.')

    monkeypatch.setattr(renderer.builds, 'run_process', render)
    monkeypatch.setattr(renderer.builds, 'build_tikz_assets', lambda directory: None)
    monkeypatch.setattr(runtime.services.slides, 'rebuild', rebuild)
    renderer.worker(source)
    state = renderer.state_payload()
    reason = 'Excaligen fehlt' if failure == 'dependency' else 'Nicht abgeschlossene Spalten'
    assert state['ok'] is succeeds
    if succeeds:
        assert state['pdf'].endswith('.pdf')
        assert 'zusätzliche Folien konnten nicht erzeugt werden' in state['message']
        assert any(reason in warning for warning in state['detail']['warnings'])
    else:
        assert reason in state['message']


def test_render_plain_pdf_does_not_create_slides(material_root, monkeypatch):
    import material_ui.slides as slides_module

    source = material_root / 'blatt.qmd'
    source.write_text('---\nformat: pdf\ndeck-design: retro\n---\n\n## Einstieg\n')
    renderer = material_app.services().render

    def render(command, **kwargs):
        write_pdf(staged_pdf(command))
        return subprocess.CompletedProcess(command, 0, stdout='PDF fertig')

    def unexpected(*args, **kwargs):
        pytest.fail('Ein Dokument ohne Folien-Template darf kein Deck erzeugen.')

    monkeypatch.setattr(slides_module, 'generate_deck', unexpected)
    monkeypatch.setattr(renderer.builds, 'run_process', render)
    monkeypatch.setattr(renderer.builds, 'build_tikz_assets', lambda directory: None)
    renderer.worker(source)
    assert renderer.state_payload()['ok'] is True
    assert not material_app.services().slides.deck_path(source).exists()


def test_ensure_updates_design_and_keeps_unchanged_annotated_deck(material_root):
    from material_ui.slides import annotations_path

    source = material_root / 'slide.qmd'
    source.write_text(set_template('## Einstieg\n\nFrage\n', 'src/quarto/templates/slide-retro.typst', 'typst'))
    service = material_app.services().slides
    deck, generated = service.ensure(source)
    assert generated
    old = deck.read_bytes()
    sidecar = annotations_path(deck)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text('{"elements": [{"id": "alter-strich"}], "files": {}}')
    assert service.ensure(source) == (deck, False)
    assert deck.read_bytes() == old
    source.write_text(set_template(source.read_text(), 'src/quarto/templates/slide-foerdermaterial.typst', 'typst'))
    assert service.ensure(source) == (deck, True)
    assert deck.read_bytes() != old
    backup = next(deck.parent.glob(deck.name + '.bak-*'))
    assert backup.read_bytes() == old
    assert annotations_path(backup).read_text() == '{"elements": [{"id": "alter-strich"}], "files": {}}'
    # Anmerkungen ohne Folienbezug ueberleben den Rebuild unabhaengig vom Design.
    assert sidecar.read_text() == '{"elements": [{"id": "alter-strich"}], "files": {}}'
    assert service.ensure(source) == (deck, False)


def test_rebuild_publishes_only_after_generation_and_restores_annotations_on_failure(material_root, monkeypatch):
    import material_ui.slides as module

    source = material_root / 'slide.qmd'
    source.write_text(set_template('## Einstieg\n', 'src/quarto/templates/slide-template.typst', 'typst'))
    service = material_app.services().slides
    deck, _ = service.ensure(source)
    original = deck.read_bytes()
    sidecar = module.annotations_path(deck)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text('Anmerkungen')
    stamp = service.source_stamp(deck).read_bytes()

    def generate(source, output_path):
        assert deck.read_bytes() == original
        assert sidecar.read_text() == 'Anmerkungen'
        output_path.write_text('Neues Deck')

    write = module.atomic_write_text

    def fail_stamp(path, text):
        if path == service.source_stamp(deck):
            raise OSError('Speicher voll')
        write(path, text)

    monkeypatch.setattr(module, 'generate_deck', generate)
    monkeypatch.setattr(module, 'atomic_write_text', fail_stamp)
    with pytest.raises(OSError, match='Speicher voll'):
        service.rebuild(source)
    assert deck.read_bytes() == original
    assert sidecar.read_text() == 'Anmerkungen'
    assert service.source_stamp(deck).read_bytes() == stamp


def test_browser_reports_outdated_api_instead_of_hiding_slides_silently(material_root):
    from test_material_ui import LiveServer, free_port, sync_playwright

    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    source = material_root / 'slide.qmd'
    source.write_text(set_template('## Einstieg\n', 'src/quarto/templates/slide-foerdermaterial.typst', 'typst'))
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')

        def old_api(route):
            response = route.fetch()
            data = response.json()
            data.pop('hasSlides', None)
            route.fulfill(response=response, json=data)

        page.route('**/api/document?**', old_api)
        page.goto(url, wait_until='networkidle')
        page.wait_for_function("document.querySelector('#renderStatus').textContent.includes('Server ist veraltet')")
        assert 'Server neu starten' in page.locator('#renderStatus').inner_text()
        page.locator('#headerMenuToggle').click()
        assert page.locator('#restartServer').is_visible()
        browser.close()


def test_rebuilt_deck_carries_bound_annotations_onto_matching_slides(material_root):
    import json
    from material_ui.slides import annotations_path

    source = material_root / 'slide.qmd'
    source.write_text(set_template('## Einstieg\n\nFrage\n', 'src/quarto/templates/slide-template.typst', 'typst'))
    slides = material_app.services().slides
    deck, _ = slides.ensure(source)
    path = deck.relative_to(material_root).as_posix()
    client = material_app.create_app().test_client()
    old_revision = client.get('/api/deck', query_string={'path': path}).headers['X-Material-Revision']
    old_frame = next(element['id'] for element in json.loads(deck.read_text(encoding='utf-8'))['elements']
                     if element.get('type') == 'frame')
    # Nur den Folientext ändern, Titel und Position bleiben: der typische
    # Rebuild waehrend des Unterrichts.
    source.write_text(source.read_text().replace('Frage', 'Neue Frage'))
    slides.rebuild(source)
    new_frame = next(element['id'] for element in json.loads(deck.read_text(encoding='utf-8'))['elements']
                     if element.get('type') == 'frame')
    assert new_frame != old_frame
    bound = json.dumps({'elements': [
        {'id': 'folien-notiz', 'type': 'freedraw', 'frameId': old_frame,
         'customData': {'presenterAnnotation': True, 'annotationSlide': old_frame}}], 'files': {}})
    response = client.post('/api/deck/annotations/save', json={
        'path': path, 'scene': bound, 'revision': None, 'deckRevision': old_revision,
    })
    assert response.status_code == 200
    carried = json.loads(annotations_path(deck).read_text(encoding='utf-8'))['elements']
    assert carried[0]['frameId'] == new_frame
    assert carried[0]['customData']['annotationSlide'] == new_frame


def test_slide_rebuild_transfers_saved_annotations_to_matching_frames(material_root):
    import json
    from material_ui.slides import annotations_path

    source = material_root / 'slide.qmd'
    source.write_text(set_template('## Einstieg\n\nFrage\n', 'src/quarto/templates/slide-template.typst', 'typst'))
    slides = material_app.services().slides
    deck, _ = slides.ensure(source)
    old_scene = json.loads(deck.read_text(encoding='utf-8'))
    old_frame = next(element['id'] for element in old_scene['elements'] if element.get('type') == 'frame')
    # Gespeicherte Anmerkungen: eine auf der Folie, eine auf einer verschollenen
    # Folie, eine ohne Folienbezug.
    sidecar = annotations_path(deck)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({'type': 'excalidraw', 'elements': [
        {'id': 'folien-notiz', 'type': 'freedraw', 'frameId': old_frame,
         'customData': {'presenterAnnotation': True, 'annotationSlide': old_frame}},
        {'id': 'verwaiste-notiz', 'type': 'freedraw', 'frameId': 'verschwundene-folie',
         'customData': {'presenterAnnotation': True, 'annotationSlide': 'verschwundene-folie'}},
        {'id': 'lose-notiz', 'type': 'freedraw', 'frameId': None,
         'customData': {'presenterAnnotation': True}},
    ], 'files': {}}))
    source.write_text(source.read_text().replace('Frage', 'Neue Frage'))
    slides.rebuild(source)
    new_scene = json.loads(deck.read_text(encoding='utf-8'))
    new_frame = next(element['id'] for element in new_scene['elements'] if element.get('type') == 'frame')
    backup = next(deck.parent.glob(deck.name + '.bak-*'))
    archived = json.loads(annotations_path(backup).read_text(encoding='utf-8'))
    assert len(archived['elements']) == 3
    # Die Rebuild-Sicherung behaelt alles; das Sidecar traegt die Folien-Anmerkung
    # auf der neuen Frame-ID weiter, die verwaiste entfaellt, die lose bleibt.
    carried = json.loads(sidecar.read_text(encoding='utf-8'))['elements']
    assert carried == [
        {'id': 'folien-notiz', 'type': 'freedraw', 'frameId': new_frame,
         'customData': {'presenterAnnotation': True, 'annotationSlide': new_frame}},
        {'id': 'lose-notiz', 'type': 'freedraw', 'frameId': None,
         'customData': {'presenterAnnotation': True}},
    ]


def test_rebuilt_deck_carries_annotations_and_rejects_renamed_slides(material_root):
    import json
    from material_ui.slides import annotations_path

    source = material_root / 'slide.qmd'
    source.write_text(set_template('## Alte Folie\n\nText\n', 'src/quarto/templates/slide-template.typst', 'typst'))
    slides = material_app.services().slides
    deck, _ = slides.ensure(source)
    path = deck.relative_to(material_root).as_posix()
    client = material_app.create_app().test_client()
    old_revision = client.get('/api/deck', query_string={'path': path}).headers['X-Material-Revision']
    source.write_text(source.read_text().replace('Alte Folie', 'Neue Folie'))
    slides.rebuild(source)
    backup = next(deck.parent.glob(deck.name + '.bak-*'))
    old_frame = next(element['id'] for element in json.loads(backup.read_text(encoding='utf-8'))['elements']
                     if element.get('type') == 'frame')
    revision = client.get('/api/deck', query_string={'path': path}).headers['X-Material-Revision']
    assert revision != old_revision
    loose = json.dumps({'elements': [{'id': 'freie-notiz', 'type': 'freedraw'}], 'files': {}})
    bound = json.dumps({'elements': [
        {'id': 'folien-notiz', 'type': 'freedraw', 'frameId': old_frame,
         'customData': {'presenterAnnotation': True, 'annotationSlide': old_frame}}], 'files': {}})
    # Umbenannte Folie: Lose Anmerkungen wandern auf die neue Fassung und der
    # Client erhaelt die aktuelle Deck-Revision zurueck.
    carried_save = client.post('/api/deck/annotations/save', json={
        'path': path, 'scene': loose, 'revision': None, 'deckRevision': old_revision,
    })
    assert carried_save.status_code == 200
    assert carried_save.json['deckRevision'] == revision
    carried = json.loads(annotations_path(deck).read_text(encoding='utf-8'))['elements']
    assert carried == [{'id': 'freie-notiz', 'type': 'freedraw'}]
    sidecar_revision = client.get('/api/deck/annotations', query_string={'path': path}).headers['X-Material-Revision']
    # Anmerkungen auf der umbenannten Folie bleiben bewusst abgewiesen.
    conflict = client.post('/api/deck/annotations/save', json={
        'path': path, 'scene': bound, 'revision': sidecar_revision, 'deckRevision': old_revision,
    })
    assert conflict.status_code == 409
    assert conflict.json['error']['code'] == 'deck_changed'
    # Alte Clients ohne Deck-Revision dürfen den Schutz nicht umgehen.
    assert client.post('/api/deck/annotations/save', json={
        'path': path, 'scene': bound, 'revision': None,
    }).status_code == 409
    # Gegenwärtige Deck-Revision speichert wie zuvor ohne Abgleich.
    assert client.post('/api/deck/annotations/save', json={
        'path': path, 'scene': bound, 'revision': sidecar_revision, 'deckRevision': revision,
    }).status_code == 200


@pytest.mark.parametrize('nested', [False, True])
def test_ensure_rebuilds_when_embedded_image_changes(material_root, nested):
    source = material_root / 'slide.qmd'
    asset = material_root / 'bild.svg'
    asset.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="red"/></svg>')
    image = '![](bild.svg)\n'
    if nested:
        image = '::: {.columns}\n::: {.column}\n[Infobox]\n\n' + image + '\n[/Infobox]\n:::\n::: {.column}\nText\n:::\n:::\n'
    source.write_text(set_template('## Bild\n\n' + image, 'src/quarto/templates/slide-template.typst', 'typst'))
    slides = material_app.services().slides
    deck, _ = slides.ensure(source)
    original = deck.read_bytes()
    assert slides.ensure(source) == (deck, False)
    # Auch gleicher Dateiname, gleiche Länge und gleiche mtime müssen erkannt werden.
    import os
    stamp = asset.stat()
    asset.write_text(asset.read_text().replace('red', 'tan'))
    os.utime(asset, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert slides.ensure(source) == (deck, True)
    assert deck.read_bytes() != original
    assert slides.ensure(source) == (deck, False)
