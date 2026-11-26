"""Optionale Plugins bringen ihre Systemprogramme selbst mit; ohne Aktivierung verlangt sie niemand."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from material_core import plugin_state, systemcheck

OPTIONAL_PROGRAMS = {"pandoc", "libreoffice", "tesseract", "ghostscript"}


@pytest.fixture()
def workspace_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MATERIAL_HOME", str(tmp_path))
    return tmp_path


def enable(root: Path, **plugins: bool) -> None:
    state = root / ".material-ui" / "plugins.json"
    state.parent.mkdir(exist_ok=True)
    state.write_text(json.dumps({"enabled": plugins}), encoding="utf-8")


def test_ab_werk_verlangt_niemand_office_oder_ocr_programme(workspace_root):
    assert not OPTIONAL_PROGRAMS & {tool["key"] for tool in systemcheck.check_tools()}


def test_aktiviertes_plugin_meldet_seine_programme(workspace_root, monkeypatch):
    enable(workspace_root, office=True, ocr=True)
    monkeypatch.setattr(systemcheck.shutil, "which", lambda name: None)
    results = {tool["key"]: tool for tool in systemcheck.check_tools()}
    assert OPTIONAL_PROGRAMS <= results.keys()
    assert {results[key]["level"] for key in OPTIONAL_PROGRAMS} == {"plugin"}
    command = systemcheck.install_command(systemcheck.install_plan(list(results.values()), "pacman", ("plugin",)))
    assert "pandoc-cli" in command and "libreoffice-fresh" in command and "tesseract-data-deu" in command


def test_entwicklerwerkzeuge_nur_auf_wunsch(workspace_root, monkeypatch, capsys):
    monkeypatch.setattr(systemcheck.shutil, "which", lambda name: None)
    systemcheck.main(["--befehl", "--alles", "--manager", "apt"])
    assert "nodejs" not in capsys.readouterr().out
    systemcheck.main(["--befehl", "--entwicklung", "--manager", "apt"])
    assert "nodejs" in capsys.readouterr().out


def test_require_nennt_den_naechsten_schritt(workspace_root, monkeypatch):
    with pytest.raises(plugin_state.PluginUnavailable, match="inv plugin-enable ocr"):
        plugin_state.require("ocr", "tesseract")
    enable(workspace_root, ocr=True)
    monkeypatch.setattr(plugin_state.shutil, "which", lambda name: None)
    with pytest.raises(plugin_state.PluginUnavailable, match="tesseract"):
        plugin_state.require("ocr", "tesseract")
    monkeypatch.setattr(plugin_state.shutil, "which", lambda name: "/usr/bin/" + name)
    plugin_state.require("ocr", "tesseract")


def test_check_laeuft_als_skript_ohne_installierte_pakete(workspace_root):
    """install.sh ruft den Check vor `pip install` auf; -S blendet alle site-packages aus."""
    enable(workspace_root, ocr=True)
    script = Path(systemcheck.__file__)
    result = subprocess.run([sys.executable, "-S", "-B", str(script), "--json", "--manager", "apt"],
                            capture_output=True, text=True)
    assert "nicht pruefbar" not in result.stderr, result.stderr
    assert "tesseract" in {tool["key"] for tool in json.loads(result.stdout)["tools"]}
