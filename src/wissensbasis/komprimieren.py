from __future__ import annotations

import collections
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pymupdf
import yaml

from .config import ROOT, Fach
from material_ui.plugins.ocr import engine

from .extract import EMPTY_PAGE_CHARS, OcrError, _ocr_page, cache_path, load_pages, ocr_language
from .notes import load_notes
from .scan import file_hash, save_manifest

TEMP_PREFIX = ".komprimiert-"
FINAL_STATUS = {
    "komprimiert", "nicht_lohnend", "klein", "aufloesung_niedrig", "keine_bilder", "qualitaet_nicht_bestanden", "fehler",
    "verschluesselt", "formular", "anhaenge",
}
WORD = re.compile(r"[a-zäöüß]{3,}")


@dataclass
class Profile:
    dpi: int
    qualitaet: float  # Ghostscript QFactor for JPEG: smaller means better quality
    beschreibung: str = ""


@dataclass
class Gates:
    max_mittlere_abweichung: float = 6.0
    min_korrelation: float = 0.98
    text_min_uebereinstimmung: float = 0.97
    ocr_min_uebereinstimmung: float = 0.60
    ocr_min_mittel: float = 0.85
    stichprobe_seiten: int = 5
    ocr_seiten: int = 3
    ocr_min_zeichen: int = 400  # pages with less text give too noisy OCR to judge a compression by


@dataclass
class Settings:
    mindestgroesse: int = 3_000_000
    mindest_ersparnis: float = 0.10
    profile: dict[str, Profile] = field(default_factory=dict)
    standard: dict[str, str] = field(default_factory=dict)
    fallback: str = "drucken"
    gates: Gates = field(default_factory=Gates)


DEFAULT_STANDARD = {
    "theorie": "lesen",
    "fachwissenschaft": "lesen",
    "populaer": "lesen",
    "zeitschrift": "drucken",
    "unterrichtsmaterial": "drucken",
    "schulbuch": "drucken",
    "aufgabensammlung": "drucken",
}
DEFAULT_PROFILES = {
    "lesen": Profile(150, 0.7, "Bücher und Aufsätze, die am Bildschirm gelesen werden"),
    "drucken": Profile(200, 0.4, "Übungen und Kopiervorlagen, gedacht für den Ausdruck auf DIN A4"),
}


def load_settings(fach: Fach) -> Settings:
    raw = {}
    if fach.quellenarten.exists():
        raw = (yaml.safe_load(fach.quellenarten.read_text(encoding="utf-8")) or {}).get("komprimierung") or {}
    profiles = dict(DEFAULT_PROFILES)
    for name, values in (raw.get("profile") or {}).items():
        profiles[name] = Profile(int(values["dpi"]), float(values["qualitaet"]), str(values.get("beschreibung", "")))
    gates = Gates(**(raw.get("qualitaet") or {}))
    return Settings(
        mindestgroesse=int(float(raw.get("mindestgroesse_mb", 3)) * 1_000_000),
        mindest_ersparnis=float(raw.get("mindest_ersparnis", 0.10)),
        profile=profiles,
        standard={**DEFAULT_STANDARD, **(raw.get("standard") or {})},
        fallback=str(raw.get("fallback", "drucken")),
        gates=gates,
    )


def profile_name(doc: dict, settings: Settings) -> str:
    """Rule-level `profil` wins, then the default for the Quellenart, then the fallback (higher quality)."""
    name = (doc.get("meta") or {}).get("profil") or settings.standard.get(doc["quellenart"]) or settings.fallback
    if name not in settings.profile:
        raise SystemExit(f"Unbekanntes Komprimierungsprofil '{name}' bei {doc['pfad']}")
    return name


A4_BREITE_ZOLL = 8.2677  # 210 mm


def _pixel_mediabox_ppi(path: Path) -> float | None:
    """Manche Scan-Exporte setzen die Page-MediaBox auf die Pixelmaße des Bilds (1 pt == 1 px) statt
    auf echte Punkte. Dadurch meldet pdfimages faelschlich ~72 dpi fuer tatsaechlich hochaufgeloeste
    Scans. Das Muster erkennen (MediaBox-Breite == Bildbreite in Pixeln) und die ppi stattdessen gegen
    eine angenommene A4-Seite berechnen."""
    try:
        with pymupdf.open(path) as document:
            page = document[0]
            images = page.get_images()
            if not images:
                return None
            breite_px = images[0][2]
            if abs(page.mediabox.width - breite_px) > 1.0:
                return None
            return breite_px / A4_BREITE_ZOLL
    except Exception:  # noqa: BLE001 - fällt auf die normale pdfimages-Auswertung zurück
        return None


