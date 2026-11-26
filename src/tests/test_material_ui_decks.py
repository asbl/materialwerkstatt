from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from material_ui import app as material_app
from material_ui import deck_routes
from material_ui.runtime import RuntimeState, runtime_scope

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:  # pragma: no cover - depends on local test environment
    sync_playwright = None


SCENE = {
    "type": "excalidraw",
    "version": 2,
    "elements": [
        {"type": "frame", "id": "frame-1", "x": 0, "y": 0, "width": 400, "height": 200, "isDeleted": False}
    ],
    "files": {},
}


@pytest.fixture()
def deck_root(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(material_app, "ROOT", root)
    runtime = RuntimeState()
    factory = material_app.create_app

    def create_test_app():
        app = factory(runtime=runtime)
        app.config.update(TESTING=True)
        return app

    monkeypatch.setattr(material_app, "create_app", create_test_app)
    with runtime_scope(runtime):
        material_app.initialize_runtime(runtime)
        try:
            yield root
        finally:
            runtime.close()


def write_deck(path: Path, scene: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scene if scene is not None else SCENE), encoding="utf-8")
    return path


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LiveServer:
    def __init__(self, app, port: int):
        # threaded: Der Browser haelt eine Server-Event-Verbindung (/api/jobs/stream)
        # offen; ein einstrangiger Server wuerde darauf blockieren.
        self.server = make_server("127.0.0.1", port, app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.url = f"http://127.0.0.1:{port}"

    def __enter__(self):
        self.thread.start()
        return self.url

    def __exit__(self, _exc_type, _exc, _tb):
        self.server.shutdown()
        self.thread.join(timeout=5)


def test_deck_data_returns_scene(deck_root):
    write_deck(deck_root / "unterricht" / "mathe" / "deck.excalidraw")
    client = material_app.create_app().test_client()

    response = client.get("/api/deck?path=unterricht/mathe/deck.excalidraw")

    assert response.status_code == 200
    assert response.get_json()["type"] == "excalidraw"


def test_deck_data_rejects_missing_wrong_suffix_and_hidden_paths(deck_root):
    write_deck(deck_root / "unterricht" / "deck.excalidraw")
    (deck_root / "unterricht" / "notdeck.txt").write_text("x", encoding="utf-8")
    client = material_app.create_app().test_client()

    assert client.get("/api/deck?path=unterricht/fehlt.excalidraw").status_code == 404
    assert client.get("/api/deck?path=unterricht/notdeck.txt").status_code == 404
    assert client.get("/api/deck?path=unterricht/.hidden/deck.excalidraw").status_code == 404


def test_deck_save_writes_scene_and_rejects_invalid_payloads(deck_root):
    deck = write_deck(deck_root / "unterricht" / "deck.excalidraw")
    client = material_app.create_app().test_client()

    scene = json.dumps({**SCENE, "elements": [*SCENE["elements"], {"type": "freedraw", "id": "x"}]})
    response = client.post(
        "/api/deck/save", json={"path": "unterricht/deck.excalidraw", "scene": scene}
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert "freedraw" in deck.read_text(encoding="utf-8")

    assert client.post("/api/deck/save", json={"path": "unterricht/deck.excalidraw", "scene": "{nope"}).status_code == 400
    assert client.post("/api/deck/save", json={"path": "unterricht/deck.excalidraw", "scene": "{\"elements\": 5}"}).status_code == 400
    assert client.post("/api/deck/save", json={"path": "unterricht/deck.excalidraw"}).status_code == 400
    assert client.post("/api/deck/save", json={"path": "../draussen.excalidraw", "scene": scene}).status_code == 400


def test_deck_save_rejects_stale_revision(deck_root):
    deck = write_deck(deck_root / "unterricht" / "deck.excalidraw")
    client = material_app.create_app().test_client()

    loaded = client.get("/api/deck?path=unterricht/deck.excalidraw")
    stale_revision = loaded.headers["X-Material-Revision"]
    assert stale_revision

    deck.write_text(json.dumps({**SCENE, "elements": []}), encoding="utf-8")
    scene = json.dumps({**SCENE, "elements": [*SCENE["elements"], {"type": "freedraw", "id": "x"}]})
    conflict = client.post(
        "/api/deck/save",
        json={"path": "unterricht/deck.excalidraw", "scene": scene, "revision": stale_revision},
    )
    assert conflict.status_code == 409
    assert conflict.get_json()["error"]["code"] == "conflict"
    assert "freedraw" not in deck.read_text(encoding="utf-8")

    fresh = client.get("/api/deck?path=unterricht/deck.excalidraw")
    saved = client.post(
        "/api/deck/save",
        json={
            "path": "unterricht/deck.excalidraw",
            "scene": scene,
            "revision": fresh.headers["X-Material-Revision"],
        },
    )
    assert saved.status_code == 200
    assert "freedraw" in deck.read_text(encoding="utf-8")

    again = client.post(
        "/api/deck/save",
        json={"path": "unterricht/deck.excalidraw", "scene": scene, "revision": saved.get_json()["revision"]},
    )
    assert again.status_code == 200

    assert client.post(
        "/api/deck/save", json={"path": "unterricht/deck.excalidraw", "scene": scene, "revision": 5}
    ).status_code == 400


def test_present_routes_serve_built_app_with_token(deck_root, tmp_path, monkeypatch):
    client = material_app.create_app().test_client()

    empty_dist = tmp_path / "empty-dist"
    empty_dist.mkdir()
    monkeypatch.setattr(deck_routes, "PRESENT_DIST", empty_dist)
    assert client.get("/present/").status_code == 503
    assert client.get("/present/assets/app.js").status_code == 503

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><head><title>p</title></head><body></body></html>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(deck_routes, "PRESENT_DIST", dist)

    index = client.get("/present/")
    assert index.status_code == 200
    assert "window.__MATERIAL_TOKEN__" in index.get_data(as_text=True)
    assert client.get("/present/assets/app.js").status_code == 200

    body_only = tmp_path / "body-dist"
    body_only.mkdir()
    (body_only / "index.html").write_text("<html><body>x</body></html>", encoding="utf-8")
    monkeypatch.setattr(deck_routes, "PRESENT_DIST", body_only)
    fallback = client.get("/present/")
    assert fallback.status_code == 200
    assert "window.__MATERIAL_TOKEN__" in fallback.get_data(as_text=True)

    broken = tmp_path / "broken-dist"
    broken.mkdir()
    (broken / "index.html").write_text("<html>ohne schliessende Tags", encoding="utf-8")
    monkeypatch.setattr(deck_routes, "PRESENT_DIST", broken)
    assert client.get("/present/").status_code == 503


def test_folder_list_opens_present_modal_for_decks(deck_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_deck(deck_root / "unterricht" / "deck.excalidraw")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script('localStorage.setItem("material-ui:active-view", "folder"); localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")
        page.locator("#folderEntries summary[data-folder='unterricht']").click()
        button = page.locator("#folderEntries button[data-present='unterricht/deck.excalidraw']")
        page.locator("#folderEntries a[title='deck.excalidraw']").hover()
        button.wait_for(state="visible")
        button.click()
        modal = page.locator("#deckModal")
        expect(modal).to_have_class("modal open")
        frame = page.locator("#deckFrame")
        expect(frame).to_have_attribute("src", "/present/?path=unterricht%2Fdeck.excalidraw")
        # Esc verlaesst die Folienansicht bewusst nicht (siehe app.js), nur der Schliessen-Knopf.
        page.keyboard.press("Escape")
        expect(modal).to_have_class("modal open")
        page.locator("#closeDeckModalButton").click()
        expect(modal).to_have_class("modal")
        browser.close()


def test_folder_list_offers_present_button_for_linked_qmd(deck_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_deck(deck_root / "unterricht" / "mathe" / "deck.excalidraw")
    source = deck_root / "unterricht" / "mathe" / "blatt.qmd"
    source.write_text("---\ntitle: Blatt\ndeck: deck.excalidraw\n---\n\nText\n", encoding="utf-8")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script('localStorage.setItem("material-ui:active-view", "folder"); localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")
        # Die UI oeffnet das erste QMD automatisch und zeigt dessen Ordner an;
        # der Play-Button am QMD verweist auf das verknuepfte Deck.
        button = page.locator(
            "#folderEntries button[title='Verknüpftes Deck präsentieren'][data-present='unterricht/mathe/deck.excalidraw']"
        )
        page.locator("#folderEntries button[data-document='unterricht/mathe/blatt.qmd']").hover()
        button.wait_for(state="visible", timeout=10000)
        assert button.get_attribute("title") == "Verknüpftes Deck präsentieren"
        button.click()
        expect(page.locator("#deckModal")).to_have_class("modal open")
        browser.close()


def test_deck_revision_route(deck_root):
    write_deck(deck_root / "unterricht" / "deck.excalidraw")
    client = material_app.create_app().test_client()

    loaded = client.get("/api/deck?path=unterricht/deck.excalidraw")
    revision = client.get("/api/deck/revision?path=unterricht/deck.excalidraw")

    assert revision.status_code == 200
    assert revision.get_json()["revision"] == loaded.headers["X-Material-Revision"]
    assert revision.get_json()["mtime"] > 0
    assert client.get("/api/deck/revision?path=unterricht/fehlt.excalidraw").status_code == 404


def test_deck_save_archives_history_and_skips_noops(deck_root):
    deck = write_deck(deck_root / "unterricht" / "deck.excalidraw")
    client = material_app.create_app().test_client()

    scene = json.dumps({**SCENE, "elements": [*SCENE["elements"], {"type": "freedraw", "id": "x"}]})
    assert client.post("/api/deck/save", json={"path": "unterricht/deck.excalidraw", "scene": scene}).status_code == 200

    history = client.get("/api/deck/history?path=unterricht/deck.excalidraw")
    assert history.status_code == 200
    versions = history.get_json()["versions"]
    assert len(versions) == 1

    snapshot = client.get(f"/api/deck/history/{versions[0]['id']}?path=unterricht/deck.excalidraw")
    assert snapshot.status_code == 200
    assert json.loads(snapshot.get_json()["text"])["elements"] == SCENE["elements"]

    assert client.get("/api/deck/history/ungueltig?path=unterricht/deck.excalidraw").status_code == 400
    assert client.get("/api/deck/history?path=unterricht/fehlt.excalidraw").status_code == 404

    # Identischer Stand erzeugt keine weitere Version.
    assert client.post("/api/deck/save", json={"path": "unterricht/deck.excalidraw", "scene": scene}).status_code == 200
    assert len(client.get("/api/deck/history?path=unterricht/deck.excalidraw").get_json()["versions"]) == 1
    assert "freedraw" in deck.read_text(encoding="utf-8")


def test_deck_annotations_sidecar(deck_root):
    deck = write_deck(deck_root / "unterricht" / "deck.excalidraw")
    client = material_app.create_app().test_client()
    sidecar = deck.parent / ".material-annotations" / deck.name

    empty = client.get("/api/deck/annotations?path=unterricht/deck.excalidraw")
    assert empty.status_code == 200
    assert empty.get_json() == {"elements": [], "files": {}, "revision": None}

    deck_revision = client.get("/api/deck?path=unterricht/deck.excalidraw").headers["X-Material-Revision"]
    scene = json.dumps({"type": "excalidraw", "elements": [{"type": "freedraw", "id": "a1"}], "files": {}})
    saved = client.post(
        "/api/deck/annotations/save",
        json={"path": "unterricht/deck.excalidraw", "scene": scene, "deckRevision": deck_revision, "revision": None},
    )
    assert saved.status_code == 200
    assert sidecar.is_file()

    loaded = client.get("/api/deck/annotations?path=unterricht/deck.excalidraw")
    assert loaded.get_json()["elements"] == [{"type": "freedraw", "id": "a1"}]
    revision = loaded.headers["X-Material-Revision"]

    # Das Deck bleibt unberuehrt.
    assert json.loads(deck.read_text(encoding="utf-8"))["elements"] == SCENE["elements"]

    # Erwartete Revision fehlt bzw. ist veraltet -> Konflikt.
    conflict = client.post(
        "/api/deck/annotations/save",
        json={"path": "unterricht/deck.excalidraw", "scene": scene, "deckRevision": deck_revision, "revision": None},
    )
    assert conflict.status_code == 409
    assert client.post(
        "/api/deck/annotations/save",
        json={"path": "unterricht/deck.excalidraw", "scene": "{nope", "deckRevision": deck_revision, "revision": revision},
    ).status_code == 400
    assert client.post(
        "/api/deck/annotations/save",
        json={"path": "unterricht/deck.excalidraw", "scene": scene, "deckRevision": deck_revision, "revision": 5},
    ).status_code == 400

    # Deck-Speichern uebernimmt die Anmerkungen und entfernt den Sidecar.
    deck_scene = json.dumps({**SCENE, "elements": [*SCENE["elements"], {"type": "freedraw", "id": "a1"}]})
    assert client.post("/api/deck/save", json={"path": "unterricht/deck.excalidraw", "scene": deck_scene}).status_code == 200
    assert not sidecar.exists()
    assert client.get("/api/deck/annotations?path=unterricht/deck.excalidraw").get_json()["elements"] == []


def test_search_finds_deck_texts(deck_root):
    scene = {
        "type": "excalidraw",
        "elements": [
            {"type": "text", "id": "t1", "x": 0, "y": 0, "width": 10, "height": 10,
             "text": "Quadratwurzel ziehen", "isDeleted": False}
        ],
        "files": {},
    }
    write_deck(deck_root / "unterricht" / "mathe" / "klasse-07" / "wurzeln.excalidraw", scene)
    (deck_root / "unterricht" / "mathe" / "blatt.qmd").write_text(
        "---\ntitle: Blatt\n---\n\nGanz anderer Inhalt.\n", encoding="utf-8"
    )
    client = material_app.create_app().test_client()

    results = client.get("/api/search?q=quadratwurzel").get_json()["results"]
    deck_result = next((item for item in results if item["path"].endswith(".excalidraw")), None)
    assert deck_result is not None
    assert deck_result["kind"] == "Deck"
    assert deck_result["subject"] == "mathe"
    assert deck_result["grade"] == "klasse-07"
    assert "Quadratwurzel" in deck_result["snippet"]

    filtered = client.get("/api/search?q=quadratwurzel&subject=deutsch").get_json()["results"]
    assert all(not item["path"].endswith(".excalidraw") for item in filtered)
    assert client.get("/api/search?q=quadratwurzel&kind=Deck").get_json()["results"] == [deck_result]


def test_deck_frontmatter_link(deck_root):
    write_deck(deck_root / "unterricht" / "mathe" / "deck.excalidraw")
    linked = deck_root / "unterricht" / "mathe" / "blatt.qmd"
    linked.write_text("---\ntitle: Blatt\ndeck: deck.excalidraw\n---\n\nText\n", encoding="utf-8")
    broken = deck_root / "unterricht" / "mathe" / "kaputt.qmd"
    broken.write_text("---\ntitle: Kaputt\ndeck: fehlt.excalidraw\n---\n\nText\n", encoding="utf-8")
    rooted = deck_root / "organisation" / "plan.qmd"
    rooted.parent.mkdir(parents=True)
    rooted.write_text(
        "---\ntitle: Plan\ndeck: unterricht/mathe/deck.excalidraw\n---\n\nText\n", encoding="utf-8"
    )
    client = material_app.create_app().test_client()

    entries = {item["path"]: item for item in client.get("/api/qmds").get_json()["qmds"]}
    assert entries["unterricht/mathe/blatt.qmd"]["deck"] == "unterricht/mathe/deck.excalidraw"
    assert entries["unterricht/mathe/kaputt.qmd"]["deck"] == ""
    assert entries["organisation/plan.qmd"]["deck"] == "unterricht/mathe/deck.excalidraw"

    document = client.get("/api/document?path=unterricht/mathe/blatt.qmd").get_json()
    assert document["deck"] == "unterricht/mathe/deck.excalidraw"
    assert client.get("/api/document?path=organisation/plan.qmd").get_json()["deck"] == "unterricht/mathe/deck.excalidraw"


def test_present_app_material_mode_sidecar_conflict_and_history(deck_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    if not deck_routes._present_built():
        pytest.skip("Present-Build fehlt (inv deck-present)")
    deck = write_deck(deck_root / "unterricht" / "deck.excalidraw")
    sidecar = deck.parent / ".material-annotations" / deck.name

    def wait_for(predicate, timeout=10.0):
        import time as time_module

        deadline = time_module.monotonic() + timeout
        while time_module.monotonic() < deadline:
            try:
                if predicate():
                    return True
            except (OSError, ValueError):
                pass
            time_module.sleep(0.2)
        return False

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{url}/present/?path=unterricht/deck.excalidraw", wait_until="networkidle")
        page.wait_for_selector("canvas", timeout=15000)
        page.wait_for_selector("text=1 / 1", timeout=10000)

        # Anmerkungen zeichnen und separat als Sidecar speichern.
        page.mouse.move(640, 400)
        page.mouse.down()
        page.mouse.move(760, 460, steps=8)
        page.mouse.up()
        page.wait_for_timeout(400)
        expect(page.locator(".deck-dirty-dot")).to_have_count(1)
        page.get_by_title("Nur Anmerkungen separat speichern (Strg+S); das Deck bleibt unberührt").click()
        assert wait_for(lambda: sidecar.is_file()), "Sidecar wurde nicht geschrieben"
        assert wait_for(lambda: page.locator(".deck-dirty-dot").count() == 0), "Ungespeichert-Punkt bleibt nach Sidecar-Speicherung"
        assert "freedraw" not in deck.read_text(encoding="utf-8"), "Deck wurde bei Sidecar-Speicherung veraendert"

        # Externe Aenderung + Speichern in die Deck-Datei -> Konfliktdialog.
        deck.write_text(json.dumps({**SCENE, "elements": []}), encoding="utf-8")
        page.get_by_role("button", name="Weitere Werkzeuge", exact=True).click()
        page.get_by_title(
            "Anmerkungen separat speichern: nur Anmerkungen werden gespeichert, das Deck bleibt unberührt"
        ).click()
        page.wait_for_timeout(200)
        page.get_by_title("Gesamte Szene in die Deck-Datei speichern (Strg+S)").click()
        page.wait_for_selector(".deck-dialog", timeout=10000)
        assert "zwischenzeitlich geändert" in page.locator(".deck-dialog").inner_text()
        page.get_by_text("Trotzdem speichern").click()
        assert wait_for(lambda: "freedraw" in deck.read_text(encoding="utf-8")), "Konfliktueberschreibung schreibt nicht"
        assert wait_for(lambda: not sidecar.exists()), "Sidecar wurde nach Deck-Speicherung nicht entfernt"

        # Versionen: die ueberschriebene externe Fassung ist gesichert.
        page.get_by_role("button", name="Weitere Werkzeuge", exact=True).click()
        page.get_by_title("Frühere Fassungen der Deck-Datei laden").click()
        page.wait_for_selector(".deck-history-list li", timeout=10000)
        assert page.locator(".deck-history-list li").count() >= 1
        assert errors == [], str(errors[:2])
        browser.close()


def test_document_routes_accept_md_sources(deck_root):
    source = deck_root / "unterricht" / "deck.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Quelle", encoding="utf-8")
    client = material_app.create_app().test_client()

    response = client.get("/api/document?path=unterricht/deck.md")

    assert response.status_code == 200
    assert response.get_json()["text"] == "# Quelle"
    assert response.get_json()["pdf"] is None

    saved = client.post("/api/document", json={"path": "unterricht/deck.md", "text": "# Quelle neu"})
    assert saved.status_code == 200
    assert source.read_text(encoding="utf-8") == "# Quelle neu"

    assert client.get("/api/document?path=unterricht/fehlt.md").status_code == 400
    (deck_root / "unterricht" / "notiz.txt").write_text("x", encoding="utf-8")
    assert client.get("/api/document?path=unterricht/notiz.txt").status_code == 400
    assert client.get("/api/source?path=unterricht/deck.md").status_code == 200


def test_folder_list_opens_deck_source_md_in_editor(deck_root):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    write_deck(deck_root / "unterricht" / "deck.excalidraw")
    (deck_root / "unterricht" / "deck.md").write_text("# Quelle", encoding="utf-8")
    (deck_root / "unterricht" / "ohne-deck.md").write_text("# Ohne Deck", encoding="utf-8")
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.add_init_script('localStorage.setItem("material-ui:active-view", "folder"); localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until="networkidle")
        page.locator("#folderEntries summary[data-folder='unterricht']").click()
        source = page.locator("#folderEntries button[data-document='unterricht/deck.md']")
        source.wait_for(state="visible")
        source.click()
        page.wait_for_function("window.materialEditor.getText() === '# Quelle'")
        play = source.locator("xpath=..").locator("button[data-present]")
        source.hover()
        play.wait_for(state="visible")
        assert play.get_attribute("title") == "Mit der Present-App präsentieren"
        ohne = page.locator("#folderEntries button[data-document='unterricht/ohne-deck.md']")
        ohne.wait_for(state="visible")
        assert ohne.locator("xpath=..").locator("button[data-present]").count() == 0
        browser.close()


def test_presenter_keeps_old_notes_local_after_deck_rebuild(deck_root):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    if not deck_routes._present_built():
        pytest.skip('Present-Build fehlt')
    deck = write_deck(deck_root / 'unterricht/deck.excalidraw')
    sidecar = deck.parent / '.material-annotations' / deck.name
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.add_init_script('localStorage.setItem("excalideck:annotations-separate", "true")')
        page.goto(f'{url}/present/?path=unterricht/deck.excalidraw', wait_until='networkidle')
        page.wait_for_selector('canvas')
        page.wait_for_selector('text=1 / 1')
        page.mouse.move(640, 400)
        page.mouse.down()
        page.mouse.move(760, 460, steps=8)
        page.mouse.up()
        expect(page.locator('.deck-dirty-dot')).to_have_count(1)
        write_deck(deck, {**SCENE, 'elements': [{**SCENE['elements'][0], 'id': 'new-frame'}]})
        with page.expect_response(lambda response: '/api/deck/annotations/save' in response.url) as saved:
            page.keyboard.press('Control+s')
        assert saved.value.status == 409
        assert saved.value.json()['error']['code'] == 'deck_changed'
        dialog = page.get_by_role('alertdialog')
        expect(dialog).to_contain_text('Deck wurde neu gebaut oder geändert')
        expect(dialog.get_by_text('Trotzdem speichern', exact=True)).to_have_count(0)
        with page.expect_download() as downloaded:
            dialog.get_by_text('Lokale Fassung herunterladen', exact=True).click()
        scene = json.loads(Path(downloaded.value.path()).read_text())
        assert any(element['type'] == 'freedraw' for element in scene['elements'])
        expect(page.locator('.deck-dirty-dot')).to_have_count(1)
        assert not sidecar.exists()
        assert not any(element['type'] == 'freedraw' for element in json.loads(deck.read_text())['elements'])
        browser.close()


def test_presenter_annotations_survive_deck_rebuild_seamlessly(deck_root):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    if not deck_routes._present_built():
        pytest.skip('Present-Build fehlt')
    deck = write_deck(deck_root / 'unterricht/deck.excalidraw')
    sidecar = deck.parent / '.material-annotations' / deck.name
    frame = SCENE['elements'][0]

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        page.goto(f'{url}/present/?path=unterricht/deck.excalidraw', wait_until='networkidle')
        page.wait_for_selector('canvas')
        page.wait_for_selector('text=1 / 1')
        # Anmerkung zeichnen und als Sidecar sichern.
        page.mouse.move(640, 400)
        page.mouse.down()
        page.mouse.move(760, 460, steps=8)
        page.mouse.up()
        page.wait_for_timeout(400)
        expect(page.locator('.deck-dirty-dot')).to_have_count(1)
        with page.expect_response(lambda response: '/api/deck/annotations/save' in response.url) as saved:
            page.keyboard.press('Control+s')
        assert saved.value.status == 200
        assert sidecar.is_file()
        # Client-seitiges Abschliessen von Speichern und Entwurf-Bereinigung abwarten.
        page.wait_for_timeout(600)

        # Rebuild simulieren: alte Fassung als Rebuild-Sicherung, neues Deck mit
        # frischen Element-IDs bei identischer Folienstruktur.
        backup = deck.with_name(f'{deck.name}.bak-20260101-000000-1')
        write_deck(backup, {**SCENE, 'elements': [dict(frame)]})
        write_deck(deck, {**SCENE, 'elements': [{**frame, 'id': 'new-frame'}]})

        # Speichern bleibt ohne Konfliktdialog moeglich: Der Server traegt die
        # Anmerkung auf die neue Frame-ID ueber und meldet die neue Deck-Revision.
        with page.expect_response(lambda response: '/api/deck/annotations/save' in response.url, timeout=8000) as rebased:
            page.keyboard.press('Control+s')
        assert rebased.value.status == 200
        page.wait_for_timeout(300)
        expect(page.get_by_role('alertdialog')).to_have_count(0)
        carried = json.loads(sidecar.read_text(encoding='utf-8'))['elements']
        assert any(element.get('customData', {}).get('annotationSlide') == 'new-frame' for element in carried)

        # Nach einem Neustart bleibt die Anmerkung auf der neuen Deck-Fassung sichtbar.
        page.reload()
        page.wait_for_selector('canvas')
        page.wait_for_selector('text=1 / 1')
        page.wait_for_timeout(600)
        strokes = page.evaluate("window.__excalidraw.getSceneElements().filter(e => e.type === 'freedraw').length")
        assert strokes == 1
        browser.close()
