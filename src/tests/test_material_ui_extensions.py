from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_ui import app as material_app  # noqa: E402
from material_ui.jobs import JobRegistry  # noqa: E402
from material_ui.rendering import render_detail, render_warnings  # noqa: E402
from material_ui.runtime import current_runtime  # noqa: E402
from test_material_ui import LiveServer, free_port, material_root, sync_playwright, write_qmd  # noqa: E402,F401


def test_search_finds_fulltext_with_snippet_and_line(material_root):
    write_qmd(
        material_root / "unterricht" / "mathematik" / "klasse-7" / "blatt.qmd",
        "---\ntitle: Uebungsblatt\n---\n\nHier geht es um die Quadratwurzel von Zahlen.\n",
    )
    write_qmd(material_root / "unterricht" / "informatik" / "info.qmd", "Nur etwas anderes Thema.\n")
    client = material_app.create_app().test_client()
    response = client.get("/api/search?q=wurzel")
    assert response.status_code == 200
    results = response.get_json()["results"]
    assert [item["path"] for item in results] == ["unterricht/mathematik/klasse-7/blatt.qmd"]
    hit = results[0]
    assert hit["line"] == 5
    assert "Quadratwurzel" in hit["snippet"]
    assert hit["score"] >= 1


def test_search_respects_facet_filters_and_rejects_empty_query(material_root):
    write_qmd(
        material_root / "unterricht" / "mathematik" / "blatt.qmd",
        "---\ntitle: Blatt\n---\n\nAufgabe mit Quadratwurzel.\n",
    )
    client = material_app.create_app().test_client()
    assert client.get("/api/search?q=quadrat&subject=informatik").get_json()["results"] == []
    assert client.get("/api/search?q=quadrat&subject=mathematik").get_json()["results"]
    assert client.get("/api/search?kind=Material").get_json()["results"]
    assert client.get("/api/search?kind=arbeitsblatt").get_json()["results"] == []
    assert client.get("/api/search").status_code == 400


