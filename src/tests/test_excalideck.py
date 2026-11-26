from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path

import pytest

from excalideck.generator import (
    SLIDE_HEIGHT,
    SLIDE_MARGIN,
    SLIDE_PITCH,
    SLIDE_TITLE_FONTSIZE,
    SLIDE_WIDTH,
    DeckExistsError,
    DeckDependencyError,
    FormulaRenderError,
    ModelRenderError,
    generate_deck,
    FONT_DIRECTORIES,
    _expand_svg_viewbox,
    _math_document,
    _formula_font,
    _render_formula_svg,
    _svg_ink_bbox,
)
from excalideck.outline import (
    DECK_TITLE_FONTSIZE,
    TEXT_FONTSIZE,
    BoxBlock,
    ColumnBlock,
    ColumnsBlock,
    ImageBlock,
    ModelBlock,
    TextBlock,
    parse_outline,
)
from excalideck.printable import (
    PrintableExistsError,
    generate_printable,
    render_printable_qmd,
)
from requirements import needs_excalidraw_fonts

ASSET_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
    '<rect width="120" height="80" fill="#eee"/></svg>'
)


def test_teacher_comments_do_not_create_slides_or_visible_blocks(tmp_path: Path) -> None:
    source = tmp_path / "notizen.md"
    source.write_text("## Sichtbar\n\nAufgabe\n\n<!-- Reflexionsfrage:\n"
                      "## Unsichtbare Überschrift\nWarum gilt das?\n"
                      "[Infobox: Nur Notiz]\n-->\n\nWeiterrechnen\n")
    outline = parse_outline(source)
    assert len(outline.slides) == 1
    printable = render_printable_qmd(outline, base_dir=tmp_path)
    assert "Aufgabe" in printable and "Weiterrechnen" in printable
    assert "Warum gilt das" not in printable
    assert "Unsichtbare Überschrift" not in printable
    assert "Nur Notiz" not in printable


def test_display_math_preserves_blank_lines_and_markdown_symbols(tmp_path: Path) -> None:
    source = tmp_path / "math.md"
    formula = "$$\n\\begin{aligned}\nx &= 1 \\\\\n\n- y &= 2\n\\end{aligned}\n$$"
    source.write_text(f"## Formel\n\n{formula}\n\nWeiter.\n", encoding="utf-8")
    outline = parse_outline(source)
    assert outline.slides[0].blocks == (
        TextBlock(tuple(formula.splitlines()), TEXT_FONTSIZE, "absatz"),
        TextBlock(("Weiter.",), TEXT_FONTSIZE, "absatz"),
    )
    assert formula in render_printable_qmd(outline, base_dir=tmp_path)


def test_unclosed_display_math_reports_error(tmp_path: Path) -> None:
    source = tmp_path / "math.md"
    source.write_text("## Formel\n\n$$\nx^2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Nicht abgeschlossene Formel"):
        parse_outline(source)


@pytest.mark.parametrize("formula", [
    "$$x^2$$ und weiter.",
    "$$\nx^2\n$$ und weiter.",
    r"\[x^2\] und weiter.",
    "\\[\nx^2\n\\] und weiter.",
])
def test_display_math_with_trailing_text_preserves_following_slide(tmp_path: Path, formula: str) -> None:
    source = tmp_path / "formula.md"
    source.write_text(f"## Formel\n{formula}\n\n## Ende\nFertig.\n", encoding="utf-8")
    outline = parse_outline(source)
    assert [slide.title for slide in outline.slides] == ["Formel", "Ende"]
    assert outline.slides[0].blocks[0].lines == tuple(formula.splitlines())


@pytest.mark.skipif(not shutil.which("quarto") or not shutil.which("typst"), reason="Quarto/Typst fehlen")
@pytest.mark.parametrize("formula", ["$a +\nb$", "$$x^2$$ und weiter.", "$$\nx^2\n$$ und weiter."])
def test_multiline_inline_and_display_formulas_generate_images(tmp_path: Path, formula: str) -> None:
    source = tmp_path / "formula.md"
    source.write_text(f"## Formel\n{formula}\n", encoding="utf-8")
    data = json.loads(generate_deck(source).read_text(encoding="utf-8"))
    assert len([element for element in data["elements"] if element["type"] == "image"]) == 1
    assert [element["text"] for element in data["elements"] if element["type"] == "text"] == ["Formel"]


@pytest.mark.skipif(not shutil.which("quarto"), reason="Quarto fehlt")
@pytest.mark.parametrize("content", ["`$x$`", r"Kosten: \$5 und \$10.", "$5 und $10"])
def test_literal_dollar_signs_are_not_math(content: str) -> None:
    assert _math_document(content) is None


@pytest.mark.skipif(not shutil.which("quarto") or not shutil.which("typst"), reason="Quarto/Typst fehlen")
@pytest.mark.parametrize("formula", [r"$\mathclap{x}$", r"$\notacommand{x}$"])
def test_unsupported_math_is_rejected_instead_of_rendering_latex(tmp_path: Path, formula: str) -> None:
    source = tmp_path / "formula.md"
    source.write_text(f"## Formel\n{formula}\n", encoding="utf-8")
    with pytest.raises(FormulaRenderError, match="Could not convert TeX math"):
        generate_deck(source)
    assert not source.with_suffix(".excalidraw").exists()


@pytest.mark.skipif(not shutil.which("quarto") or not shutil.which("typst"), reason="Quarto/Typst fehlen")
@pytest.mark.parametrize("formula", [r"$\color{red}{x}$", r"$\textcolor{blue}{x}$"])
def test_lossy_latex_colors_report_actionable_error(formula: str) -> None:
    with pytest.raises(FormulaRenderError, match=r"LaTeX-Farben.*\[Rot"):
        _render_formula_svg(formula, 36, "Normal", "#000000")


@pytest.mark.skipif(not shutil.which("quarto"), reason="Quarto fehlt")
def test_blank_lines_in_formula_are_not_silently_rendered_as_text() -> None:
    with pytest.raises(FormulaRenderError, match="Leerzeilen"):
        _math_document("$$\nx = 1\n\ny = 2\n$$")


