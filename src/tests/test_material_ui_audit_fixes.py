from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import threading

import pytest

from material_core.metadata import set_template
from material_ui.plugins.storage import PluginEnabledStore
from material_ui.app import create_app
from material_ui.config import AppConfig
from material_ui.jobs import JobBusy, JobRegistry, ResourceJobQueue
from material_ui.processes import ProcessRunner
from material_ui.protocol import API_VERSION, CAPABILITIES
from requirements import needs_present_app


@pytest.fixture
def application(tmp_path):
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    yield app
    app.extensions["material_runtime"].close()


def slide_source(root):
    source = root / "slide.qmd"
    source.write_text(set_template("## Einstieg\n\nEine Frage\n", "src/quarto/templates/slide-template.typst", "typst"))
    return source


def test_deck_generation_does_not_block_other_documents(application, tmp_path, monkeypatch):
    source = slide_source(tmp_path)
    other = tmp_path / "other.qmd"
    other.write_text("Original")
    services = application.extensions["material_runtime"].services
    entered, release, saved = threading.Event(), threading.Event(), threading.Event()
    result = SimpleNamespace(pdf_path=tmp_path / "slide.pdf", stdout="", returncode=0,
                             command=[], source_revision="snapshot")
    monkeypatch.setattr(services.builds, "build_document", lambda *a, **kw: result)
    monkeypatch.setattr("material_ui.rendering.check_layout", lambda *a, **kw: [])

    def generate(source, output_path):
        entered.set()
        assert release.wait(5)
        output_path.write_text('{"elements": []}')

    monkeypatch.setattr("material_ui.slides.generate_deck", generate)
    renderer = threading.Thread(target=services.render.worker, args=(source,))
    statuses = []

    def save_other():
        client = application.test_client()
        snapshot = client.get("/api/document?path=other.qmd").json
        statuses.append(client.post("/api/document", json={"path": "other.qmd", "text": "Neu",
                                                               "revision": snapshot["revision"]}).status_code)
        saved.set()

    renderer.start()
    writer = None
    try:
        assert entered.wait(5)
        writer = threading.Thread(target=save_other)
        writer.start()
        assert saved.wait(2), "Ein anderes Dokument darf nicht auf den Deck-Bau warten."
        assert statuses == [200]
    finally:
        release.set()
        renderer.join(5)
        if writer:
            writer.join(5)
    assert services.render.state_payload()["ok"] is True


