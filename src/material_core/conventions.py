"""Mechanisch pruefbare Material-Konventionen aus AGENTS.md.

``check_conventions`` arbeitet nur auf Pfad und Quelltext; ``scan`` liest den
Bestand, geschrieben wird nie. Material-UI (Editor-Diagnose) und
``inv konventionen`` verwenden dieselben Regeln. Jede Regel ist bewusst eng gefasst: lieber ein Verstoss
unentdeckt als ein falscher Hinweis im Editor.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from material_core.metadata import split_frontmatter


@dataclass(frozen=True)
class Finding:
    code: str
    level: str  # "warning" (klarer Regelverstoss) oder "info" (bitte pruefen)
    title: str
    detail: str
    offset: int = 0
    length: int = 1


def _blank(value: str) -> str:
    return re.sub(r"[^\r\n]", " ", value)


def visible_text(text: str) -> str:
    """Blendet Frontmatter, Kommentare, Codebloecke und Inline-Code aus.

    Zeichenpositionen bleiben erhalten, damit Fundstellen auf den Quelltext zeigen.
    """
    parts = split_frontmatter(text)
    start = len(text) - len(parts.body) if parts else 0
    masked = _blank(text[:start]) + text[start:]
    masked = re.sub(r"<!--[\s\S]*?(?:-->|\Z)", lambda m: _blank(m[0]), masked)
    lines, fence = [], None
    for line in masked.splitlines(keepends=True):
        match = re.match(r" {0,3}(`{3,}|~{3,})(.*)", line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            lines.append(_blank(line))
        elif match:
            fence = match[1]
            lines.append(_blank(line))
        else:
            lines.append(line)
    return re.sub(r"(`+)[^`\n]*?\1", lambda m: _blank(m[0]), "".join(lines))


def _without_math(masked: str) -> str:
    masked = re.sub(r"(?<![\\$])\$\$[\s\S]*?\$\$", lambda m: _blank(m[0]), masked)
    return re.sub(r"(?<![\\$\w])\$(?!\s)[^$\n]*?(?<![\s\\])\$(?!\d)", lambda m: _blank(m[0]), masked)


# Teilaufgaben-Kennzeichen wie a), (b), 3), 2a) – auch mit Pandoc-Escape "a\)".
_LABEL = r"(?:\(?[a-z]{1,2}\\?\)|\d{1,2}[a-z]?\\?\)|\d{1,2}\.)"
_LABEL_ONLY = re.compile(rf"\s*(?:{_LABEL}|\d{{1,2}}[a-z]?)\s*\Z")
_LETTER_LABEL = r"\(?[a-z]{1,2}\\?\)"
_ZUSATZ_SPAN = re.compile(r"\[([^\]\n]+)\]\{[^}\n]*\.zusatz\b[^}\n]*\}")
# "**a) Titel**" – aber nicht "**a) und b)**" (mehrere Kennzeichen in einem Fettdruck).
_BOLD_LABEL_WITH_TEXT = re.compile(
    rf"(?<![*\w])\*\*({_LETTER_LABEL})[ \t]+(?!(?:und|bis|oder|–|-)[ \t]+{_LETTER_LABEL})[^*\n]*[^\W\d_]{{2}}[^*\n]*\*\*"
)
_HEADING = re.compile(r"(?m)^(#{1,6})[ \t]+(.*?)[ \t]*(?:\{[^}\n]*\})?[ \t]*$")
_HEADING_NUMBER_DOT = re.compile(r"(?:Aufgabe[ \t]+)?\d{1,2}[a-z]?\.(?=[ \t]+\S)")
_ORDINAL = re.compile(
    r"\d{1,2}\.[ \t]+(?:Halbjahr|Schuljahr|Quartal|Stunde|Doppelstunde|Woche|Tag|Teil|Schritt|Variante|Version|Phase|"
    r"Klasse|Jahrgang|Lernjahr|Semester|Runde|Fassung|Entwurf|Station|Ordnung|Grades|Normalform|"
    r"(?:binomische|Binomische)[ \t]+Formel|Strahlensatz|Ableitung|Weltkrieg|Jahrhundert|"
    r"Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|\d)"
)
# Differenzierungsliste: "Kern: a, c, e" oder "Zusatz: übrige".
_ITEM = r"(?:\d{0,2}[a-z]\\?\)?|\d{1,2}\\?\)?)"
_META_LIST = re.compile(
    rf"(?m)(?:^[ \t>*_|-]*|[·|;.][ \t]*)(?:\*\*|__)?(Kern|Zusatz|Pflicht|Wahl)(?:aufgaben?|teil)?(?:\*\*|__)?[ \t]*:(?:\*\*|__)?[ \t]*"
    rf"(?:(?:die[ \t]+)?(?:übrigen?|restlichen?|alle[ \t]+anderen)\b|{_ITEM}[ \t]*(?:,|und|bis|–|-)[ \t]*{_ITEM}(?![\w]))"
)
# Einzelnes Etikett am Zeilenanfang. "Basis" fehlt in beiden Mustern bewusst (Fachbegriff bei Potenzen).
_META_LINE = re.compile(
    r"(?m)^[ \t>*_-]*(?:\*\*|__)?(Kern|Zusatz|Pflicht|Wahl|Arbeitsweg|Differenzierung)(?:aufgaben?|teil)?(?:\*\*|__)?[ \t]*:"
)
_AFB_MENTION = re.compile(r"\bAFB[ \t]*(?:III|II|I|[1-3])\b|\bAnforderungsbereich(?:e|en)?\b")
_WORK_HINT = re.compile(
    r"\b(?:im|ins|in[ \t]+(?:dein|das|euer|Ihr|ihr)|in[ \t]+(?:deinem|eurem|dem))[ \t]+(?:Heft|Kopf)\b|"
    r"\bauf[ \t]+(?:dem|das|diesem|dieses|deinem|dein)[ \t]+(?:Blatt|Arbeitsblatt)\b"
)
_REFLECTION = re.compile(r"\b(?:Reflexions|Verständnis|Verstaendnis)fragen?\b")
_SUBTITLE = re.compile(r"(?m)^subtitle[ \t]*:[ \t]*(.*?)[ \t]*$")
_SLIDE_NAME = re.compile(r"(?:\d+[ _-])?slide\.qmd\Z")
_HINT_FILE = re.compile(r".+[-_]hinweise\.md\Z", re.IGNORECASE)


def is_slide_path(path: PurePosixPath) -> bool:
    return bool(_SLIDE_NAME.fullmatch(path.name))


def is_worksheet_path(path: PurePosixPath) -> bool:
    return path.name.startswith("ab_") and path.suffix == ".qmd"


def check_conventions(path: Path | str, text: str) -> list[Finding]:
    """Liefert Konventionshinweise fuer ein Dokument, sortiert nach Fundstelle."""
    name = PurePosixPath(Path(path).as_posix())
    findings: list[Finding] = []
    add = lambda *args, **kwargs: findings.append(Finding(*args, **kwargs))  # noqa: E731
    masked = visible_text(text)
    prose = _without_math(masked)
    slide, worksheet = is_slide_path(name), is_worksheet_path(name)
    solution = "loesung" in name.name.lower() or "lösung" in name.name.lower()

    parts = split_frontmatter(text)
    if parts:
        subtitle = _SUBTITLE.search(parts.header)
        value = subtitle[1].strip("\"'") if subtitle else ""
        if value and value not in {"null", "~", "|", ">"}:
            add("untertitel", "info", "Untertitel gesetzt",
                "Untertitel bleiben standardmäßig leer und werden nur auf ausdrücklichen Wunsch gesetzt.",
                len(parts.prefix) + subtitle.start(), len(subtitle[0]))

    for match in _HEADING.finditer(prose):
        title, start = match[2], match.start(2)
        for separator in re.finditer(r"[·•∙]", title):
            before, after = title[:separator.start()].rstrip()[-1:], title[separator.end():].lstrip()[:1]
            if (before.isdigit() or before == ")") and (after.isdigit() or after == "("):
                continue  # Malpunkt zwischen Zahlen oder Klammern, kein Trenner
            add("ueberschrift-trenner", "warning", "Punkt als Trenner in der Überschrift",
                "Überschriften verwenden keine Punkte oder Mittelpunkte als Trenner.", start + separator.start(), 1)
        number = _HEADING_NUMBER_DOT.match(title)
        if number and not _ORDINAL.match(title[re.search(r"\d", number[0]).start():]):
            add("ueberschrift-trenner", "warning", "Punkt nach der Aufgabennummer",
                "Aufgabennummer und Titel werden nur durch ein Leerzeichen getrennt.", start + number.end() - 1, 1)

    for match in _ZUSATZ_SPAN.finditer(masked):
        if not _LABEL_ONLY.match(match[1].strip("* ")):
            add("afb-kennzeichnung", "warning", "Rote Kennzeichnung umfasst mehr als das Aufgabenkennzeichen",
                "Nur Aufgabenbuchstabe oder Teilaufgabennummer kennzeichnen, z. B. [c)]{.zusatz}; "
                "Aufgabenstellung und Formeln bleiben in normaler Textfarbe.", match.start(), len(match[0]))

    if worksheet and not solution:
        for match in _BOLD_LABEL_WITH_TEXT.finditer(prose):
            add("afb-kennzeichnung", "warning", "Fettdruck umfasst mehr als das Aufgabenkennzeichen",
                "Nur den Aufgabenbuchstaben fett setzen, z. B. **a)**; die Aufgabenstellung bleibt normal.",
                match.start(), len(match[0]))
    if worksheet:
        listed = set()
        for match in _META_LIST.finditer(prose):
            listed.add(match.start(1))
            add("metahinweis", "warning", "Differenzierungsliste im Schülertext",
                f"Listen wie „{match[1]}: a, c, e“ gehören nicht auf das Arbeitsblatt; die Staffelung zeigt die Kennzeichnung der Aufgaben.",
                match.start(1), len(match[0]))
        for match in _META_LINE.finditer(prose):
            if match.start(1) in listed:
                continue
            explicit = match[1] in {"Arbeitsweg", "Differenzierung"}
            add("metahinweis", "warning" if explicit else "info", f"Etikett „{match[1]}:“ im Schülertext",
                "Metahinweise und Differenzierungsetiketten gehören nicht auf das Arbeitsblatt. Bitte prüfen, ob eine Aufgabenkennzeichnung genügt.",
                match.start(1), len(match[1]))
        for match in _AFB_MENTION.finditer(prose):
            add("metahinweis", "warning", "Anforderungsbereich im Schülertext genannt",
                "AFB-Angaben und Legenden stehen nicht auf dem Arbeitsblatt.", match.start(), len(match[0]))
    if worksheet or slide:
        for match in _WORK_HINT.finditer(prose):
            add("bearbeitungshinweis", "info", "Bearbeitungshinweis zum Rechenort",
                "Angaben wie „im Heft“, „im Kopf“ oder „auf dem Blatt“ entfallen, sofern sie nicht ausdrücklich gewünscht sind.",
                match.start(), len(match[0]))
    if slide:
        for match in _REFLECTION.finditer(masked):
            add("reflexionsfrage-sichtbar", "warning", "Reflexionsfrage als sichtbarer Folieninhalt",
                "Reflexions- und Verständnisfragen stehen nur als HTML-Kommentar im Quelltext: <!-- Reflexionsfrage: … -->.",
                match.start(), len(match[0]))
        if "praesentation" in name.parts[:-1]:
            add("dateiname", "warning", "Deck liegt in einem Unterordner praesentation/",
                "Präsentations-Decks heißen slide.qmd und liegen direkt im Materialordner.")
    return sorted(findings, key=lambda finding: (finding.offset, finding.code))


def check_file_name(path: Path | str) -> list[Finding]:
    """Regeln, die allein am Pfad haengen (fuer die Bestandspruefung)."""
    name = PurePosixPath(Path(path).as_posix())
    if _HINT_FILE.fullmatch(name.name):
        return [Finding("hinweisdatei", "warning", "Zusätzliche Hinweisdatei",
                        "Pro Materialordner gibt es höchstens eine hinweise.md; themenbezogene Hinweise als Abschnitte dort ergänzen.")]
    if name.suffix == ".typ":
        return [Finding("typ-artefakt", "warning", "Typst-Artefakt im Materialbestand",
                        ".typ ist ein Build-Artefakt unter build/artefakte/; Layoutvorlagen tragen die Endung .typst.")]
    return []


def position(text: str, offset: int) -> tuple[int, int]:
    """1-basierte Zeile und Spalte einer Zeichenposition."""
    return text.count("\n", 0, offset) + 1, offset - text.rfind("\n", 0, offset)


# Altbestand, Kursinhalte (eigenes Format) und Build-Ausgaben werden nicht geprueft.
SKIP_DIRS = frozenset({"alt", "build", "kurse", "node_modules"})


def scan(root: Path) -> list[tuple[Path, int, Finding]]:
    """Prueft alle QMD-Quellen und Dateinamen unter ``root``: (Pfad, Zeile, Befund)."""
    root = Path(root)
    if root.is_file():
        text = root.read_text(encoding="utf-8", errors="replace")
        return [(root, position(text, finding.offset)[0], finding) for finding in check_conventions(root, text)]
    results: list[tuple[Path, int, Finding]] = []
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = sorted(name for name in subdirectories if not name.startswith(".") and name not in SKIP_DIRS)
        for filename in sorted(filenames):
            path = Path(directory) / filename
            results.extend((path, 0, finding) for finding in check_file_name(path))
            if path.suffix != ".qmd":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            results.extend((path, position(text, finding.offset)[0], finding) for finding in check_conventions(path, text))
    return results
