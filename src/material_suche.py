"""Volltextsuche ueber den erschlossenen PDF-Bestand der Wissensbasis.

Der Bestand steht im Verzeichnis ``wissen/_pdf-erschliessung.json`` (Pruefsumme
mit Pfad, relativ zu ``wissen/``). Dieses Modul extrahiert den Text aller
verzeichneten PDFs in einen lokalen Index (``build/material-index.json``,
regenerierbar, nicht versioniert) und durchsucht ihn.

Scans ohne Textebene werden im Index als ``ohne_text`` vermerkt; sie brauchen
OCR (``inv wissen-ocr``) und bleiben hier stumm.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from material_core.pdf_sources import MANIFEST_NAME, page_texts, read_manifest

INDEX_NAME = "material-index.json"


def index_pfad(root: Path) -> Path:
    """Indexpfad zum Repo-Root (build/ ist ignoriert und regenerierbar)."""
    return root / "build" / INDEX_NAME


def baue_index(wissen_root: Path, ziel: Path | None = None) -> dict:
    """Texte aller erschlossenen PDFs extrahieren und den Index schreiben."""
    eintraege = read_manifest(wissen_root / MANIFEST_NAME)["eintraege"]
    dokumente: dict[str, dict] = {}
    for _pruefsumme, eintrag in sorted(eintraege.items(), key=lambda paar: paar[1]["pfad"]):
        pfad = wissen_root / eintrag["pfad"]
        if not pfad.is_file():
            continue
        seiten = page_texts(pfad)
        dokumente[eintrag["pfad"]] = {
            "seiten": seiten,
            "erschlossen": eintrag.get("erschlossen"),
            "ohne_text": sum(1 for text in seiten if not text),
        }
    index = {
        "version": 1,
        "gebaut": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dokumente": dokumente,
    }
    ziel = ziel if ziel is not None else index_pfad(wissen_root.parent)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return index


def lade_index(root: Path) -> dict | None:
    pfad = index_pfad(root)
    if not pfad.is_file():
        return None
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@dataclass(frozen=True)
class Treffer:
    pfad: str
    seite: int
    ausschnitt: str


def suche(index: dict, begriff: str, limit: int = 20) -> list[Treffer]:
    """Groß-/Kleinschreibungsunempfindliche Teiltextsuche ueber alle Bestands-PDFs."""
    needle = begriff.strip().lower()
    if not needle:
        return []
    treffer: list[Treffer] = []
    for pfad, dokument in sorted(index.get("dokumente", {}).items()):
        for nummer, text in enumerate(dokument.get("seiten", []), start=1):
            position = text.lower().find(needle)
            if position < 0:
                continue
            start = max(0, position - 60)
            ende = position + len(needle) + 60
            ausschnitt = ("…" if start > 0 else "") + text[start:ende] + ("…" if ende < len(text) else "")
            treffer.append(Treffer(pfad, nummer, ausschnitt))
            if len(treffer) >= limit:
                return treffer
    return treffer