@needs_excalidraw_fonts
@pytest.mark.skipif(not shutil.which("quarto") or not shutil.which("typst"), reason="Quarto/Typst fehlen")
@pytest.mark.parametrize("font", FONT_DIRECTORIES)
def test_formula_fonts_render_without_fallback(font: str) -> None:
    content = "Überschrift Größe $x^2$"
    svg = _render_formula_svg(content, 36, font, "#000000")
    assert "<path" in svg
    if font != "Normal":
        assert svg != _render_formula_svg(content, 36, "Normal", "#000000")


def test_svg_ink_bbox_follows_transforms_and_use() -> None:
    svg = (
        '<svg viewBox="0 0 40 20" width="40pt" height="20pt" xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<defs><symbol id="g1" overflow="visible"><path d="M 0 0 L 5 12"/></symbol></defs>'
        '<g transform="matrix(1 0 0 -1 10 15)"><use xlink:href="#g1" x="2" y="0"/></g>'
        "</svg>"
    )
    assert _svg_ink_bbox(svg) == (12.0, 3.0, 17.0, 15.0)


def test_svg_ink_bbox_returns_none_for_unparseable_svg() -> None:
    assert _svg_ink_bbox("<svg><path") is None


def test_expand_svg_viewbox_grows_to_ink_with_padding() -> None:
    svg = '<svg viewBox="0 0 40 20" width="40pt" height="20pt"><path d="M -5 -3 L 45 25"/></svg>'
    expanded = _expand_svg_viewbox(svg, padding=2.0)
    box = re.search(r'viewBox="([^"]+)"', expanded)
    assert box
    assert [float(value) for value in box.group(1).split()] == [-7.0, -5.0, 54.0, 32.0]
    assert 'width="54' in expanded
    assert 'height="32' in expanded


def test_expand_svg_viewbox_keeps_contained_svg_unchanged() -> None:
    svg = '<svg viewBox="0 0 40 20" width="40pt" height="20pt"><path d="M 2 2 L 10 10"/></svg>'
    assert _expand_svg_viewbox(svg, padding=2.0) == svg


@pytest.mark.skipif(not shutil.which("quarto") or not shutil.which("typst"), reason="Quarto/Typst fehlen")
@pytest.mark.parametrize("formula", [
    "$(9^9)^9$ oder $9^(9^9)$",
    "Ohne Klammern liest man $9^9^9$ als $9^(9^9)$",
    "$a \\cdot a \\cdots a = a^n$",
    "$f(x) = x^2$    $g(a) = a^3$    $h(x) = 10^x$",
])
def test_rendered_formula_svg_keeps_all_ink_inside_viewbox(formula: str) -> None:
    svg = _render_formula_svg(formula, 36, "Normal", "#000000")
    view_box = re.search(r'viewBox="([^"]+)"', svg)
    assert view_box, "Typst-SVG ohne viewBox"
    x, y, width, height = (float(value) for value in view_box.group(1).split())
    ink = _svg_ink_bbox(svg)
    assert ink is not None
    assert ink[0] >= x - 0.01
    assert ink[1] >= y - 0.01
    assert ink[2] <= x + width + 0.01
    assert ink[3] <= y + height + 0.01


def test_missing_formula_font_reports_installation_hint(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace
    from excalideck import generator

    monkeypatch.setattr(generator, "FONT_ROOT", tmp_path)
    monkeypatch.setattr(generator.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="Liberation Sans\n"))
    with pytest.raises(DeckDependencyError, match="Excalifont.*npm ci"):
        _formula_font.__wrapped__("Excalifont")


@needs_excalidraw_fonts
@pytest.mark.skipif(not shutil.which("quarto") or not shutil.which("typst"), reason="Quarto/Typst fehlen")
def test_formulas_are_embedded_as_svg_in_all_text_kinds(tmp_path: Path) -> None:
    source = tmp_path / "math.md"
    source.write_text(
        "---\ntitle: 'Der Bruch $\\frac{1}{2}$'\n---\n"
        "## Satz $a^2+b^2=c^2$\n\n"
        "### Wurzel $\\sqrt{2}$\n\n"
        "Die Hälfte ist $\\frac{1}{2}$.\n\n"
        "- Ergebnis $x_1 = 2$\n- Probe $2^2=4$\n\n"
        "[Rot Lösung $x=2$]\n\n"
        "$$\n\\frac{x+1}{2} = \\sqrt{9}\n$$\n\n"
        "Text ohne Formel.\n",
        encoding="utf-8",
    )
    data = json.loads(generate_deck(source).read_text(encoding="utf-8"))
    images = [element for element in data["elements"] if element["type"] == "image"]
    assert len(images) == 7
    assert [element["text"] for element in data["elements"] if element["type"] == "text"] == ["Text ohne Formel."]
    for element in images:
        embedded = data["files"][element["fileId"]]["dataURL"]
        svg = base64.b64decode(embedded.split(",", 1)[1]).decode()
        assert "<svg" in svg
        assert "<path" in svg
        assert element["width"] > 0
        assert 0 < element["height"] < SLIDE_HEIGHT
    assert any("#c62828" in base64.b64decode(item["dataURL"].split(",", 1)[1]).decode() for item in data["files"].values())


@pytest.mark.parametrize("formula", [r"\(\frac{1}{2}\)", r"\[\sqrt{2}\]"])
@pytest.mark.skipif(not shutil.which("quarto") or not shutil.which("typst"), reason="Quarto/Typst fehlen")
def test_backslash_math_delimiters_render(formula: str) -> None:
    svg = _render_formula_svg(formula, 36, "Normal", "#000000")
    assert "<path" in svg


def test_formula_dependencies_report_error(monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda command: None)
    with pytest.raises(DeckDependencyError, match="Quarto und Typst"):
        _render_formula_svg("$dependency_test$", 36, "Normal", "#000000")


