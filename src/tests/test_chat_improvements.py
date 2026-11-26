"""Chat: Fehlermeldungen der CLI, Timeouts, Abbrechen, Sitzungs-Aufraeumen, Modellwahl,
sparsamer Dokumentkontext und Nutzungs-Cache."""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from material_ui import app as material_app
from material_ui.config import AppConfig
from material_ui.errors import InvalidInput
from material_ui.plugins.context import ensure_plugin_parent
from material_ui.runtime import RuntimeState

ensure_plugin_parent()

from material_ui_plugins.chat.events import ChatEvent, done_event, error_event, text_event, tool_result_event
from material_ui_plugins.chat.providers import (
    ClaudeCliProvider,
    CliChatProvider,
    CliSession,
    CodexCliProvider,
    VibeCliProvider,
)
from material_ui_plugins.chat.routes import build_document_prompt, document_digest, document_prompt
from material_ui_plugins.chat.service import ChatService

BASE_URL = "http://127.0.0.1:9999"


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    for name in ("wissen", "unterricht", "src"):
        (tmp_path / name).mkdir()
    return AppConfig(root=tmp_path)


class ScriptProvider(CliChatProvider):
    """Startet ein kleines Python-Skript statt einer echten CLI; Zeilen {"t": "..."} werden zu Text."""

    name = "script"
    script = ""

    def binary(self) -> str:
        return sys.executable

    def usage_hint(self):
        return {"kind": "link", "message": ""}

    def _build_command(self, session, text):
        return [sys.executable, "-c", self.script]

    def _parse_line(self, line, session):
        data = json.loads(line)
        return text_event(data["t"]) if "t" in data else None


def run(provider: ScriptProvider, script: str):
    provider.script = script
    return list(provider.send(provider.create_session(), "x"))


def kinds(events):
    return [event.type for event in events]


# -- Punkt 1: Fehler der CLI sichtbar machen ------------------------------------------------


def test_plain_text_error_with_exit_code_is_reported(config):
    events = run(ScriptProvider(config, lambda: BASE_URL),
                 "import sys; print('Error: Not logged in. Please run /login'); sys.exit(1)")
    assert kinds(events) == ["error"]
    assert "Not logged in" in events[0].message and "Exit 1" in events[0].message


def test_plain_text_without_answer_is_reported_even_with_exit_zero(config):
    events = run(ScriptProvider(config, lambda: BASE_URL), "print('Rate limit reached')")
    assert kinds(events) == ["error"] and "Rate limit" in events[0].message


def test_nonzero_exit_without_any_output_is_reported(config):
    events = run(ScriptProvider(config, lambda: BASE_URL), "import sys; sys.exit(3)")
    assert kinds(events) == ["error"] and "Exit 3" in events[0].message and "keine Ausgabe" in events[0].message


def test_ansi_codes_are_stripped_from_cli_errors(config):
    events = run(ScriptProvider(config, lambda: BASE_URL), "import sys; print('\\x1b[31mFehler\\x1b[0m'); sys.exit(2)")
    assert "\x1b" not in events[0].message and "Fehler" in events[0].message


def test_noise_around_a_good_answer_does_not_create_an_error(config):
    events = run(ScriptProvider(config, lambda: BASE_URL),
                 "import json; print('Warnung: veraltete Option'); print(json.dumps({'t': 'Antwort'}))")
    assert kinds(events) == ["text", "done"]


def test_an_answer_that_ended_with_done_is_not_turned_into_an_error(config):
    class Doneful(ScriptProvider):
        def _parse_line(self, line, session):
            data = json.loads(line)
            return done_event("tok") if data.get("done") else text_event(data["t"])

    events = run(Doneful(config, lambda: BASE_URL),
                 "import json,sys; print(json.dumps({'t':'ok'})); print(json.dumps({'done':1})); sys.exit(1)")
    assert kinds(events) == ["text", "done"]


# -- Punkt 2: Inaktivitaets-Timeout statt fester Gesamtzeit ------------------------------------


STREAMING = "import json,time\nfor i in range(12):\n  print(json.dumps({'t': str(i)}), flush=True); time.sleep(0.15)"


