from __future__ import annotations

import errno
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_ui import app as material_app
from material_ui.storage import DocumentRepository, atomic_write_text
from material_ui.processes import ProcessRunner
from test_material_ui import LiveServer, free_port, sync_playwright, write_pdf, staged_pdf, editor_text, replace_editor_text


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(material_app, "ROOT", tmp_path)
    (tmp_path / "blatt.qmd").write_text("Text\n", encoding="utf-8")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        try:
            yield app.test_client()
        finally:
            app.extensions["material_runtime"].close()


def test_concurrent_document_creation_never_overwrites(client, monkeypatch):
    barrier = threading.Barrier(2)
    original = atomic_write_text

    def simultaneous_write(*args, **kwargs):
        barrier.wait(timeout=5)
        return original(*args, **kwargs)

    from material_ui import documents as document_module
    monkeypatch.setattr(document_module, "atomic_write_text", simultaneous_write)
    responses = []

    def create(title):
        responses.append(client.application.test_client().post("/api/document/new", json={
            "title": title, "filename": "gleich",
        }))

    workers = [threading.Thread(target=create, args=(title,)) for title in ("Erste Fassung", "Zweite Fassung")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive()
    assert sorted(response.status_code for response in responses) == [200, 409]
    success = next(response.get_json() for response in responses if response.status_code == 200)
    assert client.get("/api/document", query_string={"path": success["path"]}).get_json()["text"] == success["text"]


def test_disk_full_preserves_document_and_cleans_temporary_file(client, tmp_path, monkeypatch):
    from material_ui import storage

    def full_disk(*args):
        raise OSError(errno.ENOSPC, "Kein Speicherplatz")

    monkeypatch.setattr(storage.os, "fsync", full_disk)
    response = client.post("/api/document", json={"path": "blatt.qmd", "text": "Neu"})
    assert response.status_code == 500
    assert (tmp_path / "blatt.qmd").read_text() == "Text\n"
    assert not list(tmp_path.glob(".blatt.qmd.*"))


def test_save_preserves_document_permissions(tmp_path):
    source = tmp_path / "blatt.qmd"
    source.write_text("Alt")
    source.chmod(0o640)
    DocumentRepository().save(source, "Neu")
    assert source.stat().st_mode & 0o777 == 0o640


def test_new_document_rejects_symlinked_default_folder(client, tmp_path):
    outside = tmp_path.parent / "extern"
    outside.mkdir()
    (tmp_path / "unterricht").symlink_to(outside, target_is_directory=True)
    response = client.post("/api/document/new", json={"title": "Extern"})
    assert response.status_code == 400
    assert not list(outside.rglob("*"))


def test_external_edit_during_commit_is_preserved_and_archived(tmp_path, monkeypatch):
    from material_ui import storage

    source = tmp_path / "blatt.qmd"
    source.write_text("Original")
    repository = DocumentRepository()
    snapshot = repository.read(source)
    original = storage.atomic_write_text

    def external_edit(path, text, **kwargs):
        if path == source:
            path.write_text("Extern während des Speicherns geändert")
        return original(path, text, **kwargs)

    monkeypatch.setattr(storage, "atomic_write_text", external_edit)
    with pytest.raises(storage.RevisionConflict):
        repository.save(source, "UI-Änderung", snapshot["revision"])
    assert source.read_text() == "Extern während des Speicherns geändert"
    versions = repository.history(source)
    assert {repository.history_snapshot(source, item["id"])["text"] for item in versions} == {
        "Original", "Extern während des Speicherns geändert",
    }
    assert not list(tmp_path.glob(".blatt.qmd.*"))


def test_history_is_bounded_and_accessible_without_overwriting(client, tmp_path):
    source = tmp_path / "blatt.qmd"
    repository = client.application.extensions["material_runtime"].documents
    repository.history_limit = 2
    for text in ("Eins", "Zwei", "Drei"):
        assert client.post("/api/document", json={"path": source.name, "text": text}).status_code == 200
    versions = client.get("/api/document/history?path=blatt.qmd").get_json()["versions"]
    assert len(versions) == 2
    snapshot = client.get(f'/api/document/history/{versions[0]["id"]}?path=blatt.qmd').get_json()
    assert snapshot["text"] == "Zwei"
    assert source.read_text() == "Drei"
    assert client.get("/api/document/history?path=../extern.qmd").status_code == 400
    assert client.get("/api/document/history/invalid?path=blatt.qmd").status_code == 400


def test_history_obeys_byte_limit(tmp_path):
    source = tmp_path / "blatt.qmd"
    source.write_text("Alt")
    repository = DocumentRepository(history_bytes=500)
    for number in range(6):
        repository.save(source, str(number) * 250)
    files = list(repository.history_dir(source).glob("*.json"))
    assert len(files) == 1
    assert files[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["exit", "invalid", "empty", "publish"])
def test_failed_render_preserves_last_good_pdf(client, tmp_path, monkeypatch, failure):
    from material_ui.builds import BuildService

    source = tmp_path / "blatt.qmd"
    (tmp_path / "pdf").mkdir()
    previous = write_pdf(tmp_path / "pdf" / "blatt.pdf", "Letztes gutes PDF")
    original = previous.read_bytes()

    def render(command, **kwargs):
        target = staged_pdf(command)
        if failure in {"exit", "invalid"}:
            target.write_bytes(b"Kein PDF")
        elif failure == "empty":
            target.touch()
        else:
            write_pdf(target)
        return subprocess.CompletedProcess(command, 1 if failure == "exit" else 0, stdout="Renderprotokoll")

    def broken_publish(*args, **kwargs):
        raise OSError("Datenträgerfehler")

    if failure == "publish":
        monkeypatch.setattr(BuildService, "publish_pdf", broken_publish)
    monkeypatch.setattr(material_app.services().builds, "run_process", render)
    monkeypatch.setattr(material_app.services().builds, "build_tikz_assets", lambda directory: None)
    with client.application.app_context():
        material_app.services().render.worker(source)
        state = material_app.services().render.state_payload()
    assert state["ok"] is False
    assert "Renderprotokoll" in state["detail"]["log"]
    assert previous.read_bytes() == original
    assert not list(tmp_path.glob(".material-render-*"))


def test_process_output_is_bounded_and_large_logs_are_stopped():
    runner = ProcessRunner(output_limit=4096, tail_bytes=128)
    result = runner.run([sys.executable, "-c", "print('X' * 1000)"], timeout=5, text=True, stdout=subprocess.PIPE)
    assert len(result.stdout) < 256
    assert "gekuerzt" in result.stdout
    with pytest.raises(RuntimeError, match="Log-Limit"):
        runner.run([sys.executable, "-c", "print('X' * 10000)"], timeout=5, stdout=subprocess.PIPE)
    assert not runner.processes


def test_render_queue_refuses_excess_without_losing_accepted_jobs(client, tmp_path, monkeypatch):
    monkeypatch.setattr(material_app.services().render, "submit", lambda *args: None)
    assert client.post("/api/render", json={"path": "blatt.qmd"}).status_code == 202
    identifiers = []
    for number in range(33):
        path = tmp_path / f"blatt-{number}.qmd"
        path.write_text("Text")
        response = client.post("/api/render", json={"path": path.name})
        if number < 32:
            assert response.status_code == 202
            identifiers.append(response.get_json()["job_id"])
        else:
            assert response.status_code == 409
    assert all(client.get(f"/api/jobs/{identifier}").status_code == 200 for identifier in identifiers)


def test_document_index_skips_broken_and_escaping_files(client, tmp_path):
    (tmp_path / "defekt.qmd").symlink_to(tmp_path / "fehlt.qmd")
    (tmp_path / "extern.qmd").symlink_to(tmp_path.parent / "extern.qmd")
    (tmp_path / "ausgabe.qmd").write_text('---\noutput-file: ../ausserhalb.pdf\n---\n')
    response = client.get("/api/qmds")
    assert response.status_code == 200
    data = response.get_json()
    assert [entry["path"] for entry in data["qmds"]] == ["blatt.qmd"]
    assert {warning["path"] for warning in data["warnings"]} == {"defekt.qmd", "extern.qmd", "ausgabe.qmd"}


def test_document_index_survives_deleted_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr(material_app.services().documents, "discover_sources", lambda: ([tmp_path / "weg.qmd", tmp_path / "blatt.qmd"], []))
    data = client.get("/api/qmds").get_json()
    assert [entry["path"] for entry in data["qmds"]] == ["blatt.qmd"]
    assert data["warnings"][0]["path"] == "weg.qmd"


@pytest.mark.parametrize("output", ["missing", "empty", "unchanged", "multiple_old"])
def test_render_rejects_missing_stale_or_unmatched_pdf(client, tmp_path, monkeypatch, output):
    source = tmp_path / "blatt.qmd"
    pdf = source.with_suffix(".pdf")
    if output in {"unchanged", "multiple_old"}:
        pdf.write_bytes(b"%PDF alt")
    if output == "multiple_old":
        (tmp_path / "pdf").mkdir()
        (tmp_path / "pdf" / "blatt.pdf").write_bytes(b"%PDF anderes altes PDF")

    def render(command, **kwargs):
        if output == "empty":
            staged_pdf(command).touch()
        return subprocess.CompletedProcess(command, 0, stdout="Prozess erfolgreich")

    monkeypatch.setattr(material_app.services().builds, "run_process", render)
    monkeypatch.setattr(material_app.services().builds, "build_tikz_assets", lambda directory: None)
    with client.application.app_context():
        material_app.services().render.worker(source)
        result = material_app.services().render.state_payload()
    assert result["ok"] is False
    assert result["detail"]["status"] == "failed"


@pytest.mark.parametrize("explicitly_queued", [False, True])
@pytest.mark.parametrize("first_fails", [False, True])
def test_render_changes_coalesce_into_latest_snapshot(client, tmp_path, monkeypatch, explicitly_queued, first_fails):
    service = material_app.services().render
    source = tmp_path / "blatt.qmd"
    submitted = []
    snapshots = []
    monkeypatch.setattr(service, "submit", lambda target, args: submitted.append((target, args)))

    def render(command, **kwargs):
        snapshots.append(Path(command[2]).read_text())
        if len(snapshots) == 1:
            for text in ("Erste Änderung", "Zweite Änderung", "Letzte Änderung"):
                assert client.post("/api/document", json={"path": "blatt.qmd", "text": text}).status_code == 200
                if explicitly_queued:
                    assert client.post("/api/render", json={"path": "blatt.qmd"}).status_code == 202
        write_pdf(staged_pdf(command))
        return subprocess.CompletedProcess(command, int(first_fails and len(snapshots) == 1), stdout="Renderlog")

    monkeypatch.setattr(service.builds, "run_process", render)
    monkeypatch.setattr(service.builds, "build_tikz_assets", lambda directory: None)
    first = service.start(source)
    target, args = submitted.pop(0)
    target(*args)
    completed = material_app.current_runtime().jobs.get(first)
    assert completed["ok"] is not first_fails
    assert completed["next_job_id"] == service.state_payload()["job_id"]
    assert len(submitted) == 1
    assert service.state_payload()["queue"] == []
    if not first_fails:
        assert (tmp_path / completed["pdf"]).is_file()
    target, args = submitted.pop(0)
    target(*args)
    assert snapshots == ["Text\n", "Letzte Änderung"]
    assert service.state_payload()["ok"] is True
    assert service.state_payload()["next_job_id"] is None
    assert submitted == []


@pytest.mark.parametrize("via_stream", [False, True])
def test_render_panel_follows_automatic_successor(via_stream):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(material_app.__file__).parent / "static" / "render-panel.js").as_uri()
    script = f'''
import assert from "node:assert/strict";
import {{ createRenderPanelController }} from {json.dumps(module)};
let stream;
globalThis.window = {{ addEventListener() {{}}, EventSource: class {{ constructor() {{ stream = this; }} }} }};
globalThis.EventSource = window.EventSource;
const state = {{ qmdPath: "blatt.qmd", session: 1, renderJob: "first", pollFailures: {{}} }};
const elements = {{
  pdfRenderingOverlay: {{}}, showRenderPanel: {{}}, renderLog: {{}},
  renderPanel: {{ classList: {{ remove() {{}} }}, querySelector() {{ return null; }} }}
}};
const shown = [];
const requested = [];
const first = {{ current: "blatt.qmd", resource: "blatt.qmd", operation: "render", job_id: "first",
  running: false, ok: true, pdf: "first.pdf", next_job_id: "next" }};
const controller = createRenderPanelController({{
  state, elements, setStatus() {{}}, showPdf: pdf => shown.push(pdf),
  api: async url => {{
    requested.push(url);
    return url.endsWith("first") ? first : {{ current: "blatt.qmd", running: false, ok: true, pdf: "latest.pdf" }};
  }}
}});
if ({json.dumps(via_stream)}) {{
  controller.initJobStream();
  stream.onmessage({{ data: JSON.stringify(first) }});
}} else {{
  await controller.pollRender();
}}
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(state.renderJob, "next");
assert.equal(requested.at(-1), "/api/jobs/next");
assert.deepEqual(shown, ["first.pdf", "latest.pdf"]);
assert.equal(elements.pdfRenderingOverlay.hidden, true);
'''
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_frontend_timeout_and_error_classification():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(material_app.__file__).parent / "static" / "api.js").as_uri()
    result = subprocess.run([node, "--input-type=module", "-e", f'''
import assert from "node:assert/strict";
import {{ api }} from {json.dumps(module)};
globalThis.document = {{ querySelector: () => ({{ content: "token" }}) }};
for (const options of [{{}}, {{ method: "POST" }}, {{ method: "POST", body: JSON.stringify({{}}) }}, {{ method: "POST", body: new FormData() }}]) {{
  globalThis.fetch = async (url, request) => {{
    assert.equal(request.headers["Content-Type"], typeof options.body === "string" ? "application/json" : undefined);
    assert.equal(request.headers["X-Material-Token"], "token");
    return new Response("{{}}");
  }};
  await api("/request", options);
}}
let calls = 0;
globalThis.fetch = (url, options) => {{
  calls += 1;
  assert.equal(options.headers["X-Material-Token"], "token");
  return new Promise((resolve, reject) => options.signal.addEventListener("abort", () => reject(new DOMException("Timeout", "AbortError"))));
}};
await assert.rejects(api("/write", {{ method: "POST", timeout: 10 }}), error => error.retryable && error.message.includes("Zeitüberschreitung"));
assert.equal(calls, 1);
for (const status of [409, 404, 503]) {{
  globalThis.fetch = async () => new Response(JSON.stringify({{ error: {{ message: "Fehler" }} }}), {{ status }});
  await assert.rejects(api("/status"), error => error.status === status && error.retryable === (status === 503));
}}
'''], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_drafts_handle_storage_failure_and_keep_other_repositories():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(material_app.__file__).parent / "static" / "drafts.js").as_uri()
    result = subprocess.run([node, "--input-type=module", "-e", f'''
import assert from "node:assert/strict";
import {{ readDraft, writeDraft, removeDraft }} from {json.dumps(module)};
const records = new Map();
globalThis.localStorage = {{
  getItem: key => records.get(key) || null,
  setItem: (key, value) => records.set(key, value),
  removeItem: key => records.delete(key)
}};
writeDraft("repo-a", "blatt.qmd", "Entwurf A", "revision-a");
writeDraft("repo-b", "blatt.qmd", "Entwurf B", "revision-b");
assert.equal(readDraft("repo-a", "blatt.qmd").text, "Entwurf A");
removeDraft("repo-a", "blatt.qmd", "Veralteter Speicherauftrag");
assert.equal(readDraft("repo-a", "blatt.qmd").text, "Entwurf A");
removeDraft("repo-a", "blatt.qmd", "Entwurf A");
assert.equal(readDraft("repo-a", "blatt.qmd"), null);
assert.equal(readDraft("repo-b", "blatt.qmd").text, "Entwurf B");
globalThis.localStorage = {{
  getItem: () => {{ throw new Error("Gesperrt"); }},
  setItem: () => {{ throw new Error("Speicher voll"); }}
}};
assert.equal(writeDraft("repo", "blatt.qmd", "Text", "revision"), false);
assert.equal(readDraft("repo", "blatt.qmd"), null);
removeDraft("repo", "blatt.qmd", "Text");
'''], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_browser_recovers_polling_and_reports_lost_job(client):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    with LiveServer(client.application, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("window.materialEditor && window.materialEditor.getText() === 'Text\\n'")
        requests = []

        def status(route):
            requests.append(route.request.url)
            if len(requests) == 1:
                route.abort()
            else:
                route.fulfill(json={"current": "blatt.qmd", "running": False, "ok": True, "message": "Wieder verbunden"})

        page.route("**/api/render/status", status)
        page.evaluate("async () => (await import('/static/app.js')).pollRender()")
        page.wait_for_function("document.querySelector('#renderStatus').textContent === 'Wieder verbunden'")
        assert len(requests) == 2
        page.route("**/api/jobs/verloren", lambda route: route.fulfill(status=404, json={"error": {"message": "Auftrag fehlt"}}))
        page.evaluate("async () => { const app = await import('/static/app.js'); app.state.renderJob = 'verloren'; await app.pollRender(); }")
        assert "Serverneustart" in page.locator("#renderStatus").inner_text()
        browser.close()


def test_browser_diff_aligns_changed_blocks_in_two_columns(client):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    with LiveServer(client.application, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 900, "height": 800})
        page.goto(url, wait_until="domcontentloaded")
        page.evaluate('''async () => {
            const { renderDiff } = await import('/static/diff.js');
            const container = document.createElement('div');
            container.id = 'testDiff';
            container.className = 'diff-view';
            container.style.width = '600px';
            document.body.replaceChildren(container);
            renderDiff(container,
                'Start\\nalt 1\\nalt 2\\nalt 3\\nEnde',
                'Start\\nneu 1\\nneu 2 <script> & ' + 'langer Text '.repeat(30) + '\\nEnde');
        }''')
        assert page.locator(".diff-columns strong").all_text_contents() == [
            "Deine noch nicht gespeicherten Änderungen", "Aktuell gespeicherte Datei",
        ]
        rows = page.locator(".diff-row")
        assert rows.count() == 5
        assert rows.nth(1).locator(".diff-line").all_text_contents() == ["+neu 1", "−alt 1"]
        assert rows.nth(3).locator(".diff-line").all_text_contents() == ["", "−alt 3"]
        assert page.locator("#testDiff script").count() == 0
        assert "<script> &" in rows.nth(2).inner_text()
        cells = rows.nth(2).locator(".diff-line")
        left, right = cells.nth(0).bounding_box(), cells.nth(1).bounding_box()
        assert left["y"] == right["y"]
        assert left["height"] == right["height"]
        assert left["x"] < right["x"]
        browser.close()


@pytest.mark.parametrize("local_changes", [False, True, "during-check"])
def test_browser_checks_external_changes_when_editor_receives_focus(client, tmp_path, local_changes):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    with LiveServer(client.application, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('''
            localStorage.setItem("material-ui:auto-render", "false");
            localStorage.setItem("material-ui:auto-save", "false");
        ''')
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("window.materialEditor && window.materialEditor.getText() === 'Text\\n'")
        if local_changes is True:
            replace_editor_text(page, "Eigene Änderungen")
        page.locator("#documentSearch").focus()
        (tmp_path / "blatt.qmd").write_text("Extern geändert\n", encoding="utf-8")
        pending = []
        if local_changes == "during-check":
            page.route("**/api/document?*", lambda route: pending.append((route, route.fetch())))
        page.locator(".cm-content").focus()
        if local_changes == "during-check":
            page.keyboard.press("Control+End")
            page.keyboard.type("Weiter")
            assert pending
            pending[0][0].fulfill(response=pending[0][1])
        if local_changes:
            page.get_by_role("dialog", name="Entwurf wiederherstellen").wait_for()
            expected = "Text\nWeiter" if local_changes == "during-check" else "Eigene Änderungen"
            assert page.locator("#recoveryDraft").input_value() == expected
            assert page.locator("#recoveryFile").input_value() == "Extern geändert\n"
            assert editor_text(page) == expected
        else:
            page.wait_for_function("window.materialEditor.getText() === 'Extern geändert\\n'")
            page.keyboard.press("Control+End")
            page.keyboard.type("Weiter")
            assert editor_text(page) == "Extern geändert\nWeiter"
        assert (tmp_path / "blatt.qmd").read_text() == "Extern geändert\n"
        browser.close()


def test_browser_restores_draft_and_resolves_revision_conflict(client, tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    with LiveServer(client.application, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("window.materialEditor && window.materialEditor.getText() === 'Text\\n'")
        page.route("**/api/document", lambda route: route.abort() if route.request.method == "POST" else route.continue_())
        replace_editor_text(page, "Mein ungesicherter Entwurf")
        page.wait_for_function("Object.keys(localStorage).some(key => key.startsWith('material-ui:draft:'))")
        page.reload(wait_until="domcontentloaded")
        page.get_by_role("dialog", name="Entwurf wiederherstellen").wait_for()
        assert page.locator("#recoveryDraft").input_value() == "Mein ungesicherter Entwurf"
        page.get_by_role("button", name="Meine Änderungen weiterbearbeiten", exact=True).click()
        assert editor_text(page) == "Mein ungesicherter Entwurf"
        page.unroute("**/api/document")
        (tmp_path / "blatt.qmd").write_text("Extern geändert")
        page.locator("#saveDoc").click()
        page.get_by_role("dialog", name="Entwurf wiederherstellen").wait_for()
        assert page.locator("#recoveryFile").input_value() == "Extern geändert"
        page.wait_for_selector("#docSaveFeedback.error")
        assert page.locator("#docSaveFeedback").inner_text().strip() == "Speichern fehlgeschlagen"
        assert (tmp_path / "blatt.qmd").read_text() == "Extern geändert"
        page.get_by_role("button", name="Meine Änderungen weiterbearbeiten", exact=True).click()
        page.locator("#saveDoc").click()
        page.wait_for_function("async () => !(await import('/static/app.js')).state.dirty")
        page.wait_for_selector("#docSaveFeedback.ok")
        assert (tmp_path / "blatt.qmd").read_text() == "Mein ungesicherter Entwurf"
        assert not page.evaluate("Object.keys(localStorage).some(key => key.startsWith('material-ui:draft:'))")
        browser.close()


def test_browser_keeps_drafts_from_two_tabs_and_saves_only_selected_version(client):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    with LiveServer(client.application, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        first = context.new_page()
        second = context.new_page()
        for page in (first, second):
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("window.materialEditor && window.materialEditor.getText() === 'Text\\n'")
            page.route("**/api/document", lambda route: route.abort() if route.request.method == "POST" else route.continue_())
        replace_editor_text(first, "Entwurf aus Tab A")
        replace_editor_text(second, "Entwurf aus Tab B")
        first.reload(wait_until="domcontentloaded")
        first.get_by_role("dialog", name="Entwurf wiederherstellen").wait_for()
        options = first.locator("#recoveryVersions option").all_text_contents()
        assert len(options) == 2
        selected = next(index for index, label in enumerate(options) if "Tab A" in label)
        first.locator("#recoveryVersions").select_option(str(selected))
        first.get_by_role("button", name="Meine Änderungen weiterbearbeiten", exact=True).click()
        assert editor_text(first) == "Entwurf aus Tab A"
        first.unroute("**/api/document")
        first.locator("#saveDoc").click()
        first.wait_for_selector("#docSaveFeedback.ok")
        drafts = first.evaluate("async () => { const app = await import('/static/app.js'); return (await import('/static/drafts.js')).readDrafts(app.state.repositoryRoot, 'blatt.qmd'); }")
        assert [draft["text"] for draft in drafts] == ["Entwurf aus Tab B"]
        browser.close()


def test_browser_can_compare_and_restore_history_without_immediate_write(client, tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    client.post("/api/document", json={"path": "blatt.qmd", "text": "Neuer Stand"})
    with LiveServer(client.application, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("window.materialEditor && window.materialEditor.getText() === 'Neuer Stand'")
        page.locator('.document-settings > summary').click()
        page.get_by_role("button", name="Versionen", exact=True).click()
        page.get_by_role("dialog", name="Frühere Dateifassung").wait_for()
        assert page.locator("#recoveryDraft").input_value() == "Text\n"
        assert page.locator("#recoveryFile").input_value() == "Neuer Stand"
        page.get_by_role("button", name="Frühere Fassung im Editor öffnen", exact=True).click()
        assert editor_text(page) == "Text\n"
        assert (tmp_path / "blatt.qmd").read_text() == "Neuer Stand"
        browser.close()
