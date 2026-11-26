"""Generator: DeckOutline -> .excalidraw-Datei ueber Excaligen.

Excaligen (MIT, keine Abhaengigkeiten) erzeugt die Szenen-JSON; dieses Modul
uebersetzt das Outline-Modell in Excaligen-Aufrufe und sichert den
Ueberschreibschutz: existierende Decks werden nie stillschweigend
ueberschrieben, weil annotierte Decks die Quelle der Wahrheit sind.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import warnings
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from material_core.designs import design_by_id

from excalideck.processes import run_process

from excalideck.outline import (
    HEADING_KINDS,
    AnswerBlock,
    SpacerBlock,
    BoxBlock,
    ColumnsBlock,
    DeckOutline,
    ImageBlock,
    ModelBlock,
    Slide,
    TextBlock,
    parse_outline,
)
from material_core import template_roots

SLIDE_WIDTH = 1600.0
SLIDE_HEIGHT = 900.0
# Inhaltsflaeche der Design-Hintergruende (Kopfband 32..152, Rahmen ab
# material_core/slide_designs.py): Die zentrierte Titelfolie richtet sich
# nach dieser Flaeche, nicht nach der ganzen Folie.
DESIGN_CONTENT_BOX = (32.0, 176.0, 1536.0, 644.0)
SLIDE_GAP = 80.0
SLIDE_PITCH = SLIDE_WIDTH + SLIDE_GAP
SLIDE_MARGIN = 40.0
LINE_HEIGHT_FACTOR = 1.6
BLOCK_GAP = 24.0
# Folientitel als Ueberschrift im Frame; zwischen Abschnitt (44) und Decktitel (64).
SLIDE_TITLE_FONTSIZE = 56
IMAGE_MAX_WIDTH = 800.0
# 400 statt 480: Mit Textgroesse 36 bleibt pro Folie sonst keine Zeile fuer
# Frage plus drei Antworten (Budget: 900 - Rand - Folientitel - Bild).
IMAGE_MAX_HEIGHT = 400.0
# Muss zu RED in src/quarto/filters/exam.lua passen ([Rot …]-Kuerzel).
MARKER_RED = "#c62828"
# Muss zu CHAR_WIDTH_FACTOR in Excaligen passen: Textbreite ≈ Zeichenzahl
# mal Schriftgroesse mal diesem Faktor. Grundlage des Spalten-Umbruchs.
TEXT_CHAR_WIDTH_FACTOR = 0.6
# Kasten-Akzente wie in der druckbaren Folienfassung (slide-template.typst:
# primary/warn/tip); die Flaeche ist die Akzentfarbe zu 92 % aufgehellt.
BOX_ACCENTS = {"infobox": "#1565c0", "warnbox": "#b45309", "tippbox": "#2e7d32"}
BOX_LIGHTEN = 0.92
BOX_TITLE_FONTSIZE = 40
BOX_PADDING_X = 28.0
BOX_PADDING_Y = 20.0
MODEL_FILTER = template_roots.SUPPORT / "filters" / "exam.lua"
MATH_PATTERN = re.compile(r"(?<!\\)\$(?:[^$]+|\$[\s\S]+?\$)\$|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]")
FONT_ROOT = Path(__file__).parent / "present/node_modules/@excalidraw/excalidraw/dist/prod/fonts"
FONT_DIRECTORIES = {
    "Normal": ("Liberation", "Liberation Sans"),
    "Code": ("Cascadia", "Cascadia Code"),
    "Hand-drawn": ("Virgil", "Virgil"),
    "Excalifont": ("Excalifont", "Excalifont"),
    "Comic Shaans": ("ComicShanns", "Comic Shanns"),
    "Lilita One": ("Lilita", "Lilita One"),
    "Nunito": ("Nunito", "Nunito"),
}


class DeckExistsError(Exception):
    """Ziel-Deck existiert bereits und soll ohne --force nicht ueberschrieben werden."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Deck existiert bereits: {path}")
        self.path = path


class DeckDependencyError(RuntimeError):
    """Excaligen ist nicht installiert."""


class ModelRenderError(RuntimeError):
    """Modell-Kuerzel konnte nicht als SVG gezeichnet werden."""


class FormulaRenderError(ModelRenderError):
    """Formeltext konnte nicht als SVG gesetzt werden."""


