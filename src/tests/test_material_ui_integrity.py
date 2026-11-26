from __future__ import annotations

import io
import json
import sys
import subprocess
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_ui import app as material_app
from material_ui.storage import DocumentRepository, RevisionConflict
from material_ui.processes import ProcessRunner
from test_material_ui import LiveServer, free_port, sync_playwright, editor_text, replace_editor_text, kurs_service, kurs_preview


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


def test_repository_rejects_external_changes(tmp_path):
    source = tmp_path / "blatt.qmd"
    source.write_text("Version A", encoding="utf-8")
    repository = DocumentRepository()
    snapshot = repository.read(source)
    source.write_text("Extern geändert", encoding="utf-8")
    with pytest.raises(RevisionConflict):
        repository.save(source, "Version B", snapshot["revision"])
    assert source.read_text(encoding="utf-8") == "Extern geändert"


def test_artifact_cleanup_preserves_authored_sources(client, tmp_path, monkeypatch):
    monkeypatch.setattr(material_app, "ROOT", tmp_path)
    source = tmp_path / "blatt.qmd"
    source.write_text("Text", encoding="utf-8")
    for filename in ("original.tex", "blatt.tex", "original.pdf", "vorlage.typ"):
        (tmp_path / filename).write_text("Quelle", encoding="utf-8")
    material_app.services().builds.relocate_build_artifacts([source])
    for filename in ("original.tex", "blatt.tex", "original.pdf", "vorlage.typ"):
        assert (tmp_path / filename).read_text(encoding="utf-8") == "Quelle"


