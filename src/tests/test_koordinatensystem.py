from __future__ import annotations

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FILTER = ROOT / "src/quarto/filters/exam.lua"
SVG = {"svg": "http://www.w3.org/2000/svg"}
pytestmark = pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")


def render(source: str, target: str, media: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "quarto", "pandoc", "--from", "markdown", "--to", target,
            "--lua-filter", str(FILTER), "--extract-media", str(media),
        ],
        input=source,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def path_points(path: str) -> list[tuple[float, float]]:
    return [tuple(map(float, point.split())) for point in re.split(r" L ", path[2:])]


def test_empty_system_draws_grid_axes_and_labels(tmp_path):
    result = render("[Koordinatensystem | x=-8..8 | y=-10..10]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert drawing.attrib["viewBox"] == "0 0 460 460"
    grid = drawing.findall('.//svg:g[@stroke="#d9d9d9"]/svg:path', SVG)
    assert len(grid) == 38  # 17 senkrechte + 21 waagerechte Rasterlinien
    labels = {element.text for element in drawing.findall(".//svg:text", SVG)}
    assert {"-8", "8", "-10", "10", "0"} <= labels
    assert not drawing.findall('.//svg:path[@stroke="#c62828"]', SVG)
    assert "[Koordinatensystem" not in result.stdout


def test_parabola_passes_through_vertex(tmp_path):
    result = render("[Koordinatensystem | x=-8..8 | y=-10..10 | funktion=parabel | d=-3 | e=-9 | farbe=rot]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    curves = drawing.findall('.//svg:path[@stroke="#c62828"]', SVG)
    assert len(curves) == 1
    points = [point for element in curves for point in path_points(element.attrib["d"])]
    vertex = max(points, key=lambda point: point[1])
    assert vertex[0] == pytest.approx(168.8, abs=0.5)
    assert vertex[1] == pytest.approx(413.6, abs=0.5)


def test_parabola_supports_stretch_factor_and_default_color(tmp_path):
    result = render("[Koordinatensystem | funktion=parabel | a=0,5 | d=2 | e=3]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    curves = drawing.findall('.//svg:path[@stroke="#b34300"]', SVG)
    assert len(curves) == 1
    points = [point for element in curves for point in path_points(element.attrib["d"])]
    vertex = min(points, key=lambda point: (point[0] - 270.8) ** 2 + (point[1] - 168.8) ** 2)
    assert vertex[0] == pytest.approx(270.8, abs=1)  # Scheitel S(2|3) im Bereich -10..10
    assert vertex[1] == pytest.approx(168.8, abs=1)


def test_cubic_graph_supports_readable_labels_and_negative_values(tmp_path):
    result = render(
        "[Koordinatensystem | x=-3..3 | y=-1,5..1,5 | funktion=kubik | schrift=28]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    curves = drawing.findall('.//svg:path[@stroke="#b34300"]', SVG)
    points = [point for element in curves for point in path_points(element.attrib["d"])]
    # Die drei bekannten Punkte (-1|-1), (0|0), (1|1) müssen auf der Kurve liegen.
    for expected in [(162, 298), (230, 230), (298, 162)]:
        assert any(abs(x - expected[0]) < 0.1 and abs(y - expected[1]) < 0.1 for x, y in points)
    assert drawing.find('.//svg:g[@font-size="28"]', SVG) is not None


@pytest.mark.parametrize(
    "source",
    [
        "[Koordinatensystem | x=-8..8 | unbekannt=1]",
        "[Koordinatensystem | funktion=wurzel]",
        "[Koordinatensystem | x=8..-8]",
        "[Koordinatensystem | x=-8..8 | funktion=parabel | d=drei]",
        "[Koordinatensystem | raster=0]",
        "[Koordinatensystem | schrift=0]",
        "[Koordinatensystem | schrift=37]",
    ],
)
def test_invalid_system_reports_marker_error(tmp_path, source):
    result = render(source, "typst", tmp_path)
    assert result.returncode != 0
    assert "Koordinatensystem:" in result.stderr


def test_multiple_expressions_have_independent_colors_and_coordinates(tmp_path):
    result = render(
        '[Koordinatensystem | x=-4..4 | y=-2..6 | funktionen=x^2;1;0.5*x^2 | farben=#b34300;#1565c0;#00897b]',
        'typst', tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    line = drawing.findall('.//svg:path[@stroke="#1565c0"]', SVG)
    assert len(line) == 1
    points = path_points(line[0].attrib['d'])
    assert all(y == pytest.approx(281, abs=0.01) for _, y in points)
    for color, expected in [('#b34300', (332, 128)), ('#00897b', (332, 230))]:
        curves = drawing.findall(f'.//svg:path[@stroke="{color}"]', SVG)
        points = [point for curve in curves for point in path_points(curve.attrib['d'])]
        assert any(abs(x - expected[0]) < 0.1 and abs(y - expected[1]) < 0.1 for x, y in points)


def test_expressions_support_math_functions_and_skip_undefined_values(tmp_path):
    result = render(
        '[Koordinatensystem | funktionen=sqrt(x);sin(x);1/x | farben=#1565c0;#00897b;rot]',
        'typst', tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    assert len(drawing.findall('.//svg:path[@stroke="#c62828"]', SVG)) == 2
    for path in drawing.findall('.//svg:path[@stroke="#1565c0"]', SVG):
        assert all(x >= 230 for x, _ in path_points(path.attrib['d']))


@pytest.mark.parametrize('options', [
    'funktionen=os.execute(x)', 'funktionen=x..x', 'funktionen=x+;',
    'funktionen=x;1 | farben=rot', 'farben=rot', 'funktionen=x | farben=blurple',
])
def test_invalid_expressions_and_color_lists_are_rejected(tmp_path, options):
    result = render(f'[Koordinatensystem | {options}]', 'typst', tmp_path)
    assert result.returncode != 0
    assert 'Koordinatensystem:' in result.stderr


@pytest.mark.parametrize('target,expected', [
    ('typst', '#text(fill: rgb("#1565c0"))['),
    ('latex', r'\color[HTML]{1565C0}'),
    ('html', 'color:#1565c0'),
])
def test_solution_highlight_preserves_math_content(tmp_path, target, expected):
    result = render('Ergebnis: [$3^4=81$]{.loesung}.', target, tmp_path)
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
    assert '81' in result.stdout


def test_function_names_are_opt_in_and_match_curve_colors(tmp_path):
    result = render('[Koordinatensystem | x=-4..4 | y=-2..6 | funktionen=x^2;1 | farben=#b34300;#1565c0 | funktionsnamen=ja]', 'typst', tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    labels = drawing.findall('.//svg:text[@class="function-label"]', SVG)
    assert [(label.text, label.attrib['fill']) for label in labels] == [('y = x²', '#b34300'), ('y = 1', '#1565c0')]
    for label in labels:
        assert 26 <= float(label.attrib['x']) <= 434
        assert 26 <= float(label.attrib['y']) <= 434


@pytest.mark.parametrize('names,expected', [('nein', []), ('f;g', ['f', 'g']), (';Gerade', ['Gerade'])])
def test_custom_and_disabled_function_names(tmp_path, names, expected):
    result = render(f'[Koordinatensystem | funktionen=x^2;1 | funktionsnamen={names}]', 'typst', tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob('*.svg'))).getroot()
    assert [label.text for label in drawing.findall('.//svg:text[@class="function-label"]', SVG)] == expected


def test_function_names_need_matching_graphs(tmp_path):
    result = render('[Koordinatensystem | funktionen=x^2;1 | funktionsnamen=f]', 'typst', tmp_path)
    assert result.returncode != 0
    assert 'funktionsnamen' in result.stderr
