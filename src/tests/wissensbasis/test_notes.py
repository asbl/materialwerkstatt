"""Dossiers must carry a full citation; cards that pass on another author's statement must say so (`nach:`)."""
from __future__ import annotations

from wissensbasis import pipeline
from wissensbasis.config import Fach
from wissensbasis.notes import check, load_templates

FACH = Fach("testfach")
SOURCE = "Ein Satz über Grundvorstellungen bei Bruchzahlen steht auf der ersten Seite dieses Textes und ist lang genug."
BODY = ("## Aussage\n\n" + "Die Quelle sagt etwas Wichtiges über Bruchzahlen und ihre Darstellungen im Unterricht. " * 8
        + "\n\n## Prüffrage\n\nWird die Darstellung gewechselt?\n")


def setup(project, *, citation: bool, mention: str, nach: str) -> None:
    (project / "quellen-testfach" / "quelle.txt").write_text(SOURCE, encoding="utf-8")
    (FACH.taxonomie).write_text(
        "typen: {prinzip: {label: P}}\nbelegarten: {praxis: {label: X}}\nthemen: {bruch: {label: B}}\nprinzipien: {}\nkompetenzen: {}\n",
        encoding="utf-8",
    )
    pipeline.update("testfach")
    sha = next(d["sha256"] for d in __import__("wissensbasis.scan", fromlist=["x"]).load_manifest(FACH)["dokumente"])
    FACH.dossiers.mkdir(parents=True)
    zitierweise = 'zitierweise: "Muster, A. (2020): Titel."\n' if citation else ""
    (FACH.dossiers / "quelle.md").write_text(
        f"---\ntitel: T\nstatus: freigegeben\nquelle: quelle\nhash: {sha}\nthemen: [bruch]\nautoren: [Anna Muster]\n{zitierweise}---\n\nText\n", encoding="utf-8")
    (FACH.karten / "quelle").mkdir(parents=True)
    (FACH.karten / "quelle" / "01.md").write_text(
        f"---\ntitel: K\nstatus: freigegeben\nkern: Ein Satz.\nquelle: quelle\nquelle_hash: {sha}\ntyp: prinzip\nbelegart: praxis\nseite: 1\nthemen: [bruch]\n"
        f"klassenstufen: [6]\nzitat: Grundvorstellungen bei Bruchzahlen\n{nach}---\n\n{BODY.replace('Wichtiges', 'Wichtiges ' + mention)}",
        encoding="utf-8")


def test_dossier_without_citation_is_an_error(project):
    setup(project, citation=False, mention="", nach="")
    errors, _ = check(FACH)
    assert any("zitierweise" in error for error in errors)


def test_literature_mentioned_in_the_text_without_nach_is_a_warning(project):
    setup(project, citation=True, mention="(Malle 2004)", nach="")
    errors, warnings = check(FACH)
    assert not errors
    assert any("nach:" in warning and "Malle" in warning for warning in warnings)


def test_nach_silences_the_warning_and_the_sources_own_author_is_ignored(project):
    setup(project, citation=True, mention="(Malle 2004) und (Muster 2020)", nach="nach: [Malle 2004]\n")
    errors, warnings = check(FACH)
    assert not errors and not any("nach:" in warning for warning in warnings)


def test_unquoted_colon_in_the_citation_is_reported_instead_of_crashing(project):
    setup(project, citation=False, mention="", nach="")
    text = (FACH.dossiers / "quelle.md").read_text(encoding="utf-8")
    (FACH.dossiers / "quelle.md").write_text(text.replace("---\n\nText", "zitierweise: Muster, A. (2020): Titel.\n---\n\nText"), encoding="utf-8")
    errors, _ = check(FACH)
    assert any("nicht lesbar" in error and "Anführungszeichen" in error for error in errors)


