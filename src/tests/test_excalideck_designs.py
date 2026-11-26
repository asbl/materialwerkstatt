from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from excalideck.generator import SLIDE_HEIGHT, SLIDE_WIDTH, generate_deck
from excalideck.outline import parse_outline
from material_core.designs import DESIGNS
from material_ui.config import AppConfig
from material_ui.slides import SlidesService


def write_outline(path: Path, design: str = "") -> Path:
    path.write_text(
        f"---\ntitle: Brüche entdecken\ndeck-design: '{design}'\n"
        f"format:\n  typst:\n    template: slide-{design or 'template'}.typst\n---\n\n"
        "## Was fällt dir auf?\n\nEin Ganzes, vier Teile.\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("design", DESIGNS, ids=lambda design: design["id"])
def test_all_designs_keep_titles_free_of_motifs(tmp_path, design):
    source = write_outline(tmp_path / "slide.qmd", design["id"])

    data = json.loads(generate_deck(source).read_text(encoding="utf-8"))

    frames = [element for element in data["elements"] if element["type"] == "frame"]
    assert len(frames) == 2
    for frame in frames:
        assert (frame["width"], frame["height"]) == (SLIDE_WIDTH, SLIDE_HEIGHT)
        children = [element for element in data["elements"] if element.get("frameId") == frame["id"]]
        assert any(element["type"] == "image" and element["width"] == SLIDE_WIDTH and element["height"] == SLIDE_HEIGHT for element in children)
        assert len([element for element in children if element["type"] == "image"]) == 1
        assert not any(element["type"] == "text" and element["text"] == design["label"] for element in children)
    assert any(element.get("text") == "Ein Ganzes, vier Teile." for element in data["elements"])
    embedded = [base64.b64decode(item["dataURL"].split(",", 1)[1]).decode() for item in data["files"].values()]
    # Some local designs intentionally have a plain paper background.
    assert all(design["paper"] in svg for svg in embedded)
    assert design["slide_background"] in embedded
    assert design["motif"] not in embedded


@pytest.mark.parametrize("design", DESIGNS, ids=lambda design: design["id"])
def test_title_sheet_centers_heading_for_all_designs(tmp_path, design):
    source = write_outline(tmp_path / "slide.qmd", design["id"])

    data = json.loads(generate_deck(source).read_text(encoding="utf-8"))

    frames = [element for element in data["elements"] if element["type"] == "frame"]
    assert [frame["name"] for frame in frames] == ["Titel", "Was fällt dir auf?"]
    title_frame, content_frame = frames
    texts = [element for element in data["elements"] if element["type"] == "text"]
    title = [
        element for element in texts
        if element["text"] == "Brüche entdecken" and element.get("frameId") == title_frame["id"]
    ]
    assert len(title) == 1, "Decktitel fehlt auf der Titelfolie"
    # Zentriert in der Inhaltsflaeche des Design-Hintergrunds (32, 176, 1536, 644)
    assert title[0]["x"] + title[0]["width"] / 2 == pytest.approx(SLIDE_WIDTH / 2)
    assert title[0]["y"] + title[0]["height"] / 2 == pytest.approx(176 + 644 / 2)
    # Inhaltsfolie unveraendert: Folientitel oben links im Design-Rand
    heading = [
        element for element in texts
        if element["text"] == "Was fällt dir auf?" and element.get("frameId") == content_frame["id"]
    ]
    assert heading[0]["x"] == content_frame["x"] + 64
    assert heading[0]["y"] == 52


@pytest.mark.parametrize("value", ["unbekannt", "../retro", ["retro"], 17])
def test_invalid_design_reports_error(tmp_path, value):
    source = tmp_path / "slide.qmd"
    source.write_text(f"---\ndeck-design: {json.dumps(value)}\n---\n## Folie\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Design|design"):
        generate_deck(source)
    assert not source.with_suffix(".excalidraw").exists()


def test_default_and_explicit_fonts_remain_compatible(tmp_path):
    source = write_outline(tmp_path / "slide.qmd")
    outline = parse_outline(source)
    assert outline.design_id is None
    assert outline.heading_font == "Excalifont"
    assert outline.text_font == "Normal"
    source.write_text("---\ndeck-design: retro\nfont-ueberschriften: Normal\n---\n## Folie\n", encoding="utf-8")
    assert parse_outline(source).heading_font == "Normal"


def test_explicit_design_rebuild_backs_up_annotations(tmp_path):
    source = write_outline(tmp_path / "slide.qmd", "retro")
    service = SlidesService(AppConfig(tmp_path))
    deck, generated = service.ensure(source)
    assert generated
    annotated = json.loads(deck.read_text(encoding="utf-8"))
    annotated["annotation-test"] = "Handschrift erhalten"
    deck.write_text(json.dumps(annotated), encoding="utf-8")
    previous = deck.read_bytes()
    assert service.ensure(source) == (deck, False)
    assert deck.read_bytes() == previous
    write_outline(source, "fussball")
    rebuilt, backup = service.rebuild(source)
    assert backup.read_bytes() == previous
    assert rebuilt.read_bytes() != previous
    updated = rebuilt.read_bytes()
    write_outline(source, "unbekannt")
    with pytest.raises(ValueError, match="Unbekanntes|Template"):
        service.rebuild(source)
    assert rebuilt.read_bytes() == updated
    assert backup.read_bytes() == previous
