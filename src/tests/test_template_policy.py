"""Vorlagen sind standardmaessig privat: Aufloesung, Freigabeprozess und Sperren."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from material_core import oss_check, template_policy
from material_core.template_roots import (
    all_template_names, find_template, is_private, logical_relative, private_dirname, sibling,
)
from material_core.template_versions import LOCAL_STORE, STORE, TemplateVersions

PRIV = private_dirname()   # "_local"; Tests setzen MATERIAL_PRIVATE_DIR teils auf einen anderen Ordner
BUILTIN_TEMPLATE = "#let design-name = \"Offen\"\n"


def make_root(tmp_path: Path) -> Path:
    support = tmp_path / "src/quarto"
    (support / "templates").mkdir(parents=True)
    (support / "template-releases").mkdir()
    (support / PRIV / "templates").mkdir(parents=True)
    (tmp_path / "src/material_core").mkdir(parents=True)
    (support / "templates/worksheet-offen.typst").write_text(BUILTIN_TEMPLATE, encoding="utf-8")
    (support / "templates/student-fields.typst").write_text("// Partial\n", encoding="utf-8")
    (support / "builtin-templates.json").write_text(json.dumps({
        "templates": ["student-fields.typst", "worksheet-offen.typst"],
        "release-stems": [],
        "designs": ["offen"],
    }), encoding="utf-8")
    (tmp_path / "src/material_core/template-designs.json").write_text(json.dumps([{"id": "offen", "label": "Offen"}]))
    (support / PRIV / "template-designs.json").write_text(json.dumps([{"id": "neu", "label": "Neu"}]))
    (support / PRIV / "templates/worksheet-neu.typst").write_text(
        '#let design-name = "Neu"\n$student-fields.typst()$\n$neu-layout.typst()$\n', encoding="utf-8")
    (support / PRIV / "templates/neu-layout.typst").write_text("// privates Partial\n", encoding="utf-8")
    (tmp_path / "_quarto.yml").write_text("{}\n", encoding="utf-8")
    return tmp_path


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args], cwd=root, check=True,
                   capture_output=True)


def test_templates_resolve_by_name_in_both_folders_and_builtin_wins(tmp_path):
    root = make_root(tmp_path)
    support = root / "src/quarto"
    assert find_template("worksheet-offen.typst", support) == support / "templates/worksheet-offen.typst"
    assert find_template("worksheet-neu.typst", support) == support / PRIV / "templates/worksheet-neu.typst"
    assert find_template("gibt-es-nicht.typst", support) is None
    assert {"worksheet-offen.typst", "worksheet-neu.typst"} <= all_template_names(support)
    assert is_private(find_template("worksheet-neu.typst", support), support)
    assert not is_private(find_template("worksheet-offen.typst", support), support)
    # Private Vorlagen finden eingebaute Partials wie Geschwisterdateien (und umgekehrt).
    neu = find_template("worksheet-neu.typst", support)
    assert sibling(neu, "student-fields.typst", support) == support / "templates/student-fields.typst"
    assert logical_relative(neu, support) == "templates/worksheet-neu.typst"


def test_check_reports_everything_not_explicitly_released(tmp_path):
    root = make_root(tmp_path)
    assert template_policy.check(root) == []
    (root / "src/quarto/templates/worksheet-heimlich.typst").write_text("x", encoding="utf-8")
    (root / "src/quarto/template-releases/worksheet-heimlich").mkdir()
    problems = template_policy.check(root)
    assert any("worksheet-heimlich.typst" in problem and "nicht freigegeben" in problem for problem in problems)
    assert any("Freigabe-Ordner" in problem for problem in problems)


def test_check_rejects_embedded_images_and_denylisted_names(tmp_path):
    root = make_root(tmp_path)
    (root / "src/quarto" / PRIV / "brand-denylist.txt").write_text("# Sperrliste\nfremdmarke\n", encoding="utf-8")
    (root / "src/quarto/templates/worksheet-offen.typst").write_text(
        "// Fremdmarke\n#image(bytes(\"" + "A" * 500 + "\"))\n", encoding="utf-8")
    problems = template_policy.check(root)
    assert any("gesperrter Begriff" in problem for problem in problems)
    assert any("eingebettete Bilddaten" in problem for problem in problems)


def test_release_requires_explicit_confirmation_and_moves_everything(tmp_path):
    root = make_root(tmp_path)
    versions = TemplateVersions(root)
    reference = versions.initial("worksheet-neu.typst")
    assert reference.startswith(LOCAL_STORE), "Vorlagen sind standardmaessig privat: Freigaben liegen im privaten Speicher"
    assert versions.load(reference)["template"] == "worksheet-neu.typst"
    # Ohne Bestaetigung passiert nichts; der Probelauf zeigt die privaten Abhaengigkeiten.
    with pytest.raises(template_policy.PolicyError, match="lizenz-bestaetigt"):
        template_policy.freigeben(root, "worksheet-neu", lizenz_bestaetigt=False)
    preview = template_policy.freigeben(root, "worksheet-neu", lizenz_bestaetigt=False, dry_run=True)
    assert any("neu-layout.typst" in line for line in preview)
    assert not (root / "src/quarto/templates/worksheet-neu.typst").exists()

    report = template_policy.freigeben(root, "worksheet-neu", lizenz_bestaetigt=True)
    assert any("builtin-templates.json" in line for line in report)
    assert (root / "src/quarto/templates/worksheet-neu.typst").is_file()
    assert (root / "src/quarto/templates/neu-layout.typst").is_file()
    assert not (root / "src/quarto" / PRIV / "templates/worksheet-neu.typst").exists()
    manifest = template_policy.load_manifest(root)
    assert {"worksheet-neu.typst", "neu-layout.typst"} <= set(manifest["templates"])
    assert "worksheet-neu" in manifest["release-stems"] and "neu" in manifest["designs"]
    assert [d["id"] for d in json.loads((root / "src/material_core/template-designs.json").read_text())] == ["offen", "neu"]
    assert json.loads((root / "src/quarto" / PRIV / "template-designs.json").read_text()) == []
    assert template_policy.check(root) == []
    # Die freigegebene Version bleibt ueber den privaten Bezug lesbar (Frontmatter muss nicht umgeschrieben werden).
    assert TemplateVersions(root).load(reference)["template"] == "worksheet-neu.typst"


def test_release_is_refused_for_denylisted_or_unknown_templates(tmp_path):
    root = make_root(tmp_path)
    (root / "src/quarto" / PRIV / "brand-denylist.txt").write_text("privates partial\n", encoding="utf-8")
    with pytest.raises(template_policy.PolicyError, match="abgelehnt"):
        template_policy.freigeben(root, "worksheet-neu", lizenz_bestaetigt=True)
    with pytest.raises(template_policy.PolicyError, match="Keine private Vorlage"):
        template_policy.freigeben(root, "worksheet-fehlt", lizenz_bestaetigt=True)


def test_release_scans_frozen_layouts_and_refuses_existing_release_folders(tmp_path):
    root = make_root(tmp_path)
    versions = TemplateVersions(root)
    versions.initial("worksheet-neu.typst")
    store = root / "src/quarto" / PRIV / "template-releases"
    layouts = [path for path in (store / "layouts").rglob("*.typst") if path.name == "worksheet-neu.typst"]
    assert layouts, "Layout-Snapshot der Vorlage erwartet"
    layouts[0].write_text(layouts[0].read_text(encoding="utf-8") + "// Fremdmarke im alten Snapshot\n", encoding="utf-8")
    (root / "src/quarto" / PRIV / "brand-denylist.txt").write_text("fremdmarke\n", encoding="utf-8")
    with pytest.raises(template_policy.PolicyError, match="gesperrter Begriff"):
        template_policy.freigeben(root, "worksheet-neu", lizenz_bestaetigt=True)
    (root / "src/quarto" / PRIV / "brand-denylist.txt").unlink()
    (root / "src/quarto/template-releases/worksheet-neu").mkdir(parents=True)
    with pytest.raises(template_policy.PolicyError, match="existiert bereits"):
        template_policy.freigeben(root, "worksheet-neu", lizenz_bestaetigt=True)
    assert (root / "src/quarto" / PRIV / "templates/worksheet-neu.typst").is_file()


def test_legacy_public_release_paths_resolve_to_the_private_store(tmp_path):
    root = make_root(tmp_path)
    versions = TemplateVersions(root)
    private = versions.initial("worksheet-neu.typst")
    legacy = private.replace(LOCAL_STORE, STORE)
    assert not (root / legacy).exists()
    assert versions.path(legacy) == versions.path(private)
    assert versions.load(legacy)["template"] == "worksheet-neu.typst"


def test_tracked_files_outside_the_manifest_are_found_for_the_commit_hook(tmp_path):
    root = make_root(tmp_path)
    git(root, "init", "-q")
    (root / "src/quarto/templates/worksheet-heimlich.typst").write_text("x", encoding="utf-8")
    git(root, "add", "-A", "--force")
    assert template_policy.tracked_outside_manifest(root) == ["src/quarto/templates/worksheet-heimlich.typst"]
    assert template_policy.main(["--root", str(root), "tracked"]) == 1


def test_oss_check_flags_private_paths_secrets_and_unreleased_templates(tmp_path):
    root = make_root(tmp_path)
    (root / "src/quarto" / PRIV / "oss-denylist.txt").write_text("meineschule\n", encoding="utf-8")
    git(root, "init", "-q")
    # Absichtlich unzulaessige Beispieldaten erst im Test zusammensetzen, damit
    # der Scanner seine eigenen Testquellen nicht als private Inhalte meldet.
    user_path = "/" + "home/example/Dokumente/x"
    email = "@".join(("teacher", "school.invalid"))
    (root / "notes.md").write_text(f"Pfad: {user_path}\nKontakt: {email}\n"
                                   "Gesehen bei MeineSchule\n", encoding="utf-8")
    (root / ".env").write_text("TOKEN=geheim\n", encoding="utf-8")
    (root / "unterricht").mkdir()
    (root / "unterricht/ab.qmd").write_text("x", encoding="utf-8")
    (root / "ok.md").write_text("Alles sauber, siehe https://example.org und a@example.org\n", encoding="utf-8")
    git(root, "add", "-A", "--force")
    problems = "\n".join(oss_check.scan(root))
    assert "notes.md:1: absoluter Benutzerpfad" in problems
    assert "notes.md:2: E-Mail-Adresse" in problems
    assert "notes.md:3: persoenlicher Bezug" in problems
    assert ".env: darf nicht versioniert werden" in problems
    assert "unterricht/ab.qmd: darf nicht versioniert werden" in problems
    assert "ok.md" not in problems
    # Nur vorgemerkte Dateien: ein sauberer Commit bleibt moeglich.
    git(root, "reset", "-q")
    git(root, "add", "ok.md")
    assert oss_check.scan(root, staged=True) == []


def test_staged_check_reads_the_index_not_the_working_tree(tmp_path):
    root = make_root(tmp_path)
    git(root, "init", "-q")
    user_path = "/" + "home/example/x"
    (root / "notes.md").write_text(f"Pfad: {user_path}\n", encoding="utf-8")
    git(root, "add", "notes.md")
    (root / "notes.md").write_text("sauber\n", encoding="utf-8")   # nachtraeglich bereinigt, aber nicht vorgemerkt
    assert any("absoluter Benutzerpfad" in problem for problem in oss_check.scan(root, staged=True))
