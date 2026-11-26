"""Aufgabenbereiche in Arbeitsblaetter-PDFs fuer die Besprechung erkennen.

Die gebauten Arbeitsblaetter kommen aus zwei Pipelines (Typst-Designs und
LaTeX-Template mit ``\\tasknum``). Beide schreiben erkennbare Marker in die
PDF-Textebene:

* weisse Ziffernkacheln (``\\tasknum``) in fetten LaTeX-Arbeitsblaettern,
* fette Zeilen `Aufgabe N ...` (Klausuren und Frageboegen),
* grosse fette nummerierte Abschnitts- und Wochenkopfzeilen der Typst-Designs
  (z. B. `1 · Warm werden` oder `Kopffuebung 2 · Aufstieg`).

Die Erkennung ist eine Komfortfunktion: Gelingt sie nicht, bleibt der manuelle
Rahmen im Besprechungsdialog vollstaendig nutzbar.
"""
from __future__ import annotations

import re
import statistics
import unicodedata

# `[^\W\d_]` matcht alle Unicode-Buchstaben inklusive Umlauten und ß; die
# Klasse bleibt damit unabhaengig von der NFD/NFC-Schreibweise des Quelltexts
# (ein dekomponiertes u + U+0308 wuerde bei einer literalen Klasse fehlen).
_LETTERS = r'[^\W\d_]'
_AUFGABE = re.compile(r'^Aufgabe\s+(\d{1,2})\b[\s.:)]*(.*)$')
_NUMBERED = re.compile(r'^(' + _LETTERS + r'+\s+)?(\d{1,2})\s*(?:[·:\-–—]\s*|\s+)(\S.*)$')
_TILE = re.compile(r'\d{1,3}')
TITLE_LIMIT = 48
_MIN_WIDTH = 0.02
_MIN_HEIGHT = 0.012
_PAD = 4.0


def _near_white(color: int) -> bool:
    return min((color >> 16) & 255, (color >> 8) & 255, color & 255) >= 0xC0


def _tile_label(span: dict) -> str | None:
    """Weisse Nummernkachel (\\tasknum): Ziffern allein in weisser Schrift."""
    text = span['text'].strip()
    if not _TILE.fullmatch(text):
        return None
    if not _near_white(span['color']) or not 4 <= span['size'] <= 22:
        return None
    width = span['bbox'][2] - span['bbox'][0]
    if width > 6 * span['size']:  # breite Spannen sind Fliesstext
        return None
    return text


def _lines(page) -> list[dict]:
    lines = []
    for block in page.get_text('dict')['blocks']:
        if block.get('type') != 0:
            continue
        for line in block['lines']:
            spans = [span for span in line['spans'] if span['text'].strip()]
            if not spans:
                continue
            text = unicodedata.normalize('NFC', ''.join(span['text'] for span in line['spans'])).strip()
            lines.append({
                'text': text,
                'size': max(span['size'] for span in spans),
                'bold': any(span['flags'] & 16 for span in spans),
                'coords': (min(span['bbox'][0] for span in spans), min(span['bbox'][1] for span in spans),
                           max(span['bbox'][2] for span in spans), max(span['bbox'][3] for span in spans)),
                'spans': spans,
            })
    return lines


def _title(text: str) -> str:
    text = text.strip()
    return text[:TITLE_LIMIT] + ('…' if len(text) > TITLE_LIMIT else '')


def _next_band_top(bands: list[list[dict]], start: int, left: float, right: float) -> float:
    for band in bands[start:]:
        inside = [marker for marker in band if left <= marker['x'] < right]
        if inside:
            return min(marker['y0'] for marker in inside)
    return float('inf')


