import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from material_core.metadata import set_template
from material_ui.config import AppConfig
from material_ui.slides import SlidesService, annotations_path
from material_ui.storage import DocumentRepository


@pytest.mark.parametrize("terminal_ok", [True, False], ids=["succeeded", "failed"])
@pytest.mark.parametrize("late_response", ["running", "newer-running", "no-timestamp", "retryable-error", "not-found", "sse-running", "older-terminal", "fresh-poll", "clock-rollback"])
def test_render_completion_survives_late_poll_response(late_response, terminal_ok):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js fehlt")
    module = (Path(__file__).resolve().parents[1] / "material_ui/static/render-panel.js").as_uri()
    script = r'''
import assert from "node:assert/strict";
import { createRenderPanelController } from MODULE;
let stream, resolvePoll, rejectPoll;
globalThis.window = { addEventListener() {}, EventSource: class { constructor() { stream = this; } } };
globalThis.EventSource = window.EventSource;
const timers = new Map();
let timerId = 0;
globalThis.setTimeout = (callback, delay) => { timers.set(++timerId, { callback, delay }); return timerId; };
globalThis.clearTimeout = id => timers.delete(id);
const state = { qmdPath: "a.qmd", session: 1, renderJob: "job", pollFailures: {}, loadedPdf: "previous.pdf" };
const elements = {
  pdfRenderingOverlay: {}, showRenderPanel: {}, renderLog: {},
  renderPanel: { classList: { remove() {} }, querySelector() { return null; } }
};
const statuses = [], shown = [], updates = [];
let requests = 0;
const controller = createRenderPanelController({
  state, elements, setStatus: message => statuses.push(message), showPdf: path => shown.push(path),
  onRenderStatus: data => updates.push(data),
  api: () => { requests++; return new Promise((resolve, reject) => { resolvePoll = resolve; rejectPoll = reject; }); }
});
controller.initJobStream();
stream.onopen();
assert.equal(requests, 1);
const completed = { job_id: "job", operation: "render", current: "a.qmd", resource: "a.qmd",
  running: false, ok: TERMINAL_OK, pdf: TERMINAL_OK ? "a.pdf" : null,
  message: TERMINAL_OK ? "Fertig" : "Fehlgeschlagen", updated: 2 };
const late = SCENARIO;
const expectedUpdates = [completed];
if (late === "fresh-poll" || late === "clock-rollback") {
  completed.updated = late === "clock-rollback" ? 1 : 3;
  const progress = { ...completed, running: true, ok: null, pdf: null, message: "Zwischenschritt", updated: 2 };
  stream.onmessage({ data: JSON.stringify(progress) });
  expectedUpdates.unshift(progress);
  resolvePoll(completed);
} else if (late === "sse-running") {
  resolvePoll(completed);
  for (let i = 0; i < 10; i++) await Promise.resolve();
  stream.onmessage({ data: JSON.stringify({ ...completed, running: true, ok: null, message: "Läuft", updated: 1 }) });
} else {
  stream.onmessage({ data: JSON.stringify(completed) });
  if (late === "retryable-error" || late === "not-found") {
  rejectPoll(Object.assign(new Error("Alter Anfragefehler"), { status: late === "not-found" ? 404 : 503, retryable: late !== "not-found" }));
  } else {
    const record = { ...completed, running: late !== "older-terminal", ok: null, pdf: null, message: "Veralteter Status", updated: late === "newer-running" ? 3 : 1 };
    if (late === "no-timestamp") delete record.updated;
    resolvePoll(record);
  }
}
for (let i = 0; i < 10; i++) await Promise.resolve();
assert.equal(statuses.at(-1), completed.message);
assert.equal(elements.pdfRenderingOverlay.hidden, true);
assert.deepEqual(shown, completed.ok ? ["a.pdf"] : []);
assert.deepEqual(updates, expectedUpdates);
assert.equal(timers.size, 0, "Abgeschlossene Jobs dürfen keinen Poll-/Retry-Timer erhalten");
// A new job in the same document must still be accepted and polled normally.
state.renderJob = "next";
const nextPoll = controller.pollRender();
resolvePoll({ job_id: "next", current: "a.qmd", running: true, message: "Neuer Render", updated: 3 });
await nextPoll;
assert.equal(elements.pdfRenderingOverlay.hidden, false);
assert.equal(statuses.at(-1), "Neuer Render");
assert.equal([...timers.values()][0].delay, 15000);
'''.replace("MODULE", json.dumps(module)).replace("SCENARIO", json.dumps(late_response)).replace("TERMINAL_OK", json.dumps(terminal_ok))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_stale_running_poll_does_not_stop_fallback_polling():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js fehlt")
    module = (Path(__file__).resolve().parents[1] / "material_ui/static/render-panel.js").as_uri()
    script = r'''
import assert from "node:assert/strict";
import { createRenderPanelController } from MODULE;
const timers = [];
globalThis.setTimeout = (callback, delay) => { timers.push(delay); return 1; };
globalThis.clearTimeout = () => {};
const state = { qmdPath: "a.qmd", session: 1, renderJob: "job", pollFailures: {} };
const elements = { pdfRenderingOverlay: {}, renderPanel: { classList: { remove() {} }, querySelector() { return null; } }, renderLog: {} };
const statuses = [];
const latest = { current: "a.qmd", job_id: "job", running: true, message: "Neuer Fortschritt", updated: 2 };
const controller = createRenderPanelController({ state, elements, setStatus: message => statuses.push(message),
  api: async () => ({ ...latest, message: "Alter Fortschritt", updated: 1 }) });
controller.applyRenderStatus(latest);
await controller.pollRender();
assert.equal(statuses.at(-1), "Neuer Fortschritt");
assert.equal(elements.pdfRenderingOverlay.hidden, false);
assert.deepEqual(timers, [900]);
'''.replace("MODULE", json.dumps(module))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_concurrent_render_polls_keep_one_timer_and_stop_at_completion():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js fehlt")
    module = (Path(__file__).resolve().parents[1] / "material_ui/static/render-panel.js").as_uri()
    script = r'''
import assert from "node:assert/strict";
import { createRenderPanelController } from MODULE;
const timers = new Map(), responses = [];
let timerId = 0;
globalThis.setTimeout = (callback, delay) => { timers.set(++timerId, delay); return timerId; };
globalThis.clearTimeout = id => timers.delete(id);
const state = { qmdPath: "a.qmd", session: 1, renderJob: "job", pollFailures: {} };
const elements = { pdfRenderingOverlay: {}, renderPanel: { classList: { remove() {} }, querySelector() { return null; } }, renderLog: {} };
const controller = createRenderPanelController({ state, elements, setStatus() {}, showPdf() {},
  api: () => new Promise(resolve => responses.push(resolve)) });
const record = { current: "a.qmd", job_id: "job", running: true, updated: 2 };
const first = controller.pollRender(), second = controller.pollRender();
responses[1](record);
await second;
assert.equal(timers.size, 1);
responses[0]({ ...record, updated: 1 });
await first;
assert.equal(timers.size, 1, "Parallele Antworten dürfen keine zusätzlichen Timer hinterlassen");
const third = controller.pollRender(), fourth = controller.pollRender();
responses[2]({ ...record, updated: 3 });
await third;
assert.equal(timers.size, 1);
responses[3]({ ...record, updated: 4, running: false, ok: true });
await fourth;
assert.equal(timers.size, 0);
assert.equal(state.pollTimer, null);
assert.equal(elements.pdfRenderingOverlay.hidden, true);
'''.replace("MODULE", json.dumps(module))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def deck_case(tmp_path, monkeypatch):
    source = tmp_path / "slide.qmd"
    source.write_text(set_template("## Folie\n\n![](bild.svg)\n", "src/quarto/templates/slide-template.typst", "typst"))
    asset = tmp_path / "bild.svg"
    asset.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
    other = tmp_path / "other.qmd"
    other.write_text("Anderes Dokument")
    repository = DocumentRepository()
    slides = SlidesService(AppConfig(tmp_path), repository=repository)
    deck = slides.deck_path(source)
    deck.parent.mkdir(parents=True)
    deck.write_text("Altes Deck")
    sidecar = annotations_path(deck)
    sidecar.parent.mkdir()
    sidecar.write_text("Alte Anmerkungen")
    stamp = slides.source_stamp(deck)
    stamp.parent.mkdir()
    stamp.write_text('{"signature":"vorher"}')
    monkeypatch.setattr("material_ui.slides.generate_deck", lambda source, output_path: output_path.write_text("Neues Deck"))
    yield SimpleNamespace(source=source, asset=asset, other=other, repository=repository,
                          slides=slides, deck=deck, sidecar=sidecar, stamp=stamp)
    slides.close()