def test_slides_http_returns_a_job_before_generation_finishes(application, tmp_path, monkeypatch):
    source = slide_source(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def generate(source, output_path):
        entered.set()
        assert release.wait(5)
        output_path.write_text('{"elements": []}')

    monkeypatch.setattr("material_ui.slides.generate_deck", generate)
    client = application.test_client()
    try:
        response = client.post("/api/slides/ensure", json={"path": source.name})
        assert response.status_code == 202
        identifier = response.json["job_id"]
        assert entered.wait(5)
        assert client.get(f"/api/jobs/{identifier}").json["running"]
        duplicate = client.post("/api/slides/ensure", json={"path": source.name})
        assert duplicate.json["job_id"] == identifier
    finally:
        release.set()
        runtime = application.extensions["material_runtime"]
        with runtime.worker_lock:
            workers = list(runtime.workers)
        for worker in workers:
            worker.join(5)
    record = client.get(f"/api/jobs/{identifier}").json
    assert record["ok"] is True
    assert record["generated"] is True
    assert record["deck"].endswith("slide.excalidraw")


@pytest.mark.parametrize("invalidate", ["source-change", "shutdown"])
def test_unfinished_deck_cannot_publish_after_change_or_shutdown(application, tmp_path, monkeypatch, invalidate):
    source = slide_source(tmp_path)
    slides = application.extensions["material_runtime"].services.slides
    deck = slides.deck_path(source)
    deck.parent.mkdir(parents=True)
    deck.write_text("Vorherige Fassung")

    def generate(source, output_path):
        output_path.write_text("Veraltetes Ergebnis")
        if invalidate == "source-change":
            source.write_text(source.read_text() + "\nNeue Frage\n")
        else:
            slides.close()

    monkeypatch.setattr("material_ui.slides.generate_deck", generate)
    with pytest.raises((ValueError, RuntimeError)):
        slides.rebuild(source)
    assert deck.read_text() == "Vorherige Fassung"


def test_resource_jobs_are_bounded_coalesced_and_closed():
    jobs, submissions = JobRegistry(), []
    queue = ResourceJobQueue(jobs, lambda worker, args: submissions.append((worker, args)), limit=1)
    first = queue.start("a", "slides-ensure", lambda: {"ok": True})
    assert queue.start("a", "slides-ensure", lambda: pytest.fail("duplicate")) == first
    second = queue.start("b", "slides-ensure", lambda: {"ok": True})
    assert queue.start("b", "slides-rebuild", lambda: {"ok": True, "forced": True}) == second
    with pytest.raises(JobBusy):
        queue.start("c", "slides-ensure", lambda: {})
    worker, args = submissions.pop(0)
    worker(*args)
    assert jobs.get(first)["ok"] is True
    assert jobs.get(second)["operation"] == "slides-rebuild"
    worker, args = submissions.pop(0)
    worker(*args)
    assert jobs.get(second)["forced"] is True
    assert not jobs.retained
    third = queue.start("c", "slides-ensure", lambda: {})
    queue.close()
    assert jobs.get(third)["status"] == "failed"
    with pytest.raises(JobBusy):
        queue.start("d", "slides-ensure", lambda: {})


@pytest.fixture
def application_without_workers(tmp_path):
    """Ohne Kalender und Erinnerungen: deren Hintergrundthread durchsucht dieselben Ordner."""
    store = PluginEnabledStore(tmp_path / "daten" / "plugins.json")
    for plugin_id in ("kalender", "erinnerungen"):
        store.set_enabled(plugin_id, False)
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    yield app
    app.extensions["material_runtime"].close()


def test_catalog_shares_discovery_and_metadata_after_a_save(application_without_workers, tmp_path, monkeypatch):
    import material_ui.catalog as catalog_module
    application = application_without_workers
    for name in ("a.qmd", "b.qmd"):
        (tmp_path / name).write_text("---\ntitle: Blatt\n---\nWurzel\n")
    application.extensions["material_runtime"].services.documents.invalidate_qmd_cache()
    client = application.test_client()
    walks, reads = [], []
    walk, read = catalog_module.os.walk, Path.read_text

    def counted_walk(*args, **kwargs):
        walks.append(args[0])
        return walk(*args, **kwargs)

    def counted_read(path, *args, **kwargs):
        if path.suffix == ".qmd":
            reads.append(path.name)
        return read(path, *args, **kwargs)

    monkeypatch.setattr(catalog_module.os, "walk", counted_walk)
    monkeypatch.setattr(Path, "read_text", counted_read)
    assert client.get("/api/qmds").status_code == 200
    assert len(walks) == 1
    reads.clear()
    assert len(client.get("/api/search?q=wurzel").json["results"]) == 2
    assert reads == []
    assert len(walks) == 1
    assert client.post("/api/document", json={"path": "a.qmd", "text": "Neue Wurzel"}).status_code == 200
    reads.clear()
    assert client.get("/api/qmds").status_code == 200
    assert "b.qmd" not in reads
    assert len(walks) == 1
    # External creation is detected without waiting for TTL expiry.
    (tmp_path / "c.qmd").write_text("Wurzel")
    assert len(client.get("/api/search?q=wurzel").json["results"]) == 3
    assert len(walks) == 2


def test_managed_generator_preserves_data_output_and_stdin(tmp_path):
    from excalideck.processes import process_scope, run_process
    runner = ProcessRunner(tail_bytes=64)
    try:
        with process_scope(runner.run):
            result = run_process([sys.executable, "-c", "import sys; print(sys.stdin.read() * 1000, end='')"],
                                 input="Beispiel", text=True, capture_output=True, timeout=5)
        assert result.stdout == "Beispiel" * 1000
        assert not runner.processes
    finally:
        runner.close()


def test_catalog_parses_once_for_navigation_search_and_later_outputs(application, tmp_path, monkeypatch):
    import material_core.metadata as metadata_module
    source = tmp_path / "a.qmd"
    source.write_text('---\ntitle: Blatt\noutput-file: custom.pdf\ndeck: build/custom.excalidraw\n---\nWurzel\n')
    parser, fast_parser, calls = metadata_module.yaml_parser, metadata_module.fast_yaml_parser, []

    def counted_parser():
        calls.append("roundtrip")
        return parser()

    def counted_fast_parser():
        calls.append("fast")
        return fast_parser()

    monkeypatch.setattr(metadata_module, "yaml_parser", counted_parser)
    monkeypatch.setattr(metadata_module, "fast_yaml_parser", counted_fast_parser)
    services = application.extensions["material_runtime"].services
    assert services.search.search("wurzel")[0]["title"] == "Blatt"
    assert services.documents.qmd_entries_cached()[0]["pdf"] is None
    assert len(calls) == 1
    pdf = tmp_path / "build/pdf/custom.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    deck = tmp_path / "build/custom.excalidraw"
    deck.write_text('{"elements": []}')
    entry = services.documents.qmd_entry(source)
    assert entry["pdf"] == "build/pdf/custom.pdf"
    assert entry["deck"] == "build/custom.excalidraw"
    assert len(calls) == 1


def test_server_rejects_cached_incompatible_contract_before_writing(application, tmp_path):
    (tmp_path / "a.qmd").write_text("Original")
    client = application.test_client()
    for headers in ({"X-Material-API-Version": str(API_VERSION + 1)},
                    {"X-Material-API-Version": str(API_VERSION), "X-Material-Capabilities": "unknown"}):
        assert client.post("/api/document", json={"path": "a.qmd", "text": "Neu"}, headers=headers).status_code == 426
        assert (tmp_path / "a.qmd").read_text() == "Original"
    assert client.post("/api/document", json={"path": "a.qmd", "text": "Neu"}, headers={
        "X-Material-API-Version": str(API_VERSION), "X-Material-Capabilities": ",".join(CAPABILITIES)
    }).status_code == 200


def test_concurrent_source_change_cannot_poison_shared_metadata(application, tmp_path, monkeypatch):
    source = tmp_path / "a.qmd"
    source.write_text("---\ntitle: Alt\n---\nAlte Wurzel\n")
    services = application.extensions["material_runtime"].services
    read = services.documents.catalog.read_text
    changed = False

    def change_after_read(path):
        nonlocal changed
        text = read(path)
        if not changed:
            changed = True
            source.write_text("---\ntitle: Neu\n---\nNeue Inhalte\n")
        return text

    monkeypatch.setattr(services.documents.catalog, "read_text", change_after_read)
    assert services.search.search("wurzel") == []
    assert services.documents.qmd_entry(source)["title"] == "Neu"


def test_versioned_static_assets_are_cached_but_sources_are_not(application, tmp_path):
    client = application.test_client()
    version = application.config["MATERIAL_ASSET_VERSION"]
    response = client.get(f"/static/app.js?v={version}")
    assert response.cache_control.immutable
    assert client.get(f"/static/app.js?v={version}", headers={"If-None-Match": response.headers["ETag"]}).status_code == 304
    assert client.get("/static/app.js").headers["Cache-Control"] == "no-cache"
    assert client.get("/").headers["Cache-Control"] == "no-store"
    assert f"app.js?v={version}" in client.get("/").text
    assert 'type="importmap"' in client.get("/").text
    assert client.get("/static/api-contract.json?v=old-server").status_code == 426
    (tmp_path / "a.qmd").write_text("Original")
    assert client.get("/api/document?path=a.qmd").headers["Cache-Control"] == "no-store"


@needs_present_app
def test_browser_keeps_document_navigation_available_during_slide_job(application, tmp_path, monkeypatch):
    from test_material_ui import LiveServer, free_port, sync_playwright
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    source = slide_source(tmp_path)
    (tmp_path / "other.qmd").write_text("Ein anderes Dokument")
    entered, release = threading.Event(), threading.Event()

    def generate(source, output_path):
        entered.set()
        assert release.wait(10)
        output_path.write_text('{"type":"excalidraw","elements":[],"files":{}}')

    monkeypatch.setattr("material_ui.slides.generate_deck", generate)
    try:
        with LiveServer(application, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(f"{url}?path={source.name}", wait_until="networkidle")
            page.locator("#slidesPlay").click()
            assert entered.wait(5)
            assert page.locator("#slidesPlay").is_disabled()
            page.evaluate("async () => (await import('/static/app.js')).selectDocument('other.qmd')")
            page.wait_for_function("window.materialEditor.getText() === 'Ein anderes Dokument'")
            release.set()
            page.wait_for_function("!document.querySelector('#slidesPlay').disabled")
            assert "open" not in (page.locator("#deckModal").get_attribute("class") or "").split()
            page.evaluate("async () => (await import('/static/app.js')).selectDocument('slide.qmd')")
            page.locator("#slidesPlay").click()
            page.locator("#deckModal.open").wait_for(state="visible")
            page.frame_locator("#deckFrame").locator("canvas").first.wait_for(state="visible")
            assert errors == []
            browser.close()
    finally:
        release.set()
