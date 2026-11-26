"""Strukturpruefung der Kalender-Frontendmodule (kein Browser noetig).

Das Plugin liefert nur Dateien aus, die im Manifest stehen; ein vergessener Eintrag
fuehrt im Browser erst beim Import zu einem 404 und damit zu einer leeren Ansicht.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from material_ui.app import create_app
from material_ui.config import AppConfig

PLUGIN = Path(__file__).resolve().parents[1] / "material_ui" / "plugins" / "kalender"
ASSETS = PLUGIN / "assets"
IMPORT = re.compile(r'^import\s*\{([^}]*)\}\s*from\s*"([^"]+)";', re.MULTILINE)
EXPORT = re.compile(r"^export\s+(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)


def manifest() -> dict:
    return json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))


def js_files() -> list[Path]:
    return sorted(ASSETS.glob("*.js"))


def test_every_js_module_is_listed_in_the_manifest():
    data = manifest()
    listed = {data["jsEntry"], *data.get("modules", [])}
    assert {f"assets/{path.name}" for path in js_files()} == listed


@pytest.mark.parametrize("path", js_files(), ids=lambda path: path.name)
def test_relative_imports_resolve_to_existing_exports(path: Path):
    source = path.read_text(encoding="utf-8")
    for names, target in IMPORT.findall(source):
        if not target.startswith("./"):
            continue
        module = ASSETS / target[2:]
        assert module.is_file(), f"{path.name} importiert fehlendes Modul {target}"
        exported = set(EXPORT.findall(module.read_text(encoding="utf-8")))
        wanted = {name.strip().split(" as ")[0] for name in names.split(",") if name.strip()}
        assert wanted <= exported, f"{path.name}: {sorted(wanted - exported)} fehlt in {target}"


def test_modules_have_no_cross_module_reassigned_state():
    """Veraenderlicher Zustand lebt im store; ein exportiertes `let` liesse sich extern nicht setzen."""
    for path in js_files():
        assert not re.search(r"^export\s+let\s", path.read_text(encoding="utf-8"), re.MULTILINE), path.name


def test_plugin_entry_stays_small_and_registers():
    entry = (ASSETS / "plugin.js").read_text(encoding="utf-8")
    assert re.search(r"^export function register\(ctx\)", entry, re.MULTILINE)
    assert len(entry.splitlines()) < 300
    for path in js_files():
        assert len(path.read_text(encoding="utf-8").splitlines()) < 500, f"{path.name} wieder zu gross"


def test_all_modules_are_served(tmp_path: Path):
    (tmp_path / "unterricht").mkdir()
    (tmp_path / "wissen").mkdir()
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        client = app.test_client()
        for path in js_files():
            response = client.get(f"/plugins/kalender/assets/{path.name}")
            assert response.status_code == 200, path.name
            assert b"import" in response.data or path.name == "store.js"
    finally:
        app.extensions["material_runtime"].close()
