from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_ui.errors import InvalidInput, MarketplaceUnavailable, PluginConflict
from material_ui.plugins.manifest import load_manifest
from material_ui.plugins.marketplace import Marketplace, resolve, scan_catalog
from material_ui.plugins.versions import parse_version
from test_material_ui import LiveServer, free_port

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - haengt von der lokalen Testumgebung ab
    sync_playwright = None


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                   cwd=repo, check=True, capture_output=True)


def _catalog_plugin(catalog: Path, plugin_id: str, version: str, extra: dict | None = None) -> None:
    directory = catalog / "plugins" / plugin_id / version
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {"id": plugin_id, "name": f"Plugin {plugin_id}", "version": version,
                "capabilities": ["state-write"], "pythonEntry": "register", **(extra or {})}
    (directory / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "__init__.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")


@pytest.fixture()
def catalog_repo(tmp_path):
    """Lokales git-Katalog-Repo mit foo (2 Versionen), bar (hängt von foo ab), Interface-Beispiel und Zyklus."""
    repo = tmp_path / "catalog-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _catalog_plugin(repo, "foo", "1.0.0")
    _catalog_plugin(repo, "foo", "1.1.0")
    _catalog_plugin(repo, "bar", "0.1.0", {"dependsOn": {"foo": "^1.0.0"}})
    _catalog_plugin(repo, "iface-provider", "1.0.0", {"provides": ["iface-x"]})
    _catalog_plugin(repo, "baz", "0.2.0", {"dependsOn": {"@iface-x": "*"}})
    _catalog_plugin(repo, "cyc-a", "1.0.0", {"dependsOn": {"cyc-b": "*"}})
    _catalog_plugin(repo, "cyc-b", "1.0.0", {"dependsOn": {"cyc-a": "*"}})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "katalog")
    return repo


@pytest.fixture()
def marketplace(tmp_path, monkeypatch, catalog_repo):
    monkeypatch.setenv("MATERIAL_UI_MARKETPLACE_REPO", str(catalog_repo))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    user_plugins = tmp_path / "user-plugins"
    user_plugins.mkdir()
    monkeypatch.setenv("MATERIAL_UI_PLUGIN_PATHS", str(user_plugins))
    root = tmp_path / "repo"
    root.mkdir()
    return Marketplace(root, user_dir=user_plugins,
                       catalog_root=tmp_path / "xdg" / "material-ui" / "marketplace" / "catalog")


def _actions_by_id(result: dict) -> dict[str, dict]:
    return {action["id"]: action for action in result["actions"]}


def test_refresh_clones_catalog_and_scan_finds_versions(marketplace):
    info = marketplace.refresh()
    assert info["commit"]
    assert not info.get("warning")
    catalog = scan_catalog(marketplace.catalog_root, info["commit"])
    assert [entry.version for entry in catalog["foo"]] == [parse_version("1.0.0"), parse_version("1.1.0")]
    assert catalog["bar"][0].manifest.depends_on == (("foo", "^1.0.0"),)


def test_refresh_falls_back_to_cache_when_repo_unreachable(tmp_path, monkeypatch, catalog_repo):
    monkeypatch.setenv("MATERIAL_UI_MARKETPLACE_REPO", str(catalog_repo))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "repo"
    root.mkdir()
    mp = Marketplace(root, user_dir=tmp_path / "user-plugins",
                     catalog_root=tmp_path / "xdg" / "material-ui" / "marketplace" / "catalog")
    mp.refresh()
    # Origin auf eine nicht erreichbare Quelle zeigen, damit pull fehlschlägt
    subprocess.run(["git", "remote", "set-url", "origin", str(tmp_path / "kaputt")],
                   cwd=mp.catalog_root, check=True, capture_output=True)
    mp.repo_url = str(tmp_path / "kaputt")   # konfigurierte Quelle bleibt dieselbe, ist aber nicht erreichbar
    info = mp.refresh()
    assert info["commit"]  # Cache-Commit
    assert "Cache-Stand" in info["warning"]