def test_streaming_answer_longer_than_idle_timeout_completes(config):
    provider = ScriptProvider(config, lambda: BASE_URL)
    provider.timeout_seconds = 0.6  # Gesamtdauer ~1,8 s, aber nie 0,6 s ohne Ausgabe
    events = run(provider, STREAMING)
    assert kinds(events) == ["text"] * 12 + ["done"]


def test_silent_process_is_stopped_by_idle_timeout(config):
    provider = ScriptProvider(config, lambda: BASE_URL)
    provider.timeout_seconds = 0.4
    started = time.monotonic()
    events = run(provider, "import time; time.sleep(30)")
    assert time.monotonic() - started < 5
    assert kinds(events) == ["error"] and "Keine Antwort seit 0.4 s" in events[0].message


def test_hard_limit_stops_even_a_streaming_process(config):
    provider = ScriptProvider(config, lambda: BASE_URL)
    provider.timeout_seconds = 5
    provider.max_seconds = 0.6
    events = run(provider, STREAMING)
    assert events[-1].type == "error" and "Zeitlimit von 0.6 s" in events[-1].message
    assert 0 < kinds(events).count("text") < 12


# -- Punkt 3: Abbrechen behaelt die Sitzung --------------------------------------------------


def test_cancel_turn_ends_the_turn_but_keeps_the_session(config):
    provider = ScriptProvider(config, lambda: BASE_URL)
    provider.timeout_seconds = 30
    provider.script = "import json,time\nprint(json.dumps({'t':'anfang'}), flush=True)\ntime.sleep(30)"
    session = provider.create_session()
    session.resume_token = "token-1"
    collected: list[ChatEvent] = []

    def consume():
        for event in provider.send(session, "x"):
            collected.append(event)

    thread = threading.Thread(target=consume)
    started = time.monotonic()
    thread.start()
    while not collected and time.monotonic() - started < 10:
        time.sleep(0.02)
    provider.cancel_turn(session)
    thread.join(10)
    assert not thread.is_alive() and time.monotonic() - started < 8
    assert kinds(collected) == ["text", "done"]
    assert session.closed is False and session.resume_token == "token-1"
    # Die naechste Runde funktioniert in derselben Sitzung.
    provider.script = "import json; print(json.dumps({'t':'weiter'}))"
    assert kinds(list(provider.send(session, "y"))) == ["text", "done"]


def test_cancel_without_running_turn_is_harmless(config):
    provider = ScriptProvider(config, lambda: BASE_URL)
    session = provider.create_session()
    provider.cancel_turn(session)
    assert session.cancelled is False


# -- Punkt 4: Werkzeugergebnisse mit Fehlerstatus -----------------------------------------------


def test_tool_result_event_carries_error_flag_in_sse():
    payload = json.loads(tool_result_event("read_file", "x", True).to_sse()[6:])
    assert payload["is_error"] is True
    assert "is_error" not in json.loads(tool_result_event("read_file", "x").to_sse()[6:])
    assert json.loads(error_event("weg", code="session_unknown").to_sse()[6:])["code"] == "session_unknown"


def test_claude_marks_failed_tool_results(config):
    provider = ClaudeCliProvider(config, lambda: BASE_URL)
    session = CliSession()
    line = json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "Boom", "is_error": True}]}})
    assert provider._parse_line(line, session).is_error is True


def test_codex_shell_commands_become_named_tool_events(config):
    provider = CodexCliProvider(config, lambda: BASE_URL)
    line = json.dumps({"type": "item.completed", "item": {
        "type": "command_execution", "command": "cat ~/.gitconfig", "aggregated_output": "nicht gefunden", "exit_code": 1}})
    call, result = provider._parse_line(line, CliSession())
    assert (call.type, call.tool, call.tool_input) == ("tool_call", "shell", "cat ~/.gitconfig")
    assert (result.type, result.tool, result.is_error, result.tool_output) == ("tool_result", "shell", True, "nicht gefunden")
    ok = json.loads(line)
    ok["item"]["exit_code"] = 0
    assert provider._parse_line(json.dumps(ok), CliSession())[1].is_error is False


# -- Punkt 6: Sitzungen laufen ab, Wiederaufnahme --------------------------------------------------


