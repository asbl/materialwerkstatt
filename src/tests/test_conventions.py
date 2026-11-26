"""Material-Konventionen: Regeln, Ausnahmen und Einbindung in die Editor-Diagnose."""
from pathlib import Path

import pytest

from material_core.conventions import check_conventions, check_file_name, position, scan, visible_text

HEADER = '---\ntitle: "Potenzen"\nsubtitle: ""\n---\n\n'


def codes(path, body, header=HEADER):
    return [finding.code for finding in check_conventions(path, header + body)]


def test_clean_worksheet_has_no_findings():
    body = (
        "## 1 Potenzwerte\n\nBerechne.\n\n"
        "| **a)** $6^0$ | b) $2^{-4}$ |\n|---|---|\n\n"
        "[c)]{.zusatz} Begründe.\n\ne\\) Ergänze die Folge.\n"
    )
    assert codes("unterricht/mathe/ab_potenzen.qmd", body) == []


@pytest.mark.parametrize("heading", ["## 1 · Spurensicherung", "## Vorderseite • Übung", "### Teil A ∙ Rechnen"])
def test_separator_dot_in_heading_is_reported(heading):
    findings = check_conventions("ab_x.qmd", HEADER + heading + "\n")
    assert [finding.code for finding in findings] == ["ueberschrift-trenner"]
    text = HEADER + heading + "\n"
    assert text[findings[0].offset] in "·•∙"


@pytest.mark.parametrize("heading", ["## 471 · 32", "### 14 · 13 mit zwei Teilprodukten", "## (10 + 3) · (10 + 2)", "## Rechne $3 · 4$"])
def test_multiplication_dot_in_heading_is_allowed(heading):
    assert codes("ab_x.qmd", heading + "\n") == []


def test_heading_with_two_dots_reports_only_the_separator():
    assert codes("ab_x.qmd", "## Vorderseite · 379 · 4\n") == ["ueberschrift-trenner"]


@pytest.mark.parametrize("heading", ["## 1. Vom Dreieck zum Einheitskreis", "## Aufgabe 3. Terme"])
def test_dot_after_task_number_is_reported(heading):
    assert codes("ab_x.qmd", heading + "\n") == ["ueberschrift-trenner"]


@pytest.mark.parametrize("heading", ["## 1. Halbjahr", "## 2. binomische Formel", "## 3. Stunde", "## 1.5 Liter", "## 12. November"])
def test_ordinals_and_decimals_in_headings_are_allowed(heading):
    assert codes("ab_x.qmd", heading + "\n") == []


def test_subtitle_is_a_hint_and_points_into_the_frontmatter():
    text = '---\ntitle: "X"\nsubtitle: "Python · E2"\n---\n\nText\n'
    (finding,) = check_conventions("klausur.qmd", text)
    assert (finding.code, finding.level) == ("untertitel", "info")
    assert position(text, finding.offset) == (3, 1)


@pytest.mark.parametrize("value", ['""', "''", "", "null", "~"])
def test_empty_subtitle_is_fine(value):
    assert check_conventions("ab_x.qmd", f'---\ntitle: "X"\nsubtitle: {value}\n---\n\nText\n') == []


@pytest.mark.parametrize("body", ["[c) Begründe deine Antwort.]{.zusatz}\n", "[$x^2$]{.zusatz}\n", "[**c)** Zeige]{.zusatz}\n"])
def test_red_marking_beyond_the_label_is_reported(body):
    assert codes("ab_x.qmd", body) == ["afb-kennzeichnung"]


@pytest.mark.parametrize("body", ["[c)]{.zusatz} Begründe.\n", "[(d)]{.zusatz} Zeige.\n", "## [7]{.zusatz} Rückwärts\n", "[2b)]{.zusatz}\n", "[e\\)]{.zusatz}\n"])
def test_red_marking_of_the_label_alone_is_allowed(body):
    assert codes("ab_x.qmd", body) == []


def test_bold_label_with_task_text_is_reported_on_worksheets_only():
    body = "**a) Zwei Teilprodukte berechnen**\n"
    assert codes("ab_x.qmd", body) == ["afb-kennzeichnung"]
    assert codes("klassenarbeit.qmd", body) == []
    assert codes("ab_x-loesungen.qmd", body) == []


@pytest.mark.parametrize("body", ["**a)** Berechne.\n", "**a) und b)**\n", "**a)** und **b)** gehören zusammen.\n", "**1. richtig**\n"])
def test_bold_labels_without_task_text_are_allowed(body):
    assert codes("ab_x.qmd", body) == []


@pytest.mark.parametrize("body", ["Kern: a, c, e\n", "**Kern:** a, c und e · Zusatz: übrige\n", "Pflicht: 1a) bis 2c)\n"])
def test_differentiation_lists_are_reported(body):
    findings = check_conventions("ab_x.qmd", HEADER + body)
    assert {finding.code for finding in findings} == {"metahinweis"}
    assert all(finding.level == "warning" for finding in findings)


