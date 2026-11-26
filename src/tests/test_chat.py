from __future__ import annotations

import json
import asyncio
import shutil
import subprocess
import sys
import threading
import tomllib
from pathlib import Path
from unittest import mock

import httpx
import pytest

from material_ui import app as material_app
from material_ui.plugins.context import ensure_plugin_parent

ensure_plugin_parent()

from material_ui_plugins.chat import tools
from material_ui_plugins.chat.events import ChatEvent, done_event, error_event, text_event, tool_call_event, tool_result_event
from material_ui_plugins.chat.providers import ClaudeCliProvider, CliChatProvider, CliSession, CodexCliProvider
from material_ui_plugins.chat.service import MAX_CONCURRENT_CHAT_PROCESSES, ChatService
from material_ui_plugins.chat.routes import document_prompt
from material_ui.config import AppConfig
from material_ui.errors import InvalidInput
from material_ui.runtime import RuntimeState


# -- tools.py ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_course_runtime_prewarm(monkeypatch):
    # Chat/import tests must not download and compile unrelated H5P libraries.
    from material_ui.plugins.kurse.preview import PreviewService
    monkeypatch.setattr(PreviewService, "prewarm", lambda self: None)


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    (tmp_path / "wissen").mkdir()
    (tmp_path / "unterricht").mkdir()
    (tmp_path / "src").mkdir()
    return AppConfig(root=tmp_path)


def test_safe_knowledge_path_allows_wissen_and_unterricht(config: AppConfig):
    (config.root / "wissen" / "notiz.md").write_text("hallo", encoding="utf-8")
    (config.root / "unterricht" / "blatt.qmd").write_text("hallo", encoding="utf-8")
    assert tools.safe_knowledge_path(config, "wissen/notiz.md").name == "notiz.md"
    assert tools.safe_knowledge_path(config, "unterricht/blatt.qmd").name == "blatt.qmd"


@pytest.mark.parametrize("value", ["../etc/passwd", "/etc/passwd", "src/app.py", ".git/config"])
def test_safe_knowledge_path_rejects_escapes(config: AppConfig, value: str):
    with pytest.raises(InvalidInput):
        tools.safe_knowledge_path(config, value)


def test_read_file_returns_text_and_truncation_flag(config: AppConfig):
    target = config.root / "wissen" / "notiz.md"
    target.write_text("x" * 100, encoding="utf-8")
    result = tools.read_file(config, "wissen/notiz.md", max_bytes=10)
    assert result["truncated"] is True
    assert len(result["text"]) == 10

    result_full = tools.read_file(config, "wissen/notiz.md")
    assert result_full["truncated"] is False
    assert result_full["text"] == "x" * 100


def test_read_file_missing_file_raises(config: AppConfig):
    with pytest.raises(InvalidInput):
        tools.read_file(config, "wissen/fehlt.md")


def test_search_wissen_without_index_raises(config: AppConfig):
    with pytest.raises(InvalidInput):
        tools.search_wissen(config, "Bruch")


def test_search_wissen_finds_hits(config: AppConfig):
    index = {
        "version": 1,
        "dokumente": {
            "buch.pdf": {"seiten": ["Hier steht etwas über Bruchrechnung."], "ohne_text": 0},
        },
    }
    index_path = config.root / "build" / "material-index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(json.dumps(index), encoding="utf-8")

    treffer = tools.search_wissen(config, "Bruch")
    assert treffer[0]["pfad"] == "buch.pdf"
    assert "Bruch" in treffer[0]["ausschnitt"]


def test_search_unterricht_calls_local_search_api(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json={"results": [{"path": "a.qmd"}, {"path": "b.qmd"}]}, request=request)

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    results = tools.search_unterricht("http://127.0.0.1:8765/", "Bruch", limit=1)
    assert results == [{"path": "a.qmd"}]
    assert captured["url"] == "http://127.0.0.1:8765/api/search"
    assert captured["params"]["q"] == "Bruch"