class QuietProvider:
    name = "ok"
    experimental = False

    def __init__(self):
        self.closed: list[object] = []

    def available(self):
        return True

    def usage_hint(self):
        return {"kind": "link", "message": ""}

    def create_session(self):
        return CliSession()

    def send(self, session, text):
        yield text_event(text)
        yield done_event()

    def close_session(self, session):
        self.closed.append(session)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_idle_sessions_are_closed_and_report_session_unknown(config):
    clock, provider = Clock(), QuietProvider()
    service = ChatService(config, providers=[provider], idle_seconds=60, clock=clock)
    session_id = service.create_session("ok")
    clock.now += 30
    assert service.sweep() == 0
    clock.now += 40
    assert service.sweep() == 1 and len(provider.closed) == 1
    events = list(service.send_message(session_id, "hallo"))
    assert [(e.type, e.code) for e in events] == [("error", "session_unknown")]


def test_activity_keeps_a_session_alive(config):
    clock, provider = Clock(), QuietProvider()
    service = ChatService(config, providers=[provider], idle_seconds=60, clock=clock)
    session_id = service.create_session("ok")
    for _ in range(4):
        clock.now += 40
        assert kinds(list(service.send_message(session_id, "x"))) == ["text", "done"]
    assert provider.closed == []


def test_running_turns_are_never_swept(config):
    clock, provider = Clock(), QuietProvider()
    release, started = threading.Event(), threading.Event()

    def slow_send(session, text):
        started.set()
        release.wait(5)
        yield done_event()

    provider.send = slow_send
    service = ChatService(config, providers=[provider], idle_seconds=60, clock=clock)
    session_id = service.create_session("ok")
    thread = threading.Thread(target=lambda: list(service.send_message(session_id, "x")))
    thread.start()
    assert started.wait(5)
    clock.now += 600
    assert service.sweep() == 0 and provider.closed == []
    release.set()
    thread.join(5)


def test_cancel_turn_unknown_session_and_provider_hook(config):
    provider = QuietProvider()
    calls = []
    provider.cancel_turn = lambda session: calls.append(session)
    service = ChatService(config, providers=[provider])
    assert service.cancel_turn("gibt-es-nicht") is False
    session_id = service.create_session("ok")
    assert service.cancel_turn(session_id) is True and len(calls) == 1


# -- Punkt 12: Modellwahl --------------------------------------------------------------------------


def test_models_per_provider(config):
    claude = ClaudeCliProvider(config, lambda: BASE_URL)
    assert [m["id"] for m in claude.models()] == ["sonnet", "opus", "haiku"]
    assert claude.models()[0]["label"] == "Sonnet 5.5"
    high = ClaudeCliProvider(replace(config, claude_effort="high"), lambda: BASE_URL)
    assert [e["id"] for e in high.efforts()] == ["low", "medium", "high"] and high.default_effort() == "high"
    chosen = high.create_session()
    chosen.effort = "low"
    assert high._build_command(chosen, "x")[high._build_command(chosen, "x").index("--effort") + 1] == "low"
    with pytest.raises(InvalidInput):
        high.check_effort("turbo")
    session = high.create_session()
    command = high._build_command(session, "x")
    assert command[command.index("--effort") + 1] == "high"
    assert ClaudeCliProvider(replace(config, claude_models=()), lambda: BASE_URL).models() == []
    codex = CodexCliProvider(replace(config, codex_models=("a-1", "gpt-6.1-sol")), lambda: BASE_URL)
    assert [m["id"] for m in codex.models()] == ["", "gpt-6.1-sol", "a-1"]  # Standardmodell nur einmal
    assert CodexCliProvider(config, lambda: BASE_URL).models() == []  # ein Modell = keine Wahl
    assert VibeCliProvider(config, lambda: BASE_URL).models() == []


def test_check_model_rejects_unknown_and_malicious_values(config):
    claude = ClaudeCliProvider(replace(config, claude_models=("sonnet", "--dangerously")), lambda: BASE_URL)
    assert claude.check_model("") == "sonnet" and claude.check_model(None) == "sonnet"  # Sonnet ist Standard
    assert claude.check_model("sonnet") == "sonnet"
    for value in ("opus", "sonnet; rm -rf /", "--dangerously", "../x"):
        with pytest.raises(InvalidInput):
            claude.check_model(value)


