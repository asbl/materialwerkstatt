"""Generated examples preserve place values and work inside generic dialogues."""
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import pytest

ROOT = Path(__file__).resolve().parents[2]
FILTER = ROOT / 'src/quarto/filters/exam.lua'
NS = {'s': 'http://www.w3.org/2000/svg'}
pytestmark = pytest.mark.skipif(shutil.which('quarto') is None, reason='Quarto fehlt')


def render(source, tmp_path, target="typst"):
    return subprocess.run(['quarto', 'pandoc', '-f', 'markdown', '-t', target,
                           '--lua-filter', str(FILTER), '--extract-media', str(tmp_path)],
                          input=source, text=True, capture_output=True, timeout=30)


@pytest.mark.parametrize('a,b,zero', [(356,17,'nein'), (346,107,'ja'), (346,107,'nein'),
                                     (68,8,'nein'), (544,125,'nein'), (0,305,'ja'),
                                     (999999,999999,'nein'), (12,100,'nein'), (12,0,'ja'), (0,305,'nein')])
def test_products_and_digit_columns(a,b,zero,tmp_path):
    output = render(f'[Modell schriftlich | aufgabe={a}*{b} | nullzeile={zero}]',tmp_path)
    assert output.returncode == 0, output.stderr
    drawing=ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    texts=drawing.findall('s:text',NS)
    task=[t for t in texts if t.get('class') == 'aufgabenziffer']
    assert ''.join(t.text for t in task) == f'{a}·{b}'
    units=float(task[-1].get('x'))
    rows={}
    for t in texts:
        if t.get('class') not in {'teilprodukt','ergebnisziffer'}: continue
        place=int(t.get('data-stelle'))
        assert float(t.get('x')) == units-28*place
        key=t.get('class'),t.get('y')
        rows[key]=rows.get(key,0)+int(t.text)*10**place
    assert [v for (kind,_),v in rows.items() if kind == 'ergebnisziffer'] == [a*b]
    partials=[v for (kind,_),v in rows.items() if kind == 'teilprodukt']
    if partials: assert sum(partials) == a*b
    if zero=='nein' and a != 0: assert 0 not in partials


@pytest.mark.parametrize('args', ['aufgabe=12*_', 'aufgabe=01*2', 'aufgabe=1234567*2',
                                  'aufgabe=12*3 | nullzeile=vielleicht',
                                  'aufgabe=12*3 | bildbreite=2mm', 'aufgabe=12*3 | falsch=ja', 'aufgabe=12*3 | gruppen=falsch',
                                  'aufgabe=12*3 | endnullen=falsch', 'aufgabe=12*3 | teilrechnungen=falsch'])
def test_invalid_options_fail(args,tmp_path):
    output=render('[Modell schriftlich | '+args+']',tmp_path)
    assert output.returncode != 0
    assert 'Modell schriftlich' in output.stderr


@pytest.mark.parametrize('task,zero,expected,notes', [
    ('346*107', 'nein', ['34600', '2422'], ['346 · 100', '346 · 7']),
    ('346*107', 'ja', ['34600', '0000', '2422'], ['346 · 100', '346 · 0', '346 · 7']),
    ('68*8', 'nein', [], ['68 · 8']),
])
def test_trailing_zeros_and_partial_task_labels(task, zero, expected, notes, tmp_path):
    output = render(f'[Modell schriftlich | aufgabe={task} | nullzeile={zero} | endnullen=ja | teilrechnungen=ja]', tmp_path)
    assert output.returncode == 0, output.stderr
    drawing = ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    rows = {}
    for t in drawing.findall('s:text', NS):
        if t.get('class') == 'teilprodukt':
            rows[t.get('y')] = rows.get(t.get('y'), '') + t.text
    assert list(rows.values()) == expected
    labels = [t for t in drawing.findall('s:text', NS) if t.get('class') == 'teilrechnung']
    assert [t.text for t in labels] == notes
    assert all(float(t.get('x')) < float(drawing.get('width')) for t in labels)


def test_three_part_malkreuz_has_all_six_products(tmp_path):
    output=render('[Modell malkreuz | oben=300,50,6 | links=10,7]',tmp_path)
    assert output.returncode==0,output.stderr
    root=ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    labels=[t.text for t in root.findall('s:text',NS)]
    assert all(str(v) in labels for v in [3000,500,60,2100,350,42])


def test_dialogue_colors_and_models_remain_generic(tmp_path):
    source=''':::: {.schuelerdialog}
::: {.dialogbeitrag name="Anna" figur="zopf" haarfarbe="#abcdef"}
Ich rechne.

[Modell schriftlich | aufgabe=356*17]
:::
::: {.dialogbeitrag name="Ben" figur="kurz" haarfarbe="#fedcba"}
Ich prüfe.
:::
::::'''
    output=render(source,tmp_path)
    assert output.returncode==0,output.stderr
    assert '[Modell' not in output.stdout and 'Anna' in output.stdout and 'Ben' in output.stdout
    svg=''.join(p.read_text() for p in tmp_path.glob('*.svg'))
    assert '#abcdef' in svg and '#fedcba' in svg


def test_input_table_inside_columns_is_rendered(tmp_path):
    source=''':::: {.columns}
::: {.column}
[Eingabetabelle 8mm]

| Zahl | Ergebnis |
|---|---|
| 34 | [Antwortlinie füllend] |

[/Eingabetabelle]
:::
::: {.column}
Text
:::
::::'''
    output=render(source,tmp_path)
    assert output.returncode==0,output.stderr
    assert '[Eingabetabelle' not in output.stdout and '[Antwortlinie' not in output.stdout


