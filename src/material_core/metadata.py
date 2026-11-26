from __future__ import annotations

import io
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


@dataclass
class Frontmatter:
    prefix: str
    header: str
    closing: str
    body: str


def split_frontmatter(text: str) -> Frontmatter | None:
    opening = re.match(r"\A(?:\ufeff)?---[^\S\r\n]*\r?\n", text)
    if opening is None:
        return None
    closing = re.search(r"(?m)^(?:---|\.\.\.)[^\S\r\n]*(?:\r?\n|\Z)", text[opening.end():])
    if closing is None:
        return None
    start = opening.end() + closing.start()
    end = opening.end() + closing.end()
    return Frontmatter(text[:opening.end()], text[opening.end():start], text[start:end], text[end:])


_parser_local = threading.local()
_fast_parser_local = threading.local()


def yaml_parser() -> YAML:
    # ruamel-YAML-Instanzen sind nicht thread-sicher; pro Thread eine wiederverwenden,
    # statt bei jedem read_metadata/set_fields eine neue aufzubauen.
    parser = getattr(_parser_local, "parser", None)
    if parser is None:
        parser = YAML()
        parser.preserve_quotes = True
        parser.width = 4096
        _parser_local.parser = parser
    return parser


def fast_yaml_parser() -> YAML:
    # Reiner Lesezugriff (Index, Suche): typ="safe" ist deutlich schneller als der
    # Round-Trip-Parser und liefert fuer Klartextdaten dieselben Werte (YAML 1.2).
    # Wer das Ergebnis wieder serialisieren will (set_fields), braucht weiterhin
    # yaml_parser(), weil safe geladene Skalare keine Zitierstil-Information tragen.
    parser = getattr(_fast_parser_local, "parser", None)
    if parser is None:
        parser = YAML(typ="safe")
        _fast_parser_local.parser = parser
    return parser


def _parse_header(header: str, parser: YAML) -> Mapping:
    try:
        metadata = parser.load(header)
    except YAMLError as error:
        raise ValueError(f"Ungültiger YAML-Header: {error}") from error
    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise ValueError("Der YAML-Header muss ein Objekt sein.")
    return metadata


def read_metadata(text: str) -> Mapping:
    parts = split_frontmatter(text)
    if parts is None:
        return {}
    return _parse_header(parts.header, yaml_parser())


def read_metadata_fast(text: str) -> Mapping:
    """Wie read_metadata, aber mit dem schnellen Safe-Loader (nur lesende Zugriffe)."""
    parts = split_frontmatter(text)
    if parts is None:
        return {}
    return _parse_header(parts.header, fast_yaml_parser())


def pdf_options(metadata: Mapping) -> Mapping:
    formats = metadata.get("format")
    if isinstance(formats, Mapping):
        for engine in ("pdf", "typst", "beamer"):
            if engine in formats:
                options = formats[engine]
                return options if isinstance(options, Mapping) else {}
    return {}


def template_value(text: str) -> str:
    metadata = read_metadata(text)
    return str(pdf_options(metadata).get("template") or metadata.get("template") or "")


MIN_FONTSIZE_PT = 11.0


def clamp_fontsize(value):
    """Grundschrift nie unter 11 pt; fehlende Angabe wird auf 11 pt gesetzt."""
    if not isinstance(value, str):
        return "11pt" if value is None else value
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)pt\s*", value)
    if match is None:
        return value
    size = max(float(match.group(1)), MIN_FONTSIZE_PT)
    return f"{size:g}pt"


def enforce_min_fontsize(metadata: dict, default: str | None = None) -> None:
    """Begrenzt die effektive Schriftgröße auf mindestens 11 pt.

    Ohne `default` wird nur eine vorhandene Angabe korrigiert; mit `default`
    wird zusätzlich eine fehlende Angabe auf den Standard gesetzt.
    """
    if "fontsize" in metadata:
        metadata["fontsize"] = clamp_fontsize(metadata["fontsize"])
    elif default is not None:
        metadata["fontsize"] = default
    formats = metadata.get("format")
    if isinstance(formats, Mapping):
        for engine in ("pdf", "typst", "beamer"):
            options = formats.get(engine)
            if isinstance(options, Mapping) and "fontsize" in options:
                options["fontsize"] = clamp_fontsize(options["fontsize"])


