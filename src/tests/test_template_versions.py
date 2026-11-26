from pathlib import Path
import shutil
import subprocess

import pytest

from material_core.builds import BuildService
from material_core.metadata import read_metadata, set_template
from material_core.template_roots import private_dirname
from material_core.template_versions import TemplateVersions


@pytest.fixture
def versions(tmp_path):
    templates = tmp_path / "src/quarto/templates"
    templates.mkdir(parents=True)
    (templates / "worksheet-test.typst").write_text('#let body-font = "DejaVu Sans"\n$layout.typst()$')
    (templates / "layout.typst").write_text('#set text(font: body-font, size: 10pt, lang: "de")\n$body$\n')
    filters = tmp_path / "src/quarto/filters"
    filters.mkdir()
    # Exercise the production dispatch guard, including PANDOC_SCRIPT_FILE resolution.
    shutil.copy(Path(__file__).parents[1] / "quarto/filters/exam.lua", filters / "exam.lua")
    for path in (Path(__file__).parents[1] / "quarto/filters").glob("*.lua"):
        shutil.copy(path, filters / path.name)
    (tmp_path / "_quarto.yml").write_text(
        'filters:\n  - src/quarto/filters/exam.lua\n'
        'template-partials:\n  - src/quarto/templates/layout.typst\n'
        'format:\n  typst:\n    template: src/quarto/templates/worksheet-test.typst\n')
    return TemplateVersions(tmp_path)


def document(versions):
    source = versions.root / "ab_test.qmd"
    text = '---\nformat:\n  typst:\n    template: worksheet-test.typst\n---\nHello worksheet\n'
    reference = versions.initial("src/quarto/templates/worksheet-test.typst")
    text = versions.bind(text, reference)
    source.write_text(text)
    return source, text, reference


def test_new_settings_reuse_layout_and_do_not_change_existing_document(versions):
    source, text, v1 = document(versions)
    service = BuildService(versions.root, subprocess.run)
    original = service.render_text(source, text)
    draft = versions.draft(v1)
    versions.save_draft(draft, "12pt", "Größere Schrift")
    v2 = versions.publish(draft, make_default=True)
    assert versions.load(v1)["layout"] == versions.load(v2)["layout"]
    assert versions.latest(v1) == v2
    assert versions.publish(draft, True) == v2  # retry is idempotent
    assert service.render_text(source, text) == original
    updated = service.render_text(source, versions.bind(text, v2))
    assert read_metadata(updated)["template-fontsize"] == "12pt"
    assert versions.bind(versions.bind(text, v2), v1) == text
    assert read_metadata(set_template(text, "other.typst", "typst")).get("template-release") is None


def test_live_layout_and_filter_changes_cannot_change_release(versions):
    source, text, v1 = document(versions)
    service = BuildService(versions.root, subprocess.run)
    before = service.render_text(source, text)
    (versions.support / "templates/layout.typst").write_text("BROKEN NEW LAYOUT")
    (versions.support / "filters/student-dialog.lua").write_text("BROKEN NEW HELPER")
    assert service.render_text(source, text) == before
    assert versions.initial("worksheet-test.typst") == v1


def test_frozen_project_font_paths_work_for_nested_documents(versions):
    config = versions.root / "_quarto.yml"
    config.write_text(config.read_text() + "    font-paths:\n      - src/quarto/fonts/static\n")
    source, text, reference = document(versions)
    nested = versions.root / "build/scratch/nested/ab_probe.qmd"
    nested.parent.mkdir(parents=True)
    rendered = read_metadata(versions.render(nested, text))
    paths = rendered["format"]["typst"]["font-paths"]
    assert (nested.parent / paths[0]).resolve() == versions.root / "src/quarto/fonts/static"
    assert versions.load(reference)["defaults"]["typst"]["font-paths"] == ["src/quarto/fonts/static"]


