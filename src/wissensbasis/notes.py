from __future__ import annotations

from material_core.filesystem import atomic_write_text

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .config import Fach
from .extract import load_pages
from .scan import load_manifest
from .text import match_form

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
TAG_FIELDS = {
    "themen": "themen", "kompetenzen": "kompetenzen", "prinzipien": "prinzipien",
    "typ": "typen", "belegart": "belegarten", "materialtypen": "materialtypen",
}
CARD_REQUIRED = ["titel", "status", "kern", "quelle", "seite", "typ", "themen", "belegart", "klassenstufen", "zitat"]
AUFGABE_REQUIRED = ["titel", "status", "typ", "materialtypen", "themen", "klassenstufen"]
SOURCE_SECTIONS = ["Aussage", "Beispiel"]
DERIVED_SECTIONS = ["Planung", "Prüffrage"]
AUFGABE_SECTIONS_REQUIRED = ["Aufgabe", "Ziel"]
AUFGABE_SECTIONS_ALL = ["Aufgabe", "Ziel", "Einsatz", "Variationen", "Hinweise"]
MIN_CARD_WORDS = 90
MAX_KERN_CHARS = 300
DOSSIER_REQUIRED = ["titel", "status", "quelle", "hash", "themen", "zitierweise"]
WEB_DOSSIER_REQUIRED = ["url", "abgerufen"]  # Webquellen: die Datei ist nur die Lesekopie, die Adresse gehört dazu
ZURUECKGESTELLT = "_zurueckgestellt"  # karten/_zurueckgestellt/: bei der Aufnahme abgelehnt, nicht geprüft und nicht in den Seiten
STATUS_VALUES = {"entwurf", "freigegeben"}  # freigegeben = check ohne Fehler (wird automatisch gesetzt, s. release_clean)
ABDECKUNG_VALUES = {"teilweise", "vollstaendig", "keine", "strukturell"}
LITERATURE_MENTION = re.compile(
    r"\b([A-ZÄÖÜ][a-zäöüß\-]+)(?: u\. ?a\.| & [A-ZÄÖÜ][a-zäöüß\-]+)?,? \(?(?:19|20)\d{2}[a-z]?(?:, S\. [\d ff\.–-]+)?\)?"
)


@dataclass
class Note:
    art: str
    ref: str
    dok: str
    titel: str
    body: str
    meta: dict = field(default_factory=dict)
    path: Path | None = None


def read_note(path: Path) -> tuple[dict, str]:
    match = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError("Frontmatter fehlt")
    try:
        return yaml.safe_load(match.group(1)) or {}, match.group(2).strip()
    except yaml.YAMLError as error:
        hint = "Text mit Doppelpunkt (z. B. Literaturangaben „(2006): Titel“) in Anführungszeichen setzen"
        raise ValueError(f"Frontmatter nicht lesbar ({str(error).splitlines()[0]}); {hint}") from error


