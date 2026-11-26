from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_core.metadata import output_filename, read_metadata, set_fields, set_template, template_value
from course_sync.classes.cli.runtime_cli_service import RuntimeCliService
from material_ui.app import create_app
from material_ui.config import AppConfig
from material_ui.jobs import JobRegistry, OperationChannel
from material_ui.processes import ProcessRunner
from material_ui.runtime import RuntimeState, current_runtime
from test_material_ui import LiveServer, free_port, sync_playwright


def test_application_roots_and_services_are_independent(tmp_path):
    roots = [tmp_path / "first", tmp_path / "second"]
    applications = []
    try:
        for root in roots:
            root.mkdir()
            (root / "blatt.qmd").write_text(root.name)
            applications.append(create_app(config=AppConfig(root)))
        for app, root in zip(applications, roots):
            client = app.test_client()
            assert client.get("/api/document?path=blatt.qmd").get_json()["text"] == root.name
            assert client.get("/api/desktop-status").get_json()["root"] == str(root)
            runtime = app.extensions["material_runtime"]
            assert runtime.plugins.contexts["kurse"].service.adapter.application().ROOT_DIR == root
            assert runtime.services.documents.qmd_entry(root / "blatt.qmd")["path"] == "blatt.qmd"
    finally:
        for app in applications:
            app.extensions["material_runtime"].close()


def test_runtime_requires_an_explicit_scope():
    with pytest.raises(RuntimeError, match="expliziten"):
        current_runtime()


def test_metadata_ignores_body_examples_and_other_formats():
    text = '---\ntitle: "Mein: Blatt"\nformat:\n  html:\n    output-file: website.html\n  pdf:\n    output-file: "richtig.pdf" # PDF\n---\n```yaml\noutput-file: falsch.pdf\n```\n'
    assert output_filename(text, "default.pdf") == "richtig.pdf"
    assert output_filename("```yaml\noutput-file: falsch.pdf\n```", "default.pdf") == "default.pdf"
    assert read_metadata(text)["title"] == "Mein: Blatt"


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_template_updates_preserve_comments_quotes_body_and_other_options(ending):
    text = ending.join([
        "---", '# Kommentar', 'title: "Mein Blatt"', "format:", "  html:", "    toc: true",
        "  typst:", "    papersize: a4", '    template: "alt.typ" # Vorlage', "---", "", "Unveränderter Text.", "",
    ])
    updated = set_template(text, "neu.typ")
    assert template_value(updated) == "neu.typ"
    assert '# Kommentar' in updated
    assert 'title: "Mein Blatt"' in updated
    assert "# Vorlage" in updated
    assert updated.endswith(ending.join(["---", "", "Unveränderter Text.", ""]))
    metadata = read_metadata(updated)
    assert metadata["format"]["html"]["toc"] is True
    assert metadata["format"]["typst"]["papersize"] == "a4"
    removed = set_template(updated, "")
    assert template_value(removed) == ""
    assert read_metadata(removed)["format"]["typst"]["papersize"] == "a4"


def test_template_handles_scalar_formats_and_exact_delimiters():
    text = '---\nformat: typst\n---\nText\n---not-a-delimiter\n'
    assert read_metadata(set_template(text, "vorlage.typ"))["format"]["typst"]["template"] == "vorlage.typ"
    assert read_metadata("---\ntitle: Test\n---not-a-delimiter\n") == {}
    assert template_value(set_template("Text", "vorlage.tex")) == "vorlage.tex"


@pytest.mark.parametrize("previous,target", [("pdf", "typst"), ("typst", "pdf"), ("pdf", "beamer")])
def test_explicit_template_engine_switch_keeps_portable_options(previous, target):
    text = (
        f"---\nformat:\n  {previous}:\n    template: alt\n    output-file: blatt.pdf\n"
        "    pdf-engine: lualatex\n  html:\n    toc: true\n---\n\nUnveränderter Inhalt.\n"
    )

    updated = set_template(text, "neue-vorlage", target)

    formats = read_metadata(updated)["format"]
    assert previous not in formats
    assert formats[target] == {"template": "neue-vorlage", "output-file": "blatt.pdf"}
    assert formats["html"]["toc"] is True
    assert updated.endswith("Unveränderter Inhalt.\n")


