"""Förder-PDFs in die Ordnerstruktur der bestehenden Online-Plattform kopieren.

Lernstandspakete deklarieren Quellen und bisherige Zielpfade in einheit.yaml.
Noch nicht migrierte Klasse-05-Ordner werden weiterhin über ONLINE erkannt.
Die Logik hier verwaltet Dateien; Bauen übernimmt der verwaltete inv-Task.
Neue vollständige Pakete werden mit inv lernstand.export erzeugt.
"""

from __future__ import annotations

import filecmp
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

QUELLE = Path("unterricht") / "mathematik" / "klasse-05"
LAYOUT = QUELLE / "materialgestaltung" / "foerdermaterial-vorlagen"
ZIEL_STANDARD = Path("build") / "foerder-online"
LOESUNGEN_ORDNER = "Loesungen"

# Ordnerstruktur der Online-Plattform. Quellordner -> Name des Online-Ordners.
# Die Schreibweise ist absichtlich wörtlich übernommen ("Stufe1" ohne Leerzeichen bei
# Division, Multiplikation und Subtraktion, "Stufe 1a" mit Leerzeichen sonst).
ONLINE: dict[str, dict[str, str]] = {
    "division": {"stufe-1": "Stufe1", "stufe-2": "Stufe2"},
    "multiplikation": {"stufe-1": "Stufe1", "stufe-2": "Stufe2"},
    "operationsverstaendnis": {
        "stufe-1a": "Stufe 1a",
        "stufe-1b": "Stufe 1b",
        "stufe-1c": "Stufe 1c",
        "stufe-2": "Stufe 2",
        "stufe-3": "Stufe 3",
    },
    "subtraktion": {"stufe-1": "Stufe1", "stufe-2": "Stufe2"},
    "zahlenverstaendnis": {
        "stufe-1": "Stufe 1",
        "stufe-2a": "Stufe 2a",
        "stufe-2b": "Stufe 2b",
        "stufe-3": "Stufe 3",
    },
}

BLATT = re.compile(r"^(?P<stem>.+-ab-\d+)\.qmd$")


def pdf_pfad(repo: Path, qmd: Path, stem: str) -> Path:
    """Zentraler PDF-Speicherort (build/pdf/...), mit Rueckfall auf den alten pdf/-Ordner."""
    zentral = repo / "build" / "pdf" / qmd.parent.relative_to(repo) / f"{stem}.pdf"
    if zentral.exists():
        return zentral
    alt = qmd.parent / "pdf" / f"{stem}.pdf"
    return alt if alt.exists() else zentral


@dataclass
class Eintrag:
    stem: str
    qmd: Path
    pdf: Path
    ziel: Path
    loesung: bool
    veraltet: bool = False
    fehlt: bool = False

    @property
    def quelle_qmd(self) -> Path:
        return self.qmd


@dataclass
class Plan:
    eintraege: list[Eintrag] = field(default_factory=list)
    uebersprungen: list[Path] = field(default_factory=list)


def _ordnername(thema: str, stufe_dir: str, alles: bool) -> str | None:
    """Name des Online-Ordners oder None, wenn der Quellordner nicht online vorkommt."""
    if stufe_dir in ONLINE.get(thema, {}):
        return ONLINE[thema][stufe_dir]
    if not alles:
        return None
    match = re.fullmatch(r"stufe-(\w+)", stufe_dir)
    if match:
        return f"Stufe{match.group(1)}"
    return stufe_dir.replace("-", " ").capitalize()


def _neuester_stand(qmd: Path, root: Path) -> float:
    """Zeitpunkt der jüngsten Quelle: Blatt, Lösung, Header, Metadaten."""
    kandidaten = [qmd, qmd.with_name(qmd.stem + "-loesung.qmd"), root / "materialgestaltung" / "foerdermaterial-vorlagen" / "foerder-header.tex", qmd.parent / "_metadata.yml"]
    return max((p.stat().st_mtime for p in kandidaten if p.exists()), default=0.0)


