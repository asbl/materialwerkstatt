from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf
import pytest

import layout_regression
import project_tasks


def _png() -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8))
    return pixmap.tobytes("png")


def _pdf_schreiben(pfad: Path, *, seiten: int = 1, groesse: tuple[int, int] = (595, 842), bilder: list[tuple[float, float, float, float]] | None = None) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as dokument:
        for _ in range(seiten):
            page = dokument.new_page(width=groesse[0], height=groesse[1])
            for rect in bilder or []:
                page.insert_image(pymupdf.Rect(*rect), stream=_png())
        dokument.save(pfad)


def test_source_pdf_referenz_liest_frontmatter():
    text = (
        "---\n"
        "title: Blatt\n"
        "material:\n"
        "  import:\n"
        "    kind: onlyoffice\n"
        "    source-pdf: wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/01-erste-ubungen.pdf\n"
        "---\n\nText.\n"
    )
    assert layout_regression.source_pdf_referenz(text) == (
        "wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/01-erste-ubungen.pdf"
    )


def test_source_pdf_referenz_ohne_import():
    assert layout_regression.source_pdf_referenz("---\ntitle: Blatt\n---\n\nText.\n") is None
    assert layout_regression.source_pdf_referenz("# Kein Frontmatter\n") is None


def test_vergleiche_uebereinstimmung(tmp_path):
    original = tmp_path / "original.pdf"
    gebaut = tmp_path / "gebaut.pdf"
    with pymupdf.open() as dokument:
        page = dokument.new_page(width=595, height=842)
        page.insert_image(pymupdf.Rect(100, 100, 300, 250), stream=_png())
        dokument.save(original)
    with pymupdf.open() as dokument:
        page = dokument.new_page(width=595.5, height=842)
        page.insert_image(pymupdf.Rect(101, 100, 301, 250), stream=_png())
        dokument.save(gebaut)

    abweichungen = layout_regression.vergleiche(gebaut, original)
    assert abweichungen == []


def test_vergleiche_meldet_seitenzahl_und_format(tmp_path):
    original = tmp_path / "original.pdf"
    gebaut = tmp_path / "gebaut.pdf"
    _pdf_schreiben(original, seiten=2)
    _pdf_schreiben(gebaut, seiten=1, groesse=(420, 595))

    abweichungen = layout_regression.vergleiche(gebaut, original)
    arten = {abweichung.art for abweichung in abweichungen}
    assert arten == {"seitenzahl", "seitenformat"}


def test_vergleiche_meldet_versetzte_bilder(tmp_path):
    original = tmp_path / "original.pdf"
    gebaut = tmp_path / "gebaut.pdf"
    _pdf_schreiben(original, bilder=[(100, 100, 300, 250)])
    _pdf_schreiben(gebaut, bilder=[(100, 400, 300, 550)])

    abweichungen = layout_regression.vergleiche(gebaut, original)
    assert {abweichung.art for abweichung in abweichungen} == {"bildposition"}


def test_vergleiche_meldet_bildanzahl(tmp_path):
    original = tmp_path / "original.pdf"
    gebaut = tmp_path / "gebaut.pdf"
    _pdf_schreiben(original, bilder=[(100, 100, 300, 250), (100, 400, 300, 550)])
    _pdf_schreiben(gebaut, bilder=[(100, 100, 300, 250)])

    abweichungen = layout_regression.vergleiche(gebaut, original)
    assert {abweichung.art for abweichung in abweichungen} == {"bildanzahl"}


def _layout_repo(tmp_path: Path, *, gebaut: bool, uebereinstimmung: bool) -> None:
    original = tmp_path / "wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/blatt.pdf"
    bilder = [(100, 100, 300, 250)]
    _pdf_schreiben(original, bilder=bilder)
    qmd = tmp_path / "unterricht/mathematik/klasse-10/arbeitsblaetter/blatt-entwurf.qmd"
    qmd.parent.mkdir(parents=True, exist_ok=True)
    qmd.write_text(
        "---\n"
        "title: Blatt\n"
        "material:\n"
        "  import:\n"
        "    kind: onlyoffice\n"
        f"    source-pdf: {original.relative_to(tmp_path).as_posix()}\n"
        "---\n\nText.\n",
        encoding="utf-8",
    )
    if gebaut:
        _pdf_schreiben(
            tmp_path / "build/pdf/unterricht/mathematik/klasse-10/arbeitsblaetter/blatt-entwurf.pdf",
            bilder=bilder if uebereinstimmung else [(100, 500, 300, 650)],
        )


def test_layout_pruefen_meldet_ok(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _layout_repo(tmp_path, gebaut=True, uebereinstimmung=True)

    project_tasks.layout_pruefen.body(None)

    ausgabe = capsys.readouterr().out
    assert "[ok]" in ausgabe
    assert "1 Dokument(e) geprueft, keine Abweichungen." in ausgabe


def test_layout_pruefen_scheitert_bei_abweichung(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _layout_repo(tmp_path, gebaut=True, uebereinstimmung=False)

    with pytest.raises(SystemExit, match="Abweichungen"):
        project_tasks.layout_pruefen.body(None)

    assert "[abweichung]" in capsys.readouterr().out


def test_layout_pruefen_meldet_offen_und_original_fehlt(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _layout_repo(tmp_path, gebaut=False, uebereinstimmung=True)

    project_tasks.layout_pruefen.body(None)
    ausgabe = capsys.readouterr().out
    assert "[offen]" in ausgabe

    (tmp_path / "wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/blatt.pdf").unlink()
    with pytest.raises(SystemExit, match="fehlendem Original"):
        project_tasks.layout_pruefen.body(None)
    assert "[original-fehlt]" in capsys.readouterr().out
