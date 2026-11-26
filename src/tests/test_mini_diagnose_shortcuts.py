from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILTER = ROOT / 'src/quarto/filters/exam.lua'
pytestmark = pytest.mark.skipif(shutil.which('quarto') is None, reason='Quarto fehlt')


def render(source, media, target='typst'):
    return subprocess.run(
        ['quarto', 'pandoc', '-f', 'markdown', '-t', target,
         '--lua-filter', str(FILTER), '--extract-media', str(media)],
        input=source, capture_output=True, text=True, timeout=30,
    )


def test_open_point_field_and_answer_lines_survive_inside_card(tmp_path):
    result = render('''::: {.mini-karte nummer="4" titel="Bild" hoehe="70mm"}
[Modell punktefeld | zeilen=7 | spalten=17 | bildbreite=42mm]

[Schreiblinien 2]
:::
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert '#mini_karte("4", "Bild", height: 70mm)' in result.stdout
    assert '[Modell' not in result.stdout
    assert '[Schreiblinien' not in result.stdout
    svg = ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    assert len(svg.findall('{http://www.w3.org/2000/svg}circle')) == 119
    assert not svg.findall('{http://www.w3.org/2000/svg}rect')


def test_combined_table_preserves_math_linebreaks_and_checkboxes(tmp_path):
    result = render('''::: {.mini-auswertung}
| Nr. | Lösung | Übung |
|---|---|---|
| 1 | $7\\cdot8=56$<br>Andere Wege gelten. | ☐ S. 45, Nr. 5 |
:::
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert '#mini_auswertung(' in result.stdout
    assert '<br>' not in result.stdout
    assert 'Andere Wege gelten.' in result.stdout
    assert '☐' in result.stdout
    assert 'S. 45' in result.stdout


@pytest.mark.parametrize('source, message', [
    ('::: {.mini-karte hoehe="0mm"}\nText\n:::', 'Mini-Karte'),
    ('::: {.mini-karte hoehe="30mm);panic()"}\nText\n:::', 'Mini-Karte'),
    ('::: {.mini-auswertung}\nText\n:::', 'Mini-Auswertung'),
    ('::: {.mini-auswertung}\n| A | B |\n|---|---|\n| 1 | 2 |\n:::', 'drei Spalten'),
])
def test_invalid_layout_fails_with_useful_error(source, message, tmp_path):
    result = render(source, tmp_path)
    assert result.returncode != 0
    assert message in result.stderr


def test_latex_keeps_content_without_typst_commands(tmp_path):
    result = render('::: {.mini-karte titel="Rechnen"}\n$7\\cdot8=56$\n:::', tmp_path, 'latex')
    assert result.returncode == 0, result.stderr
    assert '56' in result.stdout
    assert '#mini_' not in result.stdout
