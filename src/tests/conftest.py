"""Shared fixtures for tests that render Markdown through exam.lua via quarto pandoc."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

# Tests laufen immer im Programmverzeichnis, nie im eingestellten Inhaltsordner des Rechners.
os.environ["MATERIAL_HOME"] = str(Path(__file__).resolve().parents[2])

EXAM_LUA_FILTER = Path(__file__).resolve().parents[1] / "quarto/filters/exam.lua"


@pytest.fixture(autouse=True)
def isolate_git_discovery(monkeypatch, tmp_path_factory):
    # Testprojekte auf Platte duerfen nicht das umgebende Werkzeugrepo erben.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path_factory.getbasetemp()))


@pytest.fixture(autouse=True)
def no_update_check(monkeypatch):
    """Die Oberflaeche fragt beim Laden nach Releases; Tests bleiben ohne Netzzugriff."""
    monkeypatch.setenv("MATERIAL_UI_UPDATE_CHECK", "0")


@pytest.fixture(autouse=True)
def no_course_runtime_prewarm(monkeypatch):
    """App tests must not download H5P libraries as a startup side effect.

    Runtime and preview tests still call their explicit setup methods directly.
    """
    from material_ui.plugins.kurse.preview import PreviewService

    monkeypatch.setattr(PreviewService, "prewarm", lambda self: None)


@pytest.fixture
def render_exam_lua():
    """Render Markdown through exam.lua. Usage: render_exam_lua(source, target, extract_media=None)."""
    if shutil.which("quarto") is None:
        pytest.skip("Quarto fehlt")

    def _render(source, target="typst", extract_media=None):
        cmd = ["quarto", "pandoc", "--from", "markdown", "--to", target, "--lua-filter", str(EXAM_LUA_FILTER)]
        if extract_media:
            cmd.append(f"--extract-media={extract_media}")
        return subprocess.run(cmd, input=source, text=True, capture_output=True, timeout=30)

    return _render