def test_search_unterricht_raises_on_http_error(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    with pytest.raises(httpx.HTTPStatusError):
        tools.search_unterricht("http://127.0.0.1:8765", "Bruch")


# -- events.py -----------------------------------------------------------------


def test_chat_event_to_sse_omits_none_fields():
    event = text_event("hallo")
    payload = json.loads(event.to_sse().removeprefix("data: ").strip())
    assert payload == {"type": "text", "text": "hallo"}


def test_chat_event_rejects_unknown_type():
    with pytest.raises(ValueError):
        ChatEvent(type="not-a-type")


def test_event_factories_set_expected_fields():
    assert tool_call_event("search_wissen", {"query": "x"}).tool_input == {"query": "x"}
    assert tool_result_event("search_wissen", [1, 2]).tool_output == [1, 2]
    assert done_event("abc").session_id == "abc"
    assert error_event("oops").message == "oops"


# -- providers.py: ClaudeCliProvider -------------------------------------------


def test_claude_build_command_uses_session_id_on_first_call_and_resume_after(config: AppConfig):
    provider = ClaudeCliProvider(config, lambda: "http://127.0.0.1:8765")
    session = provider.create_session()
    first = provider._build_command(session, "hallo")
    assert "--session-id" in first
    assert session.resume_token is not None

    session.process = object()  # simulate: a subprocess already ran for this session
    second = provider._build_command(session, "weiter")
    assert "-r" in second
    assert session.resume_token in second


def test_claude_parse_line_text_delta():
    provider = ClaudeCliProvider.__new__(ClaudeCliProvider)
    session = CliSession()
    line = json.dumps({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "Hi"}}})
    event = provider._parse_line(line, session)
    assert event.type == "text"
    assert event.text == "Hi"


def test_claude_parse_line_skips_duplicate_assistant_text_block():
    provider = ClaudeCliProvider.__new__(ClaudeCliProvider)
    session = CliSession()
    line = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "ganzer text"}]}})
    assert provider._parse_line(line, session) is None


def test_claude_parse_line_reports_tool_use_and_result():
    provider = ClaudeCliProvider.__new__(ClaudeCliProvider)
    session = CliSession()
    tool_use = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "search_wissen", "input": {"query": "x"}}]}}
    )
    event = provider._parse_line(tool_use, session)
    assert event.type == "tool_call" and event.tool == "search_wissen"

    tool_result = json.dumps(
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}
    )
    event = provider._parse_line(tool_result, session)
    assert event.type == "tool_result" and event.tool_output == "ok"
    assert event.tool == "search_wissen"  # ueber tool_use_id aus session.tool_names aufgeloest


def test_claude_parse_line_tool_result_falls_back_to_raw_id_if_unmapped():
    provider = ClaudeCliProvider.__new__(ClaudeCliProvider)
    session = CliSession()
    tool_result = json.dumps(
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "unknown-id", "content": "ok"}]}}
    )
    event = provider._parse_line(tool_result, session)
    assert event.tool == "unknown-id"


def test_claude_parse_line_result_sets_resume_token_and_done():
    provider = ClaudeCliProvider.__new__(ClaudeCliProvider)
    session = CliSession()
    line = json.dumps({"type": "result", "session_id": "abc123", "is_error": False})
    event = provider._parse_line(line, session)
    assert event.type == "done"
    assert session.resume_token == "abc123"


def test_claude_parse_line_result_error():
    provider = ClaudeCliProvider.__new__(ClaudeCliProvider)
    session = CliSession()
    line = json.dumps({"type": "result", "is_error": True, "result": "kaputt"})
    event = provider._parse_line(line, session)
    assert event.type == "error"
    assert event.message == "kaputt"


def test_claude_available_checks_binary(monkeypatch, config: AppConfig):
    provider = ClaudeCliProvider(config, lambda: "http://127.0.0.1:8765")
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert provider.available() is False
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude")
    assert provider.available() is True


# -- service.py: ChatService ----------------------------------------------------


class FakeProvider:
    def __init__(self, name: str, available: bool = True) -> None:
        self.name = name
        self.experimental = False
        self._available = available
        self.closed_sessions: list[object] = []

    def available(self) -> bool:
        return self._available

    def usage_hint(self) -> dict:
        return {"kind": "link", "message": "ok"}

    def create_session(self) -> dict:
        return {"turns": 0}

    def send(self, session, text):
        session["turns"] += 1
        yield text_event(f"echo: {text}")
        yield done_event()

    def close_session(self, session) -> None:
        self.closed_sessions.append(session)


def test_chat_service_providers_status_reports_availability(config: AppConfig):
    service = ChatService(config, providers=[FakeProvider("ok", True), FakeProvider("down", False)])
    status = {entry["id"]: entry for entry in service.providers_status()}
    assert status["ok"]["available"] is True
    assert status["ok"]["usage_hint"] == {"kind": "link", "message": "ok"}
    assert status["down"]["available"] is False
    assert status["down"]["usage_hint"] is None


def test_chat_service_create_session_rejects_unknown_or_unavailable_provider(config: AppConfig):
    service = ChatService(config, providers=[FakeProvider("down", False)])
    with pytest.raises(InvalidInput):
        service.create_session("missing")
    with pytest.raises(InvalidInput):
        service.create_session("down")


def test_chat_service_send_message_round_trip(config: AppConfig):
    service = ChatService(config, providers=[FakeProvider("ok")])
    session_id = service.create_session("ok")
    events = list(service.send_message(session_id, "hallo"))
    assert [event.type for event in events] == ["text", "done"]
    assert events[0].text == "echo: hallo"


