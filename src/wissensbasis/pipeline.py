from __future__ import annotations

import fcntl
from collections import Counter
from dataclasses import dataclass
from contextlib import contextmanager

from . import assets, index, komprimieren, ordnung, pages
from .config import CACHE, Fach, discover
from .extract import OCR_FORMATS, extract_missing, load_pages, needs_ocr_language_refresh, ocr_document
from .notes import check, load_notes, release_clean
from .scan import load_manifest, save_manifest, scan


QUELLENARTEN_TEMPLATE = """# Ordnet Pfade unterhalb von {folder}/ einer Quellenart zu (längster Pfadpräfix gewinnt).
# Ein _meta.yaml direkt in einem Quellenordner überschreibt diese Angaben für alles darunter.
# Quellenarten: theorie, zeitschrift, schulbuch, aufgabensammlung, unterrichtsmaterial, fachwissenschaft, populaer, web
regeln: []
#  - pfad: web            # Lesekopien von Webseiten (invoke wissen-web <url>)
#    quellenart: web
#  - pfad: unterordner
#    quellenart: theorie
#    profil: lesen        # Komprimierung: lesen (150 dpi) oder drucken (200 dpi), Standard nach Quellenart
"""

TAXONOMIE_TEMPLATE = """# Kontrolliertes Vokabular für Dossiers und Karten. Von Hand ergänzen und freigeben.
status: entwurf
typen:
  grundvorstellung: {label: Grundvorstellung}
  fehler: {label: Typischer Fehler / Fehlvorstellung}
  aufgabenformat: {label: Aufgabenformat}
  unterrichtsidee: {label: Unterrichtsidee}
  prinzip: {label: Didaktisches Prinzip}
  befund: {label: Befund}
  methode: {label: Methode / Vorgehen}
  kriterium: {label: Prüfkriterium}
belegarten:
  empirisch: {label: "Empirische Studie"}
  theoretisch: {label: "Theoretische Herleitung / Literaturüberblick"}
  praxis: {label: "Praxisvorschlag / Erfahrungswissen"}
themen: {}
kompetenzen: {}
prinzipien: {}
"""


@contextmanager
def exclusive_run():
    """Only one writing run at a time: two runs would overwrite each other's manifest and caches."""
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / "lauf.lock").open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Es läuft bereits ein Lauf (wissen-update, -ocr oder -komprimieren). Bitte abwarten.") from None
        yield


def _ensure_config(fach: Fach, log) -> None:
    fach.quellenarten.parent.mkdir(parents=True, exist_ok=True)
    for path, template in ((fach.quellenarten, QUELLENARTEN_TEMPLATE.format(folder=fach.quellen.name)),
                           (fach.taxonomie, TAXONOMIE_TEMPLATE)):
        if not path.exists():
            path.write_text(template, encoding="utf-8")
            log(f"[{fach.name}] {path.relative_to(fach.wissen.parent.parent)} als Vorlage angelegt")


def update(only: str | None = None, reindex: bool = True, ocr_all: bool = False, compress: bool = False,
           extract_images: bool = False,
           log=print) -> None:
    """Scan, extract, optionally OCR and then compress (in this order), finally refresh the search index."""
    with exclusive_run():
        _update(only, reindex, ocr_all, compress, extract_images, log)


def _update(only, reindex, ocr_all, compress, extract_images, log) -> None:
    if reindex and only is None:
        index.purge_missing([fach.name for fach in discover()])
    for fach in discover(only):
        _ensure_config(fach, log)
        log(f"[{fach.name}] Scan von {fach.quellen.name}/ …")
        previous = load_manifest(fach)
        komprimieren.recover(fach, previous, log)
        manifest, changes = scan(fach, previous)
        komprimieren.relink(fach, manifest, log)
        counts = extract_missing(manifest["dokumente"])
        if extract_images:
            counts.update({f"asset_{key}": value for key, value in assets.extract_missing(fach, manifest).items()})
        save_manifest(fach, manifest)
        if ocr_all:
            ocr_pending(fach, manifest, log=log)
        if compress:
            counts.update({f"kompr_{key}": value for key, value in komprimieren.run(fach, manifest, log=log).items()})
        save_manifest(fach, manifest)
        if reindex:
            counts.update({f"index_{key}": value for key, value in index.sync(fach, manifest).items()})
        log(report(fach, manifest, changes, counts))


