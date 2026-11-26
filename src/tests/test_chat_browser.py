"""Chat-Panel im Browser: Markdown, Verlauf, Modellwahl, Abbrechen, Werkzeugzeilen, Diff, Wiederaufnahme."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from material_ui import app as material_app
from material_ui.config import AppConfig
from material_ui.plugins.context import ensure_plugin_parent
from test_material_ui import LiveServer, free_port, sync_playwright

ensure_plugin_parent()

from material_ui_plugins.chat.events import ChatEvent, done_event, error_event, text_event, tool_call_event, tool_result_event
from material_ui_plugins.chat.providers import CliSession
from material_ui_plugins.chat.service import ChatService

INIT = '''
localStorage.setItem("material-ui:auto-render", "false");
localStorage.setItem("material-ui:auto-save", "false");
'''
THREADS_KEY = "material-ui:chat-threads"


def sse(*events: ChatEvent) -> str:
    return "".join(event.to_sse() for event in events)


@pytest.fixture()
def workspace(tmp_path: Path):
    (tmp_path / "wissen").mkdir()
    folder = tmp_path / "unterricht"
    folder.mkdir()
    (folder / "blatt.qmd").write_text("Aufgabe 1\nAufgabe 2", encoding="utf-8")
    (folder / "ab_blatt.qmd").write_text("Aufgabe 1\nAufgabe 2", encoding="utf-8")
    app = material_app.create_app(config=AppConfig(tmp_path))
    app.testing = True
    try:
        yield app
    finally:
        app.extensions["material_runtime"].close()


class Mock:
    """Gemockte Chat-API: zeichnet Aufrufe auf und liefert vorbereitete SSE-Antworten."""

    def __init__(self, page, providers=None, replies=None):
        self.sessions: list[dict] = []
        self.deletes: list[str] = []
        self.messages: list[tuple[str, dict]] = []
        self.replies = list(replies or [])
        providers = providers or [{"id": "claude", "available": True, "blocked": None, "models": [
            {"id": "", "label": "Standard"}, {"id": "opus", "label": "opus"}]}]
        page.route("**/api/chat/providers", lambda route: route.fulfill(json={"providers": providers}))
        page.route("**/api/chat/sessions", self._create)
        page.route("**/api/chat/sessions/*/messages", self._message)
        page.route("**/api/chat/sessions/*", self._delete)

    def _create(self, route):
        self.sessions.append(route.request.post_data_json)
        route.fulfill(json={"session_id": f"s{len(self.sessions)}"})

    def _message(self, route):
        session = route.request.url.split("/sessions/")[1].split("/")[0]
        self.messages.append((session, route.request.post_data_json))
        reply = self.replies.pop(0) if self.replies else sse(text_event("ok"), done_event())
        route.fulfill(content_type="text/event-stream", body=reply)

    def _delete(self, route):
        if route.request.method == "DELETE":
            self.deletes.append(route.request.url.rsplit("/", 1)[1])
            route.fulfill(json={"ok": True})
        else:
            route.continue_()


def open_settings(page):
    if not page.locator("#chatProvider").is_visible():
        page.locator(".chat-settings > summary").click()


def open_chat(page, url, path=None):
    page.goto(f"{url}?path={path}" if path else url, wait_until="networkidle")
    if path:
        page.wait_for_function("window.materialEditor?.getText().length > 0")
    if not page.locator("#chatDock").is_visible():
        page.locator("#showChat").click()
    page.locator("#chatProvider option").first.wait_for(state="attached")
    open_settings(page)


def send(page, text):
    page.locator("#chatInput").fill(text)
    page.locator("#chatSend").click()


@pytest.fixture()
def browser_page(workspace):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    with LiveServer(workspace, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.set_default_timeout(60_000)  # der Rechner teilt sich oft die Last mit anderen Laeufen
        page.add_init_script(INIT)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        yield page, url, workspace
        assert not errors, errors
        browser.close()


# -- Punkt 5: Markdown --------------------------------------------------------------------------------


def test_assistant_answers_are_rendered_as_safe_markdown(browser_page):
    page, url, _ = browser_page
    mock = Mock(page, replies=[sse(
        text_event("## Plan\n\n**Wichtig:** nutze `x*y`\n\n- eins\n- zwei\n\n"),
        text_event("<img src=x onerror=window.__pwned=1> und [Doku](https://example.org/a) [Böse](javascript:window.__pwned=2)"),
        done_event())])
    open_chat(page, url)
    send(page, "Hallo")
    bubble = page.locator(".chat-message-assistant")
    bubble.wait_for()
    assert bubble.locator("strong").inner_text() == "Wichtig:"
    assert bubble.locator("code").inner_text() == "x*y"
    assert bubble.locator("li").all_inner_texts() == ["eins", "zwei"]
    assert bubble.locator("h4").inner_text() == "Plan"
    link = bubble.locator("a")
    assert link.count() == 1 and link.get_attribute("href") == "https://example.org/a"
    assert link.get_attribute("rel") == "noopener noreferrer"
    assert "<img" in bubble.inner_text() and bubble.locator("img").count() == 0  # HTML bleibt Text
    assert page.evaluate("window.__pwned") is None
    assert mock.sessions == [{"provider": "claude"}]


# -- Punkt 6: Verlauf nach Neuladen, Wiederaufnahme, Neuer Chat ----------------------------------------------


def reopen(page):
    page.reload(wait_until="networkidle")
    if not page.locator("#chatDock").is_visible():
        page.locator("#showChat").click()
    page.locator("#chatProvider option").first.wait_for(state="attached")
    open_settings(page)


def stored_threads(page):
    return json.loads(page.evaluate(f"localStorage.getItem('{THREADS_KEY}')"))


def test_chats_survive_reload_and_can_be_created_switched_and_deleted(browser_page):
    page, url, _ = browser_page
    mock = Mock(page, replies=[sse(text_event("Antwort **eins**"), done_event()), sse(text_event("Antwort zwei"), done_event()),
                               sse(text_event("Weiter in Chat eins"), done_event())])
    open_chat(page, url)
    assert page.locator("#chatEmpty").is_visible()
    assert page.locator("#chatStop").is_hidden()
    send(page, "Frage eins")
    page.locator(".chat-message-assistant strong").wait_for()
    assert page.locator("#chatEmpty").is_hidden()
    saved = stored_threads(page)
    assert len(saved["threads"]) == 1 and saved["threads"][0]["sessionId"] == "s1" and saved["threads"][0]["providerId"] == "claude"
    assert [m["role"] for m in saved["threads"][0]["messages"]] == ["user", "assistant"]

    reopen(page)
    assert page.locator(".chat-message-user").inner_text() == "Frage eins"
    assert page.locator(".chat-message-assistant strong").inner_text() == "eins"
    assert "wiederhergestellt" in page.locator(".chat-message-note").first.inner_text()

    # Neuer Chat: leerer zweiter Chat, der erste bleibt samt Sitzung erhalten.
    page.locator("#chatNew").click()
    page.wait_for_function("document.querySelectorAll('#chatMessages li').length === 0")
    assert page.locator("#chatEmpty").is_visible()
    assert page.locator("#chatInput").evaluate("el => el === document.activeElement")
    assert mock.deletes == []
    assert page.locator("#chatThread option").count() == 2
    send(page, "Frage zwei")
    page.get_by_text("Antwort zwei").wait_for()
    assert len(mock.sessions) == 2 and mock.messages[-1][0] == "s2"
    assert page.locator("#chatThread option").all_inner_texts()[0].startswith("Frage zwei")  # zuletzt benutzt zuerst

    # Zurueck zum ersten Chat: Verlauf und dieselbe Sitzung.
    first = page.locator("#chatThread option", has_text="Frage eins").get_attribute("value")
    page.locator("#chatThread").select_option(first)
    assert page.locator(".chat-message-user").all_inner_texts() == ["Frage eins"]
    send(page, "Und weiter")
    page.get_by_text("Weiter in Chat eins").wait_for()
    assert mock.messages[-1][0] == "s1" and len(mock.sessions) == 2

    # Chat loeschen: Sitzung wird geschlossen, der andere Chat wird aktiv.
    page.locator("#chatDelete").click()
    page.wait_for_function("document.querySelector('#chatThread').options.length === 1")
    assert mock.deletes == ["s1"]
    assert page.locator(".chat-message-user").all_inner_texts() == ["Frage zwei"]
    reopen(page)
    assert len(stored_threads(page)["threads"]) == 1

    page.locator("#chatDelete").click()
    page.wait_for_function("document.querySelectorAll('#chatMessages li').length === 0")
    assert mock.deletes == ["s1", "s2"]
    assert page.evaluate(f"localStorage.getItem('{THREADS_KEY}')") is None  # nichts mehr zu merken


def test_old_single_chat_storage_is_migrated(browser_page):
    page, url, _ = browser_page
    Mock(page)
    page.add_init_script(
        'if (!localStorage.getItem("material-ui:chat-threads")) localStorage.setItem("material-ui:chat-state", '
        'JSON.stringify({sessionId: "alt1", providerId: "claude", model: "", messages: [{role: "user", text: "Alte Frage"}, {role: "assistant", text: "Alte Antwort"}]}));')
    open_chat(page, url)
    assert page.locator(".chat-message-user").inner_text() == "Alte Frage"
    assert page.get_by_text("Alte Antwort").is_visible()
    send(page, "Neue Frage")
    page.wait_for_function("document.querySelector('#chatSend').disabled === false")
    assert page.evaluate("localStorage.getItem('material-ui:chat-state')") is None  # altes Format ist abgeloest
    assert stored_threads(page)["threads"][0]["messages"][0]["text"] == "Alte Frage"


def test_expired_session_is_replaced_once_and_the_message_is_resent(browser_page):
    page, url, _ = browser_page
    mock = Mock(page, replies=[
        sse(error_event("Unbekannte Chat-Sitzung.", code="session_unknown")),
        sse(text_event("Jetzt klappt es"), done_event()),
    ])
    open_chat(page, url)
    send(page, "Hallo?")
    page.get_by_text("Jetzt klappt es").wait_for()
    assert len(mock.sessions) == 2
    assert [session for session, _ in mock.messages] == ["s1", "s2"]
    assert [body["text"] for _, body in mock.messages] == ["Hallo?", "Hallo?"]
    assert page.locator(".chat-message-error").count() == 0
    assert "abgelaufen" in page.locator(".chat-message-note").inner_text()
    assert page.locator(".chat-message-user").count() == 1  # Nachricht wird nicht doppelt angezeigt


def test_second_expiry_in_a_row_is_reported_instead_of_looping(browser_page):
    page, url, _ = browser_page
    gone = sse(error_event("Unbekannte Chat-Sitzung.", code="session_unknown"))
    mock = Mock(page, replies=[gone, gone, gone])
    open_chat(page, url)
    send(page, "Hallo?")
    page.wait_for_function("document.querySelector('#chatSend').disabled === false")
    assert len(mock.messages) == 2  # genau ein Wiederholungsversuch
    assert "nicht mehr verfügbar" in page.locator(".chat-message-error").inner_text()


# -- Punkt 12: Modellwahl ---------------------------------------------------------------------------------------


def test_model_select_is_sent_remembered_and_starts_a_new_session(browser_page):
    page, url, _ = browser_page
    mock = Mock(page, providers=[
        {"id": "claude", "available": True, "blocked": None, "models": [{"id": "", "label": "Standard"}, {"id": "opus", "label": "opus"}]},
        {"id": "vibe", "available": True, "blocked": None, "models": []},
    ])
    open_chat(page, url)
    model = page.locator("#chatModel")
    assert model.is_visible() and model.locator("option").all_inner_texts() == ["Standard", "opus"]
    send(page, "Eins")
    page.wait_for_function("document.querySelector('#chatSend').disabled === false")
    assert mock.sessions == [{"provider": "claude"}]  # Standard: keine Modellangabe
    model.select_option("opus")
    send(page, "Zwei")
    page.wait_for_function("document.querySelectorAll('.chat-message-assistant').length === 2")
    assert mock.sessions[-1] == {"provider": "claude", "model": "opus"}
    assert mock.deletes == ["s1"]
    assert "Modell gewechselt" in page.locator(".chat-message-note").first.inner_text()
    # Provider ohne Modellliste blendet die Auswahl aus; die Wahl bleibt je Provider gemerkt.
    page.locator("#chatProvider").select_option("vibe")
    assert page.locator("#chatModel").is_hidden()
    page.locator("#chatProvider").select_option("claude")
    assert page.locator("#chatModel").input_value() == "opus"


# -- Punkt 4 und 8: Werkzeugzeilen, Fehler, Treffer -------------------------------------------------------------------


def test_tool_lines_show_errors_builtin_marker_and_clickable_hits(browser_page):
    page, url, _ = browser_page
    hits = json.dumps([{"path": "unterricht/blatt.qmd", "title": "Potenzen", "snippet": "Aufgabe 1 …"},
                       {"path": "unterricht/bild.png", "title": "Bild"}])
    Mock(page, replies=[sse(
        tool_call_event("search_tool_functions", {"mode": "details"}), tool_result_event("search_tool_functions", {"toolCount": 1}),
        tool_call_event("mcp__wissen__search_wissen", {"query": "Potenz"}),
        tool_result_event("mcp__wissen__search_wissen", {"content": [{"type": "text", "text": "Error executing tool search_wissen: Kein Wissensindex gefunden."}]}),
        tool_call_event("shell", "cat ~/.gitconfig"), tool_result_event("shell", "nicht gefunden", True),
        tool_call_event("mcp__wissen__search_unterricht", {"query": "Potenzen"}),
        tool_result_event("mcp__wissen__search_unterricht", [{"type": "text", "text": hits}]),
        text_event("Fertig."), done_event())])
    open_chat(page, url)
    send(page, "Suche")
    page.get_by_text("Fertig.").wait_for()
    tools = page.locator(".chat-tool")
    assert tools.count() == 3  # search_tool_functions ist internes Rauschen und bleibt unsichtbar
    failed = tools.nth(0)
    assert "chat-tool-error" in failed.get_attribute("class")
    assert failed.locator(".chat-tool-status").inner_text() == "fehlgeschlagen"
    assert failed.locator("details").evaluate("el => el.open")  # Fehler ist aufgeklappt
    assert "Kein Wissensindex" in failed.inner_text()
    shell = tools.nth(1)
    assert "chat-tool-builtin" in shell.get_attribute("class") and "Shell (Sandbox)" in shell.inner_text()
    assert "chat-tool-error" in shell.get_attribute("class")
    ok = tools.nth(2)
    assert ok.locator(".chat-tool-status").inner_text() == "erledigt" and not ok.locator("details").evaluate("el => el.open")
    links = ok.locator(".chat-hit-link")
    assert links.count() == 1 and links.inner_text() == "Potenzen (unterricht/blatt.qmd)"
    assert ok.locator(".chat-hit-path").inner_text() == "Bild (unterricht/bild.png)"  # nicht oeffnbar: kein Link
    # Die Antwort steht nach den Werkzeugzeilen, nicht davor.
    order = page.locator("#chatMessages li").evaluate_all("els => els.map(e => e.className.includes('chat-tool') ? 'tool' : (e.className.includes('assistant') ? 'assistant' : 'other'))")
    assert order.index("assistant") > max(i for i, kind in enumerate(order) if kind == "tool")
    links.click()
    page.wait_for_function("window.materialEditor?.getText() === 'Aufgabe 1\\nAufgabe 2'")


# -- Punkt 7: Diff und "Alle uebernehmen" ---------------------------------------------------------------------------------


def edit_call(old, new):
    return tool_call_event("mcp__wissen__propose_document_edit", {"path": "unterricht/blatt.qmd", "old_text": old, "new_text": new})


def test_edit_proposals_show_a_diff_and_can_be_applied_all_at_once(browser_page):
    page, url, _ = browser_page
    Mock(page, replies=[sse(edit_call("Aufgabe 1", "Aufgabe 1\nAntwort: ______"), edit_call("Aufgabe 2", "Aufgabe 2 (neu)"), done_event())])
    open_chat(page, url, "unterricht/blatt.qmd")
    send(page, "Mehr Platz")
    page.locator(".chat-edit").nth(1).wait_for()
    first = page.locator(".chat-edit").first
    assert first.locator(".chat-diff-ctx").inner_text().endswith("Aufgabe 1")  # unveraenderte Zeile
    assert first.locator(".chat-diff-add").all_inner_texts() == ["+ Antwort: ______"]
    assert first.locator(".chat-diff-del").count() == 0
    second = page.locator(".chat-edit").nth(1)
    assert second.locator(".chat-diff-del").inner_text().endswith("Aufgabe 2")
    assert second.locator(".chat-diff-add").inner_text() == "+ Aufgabe 2 (neu)"
    assert first.locator(".chat-diff").is_visible()  # nicht eingeklappt
    apply_all = page.get_by_role("button", name="Alle 2 Änderungen übernehmen")
    apply_all.click()
    page.wait_for_function("window.materialEditor.getText() === 'Aufgabe 1\\nAntwort: ______\\nAufgabe 2 (neu)'")
    assert page.get_by_role("button", name="Alle 2 Änderungen übernehmen").count() == 0
    assert page.get_by_role("button", name="Änderung übernehmen").count() == 0
    assert page.locator(".chat-edit button:disabled").count() == 2


def test_single_edit_has_no_apply_all_and_apply_all_shrinks_after_individual_apply(browser_page):
    page, url, _ = browser_page
    Mock(page, replies=[sse(edit_call("Aufgabe 1", "A1"), edit_call("Aufgabe 2", "A2"), done_event())])
    open_chat(page, url, "unterricht/blatt.qmd")
    send(page, "Ändern")
    page.get_by_role("button", name="Alle 2 Änderungen übernehmen").wait_for()
    page.get_by_role("button", name="Änderung übernehmen").first.click()
    page.wait_for_function("window.materialEditor.getText() === 'A1\\nAufgabe 2'")
    assert page.get_by_role("button", name="Alle 2 Änderungen übernehmen").count() == 0  # nur noch einer offen
    page.get_by_role("button", name="Änderung übernehmen").click()
    page.wait_for_function("window.materialEditor.getText() === 'A1\\nA2'")


# -- Punkt 3: Abbrechen behaelt die Sitzung (echtes Backend) -------------------------------------------------------------------


class SlowProvider:
    name = "slow"
    experimental = False

    def __init__(self):
        self.sessions_created = 0
        self.cancelled = threading.Event()
        self.closed = 0
        self.prompts: list[str] = []
        self.hang = True

    def available(self):
        return True

    def usage_hint(self):
        return {"kind": "link", "message": ""}

    def create_session(self):
        self.sessions_created += 1
        return CliSession()

    def cancel_turn(self, session):
        self.cancelled.set()

    def close_session(self, session):
        self.closed += 1

    def send(self, session, text):
        self.prompts.append(text)
        yield text_event("Teilantwort ")
        if self.hang:
            self.hang = False
            self.cancelled.wait(20)
            yield done_event()
            return
        yield text_event("vollstaendig")
        yield done_event()


def test_stop_cancels_only_the_turn_and_keeps_the_session(workspace):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    provider = SlowProvider()
    workspace.extensions["material_runtime"].plugins.contexts["chat"].chat_service = ChatService(
        workspace.extensions["material_runtime"].config, providers=[provider])
    with LiveServer(workspace, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.set_default_timeout(60_000)
        page.add_init_script(INIT)
        open_chat(page, url)
        send(page, "Lange Frage")
        page.get_by_text("Teilantwort").wait_for()
        assert page.locator("#chatStop").is_enabled()
        page.locator("#chatStop").click()
        page.locator(".chat-message-note").filter(has_text="Antwort abgebrochen").wait_for()
        assert provider.cancelled.is_set()
        assert provider.closed == 0 and provider.sessions_created == 1
        assert "Verlauf bleibt erhalten" in page.locator(".chat-message-note").last.inner_text()
        assert page.locator(".chat-message-user").inner_text() == "Lange Frage"  # Verlauf noch da
        page.wait_for_function("document.querySelector('#chatSend').disabled === false")
        send(page, "Zweite Frage")
        page.get_by_text("vollstaendig").wait_for()
        assert provider.sessions_created == 1 and provider.closed == 0  # derselbe Verlauf, keine neue Sitzung
        assert len(provider.prompts) == 2
        browser.close()


# -- Schnellaktionen, Slash-Menue, Eingabehistorie, Anhaenge, eigene Prompts ---------------------------------------


def last_text(mock):
    return mock.messages[-1][1]["text"]


def test_quick_actions_depend_on_the_document_and_send_immediately(browser_page):
    page, url, _ = browser_page
    mock = Mock(page)
    open_chat(page, url, "unterricht/ab_blatt.qmd")
    chips = page.locator("#chatQuick .chat-chip")
    chips.first.wait_for()
    titles = chips.all_inner_texts()
    assert "Lösung erstellen" in titles and "AFB kennzeichnen" in titles and "Folien sparsamer texten" not in titles
    page.get_by_role("button", name="Lösung erstellen").click()
    page.wait_for_function("document.querySelector('#chatSend').disabled === false")
    assert "propose_new_document" in last_text(mock)  # der volle Prompt geht an das Modell ...
    assert page.locator(".chat-message-user").inner_text() == "Lösung erstellen"  # ... die Blase zeigt den Titel
    # Anderes Dokument, andere Aktionen
    open_chat(page, url, "unterricht/blatt.qmd")
    page.wait_for_function("[...document.querySelectorAll('#chatQuick .chat-chip')].some(c => c.textContent === 'Zusammenfassen')")
    assert "Lösung erstellen" not in page.locator("#chatQuick .chat-chip").all_inner_texts()


def test_slash_menu_filters_and_fills_the_input_without_sending(browser_page):
    page, url, _ = browser_page
    mock = Mock(page)
    open_chat(page, url, "unterricht/ab_blatt.qmd")
    field = page.locator("#chatInput")
    field.click()
    field.type("/")
    assert page.locator("#chatSuggest li").count() >= 3
    field.type("lös")
    options = page.locator("#chatSuggest li")
    assert options.count() == 1 and "Lösung erstellen" in options.first.inner_text()
    field.press("Enter")  # waehlt aus, sendet NICHT
    assert "propose_new_document" in field.input_value() and mock.messages == []
    assert page.locator("#chatSuggest").is_hidden()
    field.fill("/")
    page.locator("#chatSuggest li").first.wait_for()
    field.press("ArrowDown")
    assert page.locator("#chatSuggest li.active").count() == 1
    field.press("Escape")
    assert page.locator("#chatSuggest").is_hidden() and field.input_value() == "/"
    field.fill("/zzzz")
    assert page.locator("#chatSuggest").is_hidden()


def test_input_history_with_arrow_keys(browser_page):
    page, url, _ = browser_page
    Mock(page)
    open_chat(page, url)
    for text in ("Erste Frage", "Zweite Frage"):
        send(page, text)
        page.wait_for_function("document.querySelector('#chatSend').disabled === false")
    field = page.locator("#chatInput")
    field.click()
    field.press("ArrowUp")
    assert field.input_value() == "Zweite Frage"
    field.press("ArrowUp")
    assert field.input_value() == "Erste Frage"
    field.press("ArrowUp")
    assert field.input_value() == "Erste Frage"  # am Anfang der Historie
    page.evaluate("document.querySelector('#chatInput').setSelectionRange(1000, 1000)")
    field.press("ArrowDown")
    assert field.input_value() == "Zweite Frage"
    page.evaluate("document.querySelector('#chatInput').setSelectionRange(1000, 1000)")
    field.press("ArrowDown")
    assert field.input_value() == ""  # zurueck zum (leeren) Entwurf
    field.fill("Entwurf")
    field.press("Home")
    field.press("ArrowUp")
    field.press("ArrowDown")
    page.evaluate("document.querySelector('#chatInput').setSelectionRange(1000, 1000)")
    field.press("ArrowDown")
    assert field.input_value() == "Entwurf"  # der Entwurf geht nicht verloren


def test_attach_files_with_at_mentions(browser_page):
    page, url, _ = browser_page
    mock = Mock(page)
    results = {"results": [
        {"path": "unterricht/m/slide.qmd", "title": "Folien Potenzen"}, {"path": "unterricht/m/bild.png", "title": "Bild"},
        {"path": "src/x.qmd", "title": "Fremd"}, {"path": "wissen/m/notizen.md", "title": "Notizen"}]}
    page.route("**/api/search?q=*", lambda route: route.fulfill(json=results))
    open_chat(page, url, "unterricht/blatt.qmd")
    field = page.locator("#chatInput")
    field.click()
    field.type("Vergleiche mit @pot")
    options = page.locator("#chatSuggest li")
    options.first.wait_for()
    assert options.all_inner_texts() == ["Folien Potenzen unterricht/m/slide.qmd", "Notizen wissen/m/notizen.md"]  # nur erlaubte Dateien
    options.first.click()
    chip = page.locator(".chat-attachment")
    assert chip.inner_text().startswith("📎 slide.qmd") and field.input_value() == "Vergleiche mit "
    chip.locator("button").click()  # wieder entfernen
    assert page.locator("#chatAttachments").is_hidden()
    field.type("@pot")
    page.locator("#chatSuggest li").first.click()
    field.press("Enter")
    page.wait_for_function("document.querySelector('#chatSend').disabled === false")
    assert mock.messages[-1][1]["attachments"] == ["unterricht/m/slide.qmd"]
    assert page.locator("#chatAttachments").is_hidden()  # Anhaenge gelten nur fuer die eine Nachricht
    send(page, "Ohne Anhang")
    page.wait_for_function("document.querySelectorAll('.chat-message-assistant').length === 2")
    assert "attachments" not in mock.messages[-1][1]


def test_custom_prompts_are_saved_validated_and_offered_as_chips(browser_page):
    page, url, _ = browser_page
    Mock(page)
    open_chat(page, url, "unterricht/blatt.qmd")
    page.locator("#chatPromptsEditor summary").click()
    area, status = page.locator("#chatPromptsText"), page.locator("#chatPromptsStatus")
    area.fill("Ohne Strich\nFalsch [xyz] | p")
    page.locator("#chatPromptsSave").click()
    assert "Zeile 1" in status.inner_text() and "Zeile 2" in status.inner_text()
    area.fill("Meine Aktion [other] | Fasse knapp zusammen\nNur Folien [slide] | Kürze")
    page.locator("#chatPromptsSave").click()
    page.wait_for_function("document.querySelector('#chatPromptsStatus').textContent.includes('2 Prompts gespeichert')")
    chips = page.locator("#chatQuick .chat-chip").all_inner_texts()
    assert "Meine Aktion" in chips and "Nur Folien" not in chips  # nach Dokumentart gefiltert
    reopen(page)
    page.wait_for_function("[...document.querySelectorAll('#chatQuick .chat-chip')].some(c => c.textContent === 'Meine Aktion')")
    page.locator("#chatPromptsEditor summary").click()
    assert "Nur Folien [slide] | Kürze" in page.locator("#chatPromptsText").input_value()


# -- Antwortaktionen -----------------------------------------------------------------------------------------------------


def test_copy_regenerate_and_edit_question(browser_page):
    page, url, _ = browser_page
    mock = Mock(page, replies=[sse(text_event("**Erste** Antwort"), done_event()), sse(text_event("Zweite Antwort"), done_event())])
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=url)
    open_chat(page, url)
    send(page, "Meine Frage")
    page.locator(".chat-message-assistant strong").wait_for()
    page.locator(".chat-message-assistant").hover()
    page.get_by_role("button", name="Antwort kopieren").click()
    page.wait_for_function("document.querySelector('.chat-copy').textContent === 'Kopiert'")
    assert page.evaluate("navigator.clipboard.readText()") == "**Erste** Antwort"  # Rohtext, nicht das Rendering
    actions = page.locator(".chat-message-actions")
    assert actions.count() == 1
    actions.get_by_role("button", name="Frage bearbeiten").click()
    assert page.locator("#chatInput").input_value() == "Meine Frage"
    page.locator("#chatInput").fill("")
    actions.get_by_role("button", name="Neu erzeugen").click()
    page.get_by_text("Zweite Antwort").wait_for()
    assert "noch einmal neu" in last_text(mock) and "Meine Frage" in last_text(mock)
    assert page.locator(".chat-message-user").all_inner_texts() == ["Meine Frage", "Antwort neu erzeugen"]
    assert page.locator(".chat-message-actions").count() == 1  # immer nur unter der letzten Antwort


# -- Regelhinweise, neue Dateien, veraltete Vorschlaege ------------------------------------------------------------------------


def test_edit_cards_show_new_rule_findings(browser_page):
    page, url, _ = browser_page
    Mock(page, replies=[sse(edit_call_for("unterricht/ab_blatt.qmd", "Aufgabe 1", "# 1 · Aufgabe\n\nAufgabe 1"),
                            edit_call_for("unterricht/ab_blatt.qmd", "Aufgabe 2", "Aufgabe 2 (neu)"), done_event())])
    open_chat(page, url, "unterricht/ab_blatt.qmd")
    send(page, "Ändern")
    page.locator(".chat-edit").nth(1).wait_for()
    page.wait_for_function("document.querySelectorAll('.chat-findings').length === 2")
    first, second = page.locator(".chat-edit").nth(0), page.locator(".chat-edit").nth(1)
    assert "Punkt als Trenner" in first.locator(".chat-finding-warning").inner_text()
    assert "chat-edit-warning" in first.get_attribute("class")
    assert first.locator(".chat-edit-buttons").evaluate("el => el.previousElementSibling.classList.contains('chat-findings')")
    assert "Keine neuen Regelhinweise" in second.locator(".chat-findings").inner_text()
    assert "chat-edit-warning" not in second.get_attribute("class")


def edit_call_for(path, old, new):
    return tool_call_event("mcp__wissen__propose_document_edit", {"path": path, "old_text": old, "new_text": new})


def test_new_document_card_creates_the_file_and_opens_it(browser_page):
    page, url, workspace = browser_page
    text = "---\ntitle: Lösung\nsubtitle: Zu viel\n---\n\n# 1 Aufgabe\n\nLösung 1\n"
    Mock(page, replies=[sse(
        tool_call_event("mcp__wissen__propose_new_document", {"path": "unterricht/ab_blatt_loesung.qmd", "text": text}),
        tool_result_event("mcp__wissen__propose_new_document", {"status": "proposed"}), done_event())])
    open_chat(page, url, "unterricht/ab_blatt.qmd")
    send(page, "Lösung")
    card = page.locator(".chat-newdoc")
    card.wait_for()
    assert card.locator(".chat-newdoc-path").inner_text() == "unterricht/ab_blatt_loesung.qmd"
    assert "Lösung 1" in card.locator("pre").inner_text()
    page.wait_for_function("document.querySelector('.chat-newdoc .chat-findings')")
    assert "Untertitel" in card.locator(".chat-finding").first.inner_text()
    target = workspace.extensions["material_runtime"].config.root / "unterricht/ab_blatt_loesung.qmd"
    assert not target.exists()  # vor dem Klick wird nichts geschrieben
    card.get_by_role("button", name="Datei anlegen").click()
    card.get_by_role("button", name="Öffnen").wait_for()
    assert target.read_text(encoding="utf-8") == text and card.get_by_role("button", name="Angelegt").is_disabled()
    card.get_by_role("button", name="Öffnen").click()
    page.wait_for_function("window.materialEditor?.getText().includes('Lösung 1')")


def test_new_document_card_reports_rejection_and_conflicts(browser_page):
    page, url, _ = browser_page
    Mock(page, replies=[sse(
        tool_call_event("mcp__wissen__propose_new_document", {"path": "unterricht/blatt.qmd", "text": "Neu"}),
        tool_result_event("mcp__wissen__propose_new_document", "Die Datei existiert bereits: unterricht/blatt.qmd", True), done_event()),
        sse(tool_call_event("mcp__wissen__propose_new_document", {"path": "unterricht/blatt.qmd", "text": "Neu"}), done_event())])
    open_chat(page, url)
    send(page, "Anlegen")
    card = page.locator(".chat-newdoc")
    card.wait_for()
    page.wait_for_function("document.querySelector('.chat-newdoc-error')")
    assert "existiert bereits" in card.locator(".chat-newdoc-error").inner_text()
    assert card.get_by_role("button", name="Datei anlegen").is_disabled() and "chat-tool-error" in card.get_attribute("class")
    # Ohne Werkzeugfehler (Datei entstand inzwischen): der Server verweigert das Ueberschreiben
    send(page, "Nochmal")
    page.locator(".chat-newdoc").nth(1).wait_for()
    page.locator(".chat-newdoc").nth(1).get_by_role("button", name="Datei anlegen").click()
    page.locator(".chat-message-error").wait_for()
    assert "existiert bereits" in page.locator(".chat-message-error").inner_text()


def test_stale_proposal_can_be_requested_again_on_the_current_text(browser_page):
    from test_material_ui_robustness import replace_editor_text

    page, url, _ = browser_page
    mock = Mock(page, replies=[sse(edit_call_for("unterricht/blatt.qmd", "Aufgabe 1", "Aufgabe 1 neu"), done_event()),
                               sse(text_event("Neu angewendet"), done_event())])
    open_chat(page, url, "unterricht/blatt.qmd")
    send(page, "Ändern")
    button = page.get_by_role("button", name="Änderung übernehmen")
    button.wait_for()
    replace_editor_text(page, "Ganz anderer Text")  # der Editor hat sich inzwischen geaendert
    button.click()
    retry = page.get_by_role("button", name="Auf aktuellem Stand neu anfordern")
    retry.wait_for()
    assert "geändert" in page.locator(".chat-retry").inner_text()
    retry.click()
    page.get_by_text("Neu angewendet").wait_for()
    sent = mock.messages[-1][1]
    assert "propose_document_edit" in sent["text"] and "Aufgabe 1 neu" in sent["text"]
    assert sent["document"]["text"] == "Ganz anderer Text"  # mit dem aktuellen Editorinhalt
    assert page.locator(".chat-message-user").all_inner_texts() == ["Ändern", "Änderung auf dem aktuellen Stand erneut anfordern"]


# -- Datenschutz ---------------------------------------------------------------------------------------------------------------


def test_context_names_the_operator_and_confirms_before_sending_exam_material(browser_page):
    page, url, workspace = browser_page
    root = workspace.extensions["material_runtime"].config.root
    (root / "unterricht/klausuren").mkdir()
    (root / "unterricht/klausuren/ab_klausur.qmd").write_text("Geheim", encoding="utf-8")
    mock = Mock(page, replies=[sse(text_event("1"), done_event()), sse(text_event("2"), done_event())])
    open_chat(page, url, "unterricht/blatt.qmd")
    assert "Anthropic" in page.locator("#chatContext").inner_text()
    assert "Daten gehen an Anthropic" in page.locator("#chatContext").get_attribute("title")
    assert "Klausurmaterial" not in page.locator("#chatContext").inner_text()
    open_chat(page, url, "unterricht/klausuren/ab_klausur.qmd")
    assert "Klausurmaterial" in page.locator("#chatContext").inner_text()
    dialogs = []
    answers = iter([False, True])

    def on_dialog(dialog):
        dialogs.append(dialog.message)
        dialog.accept() if next(answers) else dialog.dismiss()

    page.on("dialog", on_dialog)
    send(page, "Hallo")
    assert len(dialogs) == 1 and "Anthropic" in dialogs[0] and "ab_klausur.qmd" in dialogs[0]
    assert mock.messages == [] and page.locator("#chatInput").input_value() == "Hallo"  # abgelehnt: nichts gesendet
    page.locator("#chatSend").click()
    page.wait_for_function("document.querySelector('#chatSend').disabled === false")
    assert len(dialogs) == 2 and len(mock.messages) == 1
    send(page, "Noch eine")
    page.wait_for_function("document.querySelectorAll('.chat-message-assistant').length === 2")
    assert len(dialogs) == 2  # je Chat und Datei nur einmal gefragt


# -- Quellen, Markdown, Breite ---------------------------------------------------------------------------------------------------


def test_knowledge_pdf_hits_link_to_the_pdf_page(browser_page):
    page, url, workspace = browser_page
    root = workspace.extensions["material_runtime"].config.root
    (root / "wissen/curriculum").mkdir()
    (root / "wissen/curriculum/abitur.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    hit = json.dumps({"pfad": "curriculum/abitur.pdf", "seite": 91, "ausschnitt": "…Potenziale…"})
    Mock(page, replies=[sse(tool_call_event("search_wissen", {"query": "x"}),
                            tool_result_event("search_wissen", {"content": [{"type": "text", "text": hit}]}), done_event())])
    open_chat(page, url)
    send(page, "Suche")
    link = page.locator(".chat-hit-link")
    link.wait_for()
    assert link.get_attribute("href") == "/api/chat/source?path=wissen%2Fcurriculum%2Fabitur.pdf#page=91"
    assert link.get_attribute("target") == "_blank" and "noopener" in link.get_attribute("rel")
    response = page.request.get(url + "/api/chat/source?path=wissen%2Fcurriculum%2Fabitur.pdf")
    assert response.status == 200 and response.headers["content-type"] == "application/pdf"


def test_tables_and_formulas_are_rendered(browser_page):
    page, url, _ = browser_page
    Mock(page, replies=[sse(text_event("| Basis | Potenz |\n|:--|--:|\n| 2 | $2^{10}$ |\n\nDann gilt $\\frac{a^2}{b}$ und\n\n$$x = \\sqrt{2}$$\n"), done_event())])
    open_chat(page, url)
    send(page, "Tabelle")
    bubble = page.locator(".chat-message-assistant")
    bubble.locator("table").wait_for()
    assert bubble.locator("th").all_inner_texts() == ["Basis", "Potenz"]
    assert bubble.locator("td").nth(1).locator(".chat-math sup").inner_text() == "10"
    assert bubble.locator("th").nth(1).evaluate("el => el.style.textAlign") == "right"
    assert bubble.locator(".chat-frac .chat-frac-num").inner_text() == "a2" and bubble.locator(".chat-frac-den").inner_text() == "b"
    assert bubble.locator(".chat-math-display .chat-sqrt").count() == 1
    assert bubble.locator("script, img").count() == 0


def test_chat_width_can_be_changed_with_keyboard_and_mouse_and_is_remembered(browser_page):
    page, url, _ = browser_page
    Mock(page)
    open_chat(page, url)
    width = lambda: page.evaluate("document.getElementById('workspace').style.getPropertyValue('--chat-width')")
    handle = page.locator("#chatResizer")
    assert width() == "340px" and handle.get_attribute("aria-valuenow") == "340"
    handle.focus()
    page.keyboard.press("ArrowLeft")
    assert width() == "364px"
    page.keyboard.press("Shift+ArrowLeft")
    assert width() == "444px"
    page.keyboard.press("ArrowRight")
    assert width() == "420px"
    for _ in range(20):
        page.keyboard.press("Shift+ArrowLeft")
    assert width() == "720px"  # Obergrenze
    for _ in range(20):
        page.keyboard.press("Shift+ArrowRight")
    assert width() == "280px"  # Untergrenze
    page.keyboard.press("Home")
    assert width() == "340px"
    box = handle.bounding_box()
    page.mouse.move(box["x"] + 2, box["y"] + 100)
    page.mouse.down()
    page.mouse.move(box["x"] - 98, box["y"] + 100, steps=5)
    page.mouse.up()
    dragged = int(width().removesuffix("px"))
    assert 430 <= dragged <= 450  # 100 px nach links gezogen = 100 px breiter
    reopen(page)
    assert width() == f"{dragged}px"
    page.locator("#chatResizer").dblclick()
    assert width() == "340px"
