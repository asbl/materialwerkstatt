import json
import threading
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse

import pymupdf
import pytest
from werkzeug.serving import make_server

from material_ui.app import create_app
from material_ui.config import AppConfig
from material_ui.runtime import RuntimeState
from material_ui.worksheet_routes import solution_key
from requirements import needs_present_app


@pytest.fixture
def worksheet_app(tmp_path):
    runtime = RuntimeState()
    app = create_app(runtime=runtime, config=AppConfig(tmp_path))
    app.testing = True
    for name in ('ab_test', 'ab_test-loesung', 'anders'):
        path = tmp_path / 'unterricht' / f'{name}.qmd'
        path.parent.mkdir(exist_ok=True)
        path.write_text('---\ntitle: Test\n---\n\n## Aufgabe\n\nBerechne $2+3$.\n')
        target = runtime.services.builds.pdf_candidates(path)[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        with pymupdf.open() as pdf:
            first = pdf.new_page(width=600, height=800)
            first.insert_text((50, 40), 'Arbeitsblatt Test', fontsize=10)
            first.insert_text((50, 70), 'Aufgabe: 2 + 3 = ?', fontsize=10)
            first.insert_text((50, 300), '1 · Erste Schritte', fontname='hebo', fontsize=16)
            first.insert_text((50, 330), 'Berechne die Summe und notiere den Weg.', fontsize=10)
            first.insert_text((50, 520), '2 · Eigene Strategie', fontname='hebo', fontsize=16)
            first.insert_text((50, 550), 'Erkläre deinen Rechenweg.', fontsize=10)
            pdf.new_page(width=600, height=800).insert_text((50, 70), 'Zweite Seite')
            pdf.save(target)
        builds = runtime.services.builds
        stat = target.stat()
        stamp = builds.render_stamp(path)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(json.dumps({'pdf': str(target.relative_to(tmp_path)), 'mtime_ns': stat.st_mtime_ns,
                                     'size': stat.st_size, 'signature': builds.render_signature(path, path.read_text())}))
    yield app, runtime, tmp_path
    runtime.close()


def test_solution_detection_and_manual_choice_persist(worksheet_app):
    app, runtime, root = worksheet_app
    client = app.test_client()
    assert solution_key('ab_test-loesung') == solution_key('ab_test')
    assert solution_key('ab_test-musterlösungen') == solution_key('ab_test')
    assert client.get('/api/worksheet?path=unterricht/ab_test.qmd').json['solution']['path'] == 'unterricht/ab_test-loesung.qmd'
    assert client.post('/api/worksheet/solution', json={'path': 'unterricht/ab_test.qmd', 'solution': 'unterricht/anders.qmd'}).status_code == 200
    result = client.get('/api/worksheet?path=unterricht/ab_test.qmd').json
    assert result['solution']['path'] == 'unterricht/anders.qmd'
    assert (root / 'daten/worksheet-solutions.json').exists()


def test_crop_canvas_preserves_work_and_is_saved_by_existing_deck_api(worksheet_app):
    app, runtime, root = worksheet_app
    client = app.test_client()
    page = client.get('/api/worksheet/page?path=unterricht/ab_test.qmd&page=1')
    assert page.status_code == 200 and page.data.startswith(b'\x89PNG')
    assert page.headers['X-PDF-Pages'] == '2'
    payload = {'path': 'unterricht/ab_test.qmd', 'page': 1, 'crop': [0, 0, .5, .25], 'pdfRevision': page.headers['X-PDF-Revision']}
    result = client.post('/api/worksheet/canvas', json=payload)
    assert result.status_code == 200, result.json
    path = result.json['path']
    assert path.startswith('archiv/besprechungen/')
    response = client.get('/api/deck', query_string={'path': path})
    scene = response.json
    image = next(el for el in scene['elements'] if el['type'] == 'image')
    assert image['customData']['crop'] == [0, 0, .5, .25]
    assert image['width'] / image['height'] == pytest.approx(1.5)
    assert image['frameId'] == next(el['id'] for el in scene['elements'] if el['type'] == 'frame')
    stroke = dict(image, id='handwriting', type='freedraw', points=[[0, 0], [30, 20]], pressures=[], simulatePressure=True)
    scene['elements'].append(stroke)
    saved = client.post('/api/deck/save', json={'path': path, 'scene': json.dumps(scene), 'revision': response.headers['X-Material-Revision']})
    assert saved.status_code == 200
    payload['page'] = 2
    assert client.post('/api/worksheet/canvas', json=payload).status_code == 200
    final = client.get('/api/deck', query_string={'path': path}).json
    assert len([el for el in final['elements'] if el['type'] == 'frame']) == 2
    assert any(el['id'] == 'handwriting' for el in final['elements'])
    assert len(final['files']) == 2
    assert client.get('/api/worksheet?path=unterricht/ab_test.qmd').json['canvas'] == path


def test_worksheet_tasks_endpoint_reports_detected_regions(worksheet_app):
    app, _, _ = worksheet_app
    client = app.test_client()
    result = client.get('/api/worksheet/tasks?path=unterricht/ab_test.qmd&page=1')
    assert result.status_code == 200
    payload = result.json
    assert [task['label'] for task in payload['tasks']] == ['1', '2']
    assert payload['revision']
    first = payload['tasks'][0]['rect']
    second = payload['tasks'][1]['rect']
    assert all(0 <= value <= 1 for region in (first, second) for value in region)
    assert first[1] < second[1] and first[3] <= second[1] + 0.02
    assert client.get('/api/worksheet/tasks?path=unterricht/ab_test.qmd&page=2').json['tasks'] == []
    assert client.get('/api/worksheet/tasks?path=unterricht/ab_test.qmd&page=9').status_code == 400
    assert client.get('/api/worksheet/tasks?path=unterricht/../bad.qmd').status_code == 400


@pytest.mark.parametrize('crop', [[0, 0, 0, 1], [-1, 0, 1, 1], [0, 0, 2, 1], ['x', 0, 1, 1], [True, 0, 1, 1]])
def test_invalid_crops_and_paths(worksheet_app, crop):
    app, _, root = worksheet_app
    client = app.test_client()
    page = client.get('/api/worksheet/page?path=unterricht/ab_test.qmd')
    result = client.post('/api/worksheet/canvas', json={'path': 'unterricht/ab_test.qmd', 'crop': crop, 'pdfRevision': page.headers['X-PDF-Revision']})
    assert result.status_code == 400
    assert client.get('/api/worksheet?path=../outside.qmd').status_code == 400
    assert client.get('/api/worksheet/page?path=unterricht/ab_test.qmd&page=3').status_code == 400
    assert not list(root.rglob('*.excalidraw'))


def test_changed_pdf_rejected(worksheet_app):
    app, _, _ = worksheet_app
    result = app.test_client().post('/api/worksheet/canvas', json={'path': 'unterricht/ab_test.qmd', 'pdfRevision': 'outdated'})
    assert result.status_code == 400


@contextmanager
def live(app):
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_browser_discussion_actions_create_resume_and_keep_previous(worksheet_app):
    from playwright.sync_api import sync_playwright, expect
    app, _, root = worksheet_app
    owner = 'unterricht/ab_test.qmd'
    client = app.test_client()
    with live(app) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1500, 'height': 1000})
        # This test exercises the toolbar and storage; the drawing app has separate tests.
        page.route('**/present/?*', lambda route: route.fulfill(content_type='text/html', body='<p>Canvas</p>'))
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url + '/?path=' + owner)
        primary = page.get_by_role('button', name='Besprechen', exact=True)
        menu = page.locator('.discussion-menu')
        expect(primary).to_have_attribute('title', 'Erste Besprechung mit einer leeren Zeichenfläche starten')
        expect(menu).to_be_hidden()
        primary.click()
        expect(page.locator('#deckModal')).to_have_attribute('aria-hidden', 'false')
        first = client.get('/api/worksheet', query_string={'path': owner}).json['canvas']
        saved = (root / first).read_bytes()
        page.locator('#closeDeckModalButton').click()
        expect(menu).to_be_visible()
        expect(primary).to_have_attribute('title', 'Vorhandene Besprechung fortsetzen')
        # The menu belongs to Besprechen, before the independent note action.
        assert primary.evaluate("button => button.nextElementSibling.matches('.discussion-menu')")
        primary.click()
        expect(page.locator('#deckModal')).to_have_attribute('aria-hidden', 'false')
        assert parse_qs(urlparse(page.locator('#deckFrame').get_attribute('src')).query)['path'] == [first]
        assert len(client.get('/api/worksheet', query_string={'path': owner}).json['canvases']) == 1
        page.locator('#closeDeckModalButton').click()
        page.get_by_label('Weitere Besprechungsoptionen').click()
        expect(page.locator('#discussion-new-description')).to_contain_text('Vorhandene Besprechungen bleiben erhalten.')
        page.get_by_role('button', name='Weitere Besprechung anlegen', exact=True).click()
        expect(page.locator('#deckModal')).to_have_attribute('aria-hidden', 'false')
        parts = client.get('/api/worksheet', query_string={'path': owner}).json['canvases']
        assert len(parts) == 2
        assert (root / first).read_bytes() == saved
        page.locator('#closeDeckModalButton').click()
        expect(primary).to_have_attribute('title', 'Vorhandene Besprechung auswählen und fortsetzen')
        primary.click()
        expect(page.get_by_role('dialog').filter(has=page.locator('[data-parts]'))).to_be_visible()
        choices = page.locator('[data-parts] button')
        expect(choices).to_have_count(2)
        choices.first.click()
        expect(page.locator('#deckModal')).to_have_attribute('aria-hidden', 'false')
        page.locator('#closeDeckModalButton').click()
        page.locator('#folderEntries button[data-document="unterricht/anders.qmd"]').click()
        expect(primary).to_have_attribute('title', 'Erste Besprechung mit einer leeren Zeichenfläche starten')
        expect(menu).to_be_hidden()
        browser.close()