def _write_outline(root: Path) -> Path:
    asset = root / "bild.svg"
    asset.write_text(ASSET_SVG, encoding="utf-8")
    outline = root / "stunde-deck.md"
    outline.write_text(
        "\n".join(
            [
                "---",
                "title: Kapselung",
                "---",
                "",
                "# Kapselung in der OOP",
                "",
                "Informatik Klasse 11",
                "",
                "## Einstieg",
                "",
                "### Leitfrage",
                "",
                "- Wie schuetzen wir interne Daten?",
                "- Wer darf zugreifen?",
                "",
                "## Erarbeitung",
                "",
                "::: aufgabe",
                "Attribut als private deklarieren.",
                ":::",
                "",
                "![diagramm](bild.svg)",
                "",
                "## Sicherung",
                "",
                "- Begriff erklaeren",
            ]
        ),
        encoding="utf-8",
    )
    return outline


def test_parse_outline_struktur(tmp_path: Path) -> None:
    outline = parse_outline(_write_outline(tmp_path))
    assert outline.title == "Kapselung in der OOP"
    titel = [s for s in outline.slides if s.title == "Titel"]
    assert len(titel) == 1
    assert titel[0].blocks[0] == TextBlock(("Kapselung in der OOP",), DECK_TITLE_FONTSIZE, "titel")
    assert TextBlock(("Informatik Klasse 11",), TEXT_FONTSIZE, "absatz") in titel[0].blocks

    einstieg = [s for s in outline.slides if s.title == "Einstieg"][0]
    abschnitte = [b for b in einstieg.blocks if isinstance(b, TextBlock) and b.kind == "abschnitt"]
    assert abschnitte[0].lines == ("Leitfrage",)
    bullets = [b for b in einstieg.blocks if isinstance(b, TextBlock) and b.kind == "bullets"][0]
    assert bullets.lines == ("- Wie schuetzen wir interne Daten?", "- Wer darf zugreifen?")

    erarbeitung = [s for s in outline.slides if s.title == "Erarbeitung"][0]
    assert ImageBlock(Path("bild.svg")) in erarbeitung.blocks
    assert TextBlock(("Attribut als private deklarieren.",), TEXT_FONTSIZE, "absatz") in erarbeitung.blocks

    assert [s.title for s in outline.slides] == ["Titel", "Einstieg", "Erarbeitung", "Sicherung"]


def test_parse_outline_modellkuerzel(tmp_path: Path) -> None:
    outline = tmp_path / "modell-deck.md"
    outline.write_text(
        "## Folie\n\n[Modell rechenstrich | knoten=63,?,? | spruenge=-30,+2]\n",
        encoding="utf-8",
    )
    deck = parse_outline(outline)
    assert deck.slides[0].blocks == (
        ModelBlock("[Modell rechenstrich | knoten=63,?,? | spruenge=-30,+2]"),
    )


def test_parse_outline_geometrie_und_rot_kuerzel(tmp_path: Path) -> None:
    outline = tmp_path / "klausur-deck.md"
    outline.write_text(
        "\n".join(
            [
                "## Frage 1",
                "",
                "[Skizze dreieck | form=recht-C]",
                "",
                "- A) Antwort",
                "",
                "## Loesung 1",
                "",
                "[Rot B) Die Hypotenuse liegt dem rechten Winkel gegenueber.]",
                "",
                "[Einheitskreis 140 | markiert=sin,cos | farbe=rot]",
                "",
                "[Koordinatensystem | x=-8..8 | y=-10..10 | funktion=parabel | d=-3 | e=-9]",
            ]
        ),
        encoding="utf-8",
    )
    deck = parse_outline(outline)
    frage = deck.slides[0]
    assert frage.blocks == (
        ModelBlock("[Skizze dreieck | form=recht-C]"),
        TextBlock(("- A) Antwort",), TEXT_FONTSIZE, "bullets"),
    )
    loesung = deck.slides[1]
    assert loesung.blocks == (
        TextBlock(("B) Die Hypotenuse liegt dem rechten Winkel gegenueber.",), TEXT_FONTSIZE, "rot"),
        ModelBlock("[Einheitskreis 140 | markiert=sin,cos | farbe=rot]"),
        ModelBlock("[Koordinatensystem | x=-8..8 | y=-10..10 | funktion=parabel | d=-3 | e=-9]"),
    )


def test_parse_outline_boxen(tmp_path: Path) -> None:
    outline = tmp_path / "box-deck.md"
    outline.write_text(
        "## Folie\n\n"
        "[Infobox: Potenzschreibweise]\n\n"
        "a · a · … · a = aⁿ\n\n"
        "- n gleiche Faktoren\n\n"
        "[/Infobox]\n\n"
        "[Warnbox]\n\nAchtung!\n\n[/Warnbox]\n",
        encoding="utf-8",
    )
    deck = parse_outline(outline)
    blocks = deck.slides[0].blocks
    assert blocks[0] == BoxBlock(
        "infobox",
        "Potenzschreibweise",
        (
            TextBlock(("a · a · … · a = aⁿ",), TEXT_FONTSIZE, "absatz"),
            TextBlock(("- n gleiche Faktoren",), TEXT_FONTSIZE, "bullets"),
        ),
    )
    assert blocks[1] == BoxBlock(
        "warnbox", "Warnung", (TextBlock(("Achtung!",), TEXT_FONTSIZE, "absatz"),)
    )


@pytest.mark.parametrize(
    "body, message",
    [
        ("## F\n\n[Infobox: X]\n\nText\n", "Nicht abgeschlossener Kasten"),
        ("## F\n\nText\n\n[/Tippbox]\n", "ohne passenden Anfang"),
        ("## F\n\n[Infobox: X]\n\n[Warnbox]\n\nText\n\n[/Warnbox]\n", "Kästen in Kästen"),
        ("## F\n\n[Infobox: X]\n\nText\n\n[/Warnbox]\n", "schliesst"),
    ],
)
def test_box_marker_fehler_melden_klar(tmp_path: Path, body: str, message: str) -> None:
    outline = tmp_path / "fehler-deck.md"
    outline.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        parse_outline(outline)


