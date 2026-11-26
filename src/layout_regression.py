"""Layout-Regression: gebaute PDFs gegen die importierten Original-PDFs pruefen.

QMDs im positioned-draft-Modus rekonstruieren ein Original-PDF, dessen Pfad im
Frontmatter unter ``material.import.source-pdf`` steht (relativ zum Repo-Root).
Dieses Modul vergleicht das gebaute PDF mit dem Original auf die Invarianten
dieses Modus: Seitenzahl, Seitenformat und Platzierung der Bilder. Text wird
bewusst nicht verglichen -- er wird neu gesetzt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
import yaml

SEITENFORMAT_TOLERANZ_PT = 1.0
BILD_TOLERANZ = 0.02  # Anteil der Seitenbreite/-hoehe


def source_pdf_referenz(qmd_text: str) -> str | None:
    """``material.import.source-pdf`` aus dem Frontmatter lesen (relativ zum Repo-Root)."""
    if not qmd_text.startswith("---"):
        return None
    ende = qmd_text.find("\n---", 3)
    if ende < 0:
        return None
    try:
        meta = yaml.safe_load(qmd_text[4:ende]) or {}
    except yaml.YAMLError:
        return None
    import_angabe = (meta.get("material") or {}).get("import") or {}
    referenz = import_angabe.get("source-pdf")
    return referenz if isinstance(referenz, str) and referenz.strip() else None


@dataclass(frozen=True)
class Abweichung:
    art: str
    detail: str


def _bildplatzierungen(page: pymupdf.Page) -> dict[bytes | tuple, list[tuple[float, float, float, float]]]:
    """Bildplatzierungen je Inhalt: Digest -> Positionen (Mitte x, Mitte y, Breite, Hoehe als Seitenanteil).

    Der Digest identifiziert das Bild ueber beide PDFs hinweg (gleiche Quelldateien
    behalten ihren Inhalt); Bilder ohne Digest fallen auf die Bounding-Box als Schluessel.
    """
    if page.rect.width <= 0 or page.rect.height <= 0:
        return {}
    platzierungen: dict[bytes | tuple, list[tuple[float, float, float, float]]] = {}
    for info in page.get_image_info(hashes=True):
        x0, y0, x1, y1 = info["bbox"]
        schluessel = info.get("digest") or ("bbox", round(x0), round(y0), round(x1), round(y1))
        position = (
            (x0 + x1) / 2 / page.rect.width,
            (y0 + y1) / 2 / page.rect.height,
            (x1 - x0) / page.rect.width,
            (y1 - y0) / page.rect.height,
        )
        platzierungen.setdefault(schluessel, []).append(position)
    return {schluessel: sorted(positionen) for schluessel, positionen in platzierungen.items()}


def _positionen_vergleichen(
    abweichungen: list[Abweichung], seite: int, soll: list[tuple[float, float, float, float]], ist: list[tuple[float, float, float, float]]
) -> None:
    if len(soll) != len(ist):
        abweichungen.append(
            Abweichung("bildanzahl", f"Seite {seite}: {len(ist)} Bildplatzierung(en) gebaut, Original hat {len(soll)}")
        )
        return
    for soll_position, ist_position in zip(soll, ist):
        for name, soll_wert, ist_wert in zip(
            ("Bildmitte x", "Bildmitte y", "Bildbreite", "Bildhoehe"), soll_position, ist_position
        ):
            if abs(soll_wert - ist_wert) > BILD_TOLERANZ:
                abweichungen.append(
                    Abweichung(
                        "bildposition",
                        f"Seite {seite}: {name} {ist_wert:.3f} gebaut, Original {soll_wert:.3f}",
                    )
                )


def _rest_vergleichen(
    abweichungen: list[Abweichung], seite: int, soll: list[tuple[float, float, float, float]], ist: list[tuple[float, float, float, float]]
) -> None:
    """Positionsvergleich fuer Bilder ohne Inhalts-Match (z. B. neu kodierte Zeichnungen).

    Gepaart wird jede Original-Position mit der naechsten gebauten Position: Decken
    sich die Positionsmengen, ist das Layout gleich -- welches Bild dort liegt, kann
    ohne Inhaltsabgleich nicht unterschieden werden. Eine wirklich verschobene
    Zeichnung findet nur eine ferne Gegenposition und wird gemeldet.
    """
    if len(soll) != len(ist):
        abweichungen.append(
            Abweichung("bildanzahl", f"Seite {seite}: {len(ist)} Bildplatzierung(en) gebaut, Original hat {len(soll)}")
        )
        return
    ist_rest = list(ist)
    for soll_position in sorted(soll):
        ist_position = min(
            ist_rest, key=lambda position: sum((soll_wert - ist_wert) ** 2 for soll_wert, ist_wert in zip(soll_position, position))
        )
        ist_rest.remove(ist_position)
        _positionen_vergleichen(abweichungen, seite, [soll_position], [ist_position])


def vergleiche(gebaut: Path, original: Path) -> list[Abweichung]:
    """Gebautes PDF gegen Original pruefen; leere Liste = keine Abweichung.

    Bilder werden zunaechst ueber ihren Inhalt (Digest) gepaart -- gleiche
    Quelldateien behalten ihren Digest und sind so eindeutig zugeordnet, egal
    in welcher Reihenfolge sie gerendert werden. Bilder ohne Gegenstueck
    (z. B. neu kodierte Zeichnungen) werden ueber ihre Positionen gepaart.
    """
    abweichungen: list[Abweichung] = []
    with pymupdf.open(gebaut) as neu, pymupdf.open(original) as alt:
        if neu.page_count != alt.page_count:
            abweichungen.append(
                Abweichung("seitenzahl", f"{neu.page_count} Seite(n) gebaut, Original hat {alt.page_count}")
            )
        for nummer in range(min(neu.page_count, alt.page_count)):
            seite = nummer + 1
            seite_neu = neu.load_page(nummer)
            seite_alt = alt.load_page(nummer)
            if (
                abs(seite_neu.rect.width - seite_alt.rect.width) > SEITENFORMAT_TOLERANZ_PT
                or abs(seite_neu.rect.height - seite_alt.rect.height) > SEITENFORMAT_TOLERANZ_PT
            ):
                abweichungen.append(
                    Abweichung(
                        "seitenformat",
                        f"Seite {seite}: {seite_neu.rect.width:.1f}x{seite_neu.rect.height:.1f}pt gebaut, "
                        f"Original {seite_alt.rect.width:.1f}x{seite_alt.rect.height:.1f}pt",
                    )
                )
            neu_bilder = _bildplatzierungen(seite_neu)
            alt_bilder = _bildplatzierungen(seite_alt)
            for schluessel in sorted(alt_bilder, key=repr):
                if schluessel in neu_bilder:
                    _positionen_vergleichen(abweichungen, seite, alt_bilder[schluessel], neu_bilder[schluessel])
            rest_soll = sorted(
                (position for schluessel, positionen in alt_bilder.items() if schluessel not in neu_bilder for position in positionen)
            )
            rest_ist = sorted(
                (position for schluessel, positionen in neu_bilder.items() if schluessel not in alt_bilder for position in positionen)
            )
            _rest_vergleichen(abweichungen, seite, rest_soll, rest_ist)
    return abweichungen


@dataclass
class Pruefbericht:
    quelle: str
    status: str  # "ok" | "abweichung" | "offen" | "original-fehlt"
    abweichungen: list[Abweichung] = field(default_factory=list)


def pruefe_dokument(qmd_pfad: Path, gebaut: Path | None, original: Path | None) -> Pruefbericht:
    quelle = qmd_pfad.as_posix()
    if original is None or not original.is_file():
        return Pruefbericht(quelle, "original-fehlt")
    if gebaut is None or not gebaut.is_file():
        return Pruefbericht(quelle, "offen")
    abweichungen = vergleiche(gebaut, original)
    return Pruefbericht(quelle, "abweichung" if abweichungen else "ok", abweichungen)