def test_single_label_is_only_a_hint_and_arbeitsweg_a_violation():
    (extra,) = check_conventions("ab_x.qmd", HEADER + "**Zusatz:** $34\\cdot106$\n")
    assert (extra.code, extra.level) == ("metahinweis", "info")
    (way,) = check_conventions("ab_x.qmd", HEADER + "Arbeitsweg: erst lesen, dann rechnen\n")
    assert (way.code, way.level) == ("metahinweis", "warning")


@pytest.mark.parametrize("body", ["Gleiche Basis: a, b, g, j, k.\n", "Basis: 2, Exponent: 5\n", "Die Zusatzfrage: a oder b?\n"])
def test_subject_vocabulary_is_not_a_meta_hint(body):
    assert codes("ab_x.qmd", body) == []


def test_afb_mention_is_reported_on_worksheets_but_not_in_exams():
    assert codes("ab_x.qmd", "Aufgabe 3 gehört zu AFB III.\n") == ["metahinweis"]
    assert codes("klausur.qmd", "Aufgabe 3 gehört zu AFB III.\n") == []


@pytest.mark.parametrize("body", ["Berechne im Heft.\n", "Übertrage ins Heft.\n", "Rechne im Kopf.\n", "Löse auf dem Blatt.\n"])
def test_work_place_hints_are_hints(body):
    (finding,) = check_conventions("ab_x.qmd", HEADER + body)
    assert (finding.code, finding.level) == ("bearbeitungshinweis", "info")


def test_work_place_words_in_other_contexts_are_allowed():
    assert codes("ab_x.qmd", "Kopfübung und Kopfrechnen bleiben. Das Heft ist rot.\n") == []
    assert codes("klausur.qmd", "Berechne im Heft.\n") == []


def test_visible_reflection_question_on_slides_is_reported_but_comments_are_fine():
    assert codes("unterricht/x/slide.qmd", "## Einstieg: Verständnisfrage\n") == ["reflexionsfrage-sichtbar"]
    assert codes("unterricht/x/01 slide.qmd", "Reflexionsfrage: Wann gilt das?\n") == ["reflexionsfrage-sichtbar"]
    assert codes("unterricht/x/slide.qmd", "<!-- Reflexionsfrage: Wann gilt das? -->\n") == []
    assert codes("unterricht/x/ab_x.qmd", "Reflexionsfrage: Wann gilt das?\n") == []


def test_deck_in_praesentation_folder_is_reported():
    assert codes("unterricht/x/praesentation/slide.qmd", "## Titel\n") == ["dateiname"]
    assert codes("unterricht/x/slide.qmd", "## Titel\n") == []


def test_code_comments_and_frontmatter_are_ignored():
    body = (
        "```python\n## 1 · kein Titel\nprint('im Heft')\n```\n\n"
        "`## 2 · auch nicht`\n\n<!-- ## 3 · Kommentar, Kern: a, c -->\n"
    )
    header = '---\ntitle: "A · B"\nsubtitle: ""\n---\n\n'
    assert codes("ab_x.qmd", body, header) == []


def test_visible_text_keeps_offsets():
    text = HEADER + "<!-- x -->\n```\ncode\n```\n`a` Text\n"
    masked = visible_text(text)
    assert len(masked) == len(text)
    assert masked.count("\n") == text.count("\n")
    assert masked.strip() == "Text"


def test_findings_are_sorted_by_position():
    body = "## 2 · B\n\nBerechne im Heft.\n\n## 1 · A\n"
    offsets = [finding.offset for finding in check_conventions("ab_x.qmd", HEADER + body)]
    assert offsets == sorted(offsets) and len(offsets) == 3


def test_file_name_rules():
    assert [f.code for f in check_file_name("unterricht/x/potenzen-hinweise.md")] == ["hinweisdatei"]
    assert [f.code for f in check_file_name("unterricht/x/potenzen_hinweise.md")] == ["hinweisdatei"]
    assert check_file_name("unterricht/x/hinweise.md") == []
    assert [f.code for f in check_file_name("unterricht/x/ab_x.typ")] == ["typ-artefakt"]
    assert check_file_name("src/quarto/templates/worksheet.typst") == []


def test_editor_diagnostics_cap_repeated_findings_and_never_block():
    from material_ui.diagnostics import CONVENTION_LIMIT, convention_issues

    text = HEADER + "".join(f"## {number} · Titel\n\n" for number in range(1, 9))
    issues = convention_issues(Path("ab_x.qmd"), text)
    assert len(issues) == CONVENTION_LIMIT
    assert all(issue["level"] in {"warning", "info"} for issue in issues)
    assert issues[0] == {
        "level": "warning", "code": "ueberschrift-trenner", "title": "Punkt als Trenner in der Überschrift",
        "detail": "Überschriften verwenden keine Punkte oder Mittelpunkte als Trenner.", "line": 6, "column": 6, "length": 1,
    }
    assert "3 weitere Stellen" in issues[-1]["detail"]
    assert "weitere" not in issues[0]["detail"]