def test_scan_rejects_version_folder_mismatch(tmp_path, monkeypatch, catalog_repo):
    _catalog_plugin(catalog_repo, "foo", "9.9.9", {"version": "1.2.3"})  # Manifest-Version != Ordner
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A"], cwd=catalog_repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "x"], cwd=catalog_repo, check=True)
    mp_root = tmp_path / "mp"
    mp_root.mkdir()
    mp = Marketplace(mp_root, user_dir=tmp_path / "up", catalog_root=tmp_path / "cache",
                     repo_url=str(catalog_repo))
    mp.refresh()
    with pytest.raises(MarketplaceUnavailable):
        scan_catalog(mp.catalog_root)


def test_install_pulls_dependencies_and_writes_lock(marketplace):
    result = marketplace.install("bar")
    actions = _actions_by_id(result)
    assert actions["bar"]["action"] == "install" and actions["bar"]["version"] == "0.1.0"
    # Auto-Upgrade/Dependency: neueste foo-Version (1.1.0) wird mit installiert
    assert actions["foo"]["action"] == "install" and actions["foo"]["version"] == "1.1.0"
    assert result["restartRequired"] is True
    installed = load_manifest(marketplace.user_dir / "foo", "user")
    assert installed.version == "1.1.0"
    lock = json.loads((marketplace.root / ".material-ui" / "plugins.lock.json").read_text(encoding="utf-8"))
    assert lock["plugins"]["foo"]["version"] == "1.1.0"
    assert lock["plugins"]["bar"]["source"] == "marketplace"
    enabled = json.loads((marketplace.root / ".material-ui" / "plugins.json").read_text(encoding="utf-8"))
    assert enabled["enabled"]["foo"] is True and enabled["enabled"]["bar"] is True


def test_install_is_idempotent(marketplace):
    marketplace.install("foo", "^1.0.0")
    result = marketplace.install("foo", "^1.0.0")
    assert _actions_by_id(result)["foo"]["action"] == "keep"


def test_resolve_interface_dependency(marketplace):
    marketplace.refresh()
    catalog = scan_catalog(marketplace.catalog_root)
    plan = resolve(catalog, {"baz": "*"}, {})
    assert set(plan.entries) == {"baz", "iface-provider"}


def test_resolve_rejects_conflict_and_cycle(marketplace):
    marketplace.refresh()
    catalog = scan_catalog(marketplace.catalog_root)
    with pytest.raises(PluginConflict):
        resolve(catalog, {"foo": ">=2.0.0"}, {})
    with pytest.raises(PluginConflict, match="Zyklische"):
        resolve(catalog, {"cyc-a": "*"}, {})
    with pytest.raises(InvalidInput):
        resolve(catalog, {"unbekannt": "*"}, {})


def test_resolve_keeps_satisfying_builtin_and_blocks_incompatible_builtin(marketplace, tmp_path):
    marketplace.refresh()
    catalog = scan_catalog(marketplace.catalog_root)
    builtin_dir = tmp_path / "builtin" / "foo"
    _catalog_plugin(tmp_path / "builtin-src", "foo", "1.0.0")  # nur als Manifest-Vorlage
    import shutil
    shutil.copytree(tmp_path / "builtin-src" / "plugins" / "foo" / "1.0.0", builtin_dir)
    builtin = load_manifest(builtin_dir, "builtin", check_dir_name=False)
    # builtin foo 1.0.0 erfüllt bar -> keep
    plan = resolve(catalog, {"bar": "*"}, {"foo": builtin})
    assert plan.actions[0]["action"] in {"install", "keep"}
    assert any(a["id"] == "foo" and a["action"] == "keep" for a in plan.actions)
    # builtin foo 1.0.0 erfüllt >=2.0.0 nicht -> Konflikt
    with pytest.raises(PluginConflict, match="eingebaute"):
        resolve(catalog, {"foo": ">=2.0.0"}, {"foo": builtin})


def test_uninstall_blocks_dependents_and_removes_files(marketplace):
    marketplace.install("bar")
    with pytest.raises(PluginConflict, match="bar"):
        marketplace.uninstall("foo")
    result = marketplace.uninstall("foo", force=True)
    assert result["removed"] == "foo"
    assert not (marketplace.user_dir / "foo").exists()
    lock = json.loads((marketplace.root / ".material-ui" / "plugins.lock.json").read_text(encoding="utf-8"))
    assert "foo" not in lock["plugins"]
    enabled = json.loads((marketplace.root / ".material-ui" / "plugins.json").read_text(encoding="utf-8"))
    assert enabled["enabled"]["foo"] is False