def test_chat_service_send_message_unknown_session_yields_error(config: AppConfig):
    service = ChatService(config, providers=[FakeProvider("ok")])
    events = list(service.send_message("does-not-exist", "hallo"))
    assert events == [error_event("Unbekannte Chat-Sitzung.", code="session_unknown")]


def test_chat_service_rejects_concurrent_turns_on_same_session(config: AppConfig):
    provider = FakeProvider("ok")
    service = ChatService(config, providers=[provider])
    session_id = service.create_session("ok")

    release = threading.Event()
    started = threading.Event()

    def slow_send(session, text):
        started.set()
        release.wait(timeout=2)
        yield done_event()

    provider.send = slow_send
    thread = threading.Thread(target=lambda: list(service.send_message(session_id, "erste")))
    thread.start()
    started.wait(timeout=2)
    events = list(service.send_message(session_id, "zweite"))
    release.set()
    thread.join(timeout=2)
    assert "läuft bereits" in events[0].message


def test_chat_service_close_session_invokes_provider_cleanup(config: AppConfig):
    provider = FakeProvider("ok")
    service = ChatService(config, providers=[provider])
    session_id = service.create_session("ok")
    service.close_session(session_id)
    assert len(provider.closed_sessions) == 1
    assert list(service.send_message(session_id, "x")) == [error_event("Unbekannte Chat-Sitzung.", code="session_unknown")]


def test_chat_service_close_closes_all_open_sessions(config: AppConfig):
    provider = FakeProvider("ok")
    service = ChatService(config, providers=[provider])
    service.create_session("ok")
    service.create_session("ok")
    service.close()
    assert len(provider.closed_sessions) == 2


# -- chat_routes.py -------------------------------------------------------------


@pytest.fixture()
def chat_client(tmp_path: Path):
    (tmp_path / "wissen").mkdir()
    (tmp_path / "unterricht").mkdir()
    runtime = RuntimeState(config=AppConfig(tmp_path))
    app = material_app.create_app(runtime=runtime)
    app.config.update(TESTING=True)
    runtime.plugins.contexts["chat"].chat_service = ChatService(runtime.config, providers=[FakeProvider("ok")])
    try:
        yield app.test_client()
    finally:
        runtime.close()


def test_chat_providers_route(chat_client):
    response = chat_client.get("/api/chat/providers")
    assert response.status_code == 200
    assert response.get_json()["providers"][0]["id"] == "ok"


def test_chat_session_and_message_round_trip(chat_client):
    created = chat_client.post("/api/chat/sessions", json={"provider": "ok"})
    assert created.status_code == 200
    session_id = created.get_json()["session_id"]

    response = chat_client.post(f"/api/chat/sessions/{session_id}/messages", json={"text": "hallo"})
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    events = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")]
    assert events[0] == {"type": "text", "text": "echo: hallo"}
    assert events[1] == {"type": "done"}

    deleted = chat_client.delete(f"/api/chat/sessions/{session_id}")
    assert deleted.status_code == 200


def test_chat_session_rejects_unknown_provider(chat_client):
    response = chat_client.post("/api/chat/sessions", json={"provider": "does-not-exist"})
    assert response.status_code == 400


class _BlockedProvider(FakeProvider):
    def restriction(self):
        return "Gesperrt: keine Dateisystem-Sandbox."


def test_chat_service_reports_blocked_providers(config: AppConfig):
    service = ChatService(config, providers=[FakeProvider("ok"), _BlockedProvider("gesperrt")])
    status = {entry["id"]: entry for entry in service.providers_status()}
    assert status["ok"]["blocked"] is None
    assert status["gesperrt"]["blocked"] == "Gesperrt: keine Dateisystem-Sandbox."
    assert status["gesperrt"]["available"] is True


def test_chat_service_refuses_sessions_for_blocked_providers(config: AppConfig):
    service = ChatService(config, providers=[_BlockedProvider("gesperrt")])
    with pytest.raises(InvalidInput, match="Sandbox"):
        service.create_session("gesperrt")
    assert service._sessions == {}


def test_chat_route_refuses_blocked_provider(chat_client):
    context = chat_client.application.extensions["material_runtime"].plugins.contexts["chat"]
    context.chat_service = ChatService(context.config, providers=[_BlockedProvider("gesperrt")])
    listed = chat_client.get("/api/chat/providers").get_json()["providers"]
    assert listed[0]["blocked"]
    response = chat_client.post("/api/chat/sessions", json={"provider": "gesperrt"})
    assert response.status_code == 400
    assert "Sandbox" in response.get_json()["error"]["message"]