def test_document_metadata_sets_and_removes_fields(material_root):
    client = material_app.create_app().test_client()
    text = "---\ntitle: Alt\nsubtitle: Weg damit\n---\n\nKoerper bleibt.\n"
    response = client.post(
        "/api/document/metadata",
        json={"text": text, "fields": {"title": "Neu", "author": "Max Muster", "subtitle": ""}},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["metadata"]["title"] == "Neu"
    assert data["metadata"]["author"] == "Max Muster"
    assert "subtitle" not in data["metadata"]
    assert "Koerper bleibt." in data["text"]
    assert client.post("/api/document/metadata", json={"text": "x", "fields": {"a": 5}}).status_code == 400
    assert client.post("/api/document/metadata", json={"text": "x", "fields": ["a"]}).status_code == 400


def test_document_git_reports_status_diff_and_last_commit(material_root):
    source = write_qmd(material_root / "blatt.qmd", "Ursprung\n")
    git = shutil.which("git")
    if not git:
        pytest.skip("git ist nicht installiert")

    def run(*arguments: str) -> None:
        subprocess.run([git, *arguments], cwd=material_root, check=True, capture_output=True, text=True)

    app = material_app.create_app()
    client = app.test_client()
    response = client.get("/api/document/git?path=blatt.qmd")
    assert response.status_code == 200
    assert response.get_json()["available"] is False

    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    run("add", "blatt.qmd")
    run("commit", "-q", "-m", "Erster Stand")
    source.write_text("Geaenderter Stand\n", encoding="utf-8")

    # GitService merkt sich pro Prozess, ob die Wurzel ein Arbeitsverzeichnis ist (die
    # Runtime ist im Fixture ueber alle Apps geteilt); nach git init den Merker verwerfen.
    app.extensions["material_runtime"].services.git._inside_work_tree = None
    data = client.get("/api/document/git?path=blatt.qmd").get_json()
    assert data["available"] is True
    assert data["changed"] is True
    assert "M blatt.qmd" in data["status"]
    assert "+Geaenderter Stand" in data["diff"]
    assert "Erster Stand" in data["last_commit"]
    assert client.get("/api/document/git").status_code == 400


def test_render_detail_collects_warnings_from_output():
    output = "\n".join([
        "LaTeX Warning: Reference `fig:1' on page 1 undefined",
        "Overfull \\hbox (12pt too wide) in paragraph",
        "ERROR: something failed",
        "Package hyperref Warning: Token not allowed",
    ])
    warnings = render_warnings(output)
    assert warnings == [
        "LaTeX Warning: Reference `fig:1' on page 1 undefined",
        "Overfull \\hbox (12pt too wide) in paragraph",
        "Package hyperref Warning: Token not allowed",
    ]
    detail = render_detail("blatt.qmd", "failed", output, returncode=1)
    assert detail["warnings"] == warnings
    assert detail["warning_count"] == 3
    assert "ERROR" in detail["log"]


def test_render_warnings_limit_and_ansi_stripping():
    output = "\x1b[31mLaTeX Warning: rot\x1b[0m\n" + "\n".join(f"LaTeX Warning: Nummer {i}" for i in range(25))
    warnings = render_warnings(output)
    assert len(warnings) == 21
    assert warnings[0] == "LaTeX Warning: rot"
    assert warnings[-1] == "… weitere Warnungen wurden gekürzt."


def test_job_registry_persists_and_fails_running_jobs_after_restart(tmp_path):
    persist_path = tmp_path / "jobs" / "jobs.json"
    registry = JobRegistry(persist_path=persist_path)
    identifier = registry.create("blatt.qmd", "render")
    registry.update(identifier, ok=True, status="succeeded", running=False)
    running = registry.create("blatt.qmd", "render")
    assert persist_path.is_file()

    reloaded = JobRegistry(persist_path=persist_path)
    finished = reloaded.get(identifier)
    assert finished["ok"] is True and finished["running"] is False
    interrupted = reloaded.get(running)
    assert interrupted["running"] is False
    assert interrupted["status"] == "failed"
    assert "Serverneustart" in interrupted["message"]

    reloaded.update("unbekannt", ok=True)
    assert "unbekannt" not in reloaded.records


def test_job_registry_subscribe_notifies_and_unsubscribes():
    registry = JobRegistry()
    events = []
    unsubscribe = registry.subscribe(lambda record: events.append(record))
    identifier = registry.create("blatt.qmd", "render")
    registry.update(identifier, ok=True, running=False, status="succeeded")
    unsubscribe()
    registry.update(identifier, ok=False, running=False, status="failed")
    assert len(events) == 1
    assert events[0]["ok"] is True


def test_jobs_stream_emits_retry_and_updates(material_root):
    from werkzeug.serving import make_server

    def read_event(stream):
        # Ein Ereignis ist "data: ...\n\n": Data-Zeile plus Abschlusszeile.
        payload = stream.readline().decode("utf-8")
        assert payload.startswith("data: ")
        assert stream.readline() == b"\n"
        return json.loads(payload[len("data: "):])

    app = material_app.create_app()
    server = make_server("127.0.0.1", free_port(), app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/jobs/stream"
        with urllib.request.urlopen(url, timeout=10) as stream:
            assert stream.headers["Content-Type"].startswith("text/event-stream")
            assert stream.readline() == b"retry: 3000\n"
            assert stream.readline() == b"\n"
            runtime = current_runtime()
            identifier = runtime.jobs.create("blatt.qmd", "render")
            runtime.jobs.update(identifier, ok=True, running=False, status="succeeded")
            record = read_event(stream)
            assert record["job_id"] == identifier
            assert record["ok"] is True
            assert record["operation"] == "render"

            # Render-Auftraege liefern ihr Protokoll mit: Die Statusanzeige
            # zeigt Kommando, Exit-Code und Log live.
            runtime.jobs.update(
                identifier,
                running=False,
                ok=True,
                status="succeeded",
                detail=render_detail("blatt.qmd", "ok", "Logtext", returncode=0),
            )
            record = read_event(stream)
            assert record["detail"]["log"] == "Logtext"

            # Andere Operationen gehen ohne Protokoll auf den Stream.
            audit = runtime.jobs.create("unterricht/kurs", "audit")
            runtime.jobs.update(
                audit,
                running=False,
                ok=False,
                status="failed",
                message="Kaputt",
                detail={"log": "Auditprotokoll"},
            )
            record = read_event(stream)
            assert record["job_id"] == audit
            assert record["message"] == "Kaputt"
            assert "detail" not in record
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_editor_autocomplete_filters_and_inserts_templates(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(material_root / "unterricht" / "blatt.qmd")
    app = material_app.create_app()
    app.config.update(TESTING=True)

    with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(".editor-host .cm-content")
        page.locator(".editor-host .cm-content").click()
        page.keyboard.type("[auf")
        page.wait_for_selector(".cm-tooltip-autocomplete")
        assert "Aufgabe (Überschrift)" in page.locator(".cm-tooltip-autocomplete").inner_text()
        page.keyboard.press("Enter")
        page.locator(".shortcut-settings button[type=submit]").click()
        page.wait_for_function("window.materialEditor.getText().includes('## Aufgabe 1: Kurztitel [10 P]')")

        page.keyboard.type("\n[zzz")
        page.wait_for_timeout(400)
        assert page.locator(".cm-tooltip-autocomplete").count() == 0
        browser.close()

def test_picker_merges_fulltext_results_below_metadata_hits(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(__file__).resolve().parents[1] / "material_ui/static/picker.js").as_uri()
    fulltext_module = (Path(__file__).resolve().parents[1] / "material_ui/static/fulltext-state.js").as_uri()
    script = '''
import assert from "node:assert/strict";
import { createPickerController } from MODULE;
import { createFulltextState } from FULLTEXT;

const fulltext = createFulltextState();
const state = {
  qmds: [
    { path: "a.qmd", title: "Alpha", stem: "a", name: "a.qmd", area: "unterricht", subject: "mathematik", grade: "", kind: "Arbeitsblatt", solution: false, pdf: "", mtime: 1 },
    { path: "b.qmd", title: "Beta", stem: "b", name: "b.qmd", area: "unterricht", subject: "informatik", grade: "", kind: "Arbeitsblatt", solution: false, pdf: "", mtime: 2 }
  ],
  qmdPath: "",
  activeFilter: "alle",
  activeResult: 0,
  facetFilters: { subject: "", grade: "", kind: "", pdf: "", sort: "relevance" },
  filteredQmds: []
};
const results = { innerHTML: "", hidden: true, setAttribute() {}, removeAttribute() {}, querySelectorAll() { return []; } };
const controller = createPickerController({
  state,
  fulltext,
  elements: {
    documentSearch: { value: "alpha" },
    documentResults: results,
    filterChips: { innerHTML: "", querySelectorAll() { return []; } },
    subjectFilter: { value: "", innerHTML: "" },
    gradeFilter: { value: "", innerHTML: "" },
    kindFilter: { value: "", innerHTML: "" },
    pdfFilter: { value: "", innerHTML: "" },
    sortFilter: { value: "relevance" }
  },
  api: async () => ({ results: [
    { path: "a.qmd", title: "Alpha", snippet: "…alpha…", line: 2, score: 1 },
    { path: "c.qmd", title: "Gamma", snippet: "…alpha…", line: 3, score: 2 }
  ] }),
  escapeHtml: (value) => String(value),
  normalizeSearch: (value) => String(value).toLowerCase(),
  selectDocument() {},
  uiIcon: () => ""
});

controller.renderDocumentResults(true);
assert.deepEqual(state.filteredQmds.map((entry) => entry.path), ["a.qmd"]);

let timer = null;
const realSetTimeout = setTimeout;
globalThis.setTimeout = (handler, delay) => { timer = { handler, delay }; return 1; };
controller.scheduleFulltextSearch();
assert.ok(timer);
assert.equal(timer.delay, 300);
globalThis.setTimeout = realSetTimeout;
await timer.handler();
assert.deepEqual(state.filteredQmds.map((entry) => entry.path), ["a.qmd", "c.qmd"]);
assert.ok(results.innerHTML.includes("Volltext"));
assert.ok(results.innerHTML.includes("Zeile 3"));

controller.clearFulltextSearch();
assert.deepEqual(fulltext.results, []);
'''.replace("MODULE", json.dumps(module)).replace("FULLTEXT", json.dumps(fulltext_module))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_ui_theme_fulltext_metadata_git_and_autocomplete(material_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_qmd(
        material_root / "unterricht" / "mathematik" / "blatt.qmd",
        "---\ntitle: Wurzelblatt\n---\n\nHier steht die Quadratwurzel.\n",
    )
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")

        for theme, label in (("dark", "Dunkel"), ("light", "Hell"), ("system", "System")):
            # Der Farbschema-Umschalter liegt im Menue "Weitere Optionen" und laesst es beim Waehlen offen.
            if page.locator("#headerMenuPanel").is_hidden():
                page.locator("#headerMenuToggle").click()
            for option in ("Hell", "System", "Dunkel"):
                assert page.locator("#themeToggle").get_by_role("button", name=option, exact=True).is_visible()
            page.locator("#themeToggle").get_by_role("button", name=label, exact=True).click()
            assert page.evaluate("document.documentElement.dataset.theme") == ("" if theme == "system" else theme)
            assert page.locator('#themeToggle [aria-pressed="true"]').get_attribute("aria-label") == label
            assert page.locator('#themeToggle [aria-pressed="true"]').count() == 1
            assert page.evaluate('localStorage.getItem("material-ui:theme")') == theme
        page.reload(wait_until="networkidle")
        page.locator("#headerMenuToggle").click()
        assert page.locator('#themeToggle [aria-pressed="true"]').get_attribute("aria-label") == "System"

        page.locator("#documentSearch").fill("quadratwurzel")
        page.wait_for_selector(".document-fulltext-badge")
        option = page.locator(".document-option").first.inner_text()
        assert "blatt.qmd" in option and "Zeile" in option

        page.locator(".document-option").first.click()
        page.wait_for_function("window.materialEditor && window.materialEditor.getText().includes('Quadratwurzel')")

        # Metadaten liegen im Menue "Dokument"; es schliesst nach dem Klick auf einen Eintrag.
        page.locator(".document-settings > summary").click()
        page.locator("#editMetadata").click()
        page.wait_for_function("document.querySelector('#metadataTitle').value === 'Wurzelblatt'")
        page.locator("#metadataTitle").fill("Neuer Titel")
        page.locator("#applyMetadata").click()
        page.wait_for_function("window.materialEditor.getText().includes('Neuer Titel')")
        assert page.locator("#metadataModal").get_attribute("aria-hidden") == "true"

        page.locator(".document-settings > summary").click()
        page.locator("#showGit").click()
        page.wait_for_function("document.querySelector('#gitHint').textContent.includes('kein Git-Arbeitsverzeichnis')")
        page.locator("#closeGitModalButton").click()
        assert page.locator("#gitModal").get_attribute("aria-hidden") == "true"

        page.locator(".editor-host .cm-content").click()
        page.keyboard.press("Control+End")
        page.keyboard.type("\n[Antw")
        page.wait_for_selector(".cm-tooltip-autocomplete")
        page.keyboard.press("Enter")
        page.wait_for_function("window.materialEditor.getText().includes('Ergebnis: [Antwortlinie]')")
        browser.close()
