from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILTER = ROOT / 'src/quarto/filters/exam.lua'
NS = {'svg': 'http://www.w3.org/2000/svg'}
pytestmark = pytest.mark.skipif(shutil.which('quarto') is None, reason='Quarto fehlt')


def render(marker: str, media: Path, target: str = 'typst'):
    return subprocess.run(
        ['quarto', 'pandoc', '--from', 'markdown', '--to', target,
         '--lua-filter', str(FILTER), '--extract-media', str(media)],
        input=marker, text=True, capture_output=True, timeout=30,
    )


def test_single_equation_aligns_product_units_without_duplicate_factors(tmp_path):
    result = render('[Modell ziffernraetsel | aufgabe=3_1_*2 | ergebnis=6830 | bildbreite=60mm]', tmp_path)
    assert result.returncode == 0, result.stderr
    assert '[Modell' not in result.stdout and '60mm' in result.stdout
    drawing = ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    assert len(drawing.findall('svg:rect[@class="ziffernkarte"]', NS)) == 5
    assert len(drawing.findall('svg:path[@class="kartenlinie"]', NS)) == 5
    labels = drawing.findall('svg:text', NS)
    upper = [t for t in labels if t.attrib['y'] == '29']
    assert [t.text for t in upper] == ['3', '1', '·', '2']
    product = [t for t in labels if t.attrib['y'] == '76']
    assert ''.join(t.text for t in product) == '6830'
    assert product[-1].attrib['x'] == upper[-1].attrib['x']
    assert len(labels) == len(upper) + len(product)
    assert all(t.text not in ['_', '?'] for t in labels)
    assert not drawing.findall('svg:path[@class="rechenraster"]', NS)
    assert len(drawing.findall('svg:path[@class="ergebnislinie"]', NS)) == 1



@pytest.mark.parametrize('task', ['_3_1*_', '?3?1*?', '_3_1 · _', '_3_1 × _', '_3_1 x _'])
def test_placeholders_and_multiplication_signs_keep_five_cards(task, tmp_path):
    result = render(f'[Modell ziffernraetsel | aufgabe={task} | ergebnis=11705]', tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    assert len(drawing.findall('svg:rect', NS)) == 5
    upper = [t.text for t in drawing.findall('svg:text', NS) if t.attrib['y'] == '29']
    assert upper == ['3', '1', '·']  # No missing digits are solved automatically.


@pytest.mark.parametrize('args', [
    'aufgabe=3_1_+2 | ergebnis=6830',
    'aufgabe=1234567*2 | ergebnis=2469134',
    'aufgabe=03_1*2 | ergebnis=6830',
    'aufgabe=3_1_*2',
    'ergebnis=6830',
    'aufgabe=3_1_*2 | ergebnis=06',
    'aufgabe=3_1_*2 | ergebnis=abc',
    'aufgabe=3_1_*2 | ergebnis=1234567890123',
    'aufgabe=3_1_*2 | ergebnis=6830 | bildbreite=2mm',
    'aufgabe=3_1_*2 | ergebnis=6830 | fehler=ja',
])
def test_invalid_digit_puzzles_fail_with_a_useful_message(args, tmp_path):
    result = render(f'[Modell ziffernraetsel | {args}]', tmp_path)
    assert result.returncode != 0
    assert 'Modell' in result.stderr


@pytest.mark.skipif(shutil.which('rsvg-convert') is None, reason='rsvg-convert fehlt')
def test_latex_uses_the_same_diagram_as_an_embedded_pdf(tmp_path):
    result = render('[Modell ziffernraetsel | aufgabe=3_1_*2 | ergebnis=6830]', tmp_path, 'latex')
    assert result.returncode == 0, result.stderr
    assert '[Modell' not in result.stdout
    assert next(tmp_path.glob('*.pdf')).read_bytes().startswith(b'%PDF')


@pytest.mark.skipif(shutil.which('node') is None, reason='Node fehlt')
def test_editor_shortcut_configuration_matches_filter_parameters():
    shortcuts = (ROOT / 'src/material_ui/static/shortcuts.js').as_uri()
    options = (ROOT / 'src/material_ui/static/shortcut-options.js').as_uri()
    code = f'''
import assert from 'node:assert/strict';
import {{ SHORTCUTS }} from {json.dumps(shortcuts)};
import {{ shortcutFields, configuredShortcut, shortcutErrors }} from {json.dumps(options)};
const item = SHORTCUTS.find(item => item.id === 'modell-ziffernraetsel');
const fields = shortcutFields(item);
assert.equal(fields.length, 3);
const values = ['_3_1*_', '11705', '42mm'];
assert.deepEqual(shortcutErrors(item, fields, values), ['', '', '']);
assert.equal(configuredShortcut(item, fields, values), '[Modell ziffernraetsel | aufgabe=_3_1*_ | ergebnis=11705 | bildbreite=42mm]');
for (const invalid of [['03_1*2', '6830', '42mm'], ['3_1_*2', '06', '42mm'], ['3_1_*2', '6830', '2mm']]) {{
  assert(shortcutErrors(item, fields, invalid).some(Boolean));
}}
'''
    result = subprocess.run(['node', '--input-type=module', '-e', code], text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