def test_default_providers_block_codex_and_vibe_without_bwrap(config: AppConfig, monkeypatch):
    from material_ui_plugins.chat import sandbox

    monkeypatch.setattr(sandbox, "sandbox_available", lambda: False)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    status = {entry["id"]: entry for entry in ChatService(config).providers_status()}
    assert status["claude"]["blocked"] is None
    assert status["codex"]["blocked"] and status["mistral"]["blocked"]
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: True)
    status = {entry["id"]: entry for entry in ChatService(config).providers_status()}
    assert status["codex"]["blocked"] is None and status["mistral"]["blocked"] is None


def test_chat_message_includes_unsaved_document_context(chat_client):
    session_id = chat_client.post("/api/chat/sessions", json={"provider": "ok"}).get_json()["session_id"]
    response = chat_client.post(f"/api/chat/sessions/{session_id}/messages", json={
        "text": "Mehr Platz bei Aufgabe 1",
        "document": {"path": "unterricht/blatt.qmd", "text": "Ungespeicherter Editorinhalt"},
    })
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith("data: ")]
    assert "unterricht/blatt.qmd" in events[0]["text"]
    assert "Ungespeicherter Editorinhalt" in events[0]["text"]
    assert "propose_document_edit" in events[0]["text"]
    assert "Mehr Platz bei Aufgabe 1" in events[0]["text"]


@pytest.mark.parametrize("document", [
    {"path": "../outside.qmd", "text": "Text"},
    {"path": "src/code.py", "text": "Text"},
    {"path": "unterricht/bild.png", "text": "Text"},
    {"path": "unterricht/blatt.qmd", "text": 42},
    {"path": "unterricht/blatt.qmd", "text": "ü" * 100_001},
    {"text": "Text"},
    [],
])
def test_chat_message_rejects_invalid_document_context(chat_client, document):
    session_id = chat_client.post("/api/chat/sessions", json={"provider": "ok"}).get_json()["session_id"]
    response = chat_client.post(f"/api/chat/sessions/{session_id}/messages", json={"text": "Ändern", "document": document})
    assert response.status_code == 400


def test_chat_selection_uses_editor_offsets_for_unicode(config):
    prompt = document_prompt(config, "Ändern", {
        "path": "unterricht/blatt.qmd", "text": "😀 Aufgabe 1",
        "selection": {"start": 3, "end": 12},
    })
    assert '"selection": {"start": 3, "end": 12, "text": "Aufgabe 1"}' in prompt
    assert "ausschließlich diesen Abschnitt" in prompt


@pytest.mark.parametrize("selection", [[], {}, {"start": -1, "end": 2},
    {"start": 3, "end": 2}, {"start": 0, "end": 100},
    {"start": True, "end": 2}, {"start": 0.5, "end": 2}, {"start": 1, "end": 2}])
def test_chat_rejects_invalid_selection(config, selection):
    with pytest.raises(InvalidInput):
        document_prompt(config, "Ändern", {
            "path": "unterricht/blatt.qmd", "text": "😀 Aufgabe 1", "selection": selection,
        })


def test_chat_edits_require_matching_document_and_unique_section():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(__file__).resolve().parents[1] / "material_ui/plugins/chat/assets/chat-panel.js").as_uri()
    script = '''
import assert from "node:assert/strict";
import { applyDocumentEdit } from MODULE;
const snapshot = { path: "unterricht/blatt.qmd", text: "Aufgabe 1\\nAufgabe 2" };
const edit = { path: snapshot.path, old_text: "Aufgabe 1", new_text: "Aufgabe 1\\n\\nAntwort:" };
assert.deepEqual(applyDocumentEdit({ ...snapshot }, snapshot, edit), {
  offset: 0, text: "Aufgabe 1\\n\\nAntwort:\\nAufgabe 2"
});
assert.equal(applyDocumentEdit(snapshot, snapshot, { ...edit, new_text: "" }).text, "\\nAufgabe 2");
assert.throws(() => applyDocumentEdit({ ...snapshot, text: "Weitere Bearbeitung" }, snapshot, edit));
assert.throws(() => applyDocumentEdit({ ...snapshot, path: "anderes.qmd" }, snapshot, edit));
assert.throws(() => applyDocumentEdit(snapshot, snapshot, { ...edit, path: "anderes.qmd" }));
assert.throws(() => applyDocumentEdit(snapshot, snapshot, { ...edit, old_text: "" }));
assert.throws(() => applyDocumentEdit(snapshot, snapshot, { ...edit, old_text: "fehlt" }));
const repeated = { ...snapshot, text: "aaa" };
assert.throws(() => applyDocumentEdit(repeated, repeated, { ...edit, old_text: "aa" }));
assert.throws(() => applyDocumentEdit(null, snapshot, edit));
const scoped = { ...snapshot, text: "Aufgabe 1 und Aufgabe 1", selection: { start: 14, end: 23 } };
assert.deepEqual(applyDocumentEdit(scoped, scoped, edit), { offset: 14, text: "Aufgabe 1 und Aufgabe 1\\n\\nAntwort:" });
assert.throws(() => applyDocumentEdit(snapshot, { ...snapshot, selection: { start: 10, end: 19 } }, edit));
assert.throws(() => applyDocumentEdit(snapshot, { ...snapshot, selection: { start: 0, end: 0 } }, edit));
'''.replace("MODULE", json.dumps(module))
    subprocess.run([node, "--input-type=module", "-e", script], check=True, capture_output=True, text=True)


