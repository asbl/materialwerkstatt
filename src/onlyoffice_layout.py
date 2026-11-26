from __future__ import annotations

import argparse
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pymupdf
import yaml
from material_core import workspace


ROOT = workspace.root()
TEMPLATE = ROOT / "src/quarto/templates/import-layout.tex"


def number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


def point(value) -> str:
    return f"({number(value[0])},{number(value[1])})"


def tex_text(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}",
        "#": r"\#", "$": r"\$", "%": r"\%", "&": r"\&",
        "_": r"\_", "^": r"\textasciicircum{}", "~": r"\textasciitilde{}",
        " ": r"\ ",
    }
    return "".join(replacements.get(character, character) for character in value)


def font_file(name: str) -> str:
    if name == "Helvetica":
        return "LiberationSans-Regular.ttf"
    if name == "OpenSymbol":
        return "LiberationSerif-Regular.ttf"
    if name == "Aptos-BoldItalic":
        return "Aptos-Bold-Italic.ttf"
    if name in {"LiberationSans", "LiberationSerif", "LiberationMono"}:
        return f"{name}-Regular.ttf"
    return f"{name}.ttf"


def rgb(value) -> str:
    return ",".join(str(round(component * 255)) for component in value)


def rgb_option(value) -> str:
    red, green, blue = rgb(value).split(",")
    return f"{{rgb,255:red,{red};green,{green};blue,{blue}}}"


def drawing_tex(drawing: dict) -> str:
    options = ["draw=none", "fill=none"]
    if drawing.get("color") is not None:
        options.extend([
            f"draw={rgb_option(drawing['color'])}",
            f"line width={number(drawing['width'])}bp",
            f"draw opacity={number(drawing.get('stroke_opacity', 1))}",
        ])
    if drawing.get("fill") is not None:
        options.extend([
            f"fill={rgb_option(drawing['fill'])}",
            f"fill opacity={number(drawing.get('fill_opacity', 1))}",
        ])
    if drawing.get("even_odd"):
        options.append("even odd rule")
    if drawing.get("dashes"):
        dash_array = re.search(r"\[([^]]*)\]", drawing["dashes"])
        lengths = dash_array.group(1).split() if dash_array else []
        if lengths:
            pattern = " ".join(f"{'on' if index % 2 == 0 else 'off'} {length}bp" for index, length in enumerate(lengths))
            options.append(f"dash pattern={pattern}")
    paths = []
    previous = None
    for item in drawing["items"]:
        if item[0] in {"l", "c"}:
            if item[1] != previous:
                paths.append(point(item[1]))
            if item[0] == "l":
                paths.append(f"-- {point(item[2])}")
            else:
                paths.append(f".. controls {point(item[2])} and {point(item[3])} .. {point(item[4])}")
            previous = item[-1]
        elif item[0] == "re":
            paths.append(f"{point(item[1].tl)} rectangle {point(item[1].br)}")
            previous = None
        else:
            raise ValueError(f"Nicht unterstützter Zeichenpfad: {item[0]}")
    if drawing.get("closePath"):
        paths.append("-- cycle")
    return f"\\path[{','.join(options)}] {' '.join(paths)};"


def rgb_pixmap(pixmap: pymupdf.Pixmap) -> pymupdf.Pixmap:
    if pixmap.alpha:
        pixmap = pymupdf.Pixmap(pixmap, 0)
    if pixmap.n != 3:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
    return pixmap


