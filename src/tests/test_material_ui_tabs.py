import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_material_ui import LiveServer, free_port, sync_playwright
from test_material_ui_robustness import replace_editor_text
from material_ui.app import create_app
from material_ui.config import AppConfig


def test_browser_closes_other_tabs_after_save_confirmation(tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    for name in ("first.qmd", "active.qmd", "last.qmd"):
        (tmp_path / name).write_text("Text\n")
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('''
localStorage.setItem("material-ui:auto-render", "false");
localStorage.setItem("material-ui:auto-save", "false");
localStorage.setItem("material-ui:open-tabs", JSON.stringify(["first.qmd", "active.qmd", "last.qmd"]));
''')
            page.goto(f"{url}?path=active.qmd", wait_until="networkidle")
            page.wait_for_function("window.materialEditor && window.materialEditor.getText() === 'Text\\n'")
            replace_editor_text(page, "Geänderter Text")
            page.once("dialog", lambda dialog: dialog.dismiss())
            page.locator('[data-tab="last.qmd"]').click(button="right")
            page.get_by_role("menuitem", name="Andere Tabs schließen").click()
            assert page.locator(".document-tab").count() == 3
            assert (tmp_path / "active.qmd").read_text() == "Text\n"
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator('[data-tab="last.qmd"]').click(button="right")
            page.get_by_role("menuitem", name="Andere Tabs schließen").click()
            page.wait_for_function("document.querySelectorAll('.document-tab').length === 1")
            assert page.locator('[data-tab="last.qmd"]').get_attribute("aria-current") == "true"
            assert (tmp_path / "active.qmd").read_text() == "Geänderter Text"
            browser.close()
    finally:
        app.extensions["material_runtime"].close()


def test_tabs_save_before_closing_and_preserve_tabs_on_cancel_or_failure():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(__file__).resolve().parents[1] / "material_ui/static/tabs.js").as_uri()
    script = '''
import assert from "node:assert/strict";
import { createTabsController } from MODULE;
globalThis.localStorage = { setItem() {} };
for (const action of ["closeTab", "closeOtherTabs"]) {
  for (const outcome of ["saved", "cancelled", "save-error", "load-error", "auto-save"]) {
    const state = { tabs: ["first", "active", "last"], qmdPath: "active", dirty: true,
      autoSave: outcome === "auto-save" };
    const calls = [];
    globalThis.window = { confirm: () => { calls.push("confirm"); return outcome !== "cancelled"; } };
    const controller = createTabsController({
      state, elements: {}, tabLabel: path => path,
      flushPendingSave: async () => {
        calls.push("save");
        assert.deepEqual(state.tabs, ["first", "active", "last"]);
        if (outcome === "save-error") throw new Error("save failed");
        state.dirty = false;
      },
      selectDocument: async path => {
        calls.push("select");
        assert.equal(state.dirty, false);
        if (outcome === "load-error") throw new Error("load failed");
        state.qmdPath = path;
      },
      closeDocument: () => { state.qmdPath = ""; }
    });
    const pending = controller[action](action === "closeTab" ? "active" : "last");
    if (outcome.endsWith("error")) await assert.rejects(pending, /failed/);
    else await pending;
    if (["saved", "auto-save"].includes(outcome)) {
      assert.deepEqual(state.tabs, action === "closeTab" ? ["first", "last"] : ["last"]);
      assert.equal(state.qmdPath, "last");
      assert.deepEqual(calls, outcome === "auto-save" ? ["save", "select"] : ["confirm", "save", "select"]);
    } else {
      assert.deepEqual(state.tabs, ["first", "active", "last"]);
      assert.equal(state.qmdPath, "active");
      if (outcome === "cancelled") assert.deepEqual(calls, ["confirm"]);
    }
  }
}
const state = { tabs: ["active", "other"], qmdPath: "active", dirty: true };
const controller = createTabsController({ state, elements: {},
  flushPendingSave: () => { throw new Error("Active tab must stay untouched"); } });
await controller.closeOtherTabs("active");
assert.deepEqual(state.tabs, ["active"]);
assert.equal(state.dirty, true);
state.autoSave = true;
state.dirty = false;
const last = createTabsController({ state, elements: {}, flushPendingSave: async () => {},
  closeDocument: () => { state.qmdPath = ""; } });
await last.closeTab("active");
assert.deepEqual(state.tabs, []);
assert.equal(state.qmdPath, "");
'''.replace("MODULE", json.dumps(module))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
