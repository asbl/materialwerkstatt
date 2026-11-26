"""Neue Karten werden aufgenommen oder zurückgestellt, nach Bereich und Quelle einsortiert und priorisiert ausgewählt."""
from __future__ import annotations

from wissensbasis import pages, pipeline
from wissensbasis.config import Fach
from wissensbasis.notes import load_notes
from wissensbasis.ordnung import Ordnung
from wissensbasis.scan import load_manifest

FACH = Fach("testfach")
TEXT = "Grundvorstellungen bei Bruchzahlen entstehen durch Handeln. Diagnose mit Vor-Check und Nach-Check im Förderbaustein."
RULES = """stufen: {1: 4, 2: 3}
punkte:
  belegart: {empirisch: 3, theoretisch: 2, praxis: 1}
  quellenart: {theorie: 2, web: 0}
leitquellen:
  - quelle: "msk-*"
    bereiche: [arithmetik]
    grund: Förderkonzept
  - quelle: barton
    zwecke: [stundenentwurf]
    grund: Intelligent Practice
zwecke:
  stundenentwurf: {label: Stunde, typen: {methode: 2}}
kategorien: {prinzip: prinzip, methode: methode}
aufnahme: {duplikat_schwelle: 0.5, duplikat_schwelle_gleiche_seite: 0.3, mindestpunkte: 3, genug_karten: 2}
"""


def body(words: str) -> str:
    return f"## Aussage\n\n{words} " + "Die Quelle erläutert das ausführlich mit Beispielen aus dem Unterricht. " * 10 + "\n\n## Prüffrage\n\nPasst das?\n"


def card(folder: str, name: str, *, quelle: str, titel: str, kern: str, themen: str, typ: str = "prinzip",
         belegart: str = "praxis", status: str = "freigegeben", text: str = "") -> None:
    sha = next(doc["sha256"] for doc in load_manifest(FACH)["dokumente"] if doc["id"] == quelle)
    path = FACH.karten / folder / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntitel: {titel}\nstatus: {status}\nkern: {kern}\nquelle: {quelle}\nquelle_hash: {sha}\ntyp: {typ}\n"
        f"belegart: {belegart}\nseite: 1\nthemen: [{themen}]\nklassenstufen: [6]\nzitat: Grundvorstellungen bei Bruchzahlen\n---\n\n"
        + body(text or titel), encoding="utf-8")


def setup(project) -> None:
    for name in ("buch", "msk-material", "barton", "blog"):
        (project / "quellen-testfach" / f"{name}.txt").write_text(f"{TEXT} ({name})", encoding="utf-8")
    FACH.taxonomie.write_text(
        "typen: {prinzip: {label: P}, methode: {label: M}}\nbelegarten: {praxis: {label: X}, theoretisch: {label: T}}\n"
        "themen:\n  bruch: {label: Brüche, bereich: arithmetik}\n  diagnose: {label: Diagnose, bereich: querschnitt}\n"
        "prinzipien: {}\nkompetenzen: {}\n", encoding="utf-8")
    (FACH.wissen / "_config" / "prioritaet.yaml").write_text(RULES, encoding="utf-8")
    pipeline.update("testfach")
    FACH.dossiers.mkdir(parents=True)
    for doc in load_manifest(FACH)["dokumente"]:
        art = "theorie" if doc["id"] == "buch" else "web"
        (FACH.dossiers / f"{doc['id']}.md").write_text(
            f"---\ntitel: {doc['id']}\nstatus: freigegeben\nquelle: {doc['id']}\nhash: {doc['sha256']}\nthemen: [bruch]\n"
            f"quellenart: {art}\nzitierweise: \"{doc['id']} (2020): Titel.\"\n---\n\nText\n", encoding="utf-8")
    card("buch", "01-anteile", quelle="buch", titel="Anteile handelnd erzeugen", kern="Anteile entstehen durch Falten.",
         themen="bruch", belegart="theoretisch")
    card("buch", "02-rechteck", quelle="buch", titel="Rechteckmodell für Produkte", kern="Das Rechteck zeigt Produkte.",
         themen="bruch")
    card("msk-material", "01-vor-check", quelle="msk-material", titel="Vor-Check und Nach-Check",
         kern="Ein Baustein beginnt mit einem Vor-Check.", themen="diagnose", typ="methode")
    card("barton", "01-practice", quelle="barton", titel="Intelligent Practice", kern="Aufgabenfolgen mit Beziehungen.",
         themen="diagnose", typ="methode")


def paths() -> list[str]:
    return sorted(path.relative_to(FACH.karten).as_posix() for path in FACH.karten.rglob("*.md"))


def test_check_is_read_only_and_returns_a_structured_report(project):
    setup(project)
    card("_neu/buch", "neue-karte", quelle="buch", titel="Neue Diagnose", kern="Ein Diagnosegespräch hilft.",
         themen="diagnose", status="entwurf")
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    report = pipeline.inspect_all("testfach")
    assert report.error_count == 0
    assert report.subjects[0].fach == FACH
    assert pipeline.check_all("testfach", log=lambda message: None) == 0
    after = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    assert before == after


