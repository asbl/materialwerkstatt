"""Regressionen aus dem Marketplace-Audit vom 2026-11-07."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from material_ui.errors import PluginConflict
from material_ui.plugins.host import PluginHost
from material_ui.plugins.manifest import load_manifest
from material_ui.plugins.marketplace import Marketplace, resolve, scan_catalog
from material_ui.errors import MarketplaceUnavailable
from test_material_ui_marketplace import _catalog_plugin, _git, app_env, catalog_repo, marketplace


def add(catalog, pid, version, deps=None, provides=None):
    _catalog_plugin(catalog, pid, version, {"dependsOn": deps or {}, "provides": provides or []})
    return load_manifest(catalog / "plugins" / pid / version, "user", check_dir_name=False)


def test_install_preserves_existing_dependents(marketplace, catalog_repo):
    marketplace.install("bar")
    add(catalog_repo, "foo", "2.0.0")
    add(catalog_repo, "new", "1.0.0", {"foo": "^2.0.0"})
    _git(catalog_repo, "add", "-A")
    _git(catalog_repo, "commit", "-qm", "incompatible dependency")
    before = (marketplace.user_dir / "foo" / "plugin.json").read_bytes()
    with pytest.raises(PluginConflict):
        marketplace.install("new")
    assert (marketplace.user_dir / "foo" / "plugin.json").read_bytes() == before
    assert not (marketplace.user_dir / "new").exists()


def test_resolver_backtracks_and_discards_old_constraints(tmp_path):
    add(tmp_path, "a", "1.0.0", {"b": "^1.0.0"})
    add(tmp_path, "a", "1.1.0", {"b": "^2.0.0", "unneeded": "*"})
    add(tmp_path, "b", "1.0.0")
    add(tmp_path, "b", "2.0.0")
    add(tmp_path, "unneeded", "1.0.0")
    plan = resolve(scan_catalog(tmp_path), {"a": "*", "b": "^1.0.0"}, {})
    assert {pid: e.manifest.version for pid, e in plan.entries.items()} == {"a": "1.0.0", "b": "1.0.0"}


def test_interface_is_checked_on_selected_version(tmp_path):
    add(tmp_path, "provider", "1.0.0", provides=["room"])
    add(tmp_path, "provider", "2.0.0")
    add(tmp_path, "consumer", "1.0.0", {"@room": "*"})
    plan = resolve(scan_catalog(tmp_path), {"consumer": "*"}, {})
    assert plan.entries["provider"].manifest.version == "1.0.0"


def test_interface_can_choose_another_compatible_provider(tmp_path):
    high = add(tmp_path, "high", "2.0.0", provides=["room"])
    add(tmp_path, "low", "1.0.0", provides=["room"])
    add(tmp_path, "consumer", "1.0.0", {"@room": "^1.0.0"})
    plan = resolve(scan_catalog(tmp_path), {"consumer": "*"}, {"high": high})
    assert plan.entries["low"].manifest.provides == ("room",)


def test_backtracking_avoids_interface_cycle_with_alternative(tmp_path):
    add(tmp_path, "provider", "1.0.0", {"consumer": "*"}, ["room"])
    add(tmp_path, "alternative", "1.0.0", provides=["room"])
    add(tmp_path, "consumer", "1.0.0", {"@room": "*"})
    plan = resolve(scan_catalog(tmp_path), {"consumer": "*"}, {})
    assert "alternative" in plan.entries
    assert "provider" not in plan.entries


def test_kept_install_activates_and_locks_in_each_project(marketplace):
    marketplace.install("bar")
    other = Marketplace(marketplace.root.parent / "other", user_dir=marketplace.user_dir,
                        catalog_root=marketplace.catalog_root)
    other.install("bar", refresh=False)
    assert other.enabled_store.is_enabled("bar", False)
    assert other.enabled_store.is_enabled("foo", False)
    assert set(other.lock.plugins()) == {"bar", "foo"}
    other.enabled_store.set_enabled("bar", False)
    other.install("bar", refresh=False)
    assert other.enabled_store.is_enabled("bar", False)


def test_update_preserves_disabled_state_and_unrelated_versions(marketplace):
    marketplace.install("foo", "1.0.0")
    marketplace.enabled_store.set_enabled("foo", False)
    marketplace.update("foo", refresh=False)
    assert not marketplace.enabled_store.is_enabled("foo", True)
    marketplace.install("iface-provider", refresh=False)
    assert not marketplace.enabled_store.is_enabled("foo", True)


@pytest.mark.parametrize("failure", ["copy", "second-package", "lock", "activation"])
def test_failed_install_rolls_back_code_lock_and_activation(marketplace, monkeypatch, failure):
    marketplace.install("foo", "1.0.0")
    marketplace.enabled_store.set_enabled("foo", False)
    metadata = [marketplace.lock.path, marketplace.enabled_store.path]
    before = {p: p.read_bytes() for p in metadata}
    original_manifest = (marketplace.user_dir / "foo" / "plugin.json").read_bytes()
    if failure == "second-package":
        original = marketplace._install_entry
        def fail(entry):
            if entry.manifest.id == "foo":
                raise OSError("injected")
            original(entry)
        monkeypatch.setattr(marketplace, "_install_entry", fail)
    elif failure == "copy":
        import material_ui.plugins.marketplace as module
        original = module.shutil.copytree
        def fail(source, destination, *args, **kwargs):
            if ".package-stage-" in str(destination) and Path(source).name == "1.1.0":
                raise OSError("injected")
            return original(source, destination, *args, **kwargs)
        monkeypatch.setattr(module.shutil, "copytree", fail)
    else:
        owner, method = (marketplace.lock, "save") if failure == "lock" else (marketplace.enabled_store, "set_enabled")
        original = getattr(owner, method)
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("injected")
        monkeypatch.setattr(owner, method, fail)
    with pytest.raises(OSError, match="injected"):
        marketplace.install("bar", refresh=False)
    assert not (marketplace.user_dir / "bar").exists()
    assert (marketplace.user_dir / "foo" / "plugin.json").read_bytes() == original_manifest
    assert {p: p.read_bytes() for p in metadata} == before
    assert marketplace.lock.plugins() == json.loads(before[marketplace.lock.path])["plugins"]


def test_failed_purge_restores_code_metadata_and_data(marketplace, monkeypatch):
    marketplace.install("foo")
    state = marketplace.root / ".material-ui" / "plugins" / "foo"
    state.mkdir(parents=True)
    (state / "settings.json").write_text('{"keep": true}')
    before = marketplace.lock.path.read_bytes()
    original = marketplace.enabled_store.set_enabled
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("injected")
    monkeypatch.setattr(marketplace.enabled_store, "set_enabled", fail)
    with pytest.raises(OSError):
        marketplace.uninstall("foo", purge=True)
    assert (state / "settings.json").read_text() == '{"keep": true}'
    assert (marketplace.user_dir / "foo" / "plugin.json").exists()
    assert marketplace.lock.path.read_bytes() == before


def test_old_manager_reloads_lock_under_shared_lock(marketplace):
    old = Marketplace(marketplace.root, user_dir=marketplace.user_dir, catalog_root=marketplace.catalog_root)
    marketplace.install("foo")
    old.install("iface-provider", refresh=False)
    assert set(old.lock.plugins()) == {"foo", "iface-provider"}


def test_global_lock_is_shared_across_processes_and_projects(marketplace):
    lock_path = marketplace.user_dir.parent / f".{marketplace.user_dir.name}.marketplace.lock"
    code = "import fcntl,sys; f=open(sys.argv[1], 'a+'); fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)"
    with marketplace.operation_lock():
        result = subprocess.run([sys.executable, "-c", code, str(lock_path)], capture_output=True)
        assert result.returncode != 0
        assert b"BlockingIOError" in result.stderr
    assert subprocess.run([sys.executable, "-c", code, str(lock_path)], capture_output=True).returncode == 0


def test_overview_reports_installed_and_loaded_versions_separately(app_env, catalog_repo):
    app, repo, user_plugins = app_env
    client = app.test_client()
    assert client.post("/api/marketplace/install", json={"id": "foo", "version": "1.0.0"}).status_code == 200
    host = app.extensions["material_runtime"].plugins
    host.states["foo"] = "loaded"
    add(catalog_repo, "foo", "1.2.0", {"iface-provider": "*"})
    _git(catalog_repo, "add", "-A")
    _git(catalog_repo, "commit", "-qm", "upgrade")
    assert client.post("/api/marketplace/update", json={"id": "foo"}).status_code == 200
    data = client.get("/api/marketplace").get_json()
    foo = next(p for p in data["plugins"] if p["id"] == "foo")
    assert foo["installedVersion"] == "1.2.0"
    assert foo["loadedVersion"] == "1.0.0"
    assert foo["status"] == "restart-pending"
    assert foo["updateAvailable"] is False
    assert foo["dependsOn"] == [{"target": "iface-provider", "constraint": "*"}]
    assert not data["catalog"].get("warning")
    assert client.post("/api/plugins/iface-provider/enabled", json={"enabled": False}).status_code == 409


def test_browser_update_shows_new_installed_and_old_loaded_version(app_env):
    from material_ui.app import create_app
    from material_ui.config import AppConfig
    from test_material_ui_marketplace import LiveServer, free_port, sync_playwright

    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    app, repo, _ = app_env
    assert app.test_client().post("/api/marketplace/install", json={"id": "foo", "version": "1.0.0"}).status_code == 200
    restarted = create_app(config=AppConfig(repo))
    restarted.testing = True
    try:
        with LiveServer(restarted, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until="networkidle")
            page.locator("#headerMenuToggle").click()
            page.locator("#showSettings").click()
            page.locator("#settingsTabPlugins").click()
            card = page.locator("#marketplaceInstalled .plugin-card", has_text="Plugin foo")
            card.locator(".plugin-update").click()
            page.wait_for_function("Array.from(document.querySelectorAll('#marketplaceInstalled .plugin-card')).some(el => el.textContent.includes('Aktuell geladen: 1.0.0. Nach Neustart: 1.1.0.'))")
            assert card.locator(".plugin-version").inner_text() == "1.1.0"
            assert card.locator(".plugin-update").count() == 0
            assert page.locator("#marketplaceRestartBanner").is_visible()
            browser.close()
    finally:
        restarted.extensions["material_runtime"].close()


@pytest.mark.parametrize("state", ["error", "incompatible", "blocked", "disabled"])
def test_host_rejects_failed_provider_and_accepts_working_alternative(tmp_path, monkeypatch, state):
    monkeypatch.setenv("MATERIAL_UI_PLUGIN_PATHS", str(tmp_path / "empty"))
    high = add(tmp_path, "high", "2.0.0", provides=["room"])
    low = add(tmp_path, "low", "1.0.0", provides=["room"])
    consumer = add(tmp_path, "consumer", "1.0.0", {"@room": "*"})
    host = PluginHost(None, SimpleNamespace(root=tmp_path / "project"))
    host.manifests = {m.id: m for m in [high, low, consumer]}
    for pid in host.manifests:
        host.enabled_store.set_enabled(pid, True)
    host.states = {"high": state, "low": "error"}
    assert host.dependency_state(consumer)[0] == "blocked"
    host.states["low"] = "loaded"
    assert host.dependency_state(consumer) is None


def test_resolver_skips_versions_needing_newer_app_api(tmp_path):
    from material_ui.protocol import API_VERSION
    add(tmp_path, "foo", "1.0.0")
    _catalog_plugin(tmp_path, "foo", "2.0.0", {"minAppApi": API_VERSION + 1})
    plan = resolve(scan_catalog(tmp_path), {"foo": "*"}, {})
    assert plan.entries["foo"].manifest.version == "1.0.0"


def test_invalid_catalog_entry_does_not_block_other_installs(marketplace, catalog_repo):
    _catalog_plugin(catalog_repo, "future", "1.0.0", {"capabilities": ["clipboard-read"]})
    _git(catalog_repo, "add", "-A")
    _git(catalog_repo, "commit", "-qm", "invalid entry")
    result = marketplace.install("foo")
    assert (marketplace.user_dir / "foo" / "plugin.json").is_file()
    assert "future/1.0.0" in result["catalog"]["warning"]
    problems = []
    assert "foo" in scan_catalog(marketplace.catalog_root, "", problems) and problems
    with pytest.raises(MarketplaceUnavailable):
        scan_catalog(marketplace.catalog_root)


def test_update_leaves_symlinked_and_unlocked_plugins_alone(marketplace, tmp_path):
    from material_ui.errors import InvalidInput
    dev = tmp_path / "dev" / "foo"
    dev.mkdir(parents=True)
    (dev / "plugin.json").write_text(json.dumps(
        {"id": "foo", "name": "foo", "version": "0.9.0", "pythonEntry": "register"}))
    (dev / "__init__.py").write_text("def register(ctx): pass\n")
    (marketplace.user_dir / "foo").symlink_to(dev)
    local = marketplace.user_dir / "local"
    local.mkdir()
    (local / "plugin.json").write_text(json.dumps({"id": "local", "name": "l", "version": "0.1.0"}))
    marketplace.update("all")
    assert (marketplace.user_dir / "foo").is_symlink()
    assert json.loads((marketplace.user_dir / "foo" / "plugin.json").read_text())["version"] == "0.9.0"
    assert marketplace.lock.plugins() == {}
    with pytest.raises(InvalidInput):
        marketplace.update("foo")


def test_changed_catalog_url_replaces_cached_clone(marketplace, catalog_repo, tmp_path):
    from material_ui.plugins.marketplace import refresh_catalog
    marketplace.refresh()
    other = tmp_path / "other-catalog"
    other.mkdir()
    _git(other, "init", "-q")
    _catalog_plugin(other, "only-here", "1.0.0")
    _git(other, "add", "-A")
    _git(other, "commit", "-qm", "other")
    info = refresh_catalog(str(other), marketplace.catalog_root)
    assert set(scan_catalog(marketplace.catalog_root)) == {"only-here"}
    assert info["commit"]
    broken = tmp_path / "does-not-exist"
    with pytest.raises(MarketplaceUnavailable):
        refresh_catalog(str(broken), marketplace.catalog_root)
    assert set(scan_catalog(marketplace.catalog_root)) == {"only-here"}   # alter Cache bleibt erhalten


def test_overview_skips_git_pull_while_catalog_is_fresh(marketplace):
    assert not marketplace.catalog_is_fresh(600)
    marketplace.refresh()
    assert marketplace.catalog_is_fresh(600)
    assert not marketplace.catalog_is_fresh(-1)
