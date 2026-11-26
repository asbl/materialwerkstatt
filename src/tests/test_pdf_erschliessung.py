from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pdf_erschliessung as modul  # noqa: E402


QMD_MIT_IMPORT = """---
title: 01 Erste Übungen
lang: de
format:
  pdf:
    output-file: 01-erste-ubungen-entwurf.pdf
material:
  import:
    kind: onlyoffice
    mode: positioned-draft
    source: _eingang/onlyoffice/klasse-10/trigonometrie/01 Erste Übungen.docx
    source-pages: 5
tags:
- mathematik
---

Körper.
"""


def _pdf(root: Path, pfad: str, inhalt: bytes = b"%PDF-1.4 test") -> Path:
    datei = root / pfad
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_bytes(inhalt)
    return datei


def test_erschliessen_verschiebt_und_verzeichnet(tmp_path):
    quelle = _pdf(tmp_path, "_eingang/onlyoffice/arbeitsblatt.pdf")
    ergebnis = modul.erschliessen(quelle, "arbeitsblatt/mathematik/klasse-10/trigonometrie", root=tmp_path)
    assert ergebnis.status == modul.STATUS_ERSCHLOSSEN
    ziel = tmp_path / "wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/arbeitsblatt.pdf"
    assert ziel.is_file()
    assert not quelle.exists()
    daten = modul.manifest_laden(tmp_path)
    assert ergebnis.pruefsumme in daten["eintraege"]
    assert daten["eintraege"][ergebnis.pruefsumme]["pfad"] == "arbeitsblatt/mathematik/klasse-10/trigonometrie/arbeitsblatt.pdf"


def test_dublikat_wird_nur_einmal_gespeichert(tmp_path):
    erste = _pdf(tmp_path, "_eingang/a/erste-version.pdf", inhalt=b"%PDF-1.4 inhalt")
    zweite = _pdf(tmp_path, "_eingang/b/umbenannt.pdf", inhalt=b"%PDF-1.4 inhalt")
    modul.erschliessen(erste, "arbeitsblatt/mathematik/klasse-10/trigonometrie", root=tmp_path)
    ergebnis = modul.erschliessen(zweite, "arbeitsblatt/mathematik/klasse-10/trigonometrie", root=tmp_path)
    assert ergebnis.status == modul.STATUS_DUPLIKAT
    assert ergebnis.ziel is None
    assert ergebnis.duplikat_von == tmp_path / "wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/erste-version.pdf"
    # Dublette bleibt am Ort und wird nicht ein zweites Mal gespeichert.
    assert zweite.is_file()
    assert len(list((tmp_path / "wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie").glob("*.pdf"))) == 1
    assert len(modul.manifest_laden(tmp_path)["eintraege"]) == 1


def test_original_suffix_wird_entfernt(tmp_path):
    quelle = _pdf(tmp_path, "_eingang/01-erste-ubungen-original.pdf")
    ergebnis = modul.erschliessen(quelle, "arbeitsblatt/mathematik/klasse-10/trigonometrie", root=tmp_path)
    assert ergebnis.ziel is not None
    assert ergebnis.ziel.name == "01-erste-ubungen.pdf"


def test_gleicher_name_anderer_inhalt_wird_abgelehnt(tmp_path):
    erste = _pdf(tmp_path, "_eingang/erste.pdf", inhalt=b"%PDF-1.4 a")
    zweite = _pdf(tmp_path, "_eingang/zweite.pdf", inhalt=b"%PDF-1.4 b")
    modul.erschliessen(erste, "arbeitsblatt/x", root=tmp_path)
    zweite.replace(tmp_path / "_eingang/erste.pdf")
    try:
        modul.erschliessen(tmp_path / "_eingang/erste.pdf", "arbeitsblatt/x", root=tmp_path)
    except FileExistsError:
        pass
    else:
        raise AssertionError("Kollision erwartet")


