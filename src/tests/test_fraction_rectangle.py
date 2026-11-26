"""The reference whole must stay fixed when its marked fraction changes."""
import base64
import json
import shutil
import xml.etree.ElementTree as ET

import pytest

from excalideck.generator import generate_deck


@pytest.mark.skipif(not shutil.which('quarto') or not shutil.which('typst'), reason='Quarto/Typst fehlt')
def test_fraction_rectangles_preserve_whole_and_marked_area(tmp_path):
    source = tmp_path / 'slide.qmd'
    source.write_text('## Anteile\n\n[Modell bruchrechteck | werte=0,1/8,1/4,1/2,1,5/4,2,4,8 | raster=ja]\n')
    deck = json.loads(generate_deck(source).read_text())
    svgs = [ET.fromstring(base64.b64decode(f['dataURL'].split(',', 1)[1])) for f in deck['files'].values()]
    groups = [g for svg in svgs for g in svg.iter() if g.attrib.get('class') == 'fraction']
    assert len(groups) == 9
    for group in groups:
        whole = [r for r in group if r.attrib.get('class') == 'whole']
        parts = [r for r in group if r.attrib.get('class') == 'part']
        assert whole
        assert all(float(r.attrib['width']) == 50 and float(r.attrib['height']) == 100 for r in whole)
        expected = int(group.attrib['data-numerator']) / int(group.attrib['data-denominator'])
        area = sum(float(r.attrib['width']) * float(r.attrib['height']) for r in parts)
        assert area / 5000 == pytest.approx(expected)
        for part in parts:
            x,y,w,h = (float(part.attrib[k]) for k in ('x','y','width','height'))
            assert any(float(r.attrib['x']) <= x <= x+w <= float(r.attrib['x'])+50+1e-5
                       and float(r.attrib['y']) <= y <= y+h <= float(r.attrib['y'])+100+1e-5 for r in whole)


@pytest.mark.skipif(not shutil.which('quarto') or not shutil.which('typst'), reason='Quarto/Typst fehlt')
@pytest.mark.parametrize('grid', [None, 'nein', 'ja', 'gestrichelt'])
def test_optional_divisions_show_equal_parts(tmp_path, grid):
    option = f' | raster={grid}' if grid else ''
    source = tmp_path / 'slide.qmd'
    source.write_text(f'## Anteile\n\n[Modell bruchrechteck | werte=1/8,1/4,1/2,1{option}]\n')
    deck = json.loads(generate_deck(source).read_text())
    svgs = [ET.fromstring(base64.b64decode(f['dataURL'].split(',', 1)[1])) for f in deck['files'].values()]
    groups = [g for svg in svgs for g in svg.iter() if g.attrib.get('class') == 'fraction']
    for group, expected_lines in zip(groups, [4, 2, 1, 0], strict=True):
        lines = [e for e in group if e.attrib.get('class') == 'division']
        assert len(lines) == (expected_lines if grid in ('ja', 'gestrichelt') else 0)
        for line in lines:
            assert ('stroke-dasharray' in line.attrib) == (grid == 'gestrichelt')


@pytest.mark.skipif(not shutil.which('quarto') or not shutil.which('typst'), reason='Quarto/Typst fehlt')
def test_blank_extension_fields_and_labels_stay_with_their_models(tmp_path):
    source = tmp_path / 'slide.qmd'
    source.write_text('## Folge\n\n[Modell bruchrechteck | werte=?,?,1/8,1/4,1/2,1,2,4,8 | raster=gestrichelt | beschriftung=ja | texte=?,?,?,?,?,2⁰,2¹,2²,?]\n')
    deck = json.loads(generate_deck(source).read_text())
    svgs = [ET.fromstring(base64.b64decode(f['dataURL'].split(',', 1)[1])) for f in deck['files'].values()]
    groups = [g for svg in svgs for g in svg.iter() if g.attrib.get('class') in ('blank', 'fraction')]
    assert len(groups) == 9
    for index, group in enumerate(groups):
        whole = [e for e in group if e.attrib.get('class') == 'whole']
        assert all(float(e.attrib['y']) == 12 and float(e.attrib['height']) == 100 for e in whole)
        if index < 2:
            assert group.attrib['class'] == 'blank'
            assert len(whole) == 1
            assert not any(e.attrib.get('class') in ('part', 'division') for e in group)
        center = (float(whole[0].attrib['x']) + float(whole[-1].attrib['x']) + 50) / 2
        for name in ('value-label', 'custom-label'):
            label = next(e for e in group if e.attrib.get('class') == name)
            if label.tag.rsplit('}', 1)[-1] == 'rect':
                assert float(label.attrib['x']) + float(label.attrib['width']) / 2 == center
                assert label.attrib.get('fill') == '#eeeeee'
                assert label.attrib.get('stroke', 'none') == 'none'
            elif 'x' in label.attrib:
                assert float(label.attrib['x']) == center
            else:
                assert float(label.attrib['d'].split()[1]) + 20 == center

    assert [next(e for e in g if e.attrib.get("class") == "custom-label").text for g in groups[5:8]] == ["2⁰", "2¹", "2²"]
