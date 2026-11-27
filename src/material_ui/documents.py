from __future__ import annotations

import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from material_ui.assets import parse_tags, sanitize_stem, yaml_string
from material_ui.caching import TTLCache
from material_ui.material_changes import MaterialChange
from material_ui.catalog import SourceCatalog, fingerprint
from material_ui.errors import InvalidInput
from material_ui.metadata import read_metadata, split_frontmatter, template_value
from material_ui.metadata import ensure_solution_metadata, solution_filename
from material_ui.storage import atomic_write_text
from material_ui.folder_notes import is_folder_note
from material_ui.tags import TagService
from material_core.designs import DESIGNS, slide_templates, sync_template_design
from material_core.template_roots import find_template, private_root
from material_core.metadata import read_metadata_fast

# Vorpruefung fuer die Notiz-Erkennung: Frontmatter beginnt am Dateianfang.
FRONTMATTER_OPENING = re.compile(r"\A(?:\ufeff)?---[^\S\r\n]*\r?\n")

WORKSHEET_DESIGNS = [design for design in DESIGNS if not design.get("slides_only")]


TEMPLATE_DEFINITIONS = [
    {
        "path": "src/quarto/templates/worksheet-informatik.typst",
        "label": "Informatik",
        "kind": "Arbeitsblatt",
        "tags": ["Arbeitsblatt", "Informatik"],
        "engine": "Typst",
        "description": "Sachliches Arbeitsblatt mit Space Grotesk für Titel und Aufgabenüberschriften.",
        "preview": "A4 · klare Überschriften · Lernkästen · Antwortflächen",
    },
    {
        "path": "src/quarto/templates/latex-template.tex",
        "label": "Arbeitsblatt",
        "kind": "Arbeitsblatt",
        "tags": ["Arbeitsblatt"],
        "engine": "LaTeX",
        "description": "Kompaktes A4-Arbeitsblatt mit engen Rändern, Aufgabenblöcken und Bildern.",
        "preview": "Titel oben, kurze Aufgabenabschnitte, viel Platz für Material und eingebundene Bilder.",
    },
    {
        "path": "src/quarto/templates/slides-template.tex",
        "label": "Folien",
        "kind": "Praesentation",
        "tags": ["Präsentation"],
        "engine": "Beamer",
        "description": "Praesentationslayout mit ruhiger Typografie, klaren Farben und Beamer-Folien.",
        "preview": "Titelfolie, große Frame-Überschriften, farbige Strukturpunkte und Fußzeile.",
    },
    {
        "path": "src/quarto/templates/exam-template.typst",
        "label": "Klausur",
        "tags": ["Klausur"],
        "kind": "Klausur",
        "engine": "Typst",
        "description": "Klausur-Layout mit Namensfeld, Punktespalten, Codebloecken und sauberer Seitennavigation.",
        "preview": "Deckblatt, Bewertungsfelder, Aufgaben mit Punkten und Name-Feld auf Folgeseiten.",
    },
    {
        "path": "src/quarto/templates/math-test-template.typst",
        "label": "Mathe-Test",
        "tags": ["Klausur"],
        "kind": "Klausur",
        "engine": "Typst",
        "description": "Mathematik-Test mit Antwortlinien, Rechengittern, Notentabelle und kompakten Aufgaben.",
        "preview": "Name/Datum-Kopf, kurze Aufgaben, Antwortlinien und kariertes Rechengitter.",
    },
    {
        "path": "src/quarto/templates/nachpruefung-template.typst",
        "label": "Nachprüfung",
        "tags": ["Nachprüfung"],
        "kind": "Nachprüfung",
        "engine": "Typst",
        "description": "Nachprüfungs-Layout für schriftliche und mündliche Teile mit großzügigerer Führung.",
        "preview": "Prüfungsdeckblatt, Aufgaben mit klarer Gewichtung und wiederkehrendem Namensfeld.",
    },
    {
        "path": "src/quarto/templates/foerderplan-template.typst",
        "label": "Förderplan",
        "tags": ["Förderplan"],
        "kind": "Fördermaterial",
        "engine": "Typst",
        "description": "Foerderplan-Layout mit Kopfbereich, Foerderbereichen, Tabellen und Unterschriften.",
        "preview": "Schulkopf, Foerderbereich-Tabelle, Massnahmen, Beobachtung und Unterschriften.",
    },
]

