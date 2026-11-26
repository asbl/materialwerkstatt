from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pymupdf
import pytest

from conftest import make_scan_pdf, needs_tools

from wissensbasis import komprimieren, pipeline
from wissensbasis.config import Fach
from wissensbasis.extract import cache_path, load_pages
from wissensbasis.komprimieren import Profile, image_ppi, spread, visual_similarity, word_overlap
from wissensbasis.notes import read_note
from wissensbasis.scan import file_hash, load_manifest

FACH = Fach("testfach")


def doc_of(name: str) -> dict:
    return next(doc for doc in load_manifest(FACH)["dokumente"] if doc["pfad"].endswith(name))


def write_notes(doc_id: str, sha: str) -> tuple[Path, Path]:
    dossier = FACH.dossiers / f"{doc_id}.md"
    card = FACH.karten / doc_id / "01-karte.md"
    dossier.parent.mkdir(parents=True, exist_ok=True)
    card.parent.mkdir(parents=True, exist_ok=True)
    dossier.write_text(f"---\ntitel: Test\nquelle: {doc_id}\nhash: {sha}\nthemen: [x]\n---\n\nText\n", encoding="utf-8")
    card.write_text(f"---\ntitel: Karte\nquelle: {doc_id}\nquelle_hash: {sha}\nseite: 1\n---\n\nText\n", encoding="utf-8")
    return dossier, card


def fresh(project) -> Path:
    path = project / "quellen-testfach" / "buecher" / "scan.pdf"
    make_scan_pdf(path)
    pipeline.update("testfach")
    return path


# ---------------------------------------------------------------- unit tests of the measures

def test_spread_covers_first_and_last_page():
    assert spread(3, 5) == [0, 1, 2]
    assert spread(100, 5)[0] == 0 and spread(100, 5)[-1] == 99 and len(spread(100, 5)) == 5


def test_visual_similarity_detects_blank_and_shifted_pages():
    page = np.full((100, 70), 255.0, dtype=np.float32)
    page[20:30, 10:60] = 0
    assert visual_similarity(page, page.copy())[1] > 0.99
    blank = np.full_like(page, 255.0)
    assert visual_similarity(page, blank)[1] < 0.5
    assert visual_similarity(blank, blank.copy())[1] == 1.0
    shifted = np.roll(page, 30, axis=0)
    assert visual_similarity(page, shifted)[1] < 0.95


def test_word_overlap_ignores_noise_but_notices_lost_words():
    text = "Grundvorstellungen zu Bruchzahlen entstehen durch Handeln"
    assert word_overlap(text, text.upper()) == 1.0
    assert word_overlap(text, "Grundvorstellungen zu ,, ## Handeln") == pytest.approx(0.4, abs=0.01)
    assert word_overlap(text, "völlig anderer Inhalt hier") == 0.0


# ---------------------------------------------------------------- pipeline: OCR first, then compress

@needs_tools
def test_ocr_then_compress_replaces_original_and_migrates_hash(project):
    path = fresh(project)
    doc = doc_of("scan.pdf")
    assert doc["text"]["status"] == "needs_ocr"
    old_sha, old_size = doc["sha256"], path.stat().st_size
    dossier, card = write_notes(doc["id"], old_sha)

    pipeline.update("testfach", ocr_all=True, compress=True)

    doc = doc_of("scan.pdf")
    new_sha = file_hash(path)
    assert new_sha != old_sha
    assert doc["sha256"] == new_sha, "manifest points to the compressed file"
    assert doc["groesse"] == path.stat().st_size < old_size * 0.7
    assert doc["komprimierung"]["status"] == "komprimiert"
    assert doc["komprimierung"]["profil"] == "lesen" and doc["komprimierung"]["dpi"] == 150
    assert doc["komprimierung"]["vorher_sha256"] == old_sha
    assert doc["text"]["status"] == "ok" and doc["text"]["ocr_seiten"] == 3
    # notes follow the file
    assert read_note(dossier)[0]["hash"] == new_sha
    assert read_note(card)[0]["quelle_hash"] == new_sha
    # the OCR text survived the move to the new hash, the old cache is gone
    assert cache_path(new_sha).exists() and not cache_path(old_sha).exists()
    assert "Grundvorstellungen" in " ".join(page["t"] for page in load_pages(new_sha))
    # nothing counts as changed afterwards, and the original bytes are really gone
    pipeline.update("testfach")
    assert file_hash(path) == new_sha
    assert doc_of("scan.pdf")["id"] == doc["id"]
    assert not list((project / "quellen-testfach").rglob(".komprimiert-*"))


@needs_tools
def test_compress_waits_for_ocr(project):
    path = fresh(project)
    before = file_hash(path)
    pipeline.compress("testfach")
    assert file_hash(path) == before
    assert not (doc_of("scan.pdf").get("komprimierung") or {}).get("status")


@needs_tools
def test_profile_depends_on_quellenart(project):
    make_scan_pdf(project / "quellen-testfach" / "buecher" / "lesebuch.pdf", seed=1)
    make_scan_pdf(project / "quellen-testfach" / "uebungen" / "blatt.pdf", seed=1)
    pipeline.update("testfach", ocr_all=True, compress=True)
    book, sheet = doc_of("lesebuch.pdf"), doc_of("blatt.pdf")
    assert (book["komprimierung"]["profil"], sheet["komprimierung"]["profil"]) == ("lesen", "drucken")
    book_ppi = image_ppi(project / book["pfad"])
    sheet_ppi = image_ppi(project / sheet["pfad"])
    assert 140 <= book_ppi <= 160
    assert 190 <= sheet_ppi <= 210
    assert sheet["groesse"] > book["groesse"], "printable version keeps more detail"