def report(fach: Fach, manifest: dict, changes: dict | None = None, counts: dict | None = None) -> str:
    docs = manifest["dokumente"]
    lines = [f"[{fach.name}] {len(docs)} Dokumente in {manifest['quellenordner']}/"]
    if changes:
        lines.append("  Änderungen: " + ", ".join(f"{key} {len(value)}" for key, value in changes.items()))
        for key in ("geaendert", "verschoben", "wiederhergestellt", "entfernt"):
            lines += [f"    {key}: {entry}" for entry in changes[key][:10]]
    if counts:
        lines.append("  Lauf: " + ", ".join(f"{key} {value}" for key, value in counts.items()))
    status = Counter((doc.get("text") or {}).get("status", "offen") for doc in docs)
    lines.append("  Text: " + ", ".join(f"{key} {value}" for key, value in sorted(status.items())))
    formats = Counter(doc["format"] for doc in docs)
    lines.append("  Formate: " + ", ".join(f"{key} {value}" for key, value in formats.most_common()))
    arten = Counter(doc["quellenart"] for doc in docs)
    lines.append("  Quellenarten: " + ", ".join(f"{key} {value}" for key, value in arten.most_common()))
    unclassified = [doc["pfad"] for doc in docs if doc["quellenart"] == "unklassifiziert"]
    if unclassified:
        lines.append(f"  Unklassifiziert ({len(unclassified)}), in quellenarten.yaml eintragen, z. B.:")
        lines += [f"    {path}" for path in unclassified[:5]]
    duplicates = [doc for doc in docs if doc.get("duplikat_von")]
    if duplicates:
        by_id = {doc["id"]: doc for doc in docs}
        lines.append(f"  Duplikate ({len(duplicates)}, werden nicht doppelt verarbeitet):")
        lines += [f"    {doc['pfad']} = {by_id[doc['duplikat_von']]['pfad']}" for doc in duplicates[:8]]
    compression = Counter((doc.get("komprimierung") or {}).get("status", "offen") for doc in docs if doc["format"] == "pdf")
    saved = sum(
        doc["komprimierung"]["vorher_bytes"] - doc["komprimierung"]["nachher_bytes"]
        for doc in docs if (doc.get("komprimierung") or {}).get("status") == "komprimiert"
    )
    lines.append("  Komprimierung: " + ", ".join(f"{key} {value}" for key, value in sorted(compression.items()))
                 + f" (gespart {saved / 1e6:.0f} MB)")
    dossiers = {note.dok: note for note in load_notes(fach) if note.art == "dossier"}
    readable = [doc for doc in docs if (doc.get("text") or {}).get("status") in {"ok", "needs_ocr"}]
    stale = [doc for doc in readable if doc["id"] in dossiers and dossiers[doc["id"]].meta.get("hash") != doc["sha256"]]
    lines.append(
        f"  Erschließung: {sum(1 for doc in readable if doc['id'] in dossiers)}/{len(readable)} mit Dossier"
        + (f", {len(stale)} veraltet" if stale else "")
    )
    return "\n".join(lines)


def status(only: str | None = None, log=print) -> None:
    for fach in discover(only):
        log(report(fach, load_manifest(fach)))