def test_browser_chat_blocked_provider_is_disabled_and_not_preselected(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright

    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    (tmp_path / "wissen").mkdir()
    (tmp_path / "unterricht").mkdir()
    app = material_app.create_app(config=AppConfig(tmp_path))
    app.testing = True
    reason = "codex ist gesperrt: keine Dateisystem-Sandbox"
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            # Der gesperrte Provider steht zuerst: er darf trotzdem nicht vorausgewaehlt werden.
            page.route("**/api/chat/providers", lambda route: route.fulfill(json={"providers": [
                {"id": "codex", "available": True, "blocked": reason, "experimental": True},
                {"id": "claude", "available": True, "blocked": None},
            ]}))
            page.goto(url, wait_until="networkidle")
            page.locator("#showChat").click()
            if not page.locator("#chatProvider").is_visible():
                page.locator(".chat-settings > summary").click()
            codex = page.locator('#chatProvider option[value="codex"]')
            codex.wait_for(state="attached")
            assert codex.is_disabled()
            assert codex.get_attribute("title") == reason
            assert "gesperrt" in codex.inner_text()
            assert page.locator("#chatProvider").input_value() == "claude"
            browser.close()
    finally:
        app.extensions["material_runtime"].close()


@pytest.mark.parametrize("provider_id", ["ok", "codex"])
def test_browser_chat_applies_edit_and_supports_undo(tmp_path, provider_id):
    from test_material_ui import LiveServer, free_port, sync_playwright
    from test_material_ui_robustness import replace_editor_text

    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    folder = tmp_path / "unterricht"
    folder.mkdir()
    (tmp_path / "wissen").mkdir()
    (folder / "blatt.qmd").write_text("Aufgabe 1\nAufgabe 2", encoding="utf-8")
    app = material_app.create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('''
localStorage.setItem("material-ui:auto-render", "false");
localStorage.setItem("material-ui:auto-save", "false");
''')
            page.route("**/api/chat/providers", lambda route: route.fulfill(json={"providers": [
                {"id": "claude", "available": True}, {"id": provider_id, "available": True}
            ]}))
            sessions = []

            def create_session(route):
                sessions.append(route.request.post_data_json)
                route.fulfill(json={"session_id": "test"})

            page.route("**/api/chat/sessions", create_session)
            requests = []

            def respond(route):
                requests.append(route.request.post_data_json)
                events = [tool_call_event("mcp__wissen__propose_document_edit", {
                    "path": "unterricht/blatt.qmd", "old_text": "Aufgabe 1", "new_text": "Aufgabe 1\nAntwort: ______"
                }), done_event()]
                route.fulfill(content_type="text/event-stream", body="".join(event.to_sse() for event in events))

            page.route("**/api/chat/sessions/test/messages", respond)
            page.goto(f"{url}?path=unterricht/blatt.qmd", wait_until="networkidle")
            page.wait_for_function("window.materialEditor?.getText() === 'Aufgabe 1\\nAufgabe 2'")
            replace_editor_text(page, "Aufgabe 1\nAufgabe 2\nUngespeichert")
            page.locator(".cm-content").focus()
            page.keyboard.press("Control+Home")
            page.keyboard.press("Shift+End")
            page.locator("#showChat").click()
            if not page.locator("#chatProvider").is_visible():
                page.locator(".chat-settings > summary").click()
            page.locator("#chatProvider").select_option(provider_id)
            assert "Auswahl" in page.locator("#chatContext").inner_text()
            assert "Nur markierter Abschnitt (9 Zeichen)" in page.locator("#chatContext").get_attribute("title")
            page.locator("#chatInput").fill("Mehr Platz für Antworten")
            page.locator("#chatSend").click()
            button = page.get_by_role("button", name="Änderung übernehmen", exact=True)
            button.wait_for()
            assert sessions == [{"provider": provider_id}]
            assert requests[0]["document"] == {
                "path": "unterricht/blatt.qmd", "text": "Aufgabe 1\nAufgabe 2\nUngespeichert",
                "selection": {"start": 0, "end": 9},
            }
            assert "blatt.qmd" in page.locator("#chatContext").inner_text()
            assert "unterricht/blatt.qmd" in page.locator("#chatContext").get_attribute("title")
            button.click()
            page.wait_for_function("window.materialEditor.getText().includes('Antwort: ______')")
            page.locator(".cm-content").focus()
            page.keyboard.press("Control+z")
            page.wait_for_function("window.materialEditor.getText() === 'Aufgabe 1\\nAufgabe 2\\nUngespeichert'")
            assert (folder / "blatt.qmd").read_text(encoding="utf-8") == "Aufgabe 1\nAufgabe 2"
            browser.close()
    finally:
        app.extensions["material_runtime"].close()


def test_browser_chat_stops_process_and_starts_new_chat(tmp_path):
    from test_material_ui import LiveServer, free_port, sync_playwright

    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")

    class SlowProvider(FakeProvider):
        def create_session(self):
            return {"release": threading.Event()}

        def send(self, session, text):
            yield text_event(f"Antwort: {text}")
            if text == "Langsam":
                session["release"] = threading.Event()
                session["release"].wait(timeout=10)
            yield done_event()

        def cancel_turn(self, session):
            session["release"].set()

        def close_session(self, session):
            super().close_session(session)
            session["release"].set()

    (tmp_path / "wissen").mkdir()
    (tmp_path / "unterricht").mkdir()
    app = material_app.create_app(config=AppConfig(tmp_path))
    app.testing = True
    runtime = app.extensions["material_runtime"]
    provider = SlowProvider("ok")
    runtime.plugins.contexts["chat"].chat_service = ChatService(runtime.config, providers=[provider])
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle")
            page.locator("#showChat").click()
            if not page.locator("#chatProvider").is_visible():
                page.locator(".chat-settings > summary").click()
            page.wait_for_function("document.querySelector('#chatProvider').value === 'ok'")
            for action in ("chatStop", "chatDelete"):
                page.locator("#chatInput").fill("Langsam")
                page.locator("#chatSend").click()
                page.wait_for_function("Array.from(document.querySelectorAll('.chat-message-assistant')).some(item => item.textContent.includes('Antwort: Langsam'))")
                assert page.locator("#chatSend").is_disabled()
                page.locator(f"#{action}").click()
                page.wait_for_function("!document.querySelector('#chatSend').disabled")
                assert page.locator("#chatStop").is_disabled()
                if action == "chatStop":
                    # Abbrechen beendet nur die Runde: Verlauf und Sitzung bleiben erhalten.
                    assert "Antwort abgebrochen" in page.locator("#chatMessages").inner_text()
                    assert "Langsam" in page.locator(".chat-message-user").inner_text()
                    assert len(provider.closed_sessions) == 0
                else:
                    # "Chat loeschen" schliesst die Sitzung und entfernt den Verlauf.
                    page.wait_for_function("document.querySelectorAll('#chatMessages li').length === 0")
            assert len(provider.closed_sessions) == 1
            page.locator("#chatInput").fill("Weiter")
            page.locator("#chatSend").click()
            page.wait_for_function("document.querySelector('#chatMessages').textContent.includes('Antwort: Weiter')")
            page.wait_for_function("!document.querySelector('#chatSend').disabled")
            # "Neuer Chat" legt einen weiteren Chat an; der bisherige behaelt seine Sitzung.
            page.locator("#chatNew").click()
            page.wait_for_function("document.querySelector('#chatMessages').children.length === 0")
            assert len(provider.closed_sessions) == 1 and page.locator("#chatThread option").count() == 2
            page.locator("#chatDelete").click()  # der neue, leere Chat
            page.wait_for_function("document.querySelector('#chatMessages').textContent.includes('Antwort: Weiter')")
            pending = []
            page.route("**/api/chat/sessions", lambda route: pending.append(route))
            page.locator("#chatNew").click()
            page.wait_for_function("document.querySelector('#chatMessages').children.length === 0")
            page.locator("#chatInput").fill("Langsam")
            with page.expect_request("**/api/chat/sessions"):
                page.locator("#chatSend").click()
            # "Neuer Chat" waehrend die Sitzung noch angelegt wird: die Runde wird abgebrochen,
            # die entstehende Sitzung gehoert dem alten Chat und geht nicht verloren.
            page.locator("#chatNew").click()
            assert len(pending) == 1
            pending[0].fulfill(json={"session_id": "pending"})
            page.wait_for_function("!document.querySelector('#chatSend').disabled")
            page.wait_for_function("document.querySelector('#chatThread').options.length === 3")
            assert page.locator("#chatMessages li").count() == 0
            assert "pending" in json.dumps(json.loads(page.evaluate("localStorage.getItem('material-ui:chat-threads')")))
            browser.close()
    finally:
        runtime.close()


# -- Bugfixes aus dem Chat-Audit -------------------------------------------------


def test_codex_command_uses_stdin_model_and_per_process_mcp_config(config):
    provider = CodexCliProvider(config, lambda: "http://127.0.0.1:9999")
    session = provider.create_session()
    command = provider._build_command(session, "ü" * 200_000)
    assert provider.send_prompt_via_stdin is True
    assert command[-1] == "-"
    assert command[command.index("--model") + 1] == "gpt-6.1-sol"
    assert command[command.index("--sandbox") + 1] == "read-only"
    settings = tomllib.loads(command[command.index("-c") + 1])
    server = settings["mcp_servers"]["wissen"]
    assert server["command"] == sys.executable
    assert server["args"] == ["-m", "chat.mcp_server"]
    assert server["env"]["MATERIAL_UI_ROOT"] == str(config.root)
    assert server["env"]["MATERIAL_UI_BASE_URL"] == "http://127.0.0.1:9999"
    assert server["env"]["PYTHONPATH"]
    session.resume_token = "thread-123"
    resumed = provider._build_command(session, "Weiter")
    assert resumed[-3:] == ["resume", "thread-123", "-"]
    with mock.patch("subprocess.run") as run:
        provider._ensure_prepared()
    run.assert_not_called()


def test_codex_model_can_be_configured(config):
    from dataclasses import replace

    provider = CodexCliProvider(replace(config, codex_model="custom-model"), lambda: "http://localhost")
    command = provider._build_command(CliSession(), "Text")
    assert command[command.index("--model") + 1] == "custom-model"


def test_chat_mcp_tools_are_declared_read_only():
    from material_ui_plugins.chat.mcp_server import server

    registered = asyncio.run(server.list_tools())
    assert {tool.name for tool in registered} == {
        "search_wissen", "search_unterricht", "read_file", "propose_document_edit", "show_task_image",
        "check_document", "read_unit", "list_templates", "propose_new_document",
    }
    # Die Claude-Freigabeliste muss genau diese Werkzeuge enthalten (nichts Unbekanntes, nichts vergessen).
    from material_ui_plugins.chat.providers import ClaudeCliProvider

    allowed = {name.removeprefix("mcp__wissen__") for name in ClaudeCliProvider.MCP_TOOLS.split(",")}
    assert allowed == {tool.name for tool in registered}
    for tool in registered:
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


@pytest.mark.parametrize("serialized", [False, True])
def test_codex_mcp_events_provide_edit_arguments_and_result(serialized):
    provider = CodexCliProvider.__new__(CodexCliProvider)
    session = CliSession()
    arguments = {"path": "unterricht/blatt.qmd", "old_text": "Aufgabe 1", "new_text": "Antwort:"}
    item = {"type": "mcp_tool_call", "server": "wissen", "tool": "propose_document_edit",
            "arguments": json.dumps(arguments) if serialized else arguments}
    event = provider._parse_line(json.dumps({"type": "item.started", "item": item}), session)
    assert event == tool_call_event("propose_document_edit", arguments)
    item["result"] = {"content": [{"type": "text", "text": "Vorgeschlagen"}]}
    event = provider._parse_line(json.dumps({"type": "item.completed", "item": item}), session)
    assert event == tool_result_event("propose_document_edit", item["result"])


def test_codex_reports_mcp_errors():
    provider = CodexCliProvider.__new__(CodexCliProvider)
    events = provider._parse_line(json.dumps({"type": "item.completed", "item": {
        "type": "mcp_tool_call", "tool": "read_file", "error": {"message": "Datei fehlt"}
    }}), CliSession())
    assert events[-1] == error_event("Datei fehlt")


def test_codex_text_and_resume_token():
    provider = CodexCliProvider.__new__(CodexCliProvider)
    session = CliSession()
    assert provider._parse_line(json.dumps({"type": "thread.started", "thread_id": "thread-123"}), session) is None
    assert session.resume_token == "thread-123"
    assert provider._parse_line(json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": "Fertig"
    }}), session) == text_event("Fertig")
    assert provider._parse_line('{"type":"turn.completed"}', session) == done_event("thread-123")


