"""Durability of the pipeline: restored originals, duplicates, features Ghostscript would drop, and isolated failures."""
from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf
import pytest

from conftest import make_scan_pdf, needs_tools

from wissensbasis import extract, komprimieren, pipeline
from wissensbasis.config import Fach
from wissensbasis.extract import cache_path
from wissensbasis.komprimieren import Profile
from wissensbasis.notes import read_note
from wissensbasis.scan import file_hash, load_manifest

FACH = Fach("testfach")


def docs() -> list[dict]:
    return load_manifest(FACH)["dokumente"]


def doc_of(name: str) -> dict:
    return next(doc for doc in docs() if doc["pfad"].endswith(name))


def write_notes(doc_id: str, sha: str) -> tuple[Path, Path]:
    dossier = FACH.dossiers / f"{doc_id}.md"
    card = FACH.karten / doc_id / "01-karte.md"
    dossier.parent.mkdir(parents=True, exist_ok=True)
    card.parent.mkdir(parents=True, exist_ok=True)
    dossier.write_text(f"---\ntitel: T\nquelle: {doc_id}\nhash: {sha}\nthemen: [x]\n---\n\nText\n", encoding="utf-8")
    card.write_text(f"---\ntitel: K\nquelle: {doc_id}\nquelle_hash: {sha}\nseite: 1\n---\n\nText\n", encoding="utf-8")
    return dossier, card


def books(project) -> Path:
    return project / "quellen-testfach" / "buecher"


# ---------------------------------------------------------------- restored originals and duplicates

@needs_tools
def test_restored_original_at_same_path_keeps_id_text_and_notes(project):
    path = books(project) / "scan.pdf"
    make_scan_pdf(path)
    original = project / "original.pdf"
    shutil.copy(path, original)
    pipeline.update("testfach", ocr_all=True, compress=True)
    first = doc_of("scan.pdf")
    dossier, card = write_notes(first["id"], first["sha256"])

    shutil.copy(original, path)  # the backup copy is put back
    pipeline.update("testfach")

    again = doc_of("scan.pdf")
    original_sha = file_hash(original)
    assert again["id"] == first["id"] and again["sha256"] == original_sha != first["sha256"]
    assert again["text"]["status"] == "ok", "the OCR text is reused, no new OCR"
    assert again["komprimierung"]["status"] == "wiederhergestellt" and "_relink" not in again
    assert read_note(dossier)[0]["hash"] == original_sha and read_note(card)[0]["quelle_hash"] == original_sha
    assert cache_path(original_sha).exists() and not cache_path(first["sha256"]).exists()

    pipeline.compress("testfach")
    final = doc_of("scan.pdf")
    assert final["id"] == first["id"] and final["komprimierung"]["status"] == "komprimiert"
    assert read_note(dossier)[0]["hash"] == final["sha256"]


@needs_tools
def test_original_next_to_compressed_copy_is_a_duplicate_until_the_copy_disappears(project):
    path = books(project) / "scan.pdf"
    make_scan_pdf(path)
    original = project / "original.pdf"
    shutil.copy(path, original)
    pipeline.update("testfach", ocr_all=True, compress=True)
    first = doc_of("scan.pdf")
    dossier, _ = write_notes(first["id"], first["sha256"])

    extra = books(project) / "original-kopie.pdf"
    shutil.copy(original, extra)
    pipeline.update("testfach", ocr_all=True, compress=True)
    duplicate = doc_of("original-kopie.pdf")
    assert duplicate["duplikat_von"] == first["id"] and duplicate["text"]["status"] == "duplikat"
    assert file_hash(extra) == file_hash(original), "duplicates are neither OCR'd nor compressed"
    assert doc_of("scan.pdf")["sha256"] == first["sha256"]

    path.unlink()  # the compressed copy goes away, the original takes over its identity
    pipeline.update("testfach")
    assert len(docs()) == 1
    survivor = docs()[0]
    assert survivor["pfad"].endswith("original-kopie.pdf") and survivor["id"] == first["id"]
    assert survivor["text"]["status"] == "ok" and survivor["komprimierung"]["status"] == "wiederhergestellt"
    assert read_note(dossier)[0]["hash"] == file_hash(original)


@needs_tools
def test_identical_files_are_processed_once(project):
    make_scan_pdf(books(project) / "a.pdf", seed=3)
    shutil.copy(books(project) / "a.pdf", books(project) / "b.pdf")
    pipeline.update("testfach", ocr_all=True)
    first, second = doc_of("a.pdf"), doc_of("b.pdf")
    assert second["duplikat_von"] == first["id"] and "duplikat_von" not in first
    assert first["text"]["status"] == "ok" and second["text"]["status"] == "duplikat"
    assert "Duplikate (1" in pipeline.report(FACH, load_manifest(FACH))


# ---------------------------------------------------------------- features Ghostscript would drop

def scan_with(project, name: str, *, form: bool = False, toc: bool = False) -> Path:
    path = books(project) / name
    make_scan_pdf(path, seed=5)
    with pymupdf.open(path) as document:
        if form:
            widget = pymupdf.Widget()
            widget.field_name, widget.field_type = "antwort", pymupdf.PDF_WIDGET_TYPE_TEXT
            widget.rect = pymupdf.Rect(50, 50, 250, 80)
            document[0].add_widget(widget)
        if toc:
            document.set_toc([[1, "Erstes Kapitel", 1], [1, "Zweites Kapitel", 2]])
        document.save(path.with_suffix(".neu"))
    path.with_suffix(".neu").replace(path)
    return path


