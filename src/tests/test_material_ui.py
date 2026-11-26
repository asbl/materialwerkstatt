from __future__ import annotations

import base64
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import pymupdf
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_ui import app as material_app  # noqa: E402
from material_ui.assets import image_markdown, meta_yaml, parse_tags, sanitize_stem, yaml_string  # noqa: E402
from material_ui.desktop import application_version  # noqa: E402
from material_ui.documents import DocumentService  # noqa: E402
from material_ui.rendering import render_detail, render_error_summary  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - depends on local test environment
    sync_playwright = None


PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nmini").decode("ascii")


def _kurs_context():
    from material_ui.runtime import current_runtime
    runtime = current_runtime()
    if runtime.plugins is None:
        material_app.create_app()
    return runtime.plugins.contexts["kurse"]


def kurs_service():
    """CourseService des geladenen kurse-Plugins (frueher material_app.services().courses)."""
    return _kurs_context().service


def kurs_preview():
    """PreviewService des kurse-Plugins (frueher material_app.services().preview)."""
    return _kurs_context().preview


def skip_if_private_templates():
    """Katalogzaehlungen gelten fuer den oeffentlichen Bestand (MATERIAL_PRIVATE_DIR=_nicht_vorhanden)."""
    from material_core.template_roots import private_templates

    if private_templates().is_dir() or (private_templates().parent / "template-definitions.json").is_file():
        pytest.skip("Privater Vorlagenordner aktiv: Zaehlung gilt nur fuer den oeffentlichen Katalog")


@pytest.fixture()
def material_root(tmp_path, monkeypatch):
    from material_ui.runtime import RuntimeState, runtime_scope

    root = tmp_path / "repo"
    root.mkdir()
    # tmp_path liegt wegen --basetemp=.pytest-basetemp im Projekt-Repo; ohne Obergrenze
    # hielte Git die Test-Wurzel fuer ein Arbeitsverzeichnis des Projekts.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setattr(material_app, "ROOT", root)
    runtime = RuntimeState()
    from course_sync.application import CourseApplication
    from course_sync.config import settings
    from zipfile import ZipFile

    def build_package(question):
        question.package_path.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(question.package_path, "w") as archive:
            archive.writestr("h5p.json", json.dumps({"title": question.title, "mainLibrary": question.main_library}))
            archive.writestr("content/content.json", "{}")
        return question.package_path

    runtime.course_application = CourseApplication(settings.build_app_config().with_root(root))
    runtime.course_application.write_h5p_package = build_package
    factory = material_app.create_app

    def create_test_app():
        app = factory(runtime=runtime)
        app.config.update(TESTING=True)
        return app

    monkeypatch.setattr(material_app, "create_app", create_test_app)
    with runtime_scope(runtime):
        material_app.initialize_runtime(runtime)
        try:
            yield root
        finally:
            runtime.close()


def write_qmd(path: Path, text: str = "---\ntitle: Testmaterial\n---\n\n<!-- material-ui -->\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_pdf(path: Path, text: str = "Test") -> Path:
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), text)
        document.save(path)
    return path


def staged_pdf(command) -> Path:
    return Path(command[2]).parent / command[command.index("--output") + 1]


def write_kurs_index(course_dir: Path, title: str | None = None, chapters=()) -> Path:
    course_dir.mkdir(parents=True, exist_ok=True)
    heading = f"# {title}\n\n" if title else ""
    tags = "\n".join(f'<Chapter src="./chapters/{slug}.mdx" title="{chapter_title}" />' for slug, chapter_title in chapters)
    (course_dir / "index.mdx").write_text(f"{heading}{tags}\n", encoding="utf-8")
    return course_dir


def host_css() -> str:
    """Alle Host-Stylesheets in Ladereihenfolge (templates/index.html): die Kaskade ist ihre Reihenfolge."""
    import re

    base = Path(__file__).resolve().parents[1] / "material_ui"
    template = (base / "templates" / "index.html").read_text(encoding="utf-8")
    names = re.findall(r"asset_url\('(app[\w-]*\.css)'\)", template)
    assert names and names[0] == "app.css"
    return "\n".join((base / "static" / name).read_text(encoding="utf-8") for name in names)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def replace_editor_text(page, text):
    """Ersetzt den Editorinhalt wie eine Benutzereingabe (loest input/autosave aus)."""
    page.locator(".editor-host .cm-content").click()
    page.keyboard.press("Control+A")
    page.keyboard.type(text)


def editor_text(page):
    return page.evaluate("window.materialEditor.getText()")


class LiveServer:
    def __init__(self, app, port: int):
        # threaded: Der Browser haelt eine Server-Event-Verbindung (/api/jobs/stream)
        # offen; ein einstrangiger Server wuerde darauf blockieren.
        self.server = make_server("127.0.0.1", port, app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.url = f"http://127.0.0.1:{port}"

    def __enter__(self):
        self.thread.start()
        return self.url

    def __exit__(self, _exc_type, _exc, _tb):
        self.server.shutdown()
        self.thread.join(timeout=5)


def test_desktop_status_identifies_repository(material_root):
    response = material_app.create_app().test_client().get("/api/desktop-status")
    data = response.get_json()
    assert data["application"] == "material-ui"
    assert data["root"] == str(material_root)
    assert data["version"] == application_version()
    assert data["pid"] == os.getpid()


def test_pdf_preview_resize_and_fullscreen(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "blatt.qmd")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url, wait_until="networkidle")
        preview = page.locator(".preview-pane")
        initial_width = preview.bounding_box()["width"]
        resizer = page.locator("#previewResizer")
        bounds = resizer.bounding_box()
        page.mouse.move(bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2)
        page.mouse.down()
        page.mouse.move(bounds["x"] - 130, bounds["y"] + bounds["height"] / 2, steps=5)
        page.mouse.up()
        assert preview.bounding_box()["width"] > initial_width + 100
        assert not page.locator("body").evaluate("element => element.classList.contains('resizing-preview')")
        resizer.focus()
        page.keyboard.press("ArrowRight")
        resized_width = preview.bounding_box()["width"]
        assert resized_width > initial_width
        button = page.locator("#togglePdfFullscreen")
        button.click()
        page.wait_for_function("document.body.classList.contains('pdf-fullscreen')")
        assert preview.bounding_box()["width"] == page.evaluate("innerWidth")
        assert preview.bounding_box()["height"] == page.evaluate("innerHeight")
        assert page.locator(".editor-pane").evaluate("element => element.inert")
        assert not page.locator("#renderDoc").is_visible()
        assert button.get_attribute("aria-pressed") == "true"
        button.click()
        page.wait_for_function("!document.fullscreenElement && !document.body.classList.contains('pdf-fullscreen')")
        assert abs(preview.bounding_box()["width"] - resized_width) < 2
        button.click()
        page.wait_for_function("document.body.classList.contains('pdf-fullscreen')")
        page.keyboard.press("Escape")
        page.wait_for_function("!document.body.classList.contains('pdf-fullscreen')")
        assert not page.locator(".editor-pane").evaluate("element => element.inert")
        page.set_viewport_size({"width": 800, "height": 900})
        assert not resizer.is_visible()
        # Das Layout folgt der neuen Fensterbreite erst im naechsten Frame.
        page.wait_for_function("getComputedStyle(document.querySelector('#workspace')).gridTemplateColumns.split(' ').length === 1")
        assert page.locator(".editor-pane").bounding_box()["width"] > 750
        # Schmal liegt der Index in der Schublade: Oeffnen aendert das Spaltenraster nicht.
        page.locator("#workspaceNavigation").click()
        assert page.locator(".workspace-index").is_visible()
        assert page.locator("#workspace").evaluate("node => getComputedStyle(node).gridTemplateColumns.split(' ').length") == 1
        browser.close()


def test_desktop_link_opens_requested_document_instead_of_last(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    from urllib.parse import urlencode

    first = write_qmd(material_root / "unterricht" / "erstes.qmd")
    requested = write_qmd(material_root / "unterricht" / "Mathe & Üben.qmd", "---\ntitle: Gewählt\n---\n\n# Gewähltes Material\n")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.add_init_script(f'localStorage.setItem("material-ui:last-document", {json.dumps(first.relative_to(material_root).as_posix())})')
        page.goto(url + "/?" + urlencode({"path": requested.relative_to(material_root).as_posix()}), wait_until="networkidle")
        page.wait_for_function("window.materialEditor.getText().includes('# Gewähltes Material')")
        assert page.title() == "Gewählt – Material UI"
        assert page.locator("#documentSearch").input_value().startswith("Gewählt")
        page.evaluate("async path => { const app = await import('/static/app.js'); await app.selectDocument(path); }", first.relative_to(material_root).as_posix())
        assert page.title() == "Testmaterial – Material UI"
        assert "erstes.qmd" in page.url
        page.reload(wait_until="networkidle")
        assert "erstes.qmd" in page.locator("#documentSearch").input_value()
        browser.close()


@pytest.fixture()
def external_qmd_import(material_root, tmp_path, monkeypatch):
    from material_ui.qmd_imports import stage_import

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    source = write_qmd(tmp_path / "extern" / "Mathe & Üben.qmd", "---\ntitle: Importiert\n---\n\n# Externes Material\n")
    return source, stage_import(source)


def test_qmd_import_copies_only_after_confirmation(material_root, external_qmd_import):
    source, token = external_qmd_import
    client = material_app.create_app().test_client()
    details = client.get(f"/api/qmd-import/{token}")
    assert details.get_json() == {"name": source.name, "source": str(source)}
    assert not list(material_root.rglob("*.qmd"))
    target = "unterricht/importiert/neu.qmd"
    response = client.post(f"/api/qmd-import/{token}", json={"path": target})
    assert response.status_code == 200
    assert response.get_json()["path"] == target
    assert (material_root / target).read_bytes() == source.read_bytes()
    assert source.is_file()
    assert client.get(f"/api/qmd-import/{token}").status_code == 404


def test_qmd_import_preserves_existing_files_and_rejects_escape(material_root, external_qmd_import):
    source, token = external_qmd_import
    client = material_app.create_app().test_client()
    target = write_qmd(material_root / "existing.qmd", "Nicht überschreiben")
    response = client.post(f"/api/qmd-import/{token}", json={"path": "existing.qmd"})
    assert response.status_code == 409
    assert target.read_text() == "Nicht überschreiben"
    for invalid in ["../escape.qmd", ".intern/import.qmd", "test.txt"]:
        assert client.post(f"/api/qmd-import/{token}", json={"path": invalid}).status_code == 400
    assert source.is_file()
    assert client.get(f"/api/qmd-import/{token}").status_code == 200


def test_qmd_import_cancel_preserves_original(material_root, external_qmd_import):
    source, token = external_qmd_import
    client = material_app.create_app().test_client()
    assert client.delete(f"/api/qmd-import/{token}").status_code == 200
    assert client.get(f"/api/qmd-import/{token}").status_code == 404
    assert source.is_file()
    assert not list(material_root.rglob("*.qmd"))
    assert client.get("/api/qmd-import/not-a-token").status_code == 400


def test_qmd_import_dialog_confirms_destination(material_root, external_qmd_import):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    source, token = external_qmd_import
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url + "/?import=" + token, wait_until="networkidle")
        assert page.get_by_role("dialog", name="QMD importieren").is_visible()
        assert str(source) in page.locator("#qmdImportSource").inner_text()
        assert not list(material_root.rglob("*.qmd"))
        page.locator("#qmdImportTarget").fill("unterricht/importiert/gewählt.qmd")
        page.get_by_role("button", name="Importieren und öffnen").click()
        page.wait_for_function("window.materialEditor.getText().includes('# Externes Material')")
        assert "import=" not in page.url
        assert "path=" in page.url
        assert source.is_file()
        page.reload(wait_until="networkidle")
        assert page.get_by_role("dialog", name="QMD importieren").is_hidden()
        browser.close()


def test_folder_list_renames_and_deletes_files(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "eigene-materialien" / "blatt.qmd")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url + "/?path=unterricht/eigene-materialien/blatt.qmd", wait_until="networkidle")

        # Rename/Delete-Knoepfe sind per CSS nur bei echtem Hover auf der Zeile sichtbar
        # (@media (hover: hover) in app.css); Playwright muss das Sichtbarmachen hier
        # explizit ausloesen, bevor es den eigentlich verdeckten Knopf anklicken kann.
        page.locator('#folderEntries button[data-document="unterricht/eigene-materialien/blatt.qmd"]').hover()
        page.locator('#folderEntries button[data-rename="unterricht/eigene-materialien/blatt.qmd"]').click()
        rename_dialog = page.get_by_role("dialog", name="Datei umbenennen")
        assert rename_dialog.is_visible()
        page.locator("#fileActionName").fill("umbenannt.qmd")
        rename_dialog.get_by_role("button", name="Umbenennen").click()

        # state="attached" statt des Standards "visible": der Umbenennen-Knopf ist nur bei
        # Hover auf der Zeile sichtbar, hier reicht der Nachweis, dass der Eintrag im DOM steht.
        page.wait_for_selector('#folderEntries button[data-rename="unterricht/eigene-materialien/umbenannt.qmd"]', state="attached")
        assert (material_root / "unterricht" / "eigene-materialien" / "umbenannt.qmd").is_file()
        assert not (material_root / "unterricht" / "eigene-materialien" / "blatt.qmd").exists()
        page.wait_for_function(
            "new URL(window.location.href).searchParams.get('path') === 'unterricht/eigene-materialien/umbenannt.qmd'"
        )

        page.locator('#folderEntries button[data-document="unterricht/eigene-materialien/umbenannt.qmd"]').hover()
        page.locator('#folderEntries button[data-delete="unterricht/eigene-materialien/umbenannt.qmd"]').click()
        delete_dialog = page.get_by_role("dialog", name="Datei löschen")
        assert delete_dialog.is_visible()
        delete_dialog.get_by_role("button", name="Löschen", exact=True).click()

        page.wait_for_function("document.querySelector('#documentInfo').textContent.includes('Kein Dokument geöffnet.')")
        assert not (material_root / "unterricht" / "eigene-materialien" / "umbenannt.qmd").exists()
        browser.close()


def test_folder_materials_pair_solutions_and_keep_titles_readable(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    folder = material_root / "unterricht/mathematik/klasse-05/arithmetik"
    title = "AB: Multiplizieren – Zerlegen und Ergänzen mit ausführlichen Rechenwegen"
    for name, label in [
        ("ab_multiplizieren.qmd", title),
        ("ab_multiplizieren-loesung.qmd", "Lösungen: Multiplizieren"),
        ("ab_multiplizieren_loesung.qmd", "Musterlösung: Multiplizieren"),
        ("ab_einzeln-loesung.qmd", "Lösungen: Eigenständige Lösung"),
        ("slide.qmd", "Slides: Multiplizieren"),
    ]:
        write_qmd(folder / name, f"---\ntitle: '{label}'\n---\nText\n")
    (folder / "README.md").write_text("Hinweise", encoding="utf-8")
    (folder / "assets").mkdir()
    relative = folder.relative_to(material_root).as_posix()
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1300, "height": 800}, color_scheme="dark")
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:index-width", "400"); localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url + "/?path=" + relative + "/ab_multiplizieren.qmd", wait_until="networkidle")
        primary = page.locator(f'#folderEntries [data-document="{relative}/ab_multiplizieren.qmd"]')
        primary.wait_for()
        group = primary.locator("..").locator("..")
        assert group.locator(".folder-paired-solution").count() == 2
        assert group.locator(".folder-material-kind").inner_text() == "Arbeitsblatt"
        assert group.locator(".folder-material-title").inner_text() == title.removeprefix("AB: ")
        assert group.locator(".folder-material-title").evaluate("(el) => getComputedStyle(el).whiteSpace") == "normal"
        assert page.locator("#folderEntries .folder-material-group").count() == 3
        assert page.locator(f'#folderEntries summary[data-folder="{relative}/assets"]').is_visible()
        assert page.locator(f'#folderEntries [data-document="{relative}/README.md"]').is_visible()
        solution = group.locator(f'.folder-paired-solution [data-document="{relative}/ab_multiplizieren-loesung.qmd"]')
        solution.hover()
        assert solution.locator("..").locator("[data-rename]").is_visible()
        # Loesungen und Notizen haengen am Arbeitsblatt und werden nicht einzeln geloescht.
        assert solution.locator("..").locator("[data-delete]").count() == 0
        assert page.locator("#folderEntries").evaluate("(el) => el.scrollWidth <= el.clientWidth")
        solution.click()
        page.wait_for_function("new URL(location.href).searchParams.get('path').endsWith('ab_multiplizieren-loesung.qmd')")
        assert solution.get_attribute("aria-current") == "true"
        assert primary.get_attribute("aria-current") == "false"
        browser.close()


def test_folder_rows_keep_their_height_on_hover(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "mathe" / "5a" / "blatt.qmd")
    write_pdf(material_root / "unterricht" / "mathe" / "5a" / "alt.pdf")

    def row_heights(page):
        return page.evaluate(
            "() => [...document.querySelectorAll('#folderEntries li')].map((li) => li.getBoundingClientRect().height)"
        )

    def max_height_delta(heights, baseline):
        assert len(heights) == len(baseline), "Zeilenanzahl der Ordnerliste hat sich geaendert"
        return max(abs(height - base) for height, base in zip(heights, baseline))

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url + "/?path=unterricht/mathe/5a/blatt.qmd", wait_until="networkidle")
        page.wait_for_selector('#folderEntries button[data-document="unterricht/mathe/5a/blatt.qmd"]')
        baseline = row_heights(page)

        # Beim Hover muessen die Aktions-Buttons erscheinen, ohne dass eine Zeile
        # waechst -- sonst rutscht die Liste unter dem Zeiger weg (Regression: die
        # Buttons erbten sonst die globalen 36px-Tastgroessen der Icon-Buttons).
        page.locator('#folderEntries summary[data-folder="unterricht/mathe"]').hover()
        assert page.locator('#folderEntries summary[data-folder="unterricht/mathe"] button[data-rename-folder]').is_visible()
        folder_hover = row_heights(page)

        page.locator('#folderEntries button[data-document="unterricht/mathe/5a/blatt.qmd"]').hover()
        assert page.locator('#folderEntries button[data-rename="unterricht/mathe/5a/blatt.qmd"]').is_visible()
        file_hover = row_heights(page)

        page.locator('#folderEntries a[href*="alt.pdf"]').hover()
        assert page.locator('#folderEntries button[data-delete="unterricht/mathe/5a/alt.pdf"]').is_visible()
        link_hover = row_heights(page)

        for label, heights in (("Ordnerzeile", folder_hover), ("Dateizeile", file_hover), ("PDF-Zeile", link_hover)):
            delta = max_height_delta(heights, baseline)
            assert delta < 0.5, f"{label} wächst beim Hover um {delta:.2f}px"

        # Gegenprobe: Mit 36px-Tastgroessen (Stand vor dem Fix) wächst die Zeile
        # sichtbar, d. h. die Delta-Assertions oben schlagen bei einem Rueckfall an.
        page.add_style_tag(content=(
            ".index-list li.deck-entry > button.icon-button,"
            ".index-list summary > button.icon-button { min-height: 36px; padding: 4px; }"
        ))
        page.locator('#folderEntries summary[data-folder="unterricht/mathe"]').hover()
        legacy_delta = max_height_delta(row_heights(page), baseline)
        assert legacy_delta > 4, f"Gegenprobe: erwartetes Zeilenwachstum bei 36px-Buttons blieb aus ({legacy_delta:.2f}px)"
        browser.close()


def test_qmds_ignores_hidden_and_old_entries(material_root):
    write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "arbeitsblaetter" / "ab-test.qmd")
    write_qmd(material_root / "wissen" / "mathematik" / "notiz.qmd")
    write_qmd(material_root / ".cache" / "verborgen.qmd")
    write_qmd(material_root / "node_modules" / "paket" / "beispiel.qmd")
    write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "alte-version-old.qmd")

    app = material_app.create_app()
    app.config.update(TESTING=True)
    response = app.test_client().get("/api/qmds")

    assert response.status_code == 200
    data = response.get_json()
    entries = {entry["path"]: entry for entry in data["qmds"]}
    assert set(entries) == {
        "unterricht/mathematik/klasse-05/arbeitsblaetter/ab-test.qmd",
    }  # wissen/ ist eine eigene Pipeline und kommt nicht in den Materialindex
    assert entries["unterricht/mathematik/klasse-05/arbeitsblaetter/ab-test.qmd"]["kind"] == "Arbeitsblatt"
    assert entries["unterricht/mathematik/klasse-05/arbeitsblaetter/ab-test.qmd"]["grade"] == "klasse-05"