@needs_present_app
def test_browser_discussion_and_crop(worksheet_app):
    from playwright.sync_api import sync_playwright, expect
    app, _, root = worksheet_app
    with live(app) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1500, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url + '/?path=unterricht/ab_test.qmd')
        page.wait_for_function("document.querySelector('#pdfPreview').src.includes('/api/pdf')")
        page.get_by_role('button', name='Besprechen', exact=True).click()
        frame = page.frame_locator('#deckFrame')
        expect(frame.get_by_role('button', name='Aus AB einfügen', exact=True)).to_be_visible(timeout=20000)
        inner = page.locator('#deckFrame').element_handle().content_frame()
        inner.wait_for_function("!!window.__excalidraw")
        assert inner.evaluate("window.__excalidraw.getSceneElements().filter(e => e.type !== 'frame' && !e.customData?.slideBackground).length") == 0
        # A valid handwritten stroke before any PDF import must survive imports and reopening.
        inner.evaluate("""() => {
          const api = window.__excalidraw, f = api.getSceneElements()[0];
          api.updateScene({elements: [...api.getSceneElements(), {id:'handwritten', type:'freedraw', x:80,y:80,
            width:100,height:30,points:[[0,0],[50,20],[100,30]], pressures:[],simulatePressure:true,
            strokeWidth:2,strokeColor:'#e03131',opacity:100,angle:0,frameId:f.id,
            customData:{annotationSlide:f.id},version:1,versionNonce:1,isDeleted:false,groupIds:[]}]});
        }""")
        with page.expect_response(lambda r: '/api/deck/annotations/save' in r.url and r.status == 200):
            frame.get_by_title('Nur Anmerkungen separat speichern (Strg+S); das Deck bleibt unberührt', exact=True).click()
        for new_page in (False, True):
            frame.get_by_role('button', name='Aus AB einfügen', exact=True).click()
            dialog = frame.get_by_role('dialog', name='Aus AB einfügen')
            expect(dialog.get_by_role('button', name='Einfügen', exact=True)).to_be_enabled(timeout=20000)
            if new_page:
                dialog.get_by_role('button', name='Weiter', exact=True).click()
                expect(dialog.get_by_role('button', name='Einfügen', exact=True)).to_be_enabled()
                dialog.get_by_label('Einfügen in').select_option('new')
            else:
                bounds = dialog.locator('img').bounding_box()
                page.mouse.move(bounds['x'] + 10, bounds['y'] + 10)
                page.mouse.down()
                page.mouse.move(bounds['x'] + bounds['width'] / 2, bounds['y'] + 100)
                page.mouse.up()
                expect(dialog.locator('.deck-worksheet-selection')).to_be_visible()
            dialog.get_by_role('button', name='Einfügen', exact=True).click()
            expect(dialog).not_to_be_visible()
        expect(frame.locator('.deck-counter').first).to_have_text('2 / 2')
        assert inner.evaluate("window.__excalidraw.getSceneElements().some(e => e.id === 'handwritten' && !e.isDeleted)")
        # One undo removes the second import, not the handwriting or the first image.
        frame.get_by_title('Rückgängig (Strg+Z)', exact=True).click()
        inner.wait_for_function("window.__excalidraw.getSceneElements().filter(e => e.type === 'image' && !e.isDeleted).length === 1")
        frame.get_by_title('Wiederholen (Strg+Umschalt+Z)', exact=True).click()
        inner.wait_for_function("window.__excalidraw.getSceneElements().filter(e => e.type === 'image' && !e.isDeleted).length === 2")
        # Solutions enter the existing reveal/export mechanism automatically.
        frame.get_by_role('button', name='Aus AB einfügen', exact=True).click()
        dialog = frame.get_by_role('dialog', name='Aus AB einfügen')
        dialog.get_by_label('Quelle', exact=True).select_option('unterricht/ab_test-loesung.qmd')
        expect(dialog.get_by_role('button', name='Einfügen', exact=True)).to_be_enabled(timeout=20000)
        dialog.get_by_role('button', name='Einfügen', exact=True).click()
        expect(dialog).not_to_be_visible()
        assert inner.evaluate("window.__excalidraw.getSceneElements().some(e => e.customData?.solutionStep === 1)")
        frame.get_by_role('button', name='Lösungsschritte', exact=True).click()
        frame.get_by_role('button', name='Alle Lösungen verdecken', exact=True).click()
        inner.wait_for_function("window.__excalidrawNative.getSceneElements().find(e => e.customData?.solutionStep === 1)?.opacity === 0")
        with page.expect_response(lambda r: '/api/deck/annotations/save' in r.url and r.status == 200):
            frame.get_by_title('Nur Anmerkungen separat speichern (Strg+S); das Deck bleibt unberührt', exact=True).click()
        # Reload the same saved canvas (no server-side import or latest-part lookup).
        inner.goto(inner.url)
        expect(frame.get_by_role('button', name='Aus AB einfügen', exact=True)).to_be_visible(timeout=20000)
        inner.wait_for_function("window.__excalidraw.getSceneElements().filter(e => e.type === 'image').length === 3")
        assert inner.evaluate("window.__excalidraw.getSceneElements().find(e => e.id === 'handwritten').points.length") == 3
        assert not errors
        browser.close()


        assert not errors
        browser.close()