def test_unknown_status_is_an_error_and_drafts_are_marked_in_the_generated_pages(project):
    setup(project, citation=True, mention="", nach="")
    card = FACH.karten / "quelle" / "01.md"
    card.write_text(card.read_text(encoding="utf-8").replace("status: freigegeben", "status: vielleicht"), encoding="utf-8")
    errors, _ = check(FACH)
    assert any("status 'vielleicht' unbekannt" in error for error in errors)

    card.write_text(card.read_text(encoding="utf-8").replace("status: vielleicht", "status: entwurf"), encoding="utf-8")
    assert not check(FACH)[0]
    from wissensbasis import pages
    pages.build(FACH)
    assert "[Entwurf, nicht freigegeben]" in (FACH.wissen / "themen" / "bruch.md").read_text(encoding="utf-8")
    assert "1 Entwurf" in (FACH.wissen / "INDEX.md").read_text(encoding="utf-8")


def test_explicit_maintenance_releases_clean_draft_but_not_faulty_one(project):
    setup(project, citation=True, mention="", nach="")
    card = FACH.karten / "quelle" / "01.md"
    card.write_text(card.read_text(encoding="utf-8").replace("status: freigegeben", "status: entwurf"), encoding="utf-8")
    faulty = FACH.karten / "quelle" / "02.md"
    faulty.write_text(card.read_text(encoding="utf-8").replace("Grundvorstellungen bei Bruchzahlen", "Nicht im Text"), encoding="utf-8")
    assert pipeline.maintain_all("testfach", log=lambda _: None) == 1
    released = next(FACH.karten.rglob("01 #*.md"))  # nach der Freigabe einsortiert
    assert "status: freigegeben\nfreigegeben_am:" in released.read_text(encoding="utf-8")
    assert "status: entwurf" in faulty.read_text(encoding="utf-8")  # Entwurf mit Fehlern bleibt liegen


def test_load_templates_ignores_vorlagen_index_pages(project):
    source = FACH.vorlagen / "quelle"
    source.mkdir(parents=True)
    (FACH.vorlagen / "README.md").write_text(
        "---\ntitel: Vorlagen\nart: vorlagen-index\nstatus: freigegeben\n---\n\nIndex.",
        encoding="utf-8",
    )
    (source / "workout.md").write_text(
        "---\ntitel: Workout\nart: vorlage\nstatus: freigegeben\nquelle: quelle\n---\n\nTemplate.",
        encoding="utf-8",
    )

    templates = load_templates(FACH)

    assert [template.ref for template in templates] == ["vorlagen/quelle/workout"]


def test_pages_build_lists_task_cards_separately(project):
    setup(project, citation=True, mention="", nach="")
    taxonomy = FACH.taxonomie.read_text(encoding="utf-8")
    FACH.taxonomie.write_text(
        taxonomy
        .replace("typen: {prinzip: {label: P}}", "typen: {prinzip: {label: P}, aufgabe: {label: Aufgabe}}")
        .replace("prinzipien: {}", "prinzipien: {grund: {label: Grund}}")
        + "materialtypen: {diagnose: {label: Diagnose}}\n",
        encoding="utf-8",
    )
    tasks = FACH.karten / "aufgaben"
    tasks.mkdir(parents=True)
    (tasks / "README.md").write_text(
        "---\ntitel: Aufgaben\nstatus: freigegeben\nart: aufgaben-index\n---\n\nIndex.",
        encoding="utf-8",
    )
    (tasks / "bruch.md").write_text(
        """---
titel: "Bruch kleiner als 1/8"
status: freigegeben
typ: aufgabe
materialtypen: [diagnose]
quellen:
  - quelle: quelle
    seite: 1
themen: [bruch]
klassenstufen: [6]
prinzipien: [grund]
---

## Aufgabe

Gib einen Bruch an, der kleiner als 1/8 ist.

## Ziel

Bruchvergleich diagnostizieren.
""",
        encoding="utf-8",
    )

    from wissensbasis import pages
    pages.build(FACH)

    index = (FACH.wissen / "INDEX.md").read_text(encoding="utf-8")
    assert "1 Aufgabenkarten" in index
    assert "Bruch kleiner als 1/8" in index