def test_parse_outline_spalten(tmp_path: Path) -> None:
    outline = tmp_path / "spalten-deck.md"
    outline.write_text(
        "\n".join(
            [
                "## Folie",
                "",
                "::: {.columns}",
                '::: {.column width="52%"}',
                "[Skizze zahlenschloss | raeder=3 | ziffern=3]",
                ":::",
                "::: {.column}",
                "- Wie viele Einstellungen gibt es?",
                ":::",
                ":::",
                "",
                "Absatz danach.",
            ]
        ),
        encoding="utf-8",
    )
    deck = parse_outline(outline)
    assert deck.slides[0].blocks == (
        ColumnsBlock(
            (
                ColumnBlock(
                    (ModelBlock("[Skizze zahlenschloss | raeder=3 | ziffern=3]"),),
                    52.0,
                ),
                ColumnBlock(
                    (TextBlock(("- Wie viele Einstellungen gibt es?",), TEXT_FONTSIZE, "bullets"),),
                    None,
                ),
            )
        ),
        TextBlock(("Absatz danach.",), TEXT_FONTSIZE, "absatz"),
    )


@pytest.mark.parametrize(
    "body, message",
    [
        ("## F\n\n::: {.columns}\n\n::: {.column}\n\nText\n", "Nicht abgeschlossene Spalten"),
        ("## F\n\n::: {.columns}\n\n::: {.column}\n\nText\n\n:::\n\n:::\n", "mindestens zwei"),
        ("## F\n\n::: {.columns}\n\n::: {.column}\n\nText\n\n## N\n", "Nicht abgeschlossene Spalten"),
        ("## F\n\n::: {.columns}\n\n::: {.columns}\n", "Spalten in Spalten"),
    ],
)
def test_spalten_marker_fehler_melden_klar(tmp_path: Path, body: str, message: str) -> None:
    outline = tmp_path / "fehler-deck.md"
    outline.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        parse_outline(outline)


def test_eingerueckte_fortsetzung_gehoert_zum_bullet(tmp_path: Path) -> None:
    outline = tmp_path / "fortsetzung-deck.md"
    outline.write_text(
        "## Folie\n\n"
        "- A) Erster Teil der Antwort,\n"
        "  der auf der Folie in die naechste Zeile umbricht.\n"
        "- B) Kurze Antwort.\n"
        "Absatz danach.\n",
        encoding="utf-8",
    )
    deck = parse_outline(outline)
    blocks = deck.slides[0].blocks
    assert blocks == (
        TextBlock(
            (
                "- A) Erster Teil der Antwort,",
                "  der auf der Folie in die naechste Zeile umbricht.",
                "- B) Kurze Antwort.",
            ),
            TEXT_FONTSIZE,
            "bullets",
        ),
        TextBlock(("Absatz danach.",), TEXT_FONTSIZE, "absatz"),
    )