def test_metadata_endpoint_transforms_unsaved_text_without_writing_files(tmp_path):
    source = tmp_path / "blatt.qmd"
    source.write_text("Dateistand")
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        client = app.test_client()
        response = client.post("/api/document/metadata", json={"text": "Ungesicherter Entwurf", "template": "neu.tex"})
        assert response.status_code == 200
        assert response.get_json()["text"].endswith("Ungesicherter Entwurf")
        assert response.get_json()["template"] == "neu.tex"
        assert source.read_text() == "Dateistand"
        for payload in ({"text": "---\ntitle: [\n---\n"}, {"text": "Text", "template": None}):
            assert client.post("/api/document/metadata", json=payload).status_code == 400
    finally:
        app.extensions["material_runtime"].close()


def test_course_actions_wait_for_save_and_abort_on_conflict_or_navigation():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(__file__).resolve().parents[1] / "material_ui/plugins/kurse/assets/courses.js").as_uri()
    script = '''
import assert from "node:assert/strict";
import { createCourseController } from MODULE;
for (const action of ["startKursAudit", "startKursMoodleJob"]) {
  for (const outcome of ["saved", "conflict", "navigation"]) {
    let resolveSave, rejectSave;
    const saved = new Promise((resolve, reject) => { resolveSave = resolve; rejectSave = reject; });
    const calls = [];
    const reports = [];
    const state = { session: 1, course: { kursSlug: "demo", kursMode: true } };
    const controller = createCourseController({
      state, elements: { moodleTarget: { value: "" } },
      api: async (url, options) => { calls.push(url); return { job_id: "job" }; },
      flushPendingSave: () => saved, setStatus() {},
      readJobStatus: async () => ({ running: false, ok: true, detail: { log: "Fertig" } }),
      showRenderPanel: detail => reports.push(detail)
    });
    const pending = controller[action]("upload-course");
    assert.equal(calls.length, 0);
    if (outcome === "conflict") {
      rejectSave(new Error("Revisionskonflikt"));
      await assert.rejects(pending, /Revisionskonflikt/);
    } else {
      if (outcome === "navigation") state.session += 1;
      resolveSave();
      await pending;
    }
    assert.equal(calls.length, outcome === "saved" ? 1 : 0);
    await Promise.resolve();
    assert.equal(reports.length, outcome === "saved" ? 1 : 0);
  }
}
'''.replace("MODULE", json.dumps(module))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_ctrl_s_saves_course_activity_in_kurs_mode(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(__file__).resolve().parents[1] / "material_ui/static/editor.js").as_uri()
    script = '''
import assert from "node:assert/strict";
import { createEditorController, resolveSaveAction } from MODULE;

assert.equal(resolveSaveAction(true), "course");
assert.equal(resolveSaveAction(false), "document");

for (const [kursMode, expected] of [[true, ["course"]], [false, ["flush", "document"]]]) {
  const calls = [];
  let saveRequest = null;
  globalThis.window = {
    addEventListener() {},
    MaterialEditor: {
      create: (host, options) => {
        saveRequest = options.onSave;
        return { focus() {}, setReadOnly() {}, setAriaLabel() {}, getText: () => "", setText() {} };
      }
    }
  };
  const state = { course: { kursMode } };
  const controller = createEditorController({
    state,
    elements: { editorHost: {}, editorStatus: { textContent: "" } },
    scheduleAutoUpdate() {},
    flushPendingSave: async () => { calls.push("flush"); },
    saveDocument: async () => { calls.push("document"); },
    saveCourseActivity: async () => { calls.push("course"); },
    setStatus() {},
    renderDocument: async () => {},
    shortcuts: [],
    normalizeSearch: value => value.toLowerCase()
  });
  controller.initEditorExtensions();
  assert.equal(typeof saveRequest, "function");
  saveRequest();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.deepEqual(calls, expected);
}
'''.replace("MODULE", json.dumps(module))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_diff_lines_marks_additions_deletions_and_keeps_context():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(__file__).resolve().parents[1] / "material_ui/static/diff.js").as_uri()
    script = '''
import assert from "node:assert/strict";
import { diffLines } from MODULE;

const oldText = "a\\nb\\nc\\nd\\ne\\nf\\ng\\n";
const newText = "a\\nb\\nX\\nd\\ne\\nf\\nZ\\n";
const entries = diffLines(oldText, newText);
assert.deepEqual(entries.map(entry => entry.type + ":" + entry.text), [
  "same:a", "same:b", "del:c", "add:X", "same:d", "same:e", "same:f", "del:g", "add:Z", "same:"
]);

const identical = diffLines("gleich\\n", "gleich\\n");
assert.deepEqual(identical, [{ type: "same", text: "gleich" }, { type: "same", text: "" }]);
'''.replace("MODULE", json.dumps(module))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_scheduler_coalesces_jobs_and_activates_next_before_submission(tmp_path):
    for name in ("first.qmd", "second.qmd", "third.qmd"):
        (tmp_path / name).write_text("---\ntitle: Test\n---\nText\n")
    app = create_app(config=AppConfig(tmp_path))
    runtime = app.extensions["material_runtime"]
    service = runtime.services.render
    submitted = []

    def submit(target, args):
        submitted.append((args[0], service.state_payload()))

    service.submit = submit
    try:
        first = service.start(tmp_path / "first.qmd")
        second = service.start(tmp_path / "second.qmd")
        assert service.start(tmp_path / "second.qmd") == second
        service.finish(True, "Fertig", None)
        assert runtime.jobs.get(first)["status"] == "succeeded"
        assert submitted[-1][1]["job_id"] == second
        assert submitted[-1][1]["running"] is True
        queued = service.start(tmp_path / "third.qmd")
        runtime.close()
        assert runtime.jobs.get(second)["status"] == "failed"
        assert runtime.jobs.get(queued)["status"] == "failed"
        assert len(submitted) == 2
        service.worker(tmp_path / "third.qmd")
        assert runtime.jobs.get(queued)["status"] == "failed"
        assert service.state_payload()["job_id"] == second
    finally:
        runtime.close()