@needs_present_app
def test_browser_chips_zoom_and_pan_in_worksheet_dialog(worksheet_app):
    from playwright.sync_api import sync_playwright, expect
    app, _, _ = worksheet_app
    with live(app) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url + '/?path=unterricht/ab_test.qmd')
        page.wait_for_function("document.querySelector('#pdfPreview').src.includes('/api/pdf')")
        page.get_by_role('button', name='Besprechen', exact=True).click()
        frame = page.frame_locator('#deckFrame')
        frame.get_by_role('button', name='Aus AB einfügen', exact=True).click(timeout=20000)
        dialog = frame.get_by_role('dialog', name='Aus AB einfügen')
        expect(dialog.get_by_role('button', name='Einfügen', exact=True)).to_be_enabled(timeout=20000)

        # Erkannte Aufgaben erscheinen als Chips; ein Klick setzt den Rahmen.
        chips = dialog.get_by_role('group', name='Aufgabe wählen').get_by_role('button')
        expect(chips).to_have_count(2)
        first_chip, second_chip = chips.nth(0), chips.nth(1)
        first_chip.hover()
        expect(dialog.locator('.deck-worksheet-region')).to_be_visible()
        second_chip.click()
        selection = dialog.locator('.deck-worksheet-selection')
        expect(selection).to_be_visible()
        expect(second_chip).to_have_attribute('aria-pressed', 'true')
        expect(first_chip).to_have_attribute('aria-pressed', 'false')

        # Mausrad zoomt die Vorschau um den Zeiger; die Prozentanzeige folgt.
        zoom_label = dialog.locator('.deck-worksheet-zoom [aria-live="polite"]')
        expect(zoom_label).to_have_text('100 %')
        stage = dialog.locator('.deck-worksheet-stage')
        box = stage.bounding_box()
        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        page.mouse.wheel(0, -300)
        expect(zoom_label).not_to_have_text('100 %')

        # Verschieben-Modus schwenkt die Ansicht statt einen Rahmen zu ziehen.
        canvas = dialog.locator('.deck-worksheet-canvas')
        before = canvas.evaluate('element => element.style.transform')
        dialog.get_by_role('button', name='Verschieben', exact=True).click()
        expect(dialog.locator('.deck-worksheet-pan')).to_have_attribute('aria-pressed', 'true')
        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        page.mouse.down()
        page.mouse.move(box['x'] + box['width'] / 2 - 150, box['y'] + box['height'] / 2 + 60, steps=6)
        page.mouse.up()
        after = canvas.evaluate('element => element.style.transform')
        assert after != before
        dialog.get_by_role('button', name='Verschieben', exact=True).click()

        # Zwei Finger zoomen gleichzeitig und nehmen den gewählten Rahmen weg.
        inner = page.locator('#deckFrame').element_handle().content_frame()

        def pointer(action, pointer_id, x, y):
            inner.evaluate("""([action, id, x, y]) => {
              const element = document.querySelector('.deck-worksheet-stage');
              element.dispatchEvent(new PointerEvent(`pointer${action}`, {
                pointerId: id, pointerType: 'touch', button: 0, buttons: 1,
                clientX: x, clientY: y, bubbles: true, cancelable: true,
              }));
            }""", [action, pointer_id, x, y])

        zoom_before_pinch = zoom_label.inner_text()
        base = inner.evaluate("""() => {
          const rect = document.querySelector('.deck-worksheet-stage').getBoundingClientRect();
          return [rect.left, rect.top, rect.width, rect.height];
        }""")
        rect_x, rect_y, rect_w, rect_h = base
        center_x, center_y = rect_x + rect_w / 2, rect_y + rect_h / 2
        pointer('down', 1, center_x - 60, center_y)
        pointer('down', 2, center_x + 60, center_y)
        pointer('move', 1, center_x - 150, center_y - 40)
        pointer('move', 2, center_x + 150, center_y - 40)
        expect(zoom_label).not_to_have_text(zoom_before_pinch)
        pointer('up', 1, center_x - 150, center_y - 40)
        pointer('up', 2, center_x + 150, center_y - 40)
        expect(selection).to_have_count(0)  # Pinch verwirft den gesetzten Rahmen

        # Zurück auf Fit bleibt der klassische Rahmen ziehbar und einfügbar.
        dialog.get_by_role('button', name='Fit', exact=True).click()
        expect(zoom_label).to_have_text('100 %')
        fresh = canvas.bounding_box()
        page.mouse.move(fresh['x'] + 20, fresh['y'] + 20)
        page.mouse.down()
        page.mouse.move(fresh['x'] + fresh['width'] * 0.5, fresh['y'] + fresh['height'] * 0.3, steps=4)
        page.mouse.up()
        expect(selection).to_be_visible()
        dialog.get_by_role('button', name='Einfügen', exact=True).click()
        expect(dialog).not_to_be_visible()
        inner.wait_for_function("window.__excalidraw.getSceneElements().some(element => element.type === 'image' && !element.isDeleted)")
        assert not errors
        browser.close()