def image_ppi(path: Path) -> float | None:
    """Highest image resolution in the PDF (pdfimages -list), None if there are no raster images."""
    try:
        result = subprocess.run(["pdfimages", "-list", str(path)], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    values = []
    for line in result.stdout.splitlines()[2:]:
        parts = line.split()
        if len(parts) > 13 and parts[2] == "image":
            try:
                values.append(float(parts[12]))
            except ValueError:
                continue
    if not values:
        return None
    pixel_mediabox_ppi = _pixel_mediabox_ppi(path)
    if pixel_mediabox_ppi is not None:
        return max(max(values), pixel_mediabox_ppi)
    return max(values)


def special_features(path: Path) -> str | None:
    """Features Ghostscript would silently drop (form fields, attachments) or cannot open (passwords)."""
    try:
        with pymupdf.open(path) as document:
            if document.needs_pass or document.is_encrypted:
                return "verschluesselt"
            if document.is_form_pdf:
                return "formular"
            if document.embfile_count():
                return "anhaenge"
    except Exception:  # noqa: BLE001 - unreadable files are handled by the quality gates and the OCR status
        return None
    return None


def skip_reason(doc: dict, settings: Settings, profile: Profile) -> str | None:
    if doc["format"] != "pdf":
        return "kein_pdf"
    if (doc.get("text") or {}).get("status") == "needs_ocr":
        return "erst_ocr"
    if doc["groesse"] < settings.mindestgroesse:
        return "klein"
    feature = special_features(ROOT / doc["pfad"])
    if feature:
        return feature
    ppi = image_ppi(ROOT / doc["pfad"])
    if ppi is None:
        return "keine_bilder"
    if ppi < profile.dpi * 1.2:
        return "aufloesung_niedrig"
    return None


def ghostscript(src: Path, dst: Path, profile: Profile) -> None:
    engine.shrink_pdf(src, dst, dpi=profile.dpi, qfactor=profile.qualitaet)


# ------------------------------------------------------------------ quality gates

def spread(count: int, wanted: int) -> list[int]:
    if count <= wanted:
        return list(range(count))
    return sorted({round(step * (count - 1) / (wanted - 1)) for step in range(wanted)})


def _gray(document, index: int, dpi: int = 100, block: int = 4) -> np.ndarray:
    """Page as a small grayscale array (about 25 dpi). Box-filtering here keeps the result independent of how the
    renderer resamples images of different resolution; faithful copies then correlate at 0.998, different pages at 0.1."""
    pixmap = document[index].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    array = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width).astype(np.float32)
    height, width = (array.shape[0] // block) * block, (array.shape[1] // block) * block
    return array[:height, :width].reshape(height // block, block, width // block, block).mean(axis=(1, 3))


def visual_similarity(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Return (mean absolute difference, correlation). Blank pages count as correlated when both are blank."""
    if a.shape != b.shape:
        return 255.0, 0.0
    mean_diff = float(np.abs(a - b).mean())
    if a.std() < 1.0 and b.std() < 1.0:
        return mean_diff, 1.0
    if a.std() < 1.0 or b.std() < 1.0:
        return mean_diff, 0.0
    return mean_diff, float(np.corrcoef(a.ravel(), b.ravel())[0, 1])


def word_overlap(reference: str, other: str) -> float:
    """Share of the reference words (letters only, 3+ characters) that also occur in `other`."""
    ref = collections.Counter(WORD.findall(reference.lower()))
    if not ref:
        return 1.0
    return sum((ref & collections.Counter(WORD.findall(other.lower()))).values()) / sum(ref.values())


def quality_report(
    original: Path, candidate: Path, cached_pages: list[dict], gates: Gates, language: str = "deu"
) -> tuple[list[str], dict]:
    """Compare the compressed candidate against the original. Returns (failures, metrics)."""
    failures: list[str] = []
    metrics: dict = {}
    if shutil.which("qpdf"):
        check = subprocess.run(["qpdf", "--check", str(candidate)], capture_output=True, timeout=300)
        if check.returncode not in (0, 3):
            failures.append("qpdf --check meldet Fehler")
    try:
        old, new = pymupdf.open(original), pymupdf.open(candidate)
    except Exception as error:  # noqa: BLE001
        return [f"PDF nicht lesbar: {error}"], metrics
    with old, new:
        if len(old) != len(new):
            return [f"Seitenzahl {len(old)} -> {len(new)}"], metrics
        try:
            failures += _compare(old, new, candidate, cached_pages, gates, metrics, language)
        except Exception as error:  # noqa: BLE001 - if the comparison itself breaks, the original must stay
            failures.append(f"Vergleich nicht möglich: {type(error).__name__}: {error}")
    return failures, metrics


def _compare(old, new, candidate: Path, cached_pages: list[dict], gates: Gates, metrics: dict, language: str) -> list[str]:
    failures: list[str] = []
    for index in range(len(old)):
        a, b = old[index].rect, new[index].rect
        if abs(a.width - b.width) > 1 or abs(a.height - b.height) > 1:
            failures.append(f"Seitengröße auf Seite {index + 1} geändert")
            break
    if [entry[1].strip() for entry in old.get_toc()] != [entry[1].strip() for entry in new.get_toc()]:
        failures.append("Inhaltsverzeichnis (Lesezeichen) weicht ab")

    text_scores = []
    for index in spread(len(old), 12):
        original_text = old[index].get_text()
        if len(original_text.strip()) >= 200:
            text_scores.append(word_overlap(original_text, new[index].get_text()))
    if text_scores:
        metrics["textlayer_uebereinstimmung"] = round(min(text_scores), 4)
        if min(text_scores) < gates.text_min_uebereinstimmung:
            failures.append(f"Textschicht weicht ab ({min(text_scores):.3f})")

    ocr_scores = []
    for index in spread(len(old), 30):
        if len(ocr_scores) >= gates.ocr_seiten:
            break
        has_layer = len(old[index].get_text().strip()) >= EMPTY_PAGE_CHARS
        cached = next((page["t"] for page in cached_pages if page["p"] == index + 1), "")
        if not has_layer and len(cached.strip()) >= gates.ocr_min_zeichen:
            try:
                recognised = _ocr_page(candidate, index + 1, language=language)
            except OcrError:
                recognised = ""
            ocr_scores.append(word_overlap(cached, recognised))
    if ocr_scores:
        mean = sum(ocr_scores) / len(ocr_scores)
        metrics.update(ocr_uebereinstimmung_min=round(min(ocr_scores), 3), ocr_uebereinstimmung_mittel=round(mean, 3))
        if min(ocr_scores) < gates.ocr_min_uebereinstimmung or mean < gates.ocr_min_mittel:
            failures.append(f"OCR-Vergleich zu schwach (min {min(ocr_scores):.2f}, Mittel {mean:.2f})")

    # Without any text evidence (drawings, photos) the visual comparison has to carry the decision: look at more pages.
    evidence = bool(text_scores or ocr_scores)
    sample = spread(len(old), gates.stichprobe_seiten if evidence else 3 * gates.stichprobe_seiten)
    metrics["textbeleg"] = evidence
    worst_diff, worst_corr = 0.0, 1.0
    for index in sample:
        diff, corr = visual_similarity(_gray(old, index), _gray(new, index))
        worst_diff, worst_corr = max(worst_diff, diff), min(worst_corr, corr)
    metrics.update(sicht_abweichung=round(worst_diff, 2), sicht_korrelation=round(worst_corr, 4))
    if worst_diff > gates.max_mittlere_abweichung or worst_corr < gates.min_korrelation:
        failures.append(f"Sichtvergleich: Abweichung {worst_diff:.1f}, Korrelation {worst_corr:.3f}")
    return failures


# ------------------------------------------------------------------ hash migration

def _rewrite_note_hashes(fach: Fach, doc_id: str, old: str, new: str) -> int:
    changed = 0
    for note in load_notes(fach):
        if note.dok == doc_id and note.path is not None:
            text = note.path.read_text(encoding="utf-8")
            if old in text:
                note.path.write_text(text.replace(old, new), encoding="utf-8")
                changed += 1
    return changed


def _finalize(fach: Fach, manifest: dict, doc: dict, old: str, new: str, log=print) -> None:
    """Point notes, text cache and manifest to the new hash (the compressed file is already in place)."""
    _rewrite_note_hashes(fach, doc["id"], old, new)
    if not cache_path(new).exists() and cache_path(old).exists():
        shutil.copy2(cache_path(old), cache_path(new))
    still_used = any(other is not doc and other["sha256"] == old for other in manifest["dokumente"])
    if not still_used:
        cache_path(old).unlink(missing_ok=True)
    stat = (ROOT / doc["pfad"]).stat()
    info = doc["komprimierung"]
    doc.update(sha256=new, groesse=stat.st_size, mtime_ns=stat.st_mtime_ns)
    info.update(status="komprimiert", nachher_bytes=stat.st_size)
    info.pop("neu_sha256", None)
    save_manifest(fach, manifest)


def relink(fach: Fach, manifest: dict, log=print) -> None:
    """A restored original has a new hash: move text cache and note hashes over from the compressed version."""
    for doc in manifest["dokumente"]:
        link = doc.pop("_relink", None)
        if not link:
            continue
        old, new = link["alt_sha256"], doc["sha256"]
        if not cache_path(new).exists() and cache_path(old).exists():
            shutil.copy2(cache_path(old), cache_path(new))
        _rewrite_note_hashes(fach, doc["id"], old, new)
        if not any(other["sha256"] == old for other in manifest["dokumente"]):
            cache_path(old).unlink(missing_ok=True)
        log(f"[{fach.name}] Original wiedererkannt: {doc['pfad']} (Text und Karten bleiben erhalten)")


def recover(fach: Fach, manifest: dict, log=print) -> None:
    """Finish or roll back a compression that was interrupted between replacing the file and updating the manifest."""
    for leftover in fach.quellen.rglob(f"{TEMP_PREFIX}*"):
        leftover.unlink(missing_ok=True)
    for doc in manifest["dokumente"]:
        info = doc.get("komprimierung") or {}
        if info.get("status") != "ausstehend":
            continue
        if not (ROOT / doc["pfad"]).exists():
            continue
        current = file_hash(ROOT / doc["pfad"])
        if current == info["neu_sha256"]:
            log(f"[{fach.name}] Komprimierung von {doc['pfad']} wird abgeschlossen")
            _finalize(fach, manifest, doc, doc["sha256"], current, log)
        elif current == doc["sha256"]:
            cache_path(info["neu_sha256"]).unlink(missing_ok=True)
            doc.pop("komprimierung")
            save_manifest(fach, manifest)
        else:
            info["status"] = "unklar"
            save_manifest(fach, manifest)
            log(f"[{fach.name}] WARNUNG: {doc['pfad']} passt weder zum alten noch zum neuen Hash")


# ------------------------------------------------------------------ driver

def compress_document(
    fach: Fach, manifest: dict, doc: dict, settings: Settings, dry_run: bool = False, log=print
) -> tuple[str, dict]:
    """Return (result, info). info holds sizes and profile; in a dry run nothing is written to the manifest."""
    name = profile_name(doc, settings)
    profile = settings.profile[name]
    reason = skip_reason(doc, settings, profile)
    if reason:
        if reason != "erst_ocr" and not dry_run:
            doc["komprimierung"] = {"status": reason, "profil": name}
        return reason, {}
    source = ROOT / doc["pfad"]
    temporary = _temporary(source)
    repaired: Path | None = None
    try:
        before = source.stat().st_size
        cached = load_pages(doc["sha256"])

        def evaluate(start: Path) -> tuple[int, list[str], dict]:
            ghostscript(start, temporary, profile)
            after = temporary.stat().st_size
            if after > before * (1 - settings.mindest_ersparnis):
                return after, [], {}
            return (after, *quality_report(source, temporary, cached, settings.gates, ocr_language(doc)))

        after, failures, metrics = evaluate(source)
        if failures and any(reason.startswith("Seitenzahl") for reason in failures):
            # Ghostscript loses pages on structurally damaged PDFs; qpdf rewrites them first.
            repaired = _repair(source)
            if repaired is not None:
                log(f"    Seitenzahl weicht ab, neuer Versuch mit reparierter Fassung: {source.name}")
                after, failures, metrics = evaluate(repaired)
        if after > before * (1 - settings.mindest_ersparnis):
            if not dry_run:
                doc["komprimierung"] = {"status": "nicht_lohnend", "profil": name, "vorher_bytes": before, "nachher_bytes": after}
            return "nicht_lohnend", {}
        info = {"profil": name, "dpi": profile.dpi, "vorher_bytes": before, "nachher_bytes": after,
                "vorher_sha256": doc["sha256"], "kennzahlen": metrics}
        if failures:
            if not dry_run:
                doc["komprimierung"] = {**info, "status": "qualitaet_nicht_bestanden", "gruende": failures}
            log(f"    Qualität nicht bestanden, Original bleibt: {'; '.join(failures)}")
            return "qualitaet_nicht_bestanden", info
        if dry_run:
            return "trocken_ok", info
        old, new = doc["sha256"], file_hash(temporary)
        if not cache_path(new).exists() and cache_path(old).exists():
            shutil.copy2(cache_path(old), cache_path(new))
        doc["komprimierung"] = {**info, "status": "ausstehend", "neu_sha256": new}
        save_manifest(fach, manifest)
        os.replace(temporary, source)  # the original is gone from here on
        _finalize(fach, manifest, doc, old, new, log)
        return "komprimiert", info
    finally:
        temporary.unlink(missing_ok=True)
        if repaired is not None:
            repaired.unlink(missing_ok=True)


def _temporary(source: Path, kind: str = "") -> Path:
    """Versteckte Zwischendatei neben der Quelle.

    Sie muss auf `.pdf` enden: Ubuntus AppArmor-Profil erlaubt qpdf nur solche Dateien.
    """
    return source.with_name(f"{TEMP_PREFIX}{kind}{source.stem}.tmp.pdf")


def _repair(source: Path) -> Path | None:
    if not shutil.which("qpdf"):
        return None
    target = _temporary(source, "repariert-")
    result = subprocess.run(["qpdf", str(source), str(target)], capture_output=True, timeout=600)
    if result.returncode in (0, 3) and target.exists():  # 3 = repaired with warnings
        return target
    target.unlink(missing_ok=True)
    return None


def run(fach: Fach, manifest: dict, match: str | None = None, limit: int | None = None,
        dry_run: bool = False, again: bool = False, log=print) -> dict[str, int]:
    """Compress every eligible PDF of one subject; OCR must be finished first (documents waiting for OCR are skipped)."""
    settings = load_settings(fach)
    recover(fach, manifest, log)
    counts: dict[str, int] = collections.Counter()
    saved = 0
    todo = [
        doc for doc in manifest["dokumente"]
        if doc["format"] == "pdf" and not doc.get("duplikat_von")
        and (match is None or match.lower() in doc["pfad"].lower())
        and (again or (doc.get("komprimierung") or {}).get("status") not in FINAL_STATUS)
    ]
    done = 0
    for doc in todo:
        if limit is not None and done >= limit:
            break
        try:
            result, info = compress_document(fach, manifest, doc, settings, dry_run, log)
        except Exception as error:  # noqa: BLE001 - one broken PDF must not stop the run over the other 100
            if (doc.get("komprimierung") or {}).get("status") == "ausstehend":
                raise  # the file was already replaced: keep the journal entry so the next run can finish the migration
            result, info = "fehler", {}
            if not dry_run:
                doc["komprimierung"] = {"status": "fehler", "meldung": str(error)[:300]}
            log(f"    Fehler bei {doc['pfad']}: {type(error).__name__}: {error}")
        counts[result] += 1
        if result in {"komprimiert", "trocken_ok"}:
            done += 1
            saved += info["vorher_bytes"] - info["nachher_bytes"]
            log(f"[{fach.name}] {result}: {Path(doc['pfad']).name}: {info['vorher_bytes'] / 1e6:.1f} -> "
                f"{info['nachher_bytes'] / 1e6:.1f} MB (Profil {info['profil']}, {info['dpi']} dpi) {info['kennzahlen']}")
        if not dry_run:
            save_manifest(fach, manifest)
    counts["gespart_mb"] = round(saved / 1e6)
    return dict(counts)
