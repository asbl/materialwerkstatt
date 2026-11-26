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


def render(marker: str, media: Path, target: str = "typst") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["quarto", "pandoc", "--from", "markdown", "--to", target,
         "--lua-filter", str(FILTER), "--extract-media", str(media)],
        input=marker, text=True, capture_output=True, timeout=30, check=False,
    )


@pytest.mark.parametrize(("marker", "labels"), [
    ("suchfeld | werte=7,19,42 | mitte=2 | ziel=19", {"7", "19", "42", "Position", "Wert"}),
    ("suchbaum | werte=7,19,42 | ebenen=2", {"7", "19", "42", "Ebene 2"}),
    ("ebenenbaum | ebenen=3", {"Ebene 3"}),
    ("halbierung | start=16 | schritte=4", {"16", "8", "4", "2", "1", "4-mal halbiert"}),
    ("suchablauf", {"Suchbereich leer?", "kein Treffer", "Treffer: Stopp"}),
    ("suchablauf | teil=abbruch", {"Suchbereich leer?", "kein Treffer: Stopp", "Mitte prüfen"}),
    ("suchablauf | teil=vergleich", {"kleiner", "gleich", "größer", "Treffer: Stopp"}),
    ("wachstum | kurven=konstant,logarithmisch | xmax=32 | ymax=6", {"1", "log₂ n", "6", "32"}),
    ("kostenbalken | werte=1,2,3,4", {"Schritte", "Zielposition", "4"}),
    ("operationen | zeilen=2 | spalten=4", {"•"}),
    ("spaltenaddition | oben=573 | unten=683", {"5", "7", "3", "6", "8", "?"}),
    ("spaltenaddition | oben=723573589 | unten=232683589", {"7", "2", "3", "5", "8", "9", "?"}),
    ("suchvergleich", {"100.000.000", "27", "20", "10", "4"}),
])
def test_algorithm_markers_render_as_svg(tmp_path: Path, marker: str, labels: set[str]) -> None:
    result = render(f"[Skizze {marker}]", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert labels <= {element.text for element in drawing.findall(".//svg:text", SVG)}
    assert drawing.attrib["viewBox"].startswith("0 0 800 ")
    assert "[Skizze" not in result.stdout


def test_hidden_values_are_not_exposed_until_checked(tmp_path: Path) -> None:
    result = render("[Skizze suchfeld | werte=17,29,53 | verdeckt=ja | mitte=2]", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    labels = [element.text for element in drawing.findall(".//svg:text", SVG)]
    assert "29" in labels
    assert "17" not in labels
    assert "53" not in labels
    assert labels.count("?") == 2


def test_empty_search_range_is_an_explicit_failure(tmp_path: Path) -> None:
    result = render("[Skizze suchfeld | links=7 | rechts=6 | ziel=35]", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    labels = [element.text for element in drawing.findall(".//svg:text", SVG)]
    assert "Suchbereich leer → kein Treffer" in labels


def test_search_tree_has_one_node_per_value_and_correct_edges(tmp_path: Path) -> None:
    result = render("[Skizze suchbaum | markiert=5,8,6]", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert len(drawing.findall(".//svg:circle", SVG)) == 10
    assert len(drawing.findall(".//svg:path", SVG)) == 9
    assert len(drawing.findall('.//svg:circle[@stroke="#167647"]', SVG)) == 3
    labels = drawing.findall(".//svg:text", SVG)
    root_label = next(element for element in labels if element.text == "27")
    assert root_label.attrib["y"] == "57"


def test_nested_operation_grid_has_one_cell_per_execution(tmp_path: Path) -> None:
    result = render("[Skizze operationen | zeilen=4 | spalten=4]", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert len(drawing.findall(".//svg:text", SVG)) == 16


@pytest.mark.parametrize("marker", [
    "suchfeld | unbekannt=1", "suchfeld | links=-1", "suchfeld | verdeckt=vielleicht",
    "suchfeld | werte=1,2 | links=2 | mitte=1", "suchfeld | offen=99",
    "suchbaum | werte=3,2,1", "suchbaum | ebenen=5", "halbierung | start=8 | schritte=4",
    "operationen | zeilen=9", "wachstum | kurven=unbekannt", "wachstum | xmax=0",
    "kostenbalken | werte=-1,2", "spaltenaddition | oben=123 | unten=45",
    "suchfeld | links=1 | links=2",
    "suchfeld | links=7 | treffer=6", "wachstum | kurven=kosten,schranke | schwelle=1",
    "wachstum | kurven=konstant,linear | schwelle=2",
    "suchablauf | teil=falsch",
    "spaltenaddition | oben=12345678901 | unten=12345678901",
])
def test_invalid_algorithm_options_fail_clearly(tmp_path: Path, marker: str) -> None:
    result = render(f"[Skizze {marker}]", tmp_path)
    assert result.returncode != 0
    assert "Algorithmus-Skizze:" in result.stderr


@pytest.mark.skipif(shutil.which("rsvg-convert") is None, reason="rsvg-convert fehlt")
def test_algorithm_marker_supports_latex_export(tmp_path: Path) -> None:
    result = render("[Skizze suchbaum]", tmp_path, "latex")
    assert result.returncode == 0, result.stderr
    assert next(tmp_path.glob("*.pdf")).read_bytes().startswith(b"%PDF")


def test_model_cache_refreshes_when_algorithm_module_changes(tmp_path: Path, monkeypatch) -> None:
    import excalideck.generator as generator

    copied_filter = tmp_path / "exam.lua"
    copied_module = tmp_path / "algorithm_sketches.lua"
    shutil.copy(FILTER, copied_filter)
    shutil.copy(FILTER.with_name("algorithm_sketches.lua"), copied_module)
    monkeypatch.setattr(generator, "MODEL_FILTER", copied_filter)
    marker = "[Skizze suchfeld | mitte=5]"
    first = generator._render_marker_svg(marker)
    module_source = copied_module.read_text(encoding="utf-8")
    copied_module.write_text(module_source.replace("#1565c0", "#abcdef"), encoding="utf-8")
    second = generator._render_marker_svg(marker)
    assert "#1565c0" in first
    assert "#abcdef" in second
    assert "#1565c0" not in second
