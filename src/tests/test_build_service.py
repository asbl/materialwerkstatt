from __future__ import annotations

import subprocess
from pathlib import Path

import pymupdf
import pytest

import project_tasks
from material_core import builds
from material_core.builds import BuildFailure, BuildService


def write_pdf(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "PDF")
        document.save(path)


def test_render_lock_legt_sperrdatei_an_und_ist_wiederverwendbar(tmp_path):
    from material_core.builds import render_lock

    with render_lock(tmp_path):
        assert (tmp_path / "build" / ".render.lock").is_file()

    with render_lock(tmp_path, timeout=0.5):
        pass


@pytest.mark.parametrize("failure", ["exit", "invalid", "changed", "manifest"])
def test_cli_build_keeps_previous_pdf_on_failure(tmp_path, monkeypatch, failure):
    source = tmp_path / "blatt.qmd"
    source.write_text("# Original\n")
    published = tmp_path / "build" / "pdf" / "blatt.pdf"
    write_pdf(published)
    previous = published.read_bytes()
    original_write = builds.atomic_write_text

    def write_manifest(path, text, **kwargs):
        if failure == "manifest" and path.name.endswith(".material-ui.json"):
            raise OSError("Manifest konnte nicht geschrieben werden")
        return original_write(path, text, **kwargs)

    def render(command, **kwargs):
        assert kwargs["env"]["MATERIAL_BUILD_MANAGED"] == "1"
        target = Path(command[2]).parent / command[command.index("--output") + 1]
        if failure == "invalid":
            target.write_bytes(b"Invalid")
        else:
            write_pdf(target)
        if failure == "changed":
            source.write_text("# External\n")
        return subprocess.CompletedProcess(command, 1 if failure == "exit" else 0, stdout="Log")

    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(project_tasks, "_run", render)
    monkeypatch.setattr(builds, "atomic_write_text", write_manifest)
    with pytest.raises(BuildFailure):
        project_tasks.build.body(None, source="blatt.qmd")
    assert published.read_bytes() == previous
    assert not list(tmp_path.glob("material-ui-render-*"))
    assert not list(tmp_path.glob(".material-render-*"))


def test_shared_build_keeps_source_and_configured_output(tmp_path):
    source = tmp_path / "blatt.qmd"
    text = '---\noutput-file: druck.pdf\n---\n# Inhalt\n'
    source.write_text(text)

    def render(command, **kwargs):
        copied_source = Path(command[2])
        assert copied_source.read_text() == text
        write_pdf(copied_source.parent / command[command.index("--output") + 1])
        copied_source.with_suffix(".tex").write_text("Generated")
        return subprocess.CompletedProcess(command, 0, stdout="Success")

    result = BuildService(tmp_path, render).build_document(source)
    assert result.pdf_path == tmp_path / "build" / "pdf" / "druck.pdf"
    assert source.read_text() == text
    assert (tmp_path / "build" / "artefakte" / "blatt.tex").read_text() == "Generated"
    assert not (tmp_path / "druck.pdf").exists()


def test_concurrent_render_copy_race_is_retried(tmp_path):
    source = tmp_path / "blatt.qmd"
    source.write_text("# Inhalt\n")
    calls = []

    def render(command, **kwargs):
        calls.append(command)
        copied_source = Path(command[2])
        target = copied_source.parent / command[command.index("--output") + 1]
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout=(
                    "ERROR: NotFound: No such file or directory (os error 2): stat "
                    "'/projekt/ordner/material-ui-render-abc123.qmd'"
                ),
            )
        write_pdf(target)
        return subprocess.CompletedProcess(command, 0, stdout="Success")

    result = BuildService(tmp_path, render).build_document(source)

    assert result.pdf_path == tmp_path / "build" / "pdf" / "blatt.pdf"
    assert len(calls) == 2


def test_render_failure_on_own_copy_is_not_retried(tmp_path):
    source = tmp_path / "blatt.qmd"
    source.write_text("# Inhalt\n")
    calls = []

    def render(command, **kwargs):
        calls.append(command)
        copied_source = Path(command[2])
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=(
                "ERROR: NotFound: No such file or directory (os error 2): stat "
                f"'{copied_source}'"
            ),
        )

    with pytest.raises(BuildFailure):
        BuildService(tmp_path, render).build_document(source)
    assert len(calls) == 1


def test_plain_render_failure_is_not_retried(tmp_path):
    source = tmp_path / "blatt.qmd"
    source.write_text("# Inhalt\n")
    calls = []

    def render(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, stdout="ERROR: LaTeX fehlgeschlagen")

    with pytest.raises(BuildFailure):
        BuildService(tmp_path, render).build_document(source)
    assert len(calls) == 1


def test_asset_build_skips_tex_fragments_and_libraries(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "diagram.tex").write_text("\\documentclass{standalone}\n")
    (assets / "diagram-lib.tex").write_text("\\documentclass{standalone}\n")
    (assets / "fragment.tex").write_text("\\begin{tabular}{cc}\n")
    calls = []

    def compile_asset(command, **kwargs):
        calls.append(command)
        if "-output-directory" in command:
            output = Path(command[command.index("-output-directory") + 1])
            (output / "diagram.pdf").write_bytes(b"PDF")
        return subprocess.CompletedProcess(command, 0, stdout="")

    BuildService(tmp_path, compile_asset).build_tikz_assets(tmp_path)
    assert len(calls) == 2
    assert calls[0][-1] == "diagram.tex"


@pytest.mark.parametrize("dependency", ["material_core/builds.py", "course_sync/application.py", "quarto_render_guard.py"])
def test_desktop_fingerprint_tracks_shared_dependencies(tmp_path, monkeypatch, dependency):
    from material_ui import desktop

    entry = tmp_path / "material_ui" / "desktop.py"
    entry.parent.mkdir()
    entry.write_text("Launcher")
    shared = tmp_path / dependency
    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_text("Before")
    monkeypatch.setattr(desktop, "__file__", str(entry))
    before = desktop.application_version()
    shared.write_text("After")
    assert desktop.application_version() != before
