import shutil

import pytest

from material_core.metadata import read_metadata, set_template
from material_core.template_versions import TemplateVersions
from material_ui.app import create_app
from material_ui.config import AppConfig
from test_template_versions import versions


@pytest.fixture
def version_app(versions):
    path = versions.support / "templates/worksheet-retro.typst"
    shutil.copy(path.with_name("worksheet-test.typst"), path)
    ref = versions.initial(str(path))
    source = versions.root / "blatt.qmd"
    text = versions.bind(set_template("Hello worksheet\n", "worksheet-retro.typst", "typst"), ref)
    source.write_text(text)
    app = create_app(config=AppConfig(versions.root))
    app.testing = True
    try:
        yield app, source, ref
    finally:
        app.extensions["material_runtime"].close()


def test_api_publish_pins_new_documents_and_only_explicitly_updates_old_ones(version_app):
    app, source, v1 = version_app
    client = app.test_client()
    original = source.read_text()
    data = client.post("/api/template-drafts", json={"release": v1}).get_json()
    draft = data["draft"]
    assert client.post("/api/template-drafts/save", json={"draft": draft, "fontsize": "12pt", "note": "Größer"}).status_code == 200
    assert client.post("/api/template-drafts", json={"release": v1}).get_json()["settings"] == {"fontsize": "12pt"}
    published = client.post("/api/template-drafts/publish", json={"draft": draft, "makeDefault": True}).get_json()
    v2 = published["release"]
    assert published["version"] == 2
    assert source.read_text() == original
    catalog = client.get("/api/templates").get_json()["templates"]
    retro = next(entry for entry in catalog if entry["path"].endswith("worksheet-retro.typst"))
    assert retro["release"] == v2
    assert len(retro["releases"]) == 2
    service = app.extensions["material_runtime"].services.documents
    entry = service.template_by_path("src/quarto/templates/worksheet-retro.typst")
    new = service.document_skeleton("Neu", "Arbeitsblatt", source.with_name("neu.qmd"), entry)
    assert read_metadata(new)["template-release"] == v2
    for ref in (v2, v1):
        response = client.post("/api/document/metadata", json={"text": original,
            "template": "worksheet-retro.typst", "engine": "typst", "release": ref})
        assert response.status_code == 200
        assert response.get_json()["metadata"]["template-release"] == ref
    assert client.post("/api/template-drafts/save", json={"draft": draft, "fontsize": "13pt"}).status_code == 400


@pytest.mark.skipif(not shutil.which("quarto"), reason="Quarto fehlt")
def test_api_pdf_preview_does_not_change_source_or_release(version_app):
    app, source, v1 = version_app
    original = source.read_text()
    client = app.test_client()
    draft = client.post("/api/template-drafts", json={"release": v1}).get_json()["draft"]
    client.post("/api/template-drafts/save", json={"draft": draft, "fontsize": "12pt"})
    response = client.post("/api/template-drafts/preview", json={"draft": draft, "path": "blatt.qmd", "text": original})
    assert response.status_code == 200, response.get_json()
    assert client.get("/api/pdf", query_string={"path": response.get_json()["pdf"]}).status_code == 200
    assert source.read_text() == original
    assert TemplateVersions(source.parent).load(v1)["settings"] == {}
    assert not list(source.parent.glob("template-preview-*.qmd"))