def test_cli_build_uses_document_manifest_and_preserves_sources(tmp_path, monkeypatch):
    import project_tasks

    monkeypatch.setattr(project_tasks, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(project_tasks, "_build_tikz_svg_assets", lambda: None)
    source = tmp_path / "blatt.test.qmd"
    source.write_text("Text", encoding="utf-8")
    original = tmp_path / "original.tex"
    original.write_text("Handgeschrieben", encoding="utf-8")
    unrelated = tmp_path / "blatt.pdf"
    unrelated.write_bytes(b"Unabhaengiges PDF")

    def render(command, **kwargs):
        from test_material_ui import write_pdf, staged_pdf

        Path(command[2]).with_suffix(".tex").write_text("Generiert", encoding="utf-8")
        write_pdf(staged_pdf(command))
        return subprocess.CompletedProcess(command, 0, stdout="")


    monkeypatch.setattr(project_tasks, "_run", render)
    project_tasks.build.body(None, source=source.name)
    assert original.read_text(encoding="utf-8") == "Handgeschrieben"
    assert unrelated.read_bytes() == b"Unabhaengiges PDF"
    assert (tmp_path / "build" / "artefakte" / "blatt.test.tex").read_text(encoding="utf-8") == "Generiert"
    assert (tmp_path / "build" / "pdf" / "blatt.test.pdf").read_bytes().startswith(b"%PDF")
    manifest = json.loads((tmp_path / "build" / "artefakte" / "blatt.test.material-ui.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "blatt.test.qmd"
    assert set(manifest["artifacts"]) == {"build/artefakte/blatt.test.tex", "build/pdf/blatt.test.pdf"}


def test_failed_import_leaves_no_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(material_app, "ROOT", tmp_path)
    source = tmp_path / "blatt.qmd"
    source.write_text("Text", encoding="utf-8")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post("/api/import", data={
        "metadata": json.dumps({"qmdPath": "blatt.qmd", "filename": "probe", "insert": True}),
        "original": (io.BytesIO(b"PNG"), "original.png"),
    })
    assert response.status_code == 400
    assert not (tmp_path / "assets").exists() or not list((tmp_path / "assets").iterdir())
    assert source.read_text(encoding="utf-8") == "Text"
    assert not list(tmp_path.glob(".material-import-*"))


def test_document_api_returns_conflict_for_stale_revision(client, tmp_path):
    snapshot = client.get("/api/document?path=blatt.qmd").get_json()
    (tmp_path / "blatt.qmd").write_text("Extern geändert", encoding="utf-8")
    response = client.post("/api/document", json={"path": "blatt.qmd", "text": "Veraltet", "revision": snapshot["revision"]})
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "conflict"
    assert (tmp_path / "blatt.qmd").read_text(encoding="utf-8") == "Extern geändert"


def test_concurrent_saves_cannot_overwrite_the_same_revision(client, tmp_path):
    snapshot = client.get("/api/document?path=blatt.qmd").get_json()
    barrier = threading.Barrier(2)
    statuses = []

    def save(text):
        barrier.wait(timeout=5)
        response = client.application.test_client().post("/api/document", json={
            "path": "blatt.qmd", "text": text, "revision": snapshot["revision"],
        })
        statuses.append(response.status_code)

    workers = [threading.Thread(target=save, args=(text,)) for text in ("Version A", "Version B")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)
    assert sorted(statuses) == [200, 409]
    assert (tmp_path / "blatt.qmd").read_text(encoding="utf-8") in {"Version A", "Version B"}


@pytest.mark.parametrize("payload", [[], None, {"text": 12, "path": "blatt.qmd"}, {"path": "blatt.qmd"}])
def test_invalid_document_payload_is_json_error(client, tmp_path, payload):
    response = client.post("/api/document", data=json.dumps(payload), content_type="application/json")
    assert response.status_code == 400
    assert response.is_json
    assert (tmp_path / "blatt.qmd").read_text(encoding="utf-8") == "Text\n"


def test_render_get_cannot_start_a_job(client, monkeypatch):
    def unexpected(*args):
        pytest.fail("GET darf keinen Job starten")

    monkeypatch.setattr(material_app.services().render, "start", unexpected)
    response = client.get("/api/render?path=blatt.qmd")
    assert response.status_code == 405
    assert response.is_json


def test_write_requires_token_and_same_origin(client, tmp_path):
    client.application.config["TESTING"] = False
    payload = {"path": "blatt.qmd", "text": "Neu"}
    assert client.post("/api/document", json=payload).status_code == 403
    headers = {"X-Material-Token": client.application.config["MATERIAL_CSRF_TOKEN"]}
    assert client.post("/api/document", json=payload, headers={**headers, "Origin": "https://example.org"}).status_code == 403
    assert client.post("/api/document", json=payload, headers={**headers, "Origin": "http://localhost"}).status_code == 200
    assert client.get("/api/qmds", headers={"Host": "example.org"}).status_code == 400
    assert (tmp_path / "blatt.qmd").read_text(encoding="utf-8") == "Neu"


def test_import_rolls_back_assets_if_document_commit_fails(client, tmp_path, monkeypatch):
    repository = client.application.extensions["material_runtime"].documents

    def fail_commit(*args):
        raise OSError("Datenträgerfehler")

    monkeypatch.setattr(repository, "insert", fail_commit)
    response = client.post("/api/import", data={
        "metadata": json.dumps({"qmdPath": "blatt.qmd", "filename": "probe", "insert": True}),
        "original": (io.BytesIO(b"PNG"), "original.png"),
        "clean": (io.BytesIO(b"PNG"), "clean.png"),
    })
    assert response.status_code == 500
    assert response.get_json()["error"]["message"] == "Interner Fehler."
    assert not list((tmp_path / "assets").iterdir())
    assert (tmp_path / "blatt.qmd").read_text(encoding="utf-8") == "Text\n"


def test_jobs_keep_results_and_scope_moodle_status(client, tmp_path, monkeypatch):
    course = tmp_path / "unterricht" / "kurse" / "kurs-a"
    course.mkdir(parents=True)
    (course / "index.mdx").write_text("# Kurs A\n", encoding="utf-8")
    release = threading.Event()

    def fake_run(command, **kwargs):
        assert command[:2] == ["inv", "kurse.verify-moodle"]
        release.wait(timeout=5)
        return subprocess.CompletedProcess(command, 0, stdout="Fertig\n")

    monkeypatch.setattr(kurs_service(), "runner", fake_run)
    try:
        response = client.post("/api/kurse/kurs-a/moodle/verify", json={})
        assert response.status_code == 202
        identifier = response.get_json()["job_id"]
        assert client.get(f"/api/jobs/{identifier}").get_json()["resource"] == "kurs-a"
        other = client.get("/api/kurse/kurs-b/moodle/status").get_json()
        assert other == {"running": False, "slug": "kurs-b", "ok": None}
        assert client.post("/api/kurse/kurs-a/moodle/publish", json={}).status_code == 409
    finally:
        release.set()
    for attempt in range(100):
        result = client.get(f"/api/jobs/{identifier}").get_json()
        if not result["running"]:
            break
        time.sleep(0.01)
    assert result["status"] == "succeeded"
    assert result["message"] == "Fertig"
    assert client.get("/api/jobs/unknown").status_code == 404


def test_render_queue_retains_individual_results(client, tmp_path, monkeypatch):
    (tmp_path / "anderes.qmd").write_text("Anderes", encoding="utf-8")
    monkeypatch.setattr(material_app.services().render, "submit", lambda *args: None)
    first = client.post("/api/render", json={"path": "blatt.qmd"}).get_json()["job_id"]
    second = client.post("/api/render", json={"path": "anderes.qmd"}).get_json()["job_id"]
    assert first != second
    assert client.get(f"/api/jobs/{second}").get_json()["status"] == "queued"
    with client.application.app_context():
        material_app.services().render.finish(True, "Erster fertig", None)
        material_app.services().render.finish(False, "Zweiter fehlgeschlagen", None)
    assert client.get(f"/api/jobs/{first}").get_json()["status"] == "succeeded"
    assert client.get(f"/api/jobs/{second}").get_json()["status"] == "failed"


def test_app_factories_do_not_share_runtime_state():
    first = material_app.create_app()
    second = material_app.create_app()
    with first.app_context():
        identifier = first.extensions["material_runtime"].jobs.create("nur-erste-app.qmd", "render")
        material_app.services().render.latest_id = identifier
        first.extensions["material_runtime"].jobs.update(identifier, current="nur-erste-app.qmd")
    assert first.test_client().get("/api/render/status").get_json()["current"] == "nur-erste-app.qmd"
    assert second.test_client().get("/api/render/status").get_json()["current"] is None


def test_cache_hit_does_not_scan_filesystem(client, monkeypatch):
    with client.application.app_context():
        material_app.services().documents.qmd_entries_cached()

        def unexpected():
            pytest.fail("Ein Cachetreffer darf nicht erneut den Dateibaum lesen")

        monkeypatch.setattr(material_app.services().documents, "qmd_sources", unexpected)
        assert material_app.services().documents.qmd_entries_cached()


def test_timeout_stops_child_processes(tmp_path):
    marker = tmp_path / "child-survived"
    child = f"import time; from pathlib import Path; time.sleep(0.8); Path({str(marker)!r}).touch()"
    parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(10)"
    runner = ProcessRunner()
    with pytest.raises(subprocess.TimeoutExpired):
        runner.run([sys.executable, "-c", parent], timeout=0.3)
    assert not runner.processes
    time.sleep(0.9)
    assert not marker.exists()


def test_browser_saves_edits_made_while_request_is_pending(client, tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    pending = []
    with LiveServer(client.application, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")

        def save(route):
            if not pending:
                pending.append(route)
            else:
                route.continue_()

        page.route("**/api/document", save)
        replace_editor_text(page, "Version A")
        with page.expect_request(lambda request: request.method == "POST" and request.url.endswith("/api/document")):
            page.evaluate("() => { window.pendingSave = import('/static/app.js').then(app => app.saveDocument()); }")
        replace_editor_text(page, "Version B")
        pending[0].continue_()
        page.evaluate("() => window.pendingSave")
        assert editor_text(page) == "Version B"
        assert (tmp_path / "blatt.qmd").read_text(encoding="utf-8") == "Version B"
        assert page.evaluate("async () => (await import('/static/app.js')).state.dirty") is False
        browser.close()


def test_browser_ignores_late_document_response(client, tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    for name, text in (("a.qmd", "Dokument A"), ("b.qmd", "Dokument B")):
        (tmp_path / name).write_text(text, encoding="utf-8")
    snapshot = client.get("/api/document?path=a.qmd").get_json()
    pending = []
    with LiveServer(client.application, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:last-document", "blatt.qmd")')
        page.goto(url, wait_until="networkidle")
        page.route("**/api/document?path=a.qmd", lambda route: pending.append(route))
        with page.expect_request("**/api/document?path=a.qmd"):
            page.evaluate("() => { window.firstLoad = import('/static/app.js').then(app => app.selectDocument('a.qmd')); }")
        page.evaluate("async () => (await import('/static/app.js')).selectDocument('b.qmd')")
        pending[0].fulfill(json=snapshot)
        page.evaluate("() => window.firstLoad")
        assert editor_text(page) == "Dokument B"
        assert page.evaluate("async () => (await import('/static/app.js')).state.qmdPath") == "b.qmd"
        browser.close()


def test_server_restart_spawns_desktop_helper(client, monkeypatch):
    from material_ui import desktop

    spawned = []
    monkeypatch.setattr(desktop, "spawn_restart_helper", lambda host, port: spawned.append((host, port)))
    response = client.post("/api/server/restart", headers={"Host": "127.0.0.1:8765"})
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert spawned == [("127.0.0.1", 8765)]
    assert client.post("/api/server/restart", headers={"Host": "localhost"}).status_code == 400
