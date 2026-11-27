from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf
import pytest

from material_core.builds import BuildService

ROOT = Path(__file__).resolve().parents[2]
FILTER = ROOT / 'src/quarto/filters/exam.lua'
EXAMPLES = ROOT / 'src/quarto/filters/examples/schuelerdialoge/ab_beispiele.qmd'
pytestmark = pytest.mark.skipif(shutil.which('quarto') is None, reason='Quarto fehlt')


def dialogue(people):
    return ':::: {.schuelerdialog}\n' + '\n'.join(
        f'::: {{.dialogbeitrag {attrs}}}\n{text}\n:::' for attrs, text in people
    ) + '\n::::\n'


def render(source, media, target='typst'):
    return subprocess.run(
        ['quarto', 'pandoc', '--from', 'markdown', '--to', target,
         '--lua-filter', str(FILTER), '--extract-media', str(media)],
        input=source, capture_output=True, text=True, timeout=30,
    )


def test_native_dialogue_preserves_text_math_names_and_figure_choices(tmp_path):
    source = dialogue([
        ('name="Mia" figur="zopf"', 'Ich rechne **zuerst** $2+3$.\n\n$2+3=5$'),
        ('name="Jörg" figur="brille" farbe="#25674c"', 'Ich erkläre meinen Weg.'),
    ])
    result = render(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert 'zuerst' in result.stdout and '$2 + 3$' in result.stdout
    assert 'Jörg' in result.stdout and '#25674c' in result.stdout
    assert 'quotes.enumerate()' in result.stdout  # Equal-height bubble row.
    assert result.stdout.count('#grid(columns: (11mm, 1fr)') == 2
    files = list(tmp_path.glob('*.svg'))
    assert len(files) == 2
    for file in files:
        drawing = ET.parse(file).getroot()
        assert drawing.attrib['viewBox'] == '0 0 120 140'
        assert drawing.findall('.//{http://www.w3.org/2000/svg}ellipse')


def test_dialogue_supports_models_below_the_speech_bubble(tmp_path):
    source = dialogue([
        ('name="Mia"', 'Ich zerlege.\n\n[Modell malkreuz | oben=20,6 | links=10,4]'),
        ('name="Tim" figur="keine"', 'Ich prüfe das Ergebnis.\n\n- Erste Beobachtung\n- Zweite Beobachtung'),
    ])
    result = render(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert '[Modell' not in result.stdout
    assert 'Erste Beobachtung' in result.stdout
    assert len(list(tmp_path.glob('*.svg'))) == 2  # One figure and one model.


def test_one_to_four_contributions_and_repeated_speakers(tmp_path):
    for count in [1, 4]:
        result = render(dialogue([('name="Mia" figur="keine"', f'Aussage {i}.') for i in range(count)]), tmp_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout.count('"Mia"') == count
        assert 'dialogfigur-' not in result.stdout


@pytest.mark.parametrize('source', [
    '::: {.schuelerdialog}\n:::',
    dialogue([('figur="kurz"', 'Ohne Namen.')]),
    dialogue([('name="Mia" figur="unbekannt"', 'Hallo.')]),
    dialogue([('name="Mia" farbe="red"', 'Hallo.')]),
    dialogue([('name="Mia" hautfarbe="red"', 'Hallo.')]),
    dialogue([('name="Mia"', '## Kein gesprochener Absatz')]),
    dialogue([('name="Mia"', '[Modell vierhundertfeld]')]),
    dialogue([('name="Mia"', 'Hallo.') for _ in range(5)]),
    '::: {.schuelerdialog}\nNormaler Text ohne Beitrag.\n:::',
])
def test_invalid_dialogues_report_a_useful_error(source, tmp_path):
    result = render(source, tmp_path)
    assert result.returncode != 0
    assert 'Schülerdialog' in result.stderr


@pytest.mark.skipif(shutil.which('rsvg-convert') is None, reason='rsvg-convert fehlt')
def test_latex_output_keeps_figures_and_spoken_text(tmp_path):
    result = render(dialogue([
        ('name="Leo" figur="brille"', 'Ich rechne zuerst.'),
        ('name="Till" figur="kurz"', 'Ich rechne danach.'),
    ]), tmp_path, 'latex')
    assert result.returncode == 0, result.stderr
    assert result.stdout.count('\\fcolorbox') == 2
    assert 'Ich rechne zuerst.' in result.stdout and 'Till' in result.stdout
    files = list(tmp_path.glob('*.pdf'))
    assert len(files) == 2
    assert all(file.read_bytes().startswith(b'%PDF') for file in files)


def test_gallery_renders_two_compact_pages_with_aligned_speakers(tmp_path):
    source = tmp_path / 'ab_beispiele.qmd'
    source.write_text(EXAMPLES.read_text())
    result = BuildService(tmp_path, subprocess.run).build_document(source)
    with pymupdf.open(result.pdf_path) as pdf:
        assert len(pdf) == 2
        first = pdf[0].get_text()
        second = pdf[1].get_text()
        assert all(name in first for name in ['Leo', 'Till', 'Esra', 'Noah'])
        assert all(name in second for name in ['Mia', 'Kim', 'Nele', 'Jonas'])
        assert '68000' in ''.join(first.split())
        assert '37022' in ''.join(first.split())
        assert '6052' in ''.join(second.split())
        leo, till = pdf[0].search_for('Leo')[0], pdf[0].search_for('Till')[0]
        assert abs(leo.y0 - till.y0) < .5
        for page in pdf:
            text = page.get_text()
            assert '[Modell' not in text and 'dialogbeitrag' not in text
            for block in page.get_text('blocks'):
                assert 0 <= block[0] < block[2] <= page.rect.width + 1
                assert 0 <= block[1] < block[3] <= page.rect.height + 1


@pytest.mark.skipif(shutil.which('node') is None, reason='Node fehlt')
def test_editor_dialogue_shortcuts_offer_multiline_text_and_figure_choices():
    shortcuts = (ROOT / 'src/material_ui/static/shortcuts.js').as_uri()
    options = (ROOT / 'src/material_ui/static/shortcut-options.js').as_uri()
    script = f'''
import assert from 'node:assert/strict';
import {{ SHORTCUTS }} from {json.dumps(shortcuts)};
import {{ shortcutFields, configuredShortcut, shortcutErrors }} from {json.dumps(options)};
for (const id of ['schuelerdialog-zwei', 'schuelerdialog-drei', 'schuelerdialog-modelle', 'schuelerdialog-farben']) {{
  const item = SHORTCUTS.find(item => item.id === id);
  const fields = shortcutFields(item);
  const values = fields.map(field => field.value);
  assert(shortcutErrors(item, fields, values).every(error => !error));
  assert(configuredShortcut(item, fields, values).includes('.schuelerdialog'));
  assert(fields.filter(field => field.label.startsWith('Aussage')).every(field => field.type === 'multiline'));
  assert(fields.filter(field => field.label.startsWith('Figur')).every(field => field.choices.includes('keine')));
  values[0] = '"kein gültiger Name';
  assert(shortcutErrors(item, fields, values)[0]);
}}
'''
    result = subprocess.run(['node', '--input-type=module', '-e', script], text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('layout', ['', ' layout="kompakt"'])
def test_custom_skin_color_overrides_style_for_all_skin_parts(tmp_path, layout):
    source = dialogue([('name="Mia" figur="zopf" hautfarbe="#ffe1bd" haarfarbe="#f5d553"', 'Hallo.')])
    source = source.replace('{.schuelerdialog}', '{.schuelerdialog' + layout + '}')
    result = render(source, tmp_path)
    assert result.returncode == 0, result.stderr
    if layout:
        assert result.stdout.count('#ffe1bd') == 5
        assert '#bd825b' not in result.stdout
    else:
        drawing = ET.parse(next(tmp_path.glob('*.svg'))).getroot()
        skin_parts = drawing.findall('.//*[@fill="#ffe1bd"]')
        assert len(skin_parts) == 5  # Neck, ears, face and hand.
        assert not drawing.findall('.//*[@fill="#bd825b"]')


def test_gallery_draws_every_model_with_shortcuts():
    text = EXAMPLES.read_text()
    assert '![](' not in text
    assert text.count('[Modell schriftlich ') == 6
    assert '[Modell malkreuz ' in text and '[Modell rechenstrich ' in text