def test_browser_edits_previews_publishes_and_explicitly_switches_version(version_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    app, source, v1 = version_app
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")
        page.locator("#changeTemplate").click()
        page.locator("[data-template-edit]").click()
        page.locator("[data-template-fontsize]").fill("12")
        page.locator("[data-template-note]").fill("Lesbarer")
        page.locator("[data-template-save]").click()
        page.wait_for_function('document.querySelector("[data-template-draft-status]").textContent.includes("Entwurf gespeichert")')
        page.locator("[data-template-publish]").click()
        page.wait_for_function('document.querySelector("#templateStatus").textContent.includes("v2 freigegeben")')
        assert "v1.json" in page.evaluate("window.materialEditor.getText()")
        page.locator("#applyTemplate").click()
        page.wait_for_function('window.materialEditor.getText().includes("v2.json")')
        page.locator("#changeTemplate").click()
        page.locator("[data-template-version]").select_option(v1)
        page.locator("#applyTemplate").click()
        page.wait_for_function('window.materialEditor.getText().includes("v1.json")')
        browser.close()


@pytest.mark.parametrize("accept", [False, True])
def test_api_render_template_offer_and_persistent_decision(version_app, accept):
    from material_ui.storage import revision
    app, source, v1 = version_app
    versions = TemplateVersions(source.parent)
    v2 = versions.initial("worksheet-retro.typst", refresh=True)
    client = app.test_client()
    original = source.read_text()
    offer = client.get("/api/document/template-update", query_string={"path": "blatt.qmd"}).get_json()["offer"]
    assert offer["release"] == v2
    blocked = client.post("/api/render", json={"path": "blatt.qmd"})
    assert blocked.status_code == 409
    assert blocked.get_json()["error"]["code"] == "template_update_required"
    reviewed = client.post("/api/document/template-update", json={"text": original, "release": v2, "accept": accept})
    assert reviewed.status_code == 200
    text = reviewed.get_json()["text"]
    assert source.read_text() == original  # Editor saves through normal revision checks.
    saved = client.post("/api/document", json={"path": "blatt.qmd", "text": text, "revision": revision(original)})
    assert saved.status_code == 200, saved.get_json()
    assert read_metadata(source.read_text())["template-release"] == (v2 if accept else v1)
    assert app.test_client().get("/api/document/template-update", query_string={"path": "blatt.qmd"}).get_json()["offer"] is None
    v3 = versions.initial("worksheet-retro.typst", refresh=True)
    assert client.get("/api/document/template-update", query_string={"path": "blatt.qmd"}).get_json()["offer"]["release"] == v3
    assert client.post("/api/document/template-update", json={"text": text, "release": v2, "accept": True}).status_code == 400
    assert client.post("/api/document/template-update", json={"text": text, "release": v3, "accept": "false"}).status_code == 400
    assert client.get("/api/document/template-update", query_string={"path": "../outside.qmd"}).status_code == 400


def test_browser_remembers_template_choice_after_reload_and_prompts_for_next_version(version_app):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    app, source, v1 = version_app
    versions = TemplateVersions(source.parent)
    v2 = versions.initial("worksheet-retro.typst", refresh=True)
    dialogs = []
    accept = [False]
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        def answer(dialog):
            dialogs.append(dialog.message)
            dialog.accept() if accept[0] else dialog.dismiss()
        page.on("dialog", answer)
        page.route("**/api/render", lambda route: route.fulfill(status=202, json={"job_id": "template-choice-test"}))
        page.route("**/api/jobs/template-choice-test", lambda route: route.fulfill(json={
            "current": "blatt.qmd", "job_id": "template-choice-test", "running": False,
            "ok": True, "message": "Fertig",
        }))
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function('window.materialEditor?.getText().includes("Hello worksheet")')
        for attempt in range(2):
            with page.expect_request("**/api/render"):
                page.locator("#renderDoc").click()
            assert len(dialogs) == 1
        assert read_metadata(source.read_text())["template-release"] == v1
        assert read_metadata(source.read_text())["template-update-reviewed"] == v2
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function('window.materialEditor?.getText().includes("template-update-reviewed")')
        with page.expect_request("**/api/render"):
            page.locator("#renderDoc").click()
        assert len(dialogs) == 1
        v3 = versions.initial("worksheet-retro.typst", refresh=True)
        accept[0] = True
        with page.expect_request("**/api/render"):
            page.locator("#renderDoc").click()
        assert len(dialogs) == 2
        assert read_metadata(source.read_text())["template-release"] == v3
        browser.close()