@lru_cache(maxsize=256)
def _math_document(markdown: str) -> dict | None:
    if not MATH_PATTERN.search(markdown) and not re.search(r"\*\*.+?\*\*|__.+?__", markdown):
        return None
    if shutil.which("quarto") is None:
        raise DeckDependencyError("Formeln in Folien benoetigen Quarto und Typst.")
    try:
        parsed = run_process(
            ["quarto", "pandoc", "--from", "markdown+tex_math_single_backslash+hard_line_breaks", "--to", "json", "--fail-if-warnings"],
            input=markdown, text=True, capture_output=True, timeout=60, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise FormulaRenderError("Zeitlimit beim Lesen einer Formel ueberschritten.") from error
    if parsed.returncode:
        raise FormulaRenderError(f"Formel konnte nicht gelesen werden: {parsed.stderr.strip()}")
    document = json.loads(parsed.stdout)

    def contains_math(node):
        if isinstance(node, dict):
            return node.get("t") in {"Math", "Strong", "Emph"} or any(contains_math(value) for value in node.values())
        if isinstance(node, list):
            return any(contains_math(value) for value in node)
        return False

    if contains_math(document):
        return document
    if markdown.lstrip().startswith(("$$", r"\[")):
        raise FormulaRenderError("Der Formelblock enthaelt keine gueltige Markdown-Formel; Leerzeilen innerhalb der Formel entfernen.")
    return None


@lru_cache(maxsize=16)
def _formula_font(font: str) -> tuple[str, bytes | None]:
    folder, family = FONT_DIRECTORIES[font]
    sources = sorted((FONT_ROOT / folder).glob("*.woff2"))
    if not sources:
        installed = run_process(["typst", "fonts"], text=True, capture_output=True, check=False, timeout=60)
        if installed.returncode == 0 and family in installed.stdout.splitlines():
            return family, None
        raise DeckDependencyError(
            f"Schrift '{family}' fehlt fuer Formeln. Die Schriften mit npm ci in "
            "src/excalideck/present installieren oder die Schrift im System bereitstellen."
        )
    try:
        from fontTools.merge import Merger
        from fontTools.ttLib import TTFont
        from fontTools.ttLib.woff2 import haveBrotli
    except ImportError as error:
        raise DeckDependencyError("Formelschriften benoetigen fonttools[woff]: pip install -e '.[deck]'.") from error
    with tempfile.TemporaryDirectory() as temporary:
        converted = []
        for index, source in enumerate(sources):
            target = Path(temporary) / f"font-{index}.ttf"
            if not haveBrotli:
                if shutil.which("woff2_decompress") is None:
                    raise DeckDependencyError("WOFF2-Schriften benoetigen Brotli: pip install -e '.[deck]'.")
                compressed = target.with_suffix(".woff2")
                shutil.copyfile(source, compressed)
                run_process(["woff2_decompress", str(compressed)], capture_output=True, check=True, timeout=60)
            else:
                face = TTFont(source)
                face.flavor = None
                face.save(target)
                face.close()
            converted.append(str(target))
        merged = Merger().merge(converted)
        target = Path(temporary) / "merged.ttf"
        merged.save(target)
        merged.close()
        return family, target.read_bytes()


_PATH_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_IDENTITY_MATRIX = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _multiply_matrix(base: tuple, other: tuple) -> tuple:
    a1, b1, c1, d1, e1, f1 = base
    a2, b2, c2, d2, e2, f2 = other
    return (
        a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1,
    )


def _parse_transform(value: str | None) -> tuple:
    matrix = _IDENTITY_MATRIX
    if not value:
        return matrix
    for name, arguments in re.findall(r"(\w+)\s*\(([^)]*)\)", value):
        numbers = [float(item) for item in re.split(r"[\s,]+", arguments.strip()) if item]
        if name == "matrix" and len(numbers) == 6:
            matrix = _multiply_matrix(matrix, tuple(numbers))
        elif name == "translate" and numbers:
            offset = numbers[1] if len(numbers) > 1 else 0.0
            matrix = _multiply_matrix(matrix, (1.0, 0.0, 0.0, 1.0, numbers[0], offset))
        elif name == "scale" and numbers:
            scale_y = numbers[1] if len(numbers) > 1 else numbers[0]
            matrix = _multiply_matrix(matrix, (numbers[0], 0.0, 0.0, scale_y, 0.0, 0.0))
    return matrix


def _path_points(data: str) -> list[tuple[float, float]]:
    """Stuetz- und Kontrollpunkte eines Pfades; ueberschaetzt die Tinte grosszuegig."""
    tokens = _PATH_TOKEN.findall(data)
    points: list[tuple[float, float]] = []
    x = y = 0.0
    index = 0
    command = ""
    while index < len(tokens):
        token = tokens[index]
        if not token[0].isdigit() and token[0] not in "-+.":
            command = token
            index += 1
            continue
        upper = command.upper()
        if not upper or upper == "Z":
            index += 1
            continue
        arity = {"M": 2, "L": 2, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "H": 1, "V": 1}[upper]
        if index + arity > len(tokens):
            break
        arguments = [float(tokens[index + step]) for step in range(arity)]
        index += arity
        relative = command.islower()
        if upper == "H":
            x = arguments[0] + (x if relative else 0.0)
            points.append((x, y))
        elif upper == "V":
            y = arguments[0] + (y if relative else 0.0)
            points.append((x, y))
        elif upper == "A":
            x, y = (x + arguments[-2], y + arguments[-1]) if relative else (arguments[-2], arguments[-1])
            points.append((x, y))
        else:
            for step in range(0, arity, 2):
                point_x, point_y = arguments[step], arguments[step + 1]
                if relative:
                    point_x += x
                    point_y += y
                points.append((point_x, point_y))
            x, y = points[-1]
    return points


def _svg_ink_bbox(svg: str) -> tuple | None:
    """Tinte-Box (links, oben, rechts, unten) aller Pfadpunkte eines SVGs inklusive Transformationen."""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return None
    by_id = {element.get("id"): element for element in root.iter() if element.get("id")}
    box = [float("inf"), float("inf"), float("-inf"), float("-inf")]

    def extend(points: list[tuple[float, float]], matrix: tuple) -> None:
        a, b, c, d, e, f = matrix
        for point_x, point_y in points:
            x = a * point_x + c * point_y + e
            y = b * point_x + d * point_y + f
            box[0] = min(box[0], x)
            box[1] = min(box[1], y)
            box[2] = max(box[2], x)
            box[3] = max(box[3], y)

    def walk(element: ET.Element, matrix: tuple, depth: int) -> None:
        if depth > 16:
            return
        matrix = _multiply_matrix(matrix, _parse_transform(element.get("transform")))
        if element.tag.endswith("path") and element.get("d"):
            extend(_path_points(element.get("d")), matrix)
        elif element.tag.endswith("use"):
            href = element.get(_XLINK_HREF) or element.get("href")
            target = by_id.get((href or "").lstrip("#"))
            if target is not None:
                offset = _multiply_matrix(
                    matrix, (1.0, 0.0, 0.0, 1.0, float(element.get("x", 0)), float(element.get("y", 0)))
                )
                walk(target, offset, depth + 1)
            return
        elif element.tag.endswith("defs"):
            # Glyphen-Definitionen zaehlen nur, wenn ein <use> sie referenziert.
            return
        for child in element:
            walk(child, matrix, depth + 1)

    walk(root, _IDENTITY_MATRIX, 0)
    return tuple(box) if box[0] <= box[2] else None


def _expand_svg_viewbox(svg: str, padding: float = 0.0) -> str:
    """viewBox eines Typst-SVGs auf die Glyph-Tinte erweitern.

    Typst hoeht eine Formelseite auf die Zeilenhoehe; hochgestellte Exponenten
    und tief reichende Klammern ragen darueber hinaus. Excalidraw rasterisiert
    SVG-Bilder auf einen Canvas und schneidet dabei alles ausserhalb der
    viewBox ab; deshalb muss die viewBox die Tinte vollstaendig enthalten.
    `padding` haelt zusaetzlichen Rand zur neuen Kante (Sicherheit gegen
    Rundung und Antialiasing); ohne Ueberhang bleibt das SVG unveraendert.
    """
    opening = re.search(r"<svg\b[^>]*>", svg)
    if not opening:
        return svg
    tag = opening.group(0)
    view_box = re.search(r'viewBox="([^"]+)"', tag)
    if not view_box:
        return svg
    try:
        x, y, width, height = (float(value) for value in view_box.group(1).split())
    except ValueError:
        return svg
    ink = _svg_ink_bbox(svg)
    if ink is None:
        return svg
    left, top = min(x, ink[0]), min(y, ink[1])
    right, bottom = max(x + width, ink[2]), max(y + height, ink[3])
    if (left, top, right, bottom) == (x, y, x + width, y + height):
        return svg
    left, top = left - padding, top - padding
    right, bottom = right + padding, bottom + padding
    tag = re.sub(r'viewBox="[^"]*"', f'viewBox="{left} {top} {right - left} {bottom - top}"', tag)
    tag = re.sub(r'width="[^"]*"', f'width="{right - left}pt"', tag, count=1)
    tag = re.sub(r'height="[^"]*"', f'height="{bottom - top}pt"', tag, count=1)
    return tag + svg[opening.end():]


@lru_cache(maxsize=128)
def _render_formula_svg(markdown: str, fontsize: int, font: str, color: str, width: float | None = None) -> str:
    if shutil.which("quarto") is None or shutil.which("typst") is None:
        raise DeckDependencyError("Formeln in Folien benoetigen Quarto und Typst.")
    document = _math_document(markdown)
    if document is None:
        raise FormulaRenderError("Der Text enthaelt keine gueltige Markdown-Formel.")

    def check_math(node):
        if isinstance(node, dict):
            if node.get("t") == "Math" and re.search(r"\\(?:color|textcolor)\b", node["c"][1]):
                raise FormulaRenderError("LaTeX-Farben werden nicht verlustfrei unterstuetzt. Fuer rote Formeltexte [Rot …] verwenden.")
            for value in node.values():
                check_math(value)
        elif isinstance(node, list):
            for value in node:
                check_math(value)

    check_math(document)
    try:
        converted = run_process(
            ["quarto", "pandoc", "--from", "json", "--to", "typst", "--fail-if-warnings"],
            input=json.dumps(document), text=True, capture_output=True, timeout=60, check=False,
        )
        if converted.returncode:
            raise FormulaRenderError(f"Formel konnte nicht konvertiert werden: {converted.stderr.strip()}")
        with tempfile.TemporaryDirectory() as temporary:
            family, font_data = _formula_font(font)
            if font_data is not None:
                (Path(temporary) / "font.ttf").write_bytes(font_data)
            source = Path(temporary) / "formula.typst"
            target = Path(temporary) / "formula.svg"
            source.write_text(
                f'#set page(width: {str(width) + "pt" if width is not None else "auto"}, height: auto, margin: 0pt)\n'
                f'#set text(size: {fontsize}pt, font: {json.dumps(family)}, fill: rgb("{color}"))\n'
                '#set par(leading: 0.75em)\n'
                + converted.stdout,
                encoding="utf-8",
            )
            compiled = run_process(
                ["typst", "compile", "--font-path", temporary, "--format", "svg", str(source), str(target)],
                text=True, capture_output=True, timeout=60, check=False,
            )
            if compiled.returncode or compiled.stderr.strip():
                raise FormulaRenderError(f"Formel konnte nicht gesetzt werden: {compiled.stderr.strip()}")
            return _expand_svg_viewbox(target.read_text(encoding="utf-8"), fontsize * 0.05)
    except subprocess.TimeoutExpired as error:
        raise FormulaRenderError("Zeitlimit beim Rendern einer Formel ueberschritten.") from error


def _text_element(scene, content: str, fontsize: int, font: str, color: str = "#000000", width: float | None = None):
    if _math_document(content) is not None:
        svg = (_render_formula_svg(content, fontsize, font, color) if width is None else
               _render_formula_svg(content, fontsize, font, color, width))
        return scene.image().data(svg)
    return scene.text(content).align("left").fontsize(fontsize).font(font).color(color)


def _render_marker_svg(marker: str) -> str:
    sketches_path = MODEL_FILTER.with_name("algorithm_sketches.lua")
    filter_content = MODEL_FILTER.read_bytes()
    if sketches_path.is_file():
        filter_content += sketches_path.read_bytes()
    return _render_marker_svg_cached(marker, MODEL_FILTER, filter_content)


@lru_cache(maxsize=64)
def _render_marker_svg_cached(marker: str, filter_path: Path, filter_content: bytes) -> str:
    """Kuerzel ([Modell …], [Skizze …], [Einheitskreis …], [Koordinatensystem …])
    ueber den Projektfilter (exam.lua) in SVG zeichnen.

    Die Zeichnung passiert erst beim Deck-Generieren; die Outline enthaelt
    nur das Kuerzel, keine Bilddatei. Identische Kuerzel werden bei gleichem
    Filterinhalt nur einmal gezeichnet (lru_cache). Filteraenderungen erzeugen
    auch im laufenden UI-Prozess neue Bilder.
    """
    if shutil.which("quarto") is None:
        raise DeckDependencyError(
            "Quarto fehlt zum Zeichnen von Kuerzeln. Installation: "
            "https://quarto.org (oder Kuerzel durch ![](pfad.svg) ersetzen)."
        )
    with tempfile.TemporaryDirectory() as tmp:
        media = Path(tmp)
        result = run_process(
            [
                "quarto", "pandoc", "--from", "markdown", "--to", "typst",
                "--lua-filter", str(filter_path),
                "--extract-media", str(media),
            ],
            input=marker, text=True, capture_output=True, timeout=60, check=False,
        )
        if result.returncode != 0:
            raise ModelRenderError(
                f"Kuerzel konnte nicht gezeichnet werden: {result.stderr.strip() or marker}"
            )
        drawings = sorted(media.glob("*.svg"))
        if not drawings:
            raise ModelRenderError(f"Kuerzel hat kein SVG erzeugt: {marker}")
        return drawings[0].read_text(encoding="utf-8")


def _import_scene_builder():
    try:
        from excaligen.SceneBuilder import SceneBuilder
    except ImportError as error:
        raise DeckDependencyError(
            "Excaligen fehlt. Installation: pip install excaligen "
            "(oder pip install -e '.[deck]' im Repo-Root)."
        ) from error
    return SceneBuilder


def _block_height(block: TextBlock) -> float:
    return len(block.lines) * block.fontsize * LINE_HEIGHT_FACTOR


def _lighten(color: str, amount: float) -> str:
    """Hex-Farbe Richtung Weiss mischen (amount 0..1), wie typst lighten()."""
    red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    mixed = (round(value + (255 - value) * amount) for value in (red, green, blue))
    return "#" + "".join(f"{value:02x}" for value in mixed)


def _build_box(scene, block: BoxBlock, x: float, y: float, width: float, outline: DeckOutline,
               content_color: str, children: list, base_dir: Path) -> float:
    """Kasten (Infobox/Warnbox/Tippbox) als Rechteck mit Titelzeile zeichnen.

    Das Rechteck entsteht zuerst, damit es im Deck hinter den Texten liegt;
    seine Groesse wird nach dem Layout des Inhalts gesetzt. Zurueck kommt
    die absolute Unterkante des Kastens.
    """
    design = outline.design if outline.design is not None else design_by_id(outline.design_id)
    # Kastenmotive stammen aus dem Designdatensatz (private Designs liefern sie mit):
    # "box_mascot" = Maskottchen neben dem Kasten, "box_icons" = Symbole je Kastenart.
    mascot_boxes = bool(design and design.get("box_mascot"))
    icon_boxes = bool(design and design.get("box_icons"))
    accent = design["primary"] if (mascot_boxes or icon_boxes) and block.kind == "infobox" else BOX_ACCENTS[block.kind]
    shadow = None
    if icon_boxes:
        shadow = (scene.rectangle().position(x + 5, y + 5).background(design["ink"])
                  .fill("solid").color(design["ink"]).roundness("sharp"))
    rectangle = None
    if not (design and design.get("writing_grid")):
        rectangle = (
            scene.rectangle()
            .position(x, y)
            .background(_lighten(accent, BOX_LIGHTEN))
            .fill("solid")
            .color(accent)
            .thickness(2)
            .roundness("sharp" if icon_boxes else "round")
        )
    mascot_width = min(120.0, width * 0.22) if mascot_boxes else 0.0
    mascot_gutter = mascot_width + 16 if mascot_boxes else 0.0
    inner_x = x + BOX_PADDING_X + mascot_gutter
    inner_width = max(1.0, width - 2 * BOX_PADDING_X - mascot_gutter)
    title_width = max(1.0, inner_width - 64) if icon_boxes else inner_width
    title_block = _wrap_text_block(TextBlock((block.title,), BOX_TITLE_FONTSIZE, "text"), title_width) if mascot_boxes or icon_boxes else None
    title = _text_element(scene, "\n".join(title_block.lines) if title_block else block.title,
                          BOX_TITLE_FONTSIZE, outline.text_font if icon_boxes else outline.heading_font, accent)
    title.position(inner_x + (64 if icon_boxes else 0), y + BOX_PADDING_Y)
    inner_y = y + BOX_PADDING_Y + max(title.size()[1], 52 if icon_boxes else 0) + BLOCK_GAP / 2
    if icon_boxes:
        icon = scene.image().data(design["box_icons"][block.kind]).position(inner_x, y + BOX_PADDING_Y).size(48, 48)
        children.append(icon)
    inner_bottom, _ = _layout_blocks(
        scene, tuple(_wrap_text_block(item, inner_width) if (mascot_boxes or icon_boxes) and isinstance(item, TextBlock) else item
                     for item in block.blocks), inner_x, inner_y, inner_width,
        outline, content_color, children, base_dir,
    )
    content_bottom = max(inner_bottom - BLOCK_GAP, inner_y)
    if mascot_boxes:
        mascot_height = mascot_width * 200 / 180
        mascot = scene.image().data(design["box_mascot"])
        mascot.position(x + BOX_PADDING_X, y + BOX_PADDING_Y).size(mascot_width, mascot_height)
        children.append(mascot)
        content_bottom = max(content_bottom, y + BOX_PADDING_Y + mascot_height)
    if rectangle is not None:
        rectangle.size(width, content_bottom + BOX_PADDING_Y - y)
    if shadow:
        shadow.size(width, content_bottom + BOX_PADDING_Y - y)
        children.append(shadow)
    if rectangle is not None:
        children.append(rectangle)
    children.append(title)
    return content_bottom + BOX_PADDING_Y


def _layout_blocks(scene, blocks, x: float, y: float, width: float, outline: DeckOutline,
                   content_color: str, children: list, base_dir: Path,
                   design: dict | None = None) -> tuple[float, float]:
    """Bloecke in einer Spalte der Breite `width` ab (x, y) legen.

    Zurueck kommen die absolute Unterkante (inkl. Blockabstand) und die
    absolute rechte Kante des inhaltsreichsten Blocks.
    """
    right = x
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if isinstance(block, (ModelBlock, ImageBlock)):
            # Aufeinanderfolgende Bilder liegen nebeneinander: Jedes bekommt
            # einen fairen Anteil der Spaltenbreite, damit etwa zwei
            # Zahlenstriche wirklich side by side verglichen werden koennen.
            run_end = index + 1
            while run_end < len(blocks) and isinstance(blocks[run_end], (ModelBlock, ImageBlock)):
                run_end += 1
            share = (width - (run_end - index - 1) * BLOCK_GAP) / (run_end - index)
            cursor_x = x
            row_height = 0.0
            for item in blocks[index:run_end]:
                if isinstance(item, ModelBlock):
                    # fit statt size: breite Kuerzel (etwa Rechenstriche) werden in
                    # die Bildbox skaliert, ohne ihr Seitenverhaeltnis zu verzerren.
                    image = scene.image().data(_render_marker_svg(item.marker))
                else:
                    image_path = item.path if item.path.is_absolute() else base_dir / item.path
                    image = scene.image().file(str(image_path))
                image_width_limit = min(IMAGE_MAX_WIDTH, share)
                if isinstance(item, ImageBlock) and item.width is not None:
                    image_width_limit = share * item.width / 100
                image.fit(image_width_limit, IMAGE_MAX_HEIGHT)
                image.position(cursor_x, y)
                image_width, image_height = image.size()
                children.append(image)
                cursor_x += image_width + BLOCK_GAP
                row_height = max(row_height, image_height)
            right = max(right, cursor_x - BLOCK_GAP)
            y += row_height + BLOCK_GAP
            index = run_end
        elif isinstance(block, SpacerBlock):
            y += block.height_mm * SLIDE_WIDTH / 160
            index += 1
        elif isinstance(block, AnswerBlock):
            # 160 mm entsprechen der 1600 px breiten Folie.
            height = block.height_mm * SLIDE_WIDTH / 160
            rectangle = scene.rectangle().position(x, y).size(width, height).color(content_color).thickness(1).roundness("round")
            children.append(rectangle)
            right = max(right, x + width)
            y += height + BLOCK_GAP
            index += 1
        elif isinstance(block, BoxBlock):
            bottom = _build_box(scene, block, x, y, width, outline, content_color, children, base_dir)
            right = max(right, x + width)
            y = bottom + BLOCK_GAP
            index += 1
        elif isinstance(block, ColumnsBlock):
            bottom, columns_right = _layout_columns(
                scene, block, x, y, width, outline, content_color, children, base_dir
            )
            right = max(right, columns_right)
            y = bottom
            index += 1
        else:
            if design and design.get("writing_grid"):
                block = _wrap_text_block(block, width)
            text = _text_element(
                scene, "\n".join(block.lines), block.fontsize,
                outline.heading_font if block.kind in HEADING_KINDS else outline.text_font,
                MARKER_RED if block.kind == "rot" else content_color,
                width=width - block.fontsize * 0.2 if design and design.get("writing_grid") else None,
            )
            text.position(x, y)
            children.append(text)
            right = max(right, x + text.size()[0])
            height = text.size()[1] if _math_document("\n".join(block.lines)) is not None else _block_height(block)
            y = max(200, y + height + BLOCK_GAP) if design and block.kind == "titel" else y + height + BLOCK_GAP
            index += 1
    return y, right


def _wrap_line(line: str, max_chars: int) -> list[str]:
    """Eine Zeile wortweise auf max_chars Zeichen umbrechen."""
    if len(line) <= max_chars:
        return [line]
    lines: list[str] = []
    current = ""
    for word in line.split(" "):
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _wrap_text_block(block: TextBlock, width: float) -> TextBlock:
    """Textblock auf eine Zielbreite in Pixeln umbrechen.

    Excalidraw-Textelemente haben keine eigene Breite: Ohne Umbruch ragen
    laengere Zeilen aus schmalen Spalten ueber den Folienrand. Formel-Bloecke
    werden als SVG-Bild gesetzt und bleiben unverändert; Abschnitts- und
    Titelzeilen sind kurz und werden ebenfalls nicht angefasst.
    """
    if block.kind not in ("absatz", "bullets") or _math_document("\n".join(block.lines)) is not None:
        return block
    max_chars = max(1, int(width / (block.fontsize * TEXT_CHAR_WIDTH_FACTOR)))
    wrapped: list[str] = []
    for line in block.lines:
        if len(line) <= max_chars:
            wrapped.append(line)
            continue
        stripped = line.lstrip()
        first_lead = line[: len(line) - len(stripped)]
        lead = first_lead
        if block.kind == "bullets" and stripped.startswith("- "):
            lead += "  "
        for index, part in enumerate(_wrap_line(stripped, max(1, max_chars - len(lead)))):
            wrapped.append(first_lead + part if index == 0 else lead + part)
    return TextBlock(tuple(wrapped), block.fontsize, block.kind)


def _layout_columns(scene, block: ColumnsBlock, x: float, y: float, width: float,
                    outline: DeckOutline, content_color: str, children: list, base_dir: Path) -> tuple[float, float]:
    """Spalten eines Spalten-Layouts nebeneinander legen.

    Breiten sind Prozentangaben wie im Projektfilter (exam.lua): Spalten ohne
    Breite teilen sich den Rest, zusammen muss unter 100 bleiben. Text wird
    auf die Spaltenbreite umbrochen, damit er nicht aus der Spalte herauslaeuft.
    Zurueck kommen die Unterkante der tiefsten Spalte (inkl. Blockabstand)
    und die absolute rechte Kante.
    """
    columns = block.columns
    given = sum(column.width for column in columns if column.width is not None)
    if given >= 100:
        raise ValueError("Spalten: Die angegebenen Breiten muessen zusammen unter 100 Prozent bleiben.")
    unspecified = sum(1 for column in columns if column.width is None)
    default = (100 - given) / unspecified if unspecified else 0.0
    usable = width - (len(columns) - 1) * BLOCK_GAP
    cursor_x = x
    bottom = y
    right = x
    for column in columns:
        column_width = usable * ((column.width if column.width is not None else default) / 100)
        blocks = tuple(
            _wrap_text_block(item, column_width) if isinstance(item, TextBlock) else item
            for item in column.blocks
        )
        column_bottom, column_right = _layout_blocks(
            scene, blocks, cursor_x, y, column_width,
            outline, content_color, children, base_dir,
        )
        bottom = max(bottom, column_bottom)
        right = max(right, column_right)
        cursor_x += column_width + BLOCK_GAP
    return bottom, right


def _slide_decoration(scene, design: dict, x_offset: float, number: int):
    background = scene.image().data(design["slide_background"])
    background.position(x_offset, 0).size(SLIDE_WIDTH, SLIDE_HEIGHT)
    children = [background]
    if number is not None:
        number_label = scene.text(str(number)).fontsize(20).font("Normal").color(design["primary"])
        children.append(number_label.position(x_offset + 1510, 852))
    return children


def _is_title_sheet(slide: Slide) -> bool:
    """Folie, die nur aus der h1-Ueberschrift besteht: Sie wird als
    Titelfolienblatt mit zentrierter Ueberschrift gezeichnet."""
    block = slide.blocks[0] if len(slide.blocks) == 1 else None
    return isinstance(block, TextBlock) and block.kind == "titel"


def _build_title_sheet(scene, slide: Slide, x_offset: float, outline: DeckOutline,
                       design: dict | None, children: list) -> tuple[float, float]:
    """Titelfolienblatt: Die h1-Ueberschrift steht horizontal und vertikal
    zentriert, ohne Design in der Folienmitte, mit Design in der
    Inhaltsflaeche des Design-Hintergrunds (unter dem Kopfband)."""
    block = slide.blocks[0]
    title = _text_element(
        scene, "\n".join(block.lines), block.fontsize, outline.heading_font,
        design["ink"] if design else "#000000",
    )
    width, height = title.size()
    box_left, box_top, box_width, box_height = (
        DESIGN_CONTENT_BOX if design else (0.0, 0.0, SLIDE_WIDTH, SLIDE_HEIGHT)
    )
    center_x = x_offset + box_left + (box_width - width) / 2
    center_y = box_top + (box_height - height) / 2
    title.position(center_x, center_y)
    children.append(title)
    return center_y + height, center_x - x_offset + width


def _frame_slide(scene, slide: Slide, x_offset: float, children: list) -> None:
    # Excalidraw fuegt neue Striche unmittelbar VOR dem Frame ein.
    # Der Frame muss deshalb hinter seinen Kindern (auch dem Hintergrund)
    # stehen, sonst verschwinden Anmerkungen unter dem Template.
    frame = scene.frame(slide.title)
    # Feste Foliengroesse (16:9): Excaligen wuerde den Frame sonst an den
    # Inhalt anpassen, sodass Frames im Vollbild-Present-Modus keine
    # einheitliche Seite bilden.
    frame.position(x_offset, 0.0)
    frame.size(SLIDE_WIDTH, SLIDE_HEIGHT)
    frame.elements(*children)


def _build_slide(scene, slide: Slide, x_offset: float, base_dir: Path, outline: DeckOutline, number: int = 1) -> tuple[float, float]:
    y = SLIDE_MARGIN
    right = 0.0
    design = outline.design if outline.design is not None else design_by_id(outline.design_id)
    children = _slide_decoration(scene, design, x_offset, number) if design else []
    margin = 64.0 if design else SLIDE_MARGIN
    content_color = design["ink"] if design else "#000000"
    # Eine Folie nur aus h1 wird zum Titelfolienblatt mit zentrierter
    # Ueberschrift; der Folientitel steht dabei nicht zusaetzlich im Frame.
    if _is_title_sheet(slide):
        bottom, right_edge = _build_title_sheet(scene, slide, x_offset, outline, design, children)
        _frame_slide(scene, slide, x_offset, children)
        return bottom, right_edge
    # Der Folientitel steht zusaetzlich als Ueberschrift im Frame: Der
    # Frame-Name ist in Excalidraw nur klein grau ueber der Folie sichtbar.
    # Die Titelfolie traegt ihren Titel bereits als grossen Textblock.
    if not any(isinstance(block, TextBlock) and block.kind == "titel" for block in slide.blocks):
        title = _text_element(scene, slide.title, SLIDE_TITLE_FONTSIZE, outline.heading_font,
                              design.get("heading_ink", design["ink"]) if design else "#000000")
        if design and design.get("writing_grid"):
            title_width, title_height = title.size()
            factor = min(1, 1320 / max(1, title_width), 90 / max(1, title_height))
            if _math_document(slide.title) is not None:
                title.size(title_width * factor, title_height * factor)
            else:
                title.fontsize(max(1, int(SLIDE_TITLE_FONTSIZE * factor)))
        title.position(x_offset + margin, 52 if design else y)
        children.append(title)
        right = max(right, margin + title.size()[0])
        y = 200 if design else y + max(SLIDE_TITLE_FONTSIZE * LINE_HEIGHT_FACTOR, title.size()[1]) + BLOCK_GAP
    elif design:
        y = 52
    bottom, right_edge = _layout_blocks(
        scene, slide.blocks, x_offset + margin, y, SLIDE_WIDTH - 2 * margin,
        outline, content_color, children, base_dir, design,
    )
    right = max(right, right_edge - x_offset)
    _frame_slide(scene, slide, x_offset, children)
    return bottom, right


def _build_scene(outline: DeckOutline, scene, base_dir: Path):
    x_offset = 0.0
    design = outline.design if outline.design is not None else design_by_id(outline.design_id)
    writing = design and design.get("writing_grid")
    content_number = 0
    for number, slide in enumerate(outline.slides, start=1):
        if writing:
            if _is_title_sheet(slide):
                number = None
            else:
                content_number += 1
                number = content_number
        # Rueckgabewerte sind die Unterkante des letzten Blocks (inkl.
        # BLOCK_GAP) und der rechteste Rand; Content darunter/dahinter
        # wuerde aus der festen Foliengroesse herausragen.
        bottom, right = _build_slide(scene, slide, x_offset, base_dir, outline, number)
        content_bottom = 804 if outline.design_id else SLIDE_HEIGHT
        if bottom - BLOCK_GAP > content_bottom:
            warnings.warn(
                f"Folie '{slide.title}': Inhalt ragt {bottom - BLOCK_GAP - content_bottom:.0f} px "
                "ueber den unteren Folienrand; Folie kuerzen oder auf zwei Folien aufteilen.",
                stacklevel=3,
            )
        if right > SLIDE_WIDTH:
            warnings.warn(
                f"Folie '{slide.title}': Inhalt ragt {right - SLIDE_WIDTH:.0f} px "
                "ueber den rechten Folienrand; Zeilen kuerzen oder umbrechen.",
                stacklevel=3,
            )
        x_offset += SLIDE_PITCH


def generate_deck(
    outline_path: Path,
    *,
    output_path: Path | None = None,
    force: bool = False,
) -> Path:
    """Aus einer Outline-Datei ein Excalidraw-Deck erzeugen.

    Standardziel ist die Outline-Datei mit .excalidraw-Suffix. Existiert das
    Ziel bereits, wird ohne force ein DeckExistsError geworfen.
    """
    outline_path = Path(outline_path)
    output = Path(output_path) if output_path else outline_path.with_suffix(".excalidraw")
    if output.exists() and not force:
        raise DeckExistsError(output)
    outline = parse_outline(outline_path)
    if not outline.slides:
        raise ValueError(f"Outline ohne Folien: {outline_path}")
    scene = _import_scene_builder()()
    _build_scene(outline, scene, outline_path.parent)
    output.parent.mkdir(parents=True, exist_ok=True)
    scene.save(str(output))
    return output
