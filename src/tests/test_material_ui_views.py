from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_material_ui import LiveServer, free_port, sync_playwright, write_qmd
from material_ui.app import create_app
from material_ui.config import AppConfig
from material_ui.desktop import application_version


def _button_stub():
    return {
        "classList": {"toggle": lambda *_: None},
        "attributes": {},
        "listeners": [],
        "setAttribute": lambda self, key, value: self["attributes"].__setitem__(key, value),
        "addEventListener": lambda self, event, listener: self["listeners"].append((event, listener)),
    }


def test_view_registry_switches_guards_and_persists():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(__file__).resolve().parents[1] / "material_ui/static/views.js").as_uri()
    script = '''
import assert from "node:assert/strict";
import { createViewRegistry, loadActiveViewPreference } from MODULE;
function buttonStub() {
  const button = { classes: {}, attrs: {}, addEventListener(event, listener) { this.click = listener; } };
  button.classList = { toggle: (name, on) => { button.classes[name] = on; } };
  button.setAttribute = (key, value) => { button.attrs[key] = value; };
  return button;
}
const state = { navigationView: "folder" };
const calls = [];
let guardAllows = true;
const saved = [];
const registry = createViewRegistry({
  state, rail: null, sections: null,
  onLeaveActive: async () => { calls.push("guard"); return guardAllows; },
  saveActiveView: (id) => { saved.push(id); }
});
const folderButton = buttonStub();
const tagButton = buttonStub();
registry.registerView({ id: "folder", title: "Ordner", icon: "folder", button: folderButton,
  onActivate: () => calls.push("activate:folder"), onDeactivate: () => calls.push("deactivate:folder") });
registry.registerView({ id: "tagTree", title: "Tags: Baum", icon: "tag", button: tagButton,
  onPrepare: async () => {
    await Promise.resolve();
    assert.equal(state.navigationView, "folder");
    calls.push("prepare:tagTree");
  },
  onActivate: () => calls.push("activate:tagTree") });
// Unbekannte Ansichten werden abgewiesen, der Zustand bleibt unberuehrt.
assert.equal(await registry.switchTo("kalender"), false);
assert.equal(state.navigationView, "folder");
// Guard blockiert den Wechsel.
guardAllows = false;
assert.equal(await registry.switchTo("tagTree"), false);
assert.equal(state.navigationView, "folder");
assert.deepEqual(calls, ["guard"]);
// Freigegebener Wechsel aktiviert die neue und deaktiviert die alte Ansicht und persistiert.
guardAllows = true;
calls.length = 0;
assert.equal(await registry.switchTo("tagTree"), true);
assert.equal(state.navigationView, "tagTree");
assert.deepEqual(calls, ["guard", "prepare:tagTree", "deactivate:folder", "activate:tagTree"]);
assert.deepEqual(saved, ["tagTree"]);
assert.equal(folderButton.classes["active"], false);
assert.equal(folderButton.attrs["aria-pressed"], "false");
assert.equal(tagButton.classes["active"], true);
assert.equal(tagButton.attrs["aria-pressed"], "true");
// Klick auf die bereits aktive Ansicht laeuft durch den Guard, aktiviert aber nicht erneut.
calls.length = 0;
assert.equal(await registry.switchTo("tagTree"), true);
assert.deepEqual(calls, ["guard"]);
// Gleichzeitige Registrierung einer existierenden Id bleibt beim ersten Treffer.
const first = registry.view("tagTree");
registry.registerView({ id: "tagTree", title: "Andere" });
assert.equal(registry.view("tagTree"), first);
assert.equal(loadActiveViewPreference(), "");
'''.replace("MODULE", json.dumps(module))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_view_choice_persists_across_reload_and_restores_active_list(tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(tmp_path / "unterricht" / "a.qmd", "---\ntitle: Blatt A\ntags: [mathe]\n---\n\nText A\n")
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    assert app.test_client().post("/api/tags/root", json={"tag": "mathe", "root": True}).status_code == 200
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
            page.goto(url, wait_until="networkidle")

            # Ausgangslage: Ordneransicht offen, Tag-Baum zu.
            assert page.locator("#folderViewButton").get_attribute("aria-pressed") == "true"
            assert page.locator("#folderEntries").is_visible()
            page.locator("#tagTreeViewButton").click()
            page.wait_for_selector("#tagEntries button[data-subject]")
            assert page.locator("#folderEntries").is_hidden()
            assert page.locator("#tagTreeViewButton").get_attribute("aria-pressed") == "true"
            assert page.locator("#folderViewButton").get_attribute("aria-pressed") == "false"
            assert page.evaluate("localStorage.getItem('material-ui:active-view')") == "tagTree"

            # Neuladen stellt die gewählte Ansicht wieder her.
            page.reload(wait_until="networkidle")
            page.wait_for_selector("#tagEntries button[data-subject]")
            assert page.locator("#folderEntries").is_hidden()

            # Ein Klick auf die Ordneransicht öffnet die Ordnerliste wieder und persistiert.
            page.locator("#folderViewButton").click()
            page.wait_for_function("document.querySelector('#folderEntries').offsetParent !== null")
            assert page.locator("#folderViewButton").get_attribute("aria-pressed") == "true"
            assert page.evaluate("localStorage.getItem('material-ui:active-view')") == "folder"
            browser.close()
    finally:
        app.extensions["material_runtime"].close()


def test_unknown_persisted_view_falls_back_to_folder(tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(tmp_path / "unterricht" / "a.qmd", "---\ntitle: Blatt A\n---\n\nText A\n")
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('''
localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder");
localStorage.setItem("material-ui:active-view", "gibt-es-nicht");
''')
            page.goto(url, wait_until="networkidle")
            page.wait_for_function("document.querySelector('#folderEntries').offsetParent !== null")
            assert page.locator("#folderViewButton").get_attribute("aria-pressed") == "true"
            browser.close()
    finally:
        app.extensions["material_runtime"].close()


def test_asset_version_is_stable_and_independent_of_cwd():
    version = application_version()
    assert len(version) == 64
    assert application_version() == version