def svg_clip(path: ET.Element) -> str:
    tokens = re.findall(r"[A-Za-z]|[-+]?(?:\d*\.)?\d+(?:[eE][-+]?\d+)?", path.attrib["d"])
    transform = path.get("transform", "matrix(1,0,0,1,0,0)")
    matrix = pymupdf.Matrix(*map(float, re.findall(r"[-+]?(?:\d*\.)?\d+(?:[eE][-+]?\d+)?", transform)))
    cursor = pymupdf.Point(0, 0)
    parts = []
    position = 0
    command = "M"
    while position < len(tokens):
        if tokens[position].isalpha():
            command = tokens[position]
            position += 1
        count = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Z": 0}.get(command)
        if count is None:
            raise ValueError(f"Nicht unterstützter Bildbeschnitt: {command}")
        values = list(map(float, tokens[position:position + count]))
        position += count
        if command in {"M", "L"}:
            cursor = pymupdf.Point(*values)
            parts.append(("-- " if command == "L" else "") + point(cursor * matrix))
            command = "L"
        elif command in {"H", "V"}:
            cursor = pymupdf.Point(values[0], cursor.y) if command == "H" else pymupdf.Point(cursor.x, values[0])
            parts.append(f"-- {point(cursor * matrix)}")
        elif command == "C":
            controls = [pymupdf.Point(*values[index:index + 2]) * matrix for index in (0, 2, 4)]
            parts.append(f".. controls {point(controls[0])} and {point(controls[1])} .. {point(controls[2])}")
            cursor = pymupdf.Point(*values[4:6])
        else:
            parts.append("-- cycle")
    return "\\clip " + " ".join(parts) + ";"


def image_clips(page: pymupdf.Page) -> list[tuple[str, ...]]:
    svg = ET.fromstring(page.get_svg_image(text_as_path=False))
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    clips = {
        element.attrib["id"]: tuple(svg_clip(path) for path in element)
        for element in svg.findall(".//svg:clipPath", namespace)
    }
    references = {element.attrib["id"]: element for element in svg.iter() if "id" in element.attrib}
    result = []

    def visit(element: ET.Element, inherited: tuple[str, ...]) -> None:
        kind = element.tag.rsplit("}", 1)[-1]
        if kind == "defs":
            return
        clip = element.get("clip-path")
        if clip:
            inherited += clips[clip.removeprefix("url(#").removesuffix(")")]
        if kind == "use":
            reference = element.attrib["{http://www.w3.org/1999/xlink}href"].removeprefix("#")
            visit(references[reference], inherited)
        elif kind == "image":
            result.append(inherited)
        else:
            for child in element:
                visit(child, inherited)

    visit(svg, ())
    return result


class ImageCatalog:
    def __init__(self, directory: Path):
        self.directory = directory
        self.candidates: dict[tuple[int, int], list[Path]] = {}
        self.matches: dict[int, Path] = {}
        for path in sorted((directory / "media").rglob("*")):
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                continue
            pixmap = pymupdf.Pixmap(path)
            self.candidates.setdefault((pixmap.width, pixmap.height), []).append(path)

    def match(self, document: pymupdf.Document, xref: int) -> Path:
        if xref in self.matches:
            return self.matches[xref]
        pixmap = rgb_pixmap(pymupdf.Pixmap(document, xref))
        candidates = self.candidates.get((pixmap.width, pixmap.height), [])
        if candidates:
            source_pixels = np.frombuffer(pixmap.samples, dtype=np.uint8).astype(np.int16)

            def difference(path: Path) -> float:
                candidate = rgb_pixmap(pymupdf.Pixmap(path))
                pixels = np.frombuffer(candidate.samples, dtype=np.uint8).astype(np.int16)
                return float(np.abs(pixels - source_pixels).mean())

            target = min(candidates, key=difference)
            if difference(target) > 12:
                candidates = []
        if not candidates:
            target = self.directory / "layout" / f"bild-{xref}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            mask = document.extract_image(xref).get("smask", 0)
            output = pymupdf.Pixmap(pixmap, pymupdf.Pixmap(document, mask)) if mask else pixmap
            output.save(target)
        self.matches[xref] = target
        return target