def _private_definitions() -> list[dict]:
    """Katalogeintraege nicht freigegebener Vorlagen (privater Ordner, nie versioniert)."""
    import json
    import sys
    path = private_root() / "template-definitions.json"
    if not path.is_file():
        return []
    try:
        definitions = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"Warnung: {path} nicht lesbar ({error}); private Vorlagen fehlen im Katalog.", file=sys.stderr)
        return []
    return definitions if isinstance(definitions, list) else []


TEMPLATE_DEFINITIONS.extend(_private_definitions())

TEMPLATE_DEFINITIONS.append({
    "path": "src/quarto/templates/checkup-alice.typst",
    "label": "Alice im Wunderland Check-up",
    "kind": "Arbeitsblatt",
    "tags": ["Arbeitsblatt", "Check-up"],
    "engine": "Typst",
    "description": "Alice-Check-up mit direkt zugeordneten Regelkarten und Aufgabenbereichen, Modellen und mehrspaltigen Aufgaben.",
    "preview": "A4 · 12 pt · zugeordnete Regelkarten · Fläschchen, Spielkarte, Schlüssel und Uhr",
})

TEMPLATE_DEFINITIONS.extend(
    {
        "path": f"src/quarto/templates/worksheet-{design['id']}.typst",
        "label": design["label"],
        "kind": "Fördermaterial" if design["id"] == "foerdermaterial" else "Arbeitsblatt",
        "tags": ["Fördermaterial" if design["id"] == "foerdermaterial" else "Arbeitsblatt"],
        "engine": "Typst",
        "description": design["description"],
        "preview": "A4 · symbolfreie Titel · gestaltete Überschriften · Lernkästen · Antwortfelder",
        "design": design,
    }
    for design in WORKSHEET_DESIGNS
)


# Mini layouts share a compact structure and print two copies on A4.
TEMPLATE_DEFINITIONS.extend(
    {
        "path": f"src/quarto/templates/{filename}",
        "label": label,
        "kind": "Mini-AB",
        "tags": ["Mini-AB"],
        "engine": "Typst",
        "description": "Kompaktes Arbeitsblatt zum Ausschneiden mit zwei Exemplaren auf einer A4-Seite.",
        "preview": "2 × A5 auf A4 · Schnittlinie · mindestens 11 pt",
        **({"design": design} if design else {}),
    }
    for filename, label, design in [
        ("worksheet-mini.typst", "Standard", None),
        *[
            (f"worksheet-mini-{design['id']}.typst", design["label"], design)
            for design in WORKSHEET_DESIGNS
            if find_template(f"worksheet-mini-{design['id']}.typst") is not None
        ],
    ]
)


def qmd_source_paths(root: Path) -> list[Path]:
    """Alle sichtbaren QMD-Quellen unter root, wie sie auch die Material-UI indiziert.

    build/ und h5p/ sind reine Generat-/Paketordner ohne QMD-Quellen (siehe CLAUDE.md) und werden
    auf jeder Ebene uebersprungen, da sie je Kurs/Aktivitaet zehntausende H5P-Bibliotheksdateien
    enthalten koennen. archiv/ ist nur auf Root-Ebene relevant.
    """
    sources = []
    for directory, subdirectories, filenames in os.walk(root):
        root_excluded = {"archiv", "foerderempfehlungen"} if Path(directory) == root else set()
        subdirectories[:] = [
            name for name in subdirectories
            if not name.startswith(".") and name not in {"node_modules", "build", "h5p"} and name not in root_excluded
            and not (Path(directory) / name).resolve().is_relative_to(root.resolve() / "foerderempfehlungen")
        ]
        sources.extend(Path(directory) / name for name in filenames
                       if not name.startswith((".", "material-ui-render-"))
                       and name.endswith(".qmd") and not name.endswith("-old.qmd")
                       and not (Path(directory) / name).resolve().is_relative_to(root.resolve() / "foerderempfehlungen"))
    return sorted(sources)


def ensure_qmd(path: Path) -> None:
    if path.suffix != ".qmd" or not path.is_file():
        raise InvalidInput(f"Keine QMD-Datei: {path}")


