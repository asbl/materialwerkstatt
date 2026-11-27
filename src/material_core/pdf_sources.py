"""Manifest und Seitentexte der erschlossenen PDF-Quellen."""
import json
from pathlib import Path

WISSEN_DIR_NAME = "wissen"
MANIFEST_NAME = "_pdf-erschliessung.json"


def manifest_pfad(root: Path) -> Path:
    return root / WISSEN_DIR_NAME / MANIFEST_NAME


def read_manifest(path: Path, *, missing_ok=False) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if not missing_ok:
            raise
        return {"version": 1, "eintraege": {}}
    if not isinstance(data, dict) or not isinstance(data.get("eintraege"), dict):
        raise ValueError(f"Ungültiges Erschließungsmanifest: {path}")
    return data


def page_texts(path: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(path) as document:
        if document.needs_pass:
            return []
        return [" ".join(page.get_text().split()) for page in document]
