import pytest

from material_ui.app import create_app
from material_ui.config import AppConfig
from test_material_ui import LiveServer, free_port, sync_playwright


@pytest.mark.parametrize("result", ["success", "unavailable", "incompatible", "closed"])
def test_template_dialog_opens_while_loading_and_handles_failure_or_close(tmp_path, result):
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    source = tmp_path / "blatt.qmd"
    original = "---\ntitle: Test\nformat: pdf\n---\n\nAufgaben\n"
    source.write_text(original)
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(f"{url}?path=blatt.qmd", wait_until="networkidle")
            page.wait_for_function('window.materialEditor?.getText().includes("Aufgaben")')
            pending = []
            page.expose_function("hasPendingTemplateCatalog", lambda: bool(pending))
            page.route("**/api/templates", lambda route: pending.append(route))
            with page.expect_request("**/api/templates"):
                page.locator("#changeTemplate").click()
            page.wait_for_function("async () => await window.hasPendingTemplateCatalog()")
            assert page.locator("#templateModal").is_visible()
            assert page.locator("#templateStatus").inner_text() == "Vorlagen werden geladen …"
            for selector in ("#templateType", "#templateSelect", "#applyTemplate", "#removeTemplate"):
                assert page.locator(selector).is_disabled()

            if result == "closed":
                page.locator("#closeTemplateModalButton").click()
            if result in {"unavailable", "incompatible"}:
                message = "Server nicht verfügbar" if result == "unavailable" else "Bitte den Server neu starten"
                pending.pop().fulfill(status=503 if result == "unavailable" else 426,
                                     json={"error": {"message": message}})
                page.wait_for_function(
                    "message => document.querySelector('#templateStatus').textContent.includes(message)",
                    arg=message,
                )
                assert page.locator("#templateModal").is_visible()
                assert page.locator("#removeTemplate").is_disabled()
                # A failed request must allow another attempt.
                page.locator("#closeTemplateModalButton").click()
                with page.expect_request("**/api/templates"):
                    page.locator("#changeTemplate").click()
                page.wait_for_function("async () => await window.hasPendingTemplateCatalog()")

            with page.expect_response("**/api/templates"):
                pending.pop().continue_()
            if result == "closed":
                # Let the asynchronous controller finish before checking for reopening.
                page.evaluate("() => new Promise(resolve => setTimeout(resolve, 100))")
                assert not page.locator("#templateModal").is_visible()
            else:
                page.wait_for_function("!document.querySelector('#templateType').disabled")
                page.locator("#templateType").select_option("Arbeitsblatt")
                assert not page.locator("#applyTemplate").is_disabled()
                assert not page.locator("#removeTemplate").is_disabled()
            assert page.evaluate("window.materialEditor.getText()") == original
            assert source.read_text() == original
            browser.close()
    finally:
        app.extensions["material_runtime"].close()
