from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FILTER = ROOT / "src/quarto/filters/exam.lua"
SVG = {"svg": "http://www.w3.org/2000/svg"}
pytestmark = pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")


def render(marker, target, media):
    return subprocess.run(
        ["quarto", "pandoc", "--from", "markdown", "--to", target,
         "--lua-filter", str(FILTER), "--extract-media", str(media)],
        input=marker, text=True, capture_output=True, timeout=30, check=False,
    )


def test_number_line_keeps_unknowns_and_escapes_labels(tmp_path):
    result = render(
        "[Modell rechenstrich | knoten=3987,4000,4002 | spruenge=+?,A & B < C]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert {element.text for element in drawing.findall(".//svg:text", SVG)} == {
        "3987", "4000", "4002", "+ □", "A & B < C",
    }
    assert "[Modell" not in result.stdout


def test_number_line_marks_jump_starts_and_renders_blank_placeholders(tmp_path):
    result = render(
        "[Modell rechenstrich | knoten=3987,4000,4002 | spruenge=+_,+_]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert [element.text for element in drawing.findall(".//svg:text", SVG)].count("+ □") == 2
    starts = drawing.findall(".//svg:circle", SVG)
    assert len(starts) == 2
    assert all(start.attrib["cy"] == "51" for start in starts)
    assert float(starts[0].attrib["cx"]) < float(starts[1].attrib["cx"])


def test_dot_array_contains_exact_rows_and_columns_without_result(tmp_path):
    result = render("[Modell punktefeld | zeilen=4 | spalten=6]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    dots = drawing.findall(".//svg:circle", SVG)
    assert len(dots) == 24
    assert len({dot.attrib["cy"] for dot in dots}) == 4
    assert len({dot.attrib["cx"] for dot in dots}) == 6
    assert not drawing.findall(".//svg:text", SVG)


def test_dot_array_gesucht_replaces_column_counts_with_question_mark(tmp_path):
    result = render("[Modell punktefeld | zeilen=4 | spalten=12 | teilung=10 | seiten=ja | produkt=ja | gesucht=ja]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    texts = [element.text for element in drawing.findall(".//svg:text", SVG)]
    assert texts.count("?") == 2
    assert "4" in texts and "40" in texts and "8" in texts  # Zeilenzahl und Produkte bleiben


def test_number_line_subtraction_jumps_go_from_right_to_left(tmp_path):
    result = render("[Modell rechenstrich | knoten=100,80,50 | spruenge=-20,-30]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    starts = drawing.findall(".//svg:circle", SVG)
    assert float(starts[0].attrib["cx"]) > float(starts[1].attrib["cx"])
    nodes = {label.text: float(label.attrib["x"]) for label in drawing.findall(".//svg:text", SVG)}
    assert nodes["100"] > nodes["80"] > nodes["50"]


def _arc_spans(drawing):
    arcs = [path.attrib["d"] for path in drawing.findall(".//svg:path", SVG) if " Q " in path.attrib["d"]]
    return [(float(arc.split()[1]), float(arc.split()[6])) for arc in arcs]


def test_number_line_jump_direction_follows_the_sign(tmp_path):
    result = render("[Modell rechenstrich | knoten=52,12,13 | spruenge=-40,+1]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    nodes = {label.text: float(label.attrib["x"]) for label in drawing.findall(".//svg:text", SVG)}
    assert nodes["12"] < nodes["13"] < nodes["52"]
    spans = _arc_spans(drawing)
    assert spans[0][0] > spans[0][1]
    assert spans[1][0] < spans[1][1]


def test_number_line_estimates_unknown_nodes_from_jumps(tmp_path):
    result = render("[Modell rechenstrich | knoten=63,?,? | spruenge=-30,+2]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    spans = _arc_spans(drawing)
    assert spans[0][0] > spans[0][1]
    assert spans[1][0] < spans[1][1]


def test_number_line_open_mode_draws_only_line_and_nodes(tmp_path):
    result = render("[Modell rechenstrich | knoten=2400,2900,2899 | offen=ja]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert {element.text for element in drawing.findall(".//svg:text", SVG)} == {"2400", "2900", "2899"}
    assert not drawing.findall(".//svg:circle", SVG)
    assert all("Q" not in path.attrib["d"] for path in drawing.findall(".//svg:path", SVG))


def test_number_line_open_mode_accepts_jumps_but_hides_arcs(tmp_path):
    result = render(
        "[Modell rechenstrich | knoten=750,250,253 | spruenge=-500,+3 | offen=ja]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert {element.text for element in drawing.findall(".//svg:text", SVG)} == {"750", "250", "253"}
    assert not drawing.findall(".//svg:circle", SVG)
    assert all("Q" not in path.attrib["d"] for path in drawing.findall(".//svg:path", SVG))


def test_number_line_open_mode_accepts_unknown_node_without_jumps(tmp_path):
    result = render("[Modell rechenstrich | knoten=5203,? | offen=ja]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert {element.text for element in drawing.findall(".//svg:text", SVG)} == {"5203", "?"}
    assert not drawing.findall(".//svg:circle", SVG)
    assert all("Q" not in path.attrib["d"] for path in drawing.findall(".//svg:path", SVG))


def test_place_value_table_preserves_digits_and_zero_positions(tmp_path):
    result = render("[Modell stellenwerttafel | ziffern=4,0,5,0,7,2]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    labels = [label.text for label in drawing.findall(".//svg:text", SVG)]
    assert labels[::2] == ["HT", "ZT", "T", "H", "Z", "E"]
    assert labels[1::2] == ["4", "0", "5", "0", "7", "2"]
    assert len(drawing.findall(".//svg:path", SVG)) == 10


def test_blank_place_value_table_has_only_column_headers(tmp_path):
    result = render("[Modell stellenwerttafel]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert [label.text for label in drawing.findall(".//svg:text", SVG)] == ["HT", "ZT", "T", "H", "Z", "E"]


def test_place_value_cards_preserve_duplicates_and_leave_table_empty(tmp_path):
    result = render("[Modell stellenwerttafel | karten=4,0,5,0,7,2]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert len(drawing.findall(".//svg:rect", SVG)) == 6
    labels = [label.text for label in drawing.findall(".//svg:text", SVG)]
    assert labels[:6] == ["4", "0", "5", "0", "7", "2"]
    assert labels[6:] == ["HT", "ZT", "T", "H", "Z", "E"]
    assert all(float(label.attrib["y"]) < 100 for label in drawing.findall(".//svg:text", SVG))


def test_blank_multiplication_grid_does_not_supply_factors_or_products(tmp_path):
    result = render("[Modell malkreuz]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert len(drawing.findall(".//svg:path", SVG)) == 8
    assert [label.text for label in drawing.findall(".//svg:text", SVG)] == ["×"]


def test_multiplication_grid_fills_decomposition_with_colored_products(tmp_path):
    result = render("[Modell malkreuz | oben=10,4 | links=10,3]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    labels = drawing.findall(".//svg:text", SVG)
    assert [label.text for label in labels] == ["×", "10", "4", "10", "3", "100", "40", "30", "12"]
    fills = [rect.attrib["fill"] for rect in drawing.findall(".//svg:rect", SVG)]
    assert len(fills) == 4
    assert len(set(fills)) == 4
    assert [label.attrib["fill"] for label in labels[5:]] == ["#c62828", "#1565c0", "#2e7d32", "#8a6d00"]


def test_multiplication_grid_preserves_given_cells_without_revealing_answers(tmp_path):
    result = render("[Modell malkreuz | felder=20,?,?,200,?,2,?,8]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    labels = drawing.findall(".//svg:text", SVG)
    assert [label.text for label in labels] == ["×", "20", "200", "2", "8"]
    assert [(label.attrib["x"], label.attrib["y"]) for label in labels[1:]] == [
        ("135", "45"), ("135", "95"), ("50", "145"), ("245", "145"),
    ]
    assert len(drawing.findall(".//svg:path", SVG)) == 8


def test_multiplication_grid_allows_single_factor_decomposition(tmp_path):
    result = render("[Modell malkreuz | oben=14 | links=10,3]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert [label.text for label in drawing.findall(".//svg:text", SVG)] == ["×", "14", "10", "3", "140", "42"]
    assert len(drawing.findall(".//svg:rect", SVG)) == 2
    assert len(drawing.findall(".//svg:path", SVG)) == 7


def test_dimensioned_rectangle_preserves_ratio_without_partitioning(tmp_path):
    result = render("[Modell rechteck | laenge=23 | breite=14 | einheit=cm]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert {label.text for label in drawing.findall(".//svg:text", SVG)} == {"23 cm", "14 cm"}
    edges = drawing.findall(".//svg:path", SVG)[:4]
    height = float(edges[0].attrib["d"].split()[5]) - 40
    width = float(edges[2].attrib["d"].split()[4]) - 45
    assert width / height == pytest.approx(23 / 14, rel=1e-4)


def test_rectangle_partitions_and_dimensions_match_partial_lengths(tmp_path):
    result = render("[Modell rechteck | laenge=20,3 | breite=10,4 | einheit=cm]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert {label.text for label in drawing.findall(".//svg:text", SVG)} == {"20 cm", "3 cm", "10 cm", "4 cm"}
    paths = drawing.findall(".//svg:path", SVG)
    right = float(paths[1].attrib["d"].split()[1])
    bottom = float(paths[0].attrib["d"].split()[5])
    split_horizontal = float(paths[4].attrib["d"].split()[1])
    split_vertical = float(paths[5].attrib["d"].split()[2])
    assert (split_horizontal - 45) / (right - split_horizontal) == pytest.approx(20 / 3, rel=1e-4)
    assert (split_vertical - 40) / (bottom - split_vertical) == pytest.approx(10 / 4, rel=1e-4)


def test_diagnosis_table_uses_editable_markdown_and_embeds_models(tmp_path):
    result = render("""::: {.selbstdiagnose}
| Nr. | Eigene Kompetenzüberschrift | Beispielaufgabe | 🙂 | 😐 | 😕 |
|---|---|---|---|---|---|
| 42 | Neue **Kompetenz** | [Modell rechteck \\| laenge=23 \\| breite=14 \\| einheit=cm] Geänderte Aufgabe.<br>Neue Zeile. | ○ | ○ | ○ |
:::
""", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "#diagnose_tabelle" in result.stdout
    assert "zeile([42]" in result.stdout
    assert "Neue #strong[Kompetenz]" in result.stdout
    assert "Eigene Kompetenzüberschrift" in result.stdout
    assert "Geänderte Aufgabe." in result.stdout
    assert "Neue Zeile." in result.stdout
    assert "#image(bytes(" in result.stdout
    assert "[Modell" not in result.stdout


def test_model_display_width_can_be_set_without_changing_labels(tmp_path):
    result = render("[Modell rechenstrich | knoten=3987,4000,4002 | spruenge=+13,+2 | bildbreite=100mm]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "width: 100mm" in result.stdout
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert {label.text for label in drawing.findall(".//svg:text", SVG)} == {"3987", "4000", "4002", "+13", "+2"}


def test_keep_together_preserves_heading_text_and_model(tmp_path):
    result = render("""::: {.zusammenhalten}
## Eine Lösung

Begründung der Rechnung.

[Modell rechenstrich | knoten=3987,4000,4002 | spruenge=+13,+2 | bildbreite=100mm]
:::
""", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "#block(breakable: false)[" in result.stdout
    assert "Eine Lösung" in result.stdout
    assert "Begründung der Rechnung." in result.stdout
    assert "width: 100mm" in result.stdout


def test_four_hundred_array_has_four_separated_hundred_blocks(tmp_path):
    result = render("[Modell vierhundertfeld]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    dots = drawing.findall(".//svg:circle", SVG)
    assert len(dots) == 400
    colors = {dot.attrib["fill"] for dot in dots}
    assert len(colors) == 4
    assert all(sum(dot.attrib["fill"] == color for dot in dots) == 100 for color in colors)
    horizontal = sorted({float(dot.attrib["cx"]) for dot in dots})
    vertical = sorted({float(dot.attrib["cy"]) for dot in dots})
    assert len(horizontal) == len(vertical) == 20
    assert horizontal[10] - horizontal[9] > horizontal[1] - horizontal[0]
    assert vertical[10] - vertical[9] > vertical[1] - vertical[0]
    assert not drawing.findall(".//svg:text", SVG)


def test_four_hundred_array_decomposes_product_region_in_malkreuz_colors(tmp_path):
    result = render("[Modell vierhundertfeld | zeilen=14 | spalten=13]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    dots = drawing.findall(".//svg:circle", SVG)
    assert len(dots) == 400
    rects = drawing.findall(".//svg:rect", SVG)
    assert len(rects) == 4
    by_stroke = {rect.attrib["stroke"]: rect for rect in rects}
    assert set(by_stroke) == {"#c62828", "#1565c0", "#2e7d32", "#8a6d00"}
    assert {rect.attrib["fill"] for rect in rects} == {"#fdecea", "#e8f0fb", "#e6f4ea", "#fff8c4"}
    # Zehner mal Zehner (rot): oben links bis zur Zehnerlücke bei 109.5.
    assert by_stroke["#c62828"].attrib["x"] == "13"
    assert by_stroke["#c62828"].attrib["y"] == "13"
    assert by_stroke["#c62828"].attrib["width"] == "96.5"
    assert by_stroke["#c62828"].attrib["height"] == "96.5"
    # Einer mal Einer (gelb): unten rechts hinter der Zehnerlücke.
    assert by_stroke["#8a6d00"].attrib["x"] == "109.5"
    assert by_stroke["#8a6d00"].attrib["y"] == "109.5"
    assert by_stroke["#8a6d00"].attrib["width"] == "33.5"
    assert by_stroke["#8a6d00"].attrib["height"] == "42.5"


def test_four_hundred_array_decomposition_skips_parts_beyond_small_factors(tmp_path):
    result = render("[Modell vierhundertfeld | zeilen=8 | spalten=13]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    rects = drawing.findall(".//svg:rect", SVG)
    assert len(rects) == 2
    assert {rect.attrib["stroke"] for rect in rects} == {"#c62828", "#2e7d32"}


def test_markdown_include_keeps_parent_title_and_processes_models(tmp_path):
    source = tmp_path / "diagnose.qmd"
    source.write_text("---\ntitle: Fremder Titel\n---\n\n[Schülerfelder]\n\n[Modell malkreuz]\n", encoding="utf-8")
    result = render(
        '---\ntitle: Eigener Titel\n---\n\n::: {.markdown-einbinden datei="' + str(source) + '"}\n:::\n',
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "#student_fields()" in result.stdout
    assert "Fremder Titel" not in result.stdout
    assert "[Modell" not in result.stdout
    assert next(tmp_path.glob("*.svg")).is_file()


def test_area_model_preserves_proportions_without_giving_products(tmp_path):
    result = render("[Modell flaeche | oben=20,6 | links=10,4]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert {element.text for element in drawing.findall(".//svg:text", SVG)} == {"20", "6", "10", "4"}
    paths = drawing.findall(".//svg:path", SVG)
    assert len(paths) == 14
    split_x = float(paths[1].attrib["d"].split()[1])
    split_y = float(paths[4].attrib["d"].split()[2])
    assert (split_x - 65) / (430 - split_x) == pytest.approx(20 / 6, rel=1e-4)
    assert (split_y - 35) / (165 - split_y) == pytest.approx(10 / 4, rel=1e-4)
    # Maße: Messlinien mit Endstrichen über dem oberen und am linken Rand
    assert any(path.attrib["d"] == "M 65 25 L 430 25" for path in paths)
    assert any(path.attrib["d"] == "M 30 35 L 30 165" for path in paths)
    assert any(path.attrib["d"] == "M 65 21 L 65 29" for path in paths)
    assert any(path.attrib["d"] == "M 26 35 L 34 35" for path in paths)


@pytest.mark.parametrize("top,left,vertical_count,horizontal_count", [
    ("26", "14", 2, 2),
    ("26", "10,4", 2, 3),
    ("20,6", "14", 3, 2),
])
def test_area_model_only_divides_sides_with_two_values(tmp_path, top, left, vertical_count, horizontal_count):
    result = render(f"[Modell flaeche | oben={top} | links={left}]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert {element.text for element in drawing.findall(".//svg:text", SVG)} == set((top + "," + left).split(","))
    paths = [path.attrib["d"].split() for path in drawing.findall(".//svg:path", SVG)]
    vertical = [path for path in paths if path[2] == "35" and path[5] == "165" and path[1] != "30"]
    horizontal = [path for path in paths if path[1] == "65" and path[4] == "430" and path[2] != "25"]
    assert len(vertical) == vertical_count
    assert len(horizontal) == horizontal_count


@pytest.mark.skipif(shutil.which("rsvg-convert") is None, reason="rsvg-convert fehlt")
def test_undivided_area_model_renders_for_latex(tmp_path):
    result = render("[Modell flaeche | oben=26 | links=14]", "latex", tmp_path)
    assert result.returncode == 0, result.stderr
    assert next(tmp_path.glob("*.pdf")).read_bytes().startswith(b"%PDF")
    assert "[Modell" not in result.stdout


def test_elevation_profile_labels_heights_and_stages(tmp_path):
    result = render("[Modell hoehenprofil | start=1250 | etappen=-380,-220,-450]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert {element.text for element in drawing.findall(".//svg:text", SVG)} == {
        "1250", "870", "650", "200", "-380", "-220", "-450",
    }
    assert len(drawing.findall(".//svg:circle", SVG)) == 4


def test_elevation_profile_open_hides_all_heights_except_start(tmp_path):
    result = render(
        "[Modell hoehenprofil | start=1250 | etappen=-380,-220,-450 | offen=ja]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    labels = [element.text for element in drawing.findall(".//svg:text", SVG)]
    assert labels.count("?") == 3
    assert "1250" in labels
    assert "870" not in labels and "200" not in labels


def test_elevation_profile_sum_arc_spans_first_to_last_node(tmp_path):
    result = render(
        "[Modell hoehenprofil | start=1250 | etappen=-380,-220,-450 | summe=-1050]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert "-1050" in {element.text for element in drawing.findall(".//svg:text", SVG)}
    arcs = [path for path in drawing.findall(".//svg:path", SVG) if " Q " in path.attrib["d"]]
    assert len(arcs) == 1
    assert arcs[0].attrib["d"].startswith("M 50 ")


def test_elevation_profile_supports_ascents_and_scales_proportionally(tmp_path):
    result = render("[Modell hoehenprofil | start=800 | etappen=+200,-100]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert {element.text for element in drawing.findall(".//svg:text", SVG)} == {
        "800", "1000", "900", "+200", "-100",
    }
    nodes = {element.text: float(element.attrib["y"]) for element in drawing.findall(".//svg:text", SVG)}
    assert nodes["1000"] < nodes["900"] < nodes["800"]


def test_elevation_profile_stage_labels_support_meter_unit(tmp_path):
    result = render(
        "[Modell hoehenprofil | start=2480 | etappen=+20 m,+500 m | offen=ja]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    labels = [element.text for element in drawing.findall(".//svg:text", SVG)]
    assert "+20 m" in labels and "+500 m" in labels
    assert labels.count("?") == 2
    assert "2480" in labels


def test_elevation_profile_stage_labels_sit_on_their_segment(tmp_path):
    result = render("[Modell hoehenprofil | start=2480 | etappen=+20 m,+500 m]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    paths = [path.attrib["d"] for path in drawing.findall(".//svg:path", SVG)]
    assert not [d for d in paths if d.count("L") == 1], "keine Maßlinien parallel zum Abschnitt"
    assert not [d for d in paths if d.endswith("Z")], "keine Pfeilspitzen an den Etappen"
    circles = sorted(drawing.findall(".//svg:circle", SVG), key=lambda c: float(c.attrib["cx"]))
    nodes = [(float(c.attrib["cx"]), float(c.attrib["cy"])) for c in circles]
    stage_labels = [
        element for element in drawing.findall(".//svg:text", SVG)
        if element.attrib.get("paint-order") == "stroke"
    ]
    assert [element.text for element in stage_labels] == ["+20 m", "+500 m"]
    for element, start, finish in zip(stage_labels, nodes, nodes[1:]):
        assert float(element.attrib["x"]) == pytest.approx((start[0] + finish[0]) / 2, abs=0.01)
        assert float(element.attrib["y"]) == pytest.approx((start[1] + finish[1]) / 2 + 5, abs=0.01)


def test_number_line_color_tints_jumps_arrows_and_jump_labels(tmp_path):
    result = render(
        "[Modell rechenstrich | knoten=900,650,500 | spruenge=-250,-150 | farbe=#1565c0]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    arcs = [path for path in drawing.findall(".//svg:path", SVG) if " Q " in path.attrib["d"]]
    assert len(arcs) == 2
    assert all(arc.attrib["stroke"] == "#1565c0" for arc in arcs)
    arrowheads = [path for path in drawing.findall(".//svg:path", SVG) if path.attrib["d"].endswith("Z")]
    assert len(arrowheads) == 3
    assert sorted(head.attrib["fill"] for head in arrowheads) == ["#1565c0", "#1565c0", "#172033"]
    circles = drawing.findall(".//svg:circle", SVG)
    assert len(circles) == 2
    assert all(circle.attrib["fill"] == "#1565c0" for circle in circles)
    jump_labels = [
        element for element in drawing.findall(".//svg:text", SVG)
        if element.text in {"-250", "-150"}
    ]
    assert len(jump_labels) == 2
    assert all(label.attrib["fill"] == "#1565c0" for label in jump_labels)
    node_labels = [
        element for element in drawing.findall(".//svg:text", SVG)
        if element.text in {"900", "650", "500"}
    ]
    assert len(node_labels) == 3
    assert all(label.attrib["fill"] == "#172033" for label in node_labels)


def test_number_line_colors_jumps_by_direction(tmp_path):
    result = render(
        "[Modell rechenstrich | knoten=52,12,13 | spruenge=-40,+1]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    arcs = [path for path in drawing.findall(".//svg:path", SVG) if " Q " in path.attrib["d"]]
    assert len(arcs) == 2
    assert arcs[0].attrib["stroke"] == "#1565c0"
    assert arcs[1].attrib["stroke"] == "#c62828"
    jump_labels = {
        element.text: element.attrib["fill"]
        for element in drawing.findall(".//svg:text", SVG)
        if element.text in {"-40", "+1"}
    }
    assert jump_labels == {"-40": "#1565c0", "+1": "#c62828"}


def _arc_controls(drawing):
    arcs = [path.attrib["d"] for path in drawing.findall(".//svg:path", SVG) if " Q " in path.attrib["d"]]
    return [float(arc.split()[5]) for arc in arcs]


def test_number_line_nested_jumps_arch_by_span(tmp_path):
    result = render(
        "[Modell rechenstrich | knoten=750,250,253 | spruenge=-500,+3]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    controls = _arc_controls(drawing)
    assert len(controls) == 2
    assert controls[0] < controls[1]
    jump_labels = [
        element for element in drawing.findall(".//svg:text", SVG)
        if element.text in {"-500", "+3"}
    ]
    assert all(label.attrib.get("paint-order") == "stroke" for label in jump_labels)


def test_number_line_adjacent_jumps_keep_uniform_height(tmp_path):
    result = render(
        "[Modell rechenstrich | knoten=3987,4000,4002 | spruenge=+13,+2]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert _arc_controls(drawing) == [-5.0, -5.0]


def test_elevation_profile_color_tints_only_the_sum_arc(tmp_path):
    result = render(
        "[Modell hoehenprofil | start=1250 | etappen=-380,-220,-450 | summe=-1050 | farbe=rot]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    arcs = [path for path in drawing.findall(".//svg:path", SVG) if " Q " in path.attrib["d"]]
    assert len(arcs) == 1
    assert arcs[0].attrib["stroke"] == "#c62828"
    arrowheads = [path for path in drawing.findall(".//svg:path", SVG) if path.attrib["d"].endswith("Z")]
    assert len(arrowheads) == 1
    assert arrowheads[0].attrib["fill"] == "#c62828"
    sum_label = [
        element for element in drawing.findall(".//svg:text", SVG)
        if element.text == "-1050"
    ]
    assert len(sum_label) == 1
    assert sum_label[0].attrib["fill"] == "#c62828"
    profile = [path for path in drawing.findall(".//svg:path", SVG) if " Q " not in path.attrib["d"] and not path.attrib["d"].endswith("Z")]
    assert len(profile) == 1
    assert profile[0].attrib["stroke"] == "#172033"
    circles = drawing.findall(".//svg:circle", SVG)
    assert len(circles) == 4
    assert all(circle.attrib["fill"] == "#172033" for circle in circles)


@pytest.mark.parametrize("marker", [
    "[Modell unbekannt]",
    "[Modell hoehenprofil | start=1250]",
    "[Modell hoehenprofil | start=1250 | etappen=-380,-220,-450,-100,-50,-20]",
    "[Modell hoehenprofil | start=-1250 | etappen=-380]",
    "[Modell hoehenprofil | start=1250 | etappen=380]",
    "[Modell hoehenprofil | start=1250 | etappen=-380 km]",
    "[Modell hoehenprofil | start=1250 | etappen=-1300]",
    "[Modell hoehenprofil | start=1250 | etappen=-380 | unbekannt=1]",
    "[Modell punktefeld | zeilen=2.5 | spalten=6]",
    "[Modell punktefeld | zeilen=13 | spalten=6]",
    "[Modell punktefeld | zeilen=4 | spalten=6 | ergebnis=24]",
    "[Modell punktefeld | zeilen=4 | spalten=6 | gesucht=ja]",
    "[Modell punktefeld | zeilen=4 | spalten=6 | seiten=ja | gesucht=nein]",
    "[Modell flaeche | oben=20,-6 | links=10,4]",
    "[Modell flaeche | oben=20,6,1 | links=10,4]",
    "[Modell flaeche | oben=26]",
    "[Modell flaeche | oben=26 | links=0]",
    "[Modell rechenstrich | knoten=1,2,3 | spruenge=+1]",
    "[Modell rechenstrich | knoten=1,2 | spruenge=+1 | farbe=gruen]",
    "[Modell rechenstrich | knoten=100,90 | spruenge=+10]",
    "[Modell rechenstrich | knoten=2400 | offen=ja]",
    "[Modell rechenstrich | knoten=2400,2900 | spruenge=+500,+1 | offen=ja]",
    "[Modell hoehenprofil | start=1250 | etappen=-380 | farbe=gruen]",
    "[Modell rechteck | laenge=0 | breite=14]",
    "[Modell rechteck | laenge=23 | breite=-1]",
    "[Modell rechteck | laenge=20,0 | breite=10,4]",
    "[Modell rechteck | laenge=20,3,2 | breite=10,4]",
    "[Modell stellenwerttafel | ziffern=4,0,5]",
    "[Modell stellenwerttafel | ziffern=4,0,12,0,7,2]",
    "[Modell stellenwerttafel | karten=4,0,5]",
    "[Modell stellenwerttafel | karten=4,0,12,0,7,2]",
    "[Modell vierhundertfeld | bildbreite=9mm]",
    "[Modell vierhundertfeld | bildbreite=75%]",
    "[Modell vierhundertfeld | zeilen=14]",
    "[Modell vierhundertfeld | zeilen=14 | spalten=21]",
    "[Modell vierhundertfeld | zeilen=2.5 | spalten=13]",
    "[Modell malkreuz | oben=10,4]",
    "[Modell malkreuz | oben=10,4 | links=10,3,5,7]",
    "[Modell malkreuz | oben=10,4 | links=0,3]",
    "[Modell malkreuz | oben=14 | links=13]",
    "[Modell malkreuz | oben=10,4.5 | links=10,3]",
    "[Modell malkreuz | felder=20,?,200]",
    "[Modell malkreuz | felder=20,?,?,200,?,2,?,8 | oben=20,4 | links=10,2]",
    "[Modell malkreuz | felder=20,?,?,200,?,2,?,oops]",
    "[Modell malkreuz | felder=20,?,?,200,?,0,?,8]",
])
def test_invalid_models_fail_with_actionable_error(tmp_path, marker):
    result = render(marker, "typst", tmp_path)
    assert result.returncode != 0
    assert "Modell" in result.stderr


@pytest.mark.skipif(shutil.which("rsvg-convert") is None, reason="rsvg-convert fehlt")
def test_latex_uses_pdf_model(tmp_path):
    result = render("[Modell punktefeld | zeilen=3 | spalten=7]", "latex", tmp_path)
    assert result.returncode == 0, result.stderr
    assert next(tmp_path.glob("*.pdf")).read_bytes().startswith(b"%PDF")
    assert "[Modell" not in result.stdout


def test_punktefeld_can_show_product(tmp_path):
    result = render("[Modell punktefeld | zeilen=3 | spalten=5 | produkt=ja]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert [element.text for element in drawing.findall(".//svg:text", SVG)] == ["15"]
    assert len(drawing.findall(".//svg:circle", SVG)) == 15


def test_vierhundertfeld_labels_split_products_and_marks_side(tmp_path):
    result = render(
        "[Modell vierhundertfeld | zeilen=16 | spalten=18 | zerlegung=spalten | produkte=ja | seite=zeilen]",
        "typst", tmp_path,
    )
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert sorted(element.text for element in drawing.findall(".//svg:text", SVG)) == ["128", "16", "160"]
    assert len(drawing.findall(".//svg:rect", SVG)) == 2


@pytest.mark.parametrize("marker", [
    "[Modell vierhundertfeld | produkte=ja]",
    "[Modell vierhundertfeld | zeilen=16 | spalten=18 | seite=unten]",
    "[Modell vierhundertfeld | zeilen=16 | spalten=18 | zerlegung=diagonal]",
    "[Modell punktefeld | zeilen=3 | spalten=5 | produkt=nein]",
])
def test_new_model_options_reject_invalid_values(tmp_path, marker):
    assert render(marker, "typst", tmp_path).returncode != 0


def test_punktefeld_tight_crop_keeps_product_inside(tmp_path):
    result = render("[Modell punktefeld | zeilen=3 | spalten=5 | produkt=ja | zuschnitt=eng]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert float(drawing.attrib["width"]) < 200
    label = drawing.find(".//svg:text", SVG)
    assert float(label.attrib["y"]) < float(drawing.attrib["height"])
    assert render("[Modell punktefeld | zeilen=3 | spalten=5 | zuschnitt=weit]", "typst", tmp_path).returncode != 0


def test_punktefeld_teilung_zeichnet_farbige_teilfelder_mit_mittiger_zahl(tmp_path):
    result = render("[Modell punktefeld | zeilen=6 | spalten=14 | teilung=10 | produkt=ja | seiten=ja | bildbreite=50mm]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    rects = drawing.findall(".//svg:rect", SVG)
    assert len(rects) == 2
    assert {rect.attrib["stroke"] for rect in rects} == {"#c62828", "#1565c0"}
    texts = [text.text for text in drawing.findall(".//svg:text", SVG)]
    assert sorted(texts) == sorted(["60", "24", "6", "10", "4"])
    width, height = float(drawing.attrib["width"]), float(drawing.attrib["height"])
    for rect in rects:
        assert float(rect.attrib["x"]) >= 0 and float(rect.attrib["x"]) + float(rect.attrib["width"]) <= width
    for text in drawing.findall(".//svg:text", SVG):
        assert 0 < float(text.attrib["y"]) < height
    # Zahl liegt mittig im jeweiligen Teilfeld.
    for rect in rects:
        centre = float(rect.attrib["x"]) + float(rect.attrib["width"]) / 2
        assert any(abs(float(text.attrib["x"]) - centre) < 0.01 and text.text in {"60", "24"} for text in drawing.findall(".//svg:text", SVG))


def test_punktefeld_seiten_ohne_teilung_nennt_zeilen_und_spalten(tmp_path):
    result = render("[Modell punktefeld | zeilen=5 | spalten=13 | seiten=ja]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert sorted(text.text for text in drawing.findall(".//svg:text", SVG)) == ["13", "5"]
    assert not drawing.findall(".//svg:rect", SVG)


@pytest.mark.parametrize("marker", [
    "[Modell punktefeld | zeilen=3 | spalten=5 | teilung=5]",
    "[Modell punktefeld | zeilen=3 | spalten=5 | teilung=x]",
    "[Modell punktefeld | zeilen=3 | spalten=5 | seiten=nein]",
])
def test_punktefeld_teilung_und_seiten_lehnen_ungueltige_werte_ab(tmp_path, marker):
    assert render(marker, "typst", tmp_path).returncode != 0


def test_aufgabenzeilen_highlights_rows_with_bold_task_label(tmp_path):
    table = (
        "::: {.aufgabenzeilen}\n| Lösung | Übung |\n|:--|:--|\n"
        "| ☐ **1a)** richtig | – |\n| ☐ falsch | S. 1 |\n| ☐ **1b)** richtig | – |\n:::\n"
    )
    result = render(table, "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "#let aufgaben-anfaenge = (1, 3,)" in result.stdout
