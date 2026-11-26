from __future__ import annotations

import json

import pytest

from material_core import workspace


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv(workspace.ENV, raising=False)
    code = (tmp_path / "programm").resolve()
    for name, text in {"_quarto.yml": "project: {}\n", "src/quarto/filters/exam.lua": "-- a\n",
                       "src/quarto/_local/templates/privat.typst": "privat\n",
                       "src/material_core/template-designs.json": "[]",
                       "src/material_ui/app.py": "code\n", "pyproject.toml": ""}.items():
        (code / name).parent.mkdir(parents=True, exist_ok=True)
        (code / name).write_text(text)
    return code, (tmp_path / "inhalte").resolve()


def test_ohne_einstellung_ist_das_programmverzeichnis_der_arbeitsbereich(setup):
    code, _home = setup
    assert workspace.selected(code) == code
    assert workspace.prepare(code, code) == []


def test_umgebungsvariable_hat_vorrang(setup, monkeypatch):
    code, home = setup
    monkeypatch.setenv(workspace.ENV, str(home))
    assert workspace.selected(code) == home


def test_speichern_spiegelt_nur_werkzeugdateien(setup):
    code, home = setup
    workspace.save(str(home), create=True, code_root=code)
    assert workspace.selected(code) == home
    assert (home / "src/quarto/filters/exam.lua").is_file()
    assert (home / "_quarto.yml").is_file() and (home / "tasks.py").is_file()
    assert not (home / "src/material_ui").exists()
    assert not (home / "src/quarto/_local").exists()
    assert str(code) not in (home / "tasks.py").read_text()
    workspace.save("", code_root=code)
    assert workspace.selected(code) == code


def test_abgleich_aktualisiert_entfernt_und_schont_eigenes(setup):
    code, home = setup
    workspace.save(str(home), create=True, code_root=code)
    own = home / "src/quarto/_local/templates/meins.typst"
    own.parent.mkdir(parents=True)
    own.write_text("meins")
    note = home / "src/quarto/filters/notiz.txt"
    note.write_text("eigene Datei")
    (code / "src/quarto/filters/exam.lua").write_text("-- neu\n")
    (code / "src/material_core/template-designs.json").unlink()
    changed = workspace.prepare(home, code)
    assert (home / "src/quarto/filters/exam.lua").read_text() == "-- neu\n"
    assert not (home / "src/material_core/template-designs.json").exists()
    assert own.read_text() == "meins" and note.exists()
    assert "src/quarto/filters/exam.lua" in changed
    assert workspace.prepare(home, code) == []
    assert "src/quarto/filters/notiz.txt" not in json.loads((home / workspace.MANIFEST).read_text())


def test_ungeeignete_ordner(setup, tmp_path):
    code, home = setup
    other = tmp_path / "anderes-programm"
    other.mkdir()
    (other / "pyproject.toml").write_text("")
    for value, message in [("relativ", "vollständigen"), ("/", "weit"), (str(code / "x"), "Programmverzeichnis"),
                           (str(other), "Programmverzeichnis"), (str(home), "gibt es nicht"),
                           (str(tmp_path / "foerderempfehlungen"), "personenbezogene")]:
        with pytest.raises(workspace.WorkspaceError, match=message):
            workspace.save(value, code_root=code)


def test_fehlender_ordner(setup):
    code, home = setup
    workspace.save(str(home), create=True, code_root=code)
    home.rename(home.with_name("weg"))
    assert workspace.selected(code) == home
    assert not home.is_dir()


def test_api(setup, tmp_path, monkeypatch):
    from material_ui.app import create_app
    from material_ui.config import AppConfig

    # Die Test-Ordner liegen im Programmverzeichnis; fuer die API gilt daher das nachgebildete.
    code, home = setup
    monkeypatch.setattr(workspace, "CODE_ROOT", code)
    app = create_app(config=AppConfig(root=code))
    client = app.test_client()
    headers = {"X-Material-Token": app.config["MATERIAL_CSRF_TOKEN"]}
    assert client.get("/api/settings/workspace").get_json()["state"] == "default"
    assert client.put("/api/settings/workspace", json={"path": "x"}, headers=headers).status_code == 400
    assert client.put("/api/settings/workspace", json={"path": ""}).status_code == 403
    saved = client.put("/api/settings/workspace", json={"path": str(home), "create": True}, headers=headers)
    assert saved.get_json()["state"] == "restart"
    assert (home / "src/quarto/filters/exam.lua").is_file()


def test_paketinstallation_nutzt_dokumentenordner(setup, monkeypatch, tmp_path):
    code, _home = setup
    (code / workspace.SYSTEM_MARKER).write_text("")
    (tmp_path / "config").mkdir(exist_ok=True)
    documents = tmp_path / "Dokumente"
    (tmp_path / "config" / "user-dirs.dirs").write_text(f'XDG_DOCUMENTS_DIR="{documents}"\n')
    assert workspace.default_home(code) == documents / "material"
    assert workspace.selected(code) == documents / "material"
    assert workspace.save("", code_root=code) == documents / "material"
    assert (documents / "material/_quarto.yml").is_file()
    with pytest.raises(workspace.WorkspaceError, match="Programmverzeichnis"):
        workspace.save(str(code), code_root=code)