def test_model_reaches_the_command_line(config):
    claude = ClaudeCliProvider(config, lambda: BASE_URL)
    session = claude.create_session()
    assert "--model" not in claude._build_command(session, "x")
    session.model = "opus"
    command = claude._build_command(session, "x")
    assert command[command.index("--model") + 1] == "opus"
    codex = CodexCliProvider(replace(config, codex_models=("zweites",)), lambda: BASE_URL)
    chosen = CliSession(model="zweites")
    command = codex._build_command(chosen, "x")
    assert command[command.index("--model") + 1] == "zweites"
    assert codex._build_command(CliSession(), "x")[codex._build_command(CliSession(), "x").index("--model") + 1] == "gpt-6.1-sol"


def test_service_validates_model_choice(config):
    service = ChatService(config, providers=[ClaudeCliProvider(config, lambda: BASE_URL)])
    service._providers["claude"].available = lambda: True
    session_id = service.create_session("claude", "haiku")
    assert service._sessions[session_id].session.model == "haiku"
    with pytest.raises(InvalidInput):
        service.create_session("claude", "gpt-9")
    status = service.providers_status()[0]
    assert [m["id"] for m in status["models"]] == ["sonnet", "opus", "haiku"]
    plain = ChatService(config, providers=[QuietProvider()])
    with pytest.raises(InvalidInput, match="keine Modellwahl"):
        plain.create_session("ok", "irgendwas")
    assert plain.providers_status()[0]["models"] == []


# -- Punkt 10: sparsamer Dokumentkontext -------------------------------------------------------------


def test_selection_sends_only_section_and_surroundings(config):
    text = "A" * 3000 + "ZIEL" + "B" * 3000
    prompt = document_prompt(config, "Ändern", {
        "path": "unterricht/blatt.qmd", "text": text, "selection": {"start": 3000, "end": 3004}})
    assert '"text": "ZIEL"' in prompt
    assert "nicht das ganze Dokument" in prompt
    assert len(prompt) < 4500  # statt rund 6000 Zeichen Volltext
    payload = json.loads(prompt[prompt.index("{\"path\""):prompt.index("\n\nAuftrag")])
    assert len(payload["context_before"]) == 1500 and len(payload["context_after"]) == 1500
    assert "text" not in payload


def test_selection_context_handles_surrogate_pairs(config):
    prompt = document_prompt(config, "x", {
        "path": "unterricht/blatt.qmd", "text": "😀😀😀 Ziel 😀😀😀", "selection": {"start": 7, "end": 11}})
    assert '"text": "Ziel"' in prompt


def test_unchanged_document_is_not_sent_again(config):
    document = {"path": "unterricht/blatt.qmd", "text": "Gleicher Inhalt"}
    first, digest = build_document_prompt(config, "Eins", document)
    assert "Gleicher Inhalt" in first and digest == document_digest("unterricht/blatt.qmd", "Gleicher Inhalt")
    second, again = build_document_prompt(config, "Zwei", document, known_digest=digest)
    assert "Gleicher Inhalt" not in second and "unverändert" in second and again == digest
    assert "propose_document_edit" in second and "Auftrag:\nZwei" in second
    changed, new_digest = build_document_prompt(config, "Drei", {**document, "text": "Neuer Inhalt"}, known_digest=digest)
    assert "Neuer Inhalt" in changed and new_digest != digest


def test_selection_turns_never_claim_the_document_was_sent(config):
    _, digest = build_document_prompt(config, "x", {
        "path": "unterricht/blatt.qmd", "text": "Abc def", "selection": {"start": 0, "end": 3}})
    assert digest is None


def test_unchanged_document_is_still_validated(config):
    digest = document_digest("unterricht/blatt.qmd", "ü" * 100_001)
    with pytest.raises(InvalidInput):
        build_document_prompt(config, "x", {"path": "unterricht/blatt.qmd", "text": "ü" * 100_001}, known_digest=digest)


