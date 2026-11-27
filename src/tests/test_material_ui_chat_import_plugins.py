"""Integration checks for optional chat/import plugins and their stable entry points."""
import json

import pytest

from material_ui.app import create_app
from material_ui.config import AppConfig
from material_ui.plugins.kurse.preview import PreviewService


@pytest.fixture()
def plugin_app(tmp_path, monkeypatch):
    monkeypatch.setattr(PreviewService, "prewarm", lambda self: None)
    apps = []

    def build(chat=True, importe=True):
        state = tmp_path / "daten" / "plugins.json"
        state.parent.mkdir(exist_ok=True)
        state.write_text(json.dumps({"enabled": {"chat": chat, "importe": importe}}))
        app = create_app(config=AppConfig(tmp_path))
        app.testing = True
        apps.append(app)
        return app

    yield build
    for app in apps:
        app.extensions["material_runtime"].close()


def test_chat_import_plugins_provide_stable_routes_and_service(plugin_app):
    app = plugin_app()
    host = app.extensions["material_runtime"].plugins
    assert host.states["chat"] == host.states["importe"] == "loaded"
    assert host.contexts["importe"].service("chat") is host.contexts["chat"].chat_service
    client = app.test_client()
    for path in ("chat/assets/plugin.js", "chat/assets/chat-panel.js",
                 "chat/assets/chat-panel.css", "importe/assets/plugin.js",
                 "importe/assets/office-import.js", "importe/assets/task-image-import.js"):
        assert client.get("/plugins/" + path).status_code == 200
    assert client.post("/api/document/import/office").status_code == 400
    assert client.post("/api/document/import/task-image").status_code == 400


def test_disabled_chat_blocks_imports_and_removes_routes(plugin_app):
    app = plugin_app(chat=False)
    host = app.extensions["material_runtime"].plugins
    assert host.states["chat"] == "disabled"
    assert host.states["importe"] == "blocked"
    assert "chat" not in host.services
    client = app.test_client()
    assert client.get("/api/chat/providers").status_code == 404
    assert client.post("/api/document/import/office").status_code == 404


@pytest.mark.parametrize("enabled", [True, False])
def test_persisted_chat_panel_respects_plugin_state(plugin_app, enabled):
    from test_material_ui import LiveServer, free_port, sync_playwright

    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    app = plugin_app(chat=enabled, importe=False)
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:chat-open", "true")')
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("document.querySelector(\"#showChat\").hidden === !" + str(enabled).lower())
        if enabled:
            page.wait_for_function("document.querySelector(\"#workspace\").classList.contains(\"chat-open\")")
        assert page.locator("#showChat").is_visible() == enabled
        assert page.locator(".workspace.chat-open").count() == int(enabled)
        if enabled:
            page.wait_for_function('document.querySelector("#chatProvider").options.length > 0')
        browser.close()