def test_qmds_reload_picks_up_external_changes(material_root, monkeypatch):
    write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd")
    monkeypatch.setattr(time, "time", lambda: 100.0)
    client = material_app.create_app().test_client()

    first = client.get("/api/qmds").get_json()
    write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "neu.qmd")
    assert client.get("/api/qmds").get_json()["qmds"] == first["qmds"]

    response = client.post("/api/qmds/reload")

    assert response.status_code == 200
    paths = {entry["path"] for entry in response.get_json()["qmds"]}
    assert "unterricht/mathematik/klasse-05/neu.qmd" in paths
    assert "unterricht/mathematik/klasse-05/blatt.qmd" in paths


def test_editor_host_fills_large_grid_row_and_scrolls_long_documents(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    body = "\n".join(f"Zeile {number}: viel QMD-Inhalt" for number in range(1, 260))
    write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-05" / "arbeitsblaetter" / "grosses-blatt.qmd",
        f"---\ntitle: Grosses Blatt\n---\n\n{body}\n",
    )
    app = material_app.create_app()
    app.config.update(TESTING=True)

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(".editor-host .cm-content")
        metrics = page.evaluate(
            """() => {
                const host = document.querySelector('.editor-host');
                const scroller = document.querySelector('.editor-host .cm-scroller');
                const shell = document.querySelector('.editor-shell');
                const pane = document.querySelector('.editor-pane');
                return {
                    lines: window.materialEditor.getText().split(String.fromCharCode(10)).length,
                    hostHeight: host.clientHeight,
                    shellHeight: shell.clientHeight,
                    paneHeight: pane.clientHeight,
                    scrollHeight: scroller.scrollHeight,
                    gridRows: getComputedStyle(pane).gridTemplateRows
                };
            }"""
        )
        browser.close()

    assert metrics["lines"] >= 260
    assert metrics["hostHeight"] > metrics["paneHeight"] * 0.65
    assert metrics["shellHeight"] == metrics["hostHeight"]
    assert metrics["scrollHeight"] > metrics["hostHeight"]
    rows = [float(value[:-2]) for value in metrics["gridRows"].split()]
    assert len(rows) == 6
    assert all(value < 150 for value in rows[:3]), rows
    assert rows[3] > max(rows[:3]), rows


@pytest.mark.parametrize(
    ("pdf_state", "auto_render", "should_render"),
    [("missing", True, True), ("stale", True, True), ("current", True, False), ("missing", False, False)],
)
def test_open_document_prepares_pdf_preview(material_root, pdf_state, auto_render, should_render):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    source = write_qmd(material_root / "unterricht" / "blatt.qmd")
    os.utime(source, (2000, 2000))
    if pdf_state != "missing":
        source.with_suffix(".pdf").write_bytes(b"%PDF body")
        pdf_time = 1000 if pdf_state == "stale" else 3000
        os.utime(source.with_suffix(".pdf"), (pdf_time, pdf_time))
    app = material_app.create_app()
    render_requests = []

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script(f'localStorage.setItem("material-ui:auto-render", "{str(auto_render).lower()}")')

        def render(route):
            render_requests.append(route.request.post_data_json)
            route.fulfill(json={"running": True})

        page.route("**/api/render", render)
        page.route("**/api/render/status", lambda route: route.fulfill(json={
            "current": "unterricht/blatt.qmd", "running": False, "ok": True,
            "message": "Render fertig.", "pdf": "unterricht/blatt.pdf",
        }))
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("window.materialEditor.getText().includes('title: Testmaterial')")
        if should_render:
            page.wait_for_function("document.querySelector('#renderStatus').textContent === 'Render fertig.'", timeout=5000)
            assert render_requests == [{"path": "unterricht/blatt.qmd"}]
            assert "/api/pdf?path=unterricht%2Fblatt.pdf" in page.locator("#pdfPreview").get_attribute("src")
            assert page.locator("#pdfEmptyState").is_hidden()
        else:
            page.wait_for_timeout(1600)
            assert render_requests == []
            if pdf_state == "missing":
                assert page.locator("#pdfEmptyState").is_visible()
                assert "Rendern" in page.locator("#pdfEmptyState").inner_text()
            else:
                assert "/api/pdf?path=unterricht%2Fblatt.pdf" in page.locator("#pdfPreview").get_attribute("src")
        browser.close()


@pytest.mark.parametrize("second_has_pdf", [False, True])
def test_sidebar_switches_pdf_preview_with_document(material_root, second_has_pdf):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    first = write_qmd(material_root / "unterricht" / "erstes.qmd")
    write_qmd(material_root / "unterricht" / "zweites.qmd", "# Zweites Dokument\n")
    pdf_dir = first.parent / "pdf"
    pdf_dir.mkdir()
    (pdf_dir / "erstes.pdf").write_bytes(b"%PDF first")
    if second_has_pdf:
        (pdf_dir / "zweites.pdf").write_bytes(b"%PDF second")

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url + "/?path=unterricht/erstes.qmd", wait_until="domcontentloaded")
        page.wait_for_function("document.querySelector('#pdfPreview').src.includes('erstes.pdf')")

        page.locator('#folderEntries button[data-document="unterricht/zweites.qmd"]').click()
        page.wait_for_function("window.materialEditor.getText().includes('# Zweites Dokument')")
        if second_has_pdf:
            assert "zweites.pdf" in page.locator("#pdfPreview").get_attribute("src")
            assert page.locator("#pdfEmptyState").is_hidden()
        else:
            assert page.locator("#pdfPreview").get_attribute("src") is None
            assert page.locator("#pdfEmptyState").is_visible()

        page.locator('#folderEntries button[data-document="unterricht/erstes.qmd"]').click()
        page.wait_for_function("document.querySelector('#pdfPreview').src.includes('erstes.pdf')")
        assert page.locator("#pdfEmptyState").is_hidden()
        browser.close()


def test_render_preview_handles_failure_and_ignores_other_documents(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    app = material_app.create_app()

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url, wait_until="networkidle")
        page.route("**/api/render/status", lambda route: route.fulfill(json={
            "current": "unterricht/blatt.qmd", "running": False, "ok": False,
            "message": "LaTeX Error: kaputt", "pdf": None,
        }))
        page.evaluate("async () => (await import('/static/app.js')).pollRender()")
        assert "LaTeX Error: kaputt" in page.locator("#pdfEmptyState").inner_text()
        page.route("**/api/render/status", lambda route: route.fulfill(json={
            "current": "unterricht/anderes.qmd", "running": False, "ok": True,
            "message": "Render fertig.", "pdf": "unterricht/anderes.pdf",
        }))
        page.evaluate("async () => (await import('/static/app.js')).pollRender()")
        assert page.locator("#pdfPreview").get_attribute("src") is None
        assert "LaTeX Error: kaputt" in page.locator("#pdfEmptyState").inner_text()
        page.route("**/api/render/status", lambda route: route.fulfill(json={
            "current": "unterricht/blatt.qmd", "running": False, "ok": True,
            "message": "Render fertig.", "pdf": "unterricht/blatt.pdf",
        }))
        page.evaluate("""async () => {
            const { pollRender, state } = await import("/static/app.js");
            const pending = pollRender();
            state.qmdPath = 'unterricht/anderes.qmd';
            await pending;
        }""")
        assert page.locator("#pdfPreview").get_attribute("src") is None
        assert "LaTeX Error: kaputt" in page.locator("#pdfEmptyState").inner_text()
        browser.close()


def test_editor_grid_css_pins_extension_shell_to_editor_row():
    css = host_css()

    assert "grid-template-rows: auto auto auto minmax(0, 1fr) auto auto;" in css
    assert ".editor-shell {\n  grid-row: 4;" in css
    assert ".editor-host {\n  position: absolute;\n  inset: 0;\n}" in css
    assert ".editor-host .cm-content {" in css
    assert ".qmd-token-command {" in css
    assert ".qmd-fold-placeholder {" in css
    assert ".cm-flash-line {" in css
    assert ".editor-status {\n  grid-row: 5;" in css
    assert ".render-panel {\n  position: absolute;" in css
    assert ".render-panel[hidden] {\n  display: none;\n}" in css


def test_button_css_and_markup_define_hover_and_save_feedback_states():
    base = Path(__file__).resolve().parents[1] / "material_ui"
    css = host_css()
    template = (base / "templates" / "index.html").read_text(encoding="utf-8")
    icons = (base / "static" / "icons.svg").read_text(encoding="utf-8")

    assert "--accent-hover:" in css
    assert "--danger-hover:" in css
    assert "button:where(:hover:not(:disabled))" in css
    assert ".toolbar button:hover:not(:disabled)" in css
    assert "button.danger:hover:not(:disabled)" in css
    assert ".save-feedback[hidden] {\n  display: none;\n}" in css
    assert ".save-feedback.ok {" in css
    assert ".save-feedback.error {" in css
    assert 'id="docSaveFeedback"' in template
    assert 'id="courseSaveFeedback"' in template
    assert 'id="success"' in icons
    assert 'id="warning"' in icons


def test_editor_template_loads_bundle_and_keeps_status_and_toggles():
    template = (Path(__file__).resolve().parents[1] / "material_ui" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )

    assert '<div id="editorHost" class="editor-host" aria-label="QMD-Editor"></div>' in template
    assert '<script src="{{ asset_url(\'editor.bundle.js\') }}"></script>' in template
    assert 'type="importmap"' in template
    assert 'id="editorStatus"' in template
    assert 'id="autoSave"' in template
    assert 'id="showJobs"' in template
    assert 'id="restartServer"' in template
    assert 'id="jobsModal"' in template
    assert 'id="recoveryDiff"' in template


def test_editor_javascript_keeps_extension_points_for_comfort_features():
    base = Path(__file__).resolve().parents[1] / "material_ui"
    adapter = (base / "static" / "editor.js").read_text(encoding="utf-8")
    bundle_source = (base.parent / "editor-app" / "src" / "main.js").read_text(encoding="utf-8")
    assert (base / "static" / "editor.bundle.js").is_file()

    assert "export function resolveSaveAction(kursMode)" in adapter
    assert "window.MaterialEditor.create(elements.editorHost" in adapter
    assert "window.materialEditor = { getText: getEditorText, setText: setEditorText }" in adapter
    assert "jumpToLine: (line) => requireEditor().jumpToLine(line)" in adapter
    assert "insertTemplate: (template) => requireEditor().insertTemplate(template)" in adapter
    assert "openSearch: () => requireEditor().openSearch()" in adapter
    assert "setReadOnly: (readOnly) => editor?.setReadOnly(readOnly)" in adapter

    assert "function isCommandLine(line)" in bundle_source
    assert "function foldableCommandBlock(lines, start)" in bundle_source
    assert "foldService.of(" in bundle_source
    assert "codeFolding({" in bundle_source
    assert "qmd-fold-placeholder" in bundle_source
    assert "autocompletion({ override: [bausteinCompletions(" in bundle_source
    assert 'search({ top: true })' in bundle_source
    assert "view.setState(EditorState.create({ doc: value, extensions: buildExtensions() }))" in bundle_source
    assert 'indentUnit.of("  ")' in bundle_source


def test_editor_renders_highlighting_status_and_tab_indent(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-05" / "arbeitsblaetter" / "editor.qmd",
        "---\ntitle: Editor\n---\n\n# Überschrift\n\n- Punkt\n\n\\includegraphics[width=4cm]{bild.png}\n#| label: fig-test\nText mit `code` und [Link](ziel).\n",
    )
    app = material_app.create_app()
    app.config.update(TESTING=True)

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(".editor-host .cm-content")
        metrics = page.evaluate(
            """() => ({
                spellcheck: document.querySelector('.editor-host .cm-content').getAttribute('spellcheck'),
                lang: document.querySelector('.editor-host .cm-content').getAttribute('lang'),
                markup: document.querySelector('.editor-host .cm-content').innerHTML,
                status: document.querySelector('#editorStatus').textContent
            })"""
        )
        page.locator(".editor-host .cm-content").click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Tab")
        indented = page.evaluate("window.materialEditor.getText()")
        browser.close()

    assert metrics["spellcheck"] == "true"
    assert metrics["lang"] == "de"
    for token in ["qmd-token-heading", "qmd-token-list", "qmd-token-inline", "qmd-token-link",
                  "qmd-token-command", "qmd-token-command-name", "qmd-token-command-argument"]:
        assert token in metrics["markup"], token
    assert "Zeilen" in metrics["status"] and "Wörter" in metrics["status"]
    assert "Strg+F sucht" in metrics["status"]
    assert indented.startswith("  ---\n  title:")


def test_editor_folds_command_blocks_with_placeholder_and_keeps_full_text(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    source = write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-05" / "arbeitsblaetter" / "folds.qmd",
        "---\ntitle: Folds\n---\n\n::: {.callout-note}\nText 1\nText 2\n:::\n\nEnde\n",
    )
    app = material_app.create_app()
    app.config.update(TESTING=True)

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(".qmd-fold-placeholder")
        placeholder = page.locator(".qmd-fold-placeholder")
        assert placeholder.inner_text() == "4 Zeilen eingeklappt: ::: {.callout-note}"
        assert placeholder.get_attribute("role") == "button"
        full_text = page.evaluate("window.materialEditor.getText()")
        assert "::: {.callout-note}\nText 1\nText 2\n:::" in full_text

        page.click(".qmd-fold-placeholder")
        page.wait_for_function("document.querySelectorAll('.qmd-fold-placeholder').length === 0")
        assert page.evaluate("window.materialEditor.getText()") == full_text

        page.locator(".cm-line").filter(has_text="::: {.callout-note}").first.dblclick()
        page.wait_for_selector(".qmd-fold-placeholder")

        page.click(".qmd-fold-placeholder")
        page.wait_for_function("document.querySelectorAll('.qmd-fold-placeholder').length === 0")
        page.click("#saveDoc")
        page.wait_for_function("document.querySelector('#renderStatus').textContent.includes('Gespeichert')")
        browser.close()

    assert "material-ui-fold" not in source.read_text(encoding="utf-8")
    assert "::: {.callout-note}\nText 1\nText 2\n:::" in source.read_text(encoding="utf-8")


