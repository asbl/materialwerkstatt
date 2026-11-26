from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf

import material_suche
import project_tasks


def _pdf_mit_text(pfad: Path, texte: list[str]) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as dokument:
        for text in texte:
            dokument.new_page().insert_text((72, 72), text)
        dokument.save(pfad)


def _wissen_aufbauen(tmp_path: Path) -> None:
    _pdf_mit_text(
        tmp_path / "wissen/arbeitsblatt/mathematik/klasse-05/rechenbausteine/malkreuz.pdf",
        ["Punktefeld und Malkreuz", "Uebung: 6 mal 7"],
    )
    _pdf_mit_text(tmp_path / "wissen/mathematik/curriculum/curriculum.pdf", ["Jahrgangsstufe 10"])
    registry = {
        "version": 1,
        "eintraege": {
            "aaa": {
                "erschlossen": "2026-10-22T08:00:00+00:00",
                "pfad": "arbeitsblatt/mathematik/klasse-05/rechenbausteine/malkreuz.pdf",
            },
            "bbb": {
                "erschlossen": "2026-10-22T08:01:00+00:00",
                "pfad": "mathematik/curriculum/curriculum.pdf",
            },
        },
    }
    (tmp_path / "wissen/_pdf-erschliessung.json").write_text(json.dumps(registry), encoding="utf-8")


def test_index_baut_und_sucht(tmp_path):
    _wissen_aufbauen(tmp_path)

    index = material_suche.baue_index(tmp_path / "wissen")

    assert set(index["dokumente"]) == {
        "arbeitsblatt/mathematik/klasse-05/rechenbausteine/malkreuz.pdf",
        "mathematik/curriculum/curriculum.pdf",
    }
    treffer = material_suche.suche(index, "malkreuz")
    assert len(treffer) == 1
    assert treffer[0].pfad == "arbeitsblatt/mathematik/klasse-05/rechenbausteine/malkreuz.pdf"
    assert treffer[0].seite == 1
    assert "Punktefeld" in treffer[0].ausschnitt


def test_suche_ist_grossklein_unempfindlich_und_limitiert(tmp_path):
    _wissen_aufbauen(tmp_path)
    index = material_suche.baue_index(tmp_path / "wissen")

    treffer = material_suche.suche(index, "MALKREUZ")
    assert len(treffer) == 1
    assert material_suche.suche(index, "nichtvorhanden") == []
    assert material_suche.suche(index, "") == []


def test_index_vermerkt_seiten_ohne_text(tmp_path):
    _pdf_mit_text(tmp_path / "wissen/arbeitsblatt/mathematik/klasse-05/rechenbausteine/scan.pdf", ["", ""])
    registry = {
        "version": 1,
        "eintraege": {
            "ccc": {
                "erschlossen": "2026-10-22T08:02:00+00:00",
                "pfad": "arbeitsblatt/mathematik/klasse-05/rechenbausteine/scan.pdf",
            },
        },
    }
    (tmp_path / "wissen/_pdf-erschliessung.json").write_text(json.dumps(registry), encoding="utf-8")

    index = material_suche.baue_index(tmp_path / "wissen")

    dokument = index["dokumente"]["arbeitsblatt/mathematik/klasse-05/rechenbausteine/scan.pdf"]
    assert dokument["ohne_text"] == 2


def test_lade_index_roundtrip(tmp_path):
    _wissen_aufbauen(tmp_path)
    material_suche.baue_index(tmp_path / "wissen")

    index = material_suche.lade_index(tmp_path)

    assert index is not None
    assert "malkreuz" in index["dokumente"]["arbeitsblatt/mathematik/klasse-05/rechenbausteine/malkreuz.pdf"]["seiten"][0].lower()


def test_material_suche_task_findet_treffer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _wissen_aufbauen(tmp_path)

    project_tasks.material_suche_task.body(None, "malkreuz")

    ausgabe = capsys.readouterr().out
    assert "malkreuz.pdf" in ausgabe
    assert "Seite 1" in ausgabe


def test_material_suche_task_ohne_treffer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _wissen_aufbauen(tmp_path)

    project_tasks.material_suche_task.body(None, "nichtvorhanden")

    assert "Keine Treffer." in capsys.readouterr().out