def ocr_pending(fach: Fach, manifest: dict, match: str | None = None, limit: int | None = None, log=print) -> int:
    """OCR the documents of one subject that are flagged needs_ocr; returns how many are still open."""
    todo = [
        doc for doc in manifest["dokumente"]
        if doc["format"] in OCR_FORMATS
        and ((doc.get("text") or {}).get("status") == "needs_ocr" or needs_ocr_language_refresh(doc))
        and (match is None or match.lower() in doc["pfad"].lower())
    ]
    selected = todo[:limit]
    for number, doc in enumerate(selected, start=1):
        reason = "Sprache geändert" if needs_ocr_language_refresh(doc) else "ohne Text"
        log(f"[{fach.name}] OCR {number}/{len(selected)} ({reason}): {doc['pfad']}")
        try:
            ocr_document(doc, log=log)
        except Exception as error:  # noqa: BLE001 - one broken document must not stop the run over the others
            log(f"    OCR-Fehler bei {doc['pfad']}: {type(error).__name__}: {error}")
            doc["text"] = {**(doc.get("text") or {}), "ocr_meldung": f"{type(error).__name__}: {error}"[:200]}
        save_manifest(fach, manifest)
    return len(todo) - len(selected)


def ocr(only: str | None = None, match: str | None = None, limit: int | None = None, log=print) -> None:
    """OCR documents flagged needs_ocr (optionally only those whose path contains `match`)."""
    with exclusive_run():
        for fach in discover(only):
            manifest = load_manifest(fach)
            remaining = ocr_pending(fach, manifest, match, limit, log)
            index.sync(fach, manifest)
            log(f"[{fach.name}] OCR fertig, noch offen: {remaining}")


def compress(only: str | None = None, match: str | None = None, limit: int | None = None,
             dry_run: bool = False, again: bool = False, log=print) -> None:
    """Shrink PDFs after OCR, verify quality, replace the original and migrate the hash everywhere."""
    with exclusive_run():
        for fach in discover(only):
            manifest = load_manifest(fach)
            counts = komprimieren.run(fach, manifest, match, limit, dry_run, again, log)
            if not dry_run:
                index.sync(fach, manifest)
            log(f"[{fach.name}] Komprimierung{' (Trockenlauf)' if dry_run else ''}: "
                + ", ".join(f"{key} {value}" for key, value in counts.items()))


def images(only: str | None = None, match: str | None = None, overwrite: bool = False, log=print) -> None:
    """Extract embedded PDF images into wissen/<fach>/bilder/<quelle>/."""
    with exclusive_run():
        for fach in discover(only):
            manifest = load_manifest(fach)
            counts = assets.extract_missing(fach, manifest, match, overwrite, log)
            log(f"[{fach.name}] Bildextraktion: " + ", ".join(f"{key} {value}" for key, value in counts.items()))


def find_document(query: str, only: str | None = None) -> tuple[Fach, dict]:
    matches = []
    for fach in discover(only):
        for doc in load_manifest(fach)["dokumente"]:
            if query == doc["id"] or query.lower() in doc["pfad"].lower():
                matches.append((fach, doc))
    exact = [match for match in matches if match[1]["id"] == query]
    matches = exact or matches
    if len(matches) != 1:
        listing = "\n".join(f"  {doc['id']}  {doc['pfad']}" for _, doc in matches[:15])
        raise SystemExit(f"{len(matches)} Treffer für '{query}':\n{listing}" if matches else f"Kein Dokument für '{query}'")
    return matches[0]


def read(query: str, start: int = 1, end: int | None = None, only: str | None = None, log=print) -> None:
    fach, doc = find_document(query, only)
    document_pages = load_pages(doc["sha256"])
    end = end or start
    unit = (doc.get("text") or {}).get("einheit", "seite")
    label = {"seite": "Seite", "abschnitt": "Abschnitt", "folie": "Folie", "bild": "Bild"}.get(unit, unit.capitalize())
    log(f"# {doc['pfad']}  (id: {doc['id']}, {len(document_pages)} Einheiten, Fach {fach.name})")
    for page in document_pages[start - 1:end]:
        log(f"\n--- {label} {page['p']} ---\n{page['t']}")


@dataclass(frozen=True)
class SubjectCheck:
    fach: Fach
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CheckReport:
    subjects: tuple[SubjectCheck, ...]

    @property
    def error_count(self) -> int:
        return sum(len(subject.errors) for subject in self.subjects)


