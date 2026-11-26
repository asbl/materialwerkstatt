"""Markdown-Outline-Parser fuer Excalidraw-Decks.

Eine Outline ist eine schlanke Markdown-Datei, aus der `inv deck` ein
Excalidraw-Deck generiert (One-Shot-Scaffold; danach ist die .excalidraw-Datei
die Quelle der Wahrheit und wird nicht mehr ueberschrieben).

Format:

- YAML-Frontmatter optional, `title:` setzt den Deck-Titel; `subtitle:`
  setzt bei Frontmatter-Titeln den Untertitel als Absatz auf die Titelfolie
  (so kann eine druckbare QMD gleichzeitig als Outline dienen)
- `font-ueberschriften:` / `font-text:` setzen die Schriften (Standard:
  Excalifont fuer Titel und Abschnitte, Normal (Helvetica-artig) fuer Text)
- `deck-design:` waehlt ein Design aus dem gemeinsamen Vorlagenkatalog
- `# Titel` setzt den Deck-Titel und erzeugt die Titelfolie; besteht die
  Folie nur aus dieser h1-Ueberschrift, wird sie als Titelfolienblatt mit
  zentrierter Ueberschrift gezeichnet (mit Design zentriert in der
  Inhaltsflaeche des Design-Hintergrunds)
- `## Folie` beginnt eine Folie (Frame); der Folientitel steht beim
  Deck-Generieren zusaetzlich als Ueberschrift oben in der Folie
- `### Abschnitt` wird zu einer Zwischenueberschrift in der Folie
- `- Punkt` / `* Punkt` werden zu einem Bullet-Textblock; eingerueckte
  Folgezeilen setzen einen laengeren Bullet fort (Zeilenumbruch auf der Folie)
- `![alt](pfad.svg)` bettet ein Bild ein, Pfad relativ zur Outline-Datei
- `[Modell …]` / `[Skizze …]` / `[Einheitskreis …]` / `[Koordinatensystem …]`
  sind Kuerzel wie im Unterrichtsmaterial; das Deck zeichnet sie beim Generieren
  automatisch als SVG, die druckbare QMD gibt das Kuerzel unverändert an den
  Projektfilter weiter
- `[Infobox: Titel]` … `[/Infobox]` (ebenso Warnbox/Tippbox) rahmt den Inhalt
  wie im Unterrichtsmaterial als Kasten ein; das Deck zeichnet ihn als
  farbigen Rahmen mit Titelzeile, die druckbare QMD gibt die Marker weiter
- `[Rot …]` hebt den Text wie im Unterrichtsmaterial rot hervor
- `$…$` und `$$…$$` setzen Inline- und abgesetzte LaTeX-Formeln
- `::: aufgabe` / `:::` Div-Rahmen werden ignoriert, der Inhalt zaehlt als Absatz
- `::: {.columns}` mit `::: {.column width="52%"}`-Abschnitten legt Inhalte
  nebeneinander (wie im Projektfilter); Breiten in Prozent, Spalten ohne
  Breite teilen sich den Rest
- andere Textzeilen werden zu Absatz-Bloecken
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from material_core.designs import design_by_id

_IMAGE_PATTERN = re.compile(r"^!\[[^\]]*\]\(([^)]+)\)\s*(?:\{([^\n{}]*)\})?\s*$")
# Kuerzel, die der Projektfilter (exam.lua) in eine Bild-SVG umsetzt; die
# druckbare QMD reicht sie unveraendert an den Filter weiter.
_MARKER_PATTERN = re.compile(r"^\[(?:Modell|Skizze|Einheitskreis|Koordinatensystem)\s[^\n]*\]\s*$")
_ROT_PATTERN = re.compile(r"^\[Rot\s+([^\n]*)\]\s*$")
# Box-Marker wie im Projektfilter (exam.lua): Titel optional, ohne Titel
# greift der Kasten-Default-Titel.
_BOX_OPEN_PATTERN = re.compile(r"^\[(Infobox|Warnbox|Tippbox)(?::\s*(.*?))?\]$")
_BOX_CLOSE_PATTERN = re.compile(r"^\[/(Infobox|Warnbox|Tippbox)\]$")
BOX_KINDS = {"Infobox": "infobox", "Warnbox": "warnbox", "Tippbox": "tippbox"}
BOX_DEFAULT_TITLES = {"infobox": "Info", "warnbox": "Warnung", "tippbox": "Tipp"}
_BULLET_PATTERN = re.compile(r"^[-*]\s+(.*)$")
_FRONTMATTER_DELIMITER = "---"
# Pandoc-Fenced-Divs wie im Projektfilter (exam.lua): `::: {.columns}` oeffnet
# ein Spalten-Layout, `::: {.column width="52%"}` eine einzelne Spalte.
_DIV_OPEN_PATTERN = re.compile(r"^::+\s*(.*)$")
_DIV_ATTRS_PATTERN = re.compile(r"^\{(.*)\}$")
_DIV_WIDTH_PATTERN = re.compile(r"\b(?:width|breite)\s*=\s*\"?([0-9]+(?:\.[0-9]+)?)\s*%?\"?")

# Kanonische Schriftnamen wie von Excaligen akzeptiert; die IDs im
# Excalidraw-JSON vergibt Excaligen (Excalifont=5, Normal=2, ...).
DEFAULT_HEADING_FONT = "Excalifont"
DEFAULT_TEXT_FONT = "Normal"
FONT_ALIASES = {
    "excalifont": "Excalifont",
    "comic-shaans": "Comic Shaans",
    "lilita-one": "Lilita One",
    "nunito": "Nunito",
    "hand-drawn": "Hand-drawn",
    "normal": "Normal",
    "code": "Code",
}
HEADING_KINDS = frozenset({"titel", "abschnitt"})
# Schriftgroessen in px auf der 1600x900-Folie. Text frueher 24/28 px; nach
# Rueckmeldung aus der letzten Reihe (aus der Ferne schwer lesbar) erhoeht.
# Der Decktitel bleibt bei 64 px: groessere Titel sprengen die Folienbreite.
DECK_TITLE_FONTSIZE = 64
SECTION_FONTSIZE = 44
TEXT_FONTSIZE = 36


def _normalize_font(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Frontmatter '{key}': Schrift als Text angeben, z. B. 'Excalifont'.")
    normalized = value.strip().lower().replace(" ", "-").replace("_", "-")
    if normalized not in FONT_ALIASES:
        raise ValueError(
            f"Frontmatter '{key}': unbekannte Schrift '{value}'. "
            f"Verfuegbar: {', '.join(sorted(set(FONT_ALIASES.values())))}."
        )
    return FONT_ALIASES[normalized]


@dataclass(frozen=True)
class TextBlock:
    """Zusammengehoerige Textzeilen mit Ziel-Schriftgroesse."""

    lines: tuple[str, ...]
    fontsize: int
    kind: str  # "titel" | "untertitel" | "abschnitt" | "absatz" | "bullets" | "rot"


@dataclass(frozen=True)
class ImageBlock:
    """Eingebettetes Bild, Pfad relativ zur Outline-Datei."""

    path: Path
    width: float | None = None


@dataclass(frozen=True)
class ModelBlock:
    """Kuerzel wie `[Modell rechenstrich | knoten=… | spruenge=…]` oder
    `[Skizze dreieck | form=recht-C]`, das der Projektfilter als SVG zeichnet."""

    marker: str


@dataclass(frozen=True)
class SpacerBlock:
    """Vertikaler Abstand in Millimetern."""

    height_mm: float


@dataclass(frozen=True)
class AnswerBlock:
    """Freie Rechenfläche; Höhe in Millimetern wie in der PDF-Fassung."""

    height_mm: float = 10.0


@dataclass(frozen=True)
class BoxBlock:
    """Inhaltskasten aus `[Infobox: Titel]` … `[/Infobox]` (ebenso Warnbox/
    Tippbox) mit geparsten Innenbloecken; kind ist "infobox" | "warnbox" |
    "tippbox", title der Marker-Titel oder der Kasten-Default."""

    kind: str
    title: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class ColumnBlock:
    """Eine Spalte eines Spalten-Layouts; width ist die Breite in Prozent
    (0..100) oder None fuer einen fairen Anteil am Rest."""

    blocks: tuple[Block, ...]
    width: float | None = None


@dataclass(frozen=True)
class ColumnsBlock:
    """Spalten-Layout aus `::: {.columns}` mit mindestens zwei
    `::: {.column}`-Spalten; die druckbare QMD gibt die Divs an den
    Projektfilter weiter, das Deck legt die Spalten nebeneinander."""

    columns: tuple[ColumnBlock, ...]


Block = SpacerBlock | TextBlock | ImageBlock | ModelBlock | AnswerBlock | BoxBlock | ColumnsBlock


@dataclass(frozen=True)
class Slide:
    """Eine Folie des Decks; wird im Deck zu einem Excalidraw-Frame."""

    title: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class DeckOutline:
    """Vollstaendige geparste Outline."""

    title: str | None
    slides: tuple[Slide, ...]
    heading_font: str = DEFAULT_HEADING_FONT
    text_font: str = DEFAULT_TEXT_FONT
    design_id: str | None = None
    design: dict | None = None


def _split_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        return {}, text
    for index in range(1, len(lines)):
        if lines[index].strip() == _FRONTMATTER_DELIMITER:
            metadata = yaml.safe_load("\n".join(lines[1:index])) or {}
            if not isinstance(metadata, dict):
                metadata = {}
            return metadata, "\n".join(lines[index + 1 :])
    return {}, text


class _Parser:
    def __init__(self, body: str) -> None:
        # Standalone-HTML-Kommentare sind Lehrkraftnotizen, keine Folieninhalte.
        self._body = re.sub(r"(?ms)^[ \t]*<!--.*?-->[ \t]*(?:\n|$)", "\n", body)
        self._slides: list[Slide] = []
        self._current_title: str | None = None
        self._blocks: list[Block] = []
        self._bullets: list[str] = []
        self._paragraph: list[str] = []
        self._box_kind: str | None = None
        self._box_title: str | None = None
        self._box_blocks: list[Block] = []
        self._columns: list[ColumnBlock] | None = None
        self._column_width: float | None = None
        self._column_blocks: list[Block] | None = None

    def _sink(self) -> list[Block]:
        """Aktuelle Blockliste: innerhalb eines Kastens die Kasten-Inhalte,
        innerhalb einer Spalte die Spalten-Inhalte, sonst die Bloecke der
        aktuellen Folie."""
        if self._box_kind:
            return self._box_blocks
        if self._column_blocks is not None:
            return self._column_blocks
        return self._blocks

    def parse(self) -> tuple[str | None, tuple[Slide, ...]]:
        math_end: str | None = None
        for raw_line in self._body.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if math_end is not None:
                self._paragraph.append(stripped)
                if re.search(r"(?<!\\)" + re.escape(math_end), stripped):
                    math_end = None
                    self._flush()
                continue
            delimiter = next((value for value in ("$$", r"\[") if stripped.startswith(value)), None)
            if delimiter is not None:
                self._flush()
                self._paragraph.append(stripped)
                closing = "$$" if delimiter == "$$" else r"\]"
                if not re.search(r"(?<!\\)" + re.escape(closing), stripped[len(delimiter):]):
                    math_end = closing
                else:
                    self._flush()
                continue
            if stripped.startswith("### "):
                self._flush()
                self._sink().append(TextBlock((stripped[4:].strip(),), SECTION_FONTSIZE, "abschnitt"))
            elif stripped.startswith("## "):
                if self._box_kind:
                    raise ValueError(f"Nicht abgeschlossener Kasten: Abschluss [/{self._box_kind.capitalize()}] fehlt.")
                if self._column_blocks is not None or self._columns is not None:
                    raise ValueError("Nicht abgeschlossene Spalten: Abschluss ::: fehlt vor der neuen Folie.")
                self._flush()
                self._finish_slide()
                self._current_title = stripped[3:].strip()
            elif stripped.startswith("# "):
                if self._box_kind:
                    raise ValueError(f"Nicht abgeschlossener Kasten: Abschluss [/{self._box_kind.capitalize()}] fehlt.")
                if self._column_blocks is not None or self._columns is not None:
                    raise ValueError("Nicht abgeschlossene Spalten: Abschluss ::: fehlt vor der neuen Folie.")
                self._flush()
                self._finish_slide()
                self._current_title = "Titel"
                self._blocks.append(TextBlock((stripped[2:].strip(),), DECK_TITLE_FONTSIZE, "titel"))
            elif not stripped:
                self._flush()
            elif stripped.startswith(":::"):
                self._handle_div(stripped)
            else:
                box_close = _BOX_CLOSE_PATTERN.match(stripped)
                if box_close:
                    kind = BOX_KINDS[box_close.group(1)]
                    if self._box_kind != kind:
                        raise ValueError(
                            f"[/{box_close.group(1)}] ohne passenden Anfang"
                            if self._box_kind is None
                            else f"[/{box_close.group(1)}] schliesst [{self._box_kind.capitalize()}] nicht."
                        )
                    self._flush()
                    target = self._column_blocks if self._column_blocks is not None else self._blocks
                    target.append(BoxBlock(kind, self._box_title or BOX_DEFAULT_TITLES[kind], tuple(self._box_blocks)))
                    self._box_kind = None
                    self._box_title = None
                    self._box_blocks = []
                    continue
                box_open = _BOX_OPEN_PATTERN.match(stripped)
                if box_open:
                    if self._box_kind:
                        raise ValueError("Kästen in Kästen werden nicht unterstützt.")
                    self._flush()
                    self._box_kind = BOX_KINDS[box_open.group(1)]
                    self._box_title = (box_open.group(2) or "").strip() or None
                    continue
                answer = re.fullmatch(r"\[Antwortkasten(?::\s*([0-9]+(?:[.,][0-9]+)?)\s*(cm|mm|pt))?\]", stripped)
                if not answer and stripped.startswith("[Antwortkasten"):
                    raise ValueError("Antwortkasten: Höhe als positive Zahl mit cm, mm oder pt angeben.")
                if answer:
                    self._flush()
                    amount = float(answer.group(1).replace(",", ".")) if answer.group(1) else 1.0
                    unit = answer.group(2) or "cm"
                    height = amount * {"cm": 10, "mm": 1, "pt": 25.4 / 72}[unit]
                    if height <= 0:
                        raise ValueError("Antwortkasten: Höhe muss positiv sein.")
                    self._sink().append(AnswerBlock(height))
                    continue
                spacer = re.fullmatch(r"\[abstand\s+([0-9]+(?:[.,][0-9]+)?)\s*(cm|mm|pt)\]", stripped, re.IGNORECASE)
                if spacer:
                    self._flush()
                    height = float(spacer.group(1).replace(",", ".")) * {"cm": 10, "mm": 1, "pt": 25.4 / 72}[spacer.group(2).lower()]
                    self._sink().append(SpacerBlock(height))
                    continue
                image_match = _IMAGE_PATTERN.match(stripped)
                if image_match:
                    self._flush()
                    attributes = image_match.group(2) or ""
                    width_match = re.search(r'\bwidth\s*=\s*["\']?([0-9]+(?:\.[0-9]+)?)%', attributes)
                    image_width = float(width_match.group(1)) if width_match else None
                    if image_width is not None and not 0 < image_width <= 100:
                        raise ValueError("Bildbreite muss zwischen 0 und 100 Prozent liegen.")
                    self._sink().append(ImageBlock(Path(image_match.group(1)), image_width))
                    continue
                if _MARKER_PATTERN.match(stripped):
                    self._flush()
                    self._sink().append(ModelBlock(stripped))
                    continue
                rot_match = _ROT_PATTERN.match(stripped)
                if rot_match:
                    self._flush()
                    self._sink().append(TextBlock((rot_match.group(1).strip(),), TEXT_FONTSIZE, "rot"))
                    continue
                bullet_match = _BULLET_PATTERN.match(stripped)
                if bullet_match:
                    if self._paragraph:
                        self._flush()
                    self._bullets.append(f"- {bullet_match.group(1).strip()}")
                elif self._bullets and line[:1] in (" ", "\t"):
                    # Eingerueckte Fortsetzungszeile gehoert zum letzten Bullet:
                    # Laengere Antworten lassen sich sonst nicht umbrechen, ohne
                    # im Deck in einen eigenen Absatzblock zu fallen.
                    self._bullets.append(f"  {stripped}")
                else:
                    if self._bullets:
                        self._flush()
                    self._paragraph.append(stripped)
        if math_end is not None:
            raise ValueError(f"Nicht abgeschlossene Formel: Abschluss {math_end} fehlt.")
        if self._box_kind is not None:
            raise ValueError(f"Nicht abgeschlossener Kasten: Abschluss [/{self._box_kind.capitalize()}] fehlt.")
        if self._column_blocks is not None or self._columns is not None:
            raise ValueError("Nicht abgeschlossene Spalten: Abschluss ::: fehlt.")
        self._flush()
        self._finish_slide()
        return self._deck_title, tuple(self._slides)

    def _handle_div(self, stripped: str) -> None:
        """Fenced-Div verarbeiten: Spalten-Layouts erkennen, alle anderen
        Div-Rahmen ignorieren (Inhalt zaehlt wie bisher als Absatz)."""
        rest = _DIV_OPEN_PATTERN.match(stripped).group(1).strip()
        if not rest:
            self._close_div()
            return
        attrs = _DIV_ATTRS_PATTERN.match(rest)
        if attrs:
            classes = {
                token[1:].lower()
                for token in attrs.group(1).split()
                if token.startswith(".") and len(token) > 1
            }
            width_match = _DIV_WIDTH_PATTERN.search(attrs.group(1))
            width = float(width_match.group(1)) if width_match else None
        else:
            classes = {rest.lower()}
            width = None
        if "columns" in classes or "spalten" in classes:
            if self._columns is not None or self._column_blocks is not None:
                raise ValueError("Spalten in Spalten werden nicht unterstuetzt.")
            self._flush()
            self._columns = []
        elif ("column" in classes or "spalte" in classes) and self._columns is not None:
            if self._column_blocks is not None:
                raise ValueError("Spalte in Spalte wird nicht unterstuetzt.")
            self._flush()
            self._column_width = width
            self._column_blocks = []
        else:
            self._flush()

    def _close_div(self) -> None:
        if self._column_blocks is not None:
            self._flush()
            self._columns.append(ColumnBlock(tuple(self._column_blocks), self._column_width))
            self._column_blocks = None
            self._column_width = None
        elif self._columns is not None:
            self._flush()
            columns = tuple(self._columns)
            self._columns = None
            if len(columns) < 2:
                raise ValueError("Spalten brauchen mindestens zwei ::: {.column}-Abschnitte.")
            self._blocks.append(ColumnsBlock(columns))
        else:
            self._flush()

    @property
    def _deck_title(self) -> str | None:
        for slide in self._slides:
            for block in slide.blocks:
                if isinstance(block, TextBlock) and block.kind == "titel":
                    return block.lines[0]
        return None

    def _flush(self) -> None:
        if self._bullets:
            self._sink().append(TextBlock(tuple(self._bullets), TEXT_FONTSIZE, "bullets"))
            self._bullets = []
        if self._paragraph:
            self._sink().append(TextBlock(tuple(self._paragraph), TEXT_FONTSIZE, "absatz"))
            self._paragraph = []

    def _finish_slide(self) -> None:
        if self._current_title is None and not self._blocks:
            return
        title = self._current_title or "Folie"
        self._slides.append(Slide(title, tuple(self._blocks)))
        self._blocks = []
        self._current_title = None


def parse_outline(path: Path) -> DeckOutline:
    """Outline-Datei lesen und in ein DeckOutline-Modell ueberfuehren."""
    text = path.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(text)
    title, slides = _Parser(body).parse()
    frontmatter_title = metadata.get("title")
    if frontmatter_title and not title:
        blocks: tuple[Block, ...] = (TextBlock((str(frontmatter_title),), DECK_TITLE_FONTSIZE, "titel"),)
        frontmatter_subtitle = metadata.get("subtitle")
        if frontmatter_subtitle:
            blocks = (*blocks, TextBlock((str(frontmatter_subtitle),), TEXT_FONTSIZE, "absatz"))
        title_slide = Slide("Titel", blocks)
        slides = (title_slide, *slides)
        title = str(frontmatter_title)
    from material_core.designs import resolved_slide_design
    design = resolved_slide_design(text, path)
    design_font = (
        design["heading_font"] if design and design.get("heading_font")
        else design["deck_heading_font"] if design and design.get("deck_heading_font")
        else DEFAULT_HEADING_FONT
    )
    heading_font = (
        _normalize_font(metadata["font-ueberschriften"], "font-ueberschriften")
        if "font-ueberschriften" in metadata
        else design_font
    )
    text_font = (
        _normalize_font(metadata["font-text"], "font-text")
        if "font-text" in metadata
        else design.get("text_font", DEFAULT_TEXT_FONT) if design else DEFAULT_TEXT_FONT
    )
    return DeckOutline(title, slides, heading_font, text_font, design["id"] if design else None, design)