def test_refresh_preserves_selected_fontsize_and_existing_releases(versions):
    _, _, initial = document(versions)
    draft = versions.draft(initial)
    versions.save_draft(draft, "14pt", "Gut lesbare Grundschrift")
    selected = versions.publish(draft, make_default=True)
    before = versions.path(selected).read_bytes()
    (versions.support / "templates/layout.typst").write_text("$body$\n")
    refreshed = versions.initial("worksheet-test.typst", refresh=True, note="Neue Überschriften")
    assert versions.load(refreshed)["settings"] == {"fontsize": "14pt"}
    assert versions.load(refreshed)["note"] == "Neue Überschriften"
    assert versions.load(refreshed)["layout"] != versions.load(selected)["layout"]
    assert versions.path(selected).read_bytes() == before


@pytest.mark.parametrize("corrupt", ["layout", "manifest", "missing"])
def test_corrupt_or_missing_release_fails_even_for_cached_build(versions, corrupt):
    source, text, ref = document(versions)
    release = versions.load(ref)
    if corrupt == "layout":
        (versions.path(release["layout"]) / "templates/layout.typst").write_text("modified")
    elif corrupt == "manifest":
        path = versions.path(ref)
        path.write_text(path.read_text().replace('"version": 1', '"version": 99'))
    else:
        versions.path(ref).unlink()
    with pytest.raises(ValueError):
        BuildService(versions.root, subprocess.run).render_signature(source, text)


@pytest.mark.parametrize("value", ["5pt", "32.1pt", "33pt", "12", "12pt; evil()", 12, None])
def test_fontsize_validation(versions, value):
    _, _, ref = document(versions)
    with pytest.raises(ValueError):
        versions.save_draft(versions.draft(ref), value, "")


def test_document_fontsize_override_and_preview_do_not_mutate_release(versions):
    source, text, ref = document(versions)
    draft = versions.draft(ref)
    versions.save_draft(draft, "13pt", "")
    from material_core.metadata import set_fields
    preview = set_fields(text, {"template-preview-draft": draft})
    rendered = read_metadata(versions.render(source, preview))
    assert rendered["template-fontsize"] == "13pt"
    assert "template-preview-draft" not in rendered
    assert versions.load(ref)["settings"] == {}
    v2 = versions.publish(draft)
    override = set_fields(versions.bind(text, v2), {"fontsize": "14pt"})
    assert read_metadata(versions.render(source, override))["template-fontsize"] == "14pt"


def test_migration_pins_inherited_templates_to_v1_and_is_idempotent(versions):
    _, _, v1 = document(versions)
    draft = versions.draft(v1)
    versions.save_draft(draft, "12pt", "")
    versions.publish(draft, True)
    source = versions.root / "inherited.qmd"
    source.write_text('---\ntitle: "Unverändert"\nformat:\n  typst:\n    output-file: custom.pdf\n---\nBody\n')
    report = versions.migrate([source], write=True)
    assert len(report["pinned"]) == 1
    metadata = read_metadata(source.read_text())
    assert metadata["template-release"] == v1
    assert metadata["format"]["typst"]["output-file"] == "custom.pdf"
    assert versions.migrate([source], write=True)["unchanged"] == ["inherited.qmd"]


def test_local_catalog_never_exports_protected_templates(versions):
    catalog = versions.root / "src/material_core"
    catalog.mkdir()
    (catalog / "template-designs.json").write_text("[]")
    private = versions.support / private_dirname()
    private.mkdir(exist_ok=True)
    (private / "template-designs.json").write_text('[{"id": "test"}]')
    reference = versions.initial("worksheet-test.typst")
    assert reference.startswith(f"src/quarto/{private_dirname()}/")
    assert not (versions.root / "src/quarto/template-releases").exists()