def page_tex(page: pymupdf.Page, catalog: ImageCatalog, source_dir: Path) -> str:
    elements = []
    for drawing in page.get_drawings():
        elements.append((drawing["seqno"], drawing_tex(drawing)))
    image_orders = [index for index, item in enumerate(page.get_bboxlog()) if item[0] == "fill-image"]
    for order, info, clips in zip(image_orders, page.get_image_info(xrefs=True), image_clips(page), strict=True):
        transform = info["transform"]
        if abs(transform[1]) > 0.001 or abs(transform[2]) > 0.001:
            raise ValueError("Gedrehte Bilder benötigen eine gesonderte Layoutanpassung.")
        image = catalog.match(page.parent, info["xref"])
        bounds = pymupdf.Rect(info["bbox"])
        reference = image.relative_to(source_dir).as_posix()
        image_tex = f"\\importbild{{{number(bounds.x0)}}}{{{number(bounds.y0)}}}{{{number(bounds.width)}}}{{{number(bounds.height)}}}{{{reference}}}"
        if clips:
            image_tex = "\n".join([r"\begin{scope}", *clips, image_tex, r"\end{scope}"])
        elements.append((order, image_tex))
    for span in page.get_texttrace():
        if span["dir"] != (1.0, 0.0):
            raise ValueError("Gedrehter Text benötigt eine gesonderte Layoutanpassung.")
        text = "".join(chr(character[0]) for character in span["chars"])
        if not text.strip():
            continue
        origin = span["chars"][0][2]
        color = span["color"]
        if len(color) == 1:
            color = color * 3
        elements.append((span["seqno"], f"\\importtext{{{number(origin[0])}}}{{{number(origin[1])}}}{{{number(span['size'])}}}{{{font_file(span['font'])}}}{{{rgb(color)}}}{{{tex_text(text)}}}"))
    return "\n".join([r"\begin{importseite}", *(value for _, value in sorted(elements)), r"\end{importseite}"])


def _original_pdf(source: Path, imported: dict) -> Path:
    """Original-PDF des Imports: vorzugsweise ueber die source-pdf-Referenz.

    Die Referenz ist relativ zum Repo-Root (z. B. wissen/arbeitsblatt/...);
    aeltere Entwuerfe ohne Referenz nutzen die ehemalige assets/-Konvention.
    """
    referenz = imported.get("source-pdf")
    if isinstance(referenz, str) and referenz.strip():
        pfad = Path(referenz.strip())
        return pfad if pfad.is_absolute() else ROOT / pfad
    slug = source.stem.removesuffix("-entwurf")
    return source.parent / "assets" / slug / f"{slug}-original.pdf"


def layout_draft(source: Path) -> str:
    header = source.read_text(encoding="utf-8").split("---", 2)[1]
    metadata = yaml.safe_load(header)
    imported = metadata["material"]["import"]
    slug = source.stem.removesuffix("-entwurf")
    original = _original_pdf(source, imported)
    catalog = ImageCatalog(source.parent / "assets" / slug)
    with pymupdf.open(original) as document:
        sizes = {(round(page.rect.width, 3), round(page.rect.height, 3)) for page in document}
        if len(sizes) != 1:
            raise ValueError("Unterschiedliche Seitengrößen benötigen eine gesonderte Layoutanpassung.")
        width, height = next(iter(sizes))
        metadata["format"]["pdf"].update({
            "pdf-engine": "lualatex",
            "template": Path(os.path.relpath(TEMPLATE, source.parent)).as_posix(),
            "geometry": [f"paperwidth={number(width)}bp", f"paperheight={number(height)}bp", "margin=0pt"],
        })
        imported.update({"mode": "positioned-draft", "source-pages": len(document)})
        body = "\n\n".join(page_tex(page, catalog, source.parent) for page in document)
    metadata_text = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
    return f"---\n{metadata_text}---\n\n```{{=latex}}\n{body}\n```\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bearbeitbaren Entwurf nach dem Layout seiner Original-PDF rekonstruieren.")
    parser.add_argument("source", type=Path)
    arguments = parser.parse_args()
    print(layout_draft(arguments.source.resolve()), end="")


if __name__ == "__main__":
    main()