def test_codex_parse_line_handles_explicit_null_msg():
    """Regression: data.get("msg", {}) lieferte None statt {} wenn der Schluessel mit Wert null vorhanden war."""
    provider = CodexCliProvider.__new__(CodexCliProvider)
    session = CliSession()
    line = json.dumps({"msg": None})
    assert provider._parse_line(line, session) is None


def test_ensure_prepared_runs_prepare_exactly_once(config: AppConfig):
    provider = ClaudeCliProvider(config, lambda: "http://127.0.0.1:8765")
    calls = []
    provider.prepare = lambda: calls.append(1)
    provider._ensure_prepared()
    provider._ensure_prepared()
    provider._ensure_prepared()
    assert len(calls) == 1


def test_claude_mcp_config_written_once_via_prepare(config: AppConfig):
    provider = ClaudeCliProvider(config, lambda: "http://127.0.0.1:8765")
    path = provider._mcp_config_path()
    assert not path.exists()
    provider._ensure_prepared()
    assert path.is_file()
    written_at = path.stat().st_mtime_ns
    provider._ensure_prepared()
    assert path.stat().st_mtime_ns == written_at


def test_send_rejects_already_closed_session(config: AppConfig, monkeypatch):
    provider = ClaudeCliProvider(config, lambda: "http://127.0.0.1:8765")
    provider.prepare = lambda: None
    session = provider.create_session()
    provider.close_session(session)

    def fail_popen(*args, **kwargs):
        raise AssertionError("Popen darf fuer eine bereits geschlossene Sitzung nicht aufgerufen werden")

    monkeypatch.setattr(subprocess, "Popen", fail_popen)
    events = list(provider.send(session, "hallo"))
    assert events == [error_event("Sitzung wurde geschlossen.")]


