"""Gemeinsame, nicht destruktive Layoutprüfung fertiger PDFs und Excalidraw-Decks."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import pymupdf

MAX_ISSUES = 60
MIN_PDF_FONT = 8.0
MIN_SLIDE_FONT = 9.0
MIN_DECK_FONT = 24.0


def issue(target, code, page, title, detail):
    return {'level': 'warning', 'target': target, 'code': code, 'page': page,
            'title': title, 'detail': detail}


def outside(bounds, canvas, tolerance):
    return (bounds[0] < canvas[0] - tolerance or bounds[1] < canvas[1] - tolerance
            or bounds[2] > canvas[2] + tolerance or bounds[3] > canvas[3] + tolerance)


@lru_cache(maxsize=32)
def _pdf_checks(path, mtime, size, slides):
    issues = []
    try:
        with pymupdf.open(path) as pdf:
            for index, page in enumerate(pdf):
                canvas = page.rect * page.derotation_matrix
                minimum = MIN_SLIDE_FONT if slides and abs(canvas.width / canvas.height - 16 / 9) < .1 else MIN_PDF_FONT
                small = []
                clipped = []
                for block in page.get_text('dict', clip=pymupdf.INFINITE_RECT()).get('blocks', []):
                    for line in block.get('lines', []):
                        spans = [span for span in line['spans'] if span['text'].strip()]
                        if not spans:
                            continue
                        text = ''.join(span['text'] for span in spans)
                        # Kleine Hoch-/Tiefstellungen allein machen eine normal gesetzte Zeile nicht unlesbar.
                        largest = max(span['size'] for span in spans)
                        threshold = 6.0 if line["bbox"][1] > canvas.y0 + .90 * canvas.height else minimum
                        if largest < threshold - .1:
                            small.append((largest, text, threshold))
                        if outside(line['bbox'], canvas, 1.0):
                            clipped.append(text)
                if small:
                    font, text, threshold = min(small)
                    issues.append(issue('pdf', 'small-font', index + 1, 'Kleine Schrift',
                                        f'PDF, Seite {index + 1}: {font:.1f} pt (Richtwert mindestens {threshold:g} pt), z. B. „{text[:90]}“.'))
                if clipped:
                    issues.append(issue('pdf', 'overflow', index + 1, 'Text außerhalb der Seite',
                                        f'PDF, Seite {index + 1}: {len(clipped)} Textzeile(n) können abgeschnitten sein, z. B. „{clipped[0][:90]}“.'))
                for image in page.get_image_info():
                    if outside(image['bbox'], canvas, 1.0):
                        issues.append(issue('pdf', 'image-overflow', index + 1, 'Bild außerhalb der Seite',
                                            f'PDF, Seite {index + 1}: Ein Bild ragt über den sichtbaren Seitenrand.'))
                        break
                if len(issues) >= MAX_ISSUES:
                    break
    except (OSError, RuntimeError, ValueError):
        issues.append(issue('pdf', 'unreadable', None, 'Layout nicht prüfbar', 'Die vorhandene PDF-Datei konnte für die Layoutprüfung nicht gelesen werden.'))
    return tuple(issues[:MAX_ISSUES])


def bounds(element):
    x, y = element.get('x', 0), element.get('y', 0)
    width, height = element.get('width', 0), element.get('height', 0)
    angle = element.get('angle', 0)
    rotated_width = abs(width * math.cos(angle)) + abs(height * math.sin(angle))
    rotated_height = abs(height * math.cos(angle)) + abs(width * math.sin(angle))
    cx, cy = x + width / 2, y + height / 2
    return (cx - rotated_width / 2, cy - rotated_height / 2,
            cx + rotated_width / 2, cy + rotated_height / 2)


@lru_cache(maxsize=32)
def _deck_checks(path, mtime, size):
    issues = []
    try:
        scene = json.loads(Path(path).read_text(encoding='utf-8'))
        elements = [element for element in scene['elements'] if not element.get('isDeleted')]
        frames = [element for element in elements if element['type'] == 'frame']
        for index, frame in enumerate(frames):
            canvas = (frame['x'], frame['y'], frame['x'] + frame['width'], frame['y'] + frame['height'])
            name = frame.get('name') or str(index + 1)
            children = [element for element in elements if element.get('frameId') == frame['id']
                        and not element.get('customData', {}).get('presenterAnnotation')]
            clipped = [element for element in children if outside(bounds(element), canvas, 2.0)]
            if clipped:
                label = next((element.get('text', '') for element in clipped if element.get('text')), '')
                issues.append(issue('slides', 'overflow', index + 1, 'Inhalt außerhalb der Folie',
                                    f'Slides, Folie {index + 1} „{name}“: {len(clipped)} Element(e) können abgeschnitten sein.'
                                    + (f' Betroffen: „{label[:90]}“.' if label else '')))
            small = [element for element in children if element['type'] == 'text'
                     and element.get('fontSize', MIN_DECK_FONT) < MIN_DECK_FONT
                     and element.get('text', '').strip()
                     and element['y'] < frame['y'] + .92 * frame['height']]
            if small:
                font = min(element['fontSize'] for element in small)
                issues.append(issue('slides', 'small-font', index + 1, 'Kleine Schrift',
                                    f'Slides, Folie {index + 1} „{name}“: {font:g} px (Richtwert mindestens {MIN_DECK_FONT:g} px).'))
            if len(issues) >= MAX_ISSUES:
                break
    except (OSError, ValueError, KeyError, TypeError):
        issues.append(issue('slides', 'unreadable', None, 'Layout nicht prüfbar', 'Das vorhandene Deck konnte für die Layoutprüfung nicht gelesen werden.'))
    return tuple(issues[:MAX_ISSUES])


def check_layout(pdf: Path | None = None, deck: Path | None = None, *, slides=False) -> list[dict]:
    issues = []
    for path, checker, extra in ((pdf, _pdf_checks, (slides,)), (deck, _deck_checks, ())):
        if path is not None:
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            issues.extend(dict(item) for item in checker(str(path), stat.st_mtime_ns, stat.st_size, *extra))
    return issues[:MAX_ISSUES]