def test_erschliessen_akzeptiert_bilder(tmp_path):
    quelle = _pdf(tmp_path, "_eingang/aufgabe.png", inhalt=b"\x89PNG\r\n\x1a\ntest")
    ergebnis = modul.erschliessen(quelle, "aufgaben/mathematik/klasse-06/bruchrechnung", root=tmp_path)
    assert ergebnis.status == modul.STATUS_ERSCHLOSSEN
    ziel = tmp_path / "wissen/aufgaben/mathematik/klasse-06/bruchrechnung/aufgabe.png"
    assert ziel.is_file()


def test_erschliessen_lehnt_andere_dateitypen_ab(tmp_path):
    quelle = _pdf(tmp_path, "_eingang/notiz.txt", inhalt=b"kein pdf oder bild")
    try:
        modul.erschliessen(quelle, "arbeitsblatt/x", root=tmp_path)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("FileNotFoundError erwartet")


def test_trocken_laesst_alles_am_ort(tmp_path):
    quelle = _pdf(tmp_path, "_eingang/arbeitsblatt.pdf")
    ergebnis = modul.erschliessen(quelle, "arbeitsblatt/mathematik/klasse-10/trigonometrie", root=tmp_path, trocken=True)
    assert ergebnis.status == modul.STATUS_TROCKEN
    assert quelle.is_file()
    assert not (tmp_path / "wissen").exists()


def test_unzulaessiges_ziel_wird_abgelehnt(tmp_path):
    quelle = _pdf(tmp_path, "_eingang/arbeitsblatt.pdf")
    for ziel in ("", "..", "arbeitsblatt/../quellen", ".versteckt"):
        try:
            modul.erschliessen(quelle, ziel, root=tmp_path)
        except ValueError:
            continue
        raise AssertionError(f"ValueError erwartet fuer {ziel!r}")


def test_verlinse_import_pdf_ersetzt_docx_referenz(tmp_path):
    qmd = tmp_path / "01-erste-ubungen-entwurf.qmd"
    qmd.write_text(QMD_MIT_IMPORT, encoding="utf-8")
    modul.verlinse_import_pdf(qmd, "wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/01-erste-ubungen.pdf")
    text = qmd.read_text(encoding="utf-8")
    assert "source: _eingang/onlyoffice" not in text
    assert "    source-pdf: wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/01-erste-ubungen.pdf\n" in text
    # Header bleibt sonst unangetastet: Titel, tags und Koerper stehen noch.
    assert "title: 01 Erste Übungen" in text
    assert "- mathematik" in text
    assert text.endswith("\nKörper.\n")


def test_verlinse_ersetzt_auch_includepdf_pfad(tmp_path):
    qmd = tmp_path / "unterricht" / "klasse-10" / "arbeitsblaetter" / "01-erste-ubungen.qmd"
    qmd.parent.mkdir(parents=True)
    qmd.write_text(
        "---\n"
        "title: 01 Erste Übungen\n"
        "material:\n"
        "  import:\n"
        "    kind: onlyoffice\n"
        "    mode: pdfpages\n"
        "    source: _eingang/onlyoffice/klasse-10/trigonometrie/01 Erste Übungen.docx\n"
        "    source-pages: 5\n"
        "---\n\n"
        "\\includepdf[pages=-,fitpaper=true]{../../../../_eingang/onlyoffice/klasse-10/trigonometrie/01-erste-ubungen-original.pdf}\n",
        encoding="utf-8",
    )
    modul.verlinse_import_pdf(
        qmd,
        "wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/01-erste-ubungen.pdf",
        root=tmp_path,
    )
    text = qmd.read_text(encoding="utf-8")
    assert "source-pdf: wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/01-erste-ubungen.pdf" in text
    assert "\\includepdf[pages=-,fitpaper=true]{../../../wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/01-erste-ubungen.pdf}" in text


def test_verlinse_ohne_docx_quelle_wird_abgelehnt(tmp_path):
    qmd = tmp_path / "ohne-import.qmd"
    qmd.write_text("---\ntitle: Ohne\n---\n\nKörper.\n", encoding="utf-8")
    try:
        modul.verlinse_import_pdf(qmd, "wissen/x/y.pdf")
    except ValueError:
        pass
    else:
        raise AssertionError("ValueError erwartet")
    assert qmd.read_text(encoding="utf-8") == "---\ntitle: Ohne\n---\n\nKörper.\n"