def detect_tasks(page) -> list[dict]:
    """Erkannte Aufgaben als normalisierte Rechtecke (x0, y0, x1, y1) der Seite.

    Rechtecke beziehen sich wie der Besprechungsrahmen auf die ganze Seite
    (0..1), beginnen knapp ueber dem Aufgabenkopf und enden am naechsten
    Aufgabenanfang derselben Spalte bzw. am Seiteninhalt unten.
    """
    lines = _lines(page)
    if not lines:
        return []
    # Grundschrift aus unformatierten Zeilen: Der Median ueber alle Zeilen
    # faellt auf Seiten mit wenigen, ueberschriftslastigen Eintraufen sonst
    # auf eine Ueberschrift selbst. Ohne ungebundene Zeilen gilt typische 10 pt.
    plain_sizes = [line['size'] for line in lines if not line['bold']]
    body = statistics.median(plain_sizes) if plain_sizes else 10.0
    heading_size = max(12.5, body * 1.12)
    rect = page.rect
    if rect.width <= 0 or rect.height <= 0:
        return []

    markers = []
    for line in lines:
        tiles = [(span, label) for span in line['spans'] if (label := _tile_label(span))]
        if tiles:
            for span, label in tiles:
                rest = [item for item in line['spans']
                        if item is not span and item['bbox'][0] >= span['bbox'][2] - 0.5]
                markers.append({'label': label, 'title': _title(' '.join(item['text'] for item in rest)),
                                'x': span['bbox'][0], 'x1': line['coords'][2],
                                'y0': line['coords'][1], 'y1': line['coords'][3]})
            continue
        match = _AUFGABE.match(line['text'])
        if match and (line['bold'] or line['size'] >= heading_size):
            markers.append({'label': f'Aufgabe {match.group(1)}', 'title': _title(match.group(2)),
                            'x': line['coords'][0], 'x1': line['coords'][2],
                            'y0': line['coords'][1], 'y1': line['coords'][3]})
            continue
        match = _NUMBERED.match(line['text'])
        if match and line['bold'] and line['size'] >= heading_size:
            prefix, number, rest = match.groups()
            prefix = (prefix or '').strip()
            markers.append({'label': f'{prefix} {number}' if prefix else number, 'title': _title(rest),
                            'x': line['coords'][0], 'x1': line['coords'][2],
                            'y0': line['coords'][1], 'y1': line['coords'][3]})

    if not markers:
        return []

    markers.sort(key=lambda marker: (round(marker['y0'], 1), marker['x']))
    tolerance = max(5.0, 0.45 * statistics.median(marker['y1'] - marker['y0'] for marker in markers))
    bands: list[list[dict]] = []
    for marker in markers:
        if bands and abs(marker['y0'] - bands[-1][0]['y0']) <= tolerance:
            bands[-1].append(marker)
        else:
            bands.append([marker])

    content_x0 = min(line['coords'][0] for line in lines)
    content_x1 = max(line['coords'][2] for line in lines)
    content_bottom = max(line['coords'][3] for line in lines)

    regions = []
    for index, band in enumerate(bands):
        band.sort(key=lambda marker: marker['x'])
        bounds = []
        for position, marker in enumerate(band):
            left = content_x0 - _PAD
            right = content_x1 + _PAD
            if len(band) > 1:
                if position > 0:
                    previous = band[position - 1]
                    left = previous['x1'] + max(marker['x'] - previous['x1'], 0) / 2
                if position + 1 < len(band):
                    following = band[position + 1]
                    right = marker['x1'] + max(following['x'] - marker['x1'], 0) / 2
            bounds.append((left, right))
        for marker, (left, right) in zip(band, bounds):
            bottom = _next_band_top(bands, index + 1, left, right)
            bottom = content_bottom + _PAD if bottom == float('inf') else bottom - 2.0
            top = max(0.0, marker['y0'] - _PAD)
            x0 = max(0.0, left) / rect.width
            x1 = min(rect.width, right) / rect.width
            y0 = top / rect.height
            y1 = min(rect.height, bottom) / rect.height
            if x1 - x0 < _MIN_WIDTH or y1 - y0 < _MIN_HEIGHT:
                continue
            regions.append({'label': marker['label'], 'title': marker['title'],
                            'rect': [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]})

    seen: dict[str, int] = {}
    for region in regions:
        count = seen.get(region['label'], 0) + 1
        seen[region['label']] = count
        if count > 1:
            region['label'] = f"{region['label']} ({count})"
    return sorted(regions, key=lambda region: (region['rect'][1], region['rect'][0]))