def test_stale_pdf_and_unknown_stamp_are_rejected(worksheet_app):
    app, runtime, root = worksheet_app
    client = app.test_client()
    owner = 'unterricht/ab_test.qmd'
    response = client.get('/api/worksheet/page', query_string={'path': owner})
    (root / owner).write_text((root / owner).read_text() + '\nNeue Aufgabe!\n')
    assert client.get('/api/worksheet/page', query_string={'path': owner}).status_code == 400
    assert client.post('/api/worksheet/canvas', json={'path': owner, 'pdfRevision': response.headers['X-PDF-Revision']}).status_code == 400
    solution = root / 'unterricht/ab_test-loesung.qmd'
    runtime.services.builds.render_stamp(solution).unlink()
    result = client.get('/api/worksheet', query_string={'path': owner}).json
    assert result['solution']['pdfCurrent'] is None


def create_canvas(client, path='unterricht/ab_test.qmd'):
    page = client.get('/api/worksheet/page', query_string={'path': path})
    result = client.post('/api/worksheet/canvas', json={'path': path, 'pdfRevision': page.headers['X-PDF-Revision']})
    assert result.status_code == 200, result.json
    return result.json['path']


def test_clean_preserves_canvas_history_and_sidecar_and_migrates_legacy(worksheet_app, monkeypatch):
    import project_tasks
    from material_ui.slides import annotations_path
    app, runtime, root = worksheet_app
    client = app.test_client()
    canvas = root / create_canvas(client)
    original = canvas.read_bytes()
    annotations_path(canvas).parent.mkdir()
    annotations_path(canvas).write_text(json.dumps({'elements': [{'id': 'stroke'}], 'files': {}}))
    runtime.documents.archive(canvas, {'text': original.decode(), 'revision': 'before'})
    # Simulate the previous feature version before a clean, without opening it.
    legacy = root / 'build/artefakte/unterricht/ab_test.qmd'
    legacy.parent.mkdir(parents=True, exist_ok=True)
    canvas.parent.rename(legacy)
    (root / '_quarto.yml').write_text('project:\n  render:\n    - /unterricht/*.qmd\n')
    monkeypatch.setattr(project_tasks, 'ROOT_DIR', root)
    project_tasks.clean.body(None)
    # build/ selbst darf als leerer Ordner bleiben; Scratch-Ausgaben bleiben ohne --artefakte erhalten.
    assert not any(path.is_file() for path in (root / 'build').rglob('*'))
    assert canvas.read_bytes() == original
    assert json.loads(annotations_path(canvas).read_text())['elements'][0]['id'] == 'stroke'
    assert runtime.documents.history(canvas)
    assert client.get('/api/worksheet?path=unterricht/ab_test.qmd').json['canvas'] == str(canvas.relative_to(root))


