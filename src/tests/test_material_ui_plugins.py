from __future__ import annotations

import json
from pathlib import Path

import pytest

from material_ui.app import create_app
from material_ui.config import AppConfig
from material_ui.plugins.manifest import ManifestError, asset_path, dependency_matches, load_manifest
from material_ui.plugins.storage import PASSWORD_PLACEHOLDER, PluginSettings, PluginStorage

import os
import time
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - haengt von der lokalen Testumgebung ab
    sync_playwright = None

from test_material_ui import LiveServer, free_port, write_qmd


TEST_PLUGIN_MANIFEST = {
    "id": "testp",
    "name": "Testplugin",
    "version": "0.1.0",
    "capabilities": ["state-write"],
    "pythonEntry": "register",
    "jsEntry": "assets/plugin.js",
    "styles": ["assets/test-plugin.css"],
    "icons": "assets/icons.svg",
}

TEST_PLUGIN_PY = """
from flask import Blueprint, jsonify


def register(ctx):
    bp = Blueprint("testp_routes", __name__)

    @bp.get("/api/plugins/testp/echo")
    def echo():
        return jsonify({"message": ctx.settings.load().get("note", "")})

    @bp.post("/api/plugins/testp/echo")
    def set_note():
        from flask import request
        ctx.settings.replace({"note": request.get_json(force=True).get("note", "")})
        return jsonify({"ok": True})

    @bp.post("/api/plugins/testp/job")
    def start_job():
        channel = ctx.jobs.channel("testp")
        identifier = channel.start("testp", "test-op", lambda: {"ok": True, "message": "Erledigt."})
        return jsonify({"job_id": identifier}), 202

    ctx.register_routes(bp)
"""

TEST_PLUGIN_JS = """
export function register(ctx) {
  ctx.views.register({
    id: "hello",
    title: "Hallo",
    icon: "hello",
    order: 40,
    mount(section) {
      section.innerHTML = '<h3>Hallo-Plugin</h3><p data-plugin-hello>aktiv</p>';
    }
  });
  window.__helloPluginLoaded = true;
}
"""

TEST_PLUGIN_ICONS = """<svg xmlns="http://www.w3.org/2000/svg"><symbol id="hello" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7"/></symbol></svg>"""