@pytest.mark.parametrize("phase", ["deck", "annotations", "restore-deck", "restore-annotations", "deck-lock"])
def test_deck_backup_and_rollback_allow_other_document_access(deck_case, monkeypatch, phase):
    import material_ui.slides as module
    case = deck_case
    paused, release = threading.Event(), threading.Event()
    copy, write, lock = module.atomic_copy_file, module.atomic_write_text, module.deck_lock
    failed = False

    def slow_copy(source, target):
        stop = ((phase == "deck" and source == case.deck)
                or (phase == "annotations" and source == case.sidecar)
                or (phase == "restore-deck" and target == case.deck)
                or (phase == "restore-annotations" and target == case.sidecar))
        if stop:
            paused.set()
            assert release.wait(5)
        return copy(source, target)

    def fail_stamp(path, text):
        nonlocal failed
        if phase.startswith("restore-") and path == case.stamp and not failed:
            failed = True
            raise OSError("Stempel konnte nicht geschrieben werden")
        return write(path, text)

    @contextmanager
    def observed_lock(path):
        if phase == "deck-lock":
            paused.set()
        with lock(path):
            yield

    def edit_other():
        snapshot = case.repository.read(case.other)
        case.repository.save(case.other, "Gespeicherte Änderung", snapshot["revision"])
        return case.repository.read(case.other)["text"]

    monkeypatch.setattr(module, "atomic_copy_file", slow_copy)
    monkeypatch.setattr(module, "atomic_write_text", fail_stamp)
    monkeypatch.setattr(module, "deck_lock", observed_lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with lock(case.deck) if phase == "deck-lock" else nullcontext():
            build = pool.submit(case.slides.rebuild, case.source)
            try:
                assert paused.wait(5)
                assert pool.submit(edit_other).result(timeout=2) == "Gespeicherte Änderung"
            finally:
                release.set()
        if phase.startswith("restore-"):
            with pytest.raises(OSError, match="Stempel"):
                build.result(timeout=5)
            assert case.deck.read_text() == "Altes Deck"
            assert case.sidecar.read_text() == "Alte Anmerkungen"
            assert case.stamp.read_text() == '{"signature":"vorher"}'
        else:
            deck, backup = build.result(timeout=5)
            assert deck.read_text() == "Neues Deck"
            assert backup.read_text() == "Altes Deck"
            assert annotations_path(backup).read_text() == "Alte Anmerkungen"
            assert not case.sidecar.exists()


@pytest.mark.parametrize("change", ["source", "asset", "shutdown"])
def test_changes_during_backup_prevent_deck_publication(deck_case, monkeypatch, change):
    import material_ui.slides as module
    case = deck_case
    paused, release = threading.Event(), threading.Event()
    copy = module.atomic_copy_file

    def pause_backup(source, target):
        if source == case.deck:
            paused.set()
            assert release.wait(5)
        return copy(source, target)

    def invalidate():
        if change == "source":
            case.repository.save(case.source, case.source.read_text() + "\nNeue Frage\n")
        elif change == "asset":
            case.asset.write_text(case.asset.read_text().replace('width="10"', 'width="20"'))
        else:
            case.slides.close()

    monkeypatch.setattr(module, "atomic_copy_file", pause_backup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        build = pool.submit(case.slides.rebuild, case.source)
        try:
            assert paused.wait(5)
            pool.submit(invalidate).result(timeout=2)
        finally:
            release.set()
        with pytest.raises(RuntimeError if change == "shutdown" else ValueError):
            build.result(timeout=5)
    assert case.deck.read_text() == "Altes Deck"
    assert case.sidecar.read_text() == "Alte Anmerkungen"
    assert case.stamp.read_text() == '{"signature":"vorher"}'