def test_release_and_sort_are_explicit_operations(project):
    setup(project)
    card("_neu/buch", "neue-karte", quelle="buch", titel="Neue Diagnose", kern="Ein Diagnosegespräch hilft.",
         themen="diagnose", status="entwurf")
    original = FACH.karten / "_neu" / "buch" / "neue-karte.md"
    pipeline.apply_checks("testfach", release=True, log=lambda message: None)
    assert original.exists()
    assert "status: freigegeben" in original.read_text()
    pipeline.sort_all("testfach", log=lambda message: None)
    assert not original.exists()


def test_check_sorts_cards_by_area_and_source_with_tags_in_the_file_name(project):
    setup(project)
    assert pipeline.maintain_all("testfach", log=lambda _: None) == 0
    assert paths() == [
        "arithmetik/buch/01-anteile #prinzip #prio1.md",
        "arithmetik/buch/02-rechteck #prinzip #prio2.md",
        "querschnitt/barton/01-practice #methode #prio1 #leitquelle.md",
        "querschnitt/msk-material/01-vor-check #methode #prio1 #leitquelle.md",
    ]
    assert not (FACH.karten / "buch").exists()  # leere alte Ordner werden entfernt
    assert pipeline.maintain_all("testfach", log=lambda _: None) == 0 and len(paths()) == 4  # stabil


def test_lead_sources_come_first_for_their_area_or_purpose(project):
    setup(project)
    order = Ordnung(FACH)
    pflicht, rest = order.auswahl({"bruch"})
    assert [hit.card.dok for hit in pflicht] == ["msk-material"]  # taggt 'bruch' nicht, gehört aber zu Arithmetik
    assert [hit.card.titel for hit in rest] == ["Anteile handelnd erzeugen", "Rechteckmodell für Produkte"]
    pflicht, _ = order.auswahl({"bruch"}, zweck="stundenentwurf")
    assert {hit.card.dok for hit in pflicht} == {"msk-material", "barton"}
    assert order.themen_zu("arithmetik") == {"bruch"} and order.themen_zu("Brüche") == {"bruch"}


def test_new_cards_are_admitted_or_set_aside(project):
    setup(project)
    card("_neu/buch", "03-anteile-falten", quelle="buch", titel="Anteile handelnd erzeugen durch Falten",
         kern="Anteile entstehen durch Falten.", themen="bruch", status="entwurf", text="Anteile handelnd erzeugen")
    card("_neu/blog", "04-schwach", quelle="blog", titel="Bruchstreifen aus Papier", kern="Streifen helfen beim Vergleichen.",
         themen="bruch", status="entwurf", text="Papierstreifen im Klassenraum")
    card("_neu/buch", "05-diagnose", quelle="buch", titel="Diagnosegespräch führen", kern="Gespräche zeigen Denkwege.",
         themen="diagnose", status="entwurf", text="Diagnosegespräch mit einzelnen Lernenden")
    messages: list[str] = []
    assert pipeline.maintain_all("testfach", log=messages.append) == 0
    listing = paths()
    assert "_zurueckgestellt/buch/03-anteile-falten.md" in listing  # Dublette derselben Seite
    assert "_zurueckgestellt/blog/04-schwach.md" in listing  # schwach, Thema hat schon genug Karten
    assert "querschnitt/buch/05-diagnose #prinzip #prio2.md" in listing  # ergänzt ein dünnes Thema
    text = (FACH.karten / "querschnitt/buch/05-diagnose #prinzip #prio2.md").read_text(encoding="utf-8")
    assert "aufnahme: aufgenommen" in text and "status: freigegeben" in text
    assert "Dublette von" in (FACH.karten / "_zurueckgestellt/buch/03-anteile-falten.md").read_text(encoding="utf-8")
    assert not any("03-anteile" in note.ref for note in load_notes(FACH))  # zurückgestellt = nicht in den Seiten
    assert not list((FACH.karten / "_neu").rglob("*.md"))


def test_generated_pages_link_tagged_file_names_and_show_priorities(project):
    setup(project)
    pipeline.maintain_all("testfach", log=lambda _: None)
    pages.build(FACH)
    page = (FACH.wissen / "themen" / "bruch.md").read_text(encoding="utf-8")
    assert "## Zuerst lesen" in page and "Immer berücksichtigen (Leitquellen für arithmetik)" in page
    assert "(../karten/arithmetik/buch/01-anteile%20%23prinzip%20%23prio1.md)" in page
    assert "--zweck stundenentwurf" in page
    assert "Leitquellen (immer berücksichtigen)" in (FACH.wissen / "INDEX.md").read_text(encoding="utf-8")