@needs_tools
def test_dry_run_changes_nothing(project):
    path = fresh(project)
    pipeline.ocr("testfach")
    before, manifest_before = file_hash(path), FACH.manifest.read_text(encoding="utf-8")
    pipeline.compress("testfach", dry_run=True)
    assert file_hash(path) == before
    assert FACH.manifest.read_text(encoding="utf-8") == manifest_before
    assert not list((project / "quellen-testfach").rglob(".komprimiert-*"))


# ---------------------------------------------------------------- quality gates protect the original

def _broken_variants():
    """Each variant first shrinks like the real tool (so the size check passes) and then damages the result."""
    def shrink(src, dst):
        komprimieren.__dict__["_real_gs"](src, dst, Profile(dpi=150, qualitaet=0.7))

    def drop_last_page(src, dst, profile):
        shrink(src, dst.with_suffix(".full"))
        with pymupdf.open(dst.with_suffix(".full")) as document:
            document.select(list(range(len(document) - 1)))
            document.save(dst)

    def swapped_pages(src, dst, profile):
        shrink(src, dst.with_suffix(".full"))
        with pymupdf.open(dst.with_suffix(".full")) as document:
            document.select([1, 0, 2])
            document.save(dst)

    def blank_pages(src, dst, profile):
        with pymupdf.open(src) as document:
            blank = pymupdf.open()
            for page in document:
                blank.new_page(width=page.rect.width, height=page.rect.height)
            blank.save(dst)

    def unreadable(src, dst, profile):
        komprimieren.__dict__["_real_gs"](src, dst, Profile(dpi=30, qualitaet=3.0))

    return {"seite fehlt": drop_last_page, "leere Seiten": blank_pages, "unlesbar": unreadable, "vertauscht": swapped_pages}


@needs_tools
@pytest.mark.parametrize("variant", ["seite fehlt", "leere Seiten", "unlesbar", "vertauscht"])
def test_quality_gates_keep_original_when_result_is_bad(project, monkeypatch, variant):
    path = fresh(project)
    pipeline.ocr("testfach")
    before_sha = file_hash(path)
    doc = doc_of("scan.pdf")
    write_notes(doc["id"], before_sha)
    monkeypatch.setitem(komprimieren.__dict__, "_real_gs", komprimieren.ghostscript)
    monkeypatch.setattr(komprimieren, "ghostscript", _broken_variants()[variant])

    pipeline.compress("testfach")

    assert file_hash(path) == before_sha, "original must stay untouched"
    doc = doc_of("scan.pdf")
    assert doc["sha256"] == before_sha
    assert doc["komprimierung"]["status"] == "qualitaet_nicht_bestanden", variant
    assert doc["komprimierung"]["gruende"]
    assert cache_path(before_sha).exists()
    assert read_note(FACH.dossiers / f"{doc['id']}.md")[0]["hash"] == before_sha


@needs_tools
def test_no_saving_keeps_original(project, monkeypatch):
    path = fresh(project)
    pipeline.ocr("testfach")
    before = file_hash(path)
    monkeypatch.setattr(komprimieren, "ghostscript", lambda src, dst, profile: shutil.copy(src, dst))
    pipeline.compress("testfach")
    assert file_hash(path) == before
    assert doc_of("scan.pdf")["komprimierung"]["status"] == "nicht_lohnend"


@needs_tools
def test_interrupted_compression_is_completed_on_next_run(project, monkeypatch):
    path = fresh(project)
    pipeline.ocr("testfach")
    doc = doc_of("scan.pdf")
    old_sha = doc["sha256"]
    dossier, card = write_notes(doc["id"], old_sha)

    def crash(*args, **kwargs):
        raise RuntimeError("Stromausfall")

    monkeypatch.setattr(komprimieren, "_finalize", crash)
    with pytest.raises(RuntimeError):
        pipeline.compress("testfach")
    new_sha = file_hash(path)
    assert new_sha != old_sha, "file was replaced before the crash"
    assert load_manifest(FACH)["dokumente"][0]["komprimierung"]["status"] == "ausstehend"

    monkeypatch.undo()
    pipeline.update("testfach")

    doc = doc_of("scan.pdf")
    assert doc["sha256"] == new_sha and doc["komprimierung"]["status"] == "komprimiert"
    assert read_note(dossier)[0]["hash"] == new_sha and read_note(card)[0]["quelle_hash"] == new_sha
    assert doc["text"]["status"] == "ok" and cache_path(new_sha).exists()


@needs_tools
def test_moved_compressed_pdf_keeps_id_and_status(project):
    path = fresh(project)
    pipeline.update("testfach", ocr_all=True, compress=True)
    before = doc_of("scan.pdf")
    target = project / "quellen-testfach" / "buecher" / "unterordner" / "umbenannt.pdf"
    target.parent.mkdir()
    path.rename(target)
    pipeline.update("testfach")
    after = doc_of("umbenannt.pdf")
    assert after["id"] == before["id"] and after["sha256"] == before["sha256"]
    assert after["komprimierung"]["status"] == "komprimiert"