def test_rename_keeps_canvas_sidecar_history_and_solution_links(worksheet_app):
    from material_ui.slides import annotations_path
    app, runtime, root = worksheet_app
    client = app.test_client()
    old = root / create_canvas(client)
    annotations_path(old).parent.mkdir()
    annotations_path(old).write_text('manual notes')
    runtime.documents.archive(old, {'text': old.read_text(), 'revision': 'before'})
    client.post('/api/worksheet/solution', json={'path': 'unterricht/ab_test.qmd', 'solution': 'unterricht/anders.qmd'})
    result = client.post('/api/file/rename', json={'path': 'unterricht/ab_test.qmd', 'name': 'ab_neu.qmd'})
    assert result.status_code == 200, result.json
    result = client.get('/api/worksheet?path=unterricht/ab_neu.qmd').json
    new = root / result['canvas']
    assert new.exists() and not old.exists()
    assert annotations_path(new).read_text() == 'manual notes'
    assert runtime.documents.history(new)
    assert result['solution']['path'] == 'unterricht/anders.qmd'
    assert client.post('/api/file/rename', json={'path': 'unterricht/anders.qmd', 'name': 'antwort.qmd'}).status_code == 200
    assert client.get('/api/worksheet?path=unterricht/ab_neu.qmd').json['solution']['path'] == 'unterricht/antwort.qmd'