def inspect_all(only: str | None = None) -> CheckReport:
    subjects = []
    for fach in discover(only):
        errors, warnings = check(fach)
        warnings = [*warnings, *ordnung.Ordnung(fach).regel_warnungen()]
        subjects.append(SubjectCheck(fach, tuple(errors), tuple(warnings)))
    return CheckReport(tuple(subjects))


def print_check_report(report: CheckReport, log=print) -> None:
    for subject in report.subjects:
        for message in subject.warnings:
            log(f"Warnung  {message}")
        for message in subject.errors:
            log(f"FEHLER   {message}")
        log(f"[{subject.fach.name}] {len(subject.errors)} Fehler, {len(subject.warnings)} Warnungen")


def check_all(only: str | None = None, log=print) -> int:
    report = inspect_all(only)
    print_check_report(report, log)
    return report.error_count


def apply_checks(only: str | None = None, *, admit: bool = False, release: bool = False,
                 sort: bool = False, log=print) -> int:
    with exclusive_run():
        report = inspect_all(only)
        print_check_report(report, log)
        for subject in report.subjects:
            fach = subject.fach
            if admit:
                ordnung.aufnehmen(fach, list(subject.errors), log)
            if release:
                for name in release_clean(fach, list(subject.errors)):
                    log(f"[{fach.name}] freigegeben: {name}")
            if sort:
                moves = ordnung.sortieren(fach, log=log)
                if moves:
                    log(f"[{fach.name}] {len(moves)} Karten einsortiert")
        return report.error_count


def maintain_all(only: str | None = None, log=print) -> int:
    return apply_checks(only, admit=True, release=True, sort=True, log=log)


def sort_all(only: str | None = None, dry_run: bool = False, log=print) -> None:
    with exclusive_run():
        for fach in discover(only):
            moves = ordnung.sortieren(fach, dry_run, log)
            for source, target in moves:
                log(f"  {source.relative_to(fach.karten)} -> {target.relative_to(fach.karten)}")
            log(f"[{fach.name}] {len(moves)} Karten {'würden einsortiert' if dry_run else 'einsortiert'}")


def select(query: str, only: str | None = None, zweck: str | None = None, klasse: int | None = None,
           anzahl: int = 10, log=print) -> None:
    """Die wichtigsten Karten zu einem Thema: erst die Leitquellen, dann die übrigen nach Punkten."""
    for fach in discover(only):
        order = ordnung.Ordnung(fach)
        themen = order.themen_zu(query)
        pflicht, rest = order.auswahl(themen, zweck, klasse)
        log(f"# {fach.name}: {', '.join(sorted(themen))}" + (f" · Zweck {zweck}" if zweck else "")
            + (f" · Klasse {klasse}" if klasse else "") + f" · {len(pflicht) + len(rest)} Karten")
        for title, hits in (("Immer berücksichtigen (Leitquellen)", pflicht), (f"Wichtigste weitere Karten (Top {anzahl})", rest[:anzahl])):
            if not hits:
                continue
            log(f"\n## {title}")
            for lead in dict.fromkeys(reason for hit in hits for reason in hit.gruende if reason.startswith("Leitquelle")):
                log(f"   {lead}")
            for hit in hits:
                card = hit.card
                other = [reason for reason in hit.gruende if not reason.startswith("Leitquelle")]
                reasons = f" – {'; '.join(other)}" if other else ""
                log(f"[P{order.stufe(card)} · {hit.punkte:>2}] {card.titel} ({card.meta.get('typ')}, {card.meta.get('belegart')}){reasons}\n"
                    f"    {card.meta.get('kern')}\n    {card.path.relative_to(fach.wissen.parent.parent).as_posix()}")


def build_all(only: str | None = None, log=print) -> None:
    for fach in discover(only):
        counts = pages.build(fach)
        log(f"[{fach.name}] Seiten erzeugt: " + ", ".join(f"{key} {len(value)}" for key, value in counts.items()))