def test_editor_undo_restores_typing_but_not_document_loads(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    first = write_qmd(material_root / "unterricht" / "erstes.qmd", "---\ntitle: Erstes\n---\n\n# Erstes\n")
    second = write_qmd(material_root / "unterricht" / "zweites.qmd", "---\ntitle: Zweites\n---\n\n# Zweites\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url + "/?path=unterricht/erstes.qmd", wait_until="networkidle")
        page.wait_for_function("window.materialEditor.getText().includes('# Erstes')")

        page.locator(".editor-host .cm-content").click()
        page.keyboard.type("Anhang")
        assert "Anhang" in page.evaluate("window.materialEditor.getText()")
        page.keyboard.press("Control+z")
        assert "Anhang" not in page.evaluate("window.materialEditor.getText()")

        page.evaluate("async path => { const app = await import('/static/app.js'); await app.selectDocument(path); }",
                     second.relative_to(material_root).as_posix())
        page.wait_for_function("window.materialEditor.getText().includes('# Zweites')")
        page.keyboard.press("Control+z")
        page.wait_for_function("window.materialEditor.getText().includes('# Zweites')")
        browser.close()


def test_jobs_endpoint_lists_recent_jobs_first(material_root):
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    jobs = material_app.current_runtime().jobs

    first = jobs.create("unterricht/blatt.qmd", "render")
    jobs.update(first, status="succeeded", running=False, ok=True)
    second = jobs.create("unterricht/blatt.qmd", "audit")
    jobs.update(second, status="failed", running=False, ok=False, message="Kaputt")

    response = client.get("/api/jobs")

    assert response.status_code == 200
    records = response.get_json()["jobs"]
    assert [record["job_id"] for record in records[:2]] == [second, first]
    assert records[0]["operation"] == "audit"
    assert records[0]["status"] == "failed"
    assert records[0]["message"] == "Kaputt"


def test_jobs_modal_lists_session_jobs(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    identifier = material_app.current_runtime().jobs.create("unterricht/blatt.qmd", "render")
    material_app.current_runtime().jobs.update(identifier, status="succeeded", running=False, ok=True)

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        page.click("#headerMenuToggle")
        page.click("#showJobs")
        page.wait_for_selector("#jobsModal.open")
        page.wait_for_function("document.querySelector('#jobsList').children.length > 0")
        assert "Rendern" in page.locator(".job-item").first.inner_text()
        assert "erfolgreich" in page.locator(".job-item").first.inner_text()
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('#jobsModal').classList.contains('open')")
        browser.close()


def test_autosave_toggle_controls_server_saves(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    source = write_qmd(material_root / "unterricht" / "blatt.qmd")
    app = material_app.create_app()
    app.config.update(TESTING=True)

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.add_init_script('localStorage.setItem("material-ui:auto-save", "false")')
        saves = []
        page.on("request", lambda request: saves.append(request) if request.method == "POST" and request.url.split("?")[0].endswith("/api/document") else None)
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("window.materialEditor.getText().includes('Testmaterial')")
        assert page.locator("#autoSave").is_checked() is False

        page.locator(".editor-host .cm-content").click()
        page.keyboard.type("Anhang")
        page.wait_for_timeout(1500)
        assert saves == []
        assert "Anhang" not in source.read_text(encoding="utf-8")

        page.locator("#headerMenuToggle").click()
        with page.expect_request(lambda request: request.method == "POST" and request.url.split("?")[0].endswith("/api/document")):
            page.locator("#autoSave").check()
        page.wait_for_function("document.querySelector('#renderStatus').textContent.includes('Gespeichert')")
        assert "Anhang" in source.read_text(encoding="utf-8")
        browser.close()


def test_fulltext_result_jumps_to_line_and_chips_follow_index_data(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    body = "\n".join(f"Zeile {number}" for number in range(1, 60))
    write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-05" / "arbeitsblaetter" / "sprung.qmd",
        f"---\ntitle: Sprungziel\n---\n\n{body}\n\nNadelheu\n",
    )
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    app = material_app.create_app()
    app.config.update(TESTING=True)

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url + "/?path=unterricht/blatt.qmd", wait_until="networkidle")

        chips = page.locator("#filterChips .chip").all_text_contents()
        assert "Alle Bereiche" in chips
        assert "Unterricht" in chips
        assert "mathematik" in chips
        assert "Arbeitsblätter" in chips
        assert "informatik" not in chips
        assert "Sachkunde" not in chips

        page.locator("#documentSearch").fill("Nadelheu")
        page.wait_for_selector("#documentResults .document-option")
        assert page.locator("#documentResults .document-option").first.get_attribute("data-line") == "65"
        page.locator("#documentResults .document-option").first.click()
        page.wait_for_function("window.materialEditor.getText().includes('Nadelheu')")
        page.wait_for_selector(".cm-flash-line")
        assert "Nadelheu" in page.locator(".cm-flash-line").inner_text()
        browser.close()


def test_qmd_entry_extracts_title_solution_kind_and_pdf_status(material_root):
    source = write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-09" / "foerder" / "termumformung-loesung.qmd",
        "---\ntitle: 'Terme sicher umformen'\n---\n\nText\n",
    )
    pdf = source.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF")

    entry = material_app.services().documents.qmd_entry(source)

    assert entry["title"] == "Terme sicher umformen"
    assert entry["solution"] is True
    assert entry["kind"] == "Lösung"
    assert entry["pdf"] == "unterricht/mathematik/klasse-09/foerder/termumformung-loesung.pdf"


def test_templates_endpoint_exposes_preview_metadata(material_root):
    skip_if_private_templates()
    from material_ui.documents import WORKSHEET_DESIGNS

    app = material_app.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().get("/api/templates")

    assert response.status_code == 200
    templates = response.get_json()["templates"]
    assert templates[0]["path"] == ""
    assert any(template["label"] == "Mathe-Test" and template["preview"] for template in templates)
    assert all("Typst" not in template["label"] and "LaTeX" not in template["label"] for template in templates)
    # Design-Anzahl aus dem Katalog ableiten: lokale Designs (template-designs.local.json)
    # mischen sich dazu, daher nie eine feste Zahl hartkodieren.
    assert len([template for template in templates if template.get("design")]) == len(WORKSHEET_DESIGNS)
    assert any(template["path"] == "src/quarto/templates/exam-template.typst" for template in templates)
    assert all(template["tags"] and all(isinstance(tag, str) and tag for tag in template["tags"]) for template in templates)
    assert next(template for template in templates if template["label"] == "Förderplan")["tags"] == ["Förderplan"]
    assert all(template["tags"] == ["Excalidraw-Folien"] for template in response.get_json()["slideTemplates"])


def test_template_design_selection_previews_and_switches_format(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    skip_if_private_templates()
    from material_ui.documents import TEMPLATE_DEFINITIONS, WORKSHEET_DESIGNS
    from material_core.metadata import read_metadata

    write_qmd(material_root / "blatt.qmd", "---\ntitle: Testmaterial\nformat: pdf\n---\n\n# Aufgaben\n")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("window.materialEditor.getText().includes('# Aufgaben')")
        page.locator("#changeTemplate").click()
        # Der Dialog oeffnet sofort; Auswahlfelder erst nach dem Laden lesen.
        page.wait_for_selector("#templateType:not([disabled])")
        assert page.locator("#templateSelect").is_disabled()
        assert page.locator("#applyTemplate").is_disabled()
        page.locator("#templateType").select_option("Klausur")
        klausur_labels = [t["label"] for t in TEMPLATE_DEFINITIONS if t.get("kind") == "Klausur"]
        assert page.locator("#templateSelect option").all_text_contents() == klausur_labels
        assert page.locator("#templatePreview .template-type-tag").inner_text() == "Klausur"
        page.locator("#templateType").select_option("Förderplan")
        assert page.locator("#templateSelect option").all_text_contents() == ["Förderplan"]
        page.locator("#templateType").select_option("Arbeitsblatt")
        labels = page.locator("#templateSelect option").all_text_contents()
        assert len(labels) == len([t for t in TEMPLATE_DEFINITIONS if t.get("kind") == "Arbeitsblatt"])
        assert all("LaTeX" not in label and "Typst" not in label for label in labels)
        for design in WORKSHEET_DESIGNS:
            page.locator("#templateType").select_option("Fördermaterial" if design["id"] == "foerdermaterial" else "Arbeitsblatt")
            page.locator("#templateSelect").select_option(f"src/quarto/templates/worksheet-{design['id']}.typst")
            # Motifs may contain nested SVGs; the worksheet itself has one canvas.
            assert page.locator("#templatePreview .template-layout-preview > svg").count() == 1
            assert page.locator("#templatePreview strong").inner_text() == design["label"]
        page.set_viewport_size({"width": 390, "height": 640})
        bounds = page.locator("#templateModal .modal-panel").bounding_box()
        assert bounds["x"] >= 0
        assert bounds["x"] + bounds["width"] <= 390
        assert page.locator("#templateModal .template-body").evaluate(
            "element => element.scrollWidth <= element.clientWidth"
        )
        page.locator("#applyTemplate").click()
        # Das zuletzt gewaehlte Design anwenden: mit lokalen Designs endet der
        # Katalog nicht mehr zwingend bei "anime".
        last_design_path = f"worksheet-{WORKSHEET_DESIGNS[-1]['id']}.typst"
        page.wait_for_function(f"window.materialEditor.getText().includes({last_design_path!r})")
        formats = read_metadata(editor_text(page))["format"]
        assert "typst" in formats
        assert "pdf" not in formats
        page.locator("#changeTemplate").click()
        # Der Dialog oeffnet sofort; Auswahlfelder erst nach dem Laden lesen.
        page.wait_for_selector("#templateType:not([disabled])")
        assert page.locator("#templateType").input_value() == "Arbeitsblatt"
        assert page.locator("#templateSelect").input_value().endswith(last_design_path)
        page.locator("#closeTemplateModalButton").click()
        page.locator("#newDoc").click()
        page.locator("#newKind").select_option("Förderplan")
        assert page.locator("#newTemplate option").all_text_contents() == ["Förderplan"]
        page.locator("#newKind").select_option("Klausur")
        assert page.locator("#newTemplate option").all_text_contents() == klausur_labels
        page.locator("#newKind").select_option("Planung")
        assert page.locator("#newTemplate").input_value() == ""
        assert "Standardausgabe" in page.locator("#newTemplate").inner_text()
        browser.close()


def test_unified_template_selection_and_creation(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    from material_core.metadata import read_metadata
    from playwright.sync_api import expect

    write_qmd(material_root / "blatt.qmd", "---\ntitle: Testmaterial\nformat: pdf\n---\n\n## Einstieg\n\nWas fällt dir auf?\n")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("window.materialEditor.getText().includes('Testmaterial')")
        expect(page.locator("#slidesPlay")).to_be_hidden()
        assert page.locator("#slidesDesign, #slidesRebuild, #templateTarget").count() == 0
        page.locator("#headerMenuToggle").click()
        expect(page.locator("#headerMenuPanel #autoSave")).to_be_visible()
        expect(page.locator("#headerMenuPanel #autoRender")).to_be_visible()
        page.locator("#headerMenuToggle").click()
        page.locator("#changeTemplate").click()
        # Der Dialog oeffnet sofort; Auswahlfelder erst nach dem Laden lesen.
        page.wait_for_selector("#templateType:not([disabled])")
        page.locator("#templateType").select_option("Excalidraw-Folien")
        page.locator("#templateSelect").select_option("src/quarto/templates/slide-retro.typst")
        page.locator("#applyTemplate").click()
        page.wait_for_function("window.materialEditor.getText().includes('deck-design: retro')")
        expect(page.locator("#slidesPlay")).to_be_visible()
        metadata = read_metadata(editor_text(page))
        assert metadata["format"]["typst"]["template"].endswith("slide-retro.typst")
        assert "material-output" not in metadata
        page.locator("#changeTemplate").click()
        # Der Dialog oeffnet sofort; Auswahlfelder erst nach dem Laden lesen.
        page.wait_for_selector("#templateType:not([disabled])")
        assert page.locator("#templateSelect").input_value() == "src/quarto/templates/slide-retro.typst"
        page.locator("#removeTemplate").click()
        expect(page.locator("#slidesPlay")).to_be_hidden()
        assert "deck-design" not in read_metadata(editor_text(page))
        browser.close()


@pytest.mark.parametrize("design", ["retro", "standard"])
def test_new_slide_template_uses_slide_filename_and_keeps_existing_sources(material_root, design):
    from material_core.metadata import read_metadata

    target = material_root / "unterricht"
    target.mkdir()
    client = material_app.create_app().test_client()
    filename = "slide-template.typst" if design == "standard" else f"slide-{design}.typst"
    data = {"folder": "unterricht", "kind": "Excalidraw-Folien", "title": "Neue Folien", "template": f"src/quarto/templates/{filename}"}
    response = client.post("/api/document/new", json=data)
    assert response.status_code == 200
    assert response.get_json()["path"] == "unterricht/slide.qmd"
    metadata = read_metadata(response.get_json()["text"])
    assert "material-output" not in metadata
    assert metadata.get("deck-design", "standard") == design
    assert metadata["format"]["typst"]["template"].endswith(filename)
    previous = (target / "slide.qmd").read_bytes()
    assert client.post("/api/document/new", json=data).status_code == 409
    assert (target / "slide.qmd").read_bytes() == previous


def test_new_document_endpoint_creates_qmd_with_template_and_skeleton(material_root):
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post(
        "/api/document/new",
        json={
            "subject": "Mathematik",
            "grade": "6",
            "topic": "Bruchrechnung",
            "title": "Brueche vergleichen",
            "kind": "Arbeitsblatt",
            "filename": "",
            "template": "src/quarto/templates/latex-template.tex",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["path"] == (
        "unterricht/mathematik/klasse-06/bruchrechnung/arbeitsblaetter/"
        "brueche-vergleichen/ab_brueche-vergleichen.qmd"
    )
    assert data["klasse"] == "klasse-06"
    assert data["thema"] == "bruchrechnung"
    source = material_root / data["path"]
    text = source.read_text(encoding="utf-8")
    assert 'title: "Brueche vergleichen"' in text
    assert "template: ../../../../../../src/quarto/templates/latex-template.tex" in text
    assert "::: aufgabe" in text
    assert "<!-- material-ui -->" in text
    assert any(entry["path"] == data["path"] for entry in data["qmds"])


def test_new_document_endpoint_refuses_existing_file(material_root):
    existing = write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-05" / "materialien" / "arbeitsblaetter" / "test" / "ab_test.qmd"
    )
    app = material_app.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().post(
        "/api/document/new",
        json={"subject": "mathematik", "grade": "05", "topic": "materialien", "title": "Test", "kind": "Arbeitsblatt"},
    )
    assert response.status_code == 409
    assert 'existiert bereits' in response.get_json()["error"]["message"]

    assert existing.read_text(encoding="utf-8").startswith("---")


def test_new_document_in_selected_folder(material_root):
    folder = material_root / "unterricht" / "eigene-materialien"
    folder.mkdir(parents=True)
    client = material_app.create_app().test_client()
    payload = {"folder": "unterricht/eigene-materialien", "title": "Neues Blatt"}
    response = client.post("/api/document/new", json=payload)
    assert response.status_code == 200
    assert response.get_json()["path"] == "unterricht/eigene-materialien/ab_neues-blatt.qmd"
    source = folder / "ab_neues-blatt.qmd"
    original = source.read_text(encoding="utf-8")
    assert client.post("/api/document/new", json=payload).status_code == 409
    assert source.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("folder", ["../ausserhalb", "fehlt", ".versteckt"])
def test_new_document_rejects_invalid_target_folder(material_root, folder):
    (material_root / ".versteckt").mkdir()
    response = material_app.create_app().test_client().post(
        "/api/document/new", json={"folder": folder, "title": "Neues Blatt"}
    )
    assert response.status_code == 400
    assert not list(material_root.rglob("*.qmd"))


@pytest.mark.parametrize("filename", ["ab_potenzen", "ab-potenzen", "potenzen"])
def test_new_worksheet_keeps_single_ab_prefix(material_root, filename):
    (material_root / "unterricht").mkdir()
    client = material_app.create_app().test_client()
    response = client.post(
        "/api/document/new",
        json={"folder": "unterricht", "title": "Potenzen", "kind": "Arbeitsblatt", "filename": filename},
    )
    assert response.status_code == 200
    assert response.get_json()["path"] == "unterricht/ab_potenzen.qmd"


def test_new_document_without_worksheet_kind_gets_no_ab_prefix(material_root):
    (material_root / "unterricht").mkdir()
    client = material_app.create_app().test_client()
    response = client.post(
        "/api/document/new",
        json={"folder": "unterricht", "title": "Klausur Potenzen", "kind": "Klausur"},
    )
    assert response.status_code == 200
    assert response.get_json()["path"] == "unterricht/klausur-potenzen.qmd"


@pytest.mark.parametrize("filename", ["feedbackbogen", "ab_feedbackbogen", "ab_mini_feedbackbogen"])
def test_new_worksheet_mini_flag_uses_ab_mini_prefix(material_root, filename):
    (material_root / "unterricht").mkdir()
    client = material_app.create_app().test_client()
    response = client.post(
        "/api/document/new",
        json={"folder": "unterricht", "title": "Feedbackbogen", "kind": "Arbeitsblatt", "filename": filename, "mini": True},
    )
    assert response.status_code == 200
    assert response.get_json()["path"] == "unterricht/ab_mini_feedbackbogen.qmd"


def test_new_slide_template_gets_number_prefix_for_numbered_material(material_root):
    (material_root / "unterricht").mkdir()
    client = material_app.create_app().test_client()
    data = {
        "folder": "unterricht",
        "kind": "Excalidraw-Folien",
        "title": "Neue Folien",
        "filename": "01-einstieg",
        "template": "src/quarto/templates/slide-template.typst",
    }
    response = client.post("/api/document/new", json=data)
    assert response.status_code == 200
    assert response.get_json()["path"] == "unterricht/01 slide.qmd"


def test_new_document_preview_matches_created_path_without_writing(material_root):
    (material_root / "unterricht").mkdir()
    client = material_app.create_app().test_client()
    params = {"folder": "unterricht", "title": "Potenzen", "kind": "Arbeitsblatt", "filename": "potenzen"}
    preview = client.get("/api/document/new-preview", query_string=params)
    assert preview.status_code == 200
    assert preview.get_json() == {"path": "unterricht/ab_potenzen.qmd", "exists": False}
    assert not list(material_root.rglob("*.qmd"))

    created = client.post("/api/document/new", json=params)
    assert created.status_code == 200
    assert created.get_json()["path"] == preview.get_json()["path"]

    preview_after = client.get("/api/document/new-preview", query_string=params)
    assert preview_after.get_json() == {"path": "unterricht/ab_potenzen.qmd", "exists": True}


def test_rename_file_moves_file_and_refreshes_index(material_root):
    source = write_qmd(material_root / "unterricht" / "eigene-materialien" / "altes-blatt.qmd")
    client = material_app.create_app().test_client()

    response = client.post(
        "/api/file/rename",
        json={"path": "unterricht/eigene-materialien/altes-blatt.qmd", "name": "neues-blatt.qmd"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["path"] == "unterricht/eigene-materialien/neues-blatt.qmd"
    assert not source.exists()
    assert (material_root / "unterricht" / "eigene-materialien" / "neues-blatt.qmd").read_text(encoding="utf-8").startswith("---")
    paths = {entry["path"] for entry in data["qmds"]}
    assert "unterricht/eigene-materialien/neues-blatt.qmd" in paths
    assert "unterricht/eigene-materialien/altes-blatt.qmd" not in paths


@pytest.mark.parametrize("name", ["../draussen.qmd", ".versteckt.qmd", "ordner/datei.qmd", ""])
def test_rename_file_rejects_invalid_names(material_root, name):
    source = write_qmd(material_root / "unterricht" / "eigene-materialien" / "blatt.qmd")
    response = material_app.create_app().test_client().post(
        "/api/file/rename", json={"path": "unterricht/eigene-materialien/blatt.qmd", "name": name}
    )
    assert response.status_code == 400
    assert source.is_file()


def test_rename_file_rejects_existing_target_and_missing_source(material_root):
    write_qmd(material_root / "unterricht" / "eigene-materialien" / "blatt.qmd")
    write_qmd(material_root / "unterricht" / "eigene-materialien" / "ziel.qmd")
    client = material_app.create_app().test_client()

    conflict = client.post(
        "/api/file/rename", json={"path": "unterricht/eigene-materialien/blatt.qmd", "name": "ziel.qmd"}
    )
    missing = client.post(
        "/api/file/rename", json={"path": "unterricht/eigene-materialien/fehlt.qmd", "name": "neu.qmd"}
    )

    assert conflict.status_code == 409
    assert missing.status_code == 404
    assert (material_root / "unterricht" / "eigene-materialien" / "blatt.qmd").is_file()
    assert (material_root / "unterricht" / "eigene-materialien" / "ziel.qmd").read_text(encoding="utf-8").startswith("---")


def test_delete_file_removes_file_and_refreshes_index(material_root):
    source = write_qmd(material_root / "unterricht" / "eigene-materialien" / "blatt.qmd")
    client = material_app.create_app().test_client()

    response = client.delete("/api/file?path=unterricht/eigene-materialien/blatt.qmd")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["qmds"] == []
    assert not source.exists()


@pytest.mark.parametrize("path", [".material-history/blatt/blatt.txt", "unterricht", "unterricht/fehlt.qmd"])
def test_delete_file_rejects_hidden_missing_and_directories(material_root, path):
    hidden = material_root / ".material-history" / "blatt"
    hidden.mkdir(parents=True)
    (hidden / "blatt.txt").write_text("alt", encoding="utf-8")
    (material_root / "unterricht").mkdir(parents=True)

    response = material_app.create_app().test_client().delete(f"/api/file?path={path}")

    # Versteckte Pfade sind eine ungueltige Eingabe (400), fehlende Dateien und Ordner nicht gefunden (404).
    assert response.status_code == (400 if path.startswith(".") else 404)
    assert (hidden / "blatt.txt").is_file()


@pytest.mark.parametrize(
    ("parts", "name", "kind"),
    [
        (["unterricht", "mathematik", "klausuren"], "probe.qmd", "Klausur"),
        (["unterricht", "mathematik", "nachprüfung"], "material.qmd", "Nachprüfung"),
        (["unterricht", "mathematik", "lernkarten"], "bruchrechnung.qmd", "Lernkarten"),
        (["unterricht", "mathematik"], "reihenplanung-terme.qmd", "Planung"),
        (["unterricht", "mathematik", "probe"], "test.qmd", "Probe"),
        (["unterricht", "mathematik"], "sonstiges.qmd", "Material"),
    ],
)
def test_infer_kind_covers_material_folders(parts, name, kind):
    assert DocumentService.infer_kind(parts, name) == kind


def test_document_endpoint_finds_configured_pdf_and_rejects_traversal(material_root):
    source = write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-06" / "klausuren" / "arbeit.qmd",
        "---\ntitle: Arbeit\noutput-file: anderes.pdf\n---\n\nText\n",
    )
    pdf = source.parent / "pdf" / "anderes.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF")

    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.get("/api/document", query_string={"path": "unterricht/mathematik/klasse-06/klausuren/arbeit.qmd"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["pdf"] == "unterricht/mathematik/klasse-06/klausuren/pdf/anderes.pdf"
    assert data["klasse"] == "klasse-06"
    assert data["thema"] == "klausuren"

    response = client.get("/api/document", query_string={"path": "../ausbruch.qmd"})
    assert response.status_code == 400
    assert 'ausserhalb' in response.get_json()["error"]["message"]


def test_check_endpoint_reports_stale_pdf_missing_image_and_bad_template(material_root):
    source = write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd",
        "---\ntitle: Blatt\nformat:\n  pdf:\n    template: fehlt.typ\n---\n\n![Bild](assets/fehlt.png)\n",
    )
    pdf = source.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF")
    source.write_text(source.read_text(encoding="utf-8") + "\nNachtrag\n", encoding="utf-8")
    os.utime(pdf, (1000, 1000))
    os.utime(source, (1010, 1010))

    app = material_app.create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post("/api/check", json={"path": "unterricht/mathematik/klasse-05/blatt.qmd"})

    assert response.status_code == 200
    titles = {issue["title"] for issue in response.get_json()["issues"]}
    assert "Einfügemarke fehlt" in titles
    assert "PDF ist veraltet" in titles
    assert "Template nicht gefunden" in titles
    assert "Bild fehlt" in titles


def test_save_invalidates_qmd_cache_and_keeps_path_inside_project(material_root):
    source = write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd", "alt")

    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/document", json={"path": "unterricht/mathematik/klasse-05/blatt.qmd", "text": "neu"})

    assert response.status_code == 200
    assert source.read_text(encoding="utf-8") == "neu"
    assert material_app.services().documents.cache.expires == 0.0


def test_source_and_pdf_endpoints_return_files_with_no_store(material_root):
    source = write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd", "Quelle")
    pdf = source.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF body")
    identifier = material_app.current_runtime().jobs.create("unterricht/mathematik/klasse-05/blatt.qmd", "render")
    material_app.services().render.latest_id = identifier
    material_app.current_runtime().jobs.update(identifier, pdf="unterricht/mathematik/klasse-05/blatt.pdf")

    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    source_response = client.get("/api/source", query_string={"path": "unterricht/mathematik/klasse-05/blatt.qmd"})
    pdf_response = client.get("/api/pdf")
    missing_response = client.get("/api/pdf", query_string={"path": "unterricht/mathematik/klasse-05/blatt.qmd"})

    assert source_response.status_code == 200
    assert source_response.text == "Quelle"
    assert source_response.headers["Cache-Control"] == "no-store"
    assert pdf_response.status_code == 200
    assert pdf_response.data == b"%PDF body"
    assert pdf_response.headers["Cache-Control"] == "no-store"
    assert missing_response.status_code == 404


def test_pdf_for_ignores_pdfs_belonging_to_other_documents(material_root):
    source = write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd")
    pdf_dir = source.parent / "pdf"
    pdf_dir.mkdir()
    only_pdf = pdf_dir / "anderer-name.pdf"
    only_pdf.write_bytes(b"%PDF")

    assert material_app.services().builds.find_pdf(source) is None

    (pdf_dir / "zweiter-name.pdf").write_bytes(b"%PDF")
    assert material_app.services().builds.find_pdf(source) is None


def test_import_writes_unique_assets_metadata_and_inserts_at_marker(material_root):
    source = write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "arbeitsblaetter" / "blatt.qmd")
    assets = source.parent / "assets"
    assets.mkdir()
    (assets / "aufgabe-original.png").write_bytes(b"exists")
    (assets / "aufgabe-clean.png").write_bytes(b"exists")
    (assets / "aufgabe.meta.yaml").write_text("exists", encoding="utf-8")

    app = material_app.create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post(
        "/api/import",
        json={
            "qmdPath": "unterricht/mathematik/klasse-05/arbeitsblaetter/blatt.qmd",
            "filename": "Aufgabe",
            "originalDataUrl": PNG_DATA_URL,
            "cleanDataUrl": PNG_DATA_URL,
            "alt": "Wert ] prüfen",
            "width": "70%",
            "source": "Buch",
            "page": "12",
            "kind": "aufgabe",
            "description": "Beschreibung",
            "klasse": "klasse-05",
            "thema": "arbeitsblaetter",
            "tags": "Bruchrechnung, kuerzen",
            "insert": True,
            "taskBlock": True,
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["assetPath"] == "unterricht/mathematik/klasse-05/arbeitsblaetter/assets/aufgabe-clean-2.png"
    assert data["metaPath"] == "unterricht/mathematik/klasse-05/arbeitsblaetter/assets/aufgabe.meta-2.yaml"
    assert "![Wert \\] prüfen](assets/aufgabe-clean-2.png){width=70%}" in data["markdown"]
    assert source.read_text(encoding="utf-8").count("<!-- material-ui -->") == 1
    assert "::: aufgabe" in source.read_text(encoding="utf-8")
    meta_text = (assets / "aufgabe.meta-2.yaml").read_text(encoding="utf-8")
    assert 'quelle: "Buch"' in meta_text
    assert 'klasse: "klasse-05"' in meta_text
    assert 'thema: "arbeitsblaetter"' in meta_text
    assert "tags:\n  - \"Bruchrechnung\"\n  - \"kuerzen\"" in meta_text


def test_import_without_insert_keeps_document_but_returns_markdown(material_root):
    source = write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd", "Ursprung\n")

    app = material_app.create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post(
        "/api/import",
        json={
            "qmdPath": "unterricht/mathematik/klasse-05/blatt.qmd",
            "filename": "Schaubild groß!",
            "originalDataUrl": PNG_DATA_URL,
            "cleanDataUrl": PNG_DATA_URL,
            "description": "Diagramm",
            "insert": False,
            "taskBlock": False,
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["assetPath"] == "unterricht/mathematik/klasse-05/assets/schaubild-gross-clean.png"
    assert data["markdown"] == "\n![Diagramm](assets/schaubild-gross-clean.png){width=80%}\n"
    assert data["document"] == "Ursprung\n"
    assert source.read_text(encoding="utf-8") == "Ursprung\n"


def test_import_rejects_missing_png_data_url(material_root):
    write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd")

    app = material_app.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().post(
        "/api/import",
        json={
            "qmdPath": "unterricht/mathematik/klasse-05/blatt.qmd",
            "filename": "bild",
            "originalDataUrl": "data:image/jpeg;base64,abc",
            "cleanDataUrl": PNG_DATA_URL,
        },
    )
    assert response.status_code == 400
    assert 'PNG-Daten fehlen' in response.get_json()["error"]["message"]


def test_image_markdown_meta_yaml_and_sanitizing_helpers():
    sanitized = sanitize_stem(" Äußerst lange Aufgabe?! " * 8)
    assert sanitized.startswith("aeusserst-lange-aufgabe")
    assert len(sanitized) == 80
    assert "ä" not in sanitized and " " not in sanitized and "?" not in sanitized
    assert yaml_string("  Wert mit Umlaut ä  ") == '"Wert mit Umlaut ä"'
    assert image_markdown({"width": " 55% ", "taskBlock": False}, "assets/a.png") == (
        "\n![Material](assets/a.png){width=55%}\n"
    )

    meta = meta_yaml(
        {"filename": "Größe 1", "source": "Buch", "page": "7", "edits": ["crop", "grau"]},
        "original.png",
        "clean.png",
    )

    assert 'id: "groesse-1"' in meta
    assert 'seite: "7"' in meta
    assert '  - "crop"' in meta
    assert '  - "grau"' in meta
    assert 'klasse: ""' in meta
    assert 'thema: ""' in meta
    assert "tags: []" in meta

    tagged_meta = meta_yaml(
        {"filename": "bild", "klasse": "klasse-10", "thema": "trigonometrie", "tags": "Winkel, winkel, "},
        "original.png",
        "clean.png",
    )
    assert 'klasse: "klasse-10"' in tagged_meta
    assert 'thema: "trigonometrie"' in tagged_meta
    assert "tags:\n  - \"Winkel\"\n  - \"winkel\"" in tagged_meta


def test_parse_tags_splits_trims_and_dedupes():
    assert parse_tags("Winkel, winkel,  , Grad ") == ["Winkel", "winkel", "Grad"]
    assert parse_tags(["a", " b ", "a", ""]) == ["a", "b"]
    assert parse_tags(None) == []


def test_parse_tags_normalizes_hierarchical_paths():
    assert parse_tags("/klausuren, klasse-10//klausuren, klasse-10 / trigonometrie / klausuren") == [
        "klausuren",
        "klasse-10/klausuren",
        "klasse-10/trigonometrie/klausuren",
    ]


def test_grade_and_topic_part_helpers():
    parts = ["unterricht", "mathematik", "klasse-10", "trigonometrie", "klausuren", "klausur-01.qmd"]
    assert DocumentService.grade_part(parts) == "klasse-10"
    assert DocumentService.topic_part(parts) == "trigonometrie"
    assert DocumentService.grade_part(["unterricht", "mathematik"]) == ""
    assert DocumentService.topic_part(["unterricht", "mathematik"]) == ""


def test_insert_at_marker_appends_when_marker_missing(material_root):
    with_newline = write_qmd(material_root / "a.qmd", "Anfang\n")
    without_newline = write_qmd(material_root / "b.qmd", "Anfang")

    material_app.current_runtime().documents.insert(with_newline, "\n![Bild](a.png)\n")
    material_app.current_runtime().documents.insert(without_newline, "\n![Bild](b.png)\n")

    assert with_newline.read_text(encoding="utf-8") == "Anfang\n![Bild](a.png)\n"
    assert without_newline.read_text(encoding="utf-8") == "Anfang\n![Bild](b.png)\n"


def test_relocate_build_artifacts_moves_outputs_to_build_and_pdf(material_root):
    source = write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd",
        "---\noutput-file: custom.pdf\n---\n",
    )
    (source.parent / "custom.pdf").write_bytes(b"%PDF")
    (source.parent / "custom.log").write_text("log", encoding="utf-8")
    files_dir = source.parent / "custom_files"
    files_dir.mkdir()
    (files_dir / "asset.txt").write_text("asset", encoding="utf-8")

    material_app.services().builds.relocate_build_artifacts([source])

    build = material_root / "build"
    rel = Path("unterricht") / "mathematik" / "klasse-05"
    assert not (source.parent / "custom.pdf").exists()
    assert (build / "pdf" / rel / "custom.pdf").read_bytes() == b"%PDF"
    assert (build / "artefakte" / rel / "custom.log").read_text(encoding="utf-8") == "log"
    assert (build / "artefakte" / rel / "custom_files" / "asset.txt").read_text(encoding="utf-8") == "asset"
    assert source.exists()


def test_render_error_summary_and_detail_keep_full_log():
    output = "\n".join(f"line {number}" for number in range(90))
    output += "\nWARN vorher\nError: erste Meldung\nTypst: letzte Meldung\n"

    assert render_error_summary(output) == "Error: erste Meldung"
    detail = render_detail("blatt.qmd", "failed", output, 1, ["quarto", "render", "blatt.qmd"])

    assert detail["command"] == "quarto render blatt.qmd"
    assert detail["returncode"] == 1
    assert detail["log"].splitlines()[0] == "line 0"
    assert detail["log"].splitlines()[-1] == "Typst: letzte Meldung"
    assert render_error_summary("") == "Render fehlgeschlagen."


@pytest.mark.parametrize("heading", ["ERROR:", "Error:", "Fehler:", "\x1b[91mERROR:\x1b[39m"])
def test_render_error_summary_skips_generic_heading(heading):
    error = "Package pdfpages Error: Cannot find file `assets/original.pdf'."
    output = f"pandoc\nRendering PDF\n{heading}\ncompilation failed- error\n{error}\nWARN: Error encountered when rendering files\n"

    assert render_error_summary(output) == error
    assert render_error_summary(heading) == "Render fehlgeschlagen."


def test_render_detail_removes_terminal_colors_and_links():
    output = "\x1b[1mpandoc\x1b[22m\n\x1b[91mERROR:\x1b[39m\nFile missing\n\x1b]8;;https://example.org\x1b\\Details\x1b]8;;\x1b\\"
    detail = render_detail("blatt.qmd", "failed", output)
    assert detail["log"] == "pandoc\nERROR:\nFile missing\nDetails"


def test_render_log_can_be_reopened_after_failure_and_success(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    write_qmd(material_root / "unterricht" / "anderes.qmd")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url + "/?path=unterricht/blatt.qmd", wait_until="networkidle")
        for success in (False, True):
            payload = {
                "current": "unterricht/blatt.qmd", "running": False, "ok": success,
                "message": "Render fertig." if success else "Bild fehlt", "pdf": None,
                "detail": {"source": "unterricht/blatt.qmd", "command": "quarto render unterricht/blatt.qmd",
                           "status": "ok" if success else "failed", "returncode": 0 if success else 1,
                           "log": "Vollständige Render-Ausgabe"},
            }
            page.route("**/api/render/status", lambda route: route.fulfill(json=payload))
            page.evaluate("async () => (await import('/static/app.js')).pollRender()")
            if not success:
                page.locator("#closeRenderPanel").click()
                page.locator("#pdfEmptyState button").click()
                assert page.locator("#renderPanel").is_visible()
            for selector in ("#renderStatus", "#showRenderPanel"):
                if page.locator("#renderPanel").is_visible():
                    page.locator("#closeRenderPanel").click()
                if selector == "#showRenderPanel":
                    page.locator(".document-settings > summary").click()
                page.locator(selector).click()
                assert page.locator("#renderPanel").is_visible()
                assert page.locator("#renderLog").inner_text() == payload["detail"]["log"]
        page.evaluate("async () => (await import('/static/app.js')).loadDocument('unterricht/anderes.qmd')")
        assert page.locator("#showRenderPanel").is_disabled()
        assert page.locator("#renderPanel").is_hidden()
        browser.close()


def test_render_queue_moves_duplicate_to_the_end(material_root, monkeypatch):
    first = write_qmd(material_root / "unterricht" / "erstes.qmd")
    second = write_qmd(material_root / "unterricht" / "zweites.qmd")
    service = material_app.services().render
    monkeypatch.setattr(service, "submit", lambda *args: None)
    service.start(first)
    service.start(first)
    service.start(second)
    service.start(first)
    assert service.state_payload()["queued"] == "unterricht/erstes.qmd"
    assert service.state_payload()["queue"] == ["unterricht/zweites.qmd", "unterricht/erstes.qmd"]


def test_finish_render_records_result_and_starts_next_queued_item(material_root, monkeypatch):
    pdf = material_root / "unterricht" / "fertig.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF")
    first = write_qmd(pdf.with_suffix(".qmd"))
    second = write_qmd(pdf.parent / "naechstes.qmd")
    service = material_app.services().render
    started = []
    monkeypatch.setattr(service, "submit", lambda target, args: started.append(args[0]))
    identifier = service.start(first)
    next_identifier = service.start(second)
    service.finish(True, "fertig", pdf, {"status": "ok"})
    result = material_app.current_runtime().jobs.get(identifier)
    assert result["running"] is False
    assert result["ok"] is True
    assert result["pdf"] == "unterricht/fertig.pdf"
    assert service.state_payload()["queue"] == []
    assert service.state_payload()["job_id"] == next_identifier
    assert service.state_payload()["running"] is True
    assert started == [first, second]

def test_qmd_entries_cached_reuses_entries_until_expired(material_root, monkeypatch):
    source = write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd")
    calls = []
    now = 100.0

    def fake_entry(path):
        calls.append(path)
        return {"path": path.name, "call": len(calls)}

    monkeypatch.setattr(time, "time", lambda: now)
    monkeypatch.setattr(material_app.services().documents, "qmd_entry", fake_entry)

    first = material_app.services().documents.qmd_entries_cached()
    second = material_app.services().documents.qmd_entries_cached()
    now = 200.0
    third = material_app.services().documents.qmd_entries_cached()

    assert first == [{"path": source.name, "call": 1}]
    assert second == first
    assert third == [{"path": source.name, "call": 2}]
    assert calls == [source, source]


def test_qmd_cache_invalidation_forces_reload_before_ttl(material_root, monkeypatch):
    write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd")
    calls = 0

    def fake_entry(path):
        nonlocal calls
        calls += 1
        return {"path": path.name, "call": calls}

    monkeypatch.setattr(time, "time", lambda: 100.0)
    monkeypatch.setattr(material_app.services().documents, "qmd_entry", fake_entry)

    assert material_app.services().documents.qmd_entries_cached()[0]["call"] == 1
    material_app.services().documents.invalidate_qmd_cache()
    assert material_app.services().documents.qmd_entries_cached()[0]["call"] == 2


def test_multipart_import_writes_uploaded_images(material_root):
    source = write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd")
    metadata = {
        "qmdPath": "unterricht/mathematik/klasse-05/blatt.qmd",
        "filename": "Scan",
        "alt": "Scanbild",
        "insert": False,
    }

    app = material_app.create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post(
        "/api/import",
        data={
            "metadata": json.dumps(metadata),
            "original": (io.BytesIO(b"original-bytes"), "original.png"),
            "clean": (io.BytesIO(b"clean-bytes"), "clean.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assets = source.parent / "assets"
    assert (assets / "scan-original.png").read_bytes() == b"original-bytes"
    assert (assets / "scan-clean.png").read_bytes() == b"clean-bytes"
    assert response.get_json()["markdown"] == "\n::: aufgabe\n![Scanbild](assets/scan-clean.png){width=80%}\n:::\n"


def test_multipart_import_rejects_missing_clean_field(material_root):
    write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd")
    app = material_app.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().post(
        "/api/import",
        data={
            "metadata": json.dumps({"qmdPath": "unterricht/mathematik/klasse-05/blatt.qmd", "filename": "Scan"}),
            "original": (io.BytesIO(b"original-bytes"), "original.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert 'Bildfeld fehlt: clean' in response.get_json()["error"]["message"]


def test_multipart_import_rejects_oversized_upload(material_root, monkeypatch):
    write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd")
    monkeypatch.setattr(material_app, "MAX_UPLOAD_BYTES", 4)
    app = material_app.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().post(
        "/api/import",
        data={
            "metadata": json.dumps({"qmdPath": "unterricht/mathematik/klasse-05/blatt.qmd", "filename": "Scan"}),
            "original": (io.BytesIO(b"12345"), "original.png"),
            "clean": (io.BytesIO(b"1234"), "clean.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert 'zu groß' in response.get_json()["error"]["message"]


def test_document_issues_reports_clean_document(material_root):
    source = write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd",
        "---\ntitle: Blatt\n---\n\n![Bild](assets/bild.png)\n\n<!-- material-ui -->\n",
    )
    assets = source.parent / "assets"
    assets.mkdir()
    (assets / "bild.png").write_bytes(b"png")
    pdf = source.with_suffix(".pdf")
    write_pdf(pdf)
    os.utime(source, (1000, 1000))
    os.utime(pdf, (1010, 1010))

    assert material_app.services().documents.document_issues(source) == [
        {"level": "ok", "title": "Keine Auffälligkeiten", "detail": "Pfad, PDF, Bilder und Grundstruktur sehen gut aus."}
    ]


def test_render_worker_records_success_and_relocates_artifacts(material_root, monkeypatch):
    source = write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd")
    calls = []

    def fake_run(command, **kwargs):
        assert kwargs["env"]["MATERIAL_BUILD_MANAGED"] == "1"
        calls.append((command, kwargs["cwd"]))
        write_pdf(staged_pdf(command))
        return subprocess.CompletedProcess(command, 0, stdout="ok\n")

    monkeypatch.setattr(material_app.services().builds, "build_tikz_assets", lambda directory: calls.append(("tikz", directory)))
    monkeypatch.setattr(material_app.services().builds, "run_process", fake_run)

    material_app.services().render.worker(source)

    payload = material_app.services().render.state_payload()
    assert calls[0] == ("tikz", source.parent)
    assert calls[1][0][:2] == [material_app.QUARTO, "render"]
    assert Path(calls[1][0][2]).parent == source.parent
    assert Path(calls[1][0][2]).name.startswith("material-ui-render-")
    assert payload["ok"] is True
    assert payload["message"] == "Render fertig."
    assert payload["pdf"] == "build/pdf/unterricht/mathematik/klasse-05/blatt.pdf"
    assert payload["detail"]["status"] == "ok"
    assert (material_root / "build" / "pdf" / "unterricht" / "mathematik" / "klasse-05" / "blatt.pdf").exists()


def test_repeated_render_replaces_build_artifacts(material_root, monkeypatch):
    source = write_qmd(material_root / "unterricht" / "blatt.qmd")
    generation = 0

    def fake_run(command, **kwargs):
        nonlocal generation
        generation += 1
        for suffix in (".tex", ".log"):
            source.with_suffix(suffix).write_text(str(generation), encoding="utf-8")
        write_pdf(staged_pdf(command), str(generation))
        files_dir = source.parent / "blatt_files"
        files_dir.mkdir()
        (files_dir / f"generation-{generation}.txt").write_text(str(generation), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="ok\n")

    monkeypatch.setattr(material_app.services().builds, "build_tikz_assets", lambda directory: None)
    monkeypatch.setattr(material_app.services().builds, "run_process", fake_run)

    material_app.services().render.worker(source)
    material_app.services().render.worker(source)

    assert material_app.services().render.state_payload()["ok"] is True
    artifacts = material_root / "build" / "artefakte" / "unterricht"
    for suffix in (".tex", ".log"):
        assert not source.with_suffix(suffix).exists()
        assert (artifacts / f"blatt{suffix}").read_text(encoding="utf-8") == "2"
    with pymupdf.open(material_root / "build" / "pdf" / "unterricht" / "blatt.pdf") as document:
        assert document[0].get_text().strip() == "2"
    assert not (source.parent / "blatt_files").exists()
    assert not (artifacts / "blatt_files" / "generation-1.txt").exists()
    assert (artifacts / "blatt_files" / "generation-2.txt").exists()


def test_render_worker_records_failure_without_pdf(material_root, monkeypatch):
    source = write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd")

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 23, stdout="one\nLaTeX Error: kaputt\n")

    monkeypatch.setattr(material_app.services().builds, "build_tikz_assets", lambda _directory: None)
    monkeypatch.setattr(material_app.services().builds, "run_process", fake_run)

    material_app.services().render.worker(source)

    payload = material_app.services().render.state_payload()
    assert payload["ok"] is False
    assert payload["message"] == "LaTeX Error: kaputt"
    assert payload["pdf"] is None
    assert payload["detail"]["returncode"] == 23
    assert payload["detail"]["status"] == "failed"


def test_render_worker_records_unexpected_exception(material_root, monkeypatch):
    source = write_qmd(material_root / "unterricht" / "mathematik" / "klasse-05" / "blatt.qmd")

    def broken_build(_directory):
        raise RuntimeError("tikz kaputt")

    monkeypatch.setattr(material_app.services().builds, "build_tikz_assets", broken_build)

    material_app.services().render.worker(source)

    payload = material_app.services().render.state_payload()
    assert payload["ok"] is False
    assert payload["message"] == "RuntimeError: tikz kaputt"
    assert payload["detail"]["status"] == "failed"
    assert "RuntimeError: tikz kaputt" in payload["detail"]["log"]


def test_build_tikz_assets_builds_only_stale_visible_sources(material_root, monkeypatch):
    assets = material_root / "unterricht" / "mathematik" / "klasse-05" / "assets"
    assets.mkdir(parents=True)
    stale = assets / "diagramm.tex"
    stale.write_text("\\documentclass{standalone}", encoding="utf-8")
    up_to_date = assets / "aktuell.tex"
    up_to_date.write_text("\\documentclass{standalone}", encoding="utf-8")
    up_to_date_svg = up_to_date.with_suffix(".svg")
    up_to_date_svg.write_text("<svg/>", encoding="utf-8")
    lib = assets / "diagramm-lib.tex"
    lib.write_text("lib", encoding="utf-8")
    hidden = material_root / ".cache" / "assets" / "versteckt.tex"
    hidden.parent.mkdir(parents=True)
    hidden.write_text("hidden", encoding="utf-8")
    unrelated = material_root / "anderes-material" / "assets" / "kaputt.tex"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("invalid latex", encoding="utf-8")
    os.utime(up_to_date, (1000, 1000))
    os.utime(up_to_date_svg, (1010, 1010))
    calls = []

    def fake_run(command, cwd, **_kwargs):
        calls.append(command)
        if command[0] == "pdflatex":
            output_dir = Path(command[command.index("-output-directory") + 1])
            (output_dir / "diagramm.pdf").write_bytes(b"%PDF")
        else:
            Path(command[-1]).write_text("<svg>gebaut</svg>", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(material_app.services().builds, "run_process", fake_run)

    material_app.services().builds.build_tikz_assets(assets.parent)

    assert len(calls) == 2
    assert calls[0][0] == "pdflatex"
    assert calls[0][-1] == "diagramm.tex"
    assert calls[1][0] == "pdftocairo"
    assert stale.with_suffix(".svg").read_text(encoding="utf-8") == "<svg>gebaut</svg>"
    assert not lib.with_suffix(".svg").exists()
    assert not hidden.with_suffix(".svg").exists()
    assert not unrelated.with_suffix(".svg").exists()


def test_kurs_entry_appears_in_qmds_with_chapter_titles(material_root):
    write_kurs_index(
        material_root / "unterricht" / "kurse" / "demo-kurs",
        chapters=[("001-einstieg", "Einstieg"), ("002-schleifen", "Schleifen")],
    )

    app = material_app.create_app()
    app.config.update(TESTING=True)
    response = app.test_client().get("/api/qmds")

    assert response.status_code == 200
    entries = {entry["path"]: entry for entry in response.get_json()["qmds"]}
    kurs = entries["unterricht/kurse/demo-kurs"]
    assert kurs["kind"] == "Kurs (H5P)"
    assert kurs["slug"] == "demo-kurs"
    assert kurs["chapters"] == 2
    assert kurs["chapterList"] == [
        {"slug": "001-einstieg", "title": "Einstieg"},
        {"slug": "002-schleifen", "title": "Schleifen"},
    ]


def test_ensure_kurs_rejects_unknown_slug(material_root):
    app = material_app.create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post("/api/kurse/does-not-exist/audit")
    assert response.status_code == 400
    assert 'Unbekannter Kurs' in response.get_json()["error"]["message"]


def test_kurs_audit_runs_subprocess_and_reports_summary(material_root, monkeypatch):
    write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs", chapters=[("001-einstieg", "Einstieg")])
    calls = []

    def fake_run(command, *, cwd, text, stdout, stderr, timeout, check, env):
        calls.append(command)
        output = "Audit: errors=0, warnings=1, checks=12\n- warning: etwas fehlt\n"
        return subprocess.CompletedProcess(command, 0, stdout=output)

    monkeypatch.setattr(kurs_service(), "runner", fake_run)

    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    start_response = client.post("/api/kurse/demo-kurs/audit")
    assert start_response.status_code == 202

    status = None
    for _ in range(100):
        status = client.get("/api/kurse/demo-kurs/audit/status").get_json()
        if not status["running"]:
            break
        time.sleep(0.02)

    assert status is not None
    assert status["ok"] is True
    assert status["message"] == "0 Fehler, 1 Warnungen (12 Checks)."
    assert status["detail"]["log"].startswith("Audit: errors=0")
    assert calls and calls[0][-2:] == ["audit", "demo-kurs"]


def wait_for_moodle_job(client, slug):
    status = None
    for _ in range(100):
        status = client.get(f"/api/kurse/{slug}/moodle/status").get_json()
        if not status["running"]:
            break
        time.sleep(0.02)
    return status


def test_kurs_moodle_verify_runs_inv_task_with_target(material_root, monkeypatch):
    write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs", chapters=[("001-einstieg", "Einstieg")])
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="Verify: alles synchron\n")

    monkeypatch.setattr(kurs_service(), "runner", fake_run)

    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/kurse/demo-kurs/moodle/verify", json={"target": "staging"})
    assert response.status_code == 202

    status = wait_for_moodle_job(client, "demo-kurs")
    assert status["ok"] is True
    assert status["message"] == "Verify: alles synchron"
    assert len(calls) == 1
    assert calls[0][0] == "inv"
    assert "kurse.verify-moodle" in calls[0]
    assert "--course=demo-kurs" in calls[0]
    assert "--target=staging" in calls[0]


def test_kurs_moodle_upload_chapter_runs_inv_task_with_chapter(material_root, monkeypatch):
    write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs", chapters=[("001-einstieg", "Einstieg")])
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="Kapitel hochgeladen\n")

    monkeypatch.setattr(kurs_service(), "runner", fake_run)

    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/kurse/demo-kurs/moodle/upload-chapter", json={"chapter": "001-einstieg"})
    assert response.status_code == 202

    status = wait_for_moodle_job(client, "demo-kurs")
    assert status["ok"] is True
    assert len(calls) == 1
    assert calls[0][0] == "inv"
    assert "kurse.upload-chapter-moodle" in calls[0]
    assert "--course=demo-kurs" in calls[0]
    assert "--chapter=001-einstieg" in calls[0]


def test_kurs_moodle_upload_chapter_rejects_unknown_chapter(material_root):
    write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs", chapters=[("001-einstieg", "Einstieg")])
    app = material_app.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().post("/api/kurse/demo-kurs/moodle/upload-chapter", json={"chapter": "does-not-exist"})
    assert response.status_code == 400
    assert 'Unbekanntes Kapitel' in response.get_json()["error"]["message"]


def test_kurs_moodle_upload_course_runs_inv_task(material_root, monkeypatch):
    write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs", chapters=[("001-einstieg", "Einstieg")])
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="Kurs hochgeladen\n")

    monkeypatch.setattr(kurs_service(), "runner", fake_run)

    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/kurse/demo-kurs/moodle/upload-course", json={})
    assert response.status_code == 202

    status = wait_for_moodle_job(client, "demo-kurs")
    assert status["ok"] is True
    assert len(calls) == 1
    assert calls[0][0] == "inv"
    assert "kurse.upload-course-moodle" in calls[0]
    assert "--course=demo-kurs" in calls[0]


def test_kurs_moodle_publish_runs_inv_task_and_reports_failure(material_root, monkeypatch):
    write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs", chapters=[("001-einstieg", "Einstieg")])
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, stdout="Testsuite fehlgeschlagen\n")

    monkeypatch.setattr(kurs_service(), "runner", fake_run)

    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/kurse/demo-kurs/moodle/publish", json={})
    assert response.status_code == 202

    status = wait_for_moodle_job(client, "demo-kurs")
    assert status["ok"] is False
    assert status["message"] == "Fehlgeschlagen (Exit-Code 1)."
    assert len(calls) == 1
    assert calls[0][0] == "inv"
    assert "kurse.publish" in calls[0]
    assert "--course=demo-kurs" in calls[0]


def test_kurs_moodle_job_rejects_second_start_while_running(material_root, monkeypatch):
    write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs", chapters=[("001-einstieg", "Einstieg")])
    release = threading.Event()
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        release.wait(timeout=5)
        return subprocess.CompletedProcess(command, 0, stdout="fertig\n")

    monkeypatch.setattr(kurs_service(), "runner", fake_run)

    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    client.post("/api/kurse/demo-kurs/moodle/verify", json={})
    rejected = client.post("/api/kurse/demo-kurs/moodle/upload-course", json={})
    assert rejected.status_code == 409
    release.set()
    wait_for_moodle_job(client, "demo-kurs")

    assert len(calls) == 1


def test_moodle_upload_course_button_opens_confirm_modal_before_request(material_root, monkeypatch):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs", chapters=[("001-einstieg", "Einstieg")])
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok\n")

    monkeypatch.setattr(kurs_service(), "runner", fake_run)

    app = material_app.create_app()
    app.config.update(TESTING=True)

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("#kursPane:not([hidden])")
        page.locator(".advanced-options > summary").click()
        page.click("#moodleUploadCourseBtn")
        page.wait_for_selector("#moodleConfirmModal.open")
        confirm_text = page.text_content("#moodleConfirmText")
        page.click("#moodleConfirmCancelBtn")
        modal_open_after_cancel = page.eval_on_selector(
            "#moodleConfirmModal", "node => node.classList.contains('open')"
        )
        browser.close()

    assert "demo-kurs" in confirm_text
    assert modal_open_after_cancel is False
    assert calls == []


@pytest.mark.parametrize("open_from_folder", [False, True])
def test_course_index_opens_course_editor(material_root, open_from_folder, monkeypatch):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    course_dir = write_kurs_index(
        material_root / "unterricht" / "kurse" / "demo-kurs",
        title="Demokurs",
        chapters=[("001-einstieg", "Einstieg")],
    )
    chapter_path = course_dir / "chapters" / "001-einstieg.mdx"
    chapter_path.parent.mkdir()
    chapter_path.write_text('<PythonQuestion identifier="intro" title="Einführung" />\n', encoding="utf-8")
    preview_starts = []
    monkeypatch.setattr(kurs_preview(), "start", lambda slug: preview_starts.append(slug))

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        downloads = []
        page.on("download", lambda download: downloads.append(download))
        page.add_init_script("localStorage.setItem('material-ui:auto-render', 'false'); if (!localStorage.getItem('material-ui:active-view')) localStorage.setItem('material-ui:active-view', 'folder')")
        page.route("**/api/kurse/preview/status", lambda route: route.fulfill(json={"running": False}))
        path = "unterricht/blatt.qmd" if open_from_folder else "unterricht/kurse/demo-kurs/index.mdx"
        page.goto(f"{url}/?path={path}", wait_until="networkidle")
        if open_from_folder:
            page.locator("#navigationFolder").fill("unterricht/kurse")
            page.locator("#navigationFolder").press("Enter")
            page.locator("#navigationFolder").blur()
            page.wait_for_load_state("networkidle")
            page.locator('#folderEntries button[data-document="unterricht/kurse/demo-kurs"]').click()
        page.wait_for_selector("#kursPane:not([hidden])")
        assert page.locator("#kursTitle").text_content() == "Demokurs"
        assert page.locator("#pdfPreview").get_attribute("title") == "Kursvorschau"
        assert page.url == f"{url}/?path=unterricht%2Fkurse%2Fdemo-kurs"
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/demo-kurs/preview")) as preview_response:
            page.locator('#kursChapterList button[data-activity="intro"]').click()
        assert preview_response.value.status == 200
        assert preview_starts == ["demo-kurs"]
        page.wait_for_selector("#editorShell:not([hidden])")
        assert 'title="Einführung"' in page.evaluate("window.materialEditor.getText()")
        page.locator(".editor-host .cm-content").click()
        page.keyboard.press("Control+A")
        page.keyboard.type('<PythonQuestion identifier="intro" title="Bearbeitet" />\n')
        page.locator(".advanced-options > summary").click()
        with page.expect_response(lambda response: response.request.method == "POST" and "/activities/intro" in response.url):
            page.click("#saveCourseActivity")
        assert 'title="Bearbeitet"' in chapter_path.read_text(encoding="utf-8")
        page.wait_for_selector("#courseSaveFeedback.ok")
        assert page.locator("#courseSaveFeedback").inner_text().strip() == "Gespeichert"
        assert downloads == []
        browser.close()


def test_course_toolbar_shortcuts_and_ctrl_s(material_root, monkeypatch):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    course_dir = write_kurs_index(
        material_root / "unterricht" / "kurse" / "demo-kurs",
        title="Demokurs",
        chapters=[("001-einstieg", "Einstieg")],
    )
    chapter_path = course_dir / "chapters" / "001-einstieg.mdx"
    chapter_path.parent.mkdir()
    chapter_path.write_text('<PythonQuestion identifier="intro" title="Einführung" />\n', encoding="utf-8")
    monkeypatch.setattr(kurs_preview(), "start", lambda slug: None)

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script("localStorage.setItem('material-ui:auto-render', 'false'); if (!localStorage.getItem('material-ui:active-view')) localStorage.setItem('material-ui:active-view', 'folder')")
        page.route("**/api/kurse/preview/status", lambda route: route.fulfill(json={"running": False}))
        page.goto(f"{url}/?path=unterricht/kurse/demo-kurs/index.mdx", wait_until="networkidle")
        page.wait_for_selector("#courseToolbar:not([hidden])")
        assert page.locator("#toolbar").is_hidden()
        assert page.locator("#saveCourseActivity").is_disabled()
        shortcut_button = page.locator("#courseShortcutsHelp")
        idle_background = shortcut_button.evaluate("node => getComputedStyle(node).backgroundColor")
        shortcut_button.hover()
        assert shortcut_button.evaluate("node => getComputedStyle(node).backgroundColor") != idle_background
        assert page.locator("#saveCourseActivity").get_attribute("title") == "Aktivität speichern und Vorschau aktualisieren (Strg+S)"
        page.locator('#kursChapterList button[data-activity="intro"]').click()
        page.wait_for_selector("#editorShell:not([hidden])")
        assert page.locator("#saveCourseActivity").is_enabled()

        page.click("#courseShortcutsHelp")
        page.wait_for_selector("#shortcutsModal.open")
        assert page.locator("#shortcutsChips .chip").filter(has_text="Kurs (H5P)").count() == 1
        assert page.locator("#shortcutsChips .chip").filter(has_text="Klausur").count() == 0
        assert page.locator(".shortcut-card").filter(has_text="Warn-Box").count() == 1
        assert page.locator(".shortcut-card").filter(has_text="Editor: Startcode").count() == 1
        assert page.locator(".shortcut-card").filter(has_text="Rechenstrich").count() == 0
        page.keyboard.press("Escape")

        page.locator(".editor-host .cm-content").click()
        page.keyboard.press("Control+A")
        page.keyboard.type('<PythonQuestion identifier="intro" title="Bearbeitet" />\n')
        with page.expect_response(lambda response: response.request.method == "POST" and "/activities/intro" in response.url):
            page.keyboard.press("Control+s")
        assert 'title="Bearbeitet"' in chapter_path.read_text(encoding="utf-8")
        page.wait_for_selector("#courseSaveFeedback.ok")

        page.goto(f"{url}/?path=unterricht/blatt.qmd", wait_until="networkidle")
        page.click("#shortcutsHelp")
        page.wait_for_selector("#shortcutsModal.open")
        assert page.locator("#shortcutsChips .chip").filter(has_text="Kurs (H5P)").count() == 0
        assert page.locator(".shortcut-card").filter(has_text="Warn-Box").count() == 0
        assert page.locator(".shortcut-card").filter(has_text="Rechengitter").count() == 1
        folie_chip = page.locator("#shortcutsChips .chip").filter(has_text="Folie/Praesentation")
        assert folie_chip.count() == 1
        folie_chip.click()
        assert page.locator(".shortcut-card").filter(has_text="Vertikaler Abstand").count() == 1
        assert page.locator(".shortcut-card").filter(has_text="Zwei Spalten").count() == 1
        browser.close()


def test_shortcut_settings_preview_insert_and_reuse(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1000, "height": 800})
        page.add_init_script("localStorage.setItem('material-ui:auto-render', 'false'); if (!localStorage.getItem('material-ui:active-view')) localStorage.setItem('material-ui:active-view', 'folder')")
        page.goto(f"{url}/?path=unterricht/blatt.qmd", wait_until="networkidle")
        page.wait_for_selector(".editor-host .cm-content")
        before = page.evaluate("window.materialEditor.getText()")

        def configure(shortcut):
            page.click("#shortcutsHelp")
            page.locator(f'.shortcut-card[data-id="{shortcut}"]').click()
            return page.locator(".shortcut-settings")

        form = configure("skizze-dreieck")
        assert form.get_by_label("Dreiecksform", exact=True).input_value() == "recht-C"
        form.get_by_label("Dreiecksform", exact=True).select_option("gleichschenklig")
        form.get_by_label("Seite a", exact=True).fill("12 cm")
        form.get_by_label("Höhe auf AB einzeichnen", exact=True).select_option("ja")
        assert "form=gleichschenklig | a=12 cm | beta=14° | hoehe=ja" in form.locator("pre").inner_text()
        form.get_by_role("button", name="Abbrechen", exact=True).click()
        assert page.evaluate("window.materialEditor.getText()") == before
        page.keyboard.press("Escape")

        form = configure("skizze-dreieck")
        assert form.get_by_label("Seite a", exact=True).input_value() == "7 cm"
        form.get_by_label("Seite a", exact=True).fill("12 cm")
        expected = form.locator("pre").inner_text()
        form.get_by_role("button", name="Einfügen", exact=True).click()
        page.wait_for_function("text => window.materialEditor.getText().includes(text)", arg=expected)
        assert page.locator("#shortcutsModal").is_hidden()

        form = configure("skizze-dreieck")
        assert form.get_by_label("Seite a", exact=True).input_value() == "12 cm"
        form.get_by_role("button", name="Beispielwerte verwenden", exact=True).click()
        assert form.get_by_label("Seite a", exact=True).input_value() == "7 cm"
        form.get_by_role("button", name="Letzte Einstellungen verwenden", exact=True).click()
        assert form.get_by_label("Seite a", exact=True).input_value() == "12 cm"
        page.keyboard.press("Escape")

        form = configure("skizze-zahlenschloss")
        form.get_by_label("Anzahl der Räder", exact=True).fill("9")
        form.get_by_role("button", name="Einfügen", exact=True).click()
        assert page.locator("#shortcutsModal").is_visible()
        assert not form.get_by_label("Anzahl der Räder", exact=True).evaluate("node => node.checkValidity()")
        page.keyboard.press("Escape")

        form = configure("infobox")
        # User-entered template markers and HTML must survive literally.
        content = "Zeile 1\n{{Wert}} <img src=x onerror=alert(1)>"
        form.get_by_label("Text der Infobox", exact=True).fill(content)
        assert form.locator("pre img").count() == 0
        expected = form.locator("pre").inner_text()
        form.get_by_role("button", name="Einfügen", exact=True).click()
        page.wait_for_function("text => window.materialEditor.getText().includes(text)", arg=expected)
        assert content in page.evaluate("window.materialEditor.getText()")

        page.click("#shortcutsHelp")
        page.locator('.shortcut-card[data-id="seitenumbruch"]').click()
        page.wait_for_function("window.materialEditor.getText().includes('[Seitenumbruch]')")
        browser.close()


def test_shortcut_validation_completion_and_focus(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 700})
        page.add_init_script("localStorage.setItem('material-ui:auto-render', 'false'); if (!localStorage.getItem('material-ui:active-view')) localStorage.setItem('material-ui:active-view', 'folder')")
        page.add_init_script("localStorage.setItem('material-ui:shortcut:einheitskreis', JSON.stringify(['37']))")
        page.goto(f"{url}/?path=unterricht/blatt.qmd", wait_until="networkidle")
        page.wait_for_selector(".cm-content")

        def configure(shortcut):
            page.click("#shortcutsHelp")
            page.locator(f'.shortcut-card[data-id="{shortcut}"]').click()
            return page.locator(".shortcut-settings")

        form = configure("modell-rechenstrich")
        form.get_by_label("Zahlen am Rechenstrich", exact=True).fill("1,2,3,4")
        form.get_by_role("button", name="Einfügen", exact=True).click()
        assert "3 Sprünge benötigt" in form.locator(".shortcut-field-error").all_text_contents()[1]
        assert form.get_by_label("Sprünge", exact=True).get_attribute("aria-invalid") == "true"
        form.get_by_label("Sprünge", exact=True).fill("+1,+1,+1")
        form.get_by_role("button", name="Einfügen", exact=True).click()
        page.wait_for_selector("#shortcutsModal", state="hidden")
        page.wait_for_function("document.activeElement.matches('.cm-content')")

        form = configure("rechengitter")
        form.get_by_label("Kästchengröße in cm", exact=True).fill("Unsinn")
        form.get_by_role("button", name="Einfügen", exact=True).click()
        assert "positive Kästchengröße" in form.locator(".shortcut-field-error").all_text_contents()[0]
        page.keyboard.press("Escape")

        form = configure("schuelerfelder")
        form.get_by_label("Abstand nach oben", exact=True).fill("5mm")
        form.get_by_role("button", name="Einfügen", exact=True).click()
        assert "Abstand in cm" in form.locator(".shortcut-field-error").inner_text()
        form.get_by_label("Abstand nach oben", exact=True).fill("1,5cm")
        assert form.locator("pre").inner_text() == "[Schuelerfelder 1.5cm]"
        form.get_by_role("button", name="Einfügen", exact=True).click()
        page.wait_for_function("document.activeElement.matches('.cm-content')")
        assert "[Schuelerfelder 1.5cm]" in page.evaluate("window.materialEditor.getText()")

        page.keyboard.press("Control+A")
        page.keyboard.type("[einheitskreis")
        page.locator('.cm-tooltip-autocomplete [role="option"]').filter(has_text="Einheitskreis mit Winkel").click()
        form = page.locator(".shortcut-settings")
        assert form.get_by_label("Winkel in Grad", exact=True).input_value() == "37"
        form.get_by_label("Winkel in Grad", exact=True).fill("42")
        page.keyboard.press("Escape")
        assert page.evaluate("window.materialEditor.getText()") == "[einheitskreis]"
        # Reopen without changing the completion trigger's selected range.
        page.click("#shortcutsHelp")
        page.locator('.shortcut-card[data-id="einheitskreis"]').click()
        form.get_by_label("Winkel in Grad", exact=True).fill("42")
        form.get_by_role("button", name="Einfügen", exact=True).click()
        page.wait_for_function("window.materialEditor.getText() === '[Einheitskreis 42]'")
        page.wait_for_function("document.activeElement.matches('.cm-content')")
        browser.close()


def test_course_shortcut_multiline_yaml_and_active_due_date(material_root, monkeypatch):
    from ruamel.yaml import YAML

    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    course_dir = write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs",
                                  title="Demokurs", chapters=[("001-einstieg", "Einstieg")])
    chapter = course_dir / "chapters" / "001-einstieg.mdx"
    chapter.parent.mkdir()
    chapter.write_text('<PythonQuestion identifier="intro" title="Einführung" />\n', encoding="utf-8")
    monkeypatch.setattr(kurs_preview(), "start", lambda slug: None)
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script("localStorage.setItem('material-ui:auto-render', 'false'); if (!localStorage.getItem('material-ui:active-view')) localStorage.setItem('material-ui:active-view', 'folder')")
        page.route("**/api/kurse/preview/status", lambda route: route.fulfill(json={"running": False}))
        page.goto(f"{url}/?path=unterricht/kurse/demo-kurs/index.mdx", wait_until="networkidle")
        page.locator('#kursChapterList button[data-activity="intro"]').click()
        page.wait_for_selector("#editorShell:not([hidden])")

        def configure(shortcut):
            page.click("#courseShortcutsHelp")
            page.locator(f'.shortcut-card[data-id="{shortcut}"]').click()
            return page.locator(".shortcut-settings")

        code = "x = 1\nif x:\n    print(x)"
        for shortcut in ("kurs-code-beispiel", "kurs-code-noeditor", "kurs-editor-startcode"):
            form = configure(shortcut)
            assert form.get_by_label("Python-Code", exact=True).evaluate("node => node.tagName") == "TEXTAREA"
            form.get_by_label("Python-Code", exact=True).fill(code)
            expected = form.locator("pre").inner_text()
            assert code in expected
            form.get_by_role("button", name="Einfügen", exact=True).click()
            page.wait_for_function("text => window.materialEditor.getText().includes(text)", arg=expected)

        form = configure("kurs-editor-yaml")
        form.get_by_label("Dateiname", exact=True).fill("helper: #1.py")
        form.get_by_label("Code", exact=True).fill(code)
        form.get_by_label("Für Lernende sichtbar", exact=True).select_option("true")
        expected = form.locator("pre").inner_text()
        payload = YAML(typ="safe").load(expected.split("\n", 1)[1].rsplit("\n", 1)[0])
        source = payload["options"]["sourceFiles"][0]
        assert source["fileName"] == "helper: #1.py"
        assert source["code"].rstrip("\n") == code
        assert source["visibleToLearner"] is True
        assert source["learnerEditable"] is False
        form.get_by_role("button", name="Einfügen", exact=True).click()
        page.wait_for_function("text => window.materialEditor.getText().includes(text)", arg=expected)

        form = configure("kurs-grading")
        date = form.locator("#shortcut-field-1")
        assert date.is_disabled()
        form.get_by_label("Frist aktivieren", exact=True).select_option("true")
        assert date.is_enabled()
        date.fill("31.02.2027")
        form.get_by_role("button", name="Einfügen", exact=True).click()
        assert "gültiges Datum" in form.locator(".shortcut-field-error").all_text_contents()[1]
        date.fill("28.02.2027")
        expected = form.locator("pre").inner_text()
        payload = YAML(typ="safe").load(expected.split("\n", 1)[1].rsplit("\n", 1)[0])
        assert payload["dueDateGroup"] == {"enableDueDate": True, "duedate": "28.02.2027"}
        form.get_by_role("button", name="Einfügen", exact=True).click()
        page.wait_for_function("text => window.materialEditor.getText().includes(text)", arg=expected)
        browser.close()


def test_course_mode_reentry_after_leaving(material_root, monkeypatch):
    """Regression: Nach Verlassen des Kursmodus (Ansichtswechsel) muss ein erneutes
    Öffnen eines Kurses den Modus wieder aktivieren (enter() darf nicht an
    activeMode === mode hängen bleiben)."""
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    course_dir = write_kurs_index(
        material_root / "unterricht" / "kurse" / "demo-kurs",
        title="Demokurs",
        chapters=[("001-einstieg", "Einstieg")],
    )
    chapter_path = course_dir / "chapters" / "001-einstieg.mdx"
    chapter_path.parent.mkdir()
    chapter_path.write_text('<PythonQuestion identifier="intro" title="Einführung" />\n', encoding="utf-8")
    monkeypatch.setattr(kurs_preview(), "start", lambda slug: None)

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script("localStorage.setItem('material-ui:auto-render', 'false'); localStorage.setItem('material-ui:active-view', 'folder')")
        page.route("**/api/kurse/preview/status", lambda route: route.fulfill(json={"running": False}))
        page.goto(f"{url}/?path=unterricht/kurse/demo-kurs", wait_until="networkidle")
        page.wait_for_selector("#workspace.kurs-mode")
        # Kursmodus verlassen: anderes Dokument laden räumt den Modus ab
        page.goto(f"{url}/?path=unterricht/blatt.qmd", wait_until="networkidle")
        page.wait_for_selector("#workspace:not(.kurs-mode)")
        # Erneutes Öffnen des Kurses muss den Modus wieder aktivieren
        page.goto(f"{url}/?path=unterricht/kurse/demo-kurs", wait_until="networkidle")
        page.wait_for_selector("#workspace.kurs-mode", timeout=15000)
        assert page.locator("#kursTitle").text_content() == "Demokurs"
        browser.close()


def test_chapter_mdx_opens_course_view(material_root, monkeypatch):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    course_dir = write_kurs_index(
        material_root / "unterricht" / "kurse" / "demo-kurs",
        title="Demokurs",
        chapters=[("001-einstieg", "Einstieg")],
    )
    chapter_path = course_dir / "chapters" / "001-einstieg.mdx"
    chapter_path.parent.mkdir()
    chapter_path.write_text('<PythonQuestion identifier="intro" title="Einführung" />\n', encoding="utf-8")
    monkeypatch.setattr(kurs_preview(), "start", lambda slug: None)

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        downloads = []
        page.on("download", lambda download: downloads.append(download))
        page.add_init_script("localStorage.setItem('material-ui:auto-render', 'false'); if (!localStorage.getItem('material-ui:active-view')) localStorage.setItem('material-ui:active-view', 'folder')")
        page.route("**/api/kurse/preview/status", lambda route: route.fulfill(json={"running": False}))
        page.goto(f"{url}/?path=unterricht/kurse/demo-kurs/chapters/001-einstieg.mdx", wait_until="networkidle")
        page.wait_for_selector("#kursPane:not([hidden])")
        assert page.locator("#kursTitle").text_content() == "Demokurs"
        assert page.url == f"{url}/?path=unterricht%2Fkurse%2Fdemo-kurs"
        page.locator("#folderNavDetails > summary").click()
        page.locator("#navigationFolder").fill("unterricht/kurse")
        page.locator("#navigationFolder").press("Enter")
        page.locator("#navigationFolder").blur()
        page.wait_for_load_state("networkidle")
        page.locator('#folderEntries button[data-document="unterricht/kurse/demo-kurs"]').click()
        page.wait_for_selector("#kursPane:not([hidden])")
        assert page.locator("#kursTitle").text_content() == "Demokurs"
        assert downloads == []
        browser.close()


def test_course_mode_collapses_folder_navigation_and_prioritizes_chapters(material_root, monkeypatch):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    write_kurs_index(
        material_root / "unterricht" / "kurse" / "demo-kurs",
        title="Demokurs",
        chapters=[("001-einstieg", "Einstieg")],
    )
    monkeypatch.setattr(kurs_preview(), "start", lambda slug: None)

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script("localStorage.setItem('material-ui:auto-render', 'false'); if (!localStorage.getItem('material-ui:active-view')) localStorage.setItem('material-ui:active-view', 'folder')")
        page.route("**/api/kurse/preview/status", lambda route: route.fulfill(json={"running": False}))
        page.goto(f"{url}/?path=unterricht/kurse/demo-kurs/index.mdx", wait_until="networkidle")
        page.wait_for_selector("#kursPane:not([hidden])")
        assert page.eval_on_selector("#folderNavDetails", "node => node.open") is False
        assert page.eval_on_selector("#workspace", "node => node.classList.contains('kurs-mode')") is True
        kurs_pane_top = page.eval_on_selector("#kursPane", "node => node.getBoundingClientRect().top")
        folder_nav_top = page.eval_on_selector("#folderNavigation", "node => node.getBoundingClientRect().top")
        assert kurs_pane_top < folder_nav_top

        page.locator("#folderNavDetails > summary").click()
        assert page.eval_on_selector("#folderNavDetails", "node => node.open") is True
        page.locator("#navigationFolder").fill("unterricht")
        page.locator("#navigationFolder").press("Enter")
        page.locator("#navigationFolder").blur()
        page.wait_for_load_state("networkidle")
        page.locator('#folderEntries button[data-document="unterricht/blatt.qmd"]').click()
        page.wait_for_selector("#kursPane[hidden]", state="attached")
        assert page.eval_on_selector("#folderNavDetails", "node => node.open") is True
        assert page.eval_on_selector("#workspace", "node => node.classList.contains('kurs-mode')") is False
        browser.close()


@pytest.mark.parametrize("nested_chapters", [False, True])
def test_course_preview_starts_and_navigates_between_chapters(material_root, nested_chapters):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    from course_sync.main import render_course_page

    chapter_suffix = "/content" if nested_chapters else ""
    course_dir = write_kurs_index(
        material_root / "unterricht" / "kurse" / "demo-kurs",
        title="Demokurs",
        chapters=[(f"001-start{chapter_suffix}", "Einstieg"), (f"002-classes{chapter_suffix}", "Klassen & Objekte")],
    )
    chapters_dir = course_dir / "chapters"
    chapters_dir.mkdir()
    for slug, identifier in [("001-start", "start"), ("002-classes", "classes")]:
        chapter_path = chapters_dir / f"{slug}{chapter_suffix}.mdx"
        chapter_path.parent.mkdir(parents=True, exist_ok=True)
        chapter_path.write_text(
            f'<PythonQuestion identifier="{identifier}" title="{identifier}" />\n'
            f'### Test: {identifier}\n\n'
            f'<PythonQuestion identifier="{identifier}-test" title="Test: {identifier}" />\n',
            encoding="utf-8",
        )
    course_html = render_course_page(course_dir)
    starts = []
    status_requests = []

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        def start_preview(route):
            starts.append(route.request.url)
            route.fulfill(json={})

        def preview_status(route):
            status_requests.append(True)
            route.fulfill(json={
                "slug": "demo-kurs" if starts else None,
                "running": bool(starts),
                "ready": len(status_requests) > 2,
                "url": f"{url}/courses/demo-kurs",
            })

        page.route("**/api/kurse/demo-kurs/preview", start_preview)
        page.route("**/api/kurse/preview/status", preview_status)
        page.route("**/courses/demo-kurs", lambda route: route.fulfill(body=course_html, content_type="text/html"))
        page.route("**/preview/demo-kurs/**", lambda route: route.fulfill(body="Aktivität", content_type="text/html"))
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("#workspace.kurs-mode", timeout=15000)
        assert page.locator("#toolbar").is_hidden()
        assert page.locator("#editorShell").is_hidden()
        assert page.locator("#pdfPreview").get_attribute("title") == "Kursvorschau"
        assert "Kursvorschau" in page.locator("#pdfEmptyState").inner_text()
        assert "PDF" not in page.locator("#pdfEmptyState").inner_text()
        page.locator(".advanced-options > summary").click()
        page.click("#kursPreviewBtn")
        preview = page.frame_locator("#pdfPreview")
        preview.locator("#course-player-chapter").get_by_text("Einstieg", exact=True).wait_for()
        assert preview.locator("#course-player-title").inner_text() == "start"
        assert preview.locator(".course-chapter-button").count() == 2
        chapter = preview.locator(".course-chapter").filter(has_text="Klassen & Objekte")
        assert chapter.locator(".course-chapter-button").get_attribute("aria-expanded") == "false"
        chapter.locator(".course-chapter-button").click()
        assert chapter.locator(".course-chapter-button").get_attribute("aria-expanded") == "true"
        assert chapter.locator(".course-activity-button").all_text_contents() == ["classes", "Test: classes"]
        assert preview.locator("#course-player-title").inner_text() == "classes"
        chapter.locator(".course-chapter-button").click()
        assert chapter.locator(".course-subactivity-list").is_hidden()
        chapter.locator(".course-chapter-button").click()
        chapter.get_by_role("button", name="Test: classes", exact=True).click()
        assert preview.locator("#course-player-title").inner_text() == "Test: classes"
        assert page.locator("#pdfEmptyState").is_hidden()
        with page.expect_response(lambda response: response.request.method == "POST" and "/api/kurse/demo-kurs/preview" in response.url):
            page.click("#kursPreviewBtn")
        assert len(starts) == 2
        page.locator("#kursChapterList summary").filter(has_text="Klassen & Objekte").click()
        page.locator('#kursChapterList button[data-activity="classes"]').click()
        page.wait_for_function("!document.querySelector('#editorShell').hidden")
        assert page.locator(".editor-host .cm-content").get_attribute("aria-label") == "Aktivitätseditor"
        page.wait_for_function("document.querySelector('#pdfPreview').src.includes('/preview/demo-kurs/classes?')")
        source_text = page.evaluate("window.materialEditor.getText()")
        page.locator(".editor-host .cm-content").click()
        page.keyboard.press("Control+A")
        page.keyboard.type(source_text.replace('title="classes"', 'title="Neue Aktivität"'))
        with page.expect_response(lambda response: response.request.method == "POST" and "/activities/classes" in response.url):
            page.click("#saveCourseActivity")
        page.evaluate("async () => { const { state } = await import('/static/app.js'); await state.savePromise; }")
        saved_path = chapters_dir / f"002-classes{chapter_suffix}.mdx"
        assert 'title="Neue Aktivität"' in saved_path.read_text(encoding="utf-8")
        assert page.locator("#saveCourseActivity").locator("xpath=ancestor::section[contains(@class, 'editor-pane')]").count() == 1
        browser.close()


def test_course_index_and_activity_source_use_authored_content(material_root):
    course_dir = write_kurs_index(
        material_root / "unterricht" / "kurse" / "demo-kurs",
        chapters=[("001-start/content", "Einstieg")],
    )
    chapter = course_dir / "chapters" / "001-start" / "content.mdx"
    chapter.parent.mkdir(parents=True)
    chapter.write_text('<PythonQuestion identifier="intro" title="Objekte verwenden" />\n', encoding="utf-8")
    source = chapter.parent / "intro" / "content.mdx"
    source.parent.mkdir()
    source.write_text("---\ncontentType: text_only\n---\n\n# Objekte verwenden\n\nAlter Inhalt\n", encoding="utf-8")
    client = material_app.create_app().test_client()
    data = client.get("/api/kurse/demo-kurs/index").get_json()
    assert data["chapters"] == [{
        "slug": "001-start/content", "title": "Einstieg",
        "activities": [{"id": "intro", "title": "Objekte verwenden"}],
    }]
    activity_url = "/api/kurse/demo-kurs/activities/intro"
    data = client.get(activity_url).get_json()
    assert data["path"].endswith("/001-start/intro/content.mdx")
    assert data["text"] == source.read_text(encoding="utf-8")
    original_chapter = chapter.read_text(encoding="utf-8")
    edited = data["text"].replace("Alter Inhalt", "Neuer Inhalt")
    response = client.post(activity_url, json={"text": edited})
    assert response.status_code == 200
    assert source.read_text(encoding="utf-8") == edited
    assert chapter.read_text(encoding="utf-8") == original_chapter
    app = material_app.create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post("/api/kurse/demo-kurs/activities/unknown", json={"text": "kaputt"})
    assert response.status_code == 400
    assert 'Unbekannte Aktivität' in response.get_json()["error"]["message"]


def test_folder_lists_all_files_and_rejects_paths_outside_project(material_root):
    folder = material_root / "unterricht" / "trigonometrie"
    write_qmd(folder / "ab-01.qmd")
    (folder / "klausur.pdf").write_bytes(b"%PDF-1.4\n")
    (folder / "notizen.txt").write_text("Notizen", encoding="utf-8")
    (folder / "loesungen").mkdir()
    (folder / ".intern").write_text("intern", encoding="utf-8")
    outside = material_root.parent / "privat.txt"
    outside.write_text("privat", encoding="utf-8")
    (folder / "extern.txt").symlink_to(outside)
    client = material_app.create_app().test_client()

    response = client.get("/api/folder?path=unterricht/trigonometrie")
    assert response.status_code == 200
    entries = {entry["name"]: entry for entry in response.get_json()["entries"]}
    assert set(entries) == {"ab-01.qmd", "klausur.pdf", "notizen.txt", "loesungen"}
    assert entries["loesungen"]["directory"] is True
    assert entries["klausur.pdf"]["directory"] is False
    assert client.get("/api/folder?path=..").status_code == 400
    assert client.get("/api/folder?path=fehlt").status_code == 404
    response = client.get("/api/file?path=unterricht/trigonometrie/notizen.txt")
    assert response.data == b"Notizen"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert client.get("/api/file?path=unterricht/trigonometrie/extern.txt").status_code == 400
    assert client.get("/api/file?path=unterricht/trigonometrie/.intern").status_code == 404


def test_folder_root_listing_hides_wissen_but_subfolder_stays_reachable(material_root):
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    write_qmd(material_root / "wissen" / "mathematik" / "notiz.qmd")
    client = material_app.create_app().test_client()

    root_entries = {entry["name"] for entry in client.get("/api/folder?path=").get_json()["entries"]}
    assert "unterricht" in root_entries
    assert "wissen" not in root_entries

    nested_entries = {entry["name"] for entry in client.get("/api/folder?path=wissen").get_json()["entries"]}
    assert "mathematik" in nested_entries


def test_folder_index_navigates_all_files_without_document_headings(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    folder = material_root / "unterricht" / "mathematik" / "klasse-10" / "trigonometrie"
    first = write_qmd(folder / "ab-01.qmd", "---\ntitle: Erstes AB\n---\n\n# Einstieg\n\n" + "Text\n" * 80 + "\n## Vertiefung\n")
    second = write_qmd(folder / "ab-02.qmd", "---\ntitle: Zweites AB\n---\n\n# Sinussatz\n")
    (folder / "klausur.pdf").write_bytes(b"%PDF-1.4\n")
    (folder / "notizen.txt").write_text("Notizen", encoding="utf-8")
    write_qmd(folder / "loesungen" / "ab-01.qmd", "---\ntitle: Lösung\n---\n\n# Lösungen\n")

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.add_init_script(f'localStorage.setItem("material-ui:last-document", {json.dumps(first.relative_to(material_root).as_posix())})')
        page.goto(url, wait_until="networkidle")
        assert page.locator("#documentOutline").count() == 0
        assert page.locator("#navigationFolder").is_visible()
        assert page.locator("#folderEntries").get_by_role("link", name="klausur.pdf", exact=True).get_attribute("href").startswith("/api/pdf?path=")
        assert page.locator("#folderEntries").get_by_role("link", name="notizen.txt", exact=True).get_attribute("href").startswith("/api/file?path=")
        page.locator("#folderEntries").get_by_role("button", name="Arbeitsblatt: Zweites AB", exact=True).click()
        page.wait_for_function("window.materialEditor.getText().includes('# Sinussatz')")
        page.wait_for_selector("#folderEntries button[aria-current=true]")
        assert page.locator("#folderEntries button[aria-current=true] .folder-material-title").inner_text() == "Zweites AB"
        page.locator('#folderEntries summary[data-folder="unterricht/mathematik/klasse-10/trigonometrie/loesungen"]').click()
        page.locator('#folderEntries button[data-document$="/loesungen/ab-01.qmd"]').click()
        page.wait_for_function("window.materialEditor.getText().includes('# Lösungen')")
        page.locator("#navigationFolder").fill("unterricht/mathematik/klasse-10/trigonometrie")
        page.locator("#navigationFolder").press("Enter")
        page.locator("#folderEntries").get_by_role("button", name="Arbeitsblatt: Zweites AB", exact=True).wait_for(state="visible")
        page.locator("#navigationFolder").fill("10/trigonometrie")
        page.locator("#navigationFolder").press("Enter")
        page.wait_for_selector("#folderEntries button[data-document]")
        assert page.locator("#navigationFolder").input_value().endswith("klasse-10/trigonometrie")
        page.get_by_role("button", name="Index einklappen", exact=True).click()
        assert page.locator("#indexContent").is_hidden()
        page.reload(wait_until="networkidle")
        assert page.get_by_role("button", name="Index ausklappen", exact=True).get_attribute("aria-expanded") == "false"
        page.get_by_role("button", name="Index ausklappen", exact=True).click()
        assert page.locator("#toolbar").locator("xpath=ancestor::section[contains(@class, 'editor-pane')]").count() == 1
        assert page.locator(".app-brand strong").inner_text() == "Materialwerkstatt"
        assert page.locator("#showJobs").inner_text().strip() == "Aufträge"
        page.locator("#headerMenuToggle").click()
        for action in ("showJobs", "themeToggle"):
            assert page.locator(f"#{action}").bounding_box()["height"] <= 40
        page.locator("#headerMenuToggle").click()
        assert page.locator(".picker-row #newDoc").is_visible()
        for action in ("saveDoc", "addImage", "changeTemplate", "shortcutsHelp"):
            assert page.locator(f"#toolbar #{action}").is_visible()
        assert page.locator("#checkDoc").is_hidden()
        page.locator(".document-settings > summary").click()
        assert page.locator("#checkDoc").is_visible()
        page.locator(".document-settings > summary").click()
        page.locator("#navigationFolder").fill("unterricht/mathematik/klasse-10/trigonometrie")
        page.locator("#navigationFolder").press("Enter")
        page.locator("#folderEntries").get_by_role("button", name="Arbeitsblatt: Zweites AB", exact=True).wait_for(state="visible")
        page.locator("#newDocInFolder").click()
        assert page.locator("#newTargetFolder").input_value() == folder.relative_to(material_root).as_posix()
        page.locator("#newTitle").fill("Neues Blatt")
        from playwright.sync_api import expect

        expect(page.locator("#newDocStatus")).to_have_text(f"{folder.relative_to(material_root).as_posix()}/ab_neues-blatt.qmd")
        page.locator("#createNewDoc").click()
        page.wait_for_function("new URL(location.href).searchParams.get('path').endsWith('ab_neues-blatt.qmd')")
        assert (folder / "ab_neues-blatt.qmd").exists()
        page.locator("#newDoc").click()
        assert page.locator("#newTargetFolderField").is_hidden()
        assert not page.locator("#newKind option:last-child").is_disabled()
        page.locator("#cancelNewDoc").click()
        assert page.locator("#workspace").evaluate("node => getComputedStyle(node).gridTemplateColumns.split(' ').length") == 3
        browser.close()


def test_new_file_button_on_folder_row_opens_modal_without_scrolling_to_bottom_button(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    folder = material_root / "unterricht" / "mathematik" / "klasse-10" / "trigonometrie"
    write_qmd(folder / "ab-01.qmd", "---\ntitle: Erstes AB\n---\n\n# Einstieg\n")

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.add_init_script('localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url, wait_until="networkidle")
        page.locator("#navigationFolder").fill("unterricht/mathematik/klasse-10")
        page.locator("#navigationFolder").press("Enter")
        row = page.locator('summary[data-folder="unterricht/mathematik/klasse-10/trigonometrie"]')
        row.wait_for(state="visible")
        row.hover()
        row.locator('button[data-new-in-folder]').click()
        assert page.locator("#newDocModal").is_visible()
        assert page.locator("#newTargetFolder").input_value() == "unterricht/mathematik/klasse-10/trigonometrie"
        browser.close()


def test_course_preview_failure_shows_course_message_without_rendering_pdf(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs", chapters=[("001-start", "Einstieg")])
    render_requests = []

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("**/api/kurse/demo-kurs/preview", lambda route: route.fulfill(status=500, json={"error": {"code": "internal_error", "message": "Testfehler"}}))
        page.route("**/api/render", lambda route: (render_requests.append(route.request.url), route.fulfill(json={})))
        page.goto(url, wait_until="networkidle")
        page.evaluate("async () => { const app = await import('/static/app.js'); await app.renderDocument(); app.scheduleRender(); }")
        page.locator(".advanced-options > summary").click()
        page.click("#kursPreviewBtn")
        page.wait_for_function("document.querySelector('#pdfEmptyState').textContent.includes('Testfehler')")
        assert page.locator("#pdfEmptyState").inner_text() == "Kursvorschau fehlgeschlagen: Testfehler"
        assert page.locator("#kursPreviewStatus").inner_text() == "Kursvorschau fehlgeschlagen: Testfehler"
        assert page.locator("#pdfPreview").get_attribute("src") is None
        page.wait_for_timeout(1300)
        assert render_requests == []
        browser.close()


class _FakePreviewProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode


class _FakeManagedPreview:
    def __init__(self, returncode=None, output=""):
        self.process = _FakePreviewProcess(returncode)
        self.output = output

    def close(self):
        self.process.returncode = 0

    def tail(self):
        return self.output


def test_kurs_preview_start_switch_and_stop(material_root, monkeypatch):
    from material_ui.plugins.kurse import preview as preview_module

    write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs")
    write_kurs_index(material_root / "unterricht" / "kurse" / "anderer-kurs")
    spawned = []

    def fake_start(command, *, cwd, env, log_path):
        managed = _FakeManagedPreview()
        spawned.append((command, managed.process))
        return managed

    monkeypatch.setattr(material_app.current_runtime().processes, "start", fake_start)
    monkeypatch.setattr(preview_module, "port_ready", lambda port: True)
    app = material_app.create_app()
    client = app.test_client()
    first = client.post("/api/kurse/demo-kurs/preview").get_json()
    assert first["running"] is True
    assert first["ready"] is True
    assert first["url"] == f"http://127.0.0.1:{material_app.KURS_PREVIEW_PORT}/courses/demo-kurs"
    assert len(spawned) == 1
    assert spawned[0][0][1:3] == ["-m", "course_sync.scoped_preview"]
    assert "demo-kurs" in spawned[0][0]
    second = client.post("/api/kurse/anderer-kurs/preview").get_json()
    assert second["slug"] == "anderer-kurs"
    assert len(spawned) == 2
    assert spawned[0][1].returncode == 0
    stopped = client.post("/api/kurse/preview/stop").get_json()
    assert stopped["running"] is False
    assert spawned[1][1].returncode == 0


def test_kurs_preview_reports_log_tail_on_crash(material_root, monkeypatch):
    write_kurs_index(material_root / "unterricht" / "kurse" / "demo-kurs")
    monkeypatch.setattr(material_app.current_runtime().processes, "start",
                        lambda *args, **kwargs: _FakeManagedPreview(1, "Fehler: Port 8767 bereits belegt"))
    client = material_app.create_app().test_client()
    client.post("/api/kurse/demo-kurs/preview")
    status = client.get("/api/kurse/preview/status").get_json()
    assert status["running"] is False
    assert "Port 8767" in status["error"]

def test_create_kurs_builds_scaffold_and_appears_in_catalog(material_root):
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post(
        "/api/kurse/new",
        json={"slug": "mein-test-kurs", "title": "Mein Testkurs", "language": "de"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["kurs"]["slug"] == "mein-test-kurs"
    assert data["kurs"]["kind"] == "Kurs (H5P)"
    assert data["kurs"]["chapters"] == 1
    assert data["kurs"]["chapterList"] == [{"slug": "001-einstieg", "title": "Einstieg"}]

    # Build-Ausgaben liegen zentral unter build/kurse/<slug>/, nicht mehr im Kursordner.
    h5p_package = material_root / "build" / "kurse" / "mein-test-kurs" / "h5p" / "001-einstieg" / "hello-world.h5p"
    assert h5p_package.exists()

    catalog_paths = {entry["path"] for entry in data["qmds"]}
    assert "unterricht/kurse/mein-test-kurs" in catalog_paths


def test_create_kurs_rejects_duplicate_slug(material_root):
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    client.post("/api/kurse/new", json={"slug": "dup-kurs", "title": "Erster"})
    response = client.post("/api/kurse/new", json={"slug": "dup-kurs", "title": "Zweiter"})
    assert response.status_code == 409


def test_create_kurs_rejects_invalid_slug(material_root):
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/kurse/new", json={"slug": "ungueltig slug!"})
    assert response.status_code == 400


def test_create_kurs_rejects_empty_slug(material_root):
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/kurse/new", json={"slug": ""})
    assert response.status_code == 400


def test_qmd_entry_reads_tags_from_frontmatter(material_root):
    source = write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-05" / "arbeitsblaetter" / "einheitskreis.qmd",
        "---\ntitle: Einheitskreis\ntags: [einheitskreis, winkel]\n---\n\nText\n",
    )

    entry = material_app.services().documents.qmd_entry(source)

    assert entry["tags"] == ["einheitskreis", "winkel"]


def test_tags_endpoint_lists_vocabulary_with_counts(material_root):
    write_qmd(material_root / "unterricht" / "a.qmd", "---\ntitle: A\ntags: [mathe, klasse-10]\n---\n\nText A\n")
    write_qmd(material_root / "unterricht" / "b.qmd", "---\ntitle: B\ntags: [mathe]\n---\n\nText B\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.get("/api/tags")

    assert response.status_code == 200
    assert response.get_json()["tags"] == [
        {"tag": "mathe", "count": 2},
        {"tag": "klasse-10", "count": 1},
    ]


def test_search_filters_by_tags(material_root):
    write_qmd(material_root / "unterricht" / "a.qmd", "---\ntitle: A\ntags: [mathe, klasse-10]\n---\n\nText A\n")
    write_qmd(material_root / "unterricht" / "b.qmd", "---\ntitle: B\ntags: [mathe]\n---\n\nText B\n")
    (material_root / "unterricht" / "deck.excalidraw").write_text(
        json.dumps(
            {
                "type": "excalidraw",
                "version": 2,
                "elements": [{"type": "text", "id": "t1", "x": 0, "y": 0, "text": "Kreisdarstellung"}],
                "files": {},
            }
        ),
        encoding="utf-8"
    )
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    both = client.get("/api/search?tags=mathe").get_json()["results"]
    assert {result["path"] for result in both} == {"unterricht/a.qmd", "unterricht/b.qmd"}

    combined = client.get("/api/search?tags=mathe,klasse-10").get_json()["results"]
    assert [result["path"] for result in combined] == ["unterricht/a.qmd"]
    assert combined[0]["tags"] == ["mathe", "klasse-10"]

    decks = client.get("/api/search?q=kreisdarstellung").get_json()["results"]
    assert [result["path"] for result in decks] == ["unterricht/deck.excalidraw"]


def test_search_filters_by_tags_matches_hierarchical_descendants(material_root):
    write_qmd(material_root / "unterricht" / "a.qmd", "---\ntitle: A\ntags: [klasse-10/klausuren]\n---\n\nText A\n")
    write_qmd(
        material_root / "unterricht" / "b.qmd",
        "---\ntitle: B\ntags: [klasse-10/trigonometrie/klausuren]\n---\n\nText B\n",
    )
    write_qmd(material_root / "unterricht" / "c.qmd", "---\ntitle: C\ntags: [klausuren]\n---\n\nText C\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    scoped = client.get("/api/search?tags=klasse-10").get_json()["results"]
    assert {result["path"] for result in scoped} == {"unterricht/a.qmd", "unterricht/b.qmd"}

    exact_leaf = client.get("/api/search?tags=klausuren").get_json()["results"]
    assert [result["path"] for result in exact_leaf] == ["unterricht/c.qmd"]


def test_rename_tag_route_renames_scope_and_descendants_only(material_root):
    write_qmd(material_root / "unterricht" / "a.qmd", "---\ntitle: A\ntags: [klasse-10/klausuren]\n---\n\nText A\n")
    write_qmd(
        material_root / "unterricht" / "b.qmd",
        "---\ntitle: B\ntags: [klasse-10/klausuren/nachschreiber, mathe]\n---\n\nText B\n",
    )
    # Anderer Zweig (trigonometrie/klausuren) und anderes Top-Level-Tag (klausuren)
    # duerfen von der Umbenennung von klasse-10/klausuren nicht betroffen sein.
    write_qmd(
        material_root / "unterricht" / "c.qmd",
        "---\ntitle: C\ntags: [klasse-10/trigonometrie/klausuren]\n---\n\nText C\n",
    )
    write_qmd(material_root / "unterricht" / "d.qmd", "---\ntitle: D\ntags: [klausuren]\n---\n\nText D\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/tags/rename", json={"from": "klasse-10/klausuren", "to": "klasse-10/pruefungen"})

    assert response.status_code == 200
    data = response.get_json()
    assert set(data["changed"]) == {"unterricht/a.qmd", "unterricht/b.qmd"}
    entries = {entry["path"]: entry for entry in data["qmds"]}
    assert entries["unterricht/a.qmd"]["tags"] == ["klasse-10/pruefungen"]
    assert entries["unterricht/b.qmd"]["tags"] == ["klasse-10/pruefungen/nachschreiber", "mathe"]
    assert entries["unterricht/c.qmd"]["tags"] == ["klasse-10/trigonometrie/klausuren"]
    assert entries["unterricht/d.qmd"]["tags"] == ["klausuren"]


def test_set_tag_root_route_toggles_and_requires_boolean_root(material_root):
    write_qmd(material_root / "unterricht" / "a.qmd", "---\ntitle: A\ntags: [mathe]\n---\n\nText A\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/tags/root", json={"tag": "mathe", "root": True})
    assert response.status_code == 200
    assert response.get_json()["rootTags"] == ["mathe"]

    response = client.post("/api/tags/root", json={"tag": "mathe", "root": False})
    assert response.get_json()["rootTags"] == []

    assert client.post("/api/tags/root", json={"tag": "mathe"}).status_code == 400
    assert client.post("/api/tags/root", json={"tag": "mathe", "root": "true"}).status_code == 400


def test_set_tag_parent_route_assigns_clears_and_rejects_cycles(material_root):
    write_qmd(material_root / "unterricht" / "a.qmd", "---\ntitle: A\ntags: [klausuren]\n---\n\nText A\n")
    write_qmd(material_root / "unterricht" / "b.qmd", "---\ntitle: B\ntags: [klasse-10]\n---\n\nText B\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post("/api/tags/parent", json={"tag": "klausuren", "parent": "klasse-10"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["tagParents"] == {"klausuren": "klasse-10"}
    # Frontmatter bleibt unveraendert: beide Tags stehen weiter flach in den Dokumenten.
    entries = {entry["path"]: entry for entry in data["qmds"]}
    assert entries["unterricht/a.qmd"]["tags"] == ["klausuren"]
    assert entries["unterricht/b.qmd"]["tags"] == ["klasse-10"]

    assert client.post("/api/tags/parent", json={"tag": "klasse-10", "parent": "klausuren"}).status_code == 400
    assert client.post("/api/tags/parent", json={"tag": "klausuren", "parent": "klausuren"}).status_code == 400
    assert client.post("/api/tags/parent", json={"tag": "klausuren", "parent": 5}).status_code == 400

    response = client.post("/api/tags/parent", json={"tag": "klausuren", "parent": None})
    assert response.get_json()["tagParents"] == {}


def test_rename_tag_route_migrates_root_flag_and_tag_parent(material_root):
    write_qmd(material_root / "unterricht" / "a.qmd", "---\ntitle: A\ntags: [klausuren]\n---\n\nText A\n")
    write_qmd(material_root / "unterricht" / "b.qmd", "---\ntitle: B\ntags: [klasse-10]\n---\n\nText B\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    assert client.post("/api/tags/root", json={"tag": "klasse-10", "root": True}).status_code == 200
    assert client.post("/api/tags/parent", json={"tag": "klausuren", "parent": "klasse-10"}).status_code == 200

    response = client.post("/api/tags/rename", json={"from": "klausuren", "to": "pruefungen"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["tagParents"] == {"pruefungen": "klasse-10"}

    response = client.post("/api/tags/rename", json={"from": "klasse-10", "to": "klasse-zehn"})
    data = response.get_json()
    assert data["rootTags"] == ["klasse-zehn"]
    assert data["tagParents"] == {"pruefungen": "klasse-zehn"}


def test_metadata_route_writes_tag_lists(material_root):
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post(
        "/api/document/metadata",
        json={"text": "---\ntitle: C\n---\n\nText\n", "fields": {"tags": ["neu", "  leer  ", ""]}},
    )

    assert response.status_code == 200
    assert response.get_json()["metadata"]["tags"] == ["neu", "leer"]


def test_topic_navigation_promotes_topics_and_filters_categories(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    for name, subject, grade, topic, kind in [
        ("a", "mathematik", "klasse-05", "arithmetik", "Arbeitsblatt"),
        ("b", "mathematik", "klasse-05", "multiplikation", "Arbeitsblatt"),
        ("c", "informatik", "klasse-10", "algorithmen", "Fördermaterial"),
    ]:
        write_qmd(material_root / "unterricht" / f"{name}.qmd",
                  f"---\ntitle: Blatt {name}\nsubject: {subject}\ngrade: {grade}\nkind: {kind}\ntags: [{subject}, {grade}, {topic}, {kind}, '26/27']\n---\nText\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    for tag, parent in [("klasse-05", "mathematik"), ("arithmetik", "klasse-05"), ("multiplikation", "arithmetik")]:
        assert client.post("/api/tags/parent", json={"tag": tag, "parent": parent}).status_code == 200
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1300, "height": 700}, color_scheme="dark")
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")
        page.locator("#tagTreeViewButton").click()
        assert page.locator("#tagResults").is_hidden()
        assert page.locator("#tagEntries [data-tag]").count() == 0
        page.locator('#tagEntries [data-subject="mathematik"]').click()
        assert page.locator("#tagEntries [data-tag]").count() == 0
        assert page.locator("#tagResults").is_hidden()
        assert page.locator('#tagEntries [data-grade="klasse-05"]').is_visible()
        assert page.locator('#tagEntries [data-grade="klasse-10"]').count() == 0
        page.locator('#tagEntries [data-grade="klasse-05"]').click()
        assert page.locator("#tagResults").is_hidden()
        assert page.locator("#tagEntries [data-tag]").evaluate_all("(els) => els.map(el => el.dataset.tag)") == ["arithmetik"]
        assert page.locator("#tagEntries details").count() == 0
        page.locator('#tagEntries [data-tag="arithmetik"]').click()
        assert page.locator("#tagResults [data-document]").count() == 2
        assert page.locator('#tagEntries [data-tag="multiplikation"]').is_visible()
        assert page.locator('#tagBreadcrumbs [aria-current]').inner_text() == "arithmetik"
        assert page.locator('#tagBreadcrumbs [aria-current]').evaluate("(el) => el === document.activeElement")
        page.locator('#tagEntries [data-tag="multiplikation"]').click()
        assert page.locator("#tagResults [data-document]").count() == 1
        assert page.locator("#tagEntries [data-tag]").count() == 0
        page.locator("#tagBack").click()
        assert page.locator('#tagBreadcrumbs [aria-current]').inner_text() == "arithmetik"
        page.locator("#tagFilterDetails > summary").click()
        page.locator("#tagKindFilter").select_option("slides")
        assert page.locator("#tagResults [data-document]").count() == 0
        assert page.locator('#tagBreadcrumbs [aria-current]').inner_text() == "arithmetik"
        assert page.locator('#tagEntries [data-tag="multiplikation"]').is_visible()
        assert page.locator('#tagEntries [data-tag="multiplikation"] .tag-count').inner_text() == "0"
        page.locator("#tagBack").click()
        assert page.locator('#tagEntries [data-tag="arithmetik"]').is_visible()
        assert page.locator("#tagKindFilter").input_value() == "slides"
        page.locator("#tagBack").click()
        assert page.locator('#tagEntries [data-grade="klasse-05"]').is_visible()
        page.locator("#tagBack").click()
        assert page.locator('#tagEntries [data-subject="informatik"]').is_visible()
        page.locator('#tagEntries [data-subject="informatik"]').click()
        page.locator('#tagEntries [data-grade="klasse-10"]').click()
        assert page.locator("#tagKindFilter").input_value() == "slides"
        page.locator("#tagReset").click()
        assert page.locator('#tagBreadcrumbs [aria-current]').inner_text() == "Klasse 10"
        page.locator('#tagEntries [data-tag="algorithmen"]').click()
        page.locator("#tagKindFilter").select_option("kind:Fördermaterial")
        assert page.locator("#tagResults [data-document]").count() == 1
        page.locator('#tagActiveFilters [data-clear-filter="tagKindFilter"]').click()
        assert page.locator('#tagBreadcrumbs [aria-current]').inner_text() == "algorithmen"
        assert page.locator("#tagResults [data-document]").count() == 1
        for selector in ["#tagEntries", "#tagResults", "#tagNavigation"]:
            assert page.locator(selector).evaluate("(el) => !['auto', 'scroll'].includes(getComputedStyle(el).overflowY)")
            assert page.locator(selector).evaluate("(el) => el.scrollWidth <= el.clientWidth")
        assert page.locator("#tagLabelViewButton").count() == 0
        browser.close()


def test_tag_results_paginate_and_filter(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    for index in range(25):
        write_qmd(material_root / "unterricht" / f"ab_{index:02}.qmd",
                  f"---\ntitle: Blatt {index:02}\nsubject: mathematik\ngrade: klasse-05\ntags: [mathe, '26/27']\n---\n\nText\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1300, "height": 760})
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")
        page.locator("#tagTreeViewButton").click()
        page.locator('#tagEntries [data-subject="mathematik"]').click()
        page.locator('#tagEntries [data-grade="klasse-05"]').click()
        page.locator('#tagEntries [data-tag="mathe"]').click()
        page.wait_for_selector("#tagResults [data-document]")
        assert page.locator("#tagResults [data-document]").count() == 20
        assert page.locator("#tagPageStatus").inner_text() == "1–20 von 25"
        page.locator("#tagNext").click()
        assert page.locator("#tagResults [data-document]").count() == 5
        assert page.locator("#tagNext").is_disabled()
        from playwright.sync_api import expect

        page.locator("#documentSearch").fill("Blatt 03")
        # Die Tag-Suche ist gepuffert (TAG_SEARCH_DEBOUNCE_MS): auf das Ergebnis warten.
        expect(page.locator("#tagResults [data-document]")).to_have_count(1)
        page.locator("#tagFilterDetails > summary").click()
        page.locator("#tagKindFilter").select_option("slides")
        assert page.locator("#tagResults [data-document]").count() == 0
        page.locator("#tagReset").click()
        assert page.locator("#tagResults [data-document]").count() == 20
        page.locator("#tagYearFilter").select_option("26/27")
        assert page.locator("#tagResults [data-document]").count() == 20
        assert page.locator("#documentSearch").is_visible()
        assert page.locator("#tagEntries [data-document]").count() == 0
        browser.close()



def test_topic_selection_survives_rename(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    for index in range(3):
        write_qmd(material_root / "unterricht" / f"a{index}.qmd",
                  f"---\ntitle: Blatt {index}\nsubject: mathematik\ngrade: klasse-05\ntags: [arithmetik, mathe]\n---\nText\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")
        page.locator("#tagTreeViewButton").click()
        page.locator('#tagEntries [data-subject="mathematik"]').click()
        page.locator('#tagEntries [data-grade="klasse-05"]').click()
        tag = page.locator('#tagEntries button[data-tag="arithmetik"]')
        assert tag.locator(".tag-count").inner_text() == "3"
        tag.focus()
        tag.press("Enter")
        current = page.locator('#tagBreadcrumbs [aria-current]')
        assert current.evaluate("(el) => el === document.activeElement")
        assert page.locator("#tagResults [data-document]").count() == 3
        current.click(button="right")
        page.locator("#tagRenameSegment").fill("rechnen")
        page.locator("#applyTagRename").click()
        page.wait_for_selector("#tagRenameModal.open", state="hidden")
        assert page.locator("#tagResultsHeading").inner_text() == "rechnen · 3 Materialien"
        assert page.locator('#tagBreadcrumbs [aria-current]').inner_text() == "rechnen"
        assert page.locator("#tagResults [data-document]").count() == 3
        browser.close()


def test_contextual_tag_badges_filter_actual_documents(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    for index in range(23):
        extra = "grundlagen, " + ("partnerarbeit" if index < 2 else "einzelarbeit") if index < 20 else "vertiefung"
        write_qmd(material_root / "unterricht" / f"ab_{index:02}.qmd",
                  f"---\ntitle: Blatt {index:02}\nsubject: mathematik\ngrade: klasse-05\ntags: [mathematik, klasse-05, arithmetik, {extra}, '26/27']\n---\nText\n")
    write_qmd(material_root / "unterricht" / "fremd.qmd",
              "---\ntitle: Fremd\nsubject: informatik\ngrade: klasse-10\ntags: [fremder-tag]\n---\nText\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")
        page.locator("#tagTreeViewButton").click()
        assert page.locator("#tagBadgePanel").is_hidden()
        page.locator('#tagEntries [data-subject="mathematik"]').click()
        page.locator('#tagEntries [data-grade="klasse-05"]').click()
        page.locator('#tagEntries [data-tag="arithmetik"]').click()
        badges = page.locator("#tagBadges")
        for excluded in ["mathematik", "klasse-05", "arithmetik", "fremder-tag"]:
            assert badges.locator(f'[data-badge="{excluded}"]').count() == 0
        assert badges.locator('[data-badge="vertiefung"] .tag-count').inner_text() == "3"
        assert badges.locator('[data-badge="grundlagen"] .tag-count').inner_text() == "20"
        badges.locator('[data-badge="grundlagen"]').click()
        assert page.locator("#tagPageStatus").inner_text() == "1–20 von 20"
        assert badges.locator('[data-badge="grundlagen"]').get_attribute("aria-pressed") == "true"
        assert badges.locator('[data-badge="grundlagen"]').evaluate("(el) => el === document.activeElement")
        assert badges.locator('[data-badge="vertiefung"]').count() == 0
        badges.locator('[data-badge="partnerarbeit"]').click()
        assert page.locator("#tagResults [data-document]").count() == 2
        assert badges.locator('[data-badge="einzelarbeit"]').count() == 0
        badges.locator('[data-badge="grundlagen"]').click()
        assert page.locator("#tagResults [data-document]").count() == 2
        from playwright.sync_api import expect

        page.locator("#documentSearch").fill("Nichts gefunden")
        expect(page.locator("#tagResults [data-document]")).to_have_count(0)
        assert badges.locator('[data-badge="partnerarbeit"]').get_attribute("aria-pressed") == "true"
        page.locator("#tagReset").click()
        assert page.locator("#tagPageStatus").inner_text() == "1–20 von 23"
        assert page.locator('#tagBreadcrumbs [aria-current]').inner_text() == "arithmetik"
        assert badges.locator('[aria-pressed="true"]').count() == 0
        page.locator("#tagFilterDetails > summary").click()
        page.locator("#tagYearFilter").select_option("26/27")
        assert badges.locator('[data-badge="26/27"]').count() == 0
        browser.close()


def test_qmd_entry_prefers_frontmatter_over_path_attributes(material_root):
    source = write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-05" / "arbeitsblaetter" / "spezial.qmd",
        "---\ntitle: Spezial\nsubject: informatik\ngrade: klasse-10\nkind: Klausur\n---\n\nText\n",
    )

    entry = material_app.services().documents.qmd_entry(source)

    assert entry["subject"] == "informatik"
    assert entry["grade"] == "klasse-10"
    assert entry["kind"] == "Klausur"


def test_tag_filter_in_search_mask(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "a.qmd", "---\ntitle: Blatt A\ntags: [sondertag]\n---\n\nText A\n")
    write_qmd(material_root / "unterricht" / "b.qmd", "---\ntitle: Blatt B\n---\n\nText B\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url, wait_until="networkidle")

        # #tagFilter steckt in der Suchmaske, die erst per Fokus auf #documentSearch oeffnet.
        page.locator("#documentSearch").click()
        page.locator("#tagFilter").fill("sondertag")
        page.locator("#tagFilter").press("Enter")
        page.wait_for_selector("#documentResults .document-option")
        options = page.locator("#documentResults .document-option")
        assert options.count() == 1
        assert "a.qmd" in options.first.get_attribute("data-path")
        browser.close()


def test_window_heartbeat_tracks_windows_and_delivers_open_requests(material_root):
    write_qmd(material_root / "unterricht" / "eigene-materialien" / "blatt.qmd")
    client = material_app.create_app().test_client()

    assert client.get("/api/desktop-status").get_json()["windows"] == 0
    response = client.post("/api/window/open", json={"path": "unterricht/eigene-materialien/blatt.qmd"})
    assert response.status_code == 202
    identifier = response.get_json()["id"]
    assert client.get(f"/api/window/open/{identifier}").get_json()["claimed"] is False

    heartbeat = client.post("/api/window/heartbeat", json={"session": "fenster-1"}).get_json()
    assert heartbeat["windows"] == 1
    assert heartbeat["requests"] == [{"id": identifier, "path": "unterricht/eigene-materialien/blatt.qmd"}]
    assert client.get(f"/api/window/open/{identifier}").get_json()["claimed"] is True
    assert client.get("/api/desktop-status").get_json()["windows"] == 1

    assert client.post("/api/window/heartbeat", json={"session": "fenster-1"}).get_json()["requests"] == []
    client.post("/api/window/close", json={"session": "fenster-1"})
    assert client.get("/api/desktop-status").get_json()["windows"] == 0


def test_window_open_rejects_incomplete_payloads_and_unknown_imports(material_root):
    client = material_app.create_app().test_client()

    assert client.post("/api/window/open", json={}).status_code == 400
    assert client.post("/api/window/open", json={"path": "a.qmd", "import": "b"}).status_code == 400
    assert client.post("/api/window/open", json={"import": "0" * 48}).status_code == 404
    assert client.post("/api/window/heartbeat", json={"session": ""}).status_code == 400


def test_window_open_request_can_be_discarded(material_root):
    client = material_app.create_app().test_client()

    identifier = client.post("/api/window/open", json={"path": "a.qmd"}).get_json()["id"]
    assert client.delete(f"/api/window/open/{identifier}").get_json()["ok"] is True
    assert client.post("/api/window/heartbeat", json={"session": "fenster-1"}).get_json()["requests"] == []


def test_window_registry_expires_stale_heartbeats():
    from material_ui.windows import WindowRegistry

    registry = WindowRegistry(timeout=0.05)
    registry.heartbeat("fenster-1")
    assert registry.count() == 1
    time.sleep(0.06)
    assert registry.count() == 0


def test_document_tabs_switch_close_and_receive_forwarded_files(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "a.qmd", "---\ntitle: Blatt A\n---\n\n# A\n")
    write_qmd(material_root / "unterricht" / "b.qmd", "---\ntitle: Blatt B\n---\n\n# B\n")
    app = material_app.create_app()
    app.config.update(TESTING=True)

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(".editor-host .cm-content")
        page.evaluate("async () => { const app = await import('/static/app.js'); await app.selectDocument('unterricht/a.qmd'); }")
        page.wait_for_function("async () => (await import('/static/app.js')).state.qmdPath === 'unterricht/a.qmd'")
        page.evaluate("async () => { const app = await import('/static/app.js'); await app.selectDocument('unterricht/b.qmd'); }")
        page.wait_for_function("async () => (await import('/static/app.js')).state.qmdPath === 'unterricht/b.qmd'")
        assert page.locator("#documentTabs .document-tab").count() == 2
        assert page.locator("#documentTabs .document-tab.active [data-tab]").first.get_attribute("data-tab") == "unterricht/b.qmd"

        page.locator('#documentTabs [data-tab="unterricht/a.qmd"]').click()
        page.wait_for_function("async () => (await import('/static/app.js')).state.qmdPath === 'unterricht/a.qmd'")

        client = app.test_client()
        assert client.post("/api/window/open", json={"path": "unterricht/b.qmd"}).status_code == 202
        page.wait_for_function("async () => (await import('/static/app.js')).state.qmdPath === 'unterricht/b.qmd'")

        page.locator('#documentTabs [data-tab-close="unterricht/b.qmd"]').click()
        page.wait_for_function("async () => (await import('/static/app.js')).state.qmdPath === 'unterricht/a.qmd'")
        assert page.locator("#documentTabs .document-tab").count() == 1
        browser.close()


def test_folder_metadata_refresh_is_local_and_tracks_external_changes(material_root, monkeypatch):
    folder = material_root / "unterricht" / "aktuell"
    source = write_qmd(folder / "blatt.qmd", "---\ntitle: Vorher\n---\n")
    write_qmd(folder / "unterordner" / "kind.qmd")
    app = material_app.create_app()
    service = app.extensions["material_runtime"].services.documents
    monkeypatch.setattr(service, "_index", lambda: pytest.fail("Globaler Index darf nicht geladen werden"))
    client = app.test_client()
    url = "/api/folder?path=unterricht/aktuell&metadata=1"
    assert [entry["title"] for entry in client.get(url).json["qmds"]] == ["Vorher"]
    source.write_text("---\ntitle: Nachher\n---\n")
    write_qmd(folder / "neu.qmd")
    data = client.get(url).json
    assert {entry["title"] for entry in data["qmds"]} == {"Nachher", "Testmaterial"}
    source.unlink()
    assert [entry["name"] for entry in client.get(url).json["qmds"]] == ["neu.qmd"]
    assert client.get("/api/folder?path=..&metadata=1").status_code == 400


def test_folder_expansion_refreshes_only_its_contents_and_preserves_branches(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    folder = material_root / "unterricht" / "aktuell"
    source = write_qmd(folder / "blatt.qmd", "---\ntitle: Vorher\n---\n")
    write_qmd(folder / "unterordner" / "kind.qmd")
    relative = source.relative_to(material_root).as_posix()
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); if (!localStorage.getItem("material-ui:active-view")) localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(f"{url}/?path={relative}", wait_until="networkidle")
        summary = page.locator('summary[data-folder="unterricht/aktuell"]')
        child = page.locator('details[data-folder="unterricht/aktuell/unterordner"]')
        child.locator(":scope > summary").click()
        child.locator('button[data-document="unterricht/aktuell/unterordner/kind.qmd"]').filter(has_text="Testmaterial").wait_for()
        summary.click()
        source.write_text("---\ntitle: Nachher\n---\n")
        write_qmd(folder / "neu.qmd", "---\ntitle: Neue Datei\n---\n")
        requests = []
        page.on("request", lambda request: requests.append(request.url))
        summary.click()
        page.locator(f'button[data-document="{relative}"]').filter(has_text="Nachher").wait_for()
        page.locator('button[data-document="unterricht/aktuell/neu.qmd"]').filter(has_text="Neue Datei").wait_for()
        assert child.evaluate("element => element.open")
        assert not any("/api/qmds" in request for request in requests)
        assert any("/api/folder?path=unterricht%2Faktuell&metadata=1" in request for request in requests)
        assert not any("path=unterricht%2Faktuell%2Funterordner" in request for request in requests)
        requests.clear()
        page.get_by_role("button", name="Aktuelle Ansicht aktualisieren", exact=True).click()
        page.wait_for_function("document.getElementById('reloadIndex').disabled === false")
        assert child.evaluate("element => element.open")
        assert not any("/api/qmds" in request for request in requests)
        browser.close()




def test_open_folder_highlights_its_contents_and_moves_selection(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    base = "unterricht/mathematik/klasse-10"
    for name in ("potenzen", "trigonometrie"):
        write_qmd(material_root / base / name / "ab.qmd", "---\ntitle: Arbeitsblatt\n---\nText\n")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:active-view", "folder")')
        page.goto(url, wait_until="networkidle")
        page.locator("#navigationFolder").fill(base)
        page.locator("#navigationFolder").press("Enter")
        for name in ("potenzen", "trigonometrie"):
            row = page.locator(f'summary[data-folder="{base}/{name}"]')
            if row.locator("..").get_attribute("open") is not None:
                row.click()
            row.click()
            selected = page.locator("#folderEntries details.folder-selected")
            assert selected.count() == 1
            assert selected.get_attribute("data-folder") == f"{base}/{name}"
            assert selected.get_attribute("open") is not None
            assert row.get_attribute("aria-current") == "location"
            selected.locator("button[data-document]").wait_for(state="visible")
            assert selected.evaluate("node => getComputedStyle(node).boxShadow") != "none"
        browser.close()


def test_explicit_mini_type_offers_templates_and_creates_two_copy_body(material_root):
    (material_root / "unterricht").mkdir()
    client = material_app.create_app().test_client()
    catalog = client.get("/api/templates").get_json()["templates"]
    mini = [entry for entry in catalog if "Mini-AB" in entry.get("tags", [])]
    assert {Path(entry["path"]).name for entry in mini} >= {"worksheet-mini.typst"}
    payload = {"folder": "unterricht", "title": "Kopfrechnen", "kind": "Mini-AB"}
    preview = client.get("/api/document/new-preview", query_string=payload)
    assert preview.status_code == 200
    assert preview.get_json()["path"] == "unterricht/ab_mini_kopfrechnen.qmd"
    response = client.post("/api/document/new", json=payload)
    assert response.status_code == 200
    source = (material_root / response.get_json()["path"]).read_text(encoding="utf-8")
    assert "worksheet-mini.typst" in source
    assert "[Mini-AB]\n\n# Kopfrechnen" in source
    assert "[/Mini-AB]" in source