def test_status_channel_retains_latest_result_when_history_is_pruned():
    registry = JobRegistry(history_limit=2)
    channel = OperationChannel(registry, lambda target, args: target(*args))
    identifier = channel.start("demo", "audit", lambda: {"ok": True})
    for number in range(10):
        unrelated = registry.create(str(number), "render")
        registry.update(unrelated, running=False)
    assert channel.payload()["job_id"] == identifier
    assert channel.payload()["status"] == "succeeded"


def test_runtime_joins_workers_and_refuses_new_work_after_close():
    runtime = RuntimeState()
    started = threading.Event()
    finished = threading.Event()

    def worker():
        started.set()
        runtime.closing.wait(timeout=5)
        finished.set()

    runtime.start_worker(worker, ())
    assert started.wait(timeout=5)
    runtime.close()
    assert finished.is_set()
    assert not runtime.workers
    with pytest.raises(RuntimeError, match="beendet"):
        runtime.start_worker(worker, ())


def _child_process_running(token: str, grace_seconds: float = 5.0) -> bool:
    def scan() -> bool:
        proc = Path("/proc")
        if not proc.is_dir():
            return False
        needle = token.encode("utf-8")
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if needle in (entry / "cmdline").read_bytes():
                    return True
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
        return False

    deadline = time.monotonic() + grace_seconds
    while scan() and time.monotonic() < deadline:
        time.sleep(0.1)
    return scan()