def ensure_editable(path: Path) -> None:
    """Datei, die im Editor geoeffnet und gespeichert werden darf (QMD oder Markdown)."""
    if path.suffix not in {".qmd", ".md"} or not path.is_file():
        raise InvalidInput(f"Keine bearbeitbare Datei: {path}")


class DocumentService:
    def __init__(self, config, repository, builds, index_extras=None, changes=None):
        self.config = config
        self.changes = changes
        self.repository = repository
        self.builds = builds
        # Plugin-Index-Provider (z. B. Kurse); ohne Plugin liefert er keine Extras.
        self.index_extras = index_extras
        self.cache = TTLCache(config.qmd_cache_ttl)
        self.catalog = SourceCatalog(config)
        self.entry_lock = threading.RLock()
        self.entry_cache = {}
        self.meta_cache = {}
        self._sources_cache: tuple[list[Path], list[dict[str, str]]] | None = None
        self._sources_generation = -1
        self.invalidate_listeners = []
        self.tags = TagService(self)

    def qmd_sources(self) -> list[Path]:
        return self.discover_sources()[0]

    def is_material_source(self, path: Path) -> bool:
        """Shared selection for the global index and folder metadata.

        Callers handle read failures per file so unrelated materials remain usable.
        Die Notizpruefung geht zuerst ueber den Dateikopf (`read_head`): ohne
        `kind: Notiz` im Frontmatter kann die Datei keine Notiz sein, dann
        bleibt der Volltext ungelesen und ungeparst. Andernfalls laeuft die
        Pruefung ueber `source_meta` (Fingerprint-Cache), sodass wiederholte
        Aufrufe weder erneut lesen noch erneut parsen.
        """
        if path.suffix == ".qmd":
            return not path.name.endswith("-old.qmd")
        if path.suffix != ".md" or is_folder_note(path.name):
            return False
        if path.stem.startswith("notiz_"):
            return True
        head = self.catalog.read_head(path)
        parts = split_frontmatter(head)
        damaged = "\ufffd" in head
        if parts is None and not damaged and not FRONTMATTER_OPENING.match(head):
            # Weder Frontmatter noch Dekodierproblem im Kopf: sicher keine Notiz.
            return False
        if parts is not None and not damaged:
            # YAML erlaubt auch Flow-Mappings, explizite und escapte Schluessel.
            # Eine Regex fuer "kind:" uebersieht diese gueltigen Notizen.
            try:
                if read_metadata_fast(head).get("kind") != "Notiz":
                    return False
            except ValueError:
                return False
        # Kopf allein reicht nicht (abgeschnittener Header, kind: Notiz vorhanden
        # oder undekodierbare Zeichen): Volltext lesen, damit Lesefehler
        # (OSError/UnicodeError) wie bisher als Warning zum Aufrufer durchgereicht
        # werden; der Text landet im Katalog-LRU, source_meta parst nur bei
        # Fingerprint-Wechsel.
        self.catalog.read_text(path)
        return self.source_meta(path)["kind"] == "Notiz"

    def discover_sources(self) -> tuple[list[Path], list[dict[str, str]]]:
        """QMD/Notiz-Quellen plus Warnungen, gecached pro Katalog-Generation.

        `catalog.sources()` stoesst dabei den Verzeichnis-Fingerprint-Check an, damit
        externe Aenderungen (Rename/Neu/Loeschen) auch innerhalb der TTL erkannt werden.
        """
        generation, (qmd_paths, md_paths) = self.catalog.snapshot(".qmd", ".md")
        with self.entry_lock:
            if self._sources_cache is not None and self._sources_generation == generation:
                sources, warnings = self._sources_cache
                return list(sources), list(warnings)
        sources = list(qmd_paths)
        warnings = []
        for path in md_paths:
            try:
                # md_paths kommt aus demselben Katalog-Scan: der teure is_visible()-resolve()
                # wird nur fuer tatsaechliche Symlinks gebraucht (siehe scan_result_visible).
                if self.catalog.scan_result_visible(path) and self.is_material_source(path):
                    sources.append(path)
            except (OSError, ValueError) as error:
                warnings.append({"path": path.relative_to(self.config.root).as_posix(), "message": str(error)})
        result = (sorted(sources), warnings)
        with self.entry_lock:
            self._sources_cache = result
            self._sources_generation = generation
        return list(result[0]), list(result[1])

    def add_invalidate_listener(self, listener) -> None:
        """Callback, der bei jeder Index-Invalidierung feuert (z. B. Einheiten-Cache)."""
        self.invalidate_listeners.append(listener)

    def source_meta(self, path: Path) -> dict[str, Any]:
        """Navigations-Metadaten aus dem Frontmatter, per Datei-Fingerprint gecached.

        Ungueltiges Frontmatter liefert leere Metadaten, damit die Datei erreichbar bleibt.
        """
        stamp = fingerprint(path)
        with self.entry_lock:
            cached = self.meta_cache.get(path)
            if cached and cached[0] == stamp:
                return dict(cached[1])
        try:
            metadata = self.catalog.metadata(path)
        except (ValueError, UnicodeError):
            metadata = {}
        note = DocumentService._note_from_metadata(path, metadata)
        kind = "Notiz" if note else DocumentService.header_text(metadata, "kind") or DocumentService.infer_kind(list(path.parts), path.name)
        if path.suffix == ".qmd" and solution_filename(path):
            kind = "Lösung"
        meta = {
            "title": DocumentService.title_from_metadata(metadata) or path.stem.replace("_", " ").replace("-", " "),
            "kind": kind,
            "solution": solution_filename(path) or kind == "Lösung" or "Lösung" in parse_tags(metadata.get("tags")),
            "loesung": self.header_text(metadata, "loesung"),
        }
        if fingerprint(path) == stamp:
            with self.entry_lock:
                self.meta_cache[path] = (stamp, dict(meta))
        return meta


    def _index(self) -> dict[str, list[dict[str, Any]]]:
        entries = []
        sources, warnings = self.discover_sources()
        with self.entry_lock:
            live = set(sources)
            # Nur tatsaechlich verschwundene Dateien verwerfen; Meta-Cache-Eintraege
            # nicht mehr indizierter Markdown-Dateien (keine Notizen) bleiben erhalten,
            # damit discover_sources beim naechsten Katalog-Wechsel nicht erneut parst.
            for path in list(self.entry_cache):
                if path not in live and not path.is_file():
                    del self.entry_cache[path]
            for path in list(self.meta_cache):
                if path not in live and not path.is_file():
                    del self.meta_cache[path]
        root = self.config.root.resolve()
        for path in sources:
            try:
                if not path.resolve().is_relative_to(root):
                    raise ValueError("Datei verweist ausserhalb des Projekts.")
                entries.append(self.qmd_entry(path))
            except (OSError, ValueError) as error:
                warnings.append({"path": path.relative_to(self.config.root).as_posix(), "message": str(error)})
        return {"entries": entries, "warnings": warnings}


    def qmd_entries_cached(self) -> list[dict[str, Any]]:
        return list(self.cache.get(self._index)["entries"])


    def qmd_warnings(self) -> list[dict[str, Any]]:
        return list(self.cache.get(self._index)["warnings"])


    def invalidate_qmd_cache(self, source: Path | None = None) -> None:
        self.catalog.changed(source)
        with self.entry_lock:
            if source is not None:
                self.entry_cache.pop(source, None)
                self.meta_cache.pop(source, None)
                if source.suffix == ".md":
                    # Nur bei Markdown kann sich die Notiz-Zugehoerigkeit der Quellenliste aendern.
                    self._sources_cache = None
            else:
                self._sources_cache = None
        self.cache.invalidate()
        for listener in list(self.invalidate_listeners):
            listener()
        if self.changes is not None:
            self.changes.publish(MaterialChange("invalidated", (source,) if source is not None else ()))


    def all_entries(self) -> list[dict[str, Any]]:
        extras = self.index_extras.entries() if self.index_extras is not None else []
        return self.qmd_entries_cached() + extras


    def qmd_entry(self, path: Path, text: str | None = None) -> dict[str, Any]:
        return self.source_details(path, text)[0]

    def source_details(self, path: Path, text: str | None = None, *, expected_fingerprint=None) -> tuple:
        """One parsed source supplies metadata and output candidates to every consumer."""
        stamp = fingerprint(path)
        if expected_fingerprint is not None and stamp != expected_fingerprint:
            raise ValueError("Datei wurde während der Indexierung geändert.")
        cacheable = text is None or expected_fingerprint is not None
        with self.entry_lock:
            cached = self.entry_cache.get(path)
            if cacheable and cached and cached[0] == stamp:
                entry = dict(cached[1])
                entry["pdf"] = self.config.relative(next((candidate for candidate in cached[2]
                                                          if candidate.suffix.lower() == ".pdf" and candidate.is_file()), None))
                entry["deck"] = self.config.relative(next((candidate for candidate in cached[3] if candidate.is_file()), None)) or ""
                return entry, cached[2], cached[3]
        if text is None:
            text = self.catalog.read_text(path)
            metadata = self.catalog.metadata(path)
        else:
            metadata = read_metadata_fast(text)
        note = self._note_from_metadata(path, metadata)
        candidates = () if note else tuple(self.builds.pdf_candidates(path, text, metadata=metadata))
        decks = () if note else tuple(self.deck_candidates(path, text, metadata=metadata))
        pdf = next((candidate for candidate in candidates if candidate.suffix.lower() == ".pdf" and candidate.is_file()), None)
        deck = next((candidate for candidate in decks if candidate.is_file()), None)
        entry = self._qmd_entry(path, metadata, pdf, deck)
        if cacheable and fingerprint(path) == stamp:
            with self.entry_lock:
                self.entry_cache[path] = (stamp, dict(entry), candidates, decks)
        return entry, candidates, decks

    @staticmethod
    def _note_from_metadata(path: Path, metadata: Mapping) -> bool:
        # Aequivalent zu is_note(path, text), aber ohne erneuten YAML-Parse:
        # die Metadaten liegen bereits geparst vor.
        return (path.suffix.lower() == ".md" and not is_folder_note(path.name)
                and (path.stem.startswith("notiz_") or metadata.get("kind") == "Notiz"))

    def _qmd_entry(self, path: Path, metadata: Mapping, pdf_path: Path | None, deck: Path | None) -> dict[str, Any]:
        relative = self.config.relative(path) or ""
        parts = relative.split("/")
        title = DocumentService.title_from_metadata(metadata) or path.stem.replace("-", " ")
        area = parts[0] if parts else ""
        subject = DocumentService.header_text(metadata, "subject") or (parts[1] if len(parts) > 1 else "")
        grade = DocumentService.header_text(metadata, "grade") or DocumentService.grade_part(parts)
        thema = DocumentService.header_text(metadata, "thema") or DocumentService.topic_part(parts)
        kind = "Notiz" if self._note_from_metadata(path, metadata) else DocumentService.header_text(metadata, "kind") or DocumentService.infer_kind(parts, path.name)
        tags = parse_tags(metadata.get("tags"))
        if path.suffix == ".qmd" and solution_filename(path):
            kind = "Lösung"
            tags = list(dict.fromkeys([*tags, "Lösung"]))
        return {
            "path": relative,
            "name": path.name,
            "stem": path.stem,
            "title": title,
            "folder": self.config.relative(path.parent),
            "area": area,
            "subject": subject,
            "grade": grade,
            "thema": thema,
            "kind": kind,
            "tags": tags,
            "deck": self.config.relative(deck) or "",
            "solution": solution_filename(path) or kind == "Lösung" or "Lösung" in parse_tags(metadata.get("tags")),
            "loesung": self.header_text(metadata, "loesung"),
            "pdf": self.config.relative(pdf_path),
            "mtime": path.stat().st_mtime,
        }


    def tag_counts(self) -> list[dict[str, Any]]:
        return self.tags.tag_counts()

    def rename_tag(self, old_path: str, new_path: str) -> list[str]:
        return self.tags.rename_tag(old_path, new_path)

    def root_tags(self) -> list[str]:
        return self.tags.root_tags()

    def set_tag_root(self, tag: str, root: bool) -> list[str]:
        return self.tags.set_tag_root(tag, root)

    def tag_parents(self) -> dict[str, str]:
        return self.tags.tag_parents()

    def set_tag_parent(self, tag: str, parent: str | None) -> dict[str, str]:
        return self.tags.set_tag_parent(tag, parent)

    @staticmethod
    def grade_part(parts: list[str]) -> str:
        return next((part for part in parts if re.fullmatch(r"klasse-\d{2}", part)), "")


    @staticmethod
    def topic_part(parts: list[str]) -> str:
        grade = DocumentService.grade_part(parts)
        if not grade:
            return ""
        index = parts.index(grade)
        return parts[index + 1] if index + 1 < len(parts) else ""


    def klasse_thema_for(self, source: Path) -> tuple[str, str]:
        parts = (self.config.relative(source) or "").split("/")
        return DocumentService.grade_part(parts), DocumentService.topic_part(parts)


    @staticmethod
    def read_source(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return None

    @staticmethod
    def title_from_metadata(metadata: Mapping) -> str | None:
        value = metadata.get("title")
        return str(value) if value is not None else None

    @staticmethod
    def header_text(metadata: Mapping, key: str) -> str:
        """Nicht leeren Zeichenketteneintrag aus dem Frontmatter, sonst leerer String."""
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return ""

    @staticmethod
    def read_title(path: Path) -> str | None:
        text = DocumentService.read_source(path)
        if text is None:
            return None
        return DocumentService.title_from_metadata(read_metadata(text))

    def deck_candidates(self, source: Path, text: str | None, *, metadata=None) -> list[Path]:
        """Safe deck paths, including references whose files do not exist yet."""
        if text is None:
            return []
        try:
            value = (read_metadata(text) if metadata is None else metadata).get("deck")
        except ValueError:
            return []
        if not isinstance(value, str) or not value.strip():
            return []
        raw = Path(value.strip())
        candidates = [raw] if raw.is_absolute() else [source.parent / raw, self.config.root / raw]
        paths = []
        for candidate in candidates:
            try:
                resolved = self.config.safe_visible_path(str(candidate))
            except InvalidInput:
                continue
            if resolved.suffix == ".excalidraw":
                paths.append(resolved)
        return paths

    def deck_link(self, source: Path, text: str | None) -> str:
        """Resolve an existing frontmatter deck, document-relative before root-relative."""
        for path in self.deck_candidates(source, text):
            if path.is_file():
                return self.config.relative(path) or ""
        return ""


    @staticmethod
    def infer_kind(parts: list[str], name: str) -> str:
        joined = "/".join(parts).lower()
        stem = Path(name).stem.lower()
        if solution_filename(Path(name)):
            return "Lösung"
        if re.fullmatch(r"(?:\d+[ _-])?slides?", stem):
            return "Praesentation"
        if "klausur" in joined or "klassenarbeit" in joined:
            return "Klausur"
        if "nachpruefung" in joined or "nachprüfung" in joined:
            return "Nachprüfung"
        if "foerder" in joined or "förder" in joined:
            return "Fördermaterial"
        if "arbeitsblaetter" in joined or "arbeitsblatt" in stem or stem.startswith(("ab-", "ab_")):
            return "Arbeitsblatt"
        if "lernkarten" in joined:
            return "Lernkarten"
        if "reihenplanung" in stem:
            return "Planung"
        if "probe" in joined:
            return "Probe"
        return "Material"


    def template_entries(self) -> list[dict[str, Any]]:
        from material_core.template_versions import TemplateVersions
        versions = TemplateVersions(self.config.root)
        entries: list[dict[str, Any]] = [{"path": "", "label": "Kein Template-Eintrag", "kind": "", "tags": ["Standard"], "engine": "", "description": "", "preview": ""}]
        for item in TEMPLATE_DEFINITIONS:
            entry = dict(item)
            template_path = self.config.root / entry["path"]
            if not template_path.exists() and entry["path"].startswith("src/quarto/templates/"):
                template_path = find_template(entry["path"], self.config.root / "src/quarto") or template_path
            entry["exists"] = str(template_path.exists()).lower()
            entries.append(versions.catalog_entry(entry))
        return entries


    def template_by_path(self, value: str) -> dict[str, Any] | None:
        clean = value.replace("\\", "/").strip().strip("\"'")
        return next((item for item in [*TEMPLATE_DEFINITIONS, *slide_templates()] if item["path"] == clean), None)


    def resolve_target(self, data: dict[str, Any]) -> tuple[Path, str, dict[str, Any] | None]:
        """Berechnet Zielpfad, Titel und Template-Eintrag fuer eine neue Datei.

        Einzige Implementierung der Pfad-/Praefixregeln aus CLAUDE.md; wird von
        `create_document` (Schreiben) und der Preview-Route (nur Anzeige) genutzt,
        damit UI-Vorschau und tatsaechlicher Zielpfad nie auseinanderlaufen.
        """
        subject = sanitize_stem(str(data.get("subject") or "mathematik"))
        grade = DocumentService.sanitize_grade(str(data.get("grade") or "05"))
        kind = str(data.get("kind") or "Arbeitsblatt")
        topic = sanitize_stem(str(data.get("topic") or "materialien"))
        title = str(data.get("title") or DocumentService.label_from_slug(topic)).strip()
        stem = sanitize_stem(str(data.get("filename") or title or "material"))
        folder = DocumentService.kind_folder(kind)
        mini = kind == "Mini-AB" or bool(data.get("mini"))
        filename_stem = DocumentService.worksheet_stem(stem, mini=mini) if DocumentService.is_worksheet_kind(kind) else stem
        source = self.config.root / "unterricht" / subject / f"klasse-{grade}" / topic / folder / stem / f"{filename_stem}.qmd"
        if data.get("folder") is not None:
            target = self.config.safe_path(str(data["folder"]))
            if not target.is_dir() or not self.config.is_visible(target):
                raise InvalidInput("Ungültiger Zielordner.")
            source = target / f"{filename_stem}.qmd"
        if kind == "Notiz":
            note_stem = stem if stem.startswith("notiz_") else f"notiz_{stem}"
            source = source.with_name(f"{note_stem}.md")
            return self.config.safe_path(str(source)), title, None
        source = self.config.safe_path(str(source))
        template_path = str(data.get("template") or "").strip()
        template_entry = self.template_by_path(template_path) if template_path else None
        if not template_path and kind == "Mini-AB":
            template_entry = self.template_by_path("src/quarto/templates/worksheet-mini.typst")
        if not template_path and kind == "Excalidraw-Folien":
            template_entry = slide_templates()[0]
        if template_path and not template_entry:
            raise InvalidInput("Unbekanntes Template.")
        if template_entry and template_entry.get("target") == "slides":
            source = source.with_name(DocumentService.slide_filename(stem))
        return source, title, template_entry

    def preview_target(self, data: dict[str, Any]) -> dict[str, Any]:
        source, _title, _template_entry = self.resolve_target(data)
        return {"path": self.config.relative(source), "exists": source.exists()}

    def create_document(self, data: dict[str, Any]) -> Path:
        source, title, template_entry = self.resolve_target(data)
        kind = str(data.get("kind") or "Arbeitsblatt")
        if source.exists():
            raise FileExistsError(f"Datei existiert bereits: {self.config.relative(source)}")
        source.parent.mkdir(parents=True, exist_ok=True)
        if kind == "Notiz":
            atomic_write_text(source, f"---\ntitle: {yaml_string(title)}\nkind: Notiz\ntags: []\n---\n\n", overwrite=False)
            return source
        atomic_write_text(source, ensure_solution_metadata(source, sync_template_design(self.document_skeleton(title, kind, source, template_entry))), overwrite=False)
        return source


    @staticmethod
    def sanitize_grade(value: str) -> str:
        match = re.search(r"\d{1,2}", value)
        number = int(match.group(0)) if match else 5
        number = max(1, min(13, number))
        return f"{number:02d}"


    @staticmethod
    def label_from_slug(value: str) -> str:
        return value.replace("-", " ").strip().title() or "Material"


    @staticmethod
    def kind_folder(kind: str) -> str:
        normalized = DocumentService.normalize_label(kind)
        if "klausur" in normalized or "klassenarbeit" in normalized:
            return "klausuren"
        if "nachpruefung" in normalized:
            return "nachpruefungen"
        if "foerder" in normalized:
            return "foerdermaterial"
        if "praesentation" in normalized or "folie" in normalized:
            return "folien"
        if "planung" in normalized:
            return "planung"
        if normalized == "notiz":
            return "notizen"
        return "arbeitsblaetter"


    @staticmethod
    def is_worksheet_kind(kind: str) -> bool:
        return kind == "Mini-AB" or "arbeitsblatt" in DocumentService.normalize_label(kind)


    @staticmethod
    def worksheet_stem(stem: str, *, mini: bool = False) -> str:
        # CLAUDE.md: Arbeitsblaetter tragen das Praefix `ab_`, Mehrfachdruck-Varianten `ab_mini_`.
        cleaned = re.sub(r"^ab[-_](mini[-_])?", "", stem)
        return f"ab_mini_{cleaned}" if mini else f"ab_{cleaned}"

    @staticmethod
    def slide_filename(stem: str) -> str:
        # CLAUDE.md: slide.qmd bekommt die AB-Nummer vorangestellt, wenn das Material nummeriert ist.
        cleaned = re.sub(r"^ab[-_](mini[-_])?", "", stem)
        match = re.match(r"^(\d{1,2})[-_]", cleaned)
        return f"{match.group(1)} slide.qmd" if match else "slide.qmd"


    @staticmethod
    def normalize_label(value: str) -> str:
        return (
            value.lower()
            .replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )


    def document_skeleton(self, title: str, kind: str, source: Path, template_entry: dict[str, Any] | None) -> str:
        if template_entry:
            relative_template = os.path.relpath(self.config.root / template_entry["path"], source.parent)
            format_key = {"Typst": "typst", "Beamer": "beamer"}.get(template_entry.get("engine"), "pdf")
            template_block = f"format:\n  {format_key}:\n    template: {relative_template}\n"
            if (self.config.root / template_entry["path"]).is_file():
                from material_core.template_versions import TemplateVersions
                versions = TemplateVersions(self.config.root)
                release = versions.latest(versions.initial(template_entry["path"]))
                template_block += f"template-release: {release}\n"
        else:
            template_block = "format: pdf\n"
        body = DocumentService.body_skeleton(kind)
        if kind == "Mini-AB" or (template_entry and template_entry.get("kind") == "Mini-AB"):
            body = f"[Mini-AB]\n\n# {title}\n\n{body.rstrip()}\n\n[/Mini-AB]\n"
        result = "\n".join(
            [
                "---",
                f"title: {yaml_string(title)}",
                template_block.rstrip(),
                "---",
                "",
                body.rstrip(),
                "",
                "<!-- material-ui -->",
                "",
            ]
        )
        if template_entry and read_metadata(result).get("template-release"):
            result = versions.freeze_context(source, result)
        return result


    @staticmethod
    def body_skeleton(kind: str) -> str:
        normalized = DocumentService.normalize_label(kind)
        if "klausur" in normalized:
            return "## Aufgabe 1 [10 P]\n\n### a) [4 P]\n\nText der Aufgabe.\n\n[Antwortkasten: 3cm]\n"
        if "nachpruefung" in normalized:
            return "## Aufgabe 1\n\nBearbeite die Aufgabe sorgfaeltig.\n\n[Antwortkasten: 4cm]\n"
        if "foerder" in normalized:
            return "## Ziel\n\nKurze Beschreibung des Foerderziels.\n\n## Uebung\n\n::: aufgabe\nAufgabe einfuegen.\n:::\n"
        if "praesentation" in normalized or "folien" in normalized:
            return "## Einstieg\n\nWelche Idee hast du?\n\n## Gemeinsam entdecken\n\nWas fällt dir auf?\n"
        return "::: aufgabe\nAufgabe einfuegen.\n:::\n"


    def document_issues(self, source: Path, text: str | None = None) -> list[dict[str, Any]]:
        from material_ui.diagnostics import document_issues

        return document_issues(self.builds, source, source.read_text(encoding="utf-8") if text is None else text)


    @staticmethod
    def issue(level: str, title: str, detail: str) -> dict[str, str]:
        return {"level": level, "title": title, "detail": detail}


    @staticmethod
    def split_frontmatter_py(text: str) -> tuple[str, str] | None:
        parts = split_frontmatter(text)
        return (parts.header, parts.body) if parts else None


    @staticmethod
    def current_template_py(text: str) -> str:
        return template_value(text)


    @staticmethod
    def resolve_document_relative(source: Path, value: str) -> Path:
        path = Path(value)
        candidate = path if path.is_absolute() else source.parent / path
        return candidate.resolve()


    @staticmethod
    def missing_image_issues(source: Path, text: str) -> list[dict[str, Any]]:
        from material_ui.diagnostics import missing_image_issues

        return missing_image_issues(source, text)