def test_scan_walks_sources_and_skips_history_old_material_and_courses(tmp_path):
    bad = HEADER + "## 1 · Titel\n"
    for folder in ("mathe/potenzen", "mathe/potenzen/.material-history", "mathe/alt", "kurse/python", "mathe/build"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
        (tmp_path / folder / "ab_x.qmd").write_text(bad, encoding="utf-8")
    (tmp_path / "mathe/potenzen/potenzen-hinweise.md").write_text("# Hinweise\n", encoding="utf-8")
    results = scan(tmp_path)
    assert [(path.relative_to(tmp_path).as_posix(), line, finding.code) for path, line, finding in results] == [
        ("mathe/potenzen/ab_x.qmd", 6, "ueberschrift-trenner"),
        ("mathe/potenzen/potenzen-hinweise.md", 0, "hinweisdatei"),
    ]
    single = scan(tmp_path / "mathe/alt/ab_x.qmd")
    assert [(line, finding.code) for _path, line, finding in single] == [(6, "ueberschrift-trenner")]


GUARD = Path(__file__).resolve().parents[1] / "material_core" / "conventions_guard.py"
BAD = HEADER + "## 1 · Titel\n"


def run_guard(*args, stdin=""):
    import subprocess
    import sys

    return subprocess.run([sys.executable, "-I", str(GUARD), *args], input=stdin, capture_output=True, text=True)


def test_agent_hook_blocks_violations_in_material_and_ignores_everything_else(tmp_path):
    import json

    for folder in ("unterricht/mathe", "unterricht/mathe/alt", "docs"):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "ab_x.qmd").write_text(BAD, encoding="utf-8")
    (tmp_path / "unterricht/mathe/ab_ok.qmd").write_text(HEADER + "## 1 Titel\n", encoding="utf-8")

    def call(relative):
        payload = json.dumps({"tool_input": {"file_path": str(tmp_path / relative)}})
        import os, subprocess, sys

        return subprocess.run([sys.executable, "-I", str(GUARD), "hook"], input=payload, capture_output=True, text=True,
                              env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)})

    blocked = call("unterricht/mathe/ab_x.qmd")
    assert blocked.returncode == 2
    assert "ueberschrift-trenner" in blocked.stderr and "ab_x.qmd:6" in blocked.stderr
    for relative in ("unterricht/mathe/ab_ok.qmd", "unterricht/mathe/alt/ab_x.qmd", "docs/ab_x.qmd", "unterricht/mathe/fehlt.qmd"):
        assert (call(relative).returncode, call(relative).stderr) == (0, "")
    assert run_guard("hook", stdin="kein json").returncode == 0


def test_git_guard_checks_only_given_files_and_reports_exit_one(tmp_path):
    (tmp_path / "mathe").mkdir()
    (tmp_path / "mathe/ab_x.qmd").write_text(BAD, encoding="utf-8")
    (tmp_path / "mathe/ab_ok.qmd").write_text(HEADER + "## 1 Titel\n", encoding="utf-8")
    assert run_guard("files", "--root", str(tmp_path), "mathe/ab_ok.qmd").returncode == 0
    result = run_guard("files", "--root", str(tmp_path), "mathe/ab_ok.qmd", "mathe/ab_x.qmd")
    assert result.returncode == 1 and "--no-verify" in result.stderr


def test_hook_installer_writes_a_working_pre_commit_and_respects_foreign_hooks(tmp_path):
    import subprocess

    import project_tasks
    from invoke import Context

    context = Context()
    repo = tmp_path / "unterricht"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    project_tasks.konventionen_hook(context, pfad=str(repo))
    hook = repo / ".git/hooks/pre-commit"
    assert hook.stat().st_mode & 0o111
    (repo / "ab_x.qmd").write_text(BAD, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "ab_x.qmd"], check=True)
    commit = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]
    blocked = subprocess.run(commit, capture_output=True, text=True)
    assert blocked.returncode != 0 and "ueberschrift-trenner" in blocked.stderr
    (repo / "ab_x.qmd").write_text(HEADER + "## 1 Titel\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "ab_x.qmd"], check=True)
    assert subprocess.run(commit, capture_output=True, text=True).returncode == 0
    project_tasks.konventionen_hook(context, pfad=str(repo), entfernen=True)
    assert not hook.exists()
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        project_tasks.konventionen_hook(context, pfad=str(repo))