def test_folder_rename_and_failed_rename_keep_associations(worksheet_app, monkeypatch):
    app, runtime, root = worksheet_app
    client = app.test_client()
    old = root / create_canvas(client)
    client.post('/api/worksheet/solution', json={'path': 'unterricht/ab_test.qmd', 'solution': 'unterricht/anders.qmd'})
    result = runtime.services.folders.rename('unterricht', 'material')
    assert result == root / 'material'
    info = client.get('/api/worksheet?path=material/ab_test.qmd').json
    assert info['canvas'] and info['solution']['path'] == 'material/anders.qmd'
    current = root / info['canvas']
    assert current.exists() and not old.exists()
    original_rename = type(current).rename
    def fail_source(path, target):
        if path == root / 'material/ab_test.qmd':
            raise OSError('simulated rename failure')
        return original_rename(path, target)
    monkeypatch.setattr(type(current), 'rename', fail_source)
    with pytest.raises(OSError):
        with runtime.services.worksheets.renaming(root / 'material/ab_test.qmd', root / 'material/new.qmd'):
            (root / 'material/ab_test.qmd').rename(root / 'material/new.qmd')
    assert current.exists()
    assert client.get('/api/worksheet?path=material/ab_test.qmd').json['solution']['path'] == 'material/anders.qmd'


