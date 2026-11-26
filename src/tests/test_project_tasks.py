from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import project_tasks  # noqa: E402


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _minimal_quarto(root: Path) -> None:
    _write(
        root / "_quarto.yml",
        "\n".join(
            [
                "project:",
                "  type: default",
                "  render:",
                "    - unterricht/mathematik/klasse-05/**/*.qmd",
                "    - unterricht/organisation/foerderplaene/**/*.qmd",
                "    - '!**/*-old.qmd'",
                "    - '!**/*-entwurf.qmd'",
                "",
            ]
        ),
    )


def test_tikz_sources_exclude_latex_fragments_and_libraries(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    standalone = _write(tmp_path / "unterricht/assets/zeichnung.tex", "\\documentclass[tikz]{standalone}\n")
    _write(tmp_path / "unterricht/assets/tabelle.tex", "\\begin{tabularx}{\\textwidth}{XX}\n")
    _write(tmp_path / "unterricht/assets/zeichnung-lib.tex", "\\documentclass{standalone}\n")
    _write(tmp_path / ".cache/assets/zeichnung.tex", "\\documentclass{standalone}\n")

    assert project_tasks._tikz_svg_sources() == [standalone]


def test_tex_sources_finden_nur_eigenstaendige_dokumente(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    brief = _write(tmp_path / "unterricht/organisation/elternbriefe/2526/brief.tex", "\\input{../templates/elternbrief-template.tex}\n")
    _write(tmp_path / "unterricht/organisation/elternbriefe/templates/elternbrief-template.tex", "\\documentclass{letter}\n")
    _write(tmp_path / "src/quarto/templates/latex-template.tex", "\\documentclass{article}\n")
    _write(tmp_path / "unterricht/assets/zeichnung.tex", "\\documentclass[tikz]{standalone}\n")
    _write(tmp_path / "unterricht/foerder-header.tex", "\\newcommand{\\foo}{1}\n")
    _write(tmp_path / ".cache/brief.tex", "\\documentclass{letter}\n")
    _write(tmp_path / "unterricht/alt/brief.tex", "\\documentclass{letter}\n")

    assert project_tasks._tex_sources() == [brief]


def _fake_pdflatex_run(command, *, cwd=None, **kwargs):
    output_dir = Path(command[command.index("-output-directory") + 1])
    stem = Path(command[-1]).stem
    (output_dir / f"{stem}.pdf").write_bytes(b"%PDF")
    (output_dir / f"{stem}.aux").write_text("", encoding="utf-8")


def test_build_tex_dokument_legt_pdf_zentral_ab(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    brief = _write(tmp_path / "unterricht/organisation/elternbriefe/2526/brief.tex", "\\documentclass{letter}\n")
    monkeypatch.setattr(project_tasks, "_run", _fake_pdflatex_run)

    project_tasks.build.body(None, source=str(brief))

    pdf = tmp_path / "build/pdf/unterricht/organisation/elternbriefe/2526/brief.pdf"
    assert pdf.read_bytes() == b"%PDF"
    assert (tmp_path / "build/artefakte/unterricht/organisation/elternbriefe/2526/brief.aux").is_file()
    assert not (tmp_path / "build/artefakte/unterricht/organisation/elternbriefe/2526/brief.pdf").exists()


def test_build_ohne_quelle_baut_auch_tex_dokumente(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    brief = _write(tmp_path / "unterricht/organisation/elternbriefe/2526/brief.tex", "\\documentclass{letter}\n")
    monkeypatch.setattr(project_tasks, "_qmd_sources", lambda: [])
    monkeypatch.setattr(project_tasks, "_run", _fake_pdflatex_run)

    project_tasks.build.body(None)

    assert (tmp_path / "build/pdf/unterricht/organisation/elternbriefe/2526/brief.pdf").is_file()


class _FakeBuildService(project_tasks.BuildService):
    """BuildService-Stub: schreibt das PDF zentral ab und zaehlt die Render-Aufrufe."""

    aufrufe: list[Path] = []

    def __init__(self, root, runner):
        super().__init__(root, runner)

    def build_document(self, document, quarto=None):
        _FakeBuildService.aufrufe.append(document)
        pdf = project_tasks._pdf_dir(document) / f"{document.stem}.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF")
        from material_core.filesystem import text_revision
        from types import SimpleNamespace

        return SimpleNamespace(
            pdf_path=pdf,
            source_revision=text_revision(document.read_text(encoding="utf-8")),
            stdout="",
        )


def test_build_inkrementell_ueberspringt_unveraenderte_quelle(tmp_path, monkeypatch, capsys):
    _FakeBuildService.aufrufe.clear()
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _minimal_quarto(tmp_path)
    quelle = _write(tmp_path / "unterricht/mathematik/klasse-05/blatt.qmd", "---\ntitle: Blatt\n---\n\nText.\n")
    monkeypatch.setattr(project_tasks, "BuildService", _FakeBuildService)
    monkeypatch.setattr(project_tasks, "_qmd_sources", lambda: [quelle])
    monkeypatch.setattr(project_tasks, "_tex_sources", lambda: [])

    project_tasks.build.body(None)
    project_tasks.build.body(None)

    assert len(_FakeBuildService.aufrufe) == 1
    assert "unveraendert" in capsys.readouterr().out


def test_build_baut_nach_quellaenderung_und_mit_alles(tmp_path, monkeypatch):
    _FakeBuildService.aufrufe.clear()
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _minimal_quarto(tmp_path)
    quelle = _write(tmp_path / "unterricht/mathematik/klasse-05/blatt.qmd", "---\ntitle: Blatt\n---\n\nText.\n")
    monkeypatch.setattr(project_tasks, "BuildService", _FakeBuildService)
    monkeypatch.setattr(project_tasks, "_qmd_sources", lambda: [quelle])
    monkeypatch.setattr(project_tasks, "_tex_sources", lambda: [])

    project_tasks.build.body(None)
    quelle.write_text("---\ntitle: Blatt\n---\n\nGeaenderter Text.\n", encoding="utf-8")
    project_tasks.build.body(None)
    project_tasks.build.body(None, alles=True)

    assert len(_FakeBuildService.aufrufe) == 3


def test_build_baut_wenn_input_im_quellordner_neuer_ist(tmp_path, monkeypatch):
    _FakeBuildService.aufrufe.clear()
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _minimal_quarto(tmp_path)
    quelle = _write(tmp_path / "unterricht/mathematik/klasse-05/blatt.qmd", "---\ntitle: Blatt\n---\n\nText.\n")
    monkeypatch.setattr(project_tasks, "BuildService", _FakeBuildService)
    monkeypatch.setattr(project_tasks, "_qmd_sources", lambda: [quelle])
    monkeypatch.setattr(project_tasks, "_tex_sources", lambda: [])

    project_tasks.build.body(None)
    _write(quelle.parent / "assets/zeichnung.svg", "<svg/>")
    project_tasks.build.body(None)

    assert len(_FakeBuildService.aufrufe) == 2


def test_inputs_neuer_als_pdf_ignoriert_build_rueckstaende(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    quelle = _write(tmp_path / "unterricht/mathematik/klasse-05/blatt.qmd", "Text\n")
    pdf = _write(tmp_path / "build/pdf/unterricht/mathematik/klasse-05/blatt.pdf", "%PDF")
    _write(quelle.parent / "blatt.log", "Rueckstand")

    assert not project_tasks._inputs_neuer_als_pdf(quelle, pdf)
    _write(quelle.parent / "include.tex", "\\newcommand{\\x}{1}")
    assert project_tasks._inputs_neuer_als_pdf(quelle, pdf)


def test_check_output_layout_rejects_pdf_beside_excluded_qmd(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    source = _write(tmp_path / "unterricht/mathematik/klasse-05/blatt-entwurf.qmd")
    _write(source.with_suffix(".pdf"))

    with pytest.raises(SystemExit, match="blatt-entwurf.pdf"):
        project_tasks.check_output_layout.body(None)


def test_check_output_layout_accepts_central_output(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _write(tmp_path / "unterricht/mathematik/klasse-05/blatt.qmd")
    _write(tmp_path / "build/pdf/unterricht/mathematik/klasse-05/blatt.pdf")

    project_tasks.check_output_layout.body(None)


def test_check_output_layout_rejects_foreign_pdf_in_unterricht(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    source = _write(tmp_path / "unterricht/mathematik/klasse-05/blatt.qmd")
    _write(tmp_path / "build/pdf/unterricht/mathematik/klasse-05/blatt.pdf")
    _write(source.parent / "original.pdf")

    with pytest.raises(SystemExit, match="original.pdf"):
        project_tasks.check_output_layout.body(None)


def test_verlinse_importierte_pdfs_verlinkt_passende_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _write(tmp_path / "wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/01-erste-ubungen.pdf", "%PDF")
    qmd = _write(
        tmp_path / "unterricht/klasse-10/arbeitsblaetter/01-erste-ubungen-entwurf.qmd",
        "---\n"
        "title: 01 Erste Übungen\n"
        "material:\n"
        "  import:\n"
        "    kind: onlyoffice\n"
        "    mode: positioned-draft\n"
        "    source: _eingang/onlyoffice/klasse-10/trigonometrie/01 Erste Übungen.docx\n"
        "    source-pages: 5\n"
        "---\n\nKörper.\n",
    )
    _write(
        qmd.parent / "02-training-entwurf.qmd",
        "---\ntitle: Ohne Import\n---\n\nKörper.\n",
    )

    project_tasks._verlinse_importierte_pdfs(
        qmd.parent, "arbeitsblatt/mathematik/klasse-10/trigonometrie", trocken=False
    )

    text = qmd.read_text(encoding="utf-8")
    assert "source: _eingang/onlyoffice" not in text
    assert "source-pdf: wissen/arbeitsblatt/mathematik/klasse-10/trigonometrie/01-erste-ubungen.pdf" in text
    assert "Körper.\n" in text
    ohne = (qmd.parent / "02-training-entwurf.qmd").read_text(encoding="utf-8")
    assert "source-pdf" not in ohne


def test_check_output_layout_rejects_legacy_pdf_folder(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    source = _write(tmp_path / "unterricht/mathematik/klasse-05/blatt.qmd")
    _write(source.parent / "pdf/blatt.pdf")

    with pytest.raises(SystemExit, match="blatt.pdf"):
        project_tasks.check_output_layout.body(None)


def test_check_output_layout_checks_configured_output_name(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    source = _write(tmp_path / "unterricht/mathematik/klasse-05/blatt.qmd", '---\noutput-file: "druck.pdf"\n---\n')
    _write(source.parent / "druck.pdf")

    with pytest.raises(SystemExit, match="druck.pdf"):
        project_tasks.check_output_layout.body(None)


def test_check_output_layout_rejects_typst_artifact_without_matching_qmd(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _write(tmp_path / "src/quarto/templates/versehentlich.typ")

    with pytest.raises(SystemExit, match="versehentlich.typ"):
        project_tasks.check_output_layout.body(None)


def test_check_output_layout_accepts_typst_sources_and_build_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _write(tmp_path / "src/quarto/templates/vorlage.typst")
    _write(tmp_path / "unterricht/mathematik/build/blatt.typ")
    _write(tmp_path / "build/vorschau.typ")

    project_tasks.check_output_layout.body(None)


def test_qmd_sources_follow_quarto_render_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _minimal_quarto(tmp_path)
    included = _write(tmp_path / "unterricht/mathematik/klasse-05/thema/blatt.qmd")
    direct = _write(tmp_path / "unterricht/mathematik/klasse-05/direkt.qmd")
    _write(tmp_path / "unterricht/mathematik/klasse-05/thema/blatt-old.qmd")
    _write(tmp_path / "unterricht/mathematik/klasse-05/thema/blatt-entwurf.qmd")
    _write(tmp_path / "unterricht/mathematik/klasse-05/thema/material-ui-render-snapshot.qmd")
    _write(tmp_path / "wissen/mathematik/karten/aufgaben/karte.qmd")

    assert project_tasks._qmd_sources() == [direct, included]


def test_repository_render_patterns_stay_within_teaching_material(tmp_path, monkeypatch):
    patterns = project_tasks._render_patterns()
    assert all(pattern.lstrip("!").startswith("/unterricht/") for pattern in patterns)
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    included = tmp_path / "unterricht/mathematik/klasse-05/arithmetik/blatt.qmd"
    assert project_tasks._is_configured_qmd_source(included, patterns)
    for excluded in [
        included.with_name("blatt-old.qmd"),
        included.with_name("blatt-entwurf.qmd"),
        tmp_path / "unterricht/kurse/demo/build/blatt.qmd",
        tmp_path / "unterricht/kurse/build/site/blatt.qmd",
    ]:
        assert not project_tasks._is_configured_qmd_source(excluded, patterns)


def test_repository_render_patterns_avoid_double_star_globs():
    # Jedes ** in den Render-Mustern veranlasst Quarto, den kompletten
    # Projektbaum zu durchlaufen (inkl. ignorierte Verzeichnisse wie
    # unterricht/kurse/build) und verlangsamt Einzelrenders um ~50 s.
    patterns = project_tasks._render_patterns()
    assert patterns, "_quarto.yml enthaelt keine Render-Muster"
    assert not any("**" in pattern for pattern in patterns), (
        "Render-Muster mit ** gefunden: Quarto durchlaeuft dafuer den ganzen Projektbaum."
    )


def test_clean_dry_run_reports_without_deleting(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _minimal_quarto(tmp_path)
    qmd = _write(tmp_path / "unterricht/mathematik/klasse-05/thema/blatt.qmd")
    generated_tex = qmd.with_suffix(".tex")
    generated_pdf = qmd.with_suffix(".pdf")
    _write(generated_tex, "generated")
    _write(generated_pdf, "generated")
    _write(tmp_path / ".quarto/listing.json", "{}")

    project_tasks.clean.body(None, trocken=True)

    output = capsys.readouterr().out
    assert "Wuerde folgende Build-Artefakte entfernen:" in output
    assert "unterricht/mathematik/klasse-05/thema/blatt.tex" in output
    assert "unterricht/mathematik/klasse-05/thema/blatt.pdf" in output
    assert generated_tex.exists()
    assert generated_pdf.exists()


def test_clean_can_include_scratch_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _minimal_quarto(tmp_path)
    scratch = _write(tmp_path / "build/scratch/temp/lauf/page-001.jpg", "scratch")

    project_tasks.clean.body(None, artefakte=True)

    assert not scratch.exists()
    assert not (tmp_path / "build/scratch/temp").exists()


def test_clean_removes_generated_output_dirs_outside_quarto_render_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    _minimal_quarto(tmp_path)
    generated = _write(tmp_path / "wissen/mathematik/vorlagen/build/vorlagen-katalog.qmd", "generated")

    project_tasks.clean.body(None)

    assert not generated.exists()
    assert not (tmp_path / "wissen/mathematik/vorlagen/build").exists()


def test_editor_bundle_runs_npm_build_in_editor_app(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "CODE_DIR", tmp_path)
    _write(tmp_path / "src" / "editor-app" / "package.json", '{"scripts": {"build": "vite build"}}')
    calls = []
    monkeypatch.setattr(project_tasks, "_run", lambda command, **kwargs: calls.append((command, kwargs)))

    project_tasks.editor_bundle.body(None)

    assert calls == [(["npm", "run", "build"], {"cwd": tmp_path / "src" / "editor-app"})]


def test_build_hint_relativiert_nur_repo_pfade(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    inside = tmp_path / "unterricht" / "stunde-deck-slides.qmd"
    outside = Path("/tmp/stunde-deck-slides.qmd")

    assert project_tasks._build_hint(inside) == "inv build --source unterricht/stunde-deck-slides.qmd"
    assert project_tasks._build_hint(outside) == f"inv build --source {outside}"


def test_tags_backfill_writes_path_derived_tags(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    source = _write(
        tmp_path / "unterricht" / "mathematik" / "klasse-05" / "arbeitsblaetter" / "bruchrechnen.qmd",
        "---\ntitle: Bruchrechnen\n---\n\nText\n",
    )

    project_tasks.tags_backfill.body(None, trocken=True)

    from material_core.metadata import read_metadata

    assert "tags" not in read_metadata(source.read_text(encoding="utf-8"))
    assert "wuerde taggen" in capsys.readouterr().out

    project_tasks.tags_backfill.body(None)

    metadata = read_metadata(source.read_text(encoding="utf-8"))
    assert metadata["tags"] == ["mathematik", "klasse-05", "arbeitsblaetter", "Arbeitsblatt"]
    assert "getaggt" in capsys.readouterr().out


def test_tags_backfill_preserves_header_formatting(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    from material_core.metadata import read_metadata

    original = (
        "---\n"
        "title: Kopfuebungen\n"
        "header-includes:\n"
        "  - |\n"
        "    \\usepackage{enumitem}\n"
        "    \\usepackage[export]{adjustbox}\n"
        "---\n\nText\n"
    )
    source = _write(
        tmp_path / "unterricht" / "mathematik" / "klasse-10" / "kopfuebungen" / "kopfuebungen.qmd",
        original,
    )

    project_tasks.tags_backfill.body(None)

    updated = source.read_text(encoding="utf-8")
    assert read_metadata(updated)["tags"] == ["mathematik", "klasse-10", "kopfuebungen"]
    assert updated == original.replace(
        "---\n\nText",
        "tags:\n  - mathematik\n  - klasse-10\n  - kopfuebungen\n---\n\nText",
    )


def test_tags_backfill_preserves_existing_tags_and_skips_uninformative(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    from material_core.metadata import read_metadata

    tagged = _write(
        tmp_path / "unterricht" / "a.qmd",
        "---\ntitle: A\ntags: [behalten]\n---\n\nText\n",
    )
    bare = _write(tmp_path / "blatt.qmd", "---\ntitle: B\n---\n\nText\n")

    project_tasks.tags_backfill.body(None)

    assert read_metadata(tagged.read_text(encoding="utf-8"))["tags"] == ["behalten"]
    assert "tags" not in read_metadata(bare.read_text(encoding="utf-8"))


def test_tags_backfill_skips_wissen_submodule(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    from material_core.metadata import read_metadata

    source = _write(tmp_path / "wissen" / "mathematik" / "karte.qmd", "---\ntitle: Karte\n---\n\nText\n")

    project_tasks.tags_backfill.body(None)

    assert "tags" not in read_metadata(source.read_text(encoding="utf-8"))


def test_orphan_pdfs_kennt_pdf_mit_quelle_und_ohne(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    pdf_root = tmp_path / "build/pdf/unterricht/mathematik/klasse-05"
    _write(pdf_root / "blatt.pdf")
    _write(pdf_root / "anders.pdf")
    _write(tmp_path / "unterricht/mathematik/klasse-05/blatt.qmd")

    orphans = project_tasks._orphan_pdfs()

    assert orphans == [pdf_root / "anders.pdf"]


def test_orphan_pdfs_beruecksichtigt_output_file(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    pdf_root = tmp_path / "build/pdf/unterricht/mathematik/klasse-05"
    _write(pdf_root / "druck.pdf")
    _write(tmp_path / "unterricht/mathematik/klasse-05/blatt.qmd", '---\noutput-file: "druck.pdf"\n---\n')

    assert project_tasks._orphan_pdfs() == []


def test_orphan_pdfs_uebersteht_ungueltiges_output_file(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    pdf_root = tmp_path / "build/pdf/unterricht/mathematik/klasse-05"
    _write(pdf_root / "blatt.pdf")
    _write(tmp_path / "unterricht/mathematik/klasse-05/blatt.qmd", '---\noutput-file: ""\n---\n')

    assert project_tasks._orphan_pdfs() == []


def test_stale_export_temps_findet_nur_alte(tmp_path, monkeypatch):
    import os
    import time as time_module

    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    old = _write(tmp_path / "build/.course-export-alt/inhalt.txt").parent
    young = _write(tmp_path / "build/.course-export-jung/inhalt.txt").parent
    legacy_old = _write(tmp_path / "unterricht/kurse/build/.course-export-alt/inhalt.txt").parent
    vor_drei_tagen = time_module.time() - 3 * 86400
    os.utime(old, (vor_drei_tagen, vor_drei_tagen))
    os.utime(legacy_old, (vor_drei_tagen, vor_drei_tagen))

    temps = project_tasks._stale_export_temps()

    assert temps == [old, legacy_old]
    assert young not in temps


def test_legacy_output_dirs_schliesst_kurse_vorlagen_und_foerderziel_aus(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    material_pdf = _write(tmp_path / "unterricht/mathematik/klasse-05/thema/pdf/blatt.pdf")
    material_build = tmp_path / "unterricht/mathematik/klasse-05/thema/build"
    _write(material_build / "blatt.files/typst.typ")
    _write(tmp_path / "unterricht/kurse/python-2026/build/site/index.html")
    _write(tmp_path / "wissen/mathematik/vorlagen/build/katalog.qmd")
    _write(tmp_path / "build/foerder-online/thema/blatt.pdf")

    pairs = dict(project_tasks._legacy_output_dirs())

    assert pairs == {
        material_pdf.parent: tmp_path / "build/pdf/unterricht/mathematik/klasse-05/thema",
        material_build: tmp_path / "build/artefakte/unterricht/mathematik/klasse-05/thema",
    }


def test_migrate_legacy_dir_verschiebt_und_entfernt_leeren_ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    source_dir = tmp_path / "unterricht/mathematik/klasse-05/thema/pdf"
    source = _write(source_dir / "blatt.pdf")
    target_dir = tmp_path / "build/pdf/unterricht/mathematik/klasse-05/thema"

    moved = project_tasks._migrate_legacy_dir(source_dir, target_dir, dry_run=False)

    assert moved == [target_dir / "blatt.pdf"]
    assert (target_dir / "blatt.pdf").is_file()
    assert not source.exists()
    assert not source_dir.exists()


def test_migrate_legacy_dir_trocken_laesst_alles_liegen(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    source_dir = tmp_path / "unterricht/mathematik/klasse-05/thema/pdf"
    source = _write(source_dir / "blatt.pdf")
    target_dir = tmp_path / "build/pdf/unterricht/mathematik/klasse-05/thema"

    moved = project_tasks._migrate_legacy_dir(source_dir, target_dir, dry_run=True)

    assert moved == [target_dir / "blatt.pdf"]
    assert source.is_file()
    assert not target_dir.exists()


def test_build_rebuilds_after_external_template_change(tmp_path, monkeypatch):
    _FakeBuildService.aufrufe.clear()
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    template = _write(tmp_path / "src/templates/custom.typst", "old layout")
    source = _write(tmp_path / "unterricht/blatt.qmd",
                    "---\nformat:\n  typst:\n    template: ../src/templates/custom.typst\n---\nText\n")
    monkeypatch.setattr(project_tasks, "BuildService", _FakeBuildService)
    project_tasks.build.body(None, source=str(source))
    project_tasks.build.body(None, source=str(source))
    assert len(_FakeBuildService.aufrufe) == 1
    template.write_text("new layout")
    project_tasks.build.body(None, source=str(source))
    assert len(_FakeBuildService.aufrufe) == 2


def test_render_runner_preserves_frozen_filter_environment(monkeypatch):
    captured = {}
    monkeypatch.setattr(project_tasks, 'run', lambda command, **options: captured.update(options))
    project_tasks._run([project_tasks.QUARTO, 'render', 'ab.qmd'],
                       env={'MATERIAL_TEMPLATE_FILTER_DIR': '/frozen/filters'})
    assert captured['env']['MATERIAL_TEMPLATE_FILTER_DIR'] == '/frozen/filters'
    assert captured['env']['MATERIAL_BUILD_MANAGED'] == '1'


def test_foerder_online_build_uses_managed_build_service(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(project_tasks, 'ROOT_DIR', tmp_path)
    source = _write(tmp_path / 'unterricht/mathematik/klasse-05/addition/foerderkurs-stufe-1/addition-stufe-1-ab-1.qmd')
    initial = SimpleNamespace(eintraege=[SimpleNamespace(qmd=source, fehlt=True, veraltet=False)])
    finished = SimpleNamespace(eintraege=[], uebersprungen=[])
    plans = iter([initial, finished])
    monkeypatch.setattr(project_tasks.foerder_online, 'plane', lambda *args, **kwargs: next(plans))
    monkeypatch.setattr(project_tasks.foerder_online, 'kopiere', lambda *args, **kwargs: {'kopiert': [], 'unveraendert': [], 'fehlend': []})
    built = []
    class ManagedBuild:
        def __init__(self, root, runner):
            assert root == tmp_path
        def build_document(self, document, *, quarto):
            built.append(document)
    monkeypatch.setattr(project_tasks, 'BuildService', ManagedBuild)
    monkeypatch.setattr(project_tasks, '_run', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Direkter Render-Aufruf')))
    project_tasks.foerder_online_cmd.body(None, build=True)
    assert built == [source]


def test_setup_installs_sph_dependency_only_on_request(tmp_path, monkeypatch):
    monkeypatch.setattr(project_tasks, "CODE_DIR", tmp_path)
    commands = []
    monkeypatch.setattr(project_tasks, "_run", lambda args, **kwargs: commands.append(args))
    project_tasks._pip_install_editable()
    assert commands == [[sys.executable, "-m", "pip", "install", "-e", "."]]
    commands.clear()
    project_tasks._pip_install_editable(entwicklung=True)
    assert commands == [[sys.executable, "-m", "pip", "install", "-e", ".[dev]"]]
    commands.clear()
    project_tasks._pip_install_editable(schulportal=True)
    assert commands == [[sys.executable, "-m", "pip", "install", "-e", ".", "-e", "src/sph_login"]]
    venv_pip = _write(tmp_path / ".venv/bin/pip")
    commands.clear()
    project_tasks._pip_install_editable()
    assert commands == [[str(venv_pip), "install", "-e", "."]]


def test_portsuche_ohne_lsof_ueberspringt_fremde_prozesse(monkeypatch):
    import socket

    real = Path.iterdir

    def guarded(path):
        if path.as_posix() == "/proc/1/fd":
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(Path, "iterdir", guarded)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        assert os.getpid() in project_tasks._listening_pids_from_proc(server.getsockname()[1])