def output_filename(text: str, default: str, *, metadata: Mapping | None = None) -> str:
    metadata = read_metadata(text) if metadata is None else metadata
    value = pdf_options(metadata).get("output-file", metadata.get("output-file", default))
    if not isinstance(value, str) or not value.strip():
        raise ValueError("output-file muss eine nicht leere Zeichenkette sein.")
    return value


def set_fields(text: str, fields: Mapping) -> str:
    """Setzt oder entfernt Zeichenketteneintraege und Listen im Frontmatter.

    Zeichenketten und Listen von Zeichenketten sind erlaubt; Listen dienen
    vor allem dem tags-Eintrag. Leere Werte und leere Listen entfernen den
    Eintrag. Andere Eintraege, Kommentare, Anfuehrungszeichen und der
    Dokumentkoerper bleiben unveraendert.
    """
    for key, value in fields.items():
        if not isinstance(key, str) or not key.strip() or key != key.strip():
            raise ValueError(f"Ungültiger Metadaten-Schlüssel: {key!r}")
        if isinstance(value, list):
            if not all(isinstance(item, str) for item in value):
                raise ValueError(f"Wert für {key} muss eine Liste von Zeichenketten sein.")
        elif not isinstance(value, str):
            raise ValueError(f"Wert für {key} muss eine Zeichenkette oder eine Liste sein.")
    parts = split_frontmatter(text)
    metadata = read_metadata(text)
    changed = False
    for key, value in fields.items():
        if isinstance(value, list):
            cleaned = [item.strip() for item in value if item.strip()]
            if cleaned:
                metadata[key] = cleaned
                changed = True
            else:
                changed = changed or key in metadata
                metadata.pop(key, None)
        elif value.strip():
            metadata[key] = value
            changed = True
        else:
            changed = changed or key in metadata
            metadata.pop(key, None)
    if not changed and not metadata:
        return text
    output = io.StringIO()
    yaml_parser().dump(metadata, output)
    header = output.getvalue()
    if parts is None:
        return f"---\n{header}---\n\n{text}"
    if "\r\n" in parts.prefix:
        header = header.replace("\n", "\r\n")
    return f"{parts.prefix}{header}{parts.closing}{parts.body}"


def set_template(text: str, template: str, engine: str | None = None) -> str:
    from material_core.designs import sync_template_design

    if engine is not None and engine not in {"pdf", "typst", "beamer"}:
        raise ValueError("Unbekanntes PDF-Format.")
    parts = split_frontmatter(text)
    metadata = read_metadata(text)
    if not template and not template_value(text):
        return sync_template_design(text)
    # Selecting a different template must never retain a stale release binding.
    metadata.pop("template-release", None)
    if template.rsplit("/", 1)[-1] != template_value(text).replace("\\", "/").rsplit("/", 1)[-1]:
        metadata.pop("template-context", None)
    if "template" in metadata:
        del metadata["template"]
    formats = metadata.get("format")
    if not isinstance(formats, Mapping):
        previous = formats if isinstance(formats, str) else None
        formats = {}
        if previous and previous not in {"pdf", "typst", "beamer"}:
            formats[previous] = "default"
        metadata["format"] = formats
        if previous in {"pdf", "typst", "beamer"}:
            formats[previous] = {}
    current_engine = next((name for name in ("pdf", "typst", "beamer") if name in formats), None)
    target_engine = engine if template and engine else current_engine or engine or "pdf"
    if template and engine and current_engine and current_engine != target_engine:
        portable_options = {"output-file", "papersize", "fontsize", "lang", "toc", "number-sections"}
        previous_options = formats.get(current_engine)
        carried_options = {
            name: value for name, value in previous_options.items() if name in portable_options
        } if isinstance(previous_options, Mapping) else {}
        for name in ("pdf", "typst", "beamer"):
            if name != target_engine:
                formats.pop(name, None)
        if not isinstance(formats.get(target_engine), Mapping):
            formats[target_engine] = carried_options
    if not isinstance(formats.get(target_engine), Mapping):
        formats[target_engine] = {}
    if template:
        formats[target_engine]["template"] = template
    else:
        formats[target_engine].pop("template", None)
    output = io.StringIO()
    yaml_parser().dump(metadata, output)
    header = output.getvalue()
    if parts is None:
        return sync_template_design(f"---\n{header}---\n\n{text}")
    if "\r\n" in parts.prefix:
        header = header.replace("\n", "\r\n")
    return sync_template_design(f"{parts.prefix}{header}{parts.closing}{parts.body}")
