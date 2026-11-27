"""PDF- und Bild-Bestand erschliessen: Dateien aus dem _eingang in die Wissensbasis verschieben.

erschliessen() legt eine PDF- oder Bilddatei unter ``wissen/<ziel>/`` ab und
verzeichnet sie in einem gemeinsamen SHA-256-Manifest. Identische Dateien
werden nur einmal erschlossen und gespeichert -- auch wenn sie unter anderem
Namen oder fuer einen anderen Zweck (Arbeitsblatt-PDF, einzelnes Aufgabenbild)
erneut importiert werden.
verlinse_import_pdf() ersetzt in einer QMD die ``material.import.source``-
Referenz auf die geloeschte DOCX-Quelle durch ``material.import.source-pdf``
mit dem Pfad des erschlossenen PDFs.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from material_core.filesystem import atomic_write_text
from material_core.metadata import split_frontmatter
from material_core import workspace
from material_core.pdf_sources import MANIFEST_NAME, WISSEN_DIR_NAME, manifest_pfad, read_manifest


ROOT_DIR = workspace.root()
ORIGINAL_SUFFIX = "-original"
ERLAUBTE_SUFFIXE = {".pdf", ".png", ".jpg", ".jpeg"}

STATUS_ERSCHLOSSEN = "erschlossen"
STATUS_DUPLIKAT = "duplikat"
STATUS_TROCKEN = "trocken"


@dataclass(frozen=True)
class ErschliessungErgebnis:
    quelle: Path
    ziel: Path | None
    status: str
    pruefsumme: str
    duplikat_von: Path | None = None


def manifest_laden(root: Path) -> dict:
    return read_manifest(manifest_pfad(root), missing_ok=True)


def manifest_speichern(root: Path, daten: dict) -> None:
    pfad = manifest_pfad(root)
    atomic_write_text(
        pfad,
        json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


@contextlib.contextmanager
def _manifest_lock(root: Path):
    """Exklusiver Dateilock um Laden+Aendern+Speichern des Manifests.

    Schuetzt den Lese-Aendern-Schreiben-Zyklus auch gegen ein zeitgleiches
    ``erschliessen()`` aus einem anderen Prozess (z. B. `inv pdf-erschliessen`
    in einem Terminal, waehrend die Material-UI laeuft) -- ``runtime.documents.lock``
    in der Material-UI schuetzt nur innerhalb des eigenen Prozesses. Liegt bewusst
    unter ``.material-ui/`` statt unter ``wissen/``, damit ein `trocken=True`-Aufruf
    (der garantiert nichts auf der Platte anlegt) nicht als Nebenwirkung schon den
    wissen/-Ordner erzeugt.
    """
    lock_pfad = root / ".material-ui" / "pdf-erschliessung.lock"
    lock_pfad.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_pfad, "w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def pruefsumme(pfad: Path) -> str:
    sha = hashlib.sha256()
    with pfad.open("rb") as datei:
        for block in iter(lambda: datei.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def ziel_name(quelle: Path) -> str:
    if quelle.stem.endswith(ORIGINAL_SUFFIX):
        return f"{quelle.stem[: -len(ORIGINAL_SUFFIX)]}{quelle.suffix}"
    return quelle.name


def _ziel_pfad(root: Path, ziel_rel: str, quelle: Path) -> Path:
    ziel_rel = ziel_rel.strip().strip("/")
    teile = [teil for teil in ziel_rel.split("/") if teil]
    if not teile or any(teil in {"..", "."} or teil.startswith(".") for teil in teile):
        raise ValueError(f"Ungueltiger Zielordner unter wissen/: {ziel_rel!r}")
    return root / WISSEN_DIR_NAME / Path(*teile) / ziel_name(quelle)


def erschliessen(
    quelle: Path,
    ziel_rel: str,
    *,
    root: Path = ROOT_DIR,
    trocken: bool = False,
) -> ErschliessungErgebnis:
    """PDF oder Bild nach wissen/<ziel_rel>/ verschieben; Dubletten nur einmal speichern."""
    quelle = quelle.resolve()
    root = root.resolve()
    if quelle.suffix.lower() not in ERLAUBTE_SUFFIXE or not quelle.is_file():
        raise FileNotFoundError(f"Keine vorhandene PDF- oder Bilddatei: {quelle}")
    with _manifest_lock(root):
        daten = manifest_laden(root)
        summe = pruefsumme(quelle)
        eintrag = daten["eintraege"].get(summe)
        if eintrag:
            vorhandener = root / WISSEN_DIR_NAME / eintrag["pfad"]
            return ErschliessungErgebnis(quelle, None, STATUS_DUPLIKAT, summe, vorhandener)
        ziel = _ziel_pfad(root, ziel_rel, quelle)
        if trocken:
            return ErschliessungErgebnis(quelle, ziel, STATUS_TROCKEN, summe)
        if ziel.exists():
            raise FileExistsError(
                f"{ziel} existiert bereits mit anderem Inhalt (Pruefsumme {summe[:12]})."
            )
        ziel.parent.mkdir(parents=True, exist_ok=True)
        quelle.replace(ziel)
        daten["eintraege"][summe] = {
            "pfad": ziel.relative_to(root / WISSEN_DIR_NAME).as_posix(),
            "erschlossen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        manifest_speichern(root, daten)
        return ErschliessungErgebnis(quelle, ziel, STATUS_ERSCHLOSSEN, summe)


_QUELLE_MUSTER = re.compile(r"(?m)^(\s+)source:\s*_eingang/onlyoffice/.*\.docx[^\S\r\n]*$")
_INCLUDEPDF_MUSTER = re.compile(r"(\\includepdf\[[^\]]*\]\{)([^}]*-original\.pdf)(\})")


def verlinse_import_pdf(qmd_pfad: Path, pdf_pfad: str, *, root: Path = ROOT_DIR) -> Path:
    """Ersetzt material.import.source (DOCX) durch source-pdf mit dem PDF-Pfad.

    Im pdfpages-Modus wird zusaetzlich der \\includepdf-Verweis im Dokumentkoerper
    auf den neuen PDF-Standort umgebogen.
    """
    qmd_pfad = qmd_pfad.resolve()
    text = qmd_pfad.read_text(encoding="utf-8")
    parts = split_frontmatter(text)
    if parts is None:
        raise ValueError(f"Kein YAML-Frontmatter: {qmd_pfad}")
    if "\r\n" in parts.header:
        raise ValueError(f"CRLF-Zeilenenden nicht unterstuetzt: {qmd_pfad}")
    neuer_header, treffer = _QUELLE_MUSTER.subn(rf"\g<1>source-pdf: {pdf_pfad}", parts.header)
    if treffer != 1:
        raise ValueError(
            f"Erwartete genau eine importierte DOCX-Quelle in {qmd_pfad}, gefunden: {treffer}"
        )
    body = parts.body
    if _INCLUDEPDF_MUSTER.search(body):
        relativ = os.path.relpath((root / pdf_pfad).resolve(), qmd_pfad.parent)
        body = _INCLUDEPDF_MUSTER.sub(lambda m: m.group(1) + relativ + m.group(3), body, count=1)
    atomic_write_text(qmd_pfad, parts.prefix + neuer_header + parts.closing + body)
    return qmd_pfad