def test_terminate_process_suppresses_wait_timeout(config: AppConfig, monkeypatch):
    provider = ClaudeCliProvider(config, lambda: "http://127.0.0.1:8765")
    fake_process = mock.Mock()
    fake_process.poll.return_value = None
    fake_process.pid = 999999
    fake_process.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=5)
    monkeypatch.setattr("os.killpg", lambda *a, **k: None)
    provider._terminate_process(fake_process)  # darf nicht werfen


class _SleepyProvider(CliChatProvider):
    name = "sleepy"
    experimental = True
    timeout_seconds = 0.3

    def binary(self) -> str:
        return sys.executable

    def usage_hint(self):
        return {"kind": "link", "message": ""}

    def _build_command(self, session, text):
        return [sys.executable, "-c", "import time; time.sleep(5)"]

    def _parse_line(self, line, session):
        return None


def test_watchdog_timeout_yields_error_not_done(config: AppConfig):
    provider = _SleepyProvider(config, lambda: "http://127.0.0.1:8765")
    session = provider.create_session()
    events = list(provider.send(session, "hallo"))
    assert events[-1].type == "error"
    assert "Keine Antwort" in events[-1].message
    assert not any(event.type == "done" for event in events)


def test_read_file_does_not_load_more_than_requested_from_disk(config: AppConfig, monkeypatch):
    target = config.root / "wissen" / "gross.md"
    target.write_text("x" * 100, encoding="utf-8")
    real_open = Path.open
    seen_sizes = []

    class _TrackingHandle:
        def __init__(self, handle):
            self._handle = handle

        def read(self, size=-1):
            seen_sizes.append(size)
            return self._handle.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._handle.close()

    def tracking_open(self, mode="r", *args, **kwargs):
        handle = real_open(self, mode, *args, **kwargs)
        return _TrackingHandle(handle) if "b" in mode else handle

    monkeypatch.setattr(Path, "open", tracking_open)
    result = tools.read_file(config, "wissen/gross.md", max_bytes=10)
    assert result["truncated"] is True
    assert seen_sizes == [11]


