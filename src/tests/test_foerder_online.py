from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import foerder_online as fo  # noqa: E402


def _blatt(repo: Path, thema: str, stufe: str, stem: str, *, pdf: bool = True, loesung: bool = True) -> None:
    ordner = repo / fo.QUELLE / thema / f"foerderkurs-{stufe}"
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{stem}.qmd").write_text("x", encoding="utf-8")
    if loesung:
        (ordner / f"{stem}-loesung.qmd").write_text("x", encoding="utf-8")
    if pdf:
        zentral = repo / "build" / "pdf" / ordner.relative_to(repo)
        zentral.mkdir(parents=True, exist_ok=True)
        (zentral / f"{stem}.pdf").write_bytes(b"%PDF sheet")
        if loesung:
            (zentral / f"{stem}-loesung.pdf").write_bytes(b"%PDF loesung")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    root = repo / fo.LAYOUT
    root.mkdir(parents=True)
    (root / "foerder-header.tex").write_text("h", encoding="utf-8")
    (root / "_metadata.yml").write_text("m", encoding="utf-8")
    past = time.time() - 1000
    os.utime(root / "foerder-header.tex", (past, past))
    os.utime(root / "_metadata.yml", (past, past))
    return repo


def test_ordnernamen_wie_online(tmp_path):
    repo = _repo(tmp_path)
    _blatt(repo, "division", "stufe-1", "division-stufe-1-ab-1")
    _blatt(repo, "operationsverstaendnis", "stufe-1a", "operationsverstaendnis-stufe-1a-ab-1")
    _blatt(repo, "zahlenverstaendnis", "stufe-2b", "zahlenverstaendnis-stufe-2b-ab-1")
    ziel = tmp_path / "ziel"
    plan = fo.plane(repo, ziel)
    ziele = {e.ziel.relative_to(ziel).as_posix() for e in plan.eintraege}
    assert ziele == {
        "division/Stufe1/division-stufe-1-ab-1.pdf",
        "operationsverstaendnis/Stufe 1a/operationsverstaendnis-stufe-1a-ab-1.pdf",
        "zahlenverstaendnis/Stufe 2b/zahlenverstaendnis-stufe-2b-ab-1.pdf",
    }


def test_loesungen_nur_auf_wunsch_im_unterordner(tmp_path):
    repo = _repo(tmp_path)
    _blatt(repo, "subtraktion", "stufe-2", "subtraktion-stufe-2-ab-1")
    ziel = tmp_path / "ziel"
    assert len(fo.plane(repo, ziel).eintraege) == 1
    plan = fo.plane(repo, ziel, loesungen=True)
    ziele = {e.ziel.relative_to(ziel).as_posix() for e in plan.eintraege}
    assert "subtraktion/Stufe2/Loesungen/subtraktion-stufe-2-ab-1-loesung.pdf" in ziele


def test_ordner_ausserhalb_der_struktur_werden_gemeldet(tmp_path):
    repo = _repo(tmp_path)
    _blatt(repo, "ueberschlag", "stufe-1", "ueberschlag-stufe-1-ab-1")
    _blatt(repo, "subtraktion", "unterrichtsmaterial", "subtraktion-mehrere-subtrahenden-ab-1")
    ziel = tmp_path / "ziel"
    plan = fo.plane(repo, ziel)
    assert plan.eintraege == []
    assert len(plan.uebersprungen) == 2
    plan = fo.plane(repo, ziel, alles=True)
    ziele = {e.ziel.relative_to(ziel).as_posix() for e in plan.eintraege}
    assert "ueberschlag/Stufe1/ueberschlag-stufe-1-ab-1.pdf" in ziele
    assert "subtraktion/Unterrichtsmaterial/subtraktion-mehrere-subtrahenden-ab-1.pdf" in ziele


def test_kopieren_ist_idempotent_und_trocken_aendert_nichts(tmp_path):
    repo = _repo(tmp_path)
    _blatt(repo, "multiplikation", "stufe-1", "multiplikation-stufe-1-ab-1")
    ziel = tmp_path / "ziel"
    plan = fo.plane(repo, ziel)
    assert fo.kopiere(plan, trocken=True)["kopiert"]
    assert not ziel.exists()
    assert len(fo.kopiere(plan)["kopiert"]) == 1
    zweiter = fo.kopiere(plan)
    assert zweiter["kopiert"] == [] and len(zweiter["unveraendert"]) == 1


def test_fehlende_und_veraltete_pdfs(tmp_path):
    repo = _repo(tmp_path)
    _blatt(repo, "division", "stufe-2", "division-stufe-2-ab-1", pdf=False)
    _blatt(repo, "multiplikation", "stufe-2", "multiplikation-stufe-2-ab-1")
    pdf = repo / "build" / "pdf" / fo.QUELLE / "multiplikation" / "foerderkurs-stufe-2" / "multiplikation-stufe-2-ab-1.pdf"
    alt = time.time() - 500
    os.utime(pdf, (alt, alt))
    (repo / fo.QUELLE / "multiplikation" / "foerderkurs-stufe-2" / "multiplikation-stufe-2-ab-1.qmd").write_text("neu", encoding="utf-8")
    plan = fo.plane(repo, tmp_path / "ziel")
    status = {e.stem: (e.fehlt, e.veraltet) for e in plan.eintraege}
    assert status["division-stufe-2-ab-1"] == (True, False)
    assert status["multiplikation-stufe-2-ab-1"] == (False, True)
    ergebnis = fo.kopiere(plan)
    assert len(ergebnis["fehlend"]) == 1


def test_aufraeumen_loescht_nur_pdfs_die_nicht_mehr_zum_plan_gehoeren(tmp_path):
    repo = _repo(tmp_path)
    _blatt(repo, "division", "stufe-1", "division-stufe-1-ab-1")
    ziel = tmp_path / "ziel"
    plan = fo.plane(repo, ziel)
    fo.kopiere(plan)
    alt = ziel / "division" / "Stufe1" / "division-stufe-1-ab-9.pdf"
    alt.write_bytes(b"alt")
    notiz = ziel / "division" / "Stufe1" / "notiz.txt"
    notiz.write_text("bleibt", encoding="utf-8")
    fremd = ziel / "andere" / "x.pdf"
    fremd.parent.mkdir()
    fremd.write_bytes(b"fremd")
    assert fo.aufraeumen(plan, ziel, trocken=True) == [alt]
    assert alt.exists()
    assert fo.aufraeumen(plan, ziel) == [alt]
    assert not alt.exists() and notiz.exists() and fremd.exists()
    assert (ziel / "division" / "Stufe1" / "division-stufe-1-ab-1.pdf").exists()
