"""Vorlagen: examples in the Fördermaterial shorthand, checked like cards and rendered into one catalogue."""
from __future__ import annotations

from wissensbasis import pipeline, vorlagen
from wissensbasis.config import Fach
from wissensbasis.notes import check

FACH = Fach("testfach")
SOURCE = "Maria rechnet 47 + 29 im Kopf, indem sie erst bis 50 springt. Dann vergleicht die Klasse die Wege."
HEADER = "\\newcommand{\\platz}[1][1cm]{\\rule{#1}{1pt}}\n\\newcommand{\\tasknum}[1]{\\textbf{#1}}\n"
LANGUAGE = """kuerzel_header: header.tex
vorschau_header: [header.tex]
latex_basis: [textbf, par, quad]
latex_umgebungen: [center]
"""
TAXONOMY = """typen: {aufgabenformat: {label: A}}
belegarten: {praxis: {label: P}}
themen: {rechnen: {label: Rechnen}}
prinzipien: {ueben: {label: Üben}}
kompetenzen: {}
formate: {workout: {label: Workout}}
modelle: {zahlenstrahl: {label: Zahlenstrahl}}
"""
EXAMPLE = "\\tasknum{1}\\textbf{Ergänze.}\\par\n$58+37=60+\\platz$"


def setup_project(project) -> None:
    (project / "quellen-testfach" / "quelle.txt").write_text(SOURCE, encoding="utf-8")
    (project / "header.tex").write_text(HEADER, encoding="utf-8")
    (project / "blatt.qmd").write_text("---\ntitle: Blatt\n---\n", encoding="utf-8")
    (FACH.wissen / "_config" / "vorlagen.yaml").write_text(LANGUAGE, encoding="utf-8")
    FACH.taxonomie.write_text(TAXONOMY, encoding="utf-8")
    pipeline.update("testfach", log=lambda _: None)
    FACH.dossiers.mkdir(parents=True, exist_ok=True)
    (FACH.dossiers / "quelle.md").write_text("---\ntitel: Quelle\n---\n\nDossier.", encoding="utf-8")


def write_template(name: str, example: str = EXAMPLE, umsetzungen: str = "[blatt.qmd]", kuerzel: str = "[tasknum, platz]",
                   sections: str = "## Variationen\n\n- mehr\n\n## Lehrerfragen\n\n- Warum?\n") -> None:
    directory = FACH.vorlagen / "quelle"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(
        f"""---
titel: "Testvorlage {name}"
status: entwurf
art: vorlage
format: workout
quelle: quelle
belege:
  - seite: 1
    fokus: Test
themen: [rechnen]
klassenstufen: [5]
prinzipien: [ueben]
modell: [zahlenstrahl]
kuerzel: {kuerzel}
umsetzungen: {umsetzungen}
---

## Muster

Wege vergleichen.

## Umsetzung

```latex
{example}
```

{sections}""",
        encoding="utf-8",
    )


def template_messages(messages: list[str]) -> list[str]:
    return [message for message in messages if message.startswith("vorlagen/")]


def test_clean_template_passes_and_is_released(project):
    setup_project(project)
    write_template("workout")

    errors, warnings = check(FACH)

    assert template_messages(errors) == []
    assert template_messages(warnings) == []
    pipeline.maintain_all("testfach", log=lambda _: None)
    assert "status: freigegeben" in (FACH.vorlagen / "quelle" / "workout.md").read_text(encoding="utf-8")


def test_check_reports_unknown_command_missing_worksheet_and_section(project):
    setup_project(project)
    write_template("kaputt", example=EXAMPLE + "\n\\eigenesding{3}", umsetzungen="[fehlt.qmd]", sections="")

    errors, _ = check(FACH)

    name = "vorlagen/quelle/kaputt.md"
    assert f"{name}: \\eigenesding ist weder Kürzel des Headers noch in latex_basis/latex_umgebungen" in errors
    assert f"{name}: Umsetzung fehlt.qmd existiert nicht" in errors
    assert f"{name}: Abschnitt '## Lehrerfragen' fehlt" in errors
    pipeline.maintain_all("testfach", log=lambda _: None)
    assert "status: entwurf" in (FACH.vorlagen / "quelle" / "kaputt.md").read_text(encoding="utf-8")


def test_check_warns_about_examples_copied_from_the_source_and_wrong_kuerzel(project):
    setup_project(project)
    write_template("kopie", example="\\tasknum{1} $47+29=50+\\platz$", kuerzel="[tasknum]")

    _, warnings = check(FACH)

    name = "vorlagen/quelle/kopie.md"
    assert f"{name}: Beispiel steht so auch in der Quelle (47 + 29), eigene Zahlen wählen" in warnings
    assert f"{name}: 'kuerzel' fehlt platz" in warnings


def test_check_rejects_old_markdown_shortcuts(project):
    setup_project(project)
    write_template("alt")
    path = FACH.vorlagen / "quelle" / "alt.md"
    path.write_text(path.read_text(encoding="utf-8").replace("```latex", "```markdown"), encoding="utf-8")

    errors, _ = check(FACH)

    assert any("alter Shortcut-Syntax" in error for error in errors)


def test_build_writes_catalogue_with_header_and_examples(project):
    setup_project(project)
    write_template("workout")

    built, problems = vorlagen.build(FACH, render=False)

    assert problems == []
    assert [template.titel for template in built] == ["Testvorlage workout"]
    catalogue = (FACH.vorlagen / "build" / "vorlagen-katalog.qmd").read_text(encoding="utf-8")
    assert "- ../../../../header.tex" in catalogue
    assert "# Testvorlage workout" in catalogue
    assert EXAMPLE in catalogue


def test_build_reports_templates_without_latex_blocks(project):
    setup_project(project)
    (FACH.vorlagen / "quelle").mkdir(parents=True)
    (FACH.vorlagen / "quelle" / "leer.md").write_text(
        "---\ntitel: Leer\nart: vorlage\nstatus: entwurf\nquelle: quelle\n---\n\n## Muster\n\nNoch ohne Beispiel.\n",
        encoding="utf-8",
    )

    built, problems = vorlagen.build(FACH, render=False)

    assert built == []
    assert problems == ["vorlagen/quelle/leer: kein ```latex-Block mit Beispielaufgaben"]
