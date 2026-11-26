from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from material_ui.errors import InvalidInput
from material_ui.storage import DocumentRepository, atomic_write_bytes, atomic_write_text


class AssetService:
    def __init__(self, root: Path, documents: DocumentRepository) -> None:
        self.root = root
        self.documents = documents

    def import_images(self, source: Path, data: dict, payloads: dict[str, bytes]) -> dict:
        with self.documents.lock:
            self.documents.check_revision(source, data.get("revision"))
            document_dir = source.parent
            assets_dir = document_dir / "assets"
            if not assets_dir.resolve().is_relative_to(self.root.resolve()):
                raise InvalidInput("Asset-Pfad liegt ausserhalb des Projekts.")
            assets_dir.mkdir(exist_ok=True)
            stem = sanitize_stem(str(data.get("filename") or "material"))
            original_name = unique_name(assets_dir, f"{stem}-original.png")
            clean_name = unique_name(assets_dir, f"{stem}-clean.png")
            meta_name = unique_name(assets_dir, f"{stem}.meta.yaml")
            markdown = image_markdown(data, f"assets/{clean_name}")
            committed = []
            with tempfile.TemporaryDirectory(dir=document_dir, prefix=".material-import-") as staging:
                staging_dir = Path(staging)
                atomic_write_bytes(staging_dir / original_name, payloads["original"])
                atomic_write_bytes(staging_dir / clean_name, payloads["clean"])
                atomic_write_text(staging_dir / meta_name, meta_yaml(data, original_name, clean_name))
                try:
                    for name in (original_name, clean_name, meta_name):
                        destination = assets_dir / name
                        os.link(staging_dir / name, destination)
                        committed.append(destination)
                    if data.get("insert"):
                        self.documents.insert(source, markdown, data.get("revision"))
                except Exception:
                    for destination in committed:
                        destination.unlink(missing_ok=True)
                    raise
            snapshot = self.documents.read(source)
            return {
                "assetPath": (assets_dir / clean_name).relative_to(self.root).as_posix(),
                "metaPath": (assets_dir / meta_name).relative_to(self.root).as_posix(),
                "markdown": markdown, "document": snapshot["text"], "revision": snapshot["revision"],
            }


def image_markdown(data: dict[str, Any], clean_rel: str) -> str:
    alt = str(data.get("alt") or data.get("description") or "Material").replace("]", "\\]")
    width = str(data.get("width") or "80%").strip()
    image = f"![{alt}]({clean_rel}){{width={width}}}"
    if data.get("taskBlock", True):
        return f"\n::: aufgabe\n{image}\n:::\n"
    return f"\n{image}\n"


def meta_yaml(data: dict[str, Any], original_name: str, clean_name: str) -> str:
    edits = data.get("edits") or ["rohimport"]
    edit_lines = "\n".join(f"  - {yaml_string(str(edit))}" for edit in edits)
    tags = parse_tags(data.get("tags"))
    tags_block = "tags: []" if not tags else "tags:\n" + "\n".join(f"  - {yaml_string(tag)}" for tag in tags)
    return "\n".join(
        [
            f"id: {yaml_string(sanitize_stem(str(data.get('filename') or 'material')))}",
            f"quelle: {yaml_string(str(data.get('source') or ''))}",
            f"seite: {yaml_string(str(data.get('page') or ''))}",
            f"klasse: {yaml_string(str(data.get('klasse') or ''))}",
            f"thema: {yaml_string(str(data.get('thema') or ''))}",
            f"typ: {yaml_string(str(data.get('kind') or 'aufgabe'))}",
            f"beschreibung: {yaml_string(str(data.get('description') or data.get('alt') or ''))}",
            tags_block,
            "dateien:",
            f"  original: {yaml_string(original_name)}",
            f"  clean: {yaml_string(clean_name)}",
            "bearbeitung:",
            edit_lines,
            "status: rohimport",
            "",
        ]
    )


def parse_tags(value: Any) -> list[str]:
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = [str(item) for item in value]
    else:
        items = []
    seen: list[str] = []
    for item in items:
        cleaned = normalize_tag_path(item)
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen


def normalize_tag_path(value: str) -> str:
    """Tag-Pfad fuer hierarchische Tags normalisieren: `/klasse-10//klausuren/` -> `klasse-10/klausuren`."""
    segments = [segment.strip() for segment in str(value).split("/")]
    return "/".join(segment for segment in segments if segment)


def tag_path_matches(tag: str, scope: str) -> bool:
    """Ob `tag` innerhalb von `scope` liegt: `scope` selbst oder ein Nachfahre davon."""
    return tag == scope or tag.startswith(f"{scope}/")


def unique_name(folder: Path, filename: str) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = filename
    counter = 2
    while (folder / candidate).exists():
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def sanitize_stem(value: str) -> str:
    value = value.lower()
    replacements = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return (value or "material")[:80]


def yaml_string(value: str) -> str:
    return json.dumps(value.strip(), ensure_ascii=False)
