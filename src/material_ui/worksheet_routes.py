"""Arbeitsblatt, Lösungsansicht und dauerhaftes Besprechungs-Canvas."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import time
import uuid
from io import BytesIO

import pymupdf
from flask import jsonify, request, send_file

from material_core.filesystem import atomic_write_text
from material_ui.errors import InvalidInput
from material_ui.http import required_arg
from material_ui.slides import deck_lock
from material_ui.worksheet_tasks import detect_tasks


CANVAS_PART_BYTES = 16 * 1024 * 1024


def discussion_background(frame):
    """Rechenkästchen wie im Hintergrundmenü der Präsentationsansicht."""
    style = dict(frameId=frame['id'], locked=True, roughness=0, strokeWidth=1,
                 strokeColor='#cbd5e1', opacity=100, customData={'slideBackground': True})
    elements = [dict(style, id=uuid.uuid4().hex, type='rectangle',
                     x=0, y=0, width=frame['width'], height=frame['height'],
                     strokeColor='transparent', backgroundColor='#ffffff', fillStyle='solid')]
    for x, y, width, height in (
        [(x, 0, 0, frame['height']) for x in range(25, frame['width'], 25)]
        + [(0, y, frame['width'], 0) for y in range(25, frame['height'], 25)]
    ):
        elements.append(dict(style, id=uuid.uuid4().hex, type='line',
                             x=x, y=y, width=width, height=height,
                             points=[[0, 0], [width, height]]))
    return elements


def solution_key(name):
    return re.sub(r'[-_\s]+', '-', re.sub(r'(?i)[-_\s]*(muster)?l(?:oe|ö)sung(?:en)?', '', name)).strip('-').casefold()


def register_worksheet_routes(app, runtime):
    config = runtime.config
    documents = runtime.services.documents
    store = runtime.services.worksheets

    def source(value):
        if not isinstance(value, str):
            raise InvalidInput('Ungültiger Dokumentpfad.')
        path = config.safe_visible_path(value)
        if path.suffix not in {'.qmd', '.md'} or not path.is_file():
            raise InvalidInput('Arbeitsblatt oder Lösung nicht gefunden.')
        from material_ui.document_types import ensure_renderable
        ensure_renderable(path)
        return path

    def pdf_for(path):
        value = documents.qmd_entry(path).get('pdf')
        if not value:
            raise InvalidInput('Noch kein PDF vorhanden. Bitte das Dokument zuerst rendern.')
        if runtime.services.builds.pdf_is_current(path) is not True:
            raise InvalidInput('Das PDF ist veraltet oder sein Stand ist unbekannt. Bitte zuerst neu rendern.')
        return config.safe_visible_path(value)

    def open_page(path, value):
        try:
            number = int(value)
        except (ValueError, TypeError) as error:
            raise InvalidInput('Ungültige Seitennummer.') from error
        content = pdf_for(path).read_bytes()
        pdf = pymupdf.open(stream=content, filetype='pdf')
        if number < 1 or number > len(pdf):
            pdf.close()
            raise InvalidInput('Seite nicht vorhanden.')
        return pdf, number - 1, hashlib.sha256(content).hexdigest()

    @app.get('/api/worksheet')
    def worksheet():
        path = source(required_arg('path'))
        entries = documents.qmd_entries_cached()
        candidates = [entry for entry in entries if entry.get('solution') and entry['path'] != config.relative(path)]
        key = solution_key(path.stem)
        matches = [entry for entry in candidates if entry['folder'] == config.relative(path.parent)
                   and solution_key(entry['stem']) == key]
        mapping = store.links()
        key_path = config.relative(path)
        selected = mapping.get(key_path)
        disabled = key_path in mapping and selected is None
        if key_path not in mapping:
            linked = documents.source_meta(path).get('loesung')
            if linked and '/' not in linked and '\\' not in linked and not linked.startswith('.'):
                selected = (path.parent / linked).relative_to(config.root).as_posix()
        selected_entry = None
        if selected:
            try:
                selected_entry = documents.qmd_entry(source(selected))
            except (InvalidInput, FileNotFoundError):
                selected = None
        if not disabled and not selected and len(matches) == 1:
            selected = matches[0]['path']
        selected_entry = selected_entry or next((entry for entry in candidates if entry['path'] == selected), None)
        if selected_entry:
            selected_entry = dict(selected_entry, pdfCurrent=runtime.services.builds.pdf_is_current(source(selected_entry['path'])))
        canvas = store.canvas(path)
        return jsonify(solution=selected_entry, candidates=candidates,
                       canvas=config.relative(canvas) if canvas.exists() else None,
                       canvasBytes=canvas.stat().st_size if canvas.exists() else 0,
                       canvases=[{'path': config.relative(p), 'bytes': p.stat().st_size} for p in store.parts(path)],
                       solutionMode='none' if disabled else ('manual' if key_path in mapping else 'auto'))

    @app.post('/api/worksheet/solution')
    def worksheet_solution():
        data = request.get_json()
        path = source(data.get('path', ''))
        choice = data.get('solution')
        selected = 'auto' if data.get('mode') == 'auto' else (source(choice) if choice else None)
        if selected == path:
            raise InvalidInput('Bitte eine andere Datei als Lösung auswählen.')
        store.set_solution(path, selected)
        return jsonify(ok=True)

    @app.get('/api/worksheet/page')
    def worksheet_page():
        path = source(required_arg('path'))
        pdf, index, revision = open_page(path, request.args.get('page', 1))
        with pdf:
            page = pdf[index]
            scale = min(2, 1600 / max(page.rect.width, page.rect.height))
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            response = send_file(BytesIO(pixmap.tobytes('png')), mimetype='image/png')
            response.headers['X-PDF-Pages'] = str(len(pdf))
            response.headers['X-PDF-Revision'] = revision
            return response

    @app.get('/api/worksheet/tasks')
    def worksheet_tasks():
        path = source(required_arg('path'))
        pdf, index, revision = open_page(path, request.args.get('page', 1))
        with pdf:
            return jsonify(tasks=detect_tasks(pdf[index]), revision=revision)

    @app.post('/api/worksheet/start')
    def worksheet_start():
        owner = source(request.get_json().get('path', ''))
        with store.lock:
            source(config.relative(owner))
            target = store.canvas(owner, new=True)
            with deck_lock(target):
                frame = dict(id=uuid.uuid4().hex, type='frame', x=0, y=0,
                             width=1600, height=900, name='Besprechung',
                             customData={'worksheetOwner': config.relative(owner),
                                         'paper': {'kind': 'grid', 'spacing': 25, 'axisStep': 1}})
                scene = dict(type='excalidraw', version=2, source='material-ui',
                             elements=[*discussion_background(frame), frame], files={},
                             appState={'viewBackgroundColor': '#ffffff'})
                atomic_write_text(target, json.dumps(scene, ensure_ascii=False))
        return jsonify(path=config.relative(target))

    @app.post('/api/worksheet/fragment')
    @app.post('/api/worksheet/canvas')
    def worksheet_canvas():
        data = request.get_json()
        owner = source(data.get('path', ''))
        origin = source(data.get('source') or data.get('path', ''))
        pdf, index, revision = open_page(origin, data.get('page', 1))
        with pdf:
            if data.get('pdfRevision') != revision:
                raise InvalidInput('Das PDF wurde geändert. Bitte die Seitenvorschau erneut öffnen.')
            crop = data.get('crop', [0, 0, 1, 1])
            if (not isinstance(crop, list) or len(crop) != 4
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in crop)
                    or not (0 <= crop[0] < crop[2] <= 1 and 0 <= crop[1] < crop[3] <= 1)):
                raise InvalidInput('Ungültiger Ausschnitt.')
            page = pdf[index]
            rect = page.rect
            clip = pymupdf.Rect(rect.x0 + crop[0] * rect.width, rect.y0 + crop[1] * rect.height,
                                rect.x0 + crop[2] * rect.width, rect.y0 + crop[3] * rect.height)
            if clip.width < 1 or clip.height < 1:
                raise InvalidInput('Der Ausschnitt ist zu klein.')
            scale = min(2.5, 2400 / max(clip.width, clip.height))
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
            png = pixmap.tobytes('png')
            while len(png) > 4 * 1024 * 1024:
                pixmap.shrink(1)
                png = pixmap.tobytes('png')
            image = 'data:image/png;base64,' + base64.b64encode(png).decode()
        if request.path.endswith('/fragment'):
            return jsonify(image=image, width=pixmap.width, height=pixmap.height,
                           metadata={'worksheetSource': config.relative(origin), 'page': index+1,
                                     'crop': crop, 'pdfRevision': revision})
        with store.lock:
            target = store.canvas(owner, new=data.get('newCanvas') is True)
            with deck_lock(target):
                source(config.relative(owner))
                if hashlib.sha256(pdf_for(origin).read_bytes()).hexdigest() != revision:
                    raise InvalidInput('Das PDF wurde geändert. Bitte die Seitenvorschau erneut öffnen.')
                previous = target.read_text() if target.exists() else None
                image_id = hashlib.sha256(png).hexdigest()
                scene = json.loads(previous) if previous else None
                if previous and len(previous.encode()) + (0 if image_id in scene.get('files', {}) else len(image)) + 4096 > CANVAS_PART_BYTES:
                    target = store.canvas(owner, new=True)
                    previous = None
                    scene = None
                scene = scene or {
                    'type': 'excalidraw', 'version': 2, 'source': 'material-ui',
                    'elements': [], 'files': {}, 'appState': {'viewBackgroundColor': '#ffffff'}}
                frames = [el for el in scene['elements'] if el['type'] == 'frame' and not el.get('isDeleted')]
                x = max((el['x'] + el['width'] for el in frames), default=-100) + 100
                frame_id, file_id = uuid.uuid4().hex, image_id
                width = min(1000, pixmap.width / 2)
                height = pixmap.height * width / pixmap.width
                now = int(time.time() * 1000)

                def element(kind, **fields):
                    return dict(id=uuid.uuid4().hex, type=kind, x=x, y=0, width=1400, height=max(900, height+100),
                                angle=0, strokeColor='#1e1e1e', backgroundColor='transparent', fillStyle='solid',
                                strokeWidth=1, strokeStyle='solid', roughness=0, opacity=100, groupIds=[],
                                frameId=None, roundness=None, seed=1, version=1, versionNonce=1,
                                isDeleted=False, boundElements=None, updated=now, link=None, locked=False) | fields

                scene['elements'].extend([
                    element('image', x=x+40, y=40, width=width, height=height, frameId=frame_id,
                            fileId=file_id, status='saved', scale=[1, 1], crop=None,
                            customData={'worksheetSource': config.relative(origin), 'page': index+1,
                                        'crop': crop, 'pdfRevision': revision}),
                    element('frame', id=frame_id, name=f'{origin.stem} · Seite {index+1}'),
                ])
                scene['files'].setdefault(file_id, dict(id=file_id, mimeType='image/png', dataURL=image, created=now))
                if previous:
                    runtime.documents.archive(target, {'text': previous, 'revision': hashlib.sha256(previous.encode()).hexdigest()})
                atomic_write_text(target, json.dumps(scene, ensure_ascii=False))
                # Existing sidecar annotations stay attached to their frames.
        return jsonify(path=config.relative(target), frame=frame_id, canvasBytes=target.stat().st_size)