def plane(repo: Path, ziel: Path, *, loesungen: bool = False, alles: bool = False) -> Plan:
    """Welche PDF kommt wohin? Berührt keine Dateien."""
    root = repo / QUELLE
    plan = Plan()
    for qmd in sorted(root.glob("*/foerderkurs-*/*.qmd")):
        m = BLATT.match(qmd.name)
        if not m:
            continue
        thema = qmd.parent.parent.name
        thema = "wegweiser" if thema == "lernstandsdiagnose" else thema
        stufe_dir = qmd.parent.name.removeprefix("foerderkurs-")
        ordner = _ordnername(thema, stufe_dir, alles)
        if ordner is None:
            plan.uebersprungen.append(qmd.parent)
            continue
        stand = _neuester_stand(qmd, root)
        for ist_loesung in (False, True):
            if ist_loesung and not loesungen:
                continue
            stem = m.group("stem") + ("-loesung" if ist_loesung else "")
            pdf = pdf_pfad(repo, qmd, stem)
            if ist_loesung and not qmd.with_name(stem + ".qmd").exists():
                continue
            zielordner = ziel / thema / ordner / (LOESUNGEN_ORDNER if ist_loesung else "")
            e = Eintrag(stem=stem, qmd=qmd if not ist_loesung else qmd.with_name(stem + ".qmd"), pdf=pdf,
                        ziel=zielordner / pdf.name, loesung=ist_loesung)
            e.fehlt = not pdf.exists()
            e.veraltet = (not e.fehlt) and pdf.stat().st_mtime < stand
            plan.eintraege.append(e)
    # New unit-owned diagnostics keep legacy destination paths explicitly in metadata.
    from material_core import lernstand
    for manifest in sorted(lernstand.manifests(repo)):
        if any(part in {"build", "kurse", ".git"} for part in manifest.relative_to(repo).parts):
            continue
        from ruamel.yaml import YAML
        unit = YAML(typ="safe").load(manifest.read_text(encoding="utf-8"))
        if not isinstance(unit, dict) or "lernstand" not in unit:
            continue
        data = lernstand.validate(unit["lernstand"], manifest.parent, repo)
        for item in data["materialien"]:
            if item["rolle"] != "foerdermaterial" or not item.get("online", False):
                continue
            if not item.get("online_pfad") and not alles:
                plan.uebersprungen.append(manifest.parent / Path(item["quelle"]).parent)
                continue
            for role in (["quelle", "loesung"] if loesungen and item.get("loesung_online", False) and "loesung" in item else ["quelle"]):
                source = lernstand.source_path(manifest.parent, item[role], repo)
                pdf = lernstand.pdf_path(source, repo)
                relative = Path(item.get("online_pfad", f"{data['id']}/{item['kompetenz']}/{item['stufe']}/{pdf.name}"))
                if role == "loesung":
                    relative = relative.parent / LOESUNGEN_ORDNER / pdf.name
                from material_core.builds import BuildService
                current = BuildService(repo, None).pdf_is_current(source)
                stand = max([source.stat().st_mtime, manifest.stat().st_mtime, *[p.stat().st_mtime for p in source.parent.glob('_metadata.yml')]])
                plan.eintraege.append(Eintrag(stem=source.stem, qmd=source, pdf=pdf, ziel=ziel / relative,
                    loesung=role == "loesung", fehlt=not pdf.exists(),
                    veraltet=pdf.exists() and (current is False or (current is None and pdf.stat().st_mtime < stand))))
    targets = {}
    for entry in plan.eintraege:
        if entry.ziel in targets and targets[entry.ziel] != entry.qmd:
            raise ValueError(f'Kollision im Online-Export: {entry.ziel} ({targets[entry.ziel]} und {entry.qmd})')
        targets[entry.ziel] = entry.qmd
    plan.uebersprungen = sorted(set(plan.uebersprungen))
    return plan


def kopiere(plan: Plan, *, trocken: bool = False) -> dict[str, list[Path]]:
    """Kopiert vorhandene PDFs. Unveränderte Dateien werden nicht angefasst."""
    ergebnis: dict[str, list[Path]] = {"kopiert": [], "unveraendert": [], "fehlend": []}
    for e in plan.eintraege:
        if e.fehlt:
            ergebnis["fehlend"].append(e.pdf)
            continue
        if e.ziel.exists() and filecmp.cmp(e.pdf, e.ziel, shallow=False):
            ergebnis["unveraendert"].append(e.ziel)
            continue
        if not trocken:
            e.ziel.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(e.pdf, e.ziel)
        ergebnis["kopiert"].append(e.ziel)
    return ergebnis


def aufraeumen(plan: Plan, ziel: Path, *, trocken: bool = False) -> list[Path]:
    """Löscht PDFs im Ziel, die nicht mehr zum Plan gehören (umbenannte oder gestrichene Blätter).

    Es werden nur .pdf-Dateien unterhalb der Themenordner des Plans gelöscht, nichts anderes."""
    erwartet = {e.ziel for e in plan.eintraege}
    themen = {e.ziel.relative_to(ziel).parts[0] for e in plan.eintraege}
    entfernt: list[Path] = []
    for thema in sorted(themen):
        for pdf in sorted((ziel / thema).rglob("*.pdf")):
            if pdf not in erwartet:
                if not trocken:
                    pdf.unlink()
                entfernt.append(pdf)
    return entfernt