@needs_present_app
def test_browser_rebuilds_stale_pdfs_before_showing_or_cropping(worksheet_app, monkeypatch):
    from playwright.sync_api import sync_playwright, expect
    app, runtime, root = worksheet_app
    builds = runtime.services.builds
    owner = root / 'unterricht/ab_test.qmd'
    solution = root / 'unterricht/ab_test-loesung.qmd'
    for source in (owner, solution):
        source.write_text(source.read_text() + '\nGeänderte Aufgabe!\n')
    rendered = []

    def render(source):
        rendered.append(source)
        identifier = runtime.jobs.create(str(source.relative_to(root)), 'render')
        target = builds.pdf_candidates(source)[0]
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((50, 70), 'Aktualisierte Aufgabe!')
            pdf.save(target)
        stat = target.stat()
        builds.render_stamp(source).write_text(json.dumps({
            'pdf': str(target.relative_to(root)), 'mtime_ns': stat.st_mtime_ns, 'size': stat.st_size,
            'signature': builds.render_signature(source, source.read_text())}))
        runtime.jobs.update(identifier, running=False, ok=True, status='succeeded')
        return identifier

    monkeypatch.setattr(runtime.services.render, 'start', render)
    with live(app) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1500, 'height': 1000})
        page.add_init_script("localStorage.setItem('material-ui:auto-render', 'false')")
        page.goto(url + '/?path=unterricht/ab_test.qmd')
        page.wait_for_function("document.querySelector('#pdfPreview').src.includes('/api/pdf')")
        page.get_by_role('button', name='Besprechen', exact=True).click()
        frame = page.frame_locator('#deckFrame')
        frame.get_by_role('button', name='Aus AB einfügen', exact=True).click(timeout=20000)
        expect(frame.get_by_role('dialog', name='Aus AB einfügen').get_by_role('button', name='Einfügen', exact=True)).to_be_enabled(timeout=20000)
        dialog = frame.get_by_role('dialog', name='Aus AB einfügen')
        dialog.get_by_label('Quelle', exact=True).select_option('unterricht/ab_test-loesung.qmd')
        expect(dialog.get_by_role('button', name='Einfügen', exact=True)).to_be_enabled(timeout=20000)
        assert solution in rendered
        assert builds.pdf_is_current(solution) is True
        assert owner in rendered
        assert builds.pdf_is_current(owner) is True
        browser.close()


def test_migrated_legacy_cannot_be_saved_or_reimported_after_rename(worksheet_app):
    app, runtime, root = worksheet_app
    client = app.test_client()
    durable = root / create_canvas(client)
    legacy = root / 'build/artefakte/unterricht/ab_test.qmd/besprechung.excalidraw'
    legacy.parent.parent.mkdir(parents=True, exist_ok=True)
    durable.parent.rename(legacy.parent)
    original = legacy.read_text()
    result = client.get('/api/worksheet?path=unterricht/ab_test.qmd')
    assert result.status_code == 200 and durable.is_file()
    response = client.post('/api/deck/save', json={'path': str(legacy.relative_to(root)), 'scene': original})
    assert response.status_code == 409
    assert durable.read_text() == original
    assert client.post('/api/file/rename', json={'path': 'unterricht/ab_test.qmd', 'name': 'ab_neu.qmd'}).status_code == 200
    runtime.services.worksheets.migrate_all()
    assert not durable.exists()
    assert client.get('/api/worksheet?path=unterricht/ab_neu.qmd').json['canvas']


def test_clear_solution_and_restore_automatic_assignment(worksheet_app):
    app, _, _ = worksheet_app
    client = app.test_client()
    path = 'unterricht/ab_test.qmd'
    assert client.post('/api/worksheet/solution', json={'path': path, 'solution': ''}).status_code == 200
    cleared = client.get('/api/worksheet', query_string={'path': path}).json
    assert cleared['solution'] is None and cleared['solutionMode'] == 'none'
    assert client.post('/api/file/rename', json={'path': path, 'name': 'ab_neu.qmd'}).status_code == 200
    assert client.get('/api/worksheet?path=unterricht/ab_neu.qmd').json['solution'] is None
    client.post('/api/file/rename', json={'path': 'unterricht/ab_neu.qmd', 'name': 'ab_test.qmd'})
    assert client.post('/api/worksheet/solution', json={'path': path, 'mode': 'auto'}).status_code == 200
    assert client.get('/api/worksheet', query_string={'path': path}).json['solution']['path'] == 'unterricht/ab_test-loesung.qmd'


def test_images_are_reused_and_large_canvases_start_accessible_parts(worksheet_app, monkeypatch):
    from material_ui import worksheet_routes
    app, _, root = worksheet_app
    client = app.test_client()
    path = create_canvas(client)
    assert create_canvas(client) == path
    scene = json.loads((root / path).read_text())
    assert len(scene['files']) == 1
    assert len([el for el in scene['elements'] if el['type'] == 'frame']) == 2
    before = (root / path).read_bytes()
    monkeypatch.setattr(worksheet_routes, 'CANVAS_PART_BYTES', 1)
    second = create_canvas(client)
    assert second != path and (root / path).read_bytes() == before
    result = client.get('/api/worksheet?path=unterricht/ab_test.qmd').json
    assert result['canvas'] == second
    assert [part['path'] for part in result['canvases']] == [path, second]


