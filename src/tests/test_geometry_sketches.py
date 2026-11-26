from __future__ import annotations

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from requirements import needs_content


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


@pytest.mark.parametrize(
    ("kind", "options", "expected_labels"),
    [
        ("dreieck", "form=allgemein | b=8 cm | alpha=50° | hoehe=ja", ["A", "B", "C", "H", "8 cm", "50°"]),
        ("steigung", "x=7,5 m | h=3,2 m", ["7,5 m", "3,2 m", "s", "α"]),
        ("steigung", "x=24 m | s=26 m | oben=P | unten=A", ["24 m", "26 m", "P", "A"]),
        ("pyramide", "a=10 cm | h=12 cm", ["A", "M", "S", "10 cm", "12 cm"]),
        ("quader", "laenge=9 m | breite=12 m | h=8 m", ["9 m", "12 m", "8 m"]),
    ],
)
def test_sketch_labels_and_auxiliary_lines(tmp_path, kind, options, expected_labels):
    result = render(f"[Skizze {kind} | {options}]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    labels = [element.text for element in drawing.findall(".//svg:text", SVG)]
    assert set(expected_labels) <= set(labels)
    assert drawing.findall(".//svg:path[@stroke-dasharray]", SVG)
    assert "[Skizze" not in result.stdout


@pytest.mark.parametrize(
    ("kind", "options", "expected_labels"),
    [
        ("zahlenschloss", "raeder=3 | ziffern=3", ["1", "2", "3"]),
        ("zahlenschloss", "raeder=5 | ziffern=6", ["1", "2", "3", "4", "5", "6"]),
        ("flaeche", "a=a | innen=a · a", ["a", "a · a"]),
        ("volumen", "a=a | innen=a · a · a", ["a", "a · a · a"]),
        ("kreis", "r=r | innen=π · r²", ["r", "π · r²"]),
        ("zylinder", "r=3 cm | h=5 cm", ["3 cm", "5 cm"]),
        ("zylinder", "r=r | h=h | innen=π · r² · h", ["r", "h", "π · r² · h"]),
        ("tippzettel", "spiele=13 | zeichen=1,0,2", ["Spiel", "Tipp", "1", "0", "2", "13"]),
        ("tippzettel", "spiele=3 | zeichen=+,−", ["Spiel", "Tipp", "+", "−", "3"]),
    ],
)
def test_new_sketch_labels(tmp_path, kind, options, expected_labels):
    result = render(f"[Skizze {kind} | {options}]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    labels = [element.text for element in drawing.findall(".//svg:text", SVG)]
    assert set(expected_labels) <= set(labels)
    assert "[Skizze" not in result.stdout


def test_zahlenschloss_draws_wheel_and_window_per_rad(tmp_path):
    result = render("[Skizze zahlenschloss | raeder=4 | ziffern=5]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    rects = drawing.findall(".//svg:rect", SVG)
    assert len(rects) == 1 + 4 + 4
    windows = [rect for rect in rects if rect.attrib.get("stroke-width") == "3"]
    assert len(windows) == 4
    assert drawing.findall(".//svg:path", SVG)


def test_tippzettel_draws_box_per_zeichen_and_row(tmp_path):
    result = render("[Skizze tippzettel | spiele=13 | zeichen=1,0,2]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    rects = drawing.findall(".//svg:rect", SVG)
    assert len(rects) == 1 + 13 * 3
    numbers = [element.text for element in drawing.findall(".//svg:text", SVG)]
    assert all(str(game) in numbers for game in range(1, 14))


def test_volumen_hides_back_edges_and_flaeche_stays_plain(tmp_path):
    result = render("::: {.abbildungen cols=2}\n[Skizze volumen]\n\n[Skizze flaeche]\n:::", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawings = [ET.parse(path).getroot() for path in tmp_path.glob("*.svg")]
    assert len(drawings) == 2
    cube = next(root for root in drawings if root.findall(".//svg:path[@stroke-dasharray]", SVG))
    square = next(root for root in drawings if not root.findall(".//svg:path", SVG))
    assert len(cube.findall(".//svg:path[@stroke-dasharray]", SVG)) == 3
    assert len(square.findall(".//svg:rect", SVG)) == 1


def test_kreis_draws_circle_and_zylinder_draws_ellipse_with_bottom_arc(tmp_path):
    result = render(
        "::: {.abbildungen cols=2}\n[Skizze kreis | r=4 cm]\n\n[Skizze zylinder | r=3 cm | h=7 cm]\n:::",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawings = [ET.parse(path).getroot() for path in tmp_path.glob("*.svg")]
    kreis, zylinder = (
        (drawings[0], drawings[1])
        if any(circle.attrib.get("r") == "88" for circle in drawings[0].findall(".//svg:circle", SVG))
        else (drawings[1], drawings[0])
    )
    assert len(kreis.findall(".//svg:circle", SVG)) == 2
    assert len(zylinder.findall(".//svg:ellipse", SVG)) == 1
    arcs = [path for path in zylinder.findall(".//svg:path", SVG) if " A " in path.attrib["d"]]
    assert len(arcs) == 1


@pytest.mark.parametrize(("vertex", "index"), [("A", 0), ("B", 1), ("C", 2)])
def test_right_angle_matches_named_vertex(tmp_path, vertex, index):
    result = render(f"[Skizze dreieck | form=recht-{vertex}]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    paths = drawing.findall(".//svg:path", SVG)
    assert len(paths) == 4
    assert sum("A" in path.attrib["d"] for path in paths) == 1
    edges = [list(map(float, re.findall(r"-?\d+(?:\.\d+)?", path.attrib["d"]))) for path in paths[:3]]
    vertices = [edge[:2] for edge in edges]
    origin = vertices[index]
    first = vertices[(index + 1) % 3]
    second = vertices[(index + 2) % 3]
    dot_product = sum((first[axis] - origin[axis]) * (second[axis] - origin[axis]) for axis in (0, 1))
    assert dot_product == pytest.approx(0)
    dots = drawing.findall(".//svg:circle", SVG)
    assert len(dots) == 1
    dot_center = [float(dots[0].attrib["cx"]), float(dots[0].attrib["cy"])]
    assert sum((dot_center[axis] - origin[axis]) ** 2 for axis in (0, 1)) ** 0.5 < 13


def test_label_escaping_and_hidden_label(tmp_path):
    result = render("[Skizze dreieck | a=A & B < C | b=]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    labels = [element.text for element in drawing.findall(".//svg:text", SVG)]
    assert "A & B < C" in labels
    assert "b" not in labels


def test_rotated_triangle_keeps_right_angle_and_upright_custom_labels(tmp_path):
    result = render(
        "[Skizze dreieck | form=recht-A | drehung=137 | A=D | B=F | C=E | a=d | b=f | c=e]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    paths = drawing.findall(".//svg:path", SVG)
    edges = [list(map(float, re.findall(r"-?\d+(?:\.\d+)?", path.attrib["d"]))) for path in paths[:3]]
    origin, first, second = [edge[:2] for edge in edges]
    dot_product = sum((first[axis] - origin[axis]) * (second[axis] - origin[axis]) for axis in (0, 1))
    assert dot_product == pytest.approx(0, abs=0.1)
    labels = drawing.findall(".//svg:text", SVG)
    assert {element.text for element in labels} == {"D", "E", "F", "d", "e", "f"}
    assert not drawing.findall(".//*[@transform]")
    assert all(0 < float(element.attrib["x"]) < 460 and 0 < float(element.attrib["y"]) < 250 for element in labels)


def test_rotated_altitude_stays_perpendicular_to_base(tmp_path):
    result = render("[Skizze dreieck | drehung=35 | hoehe=ja]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    base = drawing.find(".//svg:path", SVG)
    altitude = drawing.find(".//svg:path[@stroke-dasharray]", SVG)
    base_points = list(map(float, re.findall(r"-?\d+(?:\.\d+)?", base.attrib["d"])))
    height_points = list(map(float, re.findall(r"-?\d+(?:\.\d+)?", altitude.attrib["d"])))
    dot_product = sum((base_points[axis + 2] - base_points[axis]) * (height_points[axis + 2] - height_points[axis]) for axis in (0, 1))
    assert dot_product == pytest.approx(0, abs=0.1)


def test_marked_sides_and_angle_are_distinct_and_labelled(tmp_path):
    result = render("[Skizze dreieck | markiert=a,c,beta]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    highlighted = drawing.findall('.//svg:path[@stroke="#b34300"]', SVG)
    assert len(highlighted) == 3
    assert sum("A" in element.attrib["d"] for element in highlighted) == 1
    assert "β" in {element.text for element in drawing.findall(".//svg:text", SVG)}


@pytest.mark.parametrize(
    ("source", "expected_highlights"),
    [
        ("[Skizze steigung | x=7,5 m | h=3,2 m | markiert=h,x | farbe=rot]", 2),
        ("[Skizze quader | laenge=9 m | breite=12 m | h=8 m | markiert=boden,raumdiagonale | farbe=rot]", 2),
        ("[Skizze dreieck | form=stumpf-C | markiert=c,gamma | farbe=rot]", 2),
    ],
)
def test_marked_elements_support_red_solution_color(tmp_path, source, expected_highlights):
    result = render(source, "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert len(drawing.findall('.//svg:path[@stroke="#c62828"]', SVG)) == expected_highlights


def test_red_marker_wraps_text_in_red_typst_span(tmp_path):
    result = render("Korrekt ist: [Rot B) Die Hypotenuse liegt gegenueber.]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    assert '#text(fill: rgb("#c62828"))[B) Die Hypotenuse liegt gegenueber.]' in result.stdout
    assert "[Rot" not in result.stdout


@pytest.mark.parametrize("source", ["[Skizze kugel]", "[Skizze dreieck | form=falsch]", "[Skizze dreieck | unbekannt=1]", "[Skizze dreieck | form=recht-C | hoehe=ja]", "[Skizze dreieck | drehung=falsch]", "[Skizze dreieck | markiert=d]", "[Skizze quader | drehung=30]", "[Skizze dreieck | farbe=gruen]", "[Skizze steigung | markiert=a]", "[Skizze quader | markiert=boden,seil]", "[Skizze zahlenschloss | raeder=7]", "[Skizze zahlenschloss | ziffern=10]", "[Skizze tippzettel | spiele=15]", "[Skizze tippzettel | zeichen=1]", "[Skizze flaeche | markiert=a]", "[Skizze volumen | drehung=20]"])
def test_invalid_sketch_reports_error(tmp_path, source):
    result = render(source, "typst", tmp_path)
    assert result.returncode != 0
    assert "Skizze:" in result.stderr


@pytest.mark.skipif(shutil.which("rsvg-convert") is None, reason="rsvg-convert fehlt")
def test_sketch_grid_supports_latex_and_preserves_labels(tmp_path):
    source = "::: {.abbildungen .list-abc}\n[Skizze steigung]\n\n[Skizze quader]\n:::"
    result = render(source, "latex", tmp_path)
    assert result.returncode == 0, result.stderr
    assert len(list(tmp_path.glob("*.pdf"))) == 2
    assert "\\textbf{a)}" in result.stdout
    assert "\\textbf{b)}" in result.stdout
    assert "[Skizze" not in result.stdout


def test_float_right_collects_following_text_beside_figures(tmp_path):
    source = (
        "::: {.abbildungen float=right}\n[Skizze steigung | x=24 m | s=26 m]\n:::\n\n"
        "Der Text fließt neben der Abbildung.\n\n[Rechengitter 0.5 | 2 | 36]\n"
    )
    result = render(source, "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "#grid(" in result.stdout
    assert "columns: (1fr, 34%)" in result.stdout
    assert "Der Text fließt neben der Abbildung." in result.stdout
    assert result.stdout.index("#grid(") < result.stdout.index("Der Text fließt")
    assert result.stdout.index("#grid(") < result.stdout.index("#answer_grid")
    assert "[Skizze" not in result.stdout


def test_float_right_keeps_abc_labels_and_stops_at_marker(tmp_path):
    source = (
        "::: {.abbildungen .list-abc float=right}\n[Skizze steigung]\n\n[Skizze quader]\n:::\n\n"
        "a) Erste Teilaufgabe.\n\nb) Zweite Teilaufgabe.\n\n[Seitenumbruch]\n"
    )
    result = render(source, "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "columns: (1fr, 34%)" in result.stdout
    assert 'text(weight: "bold")[a)]' in result.stdout
    assert 'text(weight: "bold")[b)]' in result.stdout
    assert "Erste Teilaufgabe." in result.stdout
    assert result.stdout.index("#grid(") < result.stdout.index("#pagebreak")


@pytest.mark.skipif(shutil.which("rsvg-convert") is None, reason="rsvg-convert fehlt")
def test_float_left_renders_latex_minipages(tmp_path):
    source = (
        "::: {.abbildungen float=left breite=40%}\n[Skizze steigung]\n:::\n\n"
        "Text links neben der Abbildung.\n"
    )
    result = render(source, "latex", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "\\begin{minipage}[t]{0.4000\\linewidth}\\centering" in result.stdout
    assert "\\begin{minipage}[t]{0.5700\\linewidth}" in result.stdout
    assert "Text links neben der Abbildung." in result.stdout
    assert "[Skizze" not in result.stdout


@pytest.mark.parametrize("value", ["float=oben", "float=rechts-links"])
def test_invalid_float_direction_reports_error(tmp_path, value):
    source = f"::: {{.abbildungen {value}}}\n[Skizze steigung]\n:::"
    result = render(source, "typst", tmp_path)
    assert result.returncode != 0
    assert "float-Richtung" in result.stderr


@needs_content("unterricht/mathematik/klasse-10/trigonometrie")
@pytest.mark.skipif(not shutil.which("pdflatex") or not shutil.which("rsvg-convert"), reason="PDF-Werkzeuge fehlen")
def test_self_diagnosis_renders_two_native_landscape_pages(tmp_path):
    import pymupdf

    source = ROOT / "unterricht/mathematik/klasse-10/trigonometrie/arbeitsblaetter/ab_07-selbstdiagnosebogen-entwurf.qmd"
    content = source.read_text(encoding="utf-8")
    assert "importbild" not in content
    assert "importseite" not in content
    document = tmp_path / source.name
    document.write_text(
        content.replace("- exam.lua", f"- {ROOT}/src/quarto/filters/exam.lua")
        .replace("template: latex-template.tex", f"template: {ROOT}/src/quarto/templates/latex-template.tex")
        .replace("include-in-header: exam-header.tex", f"include-in-header: {ROOT}/src/quarto/templates/exam-header.tex"),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["quarto", "render", str(document), "--to", "pdf"],
        cwd=tmp_path, capture_output=True, text=True, timeout=90, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with pymupdf.open(document.with_suffix(".pdf")) as rendered:
        assert len(rendered) == 2
        for page in rendered:
            assert page.rect.width == pytest.approx(841.89, abs=0.1)
            assert page.rect.height == pytest.approx(595.28, abs=0.1)
            assert not page.get_images(full=True)
        assert "Hypotenuse" in rendered[0].get_text()
        assert "Lösungen zur Selbstkontrolle" in rendered[1].get_text()
        assert "Stadtmauer" in rendered[1].get_text()


SEGMENT = re.compile(r"M (-?[\d.]+) (-?[\d.]+) L (-?[\d.]+) (-?[\d.]+)")


def _text_boxes(drawing):
    groups = drawing.findall(".//svg:g[@font-size]", SVG)
    inherited = float(groups[0].attrib["font-size"]) if len(groups) == 1 else 17.0
    boxes = []
    for element in drawing.findall(".//svg:text", SVG):
        x, y = float(element.attrib["x"]), float(element.attrib["y"])
        text = "".join(element.itertext())
        size = float(element.attrib.get("font-size", inherited))
        width = len(text) * size * 0.6
        anchor = element.attrib.get("text-anchor", "start")
        x0 = x - width / 2 if anchor == "middle" else (x - width if anchor == "end" else x)
        boxes.append(((x0, y - size * 0.75, x0 + width, y + size * 0.25), text))
    return boxes


def _segments(drawing):
    segments = []
    for path in drawing.findall(".//svg:path", SVG):
        match = SEGMENT.fullmatch(path.attrib["d"])
        if match:
            x1, y1, x2, y2 = map(float, match.groups())
            segments.append(((x1, y1), (x2, y2), path))
    return segments


def _boxes_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _segment_hits_box(start, end, box, margin=1.0):
    x0, y0, x1, y1 = box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin
    dx, dy = end[0] - start[0], end[1] - start[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, start[0] - x0), (dx, x1 - start[0]), (-dy, start[1] - y0), (dy, y1 - start[1])):
        if p == 0:
            if q < 0:
                return False
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return False
                t0 = max(t0, r)
            else:
                if r < t0:
                    return False
                t1 = min(t1, r)
    return True


def _segments_cross(a, b):
    (x1, y1), (x2, y2) = a
    (x3, y3), (x4, y4) = b
    denominator = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(denominator) < 1e-9:
        return False
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / denominator
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / denominator
    return 0.001 < t < 0.999 and 0.001 < u < 0.999


def _filled_triangle_points(path_data):
    tokens = path_data.split()
    assert tokens[0] == "M"
    points = [(float(tokens[1]), float(tokens[2]))]
    index = 3
    while tokens[index] != "Z":
        if tokens[index] == "l":
            x, y = points[-1]
            points.append((x + float(tokens[index + 1]), y + float(tokens[index + 2])))
            index += 3
        elif tokens[index] == "v":
            x, y = points[-1]
            points.append((x, y + float(tokens[index + 1])))
            index += 2
        else:
            raise AssertionError(f"Unerwarteter Pfad-Befehl in {path_data}")
    return points


@pytest.mark.parametrize(
    "source",
    [
        "[Skizze dreieck | form=stumpf-A | b=110 m | c=85 m | alpha=105°]",
        "[Skizze dreieck | form=stumpf-A | b=110 m | c=85 m | alpha=105° | markiert=a,alpha | farbe=rot]",
        "[Skizze dreieck | form=stumpf-C | a=7 cm | b=8 cm | c=11 cm | gamma=γ]",
        "[Skizze dreieck | form=recht-C | a=7 cm | beta=14°]",
        "[Skizze dreieck | form=recht-C | a=5 cm | c=13 cm]",
        "[Skizze dreieck | form=gleichschenklig | a=12 | c=8 | hoehe=ja | h=7]",
        "[Skizze dreieck | form=allgemein | b=8 cm | alpha=50° | hoehe=ja]",
        "[Skizze dreieck | form=allgemein | drehung=150 | beta=β | markiert=a,c,beta]",
        "[Skizze dreieck | form=recht-A | drehung=180 | A=D | B=F | C=E | a=d | b=f | c=e | beta=α | gamma=β]",
        "[Skizze pyramide | a=10 cm | h=12 cm]",
        "[Skizze pyramide | a=12 m | h=8 m | s= | alpha=φ]",
        "[Skizze kreis | r=3,5 cm | innen=π · r²]",
        "[Skizze zylinder | r=2 cm | h=5 cm | innen=π · r² · h]",
    ],
)
def test_sketch_labels_stay_clear_of_lines_and_each_other(tmp_path, source):
    result = render(source, "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    boxes = _text_boxes(drawing)
    for index, (box, text) in enumerate(boxes):
        for other_box, other_text in boxes[index + 1:]:
            assert not _boxes_overlap(box, other_box), f"{text} überlappt {other_text}"
    for start, end, _ in _segments(drawing):
        for box, text in boxes:
            assert not _segment_hits_box(start, end, box), f"{text} wird von Kante {start}->{end} geschnitten"


def test_quader_diagonals_are_drawn_between_hidden_and_visible_edges(tmp_path):
    result = render(
        "[Skizze quader | laenge=9 m | breite=12 m | h=8 m | markiert=boden,raumdiagonale | farbe=rot]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    paths = [path for _, _, path in _segments(drawing)]
    diagonals = [path for path in paths if path.attrib.get("stroke") == "#c62828"]
    assert len(diagonals) == 2
    for diagonal in diagonals:
        x1, y1, x2, y2 = map(float, SEGMENT.fullmatch(diagonal.attrib["d"]).groups())
        diagonal_index = paths.index(diagonal)
        crossings = 0
        for index, path in enumerate(paths):
            if path is diagonal:
                continue
            ox1, oy1, ox2, oy2 = map(float, SEGMENT.fullmatch(path.attrib["d"]).groups())
            if not _segments_cross(((x1, y1), (x2, y2)), ((ox1, oy1), (ox2, oy2))):
                continue
            crossings += 1
            hidden = "stroke-dasharray" in path.attrib
            assert (index < diagonal_index) == hidden, (
                f"Kante {path.attrib['d']} überdeckt die Diagonale in der falschen Reihenfolge"
            )
        assert crossings > 0


@pytest.mark.parametrize(
    "source",
    [
        "[Einheitskreis 120 | markiert=sin,cos]",
        "[Einheitskreis 140 | markiert=sin,cos | farbe=rot]",
        "[Einheitskreis 210 | markiert=sin]",
        "[Einheitskreis 315 | markiert=sin,cos]",
        "[Einheitskreis 75 | punkt=nein]",
    ],
)
def test_unit_circle_axis_labels_stay_clear_of_arc_and_each_other(tmp_path, source):
    result = render(source, "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    boxes = _text_boxes(drawing)
    for index, (box, text) in enumerate(boxes):
        for other_box, other_text in boxes[index + 1:]:
            assert not _boxes_overlap(box, other_box), f"{text} überlappt {other_text}"
    circles = [c for c in drawing.findall(".//svg:circle", SVG) if float(c.attrib["r"]) > 50]
    assert len(circles) == 1
    cx, cy, radius = (float(circles[0].attrib[key]) for key in ("cx", "cy", "r"))
    for box, text in boxes:
        if text not in {"0", "1", "−1", "x", "y"}:
            continue
        nearest_x = min(max(cx, box[0]), box[2])
        nearest_y = min(max(cy, box[1]), box[3])
        nearest = ((cx - nearest_x) ** 2 + (cy - nearest_y) ** 2) ** 0.5
        farthest = max(((cx - px) ** 2 + (cy - py) ** 2) ** 0.5 for px in (box[0], box[2]) for py in (box[1], box[3]))
        assert not nearest <= radius <= farthest, f"{text} liegt auf dem Kreisbogen"


def test_rechenstrich_arrowheads_are_large_filled_triangles(tmp_path):
    result = render("[Modell rechenstrich | knoten=1280, 1300, 1320 | spruenge=+20, +20]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    filled = [
        path for path in drawing.findall(".//svg:path", SVG)
        if "Z" in path.attrib["d"] and path.attrib.get("fill") not in {None, "none"}
    ]
    assert len(filled) == 3
    for path in filled:
        points = _filled_triangle_points(path.attrib["d"])
        assert len(points) == 3
        sides = sorted(
            ((points[i][0] - points[(i + 1) % 3][0]) ** 2 + (points[i][1] - points[(i + 1) % 3][1]) ** 2) ** 0.5
            for i in range(3)
        )
        assert sides[1] >= 12, f"Pfeilspitze {path.attrib['d']} ist zu klein"