def test_frontmatter_titel_und_untertitel_ohne_titelzeile(tmp_path: Path) -> None:
    outline = tmp_path / "deck.qmd"
    outline.write_text(
        "\n".join(
            [
                "---",
                'title: "Subtrahieren und Rechentricks"',
                'subtitle: "Rueckblick · Klasse 5c"',
                "---",
                "",
                "## Folie",
                "",
                "- Punkt",
            ]
        ),
        encoding="utf-8",
    )
    deck = parse_outline(outline)
    assert deck.title == "Subtrahieren und Rechentricks"
    assert [slide.title for slide in deck.slides] == ["Titel", "Folie"]
    assert deck.slides[0].blocks == (
        TextBlock(("Subtrahieren und Rechentricks",), DECK_TITLE_FONTSIZE, "titel"),
        TextBlock(("Rueckblick · Klasse 5c",), TEXT_FONTSIZE, "absatz"),
    )


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
def test_model_cache_refreshes_when_filter_changes(tmp_path: Path, monkeypatch) -> None:
    import excalideck.generator as generator

    model_filter = tmp_path / "exam.lua"
    original = generator.MODEL_FILTER.read_text(encoding="utf-8")
    model_filter.write_text(original, encoding="utf-8")
    monkeypatch.setattr(generator, "MODEL_FILTER", model_filter)
    marker = "[Modell vierhundertfeld | zeilen=14 | spalten=13]"
    first = generator._render_marker_svg(marker)
    model_filter.write_text(original.replace("#fdecea", "#abcdef"), encoding="utf-8")
    second = generator._render_marker_svg(marker)
    assert '#fdecea' in first
    assert '#abcdef' in second
    assert '#fdecea' not in second


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
def test_presentation_rebuild_uses_updated_filter_in_same_process(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    import excalideck.generator as generator
    from material_ui.slides import SlidesService

    model_filter = tmp_path / "exam.lua"
    original_filter = generator.MODEL_FILTER.read_text(encoding="utf-8")
    model_filter.write_text(original_filter, encoding="utf-8")
    monkeypatch.setattr(generator, "MODEL_FILTER", model_filter)
    source = tmp_path / "slide.qmd"
    source.write_text("---\nformat:\n  typst:\n    template: slide-template.typst\n---\n\n## Malkreuz\n\n[Modell vierhundertfeld | zeilen=14 | spalten=13]\n", encoding="utf-8")
    service = SlidesService(SimpleNamespace(root=tmp_path))
    deck, created = service.ensure(source)
    assert created
    original_deck = deck.read_bytes()
    model_filter.write_text(original_filter.replace("#fdecea", "#abcdef"), encoding="utf-8")

    rebuilt, backup = service.rebuild(source)

    assert rebuilt == deck
    assert backup is not None
    assert backup.read_bytes() == original_deck
    data = json.loads(rebuilt.read_text(encoding="utf-8"))
    assert len(data["files"]) == 1
    embedded = next(iter(data["files"].values()))["dataURL"]
    svg = base64.b64decode(embedded.split(",", 1)[1]).decode("utf-8")
    assert "#abcdef" in svg
    assert "#fdecea" not in svg


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
@pytest.mark.parametrize("marker,aspect_ratio", [
    ("[Modell rechenstrich | knoten=52,12,13 | spruenge=-40,+1]", 460 / 95),
    ("[Modell flaeche | oben=26 | links=14]", 460 / 180),
])
def test_generate_deck_zeichnet_modellkuerzel_automatisch(tmp_path: Path, marker: str, aspect_ratio: float) -> None:
    outline = tmp_path / "modell-deck.md"
    outline.write_text(
        f"## Folie\n\n{marker}\n",
        encoding="utf-8",
    )
    generate_deck(outline)
    data = json.loads((tmp_path / "modell-deck.excalidraw").read_text(encoding="utf-8"))
    images = [e for e in data["elements"] if e["type"] == "image"]
    assert len(images) == 1
    assert data["files"], "Modell muss als dataURL eingebettet sein"
    assert images[0]["width"] / images[0]["height"] == pytest.approx(aspect_ratio, rel=0.01)


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
def test_generate_deck_zeichnet_geometrie_und_faerbt_rot(tmp_path: Path) -> None:
    outline = tmp_path / "klausur-deck.md"
    outline.write_text(
        "\n".join(
            [
                "## Loesung 1",
                "",
                "[Rot B) Die Hypotenuse liegt dem rechten Winkel gegenueber.]",
                "",
                "[Skizze dreieck | form=recht-C | markiert=c,gamma | farbe=rot]",
            ]
        ),
        encoding="utf-8",
    )
    generate_deck(outline)
    data = json.loads((tmp_path / "klausur-deck.excalidraw").read_text(encoding="utf-8"))
    images = [e for e in data["elements"] if e["type"] == "image"]
    assert len(images) == 1, "Skizze-Kuerzel muss als Bild gezeichnet werden"
    assert data["files"], "Skizze muss als dataURL eingebettet sein"
    texts = [e for e in data["elements"] if e["type"] == "text"]
    rot = [e for e in texts if e["text"].startswith("B) Die Hypotenuse")]
    assert rot, "Rot-Kuerzel muss als Textblock erscheinen"
    assert rot[0]["strokeColor"].lower() == "#c62828"


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
def test_ungueltiges_modellkuerzel_meldet_klar(tmp_path: Path) -> None:
    outline = tmp_path / "kaputt-modell-deck.md"
    outline.write_text(
        "## Folie\n\n[Modell rechenstrich | knoten=52 | spruenge=-40,+1]\n",
        encoding="utf-8",
    )
    with pytest.raises(ModelRenderError):
        generate_deck(outline)


@pytest.mark.parametrize(
    "marker, accent",
    [
        ("[Infobox: Titel]", "#1565c0"),
        ("[Warnbox: Titel]", "#b45309"),
        ("[Tippbox: Titel]", "#2e7d32"),
    ],
)
def test_generate_deck_zeichnet_box_als_kasten(tmp_path: Path, marker: str, accent: str) -> None:
    outline = tmp_path / "box-deck.md"
    close = f"[/{marker.split(':')[0][1:]}]"
    outline.write_text(
        f"## Folie\n\n{marker}\n\na · a · … · a = aⁿ\n\n{close}\n",
        encoding="utf-8",
    )
    generate_deck(outline)
    data = json.loads((tmp_path / "box-deck.excalidraw").read_text(encoding="utf-8"))
    rectangles = [e for e in data["elements"] if e["type"] == "rectangle"]
    assert len(rectangles) == 1, "Box-Marker muss als Rechteck gezeichnet werden"
    box = rectangles[0]
    assert box["strokeColor"].lower() == accent
    assert box["backgroundColor"].lower() != "#ffffff", "Kasten braucht eine gefuellte Flaeche"
    assert box["fillStyle"] == "solid"
    texts = {e["text"] for e in data["elements"] if e["type"] == "text"}
    assert "Titel" in texts
    assert "a · a · … · a = aⁿ" in texts
    assert not any(t.startswith("[") and t.endswith("]") for t in texts), \
        "Box-Marker duerfen nicht als Text auf der Folie stehen"
    title = next(e for e in data["elements"] if e["type"] == "text" and e["text"] == "Titel")
    content = next(e for e in data["elements"] if e["type"] == "text" and "a · a" in e["text"])
    assert box["x"] < title["x"] < box["x"] + box["width"]
    assert box["y"] < title["y"] < content["y"] < box["y"] + box["height"], \
        "Titel und Inhalt muessen im Kasten liegen"


def test_generate_deck_box_und_text_teilen_folie(tmp_path: Path) -> None:
    outline = tmp_path / "box-deck.md"
    outline.write_text(
        "## Folie\n\n[Infobox: Titel]\n\naⁿ\n\n[/Infobox]\n\n- n gleiche Faktoren\n",
        encoding="utf-8",
    )
    generate_deck(outline)
    data = json.loads((tmp_path / "box-deck.excalidraw").read_text(encoding="utf-8"))
    box = next(e for e in data["elements"] if e["type"] == "rectangle")
    bullets = next(e for e in data["elements"] if e["type"] == "text" and "n gleiche" in e["text"])
    assert bullets["y"] > box["y"] + box["height"], "Text nach dem Kasten liegt unter ihm"


def test_generate_deck_legt_spalten_nebeneinander(tmp_path: Path) -> None:
    outline = tmp_path / "spalten-deck.md"
    outline.write_text(
        "## Folie\n\n"
        "::: {.columns}\n"
        '::: {.column width="52%"}\n'
        "Linke Spalte\n"
        ":::\n"
        "::: {.column}\n"
        "- Rechte Spalte\n"
        ":::\n"
        ":::\n",
        encoding="utf-8",
    )
    generate_deck(outline)
    data = json.loads((tmp_path / "spalten-deck.excalidraw").read_text(encoding="utf-8"))
    left = next(e for e in data["elements"] if e["type"] == "text" and e["text"] == "Linke Spalte")
    right = next(e for e in data["elements"] if e["type"] == "text" and "Rechte Spalte" in e["text"])
    assert right["x"] > left["x"] + left["width"], "Spalten muessen nebeneinander liegen"
    assert right["y"] == pytest.approx(left["y"]), "Spalten beginnen auf gleicher Hoehe"


def test_generate_deck_bricht_spaltentext_um(tmp_path: Path) -> None:
    outline = tmp_path / "spalten-deck.md"
    outline.write_text(
        "## Folie\n\n"
        "::: {.columns}\n"
        '::: {.column width="30%"}\n'
        "Links\n"
        ":::\n"
        "::: {.column}\n"
        "- Ein sehr langer Bullet-Text, der in der Spalte nicht auf eine einzige Zeile passt.\n"
        ":::\n"
        ":::\n",
        encoding="utf-8",
    )
    generate_deck(outline)
    data = json.loads((tmp_path / "spalten-deck.excalidraw").read_text(encoding="utf-8"))
    bullet = next(e for e in data["elements"] if e["type"] == "text" and "sehr langer" in e["text"])
    assert "\n" in bullet["text"], "Langer Spaltentext muss auf die Spaltenbreite umbrechen"
    assert bullet["width"] <= 0.7 * (SLIDE_WIDTH - 2 * SLIDE_MARGIN) + 1, \
        "Umbrochener Text darf nicht aus der Spalte herausragen"


def test_printable_gibt_boxmarker_und_filter_wieder(tmp_path: Path) -> None:
    outline = tmp_path / "box-deck.md"
    outline.write_text(
        "## Folie\n\n[Infobox: Titel]\n\naⁿ\n\n[/Infobox]\n\n[Warnbox]\n\nAchtung!\n\n[/Warnbox]\n",
        encoding="utf-8",
    )
    output = generate_printable(outline)
    text = output.read_text(encoding="utf-8")
    assert "filters:" in text, "Box-Marker braucht den Projektfilter auch im eigenstaendigen Build"
    assert "exam.lua" in text
    assert "[Infobox: Titel]" in text
    assert "[/Infobox]" in text
    assert "[Warnbox]" in text, "Default-Titel wird nicht als expliziter Titel ausgeben"
    assert "[/Warnbox]" in text
    assert text.index("[Infobox: Titel]") < text.index("aⁿ") < text.index("[/Infobox]")


def test_printable_gibt_modellkuerzel_und_filter_an(tmp_path: Path) -> None:
    outline = tmp_path / "modell-deck.md"
    outline.write_text(
        "## Folie\n\n[Modell rechenstrich | knoten=65,35 | spruenge=-30]\n",
        encoding="utf-8",
    )
    output = generate_printable(outline)
    text = output.read_text(encoding="utf-8")
    assert "[Modell rechenstrich | knoten=65,35 | spruenge=-30]" in text
    assert "filters:" in text
    assert "exam.lua" in text


def test_printable_gibt_spalten_divs_und_filter_wieder(tmp_path: Path) -> None:
    outline = tmp_path / "spalten-deck.md"
    outline.write_text(
        "## Folie\n\n"
        "::: {.columns}\n"
        '::: {.column width="52%"}\n'
        "Linke Spalte\n"
        ":::\n"
        "::: {.column}\n"
        "- Rechte Spalte\n"
        ":::\n"
        ":::\n",
        encoding="utf-8",
    )
    output = generate_printable(outline)
    text = output.read_text(encoding="utf-8")
    assert "filters:" in text, "Spalten brauchen den Projektfilter auch im eigenstaendigen Build"
    assert "exam.lua" in text
    assert "::: {.columns}" in text
    assert '::: {.column width="52%"}' in text
    assert "::: {.column}" in text, "Spalte ohne Breite wird ohne width ausgegeben"
    assert text.index("::: {.columns}") < text.index("Linke Spalte") < text.rindex(":::")


def test_generate_deck_erzeugt_valide_szene(tmp_path: Path) -> None:
    outline = _write_outline(tmp_path)
    output = generate_deck(outline)
    assert output == tmp_path / "stunde-deck.excalidraw"
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["type"] == "excalidraw"
    assert data["version"] == 2
    elements = data["elements"]
    frames = [e for e in elements if e["type"] == "frame"]
    assert [f["name"] for f in frames] == ["Titel", "Einstieg", "Erarbeitung", "Sicherung"]
    for index, frame in enumerate(frames):
        assert (frame["width"], frame["height"]) == (SLIDE_WIDTH, SLIDE_HEIGHT)
        assert frame["x"] == index * SLIDE_PITCH
        assert frame["y"] == 0.0
        children = [e for e in elements if e.get("frameId") == frame["id"]]
        assert children, f"Frame {frame['name']} ohne Kinder"
        for child in children:
            # Neue Anmerkungen werden unmittelbar vor dem Frame eingefuegt:
            # vorhandene Inhalte/Hintergruende muessen darunter liegen.
            assert elements.index(child) < elements.index(frame)
            assert frame["x"] <= child["x"] < frame["x"] + SLIDE_WIDTH
            assert frame["y"] <= child["y"] < frame["y"] + SLIDE_HEIGHT
    texts = {e["text"] for e in elements if e["type"] == "text"}
    assert "Kapselung in der OOP" in texts
    assert "- Wie schuetzen wir interne Daten?\n- Wer darf zugreifen?" in texts
    # textAlign muss "left" sein: bei "center" (Excaligen-Default) werden
    # kuerzere Zeilen eines mehrzeiligen Blocks relativ zur laengsten Zeile
    # eingerueckt (Treppenstufen-Effekt bei Bullet-Listen).
    text_aligns = {e["textAlign"] for e in elements if e["type"] == "text"}
    assert text_aligns == {"left"}
    images = [e for e in elements if e["type"] == "image"]
    assert len(images) == 1
    assert data["files"], "Bild muss als dataURL eingebettet sein"


def test_folientitel_steht_als_ueberschrift_im_frame(tmp_path: Path) -> None:
    outline = _write_outline(tmp_path)
    generate_deck(outline)
    data = json.loads((tmp_path / "stunde-deck.excalidraw").read_text(encoding="utf-8"))
    elements = data["elements"]
    frames = {e["name"]: e for e in elements if e["type"] == "frame"}
    texts = [e for e in elements if e["type"] == "text"]
    for name in ("Einstieg", "Erarbeitung", "Sicherung"):
        frame = frames[name]
        headings = [
            e
            for e in texts
            if e["text"] == name and e.get("frameId") == frame["id"]
        ]
        assert headings, f"Folientitel '{name}' fehlt als Ueberschrift im Frame"
        heading = headings[0]
        assert heading["fontSize"] == SLIDE_TITLE_FONTSIZE
        assert heading["fontFamily"] == 5, "Folientitel in Excalifont"
        assert heading["x"] == frame["x"] + SLIDE_MARGIN
        assert heading["y"] == SLIDE_MARGIN
    # Titelfolie: Der Decktitel steht schon als grosser Textblock,
    # der Frame-Name wird nicht zusaetzlich als Ueberschrift wiederholt.
    title_frame = frames["Titel"]
    assert not [
        e
        for e in texts
        if e["text"] == "Titel" and e.get("frameId") == title_frame["id"]
    ]
    deck_title = [e for e in texts if e["text"] == "Kapselung in der OOP"][0]
    assert deck_title["fontSize"] == DECK_TITLE_FONTSIZE


def test_folie_nur_aus_h1_wird_zentrierte_titelfolie(tmp_path: Path) -> None:
    outline = tmp_path / "abschnitts-deck.md"
    outline.write_text(
        "# Kapselung in der OOP\n\n## Einstieg\n\n- Punkt\n\n# Zwischenstand\n",
        encoding="utf-8",
    )
    generate_deck(outline)
    data = json.loads((tmp_path / "abschnitts-deck.excalidraw").read_text(encoding="utf-8"))
    elements = data["elements"]
    frames = [e for e in elements if e["type"] == "frame"]
    assert [f["name"] for f in frames] == ["Titel", "Einstieg", "Titel"]
    texts = [e for e in elements if e["type"] == "text"]
    for frame, expected in zip(frames, ("Kapselung in der OOP", None, "Zwischenstand")):
        if expected is None:
            continue
        title = [
            e for e in texts
            if e["text"] == expected and e.get("frameId") == frame["id"]
        ]
        assert len(title) == 1, f"Titel '{expected}' fehlt auf der Titelfolie"
        assert title[0]["fontSize"] == DECK_TITLE_FONTSIZE
        # Ueberschrift horizontal und vertikal in der Folienmitte zentriert
        assert title[0]["x"] + title[0]["width"] / 2 == pytest.approx(frame["x"] + SLIDE_WIDTH / 2)
        assert title[0]["y"] + title[0]["height"] / 2 == pytest.approx(SLIDE_HEIGHT / 2)
        # Der Frame-Name wird auf der Titelfolie nicht zusaetzlich wiederholt
        assert not [
            e for e in texts
            if e["text"] == "Titel" and e.get("frameId") == frame["id"]
        ]
    # Inhaltsfolie bleibt unveraendert: Folientitel oben links am Rand
    einstieg = frames[1]
    heading = [e for e in texts if e["text"] == "Einstieg" and e.get("frameId") == einstieg["id"]][0]
    assert heading["x"] == einstieg["x"] + SLIDE_MARGIN
    assert heading["y"] == SLIDE_MARGIN


def test_titelfolie_mit_untertitel_bleibt_regulaer(tmp_path: Path) -> None:
    generate_deck(_write_outline(tmp_path))
    data = json.loads((tmp_path / "stunde-deck.excalidraw").read_text(encoding="utf-8"))
    elements = data["elements"]
    title_frame = next(e for e in elements if e["type"] == "frame" and e["name"] == "Titel")
    deck_title = [
        e for e in elements
        if e["type"] == "text" and e["text"] == "Kapselung in der OOP"
    ][0]
    # Untertitel vorhanden: keine reine h1-Folie, Layout bleibt oben links
    assert deck_title.get("frameId") == title_frame["id"]
    assert deck_title["x"] == SLIDE_MARGIN
    assert deck_title["y"] == SLIDE_MARGIN


def test_generate_deck_ohne_folien(tmp_path: Path) -> None:
    outline = tmp_path / "leer-deck.md"
    outline.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        generate_deck(outline)


def test_deck_fonts_standard(tmp_path: Path) -> None:
    outline = _write_outline(tmp_path)
    generate_deck(outline)
    data = json.loads((tmp_path / "stunde-deck.excalidraw").read_text(encoding="utf-8"))
    fonts = {e["text"]: e["fontFamily"] for e in data["elements"] if e["type"] == "text"}
    assert fonts["Kapselung in der OOP"] == 5, "Titel in Excalifont"
    assert fonts["Leitfrage"] == 5, "Abschnitt in Excalifont"
    assert fonts["Informatik Klasse 11"] == 2, "Absatz in Normal (Helvetica-artig)"
    assert fonts["- Wie schuetzen wir interne Daten?\n- Wer darf zugreifen?"] == 2


def test_frontmatter_fonts_ueberschreiben(tmp_path: Path) -> None:
    outline = tmp_path / "fonts-deck.md"
    outline.write_text(
        "\n".join(
            [
                "---",
                "font-ueberschriften: Code",
                "font-text: Hand-drawn",
                "---",
                "",
                "# Titel",
                "",
                "Absatz",
                "",
                "## Folie",
                "",
                "### Abschnitt",
                "",
                "- Punkt",
            ]
        ),
        encoding="utf-8",
    )
    deck = parse_outline(outline)
    assert deck.heading_font == "Code"
    assert deck.text_font == "Hand-drawn"
    generate_deck(outline)
    data = json.loads((tmp_path / "fonts-deck.excalidraw").read_text(encoding="utf-8"))
    fonts = {e["text"]: e["fontFamily"] for e in data["elements"] if e["type"] == "text"}
    assert fonts["Titel"] == 3, "Ueberschriften-Font aus Frontmatter (Code=3)"
    assert fonts["Abschnitt"] == 3
    assert fonts["Absatz"] == 1, "Text-Font aus Frontmatter (Hand-drawn=1)"
    assert fonts["- Punkt"] == 1


def test_unbekannte_schrift_meldet_klar(tmp_path: Path) -> None:
    outline = tmp_path / "badfont-deck.md"
    outline.write_text("---\nfont-text: Comic Sans MS\n---\n\n## Folie\n", encoding="utf-8")
    with pytest.raises(ValueError, match="font-text"):
        parse_outline(outline)


def test_loser_text_wird_implizite_folie(tmp_path: Path) -> None:
    outline = tmp_path / "notiz-deck.md"
    outline.write_text("Nur ein Absatz.\n", encoding="utf-8")
    deck = parse_outline(outline)
    assert [slide.title for slide in deck.slides] == ["Folie"]


def test_ueberschreibschutz(tmp_path: Path) -> None:
    outline = _write_outline(tmp_path)
    output = generate_deck(outline)
    output.write_text('{"elements": [], "files": {}}', encoding="utf-8")
    with pytest.raises(DeckExistsError):
        generate_deck(outline)
    assert json.loads(output.read_text(encoding="utf-8")) == {"elements": [], "files": {}}
    generate_deck(outline, force=True)
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["type"] == "excalidraw"


def test_ueberlauf_wird_gewarnt(tmp_path: Path) -> None:
    outline = tmp_path / "lang-deck.md"
    lines = ["## Viele Bullets", ""]
    lines += [f"- Punkt {index} mit etwas laengerem Text" for index in range(30)]
    outline.write_text("\n".join(lines), encoding="utf-8")
    with pytest.warns(UserWarning, match="Viele Bullets"):
        generate_deck(outline)


def test_breite_zeile_wird_gewarnt(tmp_path: Path) -> None:
    outline = tmp_path / "breit-deck.md"
    outline.write_text(
        "## Breite Folie\n\nEine Zeile mit sehr sehr vielen Woertern die weit ueber den Folienrand hinauslaeuft und deshalb gemeldet wird.\n",
        encoding="utf-8",
    )
    with pytest.warns(UserWarning, match="rechten Folienrand"):
        generate_deck(outline)


def test_kompakte_folie_ohne_warnung(tmp_path: Path, recwarn) -> None:
    generate_deck(_write_outline(tmp_path))
    assert not [w for w in recwarn.list if issubclass(w.category, UserWarning)]


def test_fehlendes_bild_meldet_klar(tmp_path: Path) -> None:
    outline = tmp_path / "kaputt-deck.md"
    outline.write_text("## Folie\n\n![weg](fehlt.svg)\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        generate_deck(outline)


def test_generate_printable_erzeugt_qmd(tmp_path: Path) -> None:
    outline = _write_outline(tmp_path)
    output = generate_printable(outline)
    assert output == tmp_path / "stunde-deck.qmd"
    text = output.read_text(encoding="utf-8")
    assert 'title: "Kapselung in der OOP"' in text
    assert 'subtitle: "Informatik Klasse 11"' in text
    assert "deck-template.typst" in text
    assert "## Einstieg" in text
    assert "### Leitfrage" in text
    assert "- Wie schuetzen wir interne Daten?" in text
    assert "![](bild.svg)" in text
    assert "## Titel" not in text
    assert "filters:" not in text, "Ohne Modell-Kuerzel braucht die QMD keinen Filter"


def test_generate_printable_ohne_folien(tmp_path: Path) -> None:
    outline = tmp_path / "leer-deck.md"
    outline.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        generate_printable(outline)


def test_printable_ueberschreibschutz(tmp_path: Path) -> None:
    outline = _write_outline(tmp_path)
    output = generate_printable(outline)
    original = output.read_text(encoding="utf-8")
    generate_printable(outline)
    assert output.read_text(encoding="utf-8") == original
    output.write_text(original + "\nManuell geaendert.\n", encoding="utf-8")
    with pytest.raises(PrintableExistsError):
        generate_printable(outline)
    assert "Manuell geaendert." in output.read_text(encoding="utf-8")
    generate_printable(outline, force=True)
    assert "Manuell geaendert." not in output.read_text(encoding="utf-8")


def test_generate_slides_erzeugt_slide_qmd(tmp_path: Path) -> None:
    outline = _write_outline(tmp_path)
    output = generate_printable(outline, variant="slides")
    assert output == tmp_path / "stunde-deck-slides.qmd"
    text = output.read_text(encoding="utf-8")
    assert "slide-template.typst" in text
    assert "deck-template.typst" not in text
    assert 'title: "Kapselung in der OOP"' in text
    assert "## Einstieg" in text
    assert "## Sicherung" in text


def test_slides_variante_stoert_druckausgabe_nicht(tmp_path: Path) -> None:
    outline = _write_outline(tmp_path)
    druck = generate_printable(outline)
    slides = generate_printable(outline, variant="slides")
    assert druck == tmp_path / "stunde-deck.qmd"
    assert slides == tmp_path / "stunde-deck-slides.qmd"
    assert "deck-template.typst" in druck.read_text(encoding="utf-8")


def test_slides_ueberschreibschutz(tmp_path: Path) -> None:
    outline = _write_outline(tmp_path)
    output = generate_printable(outline, variant="slides")
    original = output.read_text(encoding="utf-8")
    generate_printable(outline, variant="slides")
    assert output.read_text(encoding="utf-8") == original
    output.write_text(original + "\nManuell geaendert.\n", encoding="utf-8")
    with pytest.raises(PrintableExistsError):
        generate_printable(outline, variant="slides")
    assert "Manuell geaendert." in output.read_text(encoding="utf-8")
    generate_printable(outline, variant="slides", force=True)
    assert "Manuell geaendert." not in output.read_text(encoding="utf-8")


def test_unbekannte_variante_meldet_klar(tmp_path: Path) -> None:
    outline = _write_outline(tmp_path)
    deck = parse_outline(outline)
    with pytest.raises(ValueError, match="Unbekannte Variante"):
        render_printable_qmd(deck, base_dir=tmp_path, variant="kaputt")


def test_answer_area_is_a_rectangle_and_roundtrips_to_markdown(tmp_path):
    from excalideck.outline import AnswerBlock
    source = tmp_path / "aufgabe.md"
    source.write_text("## Aufgabe\n\n[Antwortkasten: 2.2cm]\n")
    outline = parse_outline(source)
    assert outline.slides[0].blocks == (AnswerBlock(22),)
    printable = render_printable_qmd(outline, base_dir=tmp_path)
    assert "[Antwortkasten: 22mm]" in printable
    target = generate_deck(source)
    deck = json.loads(target.read_text())
    assert not any("Antwortkasten" in e.get("text", "") for e in deck["elements"])
    areas = [e for e in deck["elements"] if e["type"] == "rectangle"]
    assert len(areas) == 1
    assert areas[0]["height"] == 220
