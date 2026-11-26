"""Druckbare QMD aus einer Markdown-Outline (inv deck-print, inv deck-slides).

Die Outline bleibt die Quelle der Wahrheit fuer den Inhalt; die erzeugte
QMD laesst sich ueber die normale Material-Pipeline (`inv build`) drucken.
Anders als das Excalidraw-Deck ist die QMD kein One-Shot-Scaffold: Sie kann
jederzeit aus der Outline neu erzeugt werden. Manuelle Aenderungen an der
QMD werden ohne `force` nicht ueberschrieben.

Die Variante "druck" (inv deck-print) erzeugt ein A4-Flussdokument, die
Variante "slides" (inv deck-slides) eine Fassung mit einer 16:9-Folie pro
Seite in Excalidraw-aehnlicher Schrift.
"""

from __future__ import annotations

import os
from pathlib import Path

from excalideck.outline import (
    BOX_DEFAULT_TITLES,
    AnswerBlock,
    SpacerBlock,
    Block,
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

TEMPLATES_DIR = template_roots.SUPPORT / "templates"
TEMPLATE_PATHS = {
    # A4-Fließdokument mit Folien als Abschnitten.
    "druck": TEMPLATES_DIR / "deck-template.typst",
    # 16:9-Folien, eine Folie pro Seite, Excalidraw-aehnliche Schrift.
    "slides": TEMPLATES_DIR / "slide-template.typst",
}
MODEL_FILTER_PATH = template_roots.SUPPORT / "filters" / "exam.lua"
DEFAULT_TITLE = "Praesentation"


class PrintableExistsError(Exception):
    """Ziel-QMD existiert mit abweichendem Inhalt und soll ohne force nicht ueberschrieben werden."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Druckbare QMD existiert bereits: {path}")
        self.path = path


def _yaml_value(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _template_directive(base_dir: Path, variant: str) -> str:
    relative = os.path.relpath(TEMPLATE_PATHS[variant], start=base_dir)
    return "    template: " + Path(relative).as_posix()


def _filter_directive(base_dir: Path) -> str:
    relative = os.path.relpath(MODEL_FILTER_PATH, start=base_dir)
    return "  - " + Path(relative).as_posix()


def _needs_project_filter(outline: DeckOutline) -> bool:
    """Modell-Kuerzel und Box-Marker erst der Projektfilter (exam.lua) setzt;
    eigenstaendige Builds brauchen deshalb die explizite Filterangabe."""
    return any(
        isinstance(block, (ModelBlock, SpacerBlock, AnswerBlock, BoxBlock, ColumnsBlock))
        for slide in outline.slides
        for block in slide.blocks
    )


def _title_slide(outline: DeckOutline) -> tuple[Slide | None, tuple[Slide, ...]]:
    for index, slide in enumerate(outline.slides):
        if any(isinstance(block, TextBlock) and block.kind == "titel" for block in slide.blocks):
            return slide, outline.slides[index + 1 :]
    return None, outline.slides


def _deck_title(outline: DeckOutline, title_slide: Slide | None) -> str:
    if title_slide is not None:
        for block in title_slide.blocks:
            if isinstance(block, TextBlock) and block.kind == "titel":
                return block.lines[0]
    return outline.title or DEFAULT_TITLE


def _deck_subtitle(title_slide: Slide | None) -> str | None:
    if title_slide is None:
        return None
    for block in title_slide.blocks:
        if isinstance(block, TextBlock) and block.kind == "absatz":
            return " ".join(block.lines)
    return None


def _render_block(block: Block, lines: list[str]) -> None:
    if isinstance(block, SpacerBlock):
        lines.extend([f"[abstand {block.height_mm:g}mm]", ""])
        return
    if isinstance(block, AnswerBlock):
        lines.extend([f"[Antwortkasten: {block.height_mm:g}mm]", ""])
        return
    if isinstance(block, ModelBlock):
        # Kuerzel bleibt Text: Der Projektfilter zeichnet das Modell beim
        # Bauen der QMD, genau wie im restlichen Unterrichtsmaterial.
        lines.append(block.marker)
        lines.append("")
        return
    if isinstance(block, ImageBlock):
        attributes = f"{{width={block.width:g}%}}" if block.width is not None else ""
        lines.append(f"![]({block.path.as_posix()}){attributes}")
        lines.append("")
        return
    if isinstance(block, BoxBlock):
        # Marker bleiben Text: Der Projektfilter setzt den Kasten beim Bauen
        # der QMD, genau wie im restlichen Unterrichtsmaterial.
        label = block.kind.capitalize()
        if block.title == BOX_DEFAULT_TITLES[block.kind]:
            lines.append(f"[{label}]")
        else:
            lines.append(f"[{label}: {block.title}]")
        lines.append("")
        for inner in block.blocks:
            _render_block(inner, lines)
        lines.append(f"[/{label}]")
        lines.append("")
        return
    if isinstance(block, ColumnsBlock):
        # Div-Rahmen bleiben Text: Der Projektfilter legt die Spalten beim
        # Bauen der QMD nebeneinander, genau wie im restlichen Unterrichtsmaterial.
        lines.append("::: {.columns}")
        lines.append("")
        for column in block.columns:
            if column.width is None:
                lines.append("::: {.column}")
            else:
                lines.append(f'::: {{.column width="{column.width:g}%"}}')
            lines.append("")
            for inner in column.blocks:
                _render_block(inner, lines)
            lines.append(":::")
            lines.append("")
        lines.append(":::")
        lines.append("")
        return
    if block.kind == "abschnitt":
        lines.append(f"### {block.lines[0]}")
        lines.append("")
    elif block.kind == "bullets":
        lines.extend(block.lines)
        lines.append("")
    else:
        lines.append("\n".join(block.lines))
        lines.append("")


def render_printable_qmd(
    outline: DeckOutline, *, base_dir: Path, variant: str = "druck"
) -> str:
    """DeckOutline als QMD-Text rendern; base_dir bestimmt den relativen Template-Pfad.

    variant "druck" erzeugt das A4-Fließdokument, "slides" eine Fassung mit
    einer 16:9-Folie pro Seite.
    """
    if variant not in TEMPLATE_PATHS:
        raise ValueError(f"Unbekannte Variante: {variant}. Verfuegbar: {', '.join(TEMPLATE_PATHS)}")
    title_slide, content_slides = _title_slide(outline)
    title = _deck_title(outline, title_slide)
    subtitle = _deck_subtitle(title_slide)

    lines: list[str] = [
        "---",
        f"title: {_yaml_value(title)}",
    ]
    if subtitle:
        lines.append(f"subtitle: {_yaml_value(subtitle)}")
    lines.extend(["lang: de", "format:", "  typst:"])
    lines.append(_template_directive(base_dir, variant))
    if _needs_project_filter(outline):
        # Explizite Filterangabe sichert die Modellverarbeitung auch bei
        # eigenstaendigen Builds ohne Projekt-_quarto.yml.
        lines.extend(["filters:", _filter_directive(base_dir)])
    lines.extend(["---", ""])

    if title_slide is not None:
        for block in title_slide.blocks:
            if isinstance(block, TextBlock) and block.kind == "titel":
                continue
            if subtitle and isinstance(block, TextBlock) and block.kind == "absatz" and " ".join(block.lines) == subtitle:
                continue
            _render_block(block, lines)

    for slide in content_slides:
        lines.append(f"## {slide.title}")
        lines.append("")
        for block in slide.blocks:
            _render_block(block, lines)

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def generate_printable(
    outline_path: Path,
    *,
    output_path: Path | None = None,
    force: bool = False,
    variant: str = "druck",
) -> Path:
    """Aus einer Outline-Datei eine druckbare QMD erzeugen.

    Standardziel ist die Outline-Datei mit .qmd-Suffix; die Variante "slides"
    schreibt zusaetzlich "-slides" vor die Endung. Existiert das Ziel
    mit abweichendem Inhalt, wird ohne force ein PrintableExistsError
    geworfen; identischer Inhalt wird stillschweigend akzeptiert.
    """
    outline_path = Path(outline_path)
    if output_path is not None:
        output = Path(output_path)
    elif variant == "slides":
        output = outline_path.with_name(f"{outline_path.stem}-slides.qmd")
    else:
        output = outline_path.with_suffix(".qmd")
    outline = parse_outline(outline_path)
    if not outline.slides:
        raise ValueError(f"Outline ohne Folien: {outline_path}")
    text = render_printable_qmd(outline, base_dir=outline_path.parent, variant=variant)
    if output.exists() and output.read_text(encoding="utf-8") != text and not force:
        raise PrintableExistsError(output)
    if not output.exists() or output.read_text(encoding="utf-8") != text:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    return output
