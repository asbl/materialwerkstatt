"""Inhaltliche Renderrevision: reine Index-Metadaten ändern die Ausgabe nicht."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from material_core.metadata import read_metadata, split_frontmatter, template_value, pdf_options, yaml_parser
from material_core.template_roots import find_template, is_template_dir
from ruamel.yaml.error import YAMLError

INDEX_FIELDS = frozenset({'tags', 'subject', 'grade', 'kind', 'deck'})


def render_content(text: str, source: Path | None = None) -> str:
    metadata = dict(read_metadata(text))
    parts = split_frontmatter(text)
    body = parts.body if parts else text
    template = template_value(text)
    custom = False
    base = source.parent if source else None
    if not template and source is not None:
        for directory in (source.parent, *source.parent.parents):
            stop = False
            for name in ('_metadata.yml', '_quarto.yml'):
                config = directory / name
                if not config.is_file():
                    continue
                try:
                    settings = yaml_parser().load(config.read_text()) or {}
                    if not isinstance(settings, dict):
                        custom = True
                        stop = True
                        break
                    value = pdf_options(settings).get('template') or settings.get('template')
                    if value:
                        template, base = str(value), directory
                        stop = True
                        break
                except (OSError, YAMLError):
                    custom = True
                    stop = True
                    break
                if name == '_quarto.yml':
                    stop = True
            if stop:
                break
    if template and base is not None:
        selected = (base / template).resolve()
        if not selected.exists():
            builtin = find_template(template)
            if builtin is not None:
                selected = builtin
        custom = not is_template_dir(selected.parent)
    # Unbekannte Vorlagen und explizite Meta-Shortcodes dürfen Indexfelder drucken.
    if not custom and not re.search(r'\{\{<\s*meta\b', body):
        for field in INDEX_FIELDS:
            metadata.pop(field, None)
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str) + '\n' + body


def render_revision(text: str, source: Path | None = None) -> str:
    return hashlib.sha256(render_content(text, source).encode('utf-8')).hexdigest()