@pytest.mark.skipif(not shutil.which("quarto"), reason="Quarto ist nicht installiert")
def test_actual_typst_build_keeps_v1_fontsize_after_v2_and_live_partial_change(versions):
    import pymupdf
    source, text, v1 = document(versions)
    service = BuildService(versions.root, subprocess.run)
    original = service.build_document(source)
    def size(pdf):
        with pymupdf.open(pdf) as doc:
            return [round(span["size"], 1) for page in doc for block in page.get_text("dict")["blocks"]
                    if "lines" in block for line in block["lines"] for span in line["spans"]
                    if "Hello worksheet" in span["text"]][0]
    assert size(original.pdf_path) == 10
    draft = versions.draft(v1)
    versions.save_draft(draft, "12pt", "")
    v2 = versions.publish(draft, True)
    (versions.support / "templates/layout.typst").write_text('#panic("live partial must never render")')
    assert size(service.build_document(source).pdf_path) == 10
    source.write_text(versions.bind(text, v2))
    assert size(service.build_document(source).pdf_path) == 12


def test_refreshed_layout_preserves_old_release(versions):
    source, text, v1 = document(versions)
    before = versions.render(source, text)
    layout = versions.support / 'templates/layout.typst'
    layout.write_text(layout.read_text().replace('10pt', '10.5pt'))
    v2 = versions.initial('worksheet-test.typst', refresh=True)
    assert versions.load(v2)['version'] == 2
    assert versions.load(v1)['layout'] != versions.load(v2)['layout']
    assert versions.render(source, text) == before
    assert versions.render(source, versions.bind(text, v2)) != before


def test_update_offer_remembers_decline_and_asks_again_for_next_release(versions):
    source, text, v1 = document(versions)
    v2 = versions.initial("worksheet-test.typst", refresh=True)
    # Offer the newest release even if the new-document default remains v1.
    offer = versions.update_offer(text)
    assert offer["release"] == v2
    skipped = versions.review_update(text, v2, False)
    assert read_metadata(skipped)["template-release"] == v1
    assert read_metadata(skipped)["template-update-reviewed"] == v2
    assert TemplateVersions(versions.root).update_offer(skipped) is None
    assert skipped.split("---", 2)[-1] == text.split("---", 2)[-1]
    v3 = versions.initial("worksheet-test.typst", refresh=True)
    assert versions.update_offer(skipped)["release"] == v3
    accepted = versions.review_update(skipped, v3, True)
    assert read_metadata(accepted)["template-release"] == v3
    assert read_metadata(accepted)["template-update-reviewed"] == v3
    assert versions.update_offer(accepted) is None
    with pytest.raises(ValueError, match="geändert"):
        versions.review_update(text, v2, True)
    assert versions.update_offer("Unversionierter Inhalt\n") is None


def test_build_update_requires_answer_and_keeps_it_across_builds(versions):
    from material_core.template_updates import review_before_build
    source, text, v1 = document(versions)
    v2 = versions.initial("worksheet-test.typst", refresh=True)
    with pytest.raises(ValueError, match="Entscheidung erforderlich"):
        review_before_build(versions.root, source, interactive=False)
    assert source.read_text() == text
    assert review_before_build(versions.root, source, "keep")
    assert read_metadata(source.read_text())["template-release"] == v1
    assert not review_before_build(versions.root, source, interactive=False)
    v3 = versions.initial("worksheet-test.typst", refresh=True)
    prompts = []
    assert review_before_build(versions.root, source, interactive=True,
                               ask=lambda message: prompts.append(message) or "j")
    assert len(prompts) == 1
    assert read_metadata(source.read_text())["template-release"] == v3
    assert not review_before_build(versions.root, source, interactive=False)


def test_build_update_does_not_overwrite_edits_during_question(versions):
    from material_core.template_updates import review_before_build
    source, text, v1 = document(versions)
    versions.initial("worksheet-test.typst", refresh=True)
    changed = text + "Neue Aufgabe\n"
    def answer(message):
        source.write_text(changed)
        return "j"
    with pytest.raises(ValueError, match="während"):
        review_before_build(versions.root, source, interactive=True, ask=answer)
    assert source.read_text() == changed
