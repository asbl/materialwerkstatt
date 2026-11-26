"""Exercise catalogue examples through the actual Excalidraw slide builder."""
import base64
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from excalideck.generator import SLIDE_WIDTH, SLIDE_MARGIN, generate_deck
from excalideck.outline import ImageBlock, ModelBlock, SpacerBlock, parse_outline
from excalideck.printable import render_printable_qmd

ROOT = Path(__file__).resolve().parents[2]


def catalogue():
    if not shutil.which('node'):
        return []
    uri = (ROOT / 'src/material_ui/static/shortcuts.js').as_uri()
    result = subprocess.run(['node', '--input-type=module', '-e',
        f'import {{ SHORTCUTS }} from {json.dumps(uri)}; console.log(JSON.stringify(SHORTCUTS));'],
        capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


# All slide entries, plus the drawing and box shortcuts shared with worksheets.
EXAMPLES = [item for item in catalogue() if 'folie' in item['tags'] or
            re.match(r'\[(Modell |Skizze |Einheitskreis |Koordinatensystem |Infobox|Warnbox|Tippbox|Rot )', item['code'])]


@pytest.mark.skipif(not shutil.which('quarto') or not shutil.which('typst'), reason='Quarto/Typst fehlt')
@pytest.mark.parametrize('item', EXAMPLES, ids=lambda item: item['id'])
def test_catalogue_shortcuts_build_in_slides(tmp_path, item):
    code = item['code'].replace('{{', '').replace('}}', '')
    source = tmp_path / 'slide.qmd'
    source.write_text('## Test\n\nVorher\n\n' + code + '\n\nNachher\n')
    data = json.loads(generate_deck(source).read_text())
    texts = '\n'.join(e.get('text', '') for e in data['elements'])
    assert 'Vorher' in texts and 'Nachher' in texts
    assert not re.search(r'\[(?:Modell|Skizze|Einheitskreis|Koordinatensystem|Infobox|Warnbox|Tippbox|Rot|abstand)\b', texts)
    assert 'Reflexionsfrage' not in texts
    if code.startswith(('[Modell ', '[Skizze ', '[Einheitskreis ', '[Koordinatensystem ')):
        assert data['files'], 'Zeichnung fehlt im Deck'
        for image in data['files'].values():
            assert '<svg' in base64.b64decode(image['dataURL'].split(',', 1)[1]).decode()
    if item['id'] == 'abstand':
        after = next(e for e in data['elements'] if e.get('text') == 'Nachher')
        source.write_text('## Test\n\nVorher\n\nNachher\n')
        baseline = json.loads(generate_deck(source, output_path=tmp_path / 'baseline.excalidraw').read_text())
        baseline_after = next(e for e in baseline['elements'] if e.get('text') == 'Nachher')
        assert after['y'] - baseline_after['y'] == pytest.approx(10 * SLIDE_WIDTH / 160)


@pytest.mark.parametrize('attributes', ['', '{width=100%}', '{width=90%}', '{width=80% fig-align="center"}'])
def test_image_attributes_do_not_turn_images_into_text(tmp_path, attributes):
    (tmp_path / 'model.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="30"><rect width="100" height="30"/></svg>')
    source = tmp_path / 'slide.qmd'
    source.write_text(f'## Modell\n\n![Flächenfolge](model.svg){attributes}\n')
    width_match = re.search(r'width=(\d+)%', attributes)
    expected_width = float(width_match[1]) if width_match else None
    assert parse_outline(source).slides[0].blocks == (ImageBlock(Path('model.svg'), expected_width),)
    data = json.loads(generate_deck(source).read_text())
    assert data['files']
    assert not any('![' in e.get('text', '') for e in data['elements'])


def test_spacing_survives_printable_export(tmp_path):
    source = tmp_path / 'slide.qmd'
    source.write_text('## Abstand\n\n[abstand 1cm]\n')
    outline = parse_outline(source)
    assert outline.slides[0].blocks == (SpacerBlock(10),)
    assert '[abstand 10mm]' in render_printable_qmd(outline, base_dir=tmp_path)


@pytest.mark.skipif(not shutil.which('quarto') or not shutil.which('typst'), reason='Quarto/Typst fehlt')
def test_integer_exponents_deck_has_models_and_no_literal_markdown(tmp_path):
    source = ROOT / 'unterricht/mathematik/klasse-10/potenzen/03 Ganzzahlige Exponenten/slide.qmd'
    if not source.exists():
        pytest.skip('Privates Unterrichts-Repo fehlt')
    try:
        outline = parse_outline(source)
    except ValueError as error:
        if 'Unbekanntes Folien-Design' in str(error):
            pytest.skip('Das Folien-Design des Materials ist privat und hier nicht vorhanden')
        raise
    models = [b for s in outline.slides for b in s.blocks if isinstance(b, ModelBlock)]
    assert any(b.marker.startswith("[Modell bruchrechteck |") for b in models)
    try:
        deck = generate_deck(source, output_path=tmp_path / 'slide.excalidraw')
    except ValueError as error:
        if 'Unbekanntes Folien-Design' in str(error):
            pytest.skip('Das Folien-Design des Materials ist privat und hier nicht vorhanden')
        raise
    data = json.loads(deck.read_text())
    assert len([e for e in data['elements'] if e['type'] == 'frame']) == len(outline.slides)
    texts = '\n'.join(e.get('text', '') for e in data['elements'])
    assert '![' not in texts and '\\frac' not in texts and '\\xrightarrow' not in texts
    embedded = [base64.b64decode(f['dataURL'].split(',', 1)[1]).decode() for f in data['files'].values()]
    assert any('class="whole"' in svg and 'class="part"' in svg for svg in embedded)


@pytest.mark.parametrize('width', [90, 50])
def test_image_percentage_scales_deck_and_survives_export(tmp_path, width):
    (tmp_path / 'wide.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="100"><rect width="1000" height="100"/></svg>')
    rendered = []
    for percentage in [100, width]:
        source = tmp_path / f'slide-{percentage}.qmd'
        source.write_text(f'## Bild\n\n![](wide.svg){{width="{percentage}%"}}\n')
        outline = parse_outline(source)
        assert f'{{width={percentage}%}}' in render_printable_qmd(outline, base_dir=tmp_path)
        data = json.loads(generate_deck(source).read_text())
        rendered.append(next(e for e in data['elements'] if e['type'] == 'image'))
    assert rendered[0]['width'] == pytest.approx(SLIDE_WIDTH - 2 * SLIDE_MARGIN)
    assert rendered[1]['width'] / rendered[0]['width'] == pytest.approx(width / 100)
    assert rendered[1]['height'] / rendered[0]['height'] == pytest.approx(width / 100)


@pytest.mark.parametrize('width', [0, 101])
def test_invalid_image_percentage_is_rejected(tmp_path, width):
    source = tmp_path / 'slide.qmd'
    source.write_text(f'## Bild\n\n![](wide.svg){{width={width}%}}\n')
    with pytest.raises(ValueError, match='Bildbreite'):
        parse_outline(source)