def test_rename_migrates_only_affected_sources(worksheet_app, monkeypatch):
    app, runtime, root = worksheet_app
    store = runtime.services.worksheets
    monkeypatch.setattr(store, 'migrate_all', lambda: pytest.fail('global migration during rename'))
    visited = []
    original = store.canvas
    def track(source, **options):
        visited.append(source)
        return original(source, **options)
    monkeypatch.setattr(store, 'canvas', track)
    assert app.test_client().post('/api/file/rename', json={'path': 'unterricht/ab_test.qmd', 'name': 'ab_neu.qmd'}).status_code == 200
    assert visited == [root / 'unterricht/ab_test.qmd']


def test_empty_discussions_and_fragments_do_not_mutate_saved_scene(worksheet_app):
    app, _, root = worksheet_app
    client = app.test_client()
    first = client.post('/api/worksheet/start', json={'path': 'unterricht/ab_test.qmd'}).json['path']
    second = client.post('/api/worksheet/start', json={'path': 'unterricht/ab_test.qmd'}).json['path']
    assert first != second
    original = (root / first).read_bytes()
    scene = json.loads(original)
    frame, = [e for e in scene['elements'] if e['type'] == 'frame']
    assert frame['customData']['worksheetOwner'] == 'unterricht/ab_test.qmd'
    assert frame['customData']['paper']['kind'] == 'grid'
    background = [e for e in scene['elements'] if e['type'] != 'frame']
    assert all(e['locked'] and e['customData']['slideBackground'] and e['frameId'] == frame['id']
               for e in background)
    lines = [e for e in background if e['type'] == 'line']
    assert {e['x'] for e in lines if e['width'] == 0} == set(range(25, 1600, 25))
    assert {e['y'] for e in lines if e['height'] == 0} == set(range(25, 900, 25))
    page = client.get('/api/worksheet/page?path=unterricht/ab_test.qmd&page=2')
    result = client.post('/api/worksheet/fragment', json={
        'path': 'unterricht/ab_test.qmd', 'source': 'unterricht/ab_test.qmd', 'page': 2,
        'crop': [0, 0, .5, .25], 'pdfRevision': page.headers['X-PDF-Revision']})
    assert result.status_code == 200
    assert result.json['image'].startswith('data:image/png;base64,')
    assert result.json['metadata']['page'] == 2
    assert result.json['width'] / result.json['height'] == pytest.approx(1.5)
    assert (root / first).read_bytes() == original
    assert client.post('/api/worksheet/start', json={'path': '../bad.qmd'}).status_code == 400
    assert client.post('/api/worksheet/fragment', json={
        'path': 'unterricht/ab_test.qmd', 'pdfRevision': 'stale'}).status_code == 400


def test_browser_has_no_solution_sidebar(worksheet_app):
    from playwright.sync_api import sync_playwright, expect
    app, _, _ = worksheet_app
    with live(app) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script("localStorage.setItem('material-ui:auto-render', 'false')")
        page.goto(url + '/?path=unterricht/ab_test.qmd')
        expect(page.get_by_role('button', name='Besprechen', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='Lösungen', exact=True)).to_have_count(0)
        expect(page.locator('.worksheet-solutions')).to_have_count(0)
        expect(page.get_by_role('combobox', name='Lösungsdatei', exact=True)).to_have_count(0)
        browser.close()


def test_shared_solution_frontmatter_and_manual_override(worksheet_app):
    app, runtime, root = worksheet_app
    source = root / 'unterricht/ab_test.qmd'
    source.write_text('---\ntitle: Test\nloesung: anders.qmd\n---\nAufgaben\n')
    runtime.services.documents.invalidate_qmd_cache()
    client = app.test_client()
    assert runtime.services.documents.source_meta(source)['loesung'] == 'anders.qmd'
    assert runtime.services.documents.qmd_entry(source)['loesung'] == 'anders.qmd'
    response = client.get('/api/worksheet?path=unterricht/ab_test.qmd')
    assert response.status_code == 200
    assert response.json['solution']['path'] == 'unterricht/anders.qmd'
    client.post('/api/worksheet/solution', json={'path': 'unterricht/ab_test.qmd', 'solution': None})
    assert client.get('/api/worksheet?path=unterricht/ab_test.qmd').json['solution'] is None