@pytest.fixture()
def plugin_dirs(tmp_path, monkeypatch):
    """Externe Plugin-Wurzel als einziger Suchort (überschreibt alle Standardorte)."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    monkeypatch.setenv("MATERIAL_UI_PLUGIN_PATHS", str(plugins))
    previous_modules = {name: module for name, module in sys.modules.items()
                        if name.startswith("material_ui_plugins.")}
    yield plugins
    for module in [name for name in sys.modules if name.startswith("material_ui_plugins.")]:
        del sys.modules[module]
    # Other test modules hold imports created during collection. Preserve their
    # module identities so later monkeypatches affect the modules the host loads.
    sys.modules.update(previous_modules)


@pytest.fixture()
def material_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    write_qmd(repo / "unterricht" / "a.qmd")
    return repo


def write_plugin(plugins: Path, plugin_id: str = "testp", manifest: dict | None = None,
                 python_source: str | None = None, broken: bool = False) -> Path:
    directory = plugins / plugin_id
    (directory / "assets").mkdir(parents=True, exist_ok=True)
    if not broken:
        plugin_manifest = manifest or {**TEST_PLUGIN_MANIFEST, "id": plugin_id}
        (directory / "plugin.json").write_text(json.dumps(plugin_manifest), encoding="utf-8")
    (directory / "__init__.py").write_text(python_source if python_source is not None else TEST_PLUGIN_PY, encoding="utf-8")
    (directory / "assets" / "plugin.js").write_text(TEST_PLUGIN_JS, encoding="utf-8")
    (directory / "assets" / "test-plugin.css").write_text("/* test */\n", encoding="utf-8")
    (directory / "assets" / "icons.svg").write_text(TEST_PLUGIN_ICONS, encoding="utf-8")
    return directory


def make_app(repo: Path):
    app = create_app(config=AppConfig(repo))
    app.testing = True
    return app


def with_runtime_cleanup(app):
    runtime = app.extensions["material_runtime"]
    try:
        yield app
    finally:
        runtime.close()


def test_manifest_rejects_invalid_entries(tmp_path):
    directory = write_plugin(tmp_path / "plugins", manifest={"id": "testp", "name": "x"})
    with pytest.raises(ManifestError):
        load_manifest(directory, "user")
    directory = write_plugin(tmp_path / "plugins", manifest={**TEST_PLUGIN_MANIFEST, "id": "anderer-name"})
    with pytest.raises(ManifestError):
        load_manifest(directory, "user")
    directory = write_plugin(tmp_path / "plugins", manifest={**TEST_PLUGIN_MANIFEST, "capabilities": ["unsinn"]})
    with pytest.raises(ManifestError):
        load_manifest(directory, "user")
    directory = write_plugin(tmp_path / "plugins", manifest={**TEST_PLUGIN_MANIFEST, "jsEntry": "../geheim.js"})
    with pytest.raises(ManifestError):
        load_manifest(directory, "user")
    directory = write_plugin(tmp_path / "plugins", manifest={**TEST_PLUGIN_MANIFEST, "styles": "liste-erwartet"})
    with pytest.raises(ManifestError):
        load_manifest(directory, "user")


def test_manifest_depends_on_and_provides(tmp_path):
    base = tmp_path / "plugins"
    raumcast = write_plugin(base, "raumcast", manifest={
        **TEST_PLUGIN_MANIFEST, "id": "raumcast",
        "provides": ["room-cast"],
        "dependsOn": {"stundenplan": ">=0.2.0", "@timetable-events": ["^1.0", "<2.0.0"]},
    })
    manifest = load_manifest(raumcast, "user")
    assert manifest.provides == ("room-cast",)
    assert manifest.depends_on == (("stundenplan", ">=0.2.0"), ("@timetable-events", "^1.0,<2.0.0"))

    stundenplan = write_plugin(base, "stundenplan", manifest={
        **TEST_PLUGIN_MANIFEST, "id": "stundenplan", "provides": ["timetable-events"],
    })
    provider = load_manifest(stundenplan, "user")
    assert dependency_matches("stundenplan", provider)
    assert dependency_matches("@timetable-events", provider)
    assert not dependency_matches("@room-cast", provider)
    assert not dependency_matches("raumcast", provider)


def test_manifest_rejects_invalid_dependencies(tmp_path):
    base = tmp_path / "plugins"
    for depends_on in (
        {"STUNDE": "*"},            # ungültige Plugin-ID
        {"@bad name": "*"},         # ungültiges Interface
        {"testp": "*"},             # Selbstabhängigkeit per ID
        {"andere": "kein-semver"},  # ungültige Bedingung
        {"andere": 42},             # Bedingung keine Zeichenkette
        ["liste"],                  # dependsOn kein Objekt
    ):
        directory = write_plugin(base, manifest={**TEST_PLUGIN_MANIFEST, "dependsOn": depends_on})
        with pytest.raises(ManifestError):
            load_manifest(directory, "user")
    directory = write_plugin(base, manifest={**TEST_PLUGIN_MANIFEST, "provides": ["Bad Name"]})
    with pytest.raises(ManifestError):
        load_manifest(directory, "user")
    directory = write_plugin(base, manifest={**TEST_PLUGIN_MANIFEST, "provides": ["timetable-events"],
                                              "dependsOn": {"@timetable-events": "*"}})
    with pytest.raises(ManifestError):
        load_manifest(directory, "user")


def _order_plugin(plugins: Path, plugin_id: str, order_file: Path, depends_on: dict | None = None) -> None:
    manifest = {**TEST_PLUGIN_MANIFEST, "id": plugin_id}
    if depends_on:
        manifest["dependsOn"] = depends_on
    source = ("def register(ctx):\n"
              f"    with open({str(order_file)!r}, 'a', encoding='utf-8') as fh:\n"
              f"        fh.write({plugin_id + chr(10)!r})\n")
    write_plugin(plugins, plugin_id, manifest=manifest, python_source=source)


def test_host_loads_dependencies_first_and_blocks_disable(plugin_dirs, material_repo, tmp_path):
    order_file = tmp_path / "order.txt"
    _order_plugin(plugin_dirs, "base", order_file)
    _order_plugin(plugin_dirs, "dependent", order_file, depends_on={"base": ">=0.1.0"})
    app = make_app(material_repo)
    try:
        host = app.extensions["material_runtime"].plugins
        host.enabled_store.set_enabled("base", True)
        host.enabled_store.set_enabled("dependent", True)
    finally:
        app.extensions["material_runtime"].close()
    app = make_app(material_repo)
    try:
        host = app.extensions["material_runtime"].plugins
        assert host.states["base"] == "loaded"
        assert host.states["dependent"] == "loaded"
        assert order_file.read_text(encoding="utf-8").splitlines() == ["base", "dependent"]
        client = app.test_client()
        # Deaktivieren von base ist gesperrt, solange dependent aktiv ist
        response = client.post("/api/plugins/base/enabled", json={"enabled": False})
        assert response.status_code == 409
        assert "dependent" in response.get_json()["error"]["message"]
        assert client.post("/api/plugins/dependent/enabled", json={"enabled": False}).status_code == 200
        assert client.post("/api/plugins/base/enabled", json={"enabled": False}).status_code == 200
        assert client.post("/api/plugins/dependent/enabled", json={"enabled": True}).status_code == 200
    finally:
        app.extensions["material_runtime"].close()
    app = make_app(material_repo)
    try:
        host = app.extensions["material_runtime"].plugins
        assert host.states["base"] == "disabled"
        assert host.states["dependent"] == "blocked"
        assert "deaktiviert" in host.load_errors["dependent"]
    finally:
        app.extensions["material_runtime"].close()


def test_host_marks_missing_dependency_and_version_conflict(plugin_dirs, material_repo):
    write_plugin(plugin_dirs, "lonely", manifest={**TEST_PLUGIN_MANIFEST, "id": "lonely",
                                                  "dependsOn": {"ghost": "*"}})
    write_plugin(plugin_dirs, "base2", manifest={**TEST_PLUGIN_MANIFEST, "id": "base2", "version": "0.1.0"})
    write_plugin(plugin_dirs, "picky", manifest={**TEST_PLUGIN_MANIFEST, "id": "picky",
                                                 "dependsOn": {"base2": ">=9.0.0"}})
    app = make_app(material_repo)
    try:
        host = app.extensions["material_runtime"].plugins
        for pid in ("lonely", "picky", "base2"):
            host.enabled_store.set_enabled(pid, True)
    finally:
        app.extensions["material_runtime"].close()
    app = make_app(material_repo)
    try:
        host = app.extensions["material_runtime"].plugins
        assert host.states["lonely"] == "missing-dependency"
        assert host.states["base2"] == "loaded"
        assert host.states["picky"] == "blocked"
        assert "9.0.0" in host.load_errors["picky"]
        data = app.test_client().get("/api/plugins").get_json()["plugins"]
        picky = next(p for p in data if p["id"] == "picky")
        assert picky["dependsOn"] == [{"target": "base2", "constraint": ">=9.0.0"}]
    finally:
        app.extensions["material_runtime"].close()


def test_host_rejects_dependency_cycle(plugin_dirs, material_repo):
    write_plugin(plugin_dirs, "cyc-a", manifest={**TEST_PLUGIN_MANIFEST, "id": "cyc-a", "dependsOn": {"cyc-b": "*"}})
    write_plugin(plugin_dirs, "cyc-b", manifest={**TEST_PLUGIN_MANIFEST, "id": "cyc-b", "dependsOn": {"cyc-a": "*"}})
    app = make_app(material_repo)
    try:
        host = app.extensions["material_runtime"].plugins
        host.enabled_store.set_enabled("cyc-a", True)
        host.enabled_store.set_enabled("cyc-b", True)
    finally:
        app.extensions["material_runtime"].close()
    app = make_app(material_repo)
    try:
        host = app.extensions["material_runtime"].plugins
        assert host.states["cyc-a"] == "error" and "Zykl" in host.load_errors["cyc-a"]
        assert host.states["cyc-b"] == "error"
    finally:
        app.extensions["material_runtime"].close()


def test_asset_path_allows_only_manifest_files(tmp_path):
    directory = write_plugin(tmp_path / "plugins")
    manifest = load_manifest(directory, "user")
    assert asset_path(manifest, "assets/plugin.js") == directory / "assets" / "plugin.js"
    assert asset_path(manifest, "plugin.json") is None
    assert asset_path(manifest, "assets/../__init__.py") is None


def test_settings_mask_passwords(tmp_path):
    storage = PluginStorage(tmp_path / "p")
    settings = PluginSettings(storage)
    merged = settings.replace({"accounts": [{"label": "Schule", "username": "u", "password": "streng"}], "note": "x"})
    assert merged["accounts"][0]["password"] == "streng"
    masked = settings.masked()
    assert masked["accounts"][0]["password"] == PASSWORD_PLACEHOLDER
    assert (tmp_path / "p" / "settings.json").exists()
    assert oct((tmp_path / "p" / "settings.json").stat().st_mode & 0o777) == "0o600"
    # Ein rueckgeschicktes Maskenfeld aendert das Passwort nicht.
    settings.replace({"accounts": [{"label": "Schule", "username": "u", "password": PASSWORD_PLACEHOLDER}]})
    assert settings.load()["accounts"][0]["password"] == "streng"


def test_plugins_endpoint_lists_disabled_user_plugins(plugin_dirs, material_repo):
    write_plugin(plugin_dirs)
    app = make_app(material_repo)
    try:
        client = app.test_client()
        data = client.get("/api/plugins").get_json()["plugins"]
        assert len(data) == 1
        assert data[0]["id"] == "testp"
        assert data[0]["status"] == "disabled"
        assert data[0]["jsUrl"] is None
        # Externe Plugins sind standardmaessig deaktiviert.
        assert client.get("/plugins/testp/assets/plugin.js").status_code == 400
    finally:
        app.extensions["material_runtime"].close()


def test_enable_persists_and_plugin_loads_with_routes_and_assets(plugin_dirs, material_repo):
    write_plugin(plugin_dirs)
    app = make_app(material_repo)
    try:
        client = app.test_client()
        response = client.post("/api/plugins/testp/enabled", json={"enabled": True})
        assert response.status_code == 200
        assert response.get_json()["restartRequired"] is True
    finally:
        app.extensions["material_runtime"].close()

    app = make_app(material_repo)
    try:
        client = app.test_client()
        data = client.get("/api/plugins").get_json()["plugins"][0]
        assert data["status"] == "loaded"
        assert data["jsUrl"].startswith("/plugins/testp/assets/plugin.js?v=")
        assert data["cssUrls"][0].startswith("/plugins/testp/assets/test-plugin.css?v=")
        assert data["iconsHref"].startswith("/plugins/testp/assets/icons.svg?v=")
        # Plugin-Route aus dem Blueprint
        client.post("/api/plugins/testp/echo", json={"note": " Hallo Welt "})
        assert client.get("/api/plugins/testp/echo").get_json()["message"] == " Hallo Welt "
        # Asset-Route liefert nur manifestierte Dateien
        assert client.get("/plugins/testp/assets/plugin.js").status_code == 200
        assert client.get("/plugins/testp/assets/test-plugin.css").text == "/* test */\n"
        assert client.get("/plugins/testp/plugin.json").status_code == 400
        assert client.get("/plugins/testp/assets/../__init__.py").status_code == 400
        # Deaktivieren wirkt erst nach Neustart
        assert client.post("/api/plugins/testp/enabled", json={"enabled": False}).status_code == 200
        assert client.get("/api/plugins").get_json()["plugins"][0]["status"] == "loaded"
    finally:
        app.extensions["material_runtime"].close()


def test_plugin_job_runs_in_exclusive_channel(plugin_dirs, material_repo):
    write_plugin(plugin_dirs)
    app = make_app(material_repo)
    try:
        client = app.test_client()
        assert client.post("/api/plugins/testp/enabled", json={"enabled": True}).status_code == 200
    finally:
        app.extensions["material_runtime"].close()
    app = make_app(material_repo)
    try:
        client = app.test_client()
        response = client.post("/api/plugins/testp/job")
        assert response.status_code == 202
        job_id = response.get_json()["job_id"]
        deadline = time.time() + 10
        record = {}
        while time.time() < deadline:
            record = client.get(f"/api/jobs/{job_id}").get_json()
            if not record["running"]:
                break
            time.sleep(0.1)
        assert record["status"] == "succeeded"
        assert record["ok"] is True
        # Zweiter Start waehrend des ersten Aufrufs fuehrt zu 409 -- hier abgeschlossen.
        assert client.post("/api/plugins/testp/job").status_code == 202
    finally:
        app.extensions["material_runtime"].close()


def test_broken_plugin_fails_isolated(plugin_dirs, material_repo):
    write_plugin(plugin_dirs, plugin_id="ohne-manifest", broken=True)  # kein plugin.json
    write_plugin(plugin_dirs, plugin_id="kaputt", python_source="raise RuntimeError('Kaputt im Register')\n")
    app = make_app(material_repo)
    try:
        client = app.test_client()
        assert client.post("/api/plugins/kaputt/enabled", json={"enabled": True}).status_code == 200
    finally:
        app.extensions["material_runtime"].close()
    app = make_app(material_repo)
    try:
        client = app.test_client()
        plugins = {entry["id"]: entry for entry in client.get("/api/plugins").get_json()["plugins"]}
        # Ohne plugin.json ist der Ordner schlicht kein Plugin und erscheint nicht.
        assert "ohne-manifest" not in plugins
        assert plugins["kaputt"]["status"] == "error"
        assert "Kaputt im Register" in plugins["kaputt"]["message"]
        assert plugins["kaputt"]["enabled"] is True
        # Der Kern funktioniert weiterhin.
        assert client.get("/api/qmds").status_code == 200
        assert client.post("/api/plugins/unbekannt/enabled", json={"enabled": True}).status_code == 400
        assert client.post("/api/plugins/ohne-manifest/enabled", json={"enabled": True}).status_code == 400
    finally:
        app.extensions["material_runtime"].close()


def test_plugin_routes_require_token_outside_testing(plugin_dirs, material_repo):
    write_plugin(plugin_dirs)
    app = make_app(material_repo)
    try:
        assert app.test_client().post("/api/plugins/testp/enabled", json={"enabled": True}).status_code == 200
    finally:
        app.extensions["material_runtime"].close()
    app = make_app(material_repo)
    app.testing = False
    try:
        client = app.test_client()
        token = app.config["MATERIAL_CSRF_TOKEN"]
        response = client.get("/api/plugins/testp/echo")
        assert response.status_code == 200
        response = client.post("/api/plugins/testp/echo", json={"note": "x"},
                               headers={"X-Material-Token": token})
        assert response.status_code == 200
        assert client.post("/api/plugins/testp/echo", json={"note": "x"},
                           headers={"X-Material-Token": "falsch"}).status_code == 403
        origin = client.post("/api/plugins/testp/echo", json={"note": "x"},
                             headers={"X-Material-Token": token, "Origin": "http://boese.example"})
        assert origin.status_code == 403
    finally:
        app.extensions["material_runtime"].close()


def test_browser_shows_plugin_view_in_rail_and_persists_choice(plugin_dirs, material_repo):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_plugin(plugin_dirs)
    app = make_app(material_repo)
    try:
        client = app.test_client()
        assert client.post("/api/plugins/testp/enabled", json={"enabled": True}).status_code == 200
    finally:
        app.extensions["material_runtime"].close()
    app = make_app(material_repo)
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until="networkidle")
            page.wait_for_selector("#viewButton-hello", state="attached")
            assert page.evaluate("window.__helloPluginLoaded === true")
            page.locator("#viewButton-hello").click()
            page.wait_for_selector("[data-plugin-hello]")
            assert page.locator("#viewSection-hello").is_visible()
            assert page.locator("#folderEntries").is_hidden()
            assert page.evaluate("localStorage.getItem('material-ui:active-view')") == "hello"
            page.reload(wait_until="networkidle")
            # Die Plugin-Ansicht wird nach dem Neuladen wiederhergestellt.
            page.wait_for_selector("[data-plugin-hello]")
            assert page.locator("#folderEntries").is_hidden()
            # Ordneransicht bleibt erreichbar.
            page.locator("#folderViewButton").click()
            page.wait_for_function("document.querySelector('#folderEntries').offsetParent !== null")
            browser.close()
    finally:
        app.extensions["material_runtime"].close()


def test_context_offers_units_and_workers_facades(material_repo, plugin_dirs):
    from material_ui.plugins.context import PluginContext
    write_plugin(plugin_dirs)
    app = make_app(material_repo)
    runtime = app.extensions['material_runtime']
    try:
        manifest = runtime.plugins.manifests['testp']
        context = PluginContext(manifest, runtime=runtime, state_dir=material_repo / '.material-ui/plugins/testp')
        runtime.plugins.contexts['testp'] = context
        assert not hasattr(context, "calendar")   # Kalenderquellen laufen über @calendar des Kalender-Plugins
        assert context.units.scheduled() == []
        assert context.workers.closing is runtime.closing
    finally:
        runtime.close()


@pytest.mark.parametrize("register_service", [False, True])
@pytest.mark.parametrize("exception", ["RuntimeError('registration failed')", "ModuleNotFoundError('missing dependency', name='missing_dependency')"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_failed_provider_is_rolled_back_and_blocks_dependents(
        plugin_dirs, material_repo, tmp_path, register_service, exception, cleanup_fails):
    from material_ui.plugins.host import PluginHost
    from material_ui.runtime import RuntimeState

    events = tmp_path / "cleanup.txt"
    source = f'''
def register(ctx):
    def record(text):
        with open({str(events)!r}, "a") as stream:
            stream.write(text + "\\n")
    def cleanup():
        record("shutdown")
        if {cleanup_fails!r}:
            raise RuntimeError("cleanup failed")
    ctx.lifecycle.on_shutdown(cleanup)
    ctx.lifecycle.on_shutdown(lambda: record("second shutdown"))
    ctx.jobs.close = lambda: record("jobs")
    if {register_service!r}:
        ctx.register_service("chat", object())
    raise {exception}
'''
    write_plugin(plugin_dirs, "provider", manifest={**TEST_PLUGIN_MANIFEST, "id": "provider",
                                                  "provides": ["chat"]}, python_source=source)
    for pid, dependency in (("consumer", "@chat"), ("direct", "provider")):
        write_plugin(plugin_dirs, pid, manifest={**TEST_PLUGIN_MANIFEST, "id": pid,
                                                "dependsOn": {dependency: "*"}})
    write_plugin(plugin_dirs, "healthy", manifest={**TEST_PLUGIN_MANIFEST, "id": "healthy"},
                 python_source="def register(ctx): pass\n")
    runtime = RuntimeState(config=AppConfig(material_repo))
    host = PluginHost(runtime, runtime.config)
    runtime.plugins = host
    for pid in host.manifests:
        host.enabled_store.set_enabled(pid, True)
    try:
        host.load()
        assert host.states["provider"] in {"error", "missing-dependency"}
        assert host.states["consumer"] == host.states["direct"] == "blocked"
        assert host.states["healthy"] == "loaded"
        assert "registration failed" in host.load_errors["provider"] or "missing_dependency" in host.load_errors["provider"]
        assert "provider" not in host.contexts
        assert "chat" not in host.services
        with pytest.raises(LookupError):
            host.service("chat")
        assert events.read_text().splitlines() == ["shutdown", "second shutdown", "jobs"]
        # Even a stale registry entry must never expose a failed provider.
        host.services["chat"] = ("provider", object())
        with pytest.raises(LookupError):
            host.service("chat")
    finally:
        runtime.close()
    assert events.read_text().splitlines() == ["shutdown", "second shutdown", "jobs"]


def test_require_service_survives_plugins_that_overwrite_ctx_service(plugin_dirs, material_repo):
    from material_ui.plugins.host import PluginHost
    from material_ui.runtime import RuntimeState

    write_plugin(plugin_dirs, "provider", manifest={**TEST_PLUGIN_MANIFEST, "id": "provider", "provides": ["room"]},
                 python_source="def register(ctx):\n    ctx.register_service('room', 'raum')\n")
    write_plugin(plugin_dirs, "consumer",
                 manifest={**TEST_PLUGIN_MANIFEST, "id": "consumer", "dependsOn": {"@room": "*"}},
                 python_source=("class Own:\n    value = 1\n\n"
                                "def register(ctx):\n    ctx.service = Own()\n"
                                "    ctx.found = ctx.require_service('room')\n"
                                "    ctx.found_call = ctx.service('room')\n"
                                "    ctx.service.value = 2\n"))
    runtime = RuntimeState(config=AppConfig(material_repo))
    host = PluginHost(runtime, runtime.config)
    runtime.plugins = host
    for pid in host.manifests:
        host.enabled_store.set_enabled(pid, True)
    host.load()
    assert host.states["consumer"] == "loaded"
    consumer = host.contexts["consumer"]
    assert consumer.found == "raum"
    assert consumer.found_call == "raum"      # ctx.service(...) bleibt trotz eigenem Dienst aufrufbar
    assert consumer.service.value == 2        # Attribute gehen an den eigenen Dienst
    assert consumer.own_service.value == 2


def test_unrecognized_plugin_folder_is_reported(plugin_dirs, material_repo):
    from material_ui.plugins.host import PluginHost
    from material_ui.runtime import RuntimeState

    write_plugin(plugin_dirs, "kaputt", manifest={**TEST_PLUGIN_MANIFEST, "id": "kaputt", "capabilities": ["nope"]})
    runtime = RuntimeState(config=AppConfig(material_repo))
    host = PluginHost(runtime, runtime.config)
    assert any("nope" in message for message in host.problems())


def test_application_fingerprint_follows_symlinked_plugins(plugin_dirs, tmp_path):
    from material_ui.desktop import application_version

    dev = tmp_path / "dev" / "linked"
    dev.mkdir(parents=True)
    (dev / "plugin.json").write_text("{}")
    (dev / "x.js").write_text("a")
    (plugin_dirs / "linked").symlink_to(dev)
    before = application_version()
    (dev / "x.js").write_text("b")
    assert application_version() != before


def test_frontend_plugin_context_offers_documents_open(tmp_path):
    """Plugins öffnen Dokumente über ctx.documents.open; ohne Kernhaken bleibt es ein No-op."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    loader = (Path(__file__).resolve().parents[1] / "material_ui/static/plugins/loader.js").as_uri()
    script = f"""
import assert from "node:assert/strict";
import {{ loadPlugins }} from "{loader}";
const module = "export function register(ctx) {{ globalThis.pluginCtx = ctx; }}";
const jsUrl = "data:text/javascript," + encodeURIComponent(module);
const api = async () => ({{ plugins: [{{ id: "demo", name: "Demo", status: "loaded", jsUrl }}] }});
const views = {{ activeId: () => "folder", has: () => false }};
const opened = [];
await loadPlugins({{ api, views, ui: {{}}, state: {{ plugins: {{}} }},
  documents: {{ register() {{}}, resolve() {{}} }}, openDocument: path => {{ opened.push(path); return "ok"; }} }});
assert.equal(globalThis.pluginCtx.documents.open("unterricht/a.qmd"), "ok");
assert.deepEqual(opened, ["unterricht/a.qmd"]);
await loadPlugins({{ api, views, ui: {{}}, state: {{ plugins: {{}} }}, documents: {{ register() {{}}, resolve() {{}} }} }});
assert.equal(globalThis.pluginCtx.documents.open("x.qmd"), undefined);
"""
    script_path = tmp_path / "check.mjs"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run([node, str(script_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_manifest_host_apis_are_validated_and_exposed(tmp_path):
    from material_ui.plugins.manifest import ManifestError, load_manifest

    good = write_plugin(tmp_path, "gp", {**TEST_PLUGIN_MANIFEST, "id": "gp", "hostApis": ["chat", "course-workspace"]})
    assert load_manifest(good, "user").host_apis == ("chat", "course-workspace")
    assert load_manifest(write_plugin(tmp_path, "np", {**TEST_PLUGIN_MANIFEST, "id": "np"}), "user").host_apis == ()
    for bad in ("chat", ["Chat!"], [1]):
        directory = write_plugin(tmp_path, "bad", {**TEST_PLUGIN_MANIFEST, "id": "bad", "hostApis": bad})
        with pytest.raises(ManifestError, match="hostApis"):
            load_manifest(directory, "user")


def test_frontend_loader_passes_only_declared_host_apis(tmp_path):
    """Plugins erhalten nur die im Manifest deklarierten Host-Schnittstellen; Aliase lösen alte Ansichten auf."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    root = Path(__file__).resolve().parents[1] / "material_ui/static"
    loader = (root / "plugins/loader.js").as_uri()
    registry = (root / "views.js").as_uri()
    script = f"""
import assert from "node:assert/strict";
import {{ loadPlugins }} from "{loader}";
import {{ createViewRegistry }} from "{registry}";
const seen = {{}};
const source = (id) => "data:text/javascript," + encodeURIComponent(
  `export function register(ctx) {{ globalThis.seen = globalThis.seen || {{}}; globalThis.seen["${{id}}"] = Object.keys(ctx.deps).sort(); }}`);
const plugins = [
  {{ id: "a", name: "A", status: "loaded", jsUrl: source("a"), hostApis: ["one"] }},
  {{ id: "b", name: "B", status: "loaded", jsUrl: source("b"), hostApis: [] }},
  {{ id: "c", name: "C", status: "loaded", jsUrl: source("c"), hostApis: ["fehlt"] }},
];
const messages = [];
const views = {{ activeId: () => "units", has: () => false, resolve: id => id }};
await loadPlugins({{ api: async () => ({{ plugins }}), views, ui: {{}}, state: {{ plugins: {{}} }},
  hostApis: {{ one: () => ({{ x: 1, y: 2 }}), two: () => ({{ z: 3 }}) }},
  onStatus: message => messages.push(message) }});
assert.deepEqual(globalThis.seen.a, ["x", "y"]);
assert.deepEqual(globalThis.seen.b, []);
assert.equal(globalThis.seen.c, undefined);
assert.ok(messages.some(message => message.includes("fehlt")));

const state = {{ navigationView: "units" }};
const registry = createViewRegistry({{ state, rail: null, sections: null }});
const button = {{ classList: {{ toggle() {{}} }}, setAttribute() {{}}, addEventListener() {{}} }};
registry.registerView({{ id: "agenda", aliases: ["kalender"], button }});
assert.equal(registry.resolve("kalender"), "agenda");
assert.equal(registry.resolve("agenda"), "agenda");
assert.equal(registry.resolve("unbekannt"), "unbekannt");
"""
    script_path = tmp_path / "check.mjs"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run([node, str(script_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_project_plugins_win_over_user_plugins_and_are_visible_to_the_marketplace(tmp_path, monkeypatch):
    from material_ui.plugins.manifest import discover_manifests
    from material_ui.plugins.marketplace import discover_installed
    from material_ui.plugins.paths import project_plugin_paths

    def write(base: Path, note: str) -> None:
        folder = base / "privat"
        folder.mkdir(parents=True)
        (folder / "plugin.json").write_text(json.dumps({**TEST_PLUGIN_MANIFEST, "id": "privat", "name": note}), encoding="utf-8")

    data = tmp_path / "data"
    monkeypatch.delenv("MATERIAL_UI_PLUGIN_PATHS", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    write(data / "material-ui/plugins", "aus dem Benutzerordner")
    write(tmp_path / "repo/plugins", "projektlokal")
    extra = tuple(project_plugin_paths(tmp_path / "repo"))
    found = {m.id: m for m, _ in discover_manifests(extra) if m is not None}
    assert found["privat"].source == "project" and found["privat"].name == "projektlokal"
    assert discover_installed(extra)["privat"].source == "project"