def test_uninstall_purge_removes_state_dir(marketplace):
    marketplace.install("foo")
    state = marketplace.root / ".material-ui" / "plugins" / "foo"
    state.mkdir(parents=True)
    (state / "settings.json").write_text("{}", encoding="utf-8")
    marketplace.uninstall("foo", purge=True)
    assert not state.exists()


def test_uninstall_refuses_builtin(marketplace, monkeypatch):
    monkeypatch.delenv("MATERIAL_UI_PLUGIN_PATHS", raising=False)
    with pytest.raises(InvalidInput, match="deaktiviert"):
        marketplace.uninstall("kalender")


def test_update_upgrades_to_newer_catalog_version(marketplace, catalog_repo):
    marketplace.install("foo", "^1.0.0")
    assert load_manifest(marketplace.user_dir / "foo", "user").version == "1.1.0"
    _catalog_plugin(catalog_repo, "foo", "1.2.0")
    _git(catalog_repo, "add", "-A")
    _git(catalog_repo, "commit", "-qm", "foo 1.2.0")
    result = marketplace.update("foo")
    action = _actions_by_id(result)["foo"]
    assert action["action"] == "upgrade" and action["version"] == "1.2.0" and action["from"] == "1.1.0"
    assert load_manifest(marketplace.user_dir / "foo", "user").version == "1.2.0"


def test_update_all_respects_dependent_constraints(marketplace, catalog_repo):
    marketplace.install("bar")  # bar braucht foo ^1.0.0
    _catalog_plugin(catalog_repo, "foo", "2.0.0")  # würde bar brechen
    _git(catalog_repo, "add", "-A")
    _git(catalog_repo, "commit", "-qm", "foo 2.0.0")
    result = marketplace.update("all")
    # foo 2.0.0 verletzt ^1.0.0 von bar -> Konflikt, kein Upgrade
    assert _actions_by_id(result).get("foo", {}).get("version") == "1.1.0"


@pytest.fixture()
def app_env(tmp_path, monkeypatch, catalog_repo):
    from material_ui.app import create_app
    from material_ui.config import AppConfig

    previous_modules = {name: module for name, module in sys.modules.items()
                        if name.startswith("material_ui_plugins.")}
    monkeypatch.setenv("MATERIAL_UI_MARKETPLACE_REPO", str(catalog_repo))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    user_plugins = tmp_path / "user-plugins"
    user_plugins.mkdir()
    monkeypatch.setenv("MATERIAL_UI_PLUGIN_PATHS", str(user_plugins))
    repo = tmp_path / "repo"
    repo.mkdir()
    app = create_app(config=AppConfig(repo))
    app.testing = True
    yield app, repo, user_plugins
    app.extensions["material_runtime"].close()
    for module in [name for name in sys.modules if name.startswith("material_ui_plugins.")]:
        del sys.modules[module]
    sys.modules.update(previous_modules)


def test_marketplace_routes_overview_install_uninstall(app_env):
    app, _repo, user_plugins = app_env
    client = app.test_client()
    overview = client.get("/api/marketplace").get_json()
    assert overview["catalog"]["commit"]
    foo = next(p for p in overview["plugins"] if p["id"] == "foo")
    assert foo["installed"] is False and foo["availableVersion"] == "1.1.0"

    result = client.post("/api/marketplace/install", json={"id": "bar"}).get_json()
    assert {a["id"]: a["action"] for a in result["actions"]} == {"bar": "install", "foo": "install"}
    assert result["restartRequired"] is True
    plugins = {p["id"]: p for p in client.get("/api/plugins").get_json()["plugins"]}
    assert plugins["foo"]["status"] == "restart-pending"
    assert plugins["foo"]["enabled"] is True
    assert (user_plugins / "foo" / "plugin.json").exists()

    # Deinstallieren von foo ist blockiert, solange bar installiert ist
    response = client.post("/api/marketplace/uninstall", json={"id": "foo"})
    assert response.status_code == 409
    assert "bar" in response.get_json()["error"]["message"]
    assert client.post("/api/marketplace/uninstall", json={"id": "foo", "force": True}).status_code == 200
    assert "foo" not in {p["id"] for p in client.get("/api/plugins").get_json()["plugins"]}
    assert not (user_plugins / "foo").exists()

    assert client.post("/api/marketplace/install", json={"id": "gibtsnicht"}).status_code == 400
    assert client.post("/api/marketplace/install", json={"id": "foo", "version": ">=9.0.0"}).status_code == 409
    assert client.post("/api/marketplace/update", json={"id": "all"}).status_code == 200
    assert client.post("/api/marketplace/refresh").status_code == 200


