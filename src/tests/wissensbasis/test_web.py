"""Webquellen: aus einer Seite wird eine Lesekopie, die wie jede andere Quelle geprüft und zitiert wird."""
from __future__ import annotations

import pytest

from wissensbasis import pipeline, web
from wissensbasis.config import Fach
from wissensbasis.notes import check
from wissensbasis.scan import load_manifest

FACH = Fach("testfach")
URL = "https://beispiel.example/material/ueberblick"

PAGE = """<html><head><title>Überblick | Beispielprojekt</title></head>
<body class="no-sidebars page-node">
<header id="header"><div class="region region-header-left">Beispielprojekt</div></header>
<nav id="navigation"><ul><li><a href="/start">Zur Startseite</a></li></ul></nav>
<div id="breadcrumbs">Sie sind hier: Startseite</div>
<div class="page-header"><h1>Überblick über das Material</h1></div>
<div class="region region-content">
<p>Vor dem <strong>Training</strong> kommt das Erarbeiten entlang eines Lernpfads.</p>
<ul><li>Standortbestimmung</li><li>Fördereinheit</li></ul>
<p>Mehr dazu steht im <a href="/kommentar.pdf">didaktischen Kommentar</a>.</p>
</div>
<footer><div class="region region-footer-1"><a href="/impressum">Impressum</a></div></footer>
</body></html>"""

TAXONOMIE = ("typen: {prinzip: {label: P}}\nbelegarten: {praxis: {label: X}}\nthemen: {foerderung: {label: F}}\n"
             "prinzipien: {}\nkompetenzen: {}\n")


def setup_project(project, page: str = PAGE, monkeypatch=None) -> None:
    FACH.quellenarten.write_text("regeln:\n  - pfad: web\n    quellenart: web\n", encoding="utf-8")
    monkeypatch.setattr(web, "fetch", lambda url: (page.encode("utf-8"), url))


def test_beiwerk_bleibt_draussen_und_der_inhalt_drin(project, monkeypatch):
    setup_project(project, monkeypatch=monkeypatch)
    path, status = web.holen(URL, FACH, log=lambda _message: None)
    text = path.read_text(encoding="utf-8")

    assert status == "neu"
    assert path == project / "quellen-testfach" / "web" / "beispiel.example" / "ueberblick.md"
    for noise in ("Zur Startseite", "Sie sind hier", "Impressum", "Beispielprojekt"):
        assert noise not in text, noise
    assert f"url: {URL}" in text and "abgerufen: 20" in text
    assert "# Überblick über das Material" in text
    assert "Vor dem **Training** kommt das Erarbeiten" in text
    assert "- Standortbestimmung" in text
    assert "[didaktischen Kommentar](https://beispiel.example/kommentar.pdf)" in text


def test_unveraenderte_seite_laesst_die_datei_in_ruhe(project, monkeypatch):
    """Sonst bekäme die Kopie bei jedem Abholen einen neuen Hash und jedes Dossier gälte als veraltet."""
    setup_project(project, monkeypatch=monkeypatch)
    path, _ = web.holen(URL, FACH, log=lambda _message: None)
    before = path.stat().st_mtime_ns

    assert web.holen(URL, FACH, log=lambda _message: None)[1] == "unveraendert"
    assert path.stat().st_mtime_ns == before

    setup_project(project, PAGE.replace("Lernpfads", "Lernpfads mit gestuften Lernzielen"), monkeypatch)
    assert web.holen(URL, FACH, log=lambda _message: None)[1] == "aktualisiert"
    assert "gestuften Lernzielen" in path.read_text(encoding="utf-8")


def test_seite_ohne_text_wird_abgelehnt(project, monkeypatch):
    setup_project(project, "<html><body><div id='app'></div><script>alles()</script></body></html>", monkeypatch)
    with pytest.raises(SystemExit, match="JavaScript"):
        web.holen(URL, FACH, log=lambda _message: None)


def test_kopie_wird_als_webquelle_in_abschnitten_erschlossen(project, monkeypatch):
    setup_project(project, monkeypatch=monkeypatch)
    web.holen(URL, FACH, log=lambda _message: None)
    pipeline.update("testfach", log=lambda _message: None)

    doc = next(doc for doc in load_manifest(FACH)["dokumente"] if "/web/" in doc["pfad"])
    assert doc["quellenart"] == "web"
    assert doc["text"]["status"] == "ok" and doc["text"]["einheit"] == "abschnitt"


def dossier(sha: str, adresse: str) -> str:
    return (f"---\ntitel: T\nstatus: freigegeben\nquelle: ueberblick\nhash: {sha}\nthemen: [foerderung]\n"
            f'zitierweise: "Beispielprojekt: Überblick. beispiel.example (abgerufen am 01.01.2026)."\n{adresse}---\n\nText\n')


def test_dossier_einer_webquelle_braucht_adresse_und_abrufdatum(project, monkeypatch):
    setup_project(project, monkeypatch=monkeypatch)
    web.holen(URL, FACH, log=lambda _message: None)
    pipeline.update("testfach", log=lambda _message: None)
    FACH.taxonomie.write_text(TAXONOMIE, encoding="utf-8")
    sha = next(doc["sha256"] for doc in load_manifest(FACH)["dokumente"] if "/web/" in doc["pfad"])
    FACH.dossiers.mkdir(parents=True, exist_ok=True)
    path = FACH.dossiers / "ueberblick.md"

    path.write_text(dossier(sha, ""), encoding="utf-8")
    errors, _ = check(FACH)
    assert [error for error in errors if "'url'" in error] and [error for error in errors if "'abgerufen'" in error]

    path.write_text(dossier(sha, f"url: {URL}\nabgerufen: 2026-01-01\n"), encoding="utf-8")
    assert not check(FACH)[0]