@pytest.fixture()
def chat_client(tmp_path: Path):
    (tmp_path / "wissen").mkdir()
    (tmp_path / "unterricht").mkdir()
    runtime = RuntimeState(config=AppConfig(tmp_path))
    app = material_app.create_app(runtime=runtime)
    app.config.update(TESTING=True)
    provider = QuietProvider()
    runtime.plugins.contexts["chat"].chat_service = ChatService(runtime.config, providers=[provider])
    try:
        yield app.test_client(), provider, runtime.plugins.contexts["chat"].chat_service
    finally:
        runtime.close()


def _send(client, session_id, text, document=None):
    body = {"text": text, **({"document": document} if document else {})}
    response = client.post(f"/api/chat/sessions/{session_id}/messages", json=body)
    assert response.status_code == 200
    return [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith("data: ")]


def test_route_sends_document_once_then_only_a_note(chat_client):
    client, _, _ = chat_client
    session_id = client.post("/api/chat/sessions", json={"provider": "ok"}).get_json()["session_id"]
    document = {"path": "unterricht/blatt.qmd", "text": "Aufgabe 1"}
    assert "Aufgabe 1" in _send(client, session_id, "a", document)[0]["text"]
    second = _send(client, session_id, "b", document)[0]["text"]
    assert "Aufgabe 1" not in second and "unverändert" in second
    third = _send(client, session_id, "c", {**document, "text": "Aufgabe 1 neu"})[0]["text"]
    assert "Aufgabe 1 neu" in third


def test_route_resends_document_after_a_failed_turn(chat_client):
    client, provider, service = chat_client
    session_id = client.post("/api/chat/sessions", json={"provider": "ok"}).get_json()["session_id"]
    document = {"path": "unterricht/blatt.qmd", "text": "Inhalt X"}
    _send(client, session_id, "a", document)

    def failing(session, text):
        yield error_event("kaputt")

    original = provider.send
    provider.send = failing
    _send(client, session_id, "b", document)
    provider.send = original
    assert "Inhalt X" in _send(client, session_id, "c", document)[0]["text"]


def test_route_cancel_and_model(chat_client):
    client, provider, service = chat_client
    calls = []
    provider.cancel_turn = lambda session: calls.append(session)
    session_id = client.post("/api/chat/sessions", json={"provider": "ok"}).get_json()["session_id"]
    assert client.post(f"/api/chat/sessions/{session_id}/cancel").get_json() == {"ok": True}
    assert len(calls) == 1
    assert client.post("/api/chat/sessions/unbekannt/cancel").get_json() == {"ok": False}
    assert client.post("/api/chat/sessions", json={"provider": "ok", "model": 5}).status_code == 400
    assert client.post("/api/chat/sessions", json={"provider": "ok", "model": "x"}).status_code == 400
    unknown = _send(client, "gibt-es-nicht", "hallo")
    assert unknown[0]["code"] == "session_unknown"


# -- Punkt 11: Nutzungsabfrage wird zwischengespeichert --------------------------------------------------


def test_mistral_usage_is_cached_and_failures_do_not_hammer_the_api(config, monkeypatch):
    calls = []

    class Response:
        def __init__(self, ok=True):
            self.ok = ok

        def raise_for_status(self):
            if not self.ok:
                raise httpx.ConnectError("weg")

        def json(self):
            return {"used": 10, "limit": 100}

    import httpx

    clock = Clock()
    outcomes = [Response(False), Response(True)]

    def fake_get(url, headers, timeout):
        calls.append(timeout)
        return outcomes[min(len(calls) - 1, len(outcomes) - 1)]

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = VibeCliProvider(replace(config, mistral_admin_api_key="k"), lambda: BASE_URL)
    provider._clock = clock
    assert provider.usage_hint()["kind"] == "link"
    assert provider.usage_hint()["kind"] == "link"
    assert len(calls) == 1 and calls[0] == provider.USAGE_TIMEOUT  # Fehler wird kurz gemerkt
    clock.now += provider.USAGE_ERROR_TTL + 1
    assert provider.usage_hint()["kind"] == "bar"
    assert provider.usage_hint()["kind"] == "bar" and len(calls) == 2
    clock.now += provider.USAGE_TTL + 1
    provider.usage_hint()
    assert len(calls) == 3