def test_chat_service_rejects_requests_once_process_slots_are_exhausted(config: AppConfig):
    provider = FakeProvider("ok")
    service = ChatService(config, providers=[provider])
    for _ in range(MAX_CONCURRENT_CHAT_PROCESSES):
        service._process_slots.acquire()
    session_id = service.create_session("ok")
    events = list(service.send_message(session_id, "hallo"))
    assert "gleichzeitige" in events[0].message


@pytest.mark.parametrize("provider_name", ["ClaudeCliProvider", "CodexCliProvider", "VibeCliProvider"])
def test_mcp_import_from_sources_without_editable_install(config, monkeypatch, tmp_path, provider_name):
    import os
    from material_ui_plugins.chat import providers

    monkeypatch.delenv("PYTHONPATH", raising=False)
    provider = getattr(providers, provider_name)(config, lambda: "http://127.0.0.1:9999")
    env = provider._mcp_server_env()
    source_root = Path(material_app.__file__).resolve().parents[1]
    assert str(source_root) in env["PYTHONPATH"].split(os.pathsep)
    # Keep third-party dependencies but exclude .pth/editable-install hooks and
    # the parent's pytest path injection. Run outside the repository.
    dependencies = [p for p in sys.path if p.endswith(("site-packages", "dist-packages"))]
    code = f"import sys; sys.path.extend({dependencies!r}); import chat.mcp_server"
    completed = subprocess.run([sys.executable, "-S", "-c", code], cwd=tmp_path,
                               env=env, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