@pytest.mark.skipif(shutil.which('node') is None, reason='Node fehlt')
def test_editor_validates_written_model_options():
    script=f'''
import assert from 'node:assert/strict';
import {{SHORTCUTS}} from {(ROOT / 'src/material_ui/static/shortcuts.js').as_uri()!r};
import {{shortcutFields, shortcutErrors}} from {(ROOT / 'src/material_ui/static/shortcut-options.js').as_uri()!r};
const item=SHORTCUTS.find(i=>i.id==='modell-schriftlich');
const fields=shortcutFields(item), values=fields.map(f=>f.value);
assert.deepEqual(fields[1].choices,['ja','nein']);
assert(shortcutErrors(item,fields,values).every(e=>!e));
values[0]='12*_';
assert(shortcutErrors(item,fields,values)[0]);
values[0]='346*107'; values[2]='2mm';
assert(shortcutErrors(item,fields,values)[2]);
'''
    result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('a,b', [(12,0), (12,100)])
def test_single_partial_row_is_preserved_for_zero_and_shifted_multipliers(a,b,tmp_path):
    output=render(f'[Modell schriftlich | aufgabe={a}*{b} | nullzeile=ja]',tmp_path)
    assert output.returncode==0,output.stderr
    root=ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    partials=root.findall('s:text[@class="teilprodukt"]',NS)
    assert partials  # Explicit nullzeile must also work for multiplication by zero.
    if b==0: assert ''.join(t.text for t in partials)=='00'


def test_group_colors_connect_malkreuz_rows_to_written_partial_products(tmp_path):
    source="""[Modell malkreuz | oben=300,50,6 | links=10,7 | gruppen=zeilen]

[Modell schriftlich | aufgabe=356*17 | gruppen=zeilen]"""
    output=render(source,tmp_path)
    assert output.returncode==0,output.stderr
    roots=[ET.parse(p).getroot() for p in tmp_path.glob('*.svg')]
    malkreuz=next(r for r in roots if r.findall('s:rect',NS))
    written=next(r for r in roots if r.findall('s:text[@class="teilprodukt"]',NS))
    labels={t.text:t.get('fill') for t in malkreuz.findall('s:text',NS)}
    partials=written.findall('s:text[@class="teilprodukt"]',NS)
    rows={}
    for t in partials: rows.setdefault(t.get('y'),set()).add(t.get('fill'))
    assert list(rows.values())==[{labels['3000']},{labels['2100']}]
    assert labels['3000']==labels['500']==labels['60']
    assert labels['2100']==labels['350']==labels['42']
    assert labels['3000']!=labels['2100']


def test_large_malkreuz_values_fit_three_column_cells(tmp_path):
    output=render('[Modell malkreuz | oben=10000,10000,10000 | links=10000,10000,10000]',tmp_path)
    assert output.returncode==0,output.stderr
    root=ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    products=[t for t in root.findall('s:text',NS) if t.text=='100000000']
    assert len(products)==9
    for text in products:
        assert len(text.text)*float(text.get('font-size'))*0.65 <= 220/3-9


@pytest.mark.skipif(shutil.which('rsvg-convert') is None, reason='rsvg-convert fehlt')
def test_written_model_also_exports_to_latex(tmp_path):
    output=render('[Modell schriftlich | aufgabe=346*107 | nullzeile=ja]',tmp_path,'latex')
    assert output.returncode==0,output.stderr
    assert '[Modell' not in output.stdout
    files=list(tmp_path.glob('*.pdf'))
    assert len(files)==1 and files[0].read_bytes().startswith(b'%PDF')


def test_lowercase_input_table_markers_are_accepted(tmp_path):
    source="""[eingabetabelle 8mm]

| Zahl | Ergebnis |
|---|---|
| 34 | [Antwortlinie füllend] |

[/eingabetabelle]"""
    output=render(source,tmp_path)
    assert output.returncode==0,output.stderr
    assert '[eingabetabelle' not in output.stdout and '[/eingabetabelle]' not in output.stdout


def test_project_filter_delegates_to_frozen_filter_and_its_helpers(tmp_path):
    import os
    frozen = tmp_path / 'frozen'
    frozen.mkdir()
    (frozen / 'helper.lua').write_text('return "PINNED_HELPER"')
    (frozen / 'exam.lua').write_text('''
function Str(el)
  if el.text == "TOKEN" then
    return pandoc.Str(dofile(pandoc.path.directory(PANDOC_SCRIPT_FILE) .. "/helper.lua"))
  end
end
''')
    result = subprocess.run(
        ['quarto', 'pandoc', '-f', 'markdown', '-t', 'plain', '--lua-filter', str(FILTER)],
        input='TOKEN', text=True, capture_output=True, timeout=30,
        env={**os.environ, 'MATERIAL_TEMPLATE_FILTER_DIR': str(frozen)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'PINNED_HELPER'


def test_project_filter_does_not_silently_ignore_missing_frozen_filter(tmp_path):
    import os
    result = subprocess.run(
        ['quarto', 'pandoc', '-f', 'markdown', '-t', 'plain', '--lua-filter', str(FILTER)],
        input='TOKEN', text=True, capture_output=True, timeout=30,
        env={**os.environ, 'MATERIAL_TEMPLATE_FILTER_DIR': str(tmp_path / 'missing')},
    )
    assert result.returncode != 0
    assert 'exam.lua' in result.stderr