@pytest.mark.parametrize("installed", [False, True])
def test_marketplace_warns_when_global_installation_differs_from_project_lock(app_env, installed):
    app, repo, _user_plugins = app_env
    client = app.test_client()
    if installed:
        assert client.post("/api/marketplace/install", json={"id": "foo"}).status_code == 200
    lock_path = repo / ".material-ui" / "plugins.lock.json"
    lock_path.parent.mkdir(exist_ok=True)
    lock_path.write_text(json.dumps({"plugins": {"foo": {"version": "1.0.0"}}}))
    overview = client.get("/api/marketplace").get_json()
    assert "Projekt erwartet 1.0.0" in overview["catalog"]["warning"]
    assert ("1.1.0" if installed else "keine Version") in overview["catalog"]["warning"]


def test_browser_marketplace_install_flow(app_env):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    app, _repo, user_plugins = app_env
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")
        page.locator("#headerMenuToggle").click()
        page.locator("#showSettings").click()
        page.locator("#settingsTabPlugins").click()
        page.wait_for_selector("#settingsModal.open")
        # Katalog geladen: bar und foo als verfügbar gelistet
        page.wait_for_selector("#marketplaceAvailable .plugin-card .plugin-install")
        page.locator("#marketplaceAvailable .plugin-card", has_text="Plugin bar").locator(".plugin-install").click()
        # bar installiert -> foo als Abhängigkeit mit installiert, Neustart-Banner sichtbar
        page.wait_for_selector("#marketplaceRestartBanner:not([hidden])")
        page.wait_for_selector("#marketplaceInstalled .plugin-card")
        names = page.locator("#marketplaceInstalled .plugin-name").all_text_contents()
        assert any("bar" in name for name in names)
        assert any("foo" in name for name in names)
        assert (user_plugins / "foo" / "plugin.json").exists()
        bar = page.locator("#marketplaceInstalled .plugin-card", has_text="Plugin bar")
        assert not bar.locator(".plugin-purge").is_checked()
        page.locator("#closeSettingsModalButton").click()
        page.locator("#headerMenuToggle").click()
        page.locator("#showSettings").click()
        page.locator("#settingsTabPlugins").click()
        page.wait_for_selector("#marketplaceRestartBanner:not([hidden])")
        page.on("dialog", lambda dialog: dialog.accept())
        bar.locator(".plugin-deinstall").click()
        page.wait_for_function("!Array.from(document.querySelectorAll('#marketplaceInstalled .plugin-name')).some(el => el.textContent.includes('bar'))")
        assert not (user_plugins / "bar").exists()
        browser.close()


def test_cli_tasks_use_marketplace(tmp_path, monkeypatch, catalog_repo, capsys):
    import project_tasks

    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    monkeypatch.setenv("MATERIAL_UI_MARKETPLACE_REPO", str(catalog_repo))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    user_plugins = tmp_path / "user-plugins"
    user_plugins.mkdir()
    monkeypatch.setenv("MATERIAL_UI_PLUGIN_PATHS", str(user_plugins))
    project_tasks.plugin_install.body(None, "bar")
    out = capsys.readouterr().out
    assert "install" in out and "foo" in out and "bar" in out
    project_tasks.plugin_list.body(None)
    out = capsys.readouterr().out
    assert "bar" in out and "aktiv" in out
    project_tasks.plugin_uninstall.body(None, "bar")
    project_tasks.plugin_uninstall.body(None, "foo", force=True)
    out = capsys.readouterr().out
    assert "deinstalliert" in out
    assert not (user_plugins / "foo").exists()
