"""Chat: Regelkontext, Konventionspruefung, Einheiten/Vorlagen/neue Dateien, Anhaenge, eigene Prompts,
Quell-PDFs und die zugehoerigen Routen."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from material_ui import app as material_app
from material_ui.config import AppConfig
from material_ui.errors import InvalidInput
from material_ui.plugins.context import ensure_plugin_parent
from material_ui.runtime import RuntimeState

ensure_plugin_parent()

from material_ui_plugins.chat import mcp_server, tools
from material_ui_plugins.chat.events import done_event, error_event, text_event
from material_ui_plugins.chat.providers import CliSession
from material_ui_plugins.chat.routes import build_chat_prompt, validated_attachments
from material_ui_plugins.chat.rules import BY_KIND, COMMON, KIND_LABELS, KINDS, kind_for_path, rules_text
from material_ui_plugins.chat.service import ChatService

SAMPLE = "---\ntitle: X\nsubtitle: Ein Untertitel\n---\n\n# 1 · Aufgabe\n\n**a)** Rechne im Heft 2+3.\n"
CLEAN = "---\ntitle: X\n---\n\n# 1 Aufgabe\n\n**a)** Rechne 2+3.\n"
WORKSHEET = "unterricht/mathematik/klasse-05/ab_test.qmd"


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    for name in ("wissen", "unterricht", "src"):
        (tmp_path / name).mkdir()
    return AppConfig(root=tmp_path)


def make_unit(config: AppConfig) -> Path:
    unit = config.root / "unterricht/mathematik/klasse-05/potenzen"
    unit.mkdir(parents=True)
    (unit / "einheit.yaml").write_text("titel: Potenzen\nklasse: 5\n", encoding="utf-8")
    (unit / "ab_test.qmd").write_text(CLEAN, encoding="utf-8")
    (unit / "slide.qmd").write_text("# Folie\n", encoding="utf-8")
    (unit / ".material-history").mkdir()
    return unit


# -- Regeln -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path,kind", [
    ("unterricht/m/ab_x.qmd", "worksheet"), ("unterricht/m/ab_mini_x.qmd", "mini"),
    ("unterricht/m/slide.qmd", "slide"), ("unterricht/m/01 slide.qmd", "slide"),
    ("unterricht/m/ab_x_loesung.qmd", "solution"), ("unterricht/m/Lösung_x.qmd", "solution"),
    ("unterricht/m/notizen.md", "other"),
])
def test_document_kind_from_path(path, kind):
    assert kind_for_path(path) == kind


def test_rules_text_contains_common_and_kind_specific_rules():
    assert set(BY_KIND) == set(KINDS) == set(KIND_LABELS)
    for kind in KINDS:
        text = rules_text(kind)
        assert text.startswith(f"Projektregeln für {KIND_LABELS[kind]}")
        assert all(rule in text for rule in COMMON)
    assert ".zusatz" in rules_text("worksheet") and ".loesung" in rules_text("solution")
    assert "HTML-Kommentar" in rules_text("slide") and "Knobelaufgabe" in rules_text("mini")
    assert ".zusatz" not in rules_text("slide")


# -- Konventionspruefung ------------------------------------------------------------------------------


def test_convention_findings_report_rule_line_and_level():
    findings = tools.convention_findings(WORKSHEET, SAMPLE)
    assert {f["code"] for f in findings} >= {"untertitel", "ueberschrift-trenner", "bearbeitungshinweis"}
    heading = next(f for f in findings if f["code"] == "ueberschrift-trenner")
    assert heading["level"] == "warning" and heading["line"] == 6
    assert tools.convention_findings(WORKSHEET, CLEAN) == []


def test_findings_are_limited():
    text = "".join(f"# {i} · Titel\n\n" for i in range(60))
    assert len(tools.convention_findings(WORKSHEET, text)) == tools.MAX_FINDINGS
    assert len(tools.convention_findings(WORKSHEET, text, limit=3)) == 3


def test_new_findings_only_reports_additions():
    before = tools.convention_findings(WORKSHEET, SAMPLE)
    assert tools.new_findings(before, before) == []
    worse = SAMPLE + "# 2 · Noch ein Titel\n"
    added = tools.new_findings(before, tools.convention_findings(WORKSHEET, worse))
    assert [f["code"] for f in added] == ["ueberschrift-trenner"]
    assert tools.new_findings([], before) == before
    assert tools.new_findings(before, []) == []


def test_check_document_validates_path_type_and_size(config):
    result = tools.check_document(config, WORKSHEET, SAMPLE)
    assert result["path"] == WORKSHEET and "Hinweis" in result["summary"]
    assert tools.check_document(config, WORKSHEET, CLEAN)["summary"] == "Keine Regelverstöße gefunden."
    for bad in ("../x.qmd", "src/x.qmd", "unterricht/bild.png", "foerderempfehlungen/a.md"):
        with pytest.raises(InvalidInput):
            tools.check_document(config, bad, "x")
    with pytest.raises(InvalidInput):
        tools.check_document(config, WORKSHEET, "ü" * 100_001)
    with pytest.raises(InvalidInput):
        tools.check_document(config, WORKSHEET, None)


# -- Einheiten ------------------------------------------------------------------------------------------------


def test_unit_folder_and_read_unit(config):
    unit = make_unit(config)
    assert tools.unit_folder(config, "unterricht/mathematik/klasse-05/potenzen/ab_test.qmd") == unit
    assert tools.unit_folder(config, "unterricht/mathematik/klasse-05/potenzen") == unit
    assert tools.unit_folder(config, "unterricht/mathematik/klasse-05/anderes/ab.qmd") is None
    data = tools.read_unit(config, "unterricht/mathematik/klasse-05/potenzen/ab_test.qmd")
    assert data["unit_path"] == "unterricht/mathematik/klasse-05/potenzen"
    assert "titel: Potenzen" in data["einheit_yaml"] and data["truncated"] is False
    assert data["files"] == ["ab_test.qmd", "slide.qmd"]  # ohne einheit.yaml und versteckte Ordner
    with pytest.raises(InvalidInput):
        tools.read_unit(config, "unterricht/mathematik/klasse-05/anderes/ab.qmd")
    with pytest.raises(InvalidInput):
        tools.read_unit(config, "../etc")


def test_read_unit_truncates_large_files(config):
    unit = make_unit(config)
    (unit / "einheit.yaml").write_text("x: " + "y" * 50_000, encoding="utf-8")
    data = tools.read_unit(config, str(unit.relative_to(config.root)))
    assert data["truncated"] is True and len(data["einheit_yaml"]) == tools.MAX_READ_BYTES


def test_unit_lookup_never_leaves_unterricht(config):
    (config.root / "einheit.yaml").write_text("titel: Wurzel\n", encoding="utf-8")
    (config.root / "unterricht/einheit.yaml").write_text("titel: Oberste\n", encoding="utf-8")
    assert tools.unit_folder(config, "unterricht/mathe/ab.qmd") is None  # unterricht/ selbst ist keine Einheit


# -- Vorlagen ----------------------------------------------------------------------------------------------------


def test_list_templates_trims_entries(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"templates": [{"id": "a", "name": "Arbeitsblatt", "kind": "ab", "internal": {"x": 1}, "path": "t/a.typst"}, "kaputt", {}],
                    "slideTemplates": [{"name": "Folie", "description": "d", "versions": [1, 2]}]}

    seen = {}
    monkeypatch.setattr(tools.httpx, "get", lambda url, timeout: seen.update(url=url) or Response())
    result = tools.list_templates("http://127.0.0.1:8765/")
    assert seen["url"] == "http://127.0.0.1:8765/api/templates"
    assert result["templates"] == [{"id": "a", "name": "Arbeitsblatt", "kind": "ab", "path": "t/a.typst"}]
    assert result["slideTemplates"] == [{"name": "Folie", "description": "d"}]


# -- Neue Dateien ---------------------------------------------------------------------------------------------------


def test_validate_new_document(config):
    make_unit(config)
    ok = "unterricht/mathematik/klasse-05/potenzen/ab_test_loesung.qmd"
    assert tools.validate_new_document(config, ok, CLEAN) == ok
    assert tools.validate_new_document(config, "unterricht/neu/ordner/ab_x.md", "x") == "unterricht/neu/ordner/ab_x.md"
    with pytest.raises(FileExistsError):
        tools.validate_new_document(config, "unterricht/mathematik/klasse-05/potenzen/ab_test.qmd", CLEAN)
    for bad in ("wissen/neu.md", "unterricht/bild.png", "unterricht/x.py", "unterricht/.versteckt/a.qmd", "unterricht/a/.a.qmd",
                "../a.qmd", "foerderempfehlungen/a.qmd", "src/a.qmd"):
        with pytest.raises(InvalidInput):
            tools.validate_new_document(config, bad, "x")
    for bad_text in ("", "   \n", None, "ü" * 100_001):
        with pytest.raises(InvalidInput):
            tools.validate_new_document(config, "unterricht/neu.qmd", bad_text)


def test_mcp_tools_wrap_errors_and_results(config, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    unit = make_unit(config)
    monkeypatch.setenv("MATERIAL_UI_ROOT", str(config.root))
    result = mcp_server.check_document(WORKSHEET, SAMPLE)
    assert result["findings"] and result["path"] == WORKSHEET
    assert mcp_server.read_unit(str(unit.relative_to(config.root)))["unit_path"].endswith("potenzen")
    proposed = mcp_server.propose_new_document("unterricht/neu/ab_neu.qmd", SAMPLE)
    assert proposed["status"] == "proposed" and proposed["findings"]
    assert not (config.root / "unterricht/neu").exists()  # der Vorschlag schreibt nichts
    for call in (lambda: mcp_server.check_document("src/x.qmd", "x"), lambda: mcp_server.read_unit("unterricht/leer"),
                 lambda: mcp_server.propose_new_document("unterricht/mathematik/klasse-05/potenzen/ab_test.qmd", CLEAN),
                 lambda: mcp_server.propose_new_document("wissen/x.md", CLEAN)):
        with pytest.raises(ToolError):
            call()


# -- Anhaenge und Prompt-Aufbau ----------------------------------------------------------------------------------------


def test_attachments_are_validated(config):
    unit = make_unit(config)
    rel = str(unit.relative_to(config.root))
    assert validated_attachments(config, None) == []
    assert validated_attachments(config, [f"{rel}/slide.qmd", f"{rel}/slide.qmd", f"{rel}/ab_test.qmd"], exclude=f"{rel}/ab_test.qmd") == [f"{rel}/slide.qmd"]
    for bad in ("nicht-vorhanden.qmd", f"{rel}/../../../../x.qmd", "src/x.qmd"):
        with pytest.raises(InvalidInput):
            validated_attachments(config, [bad])
    (unit / "bild.png").write_bytes(b"png")
    with pytest.raises(InvalidInput, match="Dateityp"):
        validated_attachments(config, [f"{rel}/bild.png"])
    with pytest.raises(InvalidInput):
        validated_attachments(config, "keine liste")
    with pytest.raises(InvalidInput):
        validated_attachments(config, [5])
    many = []
    for index in range(6):
        (unit / f"extra{index}.md").write_text("x", encoding="utf-8")
        many.append(f"{rel}/extra{index}.md")
    with pytest.raises(InvalidInput, match="Höchstens"):
        validated_attachments(config, many)


def test_prompt_contains_rules_unit_and_attachments_once_per_session(config):
    unit = make_unit(config)
    rel = str(unit.relative_to(config.root))
    document = {"path": f"{rel}/ab_test.qmd", "text": CLEAN}
    state: dict = {}
    first, commit = build_chat_prompt(config, "Los", document, [f"{rel}/slide.qmd"], state)
    assert "Projektregeln für Arbeitsblatt" in first and "check_document" in first
    assert f"Unterrichtseinheit {rel}" in first and f"{rel}/slide.qmd" in first
    assert state == {}  # erst commit() merkt sich etwas
    commit()
    assert state["rules_kinds"] == ["worksheet"] and state["unit_hint"] == rel
    second, commit = build_chat_prompt(config, "Weiter", document, None, state)
    assert "Projektregeln" not in second and "Unterrichtseinheit" not in second and "unverändert" in second
    commit()
    assert state["rules_kinds"] == ["worksheet"]  # nicht doppelt
    slide = {"path": f"{rel}/slide.qmd", "text": "# Folie"}
    third, commit = build_chat_prompt(config, "Folie", slide, None, state)
    assert "Projektregeln für Folien" in third and "Unterrichtseinheit" not in third
    commit()
    assert state["rules_kinds"] == ["worksheet", "slide"]


def test_rules_are_resent_when_a_turn_failed(config):
    unit = make_unit(config)
    document = {"path": f"{unit.relative_to(config.root)}/ab_test.qmd", "text": CLEAN}
    state: dict = {}
    build_chat_prompt(config, "a", document, None, state)  # commit wird nicht aufgerufen (Fehlerfall)
    again, _ = build_chat_prompt(config, "b", document, None, state)
    assert "Projektregeln für Arbeitsblatt" in again and "title: X" in again


def test_prompt_without_document_but_with_attachments(config):
    unit = make_unit(config)
    rel = str(unit.relative_to(config.root))
    prompt, commit = build_chat_prompt(config, "Vergleiche", None, [f"{rel}/slide.qmd"], {})
    assert f"{rel}/slide.qmd" in prompt and prompt.endswith("Auftrag:\nVergleiche")
    assert build_chat_prompt(config, "Nur Text", None, None, {})[0] == "Nur Text"
    commit()


def test_prompt_for_document_outside_a_unit_has_no_unit_hint(config):
    document = {"path": "unterricht/lose/notiz.md", "text": "Text"}
    prompt, _ = build_chat_prompt(config, "x", document, None, {})
    assert "Unterrichtseinheit" not in prompt and "Projektregeln für Material" in prompt


# -- Routen ----------------------------------------------------------------------------------------------------------


class EchoProvider:
    name = "ok"
    experimental = False

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
        pass


@pytest.fixture()
def client(tmp_path: Path):
    (tmp_path / "wissen").mkdir()
    (tmp_path / "unterricht").mkdir()
    runtime = RuntimeState(config=AppConfig(tmp_path))
    app = material_app.create_app(runtime=runtime)
    app.config.update(TESTING=True)
    runtime.plugins.contexts["chat"].chat_service = ChatService(runtime.config, providers=[EchoProvider()])
    try:
        yield app.test_client(), tmp_path
    finally:
        runtime.close()


def test_check_route_reports_new_findings_against_the_baseline(client):
    http, _ = client
    body = {"path": WORKSHEET, "text": SAMPLE + "# 2 · Neu\n", "old_text": SAMPLE}
    data = http.post("/api/chat/check", json=body).get_json()
    assert len(data["findings"]) > len(data["new"]) and [f["code"] for f in data["new"]] == ["ueberschrift-trenner"]
    without_baseline = http.post("/api/chat/check", json={"path": WORKSHEET, "text": SAMPLE}).get_json()
    assert without_baseline["new"] == without_baseline["findings"]
    assert http.post("/api/chat/check", json={"path": WORKSHEET, "text": CLEAN, "old_text": SAMPLE}).get_json()["new"] == []
    for bad in ({"path": "src/x.qmd", "text": "x"}, {"path": WORKSHEET}, {"path": WORKSHEET, "text": "x", "old_text": 5}, {"text": "x"}):
        assert http.post("/api/chat/check", json=bad).status_code == 400


def test_documents_route_creates_a_new_file_exclusively(client):
    http, root = client
    body = {"path": "unterricht/mathematik/klasse-05/neu/ab_neu_loesung.qmd", "text": SAMPLE}
    response = http.post("/api/chat/documents", json=body)
    assert response.status_code == 200
    created = response.get_json()
    assert created["path"] == body["path"] and created["findings"]  # Regelhinweise werden mitgeliefert
    assert (root / body["path"]).read_text(encoding="utf-8") == SAMPLE  # inkl. neu angelegter Ordner
    again = http.post("/api/chat/documents", json={**body, "text": "ueberschrieben"})
    assert again.status_code == 409
    assert (root / body["path"]).read_text(encoding="utf-8") == SAMPLE  # bestehende Datei bleibt unangetastet


@pytest.mark.parametrize("body", [
    {"path": "wissen/neu.md", "text": "x"}, {"path": "unterricht/x.py", "text": "x"},
    {"path": "unterricht/.versteckt/a.qmd", "text": "x"}, {"path": "../a.qmd", "text": "x"},
    {"path": "foerderempfehlungen/a.qmd", "text": "x"}, {"path": "unterricht/leer.qmd", "text": ""},
    {"path": "unterricht/a.qmd"},
])
def test_documents_route_rejects_unsafe_requests(client, body):
    http, root = client
    assert http.post("/api/chat/documents", json=body).status_code == 400
    assert not any(root.glob("unterricht/**/*.*"))  # nichts wurde geschrieben


def test_documents_route_is_visible_in_the_material_index(client):
    http, _ = client
    http.post("/api/chat/documents", json={"path": "unterricht/mathematik/klasse-05/neu/ab_neu.qmd", "text": CLEAN})
    entries = http.get("/api/qmds").get_json()
    assert "ab_neu.qmd" in json.dumps(entries)


def test_prompts_route_roundtrip_and_validation(client):
    http, _ = client
    assert http.get("/api/chat/prompts").get_json() == {"prompts": []}
    saved = http.put("/api/chat/prompts", json={"prompts": [
        {"title": " Kürzen ", "prompt": "Kürze alles", "kinds": ["slide"]}, {"title": "Alle", "prompt": "Tu etwas"}]}).get_json()
    assert saved["prompts"] == [{"title": "Kürzen", "prompt": "Kürze alles", "kinds": ["slide"]},
                                {"title": "Alle", "prompt": "Tu etwas", "kinds": []}]
    assert http.get("/api/chat/prompts").get_json() == saved
    for bad in ([{"title": "", "prompt": "x"}], [{"title": "x", "prompt": ""}], [{"title": "x" * 61, "prompt": "p"}],
                [{"title": "x", "prompt": "p" * 2001}], [{"title": "x", "prompt": "p", "kinds": ["unbekannt"]}],
                [{"title": "x", "prompt": "p", "kinds": "slide"}], ["text"], [{"title": "x", "prompt": "p"}] * 31, "keine liste"):
        assert http.put("/api/chat/prompts", json={"prompts": bad}).status_code == 400
    assert http.get("/api/chat/prompts").get_json() == saved  # fehlerhafte Eingaben aendern nichts


def test_prompts_route_ignores_a_corrupted_store(client):
    http, root = client
    http.put("/api/chat/prompts", json={"prompts": [{"title": "A", "prompt": "B"}]})
    for stored in root.rglob("chat-prompts.json"):
        stored.write_text('{"kaputt": true}', encoding="utf-8")
    assert http.get("/api/chat/prompts").get_json() == {"prompts": []}


def test_source_route_serves_only_knowledge_pdfs(client):
    http, root = client
    (root / "wissen/curriculum").mkdir()
    (root / "wissen/curriculum/abitur.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (root / "wissen/notizen.md").write_text("x", encoding="utf-8")
    (root / "unterricht/x.pdf").write_bytes(b"%PDF-1.4\n")
    ok = http.get("/api/chat/source?path=wissen/curriculum/abitur.pdf")
    assert ok.status_code == 200 and ok.mimetype == "application/pdf"
    assert ok.headers["Content-Disposition"] == "inline" and ok.data.startswith(b"%PDF")
    ranged = http.get("/api/chat/source?path=wissen/curriculum/abitur.pdf", headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206 and ranged.data == b"%PDF"
    for bad in ("wissen/notizen.md", "unterricht/x.pdf", "wissen/fehlt.pdf", "../x.pdf", "wissen/../unterricht/x.pdf", ""):
        assert http.get("/api/chat/source", query_string={"path": bad}).status_code == 400


def test_messages_route_adds_rules_attachments_and_unit_once(client):
    http, root = client
    unit = root / "unterricht/mathematik/klasse-05/potenzen"
    unit.mkdir(parents=True)
    (unit / "einheit.yaml").write_text("titel: P\n", encoding="utf-8")
    (unit / "slide.qmd").write_text("# F\n", encoding="utf-8")
    rel = "unterricht/mathematik/klasse-05/potenzen"
    session = http.post("/api/chat/sessions", json={"provider": "ok"}).get_json()["session_id"]

    def send(text, **extra):
        response = http.post(f"/api/chat/sessions/{session}/messages", json={"text": text, **extra})
        return response, [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith("data: ")]

    document = {"path": f"{rel}/ab_x.qmd", "text": CLEAN}
    _, first = send("eins", document=document, attachments=[f"{rel}/slide.qmd"])
    assert "Projektregeln für Arbeitsblatt" in first[0]["text"] and f"{rel}/slide.qmd" in first[0]["text"]
    _, second = send("zwei", document=document)
    assert "Projektregeln" not in second[0]["text"] and "unverändert" in second[0]["text"]
    bad, _ = send("drei", document=document, attachments=["src/x.qmd"])
    assert bad.status_code == 400
    bad, _ = send("vier", attachments="nein")
    assert bad.status_code == 400


# -- Render nach dem Anlegen einer neuen Datei ---------------------------------------------------------


class FakeRender:
    def __init__(self, job_id="job-1", error=None):
        self.job_id, self.error = job_id, error
        self.started = []

    @property
    def available(self):
        return True

    def start(self, path):
        self.started.append(path)
        if self.error is not None:
            raise self.error
        return self.job_id


@pytest.fixture()
def client_runtime(tmp_path: Path):
    (tmp_path / "wissen").mkdir()
    (tmp_path / "unterricht").mkdir()
    runtime = RuntimeState(config=AppConfig(tmp_path))
    app = material_app.create_app(runtime=runtime)
    app.config.update(TESTING=True)
    runtime.plugins.contexts["chat"].chat_service = ChatService(runtime.config, providers=[EchoProvider()])
    try:
        yield app.test_client(), tmp_path, runtime
    finally:
        runtime.close()


def test_documents_route_starts_render_and_reports_job(client_runtime):
    from material_ui.plugins.ports import PluginRender

    http, root, runtime = client_runtime
    fake = FakeRender()
    runtime.plugins.contexts["chat"].render = fake
    body = {"path": "unterricht/mathematik/klasse-05/neu/ab_neu.qmd", "text": CLEAN}
    response = http.post("/api/chat/documents", json=body)
    assert response.status_code == 200
    data = response.get_json()
    assert data["render"] == {"started": True, "job_id": "job-1", "reason": None}
    assert fake.started == [body["path"]]
    assert (root / body["path"]).is_file()
    # Ohne verfuegbaren Render-Dienst wird nur gemeldet, nichts gestartet.
    runtime.plugins.contexts["chat"].render = PluginRender(runtime.config, None)
    other = {"path": "unterricht/mathematik/klasse-05/neu/ab_weiter.qmd", "text": CLEAN}
    data = http.post("/api/chat/documents", json=other).get_json()
    assert data["render"]["started"] is False and "nicht verfügbar" in data["render"]["reason"]
    assert (root / other["path"]).is_file()


def test_documents_route_render_failure_does_not_block_creation(client_runtime):
    from material_ui.jobs import JobBusy

    http, root, runtime = client_runtime
    runtime.plugins.contexts["chat"].render = FakeRender(error=JobBusy("Render-Warteschlange ist voll."))
    body = {"path": "unterricht/mathematik/klasse-05/neu/ab_busy.qmd", "text": CLEAN}
    response = http.post("/api/chat/documents", json=body)
    assert response.status_code == 200
    data = response.get_json()
    assert data["render"]["started"] is False and data["render"]["job_id"] is None
    assert "Warteschlange" in data["render"]["reason"]
    assert (root / body["path"]).read_text(encoding="utf-8") == CLEAN


def test_documents_route_skips_render_for_notes(client_runtime):
    http, root, runtime = client_runtime
    fake = FakeRender()
    runtime.plugins.contexts["chat"].render = fake
    body = {"path": "unterricht/mathematik/klasse-05/neu/notiz_abc.md", "text": "# Notiz\n"}
    data = http.post("/api/chat/documents", json=body).get_json()
    assert data["render"]["started"] is False and "nicht gerendert" in data["render"]["reason"]
    assert fake.started == []
    assert (root / body["path"]).is_file()