def sections(body: str) -> dict[str, str]:
    """Split a card body at '## Heading' lines. Text before the first heading is ignored."""
    result: dict[str, str] = {}
    current = None
    for line in body.splitlines():
        heading = re.match(r"##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1)
            result[current] = ""
        elif current:
            result[current] += line + "\n"
    return {name: text.strip() for name, text in result.items()}


def as_list(value) -> list:
    if value is None or value == "":
        return []
    return [value] if isinstance(value, (str, int)) else list(value)


def load_notes(fach: Fach, problems: list[str] | None = None) -> list[Note]:
    """All dossiers and cards. Unreadable files are skipped; pass a list to learn about them."""
    notes: list[Note] = []
    for art, directory in (("dossier", fach.dossiers), ("karte", fach.karten)):
        for path in sorted(directory.rglob("*.md")) if directory.exists() else []:
            if art == "karte" and path.relative_to(directory).parts[0] == ZURUECKGESTELLT:
                continue
            try:
                meta, body = read_note(path)
            except ValueError as error:
                if problems is not None:
                    problems.append(f"{path.relative_to(fach.wissen).as_posix()}: {error}")
                continue
            notes.append(
                Note(art, path.relative_to(fach.wissen).with_suffix("").as_posix(), str(meta.get("quelle", "")),
                     str(meta.get("titel", path.stem)), body, meta, path)
            )
    return notes


def load_templates(fach: Fach, problems: list[str] | None = None) -> list[Note]:
    """Reusable production templates; searchable, but not validated like evidence cards."""
    notes: list[Note] = []
    directory = fach.vorlagen
    for path in sorted(directory.rglob("*.md")) if directory.exists() else []:
        try:
            meta, body = read_note(path)
        except ValueError as error:
            if problems is not None:
                problems.append(f"{path.relative_to(fach.wissen).as_posix()}: {error}")
            continue
        if meta.get("art") != "vorlage":
            continue
        notes.append(
            Note("vorlage", path.relative_to(fach.wissen).with_suffix("").as_posix(), str(meta.get("quelle", "")),
                 str(meta.get("titel", path.stem)), body, meta, path)
        )
    return notes


def load_taxonomy(fach: Fach) -> dict:
    if not fach.taxonomie.exists():
        return {}
    return yaml.safe_load(fach.taxonomie.read_text(encoding="utf-8")) or {}


def parse_pages(value) -> tuple[int, int]:
    """'12' -> (12, 12), '12-14' -> (12, 14)."""
    match = re.fullmatch(r"\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*", str(value))
    if not match:
        raise ValueError(f"Seitenangabe nicht lesbar: {value!r}")
    start = int(match.group(1))
    return start, int(match.group(2) or start)


def check(fach: Fach) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for all dossiers and cards of one subject."""
    errors: list[str] = []
    warnings: list[str] = []
    manifest = load_manifest(fach)
    docs = {doc["id"]: doc for doc in manifest["dokumente"]}
    taxonomy = load_taxonomy(fach)
    if not taxonomy:
        return [f"{fach.taxonomie} fehlt oder ist leer"], []
    page_cache: dict[str, list[str]] = {}

    def pages_of(doc: dict) -> list[str]:
        if doc["id"] not in page_cache:
            page_cache[doc["id"]] = [page["t"] for page in load_pages(doc["sha256"])]
        return page_cache[doc["id"]]

    notes = load_notes(fach, errors)
    authors_of = {
        note.dok: {str(author).split()[-1].lower() for author in as_list(note.meta.get("autoren"))}
        for note in notes if note.art == "dossier"
    }
    for note in notes:
        name = note.path.relative_to(fach.wissen).as_posix()

        # Skip index/meta files inside karten subdirectories (e.g. karten/aufgaben/README.md)
        if note.meta.get("art") == "aufgaben-index":
            continue

        is_aufgabe = note.art == "karte" and note.meta.get("typ") == "aufgabe"
        required = DOSSIER_REQUIRED if note.art == "dossier" else (AUFGABE_REQUIRED if is_aufgabe else CARD_REQUIRED)
        for key in required:
            if not note.meta.get(key):
                errors.append(f"{name}: Feld '{key}' fehlt")
        if note.meta.get("status") and note.meta["status"] not in STATUS_VALUES:
            errors.append(f"{name}: status '{note.meta['status']}' unbekannt (erlaubt: {', '.join(sorted(STATUS_VALUES))})")
        for key, group in TAG_FIELDS.items():
            for value in as_list(note.meta.get(key)):
                if value not in (taxonomy.get(group) or {}):
                    errors.append(f"{name}: '{value}' steht nicht in taxonomie.yaml ({group})")

        if is_aufgabe:
            for entry in as_list(note.meta.get("quellen")):
                if not isinstance(entry, dict):
                    errors.append(f"{name}: quellen-Eintrag muss ein Dict sein (quelle:, seite:)")
                    continue
                quelle_id = str(entry.get("quelle", ""))
                if not quelle_id:
                    errors.append(f"{name}: quellen-Eintrag ohne 'quelle:'")
                    continue
                doc = docs.get(quelle_id)
                if doc is None:
                    errors.append(f"{name}: Quelle '{quelle_id}' in quellen nicht im Manifest")
                    continue
                if entry.get("seite"):
                    try:
                        start, end = parse_pages(entry["seite"])
                    except ValueError as error:
                        errors.append(f"{name}: {error}")
                        continue
                    pages = pages_of(doc)
                    if not 1 <= start <= end <= len(pages):
                        errors.append(f"{name}: Seite {entry['seite']} bei '{quelle_id}' außerhalb 1–{len(pages)}")
            parts_of_card = sections(note.body)
            for req in AUFGABE_SECTIONS_REQUIRED:
                if req not in parts_of_card:
                    errors.append(f"{name}: Abschnitt '## {req}' fehlt")
            for section in parts_of_card:
                if section not in AUFGABE_SECTIONS_ALL:
                    errors.append(f"{name}: unbekannter Abschnitt '## {section}' (erlaubt: {', '.join(AUFGABE_SECTIONS_ALL)})")
            continue

        doc = docs.get(note.dok)
        if doc is None:
            errors.append(f"{name}: Quelle '{note.dok}' nicht im Manifest")
            continue
        if note.art == "dossier":
            if doc.get("quellenart") == "web":
                for key in WEB_DOSSIER_REQUIRED:
                    if not note.meta.get(key):
                        errors.append(f"{name}: Feld '{key}' fehlt (bei Webquellen Pflicht: Adresse und Abrufdatum)")
            if note.meta.get("hash") != doc["sha256"]:
                warnings.append(f"{name}: Quelle wurde geändert, Dossier ist veraltet")
            abdeckung = note.meta.get("abdeckung")
            if abdeckung and abdeckung not in ABDECKUNG_VALUES:
                errors.append(f"{name}: abdeckung '{abdeckung}' unbekannt (erlaubt: {', '.join(sorted(ABDECKUNG_VALUES))})")
            continue
        if note.meta.get("quelle_hash") and note.meta["quelle_hash"] != doc["sha256"]:
            warnings.append(f"{name}: Quelle wurde geändert, Karte prüfen")
        if not note.meta.get("seite"):
            continue
        try:
            start, end = parse_pages(note.meta["seite"])
        except ValueError as error:
            errors.append(f"{name}: {error}")
            continue
        pages = pages_of(doc)
        if not 1 <= start <= end <= len(pages):
            errors.append(f"{name}: Seite {note.meta['seite']} außerhalb 1–{len(pages)}")
            continue
        haystack = match_form(" ".join(pages[start - 1:end]))
        for quote in as_list(note.meta.get("zitat")):
            parts = [part for part in re.split(r"\[?(?:…|\.\.\.)\]?", str(quote)) if match_form(part)]
            if not all(match_form(part) in haystack for part in parts):
                errors.append(f"{name}: Zitat steht nicht auf Seite {note.meta['seite']}: {str(quote)[:60]}…")
        parts_of_card = sections(note.body)
        if "Aussage" not in parts_of_card:
            errors.append(f"{name}: Abschnitt '## Aussage' fehlt")
        if not any(section in parts_of_card for section in DERIVED_SECTIONS):
            errors.append(f"{name}: mindestens '## Planung' oder '## Prüffrage' erforderlich")
        for section in parts_of_card:
            if section not in SOURCE_SECTIONS + DERIVED_SECTIONS:
                errors.append(f"{name}: unbekannter Abschnitt '## {section}'")
        own = authors_of.get(note.dok, set())
        mentioned = sorted({m.group(0).strip() for m in LITERATURE_MENTION.finditer(note.body) if m.group(1).lower() not in own})
        if mentioned and not as_list(note.meta.get("nach")):
            warnings.append(f"{name}: nennt Literatur im Text ({', '.join(mentioned[:3])}), aber 'nach:' ist leer")
        if len(str(note.meta.get("kern", ""))) > MAX_KERN_CHARS:
            warnings.append(f"{name}: 'kern' länger als {MAX_KERN_CHARS} Zeichen, bitte auf einen Satz kürzen")
        words = len(note.body.split())
        if words < MIN_CARD_WORDS:
            warnings.append(f"{name}: nur {words} Wörter, Karte vermutlich zu dünn")

    from .vorlagen import check as check_templates  # imported here: vorlagen builds on this module

    template_errors, template_warnings = check_templates(fach, taxonomy, docs, pages_of)
    return errors + template_errors, warnings + template_warnings


def release_clean(fach: Fach, errors: list[str]) -> list[str]:
    """Set status 'freigegeben' on every dossier/card/template still marked 'entwurf' without check error. Returns their names."""
    released = []
    for note in [*load_notes(fach), *load_templates(fach)]:
        name = note.path.relative_to(fach.wissen).as_posix()
        if note.meta.get("status") != "entwurf" or any(error.startswith(f"{name}:") for error in errors):
            continue
        text = note.path.read_text(encoding="utf-8")
        text = re.sub(r"^status: entwurf[ \t]*$", f"status: freigegeben\nfreigegeben_am: '{date.today().isoformat()}'",
                      text, count=1, flags=re.MULTILINE)
        atomic_write_text(note.path, text)
        released.append(name)
    return released