def test_persistent_processes_have_bounded_logs_and_stop_with_their_children(tmp_path):
    runner = ProcessRunner(output_limit=4096, tail_bytes=256)
    marker = tmp_path / "child-survived"
    child = f"import time; from pathlib import Path; time.sleep(30); Path({str(marker)!r}).touch()"
    parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); print('X' * 100000); print('ENDLOG', flush=True); time.sleep(30)"
    managed = runner.start([sys.executable, "-c", parent], log_path=tmp_path / "preview.log")
    try:
        deadline = time.monotonic() + 5
        while "ENDLOG" not in managed.tail() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert "ENDLOG" in managed.tail()
        assert (tmp_path / "preview.log").stat().st_size <= 4096
        runner.close()
        assert managed.process.poll() is not None
        assert not managed.reader.is_alive()
        assert not runner.processes
        assert not _child_process_running(str(marker))
        with pytest.raises(RuntimeError, match="beendet"):
            runner.start([sys.executable, "-c", "pass"], log_path=tmp_path / "other.log")
    finally:
        runner.close()


def test_managed_h5p_startup_failure_reports_output_and_releases_process(tmp_path, monkeypatch):
    runner = ProcessRunner()
    backend = SimpleNamespace(
        ensure_h5p_runtime_libraries=lambda: None,
        get_h5p_cli_command=lambda: [sys.executable, "-c", "import sys; print('runtime failed', flush=True); sys.exit(1)"],
    )
    service = RuntimeCliService(workspace_lock=threading.RLock(), runtime_dir=tmp_path,
                                runtime_content_dir=tmp_path / "content", backend=backend)
    monkeypatch.setattr(service, "is_port_open", lambda *args: False)
    monkeypatch.setattr(service, "ensure_h5p_server_config", lambda: None)
    try:
        with pytest.raises(RuntimeError, match="runtime failed"):
            service.ensure_h5p_runtime_server(8876, start_process=runner.start)
        assert not runner.processes
        assert not runner.persistent
    finally:
        runner.close()


def test_browser_applies_and_removes_template_from_structured_frontmatter(tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    source = tmp_path / "blatt.qmd"
    source.write_text('---\ntitle: "Mein Blatt" # Titel\nformat: pdf\n---\n\nText\n')
    app = create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until="networkidle")
            page.locator("#changeTemplate").click()
            page.locator("#templateType").select_option("Arbeitsblatt")
            page.locator("#templateSelect").select_option("src/quarto/templates/latex-template.tex")
            page.locator("#applyTemplate").click()
            page.wait_for_function("window.materialEditor.getText().includes('latex-template.tex')")
            assert "# Titel" in page.evaluate("window.materialEditor.getText()")
            page.locator("#changeTemplate").click()
            page.locator("#removeTemplate").click()
            page.wait_for_function("!window.materialEditor.getText().includes('template:')")
            assert "Text" in page.evaluate("window.materialEditor.getText()")
            browser.close()
    finally:
        app.extensions["material_runtime"].close()


def test_set_fields_accepts_tag_lists_and_preserves_the_document():
    text = "---\ntitle: Blatt\nauthor: ich\n---\n\nKoerper\n"
    updated = set_fields(text, {"tags": ["mathe", "klasse-10"], "author": ""})
    assert read_metadata(updated)["tags"] == ["mathe", "klasse-10"]
    assert "author" not in read_metadata(updated)
    assert updated.endswith("---\n\nKoerper\n")
    removed = set_fields(updated, {"tags": []})
    assert "tags" not in read_metadata(removed)
    with pytest.raises(ValueError, match="Liste von Zeichenketten"):
        set_fields(text, {"tags": [1]})


def test_metadata_panel_parses_comma_separated_tags():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(__file__).resolve().parents[1] / "material_ui/static/metadata-panel.js").as_uri()
    script = '''
import assert from "node:assert/strict";
import { parseTagInput } from MODULE;
assert.deepEqual(parseTagInput("einheitskreis, winkel , einheitskreis"), ["einheitskreis", "winkel"]);
assert.deepEqual(parseTagInput("  "), []);
assert.deepEqual(parseTagInput(null), []);
'''.replace("MODULE", json.dumps(module))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
