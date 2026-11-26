from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import onlyoffice_import
import project_tasks
from quarto_render_guard import MANAGED_RENDER_VARIABLE, main, managed_render_environment


def test_guard_rejects_missing_or_invalid_marker(monkeypatch, capsys):
    monkeypatch.delenv(MANAGED_RENDER_VARIABLE, raising=False)
    assert main() == 1
    monkeypatch.setenv(MANAGED_RENDER_VARIABLE, "0")
    assert main() == 1
    assert "inv build --source" in capsys.readouterr().err


def test_managed_environment_is_scoped_to_child_process(monkeypatch):
    monkeypatch.delenv(MANAGED_RENDER_VARIABLE, raising=False)
    environment = managed_render_environment()
    assert environment[MANAGED_RENDER_VARIABLE] == "1"
    assert MANAGED_RENDER_VARIABLE not in os.environ
    monkeypatch.setenv(MANAGED_RENDER_VARIABLE, "1")
    assert main() == 0


@pytest.mark.parametrize("action", ["render", "preview"])
def test_task_runner_authorizes_quarto_subprocess_only(monkeypatch, tmp_path, action):
    monkeypatch.delenv(MANAGED_RENDER_VARIABLE, raising=False)
    calls = []
    monkeypatch.setattr(project_tasks, "run", lambda command, **kwargs: calls.append(kwargs))
    project_tasks._run([project_tasks.QUARTO, action, "blatt.qmd"], cwd=tmp_path)
    assert calls[-1]["env"][MANAGED_RENDER_VARIABLE] == "1"
    project_tasks._run(["other-command"], cwd=tmp_path)
    assert "env" not in calls[-1]
    assert MANAGED_RENDER_VARIABLE not in os.environ


def test_import_runner_authorizes_quarto_subprocess(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(onlyoffice_import.subprocess, "run", lambda command, **kwargs: calls.append(kwargs))
    onlyoffice_import._run([onlyoffice_import.QUARTO, "render", "blatt.qmd"], cwd=tmp_path)
    assert calls[-1]["env"][MANAGED_RENDER_VARIABLE] == "1"


def test_preview_relocates_artifacts_on_interrupt(monkeypatch, tmp_path):
    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(project_tasks, "_build_tikz_svg_assets", lambda: None)
    source = tmp_path / "blatt.qmd"
    source.write_text("Text\n", encoding="utf-8")

    def preview(command):
        source.with_suffix(".pdf").write_bytes(b"preview")
        source.with_suffix(".tex").write_text("generated", encoding="utf-8")
        raise KeyboardInterrupt

    monkeypatch.setattr(project_tasks, "_run", preview)
    with pytest.raises(KeyboardInterrupt):
        project_tasks.preview.body(None, source="blatt.qmd")
    assert (tmp_path / "build/pdf/blatt.pdf").read_bytes() == b"preview"
    assert (tmp_path / "build/artefakte/blatt.tex").is_file()
    assert not source.with_suffix(".pdf").exists()


@pytest.mark.parametrize("working_directory", ["root", "document"])
@pytest.mark.parametrize("action", ["render", "preview"])
def test_real_quarto_blocks_direct_render_and_allows_managed_render(tmp_path, monkeypatch, working_directory, action):
    quarto = shutil.which("quarto")
    if quarto is None:
        pytest.skip("Quarto ist nicht installiert")
    monkeypatch.delenv(MANAGED_RENDER_VARIABLE, raising=False)
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "_quarto.yml").read_text(encoding="utf-8"))
    hook = config["project"]["pre-render"]
    script = root / hook.split(" ", 1)[1]
    script_copy = tmp_path / "src" / script.name
    script_copy.parent.mkdir()
    shutil.copyfile(script, script_copy)
    (tmp_path / "_quarto.yml").write_text(
        yaml.safe_dump({"project": {"type": "default", "pre-render": hook,
                                   "render": ["unterricht/blatt.qmd"]}, "format": "html"}),
        encoding="utf-8",
    )
    source = tmp_path / "unterricht" / "blatt.qmd"
    source.parent.mkdir()
    source.write_text("---\ntitle: Guard test\n---\nText\n", encoding="utf-8")
    cwd = tmp_path if working_directory == "root" else source.parent
    command = [quarto, action, str(source.relative_to(cwd))]
    if action == "preview":
        command.append("--no-browser")
    blocked = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=30)
    assert blocked.returncode != 0
    assert "Direktes Quarto-Rendern" in blocked.stdout + blocked.stderr
    assert not source.with_suffix(".html").exists()
    if action == "preview":
        return
    allowed = subprocess.run(
        command, cwd=cwd, env=managed_render_environment(), capture_output=True, text=True, timeout=30,
    )
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    assert source.with_suffix(".html").is_file()
