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
    ("angle", "expected_x", "expected_y", "full_circle"),
    [
        ("0", 248, 252, False),
        ("90", 38, 42, False),
        ("180", 45, 155, True),
        ("270", 155, 265, True),
        ("-90", 155, 265, True),
        ("450", 155, 45, True),
        ("22,5", 232.015, 171.636, False),
    ],
)
def test_angle_determines_point_and_circle(tmp_path, angle, expected_x, expected_y, full_circle):
    result = render(f"[Einheitskreis {angle}]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    circles = drawing.findall(".//svg:circle", SVG)
    assert len(circles) == (2 if full_circle else 1)
    point = circles[-1]
    assert float(point.attrib["cx"]) == pytest.approx(expected_x, abs=0.001)
    assert float(point.attrib["cy"]) == pytest.approx(expected_y, abs=0.001)
    assert f"{angle}°" in "".join(drawing.itertext())


def test_multiple_diagrams_are_embedded_in_labelled_grid(tmp_path):
    source = "::: {.abbildungen .list-abc}\n[Einheitskreis 75]\n\n[Einheitskreis 45]\n\n[Einheitskreis 30]\n:::\n"
    result = render(source, "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("image(bytes(") == 3
    assert 'columns: (1fr, 1fr, 1fr)' in result.stdout
    for label in ("a)", "b)", "c)"):
        assert label in result.stdout
    assert "[Einheitskreis" not in result.stdout


@pytest.mark.skipif(shutil.which("rsvg-convert") is None, reason="rsvg-convert fehlt")
def test_latex_grid_uses_extracted_pdf(tmp_path):
    result = render("::: {.abbildungen .list-abc}\n[Einheitskreis 120]\n:::\n", "latex", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "\\begin{minipage}" in result.stdout
    assert "\\includesvg" not in result.stdout
    image = next(tmp_path.glob("*.pdf"))
    assert str(image) in result.stdout
    assert image.read_bytes().startswith(b"%PDF")


def test_invalid_angle_reports_marker_error(tmp_path):
    result = render("[Einheitskreis ungueltig]", "typst", tmp_path)
    assert result.returncode != 0
    assert "Bitte einen Winkel in Grad angeben" in result.stderr


def test_marked_sin_and_cos_segments_are_drawn_in_red(tmp_path):
    result = render("[Einheitskreis 140 | markiert=sin,cos | farbe=rot]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    highlighted = drawing.findall('.//svg:path[@stroke="#c62828"]', SVG)
    assert len(highlighted) == 2
    labels = {element.text: element.attrib.get("fill") for element in drawing.findall(".//svg:text", SVG)}
    assert labels.get("sin") == "#c62828"
    assert labels.get("cos") == "#c62828"


def test_marked_segments_use_default_highlight_color(tmp_path):
    result = render("[Einheitskreis 60 | markiert=cos]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    assert len(drawing.findall('.//svg:path[@stroke="#b34300"]', SVG)) == 1
    assert "sin" not in "".join(drawing.itertext())


@pytest.mark.parametrize("source", ["[Einheitskreis 140 | markiert=tan]", "[Einheitskreis 140 | unbekannt=1]", "[Einheitskreis 140 | farbe=gruen]"])
def test_invalid_circle_option_reports_marker_error(tmp_path, source):
    result = render(source, "typst", tmp_path)
    assert result.returncode != 0
    assert "Einheitskreis:" in result.stderr


def test_circle_without_point_draws_axes_and_full_circle_only(tmp_path):
    result = render("[Einheitskreis | punkt=nein]", "typst", tmp_path)
    assert result.returncode == 0, result.stderr
    drawing = ET.parse(next(tmp_path.glob("*.svg"))).getroot()
    circles = drawing.findall(".//svg:circle", SVG)
    assert len(circles) == 1
    assert drawing.findall('.//svg:path[@fill="#e6e6e6"]', SVG) == []
    text = "".join(drawing.itertext())
    assert "P" not in text
    assert "°" not in text
    for label in ("x", "y", "0", "1", "−1"):
        assert label in text


@pytest.mark.parametrize(
    "source",
    ["[Einheitskreis 140 | punkt=ja]", "[Einheitskreis | punkt=nein | markiert=sin]"],
)
def test_invalid_point_option_reports_marker_error(tmp_path, source):
    result = render(source, "typst", tmp_path)
    assert result.returncode != 0
    assert "Einheitskreis:" in result.stderr