@needs_tools
def test_forms_are_never_compressed_because_ghostscript_drops_the_fields(project):
    path = scan_with(project, "formular.pdf", form=True)
    before = file_hash(path)
    pipeline.update("testfach", ocr_all=True, compress=True)
    assert file_hash(path) == before
    assert doc_of("formular.pdf")["komprimierung"]["status"] == "formular"


@needs_tools
def test_bookmarks_survive_compression(project):
    path = scan_with(project, "mit-toc.pdf", toc=True)
    pipeline.update("testfach", ocr_all=True, compress=True)
    assert doc_of("mit-toc.pdf")["komprimierung"]["status"] == "komprimiert"
    with pymupdf.open(path) as document:
        assert [entry[1] for entry in document.get_toc()] == ["Erstes Kapitel", "Zweites Kapitel"]


@needs_tools
def test_lost_bookmarks_fail_the_quality_gate(project, monkeypatch):
    path = scan_with(project, "mit-toc.pdf", toc=True)
    pipeline.update("testfach", ocr_all=True)
    before = file_hash(path)
    real = komprimieren.ghostscript

    def without_toc(src, dst, profile):
        real(src, dst.with_suffix(".full"), Profile(dpi=150, qualitaet=0.7))
        with pymupdf.open(dst.with_suffix(".full")) as document:
            document.set_toc([])
            document.save(dst)

    monkeypatch.setattr(komprimieren, "ghostscript", without_toc)
    pipeline.compress("testfach")
    assert file_hash(path) == before
    info = doc_of("mit-toc.pdf")["komprimierung"]
    assert info["status"] == "qualitaet_nicht_bestanden" and any("Inhaltsverzeichnis" in reason for reason in info["gruende"])


# ---------------------------------------------------------------- one broken document must not stop the run

@needs_tools
def test_ocr_page_error_is_recorded_and_the_run_continues(project, monkeypatch):
    make_scan_pdf(books(project) / "a.pdf", seed=1)
    make_scan_pdf(books(project) / "b.pdf", seed=2)
    real = extract._ocr_page

    def flaky(pdf, number, image=None, language="deu"):
        if number == 2 and pdf.name == "a.pdf":
            raise extract.OcrError("Seite kaputt")
        return real(pdf, number, image, language)

    monkeypatch.setattr(extract, "_ocr_page", flaky)
    pipeline.update("testfach", ocr_all=True)
    a, b = doc_of("a.pdf"), doc_of("b.pdf")
    assert a["text"]["status"] == "ok" and a["text"]["ocr_fehlerseiten"] == 1
    assert b["text"]["status"] == "ok" and "ocr_fehlerseiten" not in b["text"]


@needs_tools
def test_exception_in_one_pdf_does_not_stop_compression_of_the_others(project, monkeypatch):
    make_scan_pdf(books(project) / "a.pdf", seed=1)
    make_scan_pdf(books(project) / "b.pdf", seed=2)
    pipeline.update("testfach", ocr_all=True)
    real = komprimieren.quality_report

    def explode_for_a(original, candidate, cached, gates, language="deu"):
        if original.name == "a.pdf":
            raise ValueError("kaputtes PDF")
        return real(original, candidate, cached, gates, language)

    monkeypatch.setattr(komprimieren, "quality_report", explode_for_a)
    a_before = file_hash(books(project) / "a.pdf")
    pipeline.compress("testfach")
    assert doc_of("a.pdf")["komprimierung"]["status"] == "fehler" and file_hash(books(project) / "a.pdf") == a_before
    assert doc_of("b.pdf")["komprimierung"]["status"] == "komprimiert"


def test_second_writing_run_is_refused(project):
    with pipeline.exclusive_run():
        with pytest.raises(SystemExit):
            pipeline.update("testfach")


# ---------------------------------------------------------------- damaged PDFs and text-poor pages

@needs_tools
def test_page_loss_by_ghostscript_is_retried_on_a_qpdf_repaired_copy(project, monkeypatch):
    path = books(project) / "kaputt.pdf"
    make_scan_pdf(path)
    pipeline.update("testfach", ocr_all=True)
    real = komprimieren.ghostscript
    calls = []

    def loses_pages_unless_repaired(src, dst, profile):
        calls.append(src.name)
        if not src.name.startswith(komprimieren.TEMP_PREFIX):
            with pymupdf.open() as one_page:
                one_page.new_page(width=595, height=842)
                one_page.save(dst)
            return
        real(src, dst, profile)

    monkeypatch.setattr(komprimieren, "ghostscript", loses_pages_unless_repaired)
    pipeline.compress("testfach")
    assert doc_of("kaputt.pdf")["komprimierung"]["status"] == "komprimiert"
    assert calls[0] == "kaputt.pdf" and calls[1].startswith(komprimieren.TEMP_PREFIX)
    with pymupdf.open(path) as document:
        assert len(document) == 3
    assert not list((project / "quellen-testfach").rglob(".komprimiert-*"))


@needs_tools
def test_pages_with_little_text_are_judged_by_the_visual_comparison_only(project):
    make_scan_pdf(books(project) / "wenig-text.pdf", sentences=1)
    pipeline.update("testfach", ocr_all=True, compress=True)
    info = doc_of("wenig-text.pdf")["komprimierung"]
    assert info["status"] == "komprimiert"
    assert info["kennzahlen"]["textbeleg"] is False and "ocr_uebereinstimmung_mittel" not in info["kennzahlen"]
