from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_ui.app import create_app
from material_ui.config import AppConfig

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - haengt von der lokalen Testumgebung ab
    sync_playwright = None

from test_material_ui import LiveServer, free_port

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Testkalender//DE
BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:konferenz-1@schule
DTSTAMP:20261020T080000Z
DTSTART;TZID=Europe/Berlin:20261105T100000
DTEND;TZID=Europe/Berlin:20261105T113000
SUMMARY:Gesamtkonferenz
LOCATION:Aula
DESCRIPTION:Alle Kolleginnen und Kollegen.
END:VEVENT
BEGIN:VEVENT
UID:ferien-1@schule
DTSTAMP:20261020T080000Z
DTSTART;VALUE=DATE:20261102
DTEND;VALUE=DATE:20261105
SUMMARY:Herbstferien
END:VEVENT
BEGIN:VEVENT
UID:ring-1@schule
DTSTAMP:20261020T080000Z
DTSTART;TZID=Europe/Berlin:20261005T083000
DTEND;TZID=Europe/Berlin:20261005T090000
SUMMARY:Mathe-Lerngruppe
RRULE:FREQ=WEEKLY;BYDAY=MO
EXDATE;TZID=Europe/Berlin:20261109T083000
END:VEVENT
END:VCALENDAR
"""


class FakeResource:
    def __init__(self, ics: str):
        import icalendar

        self.icalendar_instance = icalendar.Calendar.from_ical(ics)


class FakeCalendar:
    def __init__(self, name: str, ics: str):
        self.name = name
        self.id = f"/calendars/test/{name.lower()}"
        self._ics = ics

    def date_search(self, start, end, expand=True):
        _ = start, end, expand
        return [FakeResource(self._ics)]


class FakePrincipal:
    def __init__(self, calendars):
        self._calendars = calendars

    def calendars(self):
        return list(self._calendars)


class FakeClient:
    def __init__(self, calendars):
        self._principal = FakePrincipal(calendars)

    def principal(self):
        return self._principal


def fake_client_factory(account):
    _ = account
    return FakeClient([FakeCalendar("Persönlich", ICS), FakeCalendar("Gemietet", ICS)])


@pytest.fixture()
def repo(tmp_path):
    previous_modules = {name: module for name, module in sys.modules.items()
                        if name.startswith("material_ui_plugins.")}
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "unterricht").mkdir()
    (repo / "unterricht" / "a.qmd").write_text("---\ntitle: A\n---\nText\n", encoding="utf-8")
    yield repo
    # Andere Testmodule halten Imports aus der Collection. Deren Modulidentitaet
    # muss auch nach dem Aufraeumen der Kalender-Tests erhalten bleiben.
    sys.modules.update(previous_modules)


def warm_plugin_modules(repo: Path):
    """Laedt die Plugin-Module einmal, damit Tests die geladene Instanz patchen koennen."""
    app = create_app(config=AppConfig(repo))
    try:
        app.test_client().get("/api/plugins")
    finally:
        app.extensions["material_runtime"].close()


@pytest.fixture()
def app_with_kalender(repo, monkeypatch):
    # Das Plugin laedt als eigenstaendiges Modul (material_ui_plugins.kalender.service);
    # deshalb erst waermen, dann genau dort patchen und die App neu erzeugen.
    warm_plugin_modules(repo)
    service_module = sys.modules["material_ui_plugins.kalender.service"]
    monkeypatch.setattr(service_module, "default_client_factory", fake_client_factory)
    app = create_app(config=AppConfig(repo))
    app.testing = True
    yield app
    app.extensions["material_runtime"].close()
    for module in [name for name in sys.modules if name.startswith("material_ui_plugins.")]:
        del sys.modules[module]


def test_kalender_plugin_ships_loaded_and_serves_assets(repo):
    app = create_app(config=AppConfig(repo))
    try:
        client = app.test_client()
        plugins = {entry["id"]: entry for entry in client.get("/api/plugins").get_json()["plugins"]}
        assert plugins["kalender"]["status"] == "loaded"
        assert plugins["kalender"]["source"] == "builtin"
        assert plugins["kalender"]["jsUrl"].startswith("/plugins/kalender/assets/plugin.js?v=")
        assert client.get("/plugins/kalender/assets/plugin.js").status_code == 200
        assert client.get("/plugins/kalender/assets/kalender.css").status_code == 200
        assert client.get("/plugins/kalender/assets/icons.svg").status_code == 200
    finally:
        app.extensions["material_runtime"].close()
    for module in [name for name in sys.modules if name.startswith("material_ui_plugins.")]:
        del sys.modules[module]


def test_settings_roundtrip_and_validation(app_with_kalender):
    client = app_with_kalender.test_client()
    settings_file = (app_with_kalender.extensions["material_runtime"].config.root
                    / ".material-ui" / "plugins" / "kalender" / "settings.json")
    response = client.post("/api/plugins/kalender/settings", json={
        "accounts": [
            {"label": "Schule", "url": "https://cal.schule.example/dav/", "username": "lehr",
             "password": "app-passwort", "calendars": ["Persönlich"]},
            {"label": "Privat", "url": "https://dav.example/", "username": "", "password": ""},
        ],
        "timezone": "Europe/Berlin", "syncIntervalMinutes": 30,
        "windowPastDays": 14, "windowFutureDays": 60,
        "defaultEventCalendar": {"account": "Schule", "name": "Persönlich"},
        "defaultTodoCalendar": {"account": "Privat", "name": "Aufgaben"},
    })
    assert response.status_code == 200
    assert "app-passwort" not in response.get_data(as_text=True)
    stored = json.loads(settings_file.read_text())
    assert stored["accounts"][0]["password"] == "app-passwort"
    assert oct(settings_file.stat().st_mode & 0o777) == "0o600"
    # GET liefert Passwoerter nur als Maske.
    masked = client.get("/api/plugins/kalender/settings").get_json()
    assert masked["defaultEventCalendar"] == {"account": "Schule", "name": "Persönlich"}
    assert masked["defaultTodoCalendar"] == {"account": "Privat", "name": "Aufgaben"}
    assert masked["accounts"][0]["password"] == "••••"
    assert masked["accounts"][0]["calendars"] == ["Persönlich"]
    # Eine rueckgeschickte Maske behaelt das gespeicherte Passwort.
    roundtrip = client.post("/api/plugins/kalender/settings", json={**masked, "syncIntervalMinutes": 30})
    assert roundtrip.status_code == 200
    assert json.loads(settings_file.read_text())["accounts"][0]["password"] == "app-passwort"
    # Validierung
    assert client.post("/api/plugins/kalender/settings", json={"timezone": "Mars/Olymp"}).status_code == 400
    assert client.post("/api/plugins/kalender/settings", json={"syncIntervalMinutes": -2}).status_code == 400
    assert client.post("/api/plugins/kalender/settings",
                       json={"accounts": [{"label": "x", "url": "ftp://unsicher/"}]}).status_code == 400


def test_sync_expands_series_and_writes_cache(app_with_kalender):
    client = app_with_kalender.test_client()
    # Fenster grosszuegig um die festen Termindaten im November 2026 spannen.
    today = date.today()
    past = max(0, (today - date(2026, 9, 1)).days)
    future = max(0, (date(2027, 1, 31) - today).days)
    assert client.post("/api/plugins/kalender/settings", json={
        "accounts": [{"label": "Schule", "url": "https://cal.schule.example/dav/",
                      "username": "l", "password": "p"}],
        "windowPastDays": past, "windowFutureDays": future,
    }).status_code == 200
    response = client.post("/api/plugins/kalender/sync")
    assert response.status_code == 202
    job_id = response.get_json()["job_id"]
    deadline = time.time() + 20
    record = {}
    while time.time() < deadline:
        record = client.get(f"/api/jobs/{job_id}").get_json()
        if not record["running"]:
            break
        time.sleep(0.05)
    assert record["status"] == "succeeded", record

    status = client.get("/api/plugins/kalender/status").get_json()
    assert status["configured"] is True
    assert status["lastSync"]["ok"] is True
    assert any(item["account"] == "Schule" and item["name"] == "Persönlich" for item in status["calendars"])
    assert any(item["account"] == "Schule" and item["name"] == "Gemietet" for item in status["calendars"])

    events = client.get("/api/plugins/kalender/events?from=2026-11-01&to=2026-11-30").get_json()["events"]
    konferenz = [event for event in events if event["uid"] == "konferenz-1@schule"]
    assert len(konferenz) == 1  # gleicher Termin in zwei Kalendern wird zusammengelegt
    assert konferenz[0]["startDate"] == "2026-11-05"
    assert konferenz[0]["start"].startswith("2026-11-05T10:00:00")
    assert konferenz[0]["allDay"] is False
    # Ganztägiger mehrtägiger Termin: Ende inklusiv statt iCalendar-exklusiv.
    ferien = [event for event in events if event["uid"] == "ferien-1@schule"][0]
    assert (ferien["startDate"], ferien["endDate"]) == ("2026-11-02", "2026-11-04")
    assert ferien["allDay"] is True
    # Wochentliche Serie wurde expandiert; die Ausnahme fehlt am 09.11.2026.
    ring_termine = {event["startDate"] for event in events if event["uid"] == "ring-1@schule"}
    assert {"2026-11-02", "2026-11-16", "2026-11-23"} <= ring_termine
    assert "2026-11-09" not in ring_termine


def test_events_route_validates_window(app_with_kalender):
    client = app_with_kalender.test_client()
    assert client.get("/api/plugins/kalender/events?from=2026-11-01&to=2026-11-30").status_code == 200
    assert client.get("/api/plugins/kalender/events").status_code == 400
    assert client.get("/api/plugins/kalender/events?from=jemand&to=2026-11-30").status_code == 400
    assert client.get("/api/plugins/kalender/events?from=2026-12-01&to=2026-11-01").status_code == 400


def test_sync_failure_reports_account_errors(app_with_kalender, monkeypatch):
    def broken_factory(account):
        _ = account
        raise ConnectionError("Verbindung verweigert: secret-dav-password https://user:secret@example.test")

    service_module = sys.modules["material_ui_plugins.kalender.service"]
    monkeypatch.setattr(service_module, "default_client_factory", broken_factory)
    client = app_with_kalender.test_client()
    assert client.post("/api/plugins/kalender/settings", json={
        "accounts": [{"label": "Schule", "url": "https://cal.schule.example/dav/",
                      "username": "l", "password": "p"}],
    }).status_code == 200
    # Die Fabrik bindet der Dienst bei der Registrierung; deshalb die Instanz patchen.
    context = app_with_kalender.extensions["material_runtime"].plugins.contexts["kalender"]
    context.service.client_factory = broken_factory
    response = client.post("/api/plugins/kalender/sync")
    job_path = f"/api/jobs/{response.get_json()['job_id']}"
    deadline = time.time() + 20
    record = client.get(job_path).get_json()
    while time.time() < deadline and record["status"] in ("queued", "running"):
        time.sleep(0.05)
        record = client.get(job_path).get_json()
    assert record["status"] == "failed"
    assert "nicht erreichbar" in record["message"]
    assert "secret" not in json.dumps(record)
    status = client.get("/api/plugins/kalender/status").get_json()
    assert status["lastSync"]["ok"] is False
    assert "nicht erreichbar" in status["lastSync"]["message"]
    assert "secret" not in json.dumps(status)
    discovery = client.get("/api/plugins/kalender/calendars").get_json()
    assert "secret" not in json.dumps(discovery)


def seed_cache(repo: Path) -> dict:
    """Legt Cache, Status und Konto mit Terminen im gesamten aktuellen Monat an."""
    today = date.today()
    month_start = today.replace(day=1)
    konferenz_tag = month_start.replace(day=5).isoformat()
    ferien_start = month_start.replace(day=2).isoformat()
    ferien_ende = month_start.replace(day=4).isoformat()
    kalender_dir = repo / ".material-ui" / "plugins" / "kalender"
    kalender_dir.mkdir(parents=True, exist_ok=True)
    (kalender_dir / "cache.json").write_text(json.dumps({
        "window": {"from": month_start.isoformat(), "to": month_start.isoformat()},
        "timezone": "Europe/Berlin",
        "events": [
            {"key": "konferenz-1@schuleT10:00", "uid": "konferenz-1@schule",
             "account": "Schule", "calendar": "Persönlich", "title": "Gesamtkonferenz",
             "start": f"{konferenz_tag}T10:00:00+01:00", "end": f"{konferenz_tag}T11:30:00+01:00",
             "startDate": konferenz_tag, "endDate": konferenz_tag, "allDay": False,
             "location": "Aula", "description": "Alle Kolleginnen und Kollegen.",
             "url": "", "status": "", "categories": []},
            {"key": "ferien-1@schule", "uid": "ferien-1@schule",
             "account": "Schule", "calendar": "Persönlich", "title": "Herbstferien",
             "start": ferien_start, "end": ferien_ende, "startDate": ferien_start,
             "endDate": ferien_ende, "allDay": True, "location": "", "description": "",
             "url": "", "status": "", "categories": []},
        ],
    }), encoding="utf-8")
    (kalender_dir / "status.json").write_text(json.dumps({
        "lastSync": {"time": 1761900000.0, "ok": True,
                     "message": "2 Termine synchronisiert.", "eventCount": 2},
        "calendars": [{"account": "Schule", "name": "Persönlich"}],
    }), encoding="utf-8")
    settings = kalender_dir / "settings.json"
    settings.write_text(json.dumps({"syncIntervalMinutes": 0, "accounts": [
        {"label": "Schule", "url": "https://cal.schule.example/dav/", "username": "l",
         "password": "p", "calendars": []}]}), encoding="utf-8")
    settings.chmod(0o600)
    return {"konferenz": konferenz_tag, "ferienStart": ferien_start, "ferienEnde": ferien_ende}


def test_browser_month_and_agenda_render_cached_events(repo):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    seeded = seed_cache(repo)
    app = create_app(config=AppConfig(repo))
    app.testing = True
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.add_init_script('localStorage.setItem("material-ui:active-view", "agenda")')
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until="networkidle")

            agenda = page.locator('#viewSection-agenda')
            assert agenda.get_by_role('group', name='Zeitraum der Agenda').is_visible()
            assert agenda.locator('[data-kal="agenda-jump"]').input_value() == date.today().isoformat()
            assert agenda.locator('[data-kal=agenda-count]').count() == 0
            assert not agenda.locator('[data-kal=status]').is_visible()
            agenda.locator('.kal-tools summary').click()
            assert agenda.locator('[data-kal=status]').is_visible()
            assert agenda.locator('[data-kal=settings]').is_visible()
            page.keyboard.press('Escape')
            assert not agenda.locator('[data-kal=settings]').is_visible()
            page.set_viewport_size({"width": 600, "height": 900})
            # Unter 1200 px liegt der Index (und damit die Agenda) in der Navigationsschublade.
            page.locator('#workspaceNavigation').click()
            header = agenda.locator('.kal-header')
            assert header.evaluate('el => el.scrollWidth <= el.clientWidth')
            assert agenda.get_by_role('button', name='Termin erstellen', exact=True).is_visible()
            page.set_viewport_size({"width": 1440, "height": 900})
            page.locator('[data-kal="agenda-jump"]').fill(seeded['konferenz'])
            page.get_by_role("button", name="Kalender ↗").click()
            page.wait_for_selector(".kal-cell.today")
            assert page.locator(".kal-cell").count() == 42
            page.wait_for_selector(".kal-chip")
            assert page.locator(".kal-cell", has_text="Herbstferien").count() >= 3
            assert page.locator(".kal-cell", has_text="Gesamtkonferenz").count() == 1

            page.wait_for_selector(f'[data-kal-day="{seeded["konferenz"]}"]')
            # Zellklick auf die Ecke: ein Klick auf einen Chip oeffnet den Termindialog.
            page.locator(f'[data-kal-day="{seeded["konferenz"]}"]').click(position={"x": 3, "y": 3})
            page.wait_for_selector('[data-kal="daylist"] .kal-agenda-entry')
            page.locator('[data-kal="daylist"] .kal-agenda-entry').click()
            dialog = page.get_by_role("dialog", name="Gesamtkonferenz")
            assert dialog.is_visible()
            assert "Aula" in dialog.inner_text()
            dialog.get_by_role('button', name='Bearbeiten', exact=True).click()
            editor = page.locator('#kalCreateModal')
            assert editor.is_visible()
            assert editor.locator('[name=title]').input_value() == 'Gesamtkonferenz'
            assert editor.locator('[name=location]').input_value() == 'Aula'
            page.wait_for_function("!document.querySelector('#kalCreateModal [name=calendarTarget]').disabled")
            assert editor.locator('[name=calendarTarget] option').count() >= 1
            editor.locator('button[data-close]').click()

            page.get_by_role("button", name="Zurück zur Agenda").click()
            page.wait_for_selector("#viewSection-agenda .kal-agenda-entry")
            page.locator('[data-kal="agenda-jump"]').fill(seeded["ferienStart"])
            page.wait_for_timeout(300)
            entries = page.locator("#viewSection-agenda .kal-agenda-entry")
            assert any("Herbstferien" in entries.nth(index).inner_text() for index in range(entries.count()))
            page.locator('[data-kal="agenda-jump"]').fill(seeded["konferenz"])
            page.wait_for_timeout(300)
            entries = page.locator(".kal-agenda-entry")
            assert any("Gesamtkonferenz" in entries.nth(index).inner_text() for index in range(entries.count()))
            page.locator('#viewButton-heute').click()
            page.locator('#viewButton-agenda').click()
            page.wait_for_function("document.querySelector('#viewSection-agenda [data-kal=agenda-jump]').value === new Date().toLocaleDateString('sv-SE')")
            page.locator('[data-kal="agenda-jump"]').fill(seeded["konferenz"])
            page.wait_for_timeout(300)
            assert "Letzter Abgleich" in page.locator("#viewSection-agenda [data-kal=status]").text_content()
            page.route('**/api/plugins/kalender/status', lambda route: route.fulfill(json={
                "configured": True, "syncRunning": True,
                "lastSync": {"ok": False, "time": 1000, "message": "old failure"},
            }))
            page.wait_for_function("document.querySelector('#viewSection-agenda [data-kal=status]').textContent.includes('wird aktualisiert')")
            assert not page.locator('#viewSection-agenda [data-kal=status]').evaluate("el => el.classList.contains('error')")
            assert page.locator('#viewSection-agenda .kal-agenda-entry').count() > 0
            browser.close()
    finally:
        app.extensions["material_runtime"].close()
    for module in [name for name in sys.modules if name.startswith("material_ui_plugins.")]:
        del sys.modules[module]


def test_browser_shows_empty_hint_without_account(repo):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    app = create_app(config=AppConfig(repo))
    app.testing = True
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:active-view", "agenda")')
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until="networkidle")
            page.get_by_role("button", name="Kalender ↗").click()
            # Die Statuszeile liegt im aktuellen Layout im Menü "Weitere
            # Kalenderaktionen"; erst geoeffnet ist sie sichtbar.
            page.wait_for_selector(".kal-fullscreen .kal-tools summary")
            page.locator(".kal-fullscreen .kal-tools summary").click()
            page.wait_for_selector(".kal-fullscreen [data-kal=status]")
            assert "Noch kein CalDAV-Konto" in page.locator(".kal-fullscreen [data-kal=status]").inner_text()
            page.locator(".kal-fullscreen [data-kal=settings]").click()
            page.wait_for_selector("#kalSettingsModal.open")
            dialog = page.get_by_role("dialog", name="Kalender-Einstellungen")
            assert dialog.is_visible()
            dialog.locator("[data-kal-account-add]").click()
            dialog.locator('[data-kal-account="label"]').fill("Schule")
            dialog.locator('[data-kal-account="url"]').fill("https://cal.schule.example/dav/")
            dialog.locator('[data-kal-account="username"]').fill("lehr")
            dialog.locator('[data-kal-account="password"]').fill("geheim")
            dialog.locator("[data-kal-save]").click()
            page.wait_for_timeout(500)
            stored = json.loads((repo / ".material-ui" / "plugins" / "kalender" / "settings.json").read_text())
            assert stored["accounts"][0]["password"] == "geheim"
            page.route("**/api/plugins/kalender/calendars",
                       lambda route: route.fulfill(json={"calendars": [
                           {"account": "Schule", "name": "Termine", "components": ["VEVENT"]},
                           {"account": "Schule", "name": "Aufgaben", "components": ["VTODO"]}], "errors": []}))
            page.reload(wait_until="networkidle")
            page.get_by_role("button", name="Kalender ↗").click()
            page.locator(".kal-fullscreen .kal-tools summary").click()
            page.locator(".kal-fullscreen [data-kal=settings]").click()
            page.wait_for_selector("#kalSettingsModal.open")
            # rAF-Polling ist im Headless-Shell unzuverlässig; festes Intervall nutzen.
            page.wait_for_function("document.querySelector('#kalSettingsModal').availableCalendars.length === 2", polling=200)
            dialog.locator('[data-kal-select="selectedTodoCalendars"]').click()
            picker = page.locator("dialog.kal-calendar-picker")
            assert picker.get_by_text("Aufgaben (Schule)", exact=True).is_visible()
            assert picker.get_by_text("Termine (Schule)", exact=True).count() == 0
            picker.locator("[data-all]").uncheck()
            # Checkbox direkt klicken statt des Label-Texts (deterministisch).
            picker.locator('.kal-calendar-options label:has-text("Aufgaben (Schule)") input').check()
            picker.get_by_role("button", name="Übernehmen").click()
            page.wait_for_function(
                "document.querySelector('[data-kal-select=\"selectedTodoCalendars\"]').textContent.trim() === 'Aufgaben'",
                polling=200)
            assert dialog.locator('[data-kal-select="selectedTodoCalendars"]').inner_text() == "Aufgaben"
            account = dialog.locator(".kal-account")
            assert account.locator("[data-kal-account-name]").inner_text() == "Schule"
            assert not account.locator('[data-kal-account="url"]').is_visible()
            account.get_by_role("button", name="Bearbeiten", exact=True).click()
            assert account.locator('[data-kal-account="url"]').is_visible()
            assert account.locator('[data-kal-account="username"]').input_value() == "lehr"
            account.get_by_role("button", name="Fertig", exact=True).click()
            assert not account.locator('[data-kal-account="url"]').is_visible()
            account.get_by_role("button", name="Löschen", exact=True).click()
            assert dialog.locator(".kal-account").count() == 0
            browser.close()
    finally:
        app.extensions["material_runtime"].close()
    for module in [name for name in sys.modules if name.startswith("material_ui_plugins.")]:
        del sys.modules[module]


def source_event(key="source", start="2026-11-10T08:00:00+01:00", **overrides):
    return {"key": key, "title": key, "start": start,
            "end": "2026-11-10T09:30:00+01:00", "startDate": "2026-11-10",
            "endDate": "2026-11-10", "allDay": False, "calendar": "Stundenplan",
            "account": "", "location": "A12", "description": "", "url": "", **overrides}


@pytest.mark.parametrize('selected', [[], [{'account': 'Mail', 'name': 'Arbeit'}]])
def test_calendar_selection_keeps_plugin_source_but_respects_explicit_hiding(app_with_kalender, selected):
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    service = context.service
    service.replace_settings({**service.settings_payload(), 'selectedEventCalendars': selected})
    context.service('calendar').register_source(lambda start, end: [source_event()])
    context.storage.write_json(service._cache_path(), {'events': [source_event('cached')]})
    client = app_with_kalender.test_client()
    url = '/api/plugins/kalender/events?from=2026-11-09&to=2026-11-15'
    assert [event['key'] for event in client.get(url).json['events']] == ['source']
    service.update_visibility({'scope': 'calendars', 'id': service._calendar_identity(source_event()), 'hidden': True})
    assert client.get(url).json['events'] == []


def test_source_merges_cache_and_sorts_offsets_and_all_day(app_with_kalender):
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    cache_event = source_event("utc", "2026-11-10T07:30:00+00:00")
    context.storage.write_json(context.service._cache_path(), {"events": [cache_event]})
    context.service('calendar').register_source(lambda start, end: [
        source_event(), source_event('all-day', '2026-11-10', end='2026-11-10', allDay=True),
    ])
    data = app_with_kalender.test_client().get(
        '/api/plugins/kalender/events?from=2026-11-09&to=2026-11-15').get_json()
    assert [event['key'] for event in data['events']] == ['all-day', 'source', 'utc']
    assert data['sourceErrors'] == []


@pytest.mark.parametrize('bad_result', [None, {}, [{}], [source_event(start='bad')],
    [source_event(start='2026-11-10T08:00:00')],
    [source_event(end='2026-11-10T06:00:00+01:00')],
    [source_event(allDay='false')],
    [source_event(), {'key': 'broken'}]])
def test_invalid_source_response_preserves_cache_and_other_sources(app_with_kalender, bad_result):
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    context.storage.write_json(context.service._cache_path(), {'events': [source_event('cached')]})
    context.service('calendar').register_source(lambda start, end: bad_result, source_id='kalender')
    context.service('calendar').register_source(lambda start, end: [source_event('healthy')])
    response = app_with_kalender.test_client().get(
        '/api/plugins/kalender/events?from=2026-11-09&to=2026-11-15')
    assert response.status_code == 200
    assert {event['key'] for event in response.json['events']} == {'cached', 'healthy'}
    assert response.json['sourceErrors'][0]['source'] == 'kalender'


def test_browser_source_failure_warning_and_recovery_in_both_views(repo):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    seed_cache(repo)
    app = create_app(config=AppConfig(repo))
    app.testing = True
    context = app.extensions['material_runtime'].plugins.contexts['kalender']
    def broken(start, end):
        raise RuntimeError('sensitive-internal-detail')
    context.service('calendar').register_source(broken, source_id='kalender')
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:active-view", "agenda")')
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            for view in ['kalender', 'agenda']:
                if view == 'kalender':
                    page.get_by_role('button', name='Kalender ↗').click()
                else:
                    page.get_by_role('button', name='Zurück zur Agenda').click()
                container = '.kal-fullscreen' if view == 'kalender' else '#viewSection-agenda'
                warning = page.locator(f'{container} [data-kal=source-errors]')
                warning.wait_for(state='visible')
                assert 'Termine konnten nicht geladen werden' in warning.inner_text()
                assert 'sensitive-internal-detail' not in warning.inner_text()
            page.get_by_role("button", name="Kalender ↗").click()
            page.wait_for_selector('.kal-chip')
            context.service.calendar_interface.clear()
            page.get_by_role("button", name="Zurück zur Agenda").click()
            page.locator('#viewSection-agenda [data-kal=source-errors]').wait_for(state='hidden')
            page.get_by_role("button", name="Kalender ↗").click()
            page.locator('.kal-fullscreen [data-kal=source-errors]').wait_for(state='hidden')
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_local_events_persist_and_validate(app_with_kalender):
    client = app_with_kalender.test_client()
    response = client.post('/api/plugins/kalender/events', json={'title': 'Besprechung', 'date': '2026-11-06', 'time': '10:00', 'endTime': '11:00'})
    assert response.status_code == 201
    assert response.json['start'] == '2026-11-06T10:00:00+01:00'
    events = client.get('/api/plugins/kalender/events?from=2026-11-06&to=2026-11-06').json['events']
    assert any(event['key'] == response.json['key'] for event in events)
    assert client.post('/api/plugins/kalender/events', json={'title': 'Fehler', 'date': '2026-11-06', 'time': '10:00', 'endTime': '09:00'}).status_code == 400
    assert client.post('/api/plugins/kalender/events', json={'title': '', 'date': '2026-11-06'}).status_code == 400


def test_unit_links_respect_date_group_subject_and_school_year(app_with_kalender, monkeypatch):
    from material_ui.units import UnitService
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    unit = {'path': 'unterricht/mathematik/klasse-05/test', 'klasse': 'klasse-05', 'fach': 'mathematik',
            'data': {'titel': 'Malnehmen', 'einsatz': [{'datum': '2026-11-10'}]}}
    monkeypatch.setattr(UnitService, 'scheduled_units', lambda self: [unit])
    service = context.service
    events = [source_event(title=title) for title in ['05C MA', '05 MA', '05B MA', '05C DE', '05C MK', '05B MK', '10C MK']]
    service.link_units(events)
    assert [len(event['units']) for event in events] == [1, 1, 0, 0, 1, 0, 0]
    unit['data']['einsatz'][0]['lerngruppe'] = '05B'
    service.link_units(events)
    assert [len(event['units']) for event in events] == [0, 0, 1, 0, 0, 1, 0]
    unit['klasse'] = 'klasse-10'
    unit['data']['einsatz'][0]['lerngruppe'] = '10C'
    service.link_units(events)
    assert [len(event['units']) for event in events] == [0, 0, 0, 0, 0, 0, 1]
    unit['klasse'] = 'klasse-05'
    unit['data']['einsatz'] = [{'datum': '2027-11-10'}]
    future = source_event(title='05C MA', startDate='2027-11-10')
    service.link_units([future])
    assert len(future['units']) == 1
    service.save_group_defaults([{'year': '2027/2028', 'grade': '05', 'group': '05B'}])
    service.link_units([future])
    assert future['units'] == []
    service.save_group_defaults([{'year': '2027/2028', 'grade': '05', 'group': '05C'}])
    service.link_units([future])
    assert len(future['units']) == 1


def test_unit_links_recognise_oberstufe_courses(app_with_kalender, monkeypatch):
    from material_ui.units import UnitService
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    unit = {'path': 'unterricht/informatik/klasse-12/test', 'klasse': 'klasse-12', 'fach': 'informatik',
            'data': {'titel': 'Sortieren', 'einsatz': [{'datum': '2026-11-10'}]}}
    monkeypatch.setattr(UnitService, 'scheduled_units', lambda self: [unit])
    event = source_event(title='Q1 IN')
    context.service.link_units([event])
    assert event['teaching'] == {'klasse': 'klasse-12', 'lerngruppe': 'Q1', 'fach': 'informatik'}
    assert len(event['units']) == 1


def test_unit_date_without_group_default_occupies_lesson(app_with_kalender):
    client = app_with_kalender.test_client()
    service = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender'].service
    service.save_group_defaults([])
    unit = client.post('/api/units/new', json={
        'fach': 'mathematik', 'klasse': '05', 'thema': 'Potenzen', 'titel': 'Uebungen',
    }).get_json()
    saved = client.post('/api/units/dates', json={
        'path': unit['path'], 'revision': unit['revision'], 'dates': ['2026-11-25'], 'lerngruppe': '',
    })
    assert saved.status_code == 200
    events = [source_event(
        key=str(index), title=title, startDate=day, endDate=day,
        start=f'{day}T08:00:00+01:00', end=f'{day}T09:00:00+01:00',
    ) for index, (title, day) in enumerate([
        ('05C MA', '2026-11-25'), ('05C MA', '2026-11-26'),
        ('05C DE', '2026-11-25'), ('06C MA', '2026-11-25'),
    ])]
    service.storage.write_json(service.storage.path('local-events.json'), events)
    linked = client.get('/api/plugins/kalender/events?from=2026-11-25&to=2026-11-26').get_json()['events']
    assert len(linked) == 4
    for event in linked:
        assert [entry['path'] for entry in event['units']] == (
            [unit['path']] if event['title'] == '05C MA' and event['startDate'] == '2026-11-25' else []
        )


def test_unit_links_collect_materials_of_the_day(app_with_kalender, monkeypatch):
    from material_ui.units import UnitService
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    unit = {'path': 'unterricht/mathematik/klasse-05/test', 'klasse': 'klasse-05', 'fach': 'mathematik',
            'data': {'titel': 'Malnehmen', 'einsatz': [
                {'datum': '2026-11-10', 'material': 'ab_eins.qmd'}, {'datum': '2026-11-10', 'material': 'ab_eins.qmd'},
                {'datum': '2026-11-10', 'material': 'slide.qmd'}, {'datum': '2026-11-11', 'material': 'ab_zwei.qmd'}]}}
    monkeypatch.setattr(UnitService, 'scheduled_units', lambda self: [unit])
    event = source_event(title='05C MA')
    context.service.link_units([event])
    assert event['units'] == [{'path': unit['path'], 'title': 'Malnehmen', 'materials': ['ab_eins.qmd', 'slide.qmd']}]
    unit['data']['einsatz'] = [{'datum': '2026-11-10'}]
    context.service.link_units([event])
    assert event['units'] == [{'path': unit['path'], 'title': 'Malnehmen', 'materials': []}]


@pytest.mark.parametrize("kind", ["event", "todo"])
def test_browser_creates_general_and_dated_events_from_both_views(repo, kind):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    app = create_app(config=AppConfig(repo))
    app.testing = True
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.add_init_script('localStorage.setItem("material-ui:active-view", "agenda")')
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.wait_for_selector('#viewSection-agenda .kal-agenda-day')
            assert page.locator('#viewButton-kalender').count() == 0
            today = date.today().isoformat()
            for view in ['agenda', 'calendar']:
                container = page.locator('#viewSection-agenda' if view == 'agenda' else '.kal-fullscreen')
                if view == 'calendar':
                    page.get_by_role('button', name='Kalender ↗').click()
                    container.locator(f'[data-kal-day="{today}"]').click(position={'x': 3, 'y': 3})
                for dated in [False, True]:
                    if dated:
                        container.locator(f'[data-kal-create{ "-todo" if kind == "todo" else "" }="{today}"]').click()
                    else:
                        container.get_by_role('button', name='TODO erstellen' if kind == 'todo' else 'Termin erstellen', exact=True).click()
                    form = page.locator('#kalCreateModal form')
                    assert form.locator('[name=date]').input_value() == today
                    assert form.locator('[name=kind]').input_value() == kind
                    form.locator('[name=title]').fill(f'{view} {dated}')
                    form.locator('[name=date]').fill(today)
                    form.get_by_role('button', name='Speichern', exact=True).click()
                    page.wait_for_selector('#kalCreateModal.open', state='hidden')
                if view == 'calendar':
                    page.get_by_role('button', name='Zurück zur Agenda').click()
            page.reload(wait_until='networkidle')
            assert page.locator('#viewSection-agenda .kal-agenda-entry').count() == 4
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_browser_unit_title_opens_unit_directly(repo):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    folder = repo / 'unterricht/mathematik/klasse-05/zerlegen'
    folder.mkdir(parents=True)
    day = date.today().isoformat()
    (folder / 'einheit.yaml').write_text(f'titel: Zerlegen und ergänzen\nthema: Rechnen\nkurzbeschreibung: ""\neinsatz:\n  - datum: "{day}"\n    lerngruppe: 05C\n', encoding='utf-8')
    app = create_app(config=AppConfig(repo))
    context = app.extensions['material_runtime'].plugins.contexts['kalender']
    context.service('calendar').register_source(lambda start, end: [source_event(title='05C MA', startDate=day, endDate=day,
        start=f'{day}T11:35:00+01:00', end=f'{day}T12:20:00+01:00')])
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:active-view", "agenda")')
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.get_by_role('button', name='↳ Zerlegen und ergänzen', exact=True).click()
            # Der Locator nennt die Karte selbst: Der Planungsbereich innerhalb der
            # Karte traegt dasselbe data-unit-path wie die Karte (keine Mehrdeutigkeit).
            card = page.locator('details.unit-card[data-unit-path="unterricht/mathematik/klasse-05/zerlegen"]')
            card.wait_for(state='visible')
            page.wait_for_selector('details.unit-card[data-unit-path="unterricht/mathematik/klasse-05/zerlegen"][open]')
            assert card.get_attribute('open') is not None
            assert page.locator('#kalEventModal.open').count() == 0
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_create_event_in_selected_calendar(app_with_kalender, monkeypatch):
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/settings', json={
        'accounts': [{'label': 'Schule', 'url': 'https://example.test/dav',
                      'calendars': ['Persönlich']}], 'syncIntervalMinutes': 0,
    })
    saved = []
    monkeypatch.setattr(FakeCalendar, 'save_event', lambda self, data: saved.append((self.name, data)), raising=False)
    payload = {'title': 'Elternsprechtag', 'date': '2026-11-05',
               'account': 'Schule', 'calendar': 'Persönlich'}
    response = client.post('/api/plugins/kalender/events', json=payload)
    assert response.status_code == 201
    event = response.get_json()
    assert event['calendar'] == 'Persönlich'
    assert event['account'] == 'Schule'
    assert saved[0][0] == 'Persönlich'
    from icalendar import Calendar
    component = Calendar.from_ical(saved[0][1]).walk('VEVENT')[0]
    assert component.decoded('dtstart') == date(2026, 11, 5)
    assert component.decoded('dtend') == date(2026, 11, 6)
    events = client.get('/api/plugins/kalender/events?from=2026-11-05&to=2026-11-05').get_json()['events']
    assert any(item['key'] == event['key'] for item in events)
    for changes in ({'account': 'Unbekannt'}, {'calendar': 'Gemietet'}, {'account': ''}):
        assert client.post('/api/plugins/kalender/events', json={**payload, **changes}).status_code == 400
    assert len(saved) == 1


def test_failed_calendar_write_does_not_create_local_event(app_with_kalender, monkeypatch):
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/settings', json={
        'accounts': [{'label': 'Schule', 'url': 'https://example.test/dav'}], 'syncIntervalMinutes': 0,
    })
    def fail(self, data):
        raise RuntimeError('Schreibgeschützt: secret-dav-password')
    monkeypatch.setattr(FakeCalendar, 'save_event', fail, raising=False)
    response = client.post('/api/plugins/kalender/events', json={
        'title': 'Test', 'date': '2026-11-05', 'account': 'Schule', 'calendar': 'Persönlich',
    })
    assert response.status_code == 400
    assert "secret-dav-password" not in response.get_data(as_text=True)
    events = client.get('/api/plugins/kalender/events?from=2026-11-05&to=2026-11-05').get_json()['events']
    assert events == []


@pytest.mark.parametrize("kind", ["event", "todo"])
def test_browser_selects_calendar(app_with_kalender, kind):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    with LiveServer(app_with_kalender, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:active-view", "agenda")')
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.add_init_script('localStorage.setItem("material-ui:active-view", "agenda")')
        page.route('**/api/plugins/kalender/calendars', lambda route: route.fulfill(json={
            'calendars': [{'account': 'Schule', 'name': 'Persönlich'}, {'account': 'Privat', 'name': 'Aufgaben'}], 'errors': [],
        }))
        page.route('**/api/plugins/kalender/settings', lambda route: route.fulfill(json={
            'defaultEventCalendar': {'account': 'Schule', 'name': 'Persönlich'},
            'defaultTodoCalendar': {'account': 'Privat', 'name': 'Aufgaben'},
        }))
        page.goto(url, wait_until='networkidle')
        page.locator('#viewSection-agenda').get_by_role('button', name='TODO erstellen' if kind == 'todo' else 'Termin erstellen', exact=True).click()
        form = page.locator('#kalCreateModal form')
        select = form.locator('select[name=calendarTarget]')
        page.wait_for_function("document.querySelector('#kalCreateModal select[name=calendarTarget]').value !== ''")
        assert select.locator('option:checked').inner_text() == ('Aufgaben (Privat)' if kind == 'todo' else 'Persönlich (Schule)')
        assert form.locator('select[name=kind]').input_value() == kind
        assert form.locator('input[name=date]').input_value()
        assert form.locator('input[name=time]').is_visible() is (kind == 'event')
        assert 'ausgewählten Kalender' in form.locator('[data-calendar-hint]').inner_text()
        form.get_by_label('Titel', exact=True).fill('Elternsprechtag')
        form.locator('[name=date]').fill('2026-11-05')
        page.route('**/api/plugins/kalender/events', lambda route: route.fulfill(status=201, json={}))
        with page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/kalender/events')) as request:
            form.get_by_role('button', name='Speichern', exact=True).click()
        assert request.value.post_data_json['kind'] == kind
        assert request.value.post_data_json['account'] == ('Privat' if kind == 'todo' else 'Schule')
        assert request.value.post_data_json['calendar'] == ('Aufgaben' if kind == 'todo' else 'Persönlich')
        page.wait_for_selector('#kalCreateModal.open', state='hidden')
        browser.close()


@pytest.mark.parametrize("url", [
    "http://example.test/dav/", "https://user:secret@example.test/dav/",
    "https://example.test/dav/?password=secret", "https://example.test/#secret",
    "https:///dav/",
])
def test_dav_rejects_unsafe_urls(app_with_kalender, url):
    response = app_with_kalender.test_client().post("/api/plugins/kalender/settings", json={
        "accounts": [{"label": "Schule", "url": url, "password": "secret"}],
    })
    assert response.status_code == 400
    assert "secret" not in response.get_data(as_text=True)


def test_dav_mask_does_not_transfer_password_to_other_server(app_with_kalender):
    client = app_with_kalender.test_client()
    account = {"label": "Schule", "url": "https://old.example.test/", "password": "secret"}
    client.post("/api/plugins/kalender/settings", json={"accounts": [account]})
    account.update(url="https://new.example.test/", password="••••")
    client.post("/api/plugins/kalender/settings", json={"accounts": [account]})
    service = app_with_kalender.extensions["material_runtime"].plugins.contexts["kalender"].service
    assert service.settings()["accounts"][0]["password"] == ""


@pytest.mark.parametrize("message, expected", [
    ("Mailbox.org: HTTPSConnectionPool: NameResolutionError secret", "nicht erreichbar"),
    ("DAV failure with secret", "Kalendereinstellungen prüfen"),
    ("Der Kalenderdienst ist gerade nicht erreichbar.", "nicht erreichbar"),
])
def test_status_sanitizes_persisted_legacy_errors(app_with_kalender, message, expected):
    service = app_with_kalender.extensions["material_runtime"].plugins.contexts["kalender"].service
    service.storage.write_json(service._status_path(), {
        "lastSync": {"ok": False, "time": 1000, "message": message, "eventCount": 0},
    })
    status = app_with_kalender.test_client().get('/api/plugins/kalender/status').get_json()
    assert expected in status["lastSync"]["message"]
    assert "secret" not in json.dumps(status)
    assert status["lastSync"]["time"] == 1000


def test_sync_retains_failed_account_and_recovers(app_with_kalender, caplog):
    service = app_with_kalender.extensions["material_runtime"].plugins.contexts["kalender"].service
    service.replace_settings({"accounts": [
        {"label": "Mailbox", "url": "https://example.test/dav"},
        {"label": "Schule", "url": "https://example.test/dav"},
    ]})
    now = [1000]
    service.clock = lambda: now[0]
    revision = ["alt"]
    failing = [False]

    def read(account, *args):
        label = account["label"]
        if failing[0] and label == "Mailbox":
            raise ConnectionError("DNS-Ausfall: technische Details")
        return ([dict(key="shared-uid", account=label, startDate="2026-11-05",
                      start="2026-11-05", title=revision[0])], [{"account": label, "name": label}])

    service._read_account = read
    assert service.sync_now()["ok"]
    failing[0] = True
    revision[0] = "neu"
    for delay in (60, 300, 900, 3600):
        now[0] += 1
        assert not service.sync_now()["ok"]
        status = service.status()
        assert status["nextSync"] == now[0] + delay
        assert status["lastSuccessfulSync"] == 1000
        assert "technische Details" not in status["lastSync"]["message"]
        events = service.storage.read_json(service._cache_path())["events"]
        assert {e["account"]: e["title"] for e in events} == {"Mailbox": "alt", "Schule": "neu"}
    assert "technische Details" not in caplog.text
    assert "Fehlertyp=ConnectionError" in caplog.text
    failing[0] = False
    assert service.sync_now()["ok"]
    assert service.status()["lastSync"]["ok"]
    assert not service.status()["retryPending"]
    assert service.status()["lastSuccessfulSync"] == now[0]


def test_sync_authentication_error_does_not_retry_quickly(app_with_kalender):
    from requests import Response
    from requests.exceptions import HTTPError

    service = app_with_kalender.extensions["material_runtime"].plugins.contexts["kalender"].service
    service.replace_settings({"accounts": [{"label": "Mailbox", "url": "https://example.test/dav"}]})
    service.clock = lambda: 1000
    response = Response()
    response.status_code = 401

    def broken(*args):
        raise HTTPError("401 secret details", response=response)

    service._read_account = broken
    assert not service.sync_now()["ok"]
    status = service.status()
    assert "Anmeldung fehlgeschlagen" in status["lastSync"]["message"]
    assert status["nextSync"] == 4600
    assert not status["retryPending"]
    service.replace_settings({"accounts": [{"label": "Mailbox", "url": "https://example.test/dav"}],
                              "syncIntervalMinutes": 0})
    service.sync_now()
    assert service.status()["nextSync"] is None


def test_calendar_worker_runs_scheduled_retries(app_with_kalender):
    from types import SimpleNamespace

    service = app_with_kalender.extensions["material_runtime"].plugins.contexts["kalender"].service
    service.replace_settings({"accounts": [{"label": "Mailbox", "url": "https://example.test/dav"}]})
    now = [1000]
    service.clock = lambda: now[0]
    calls = []

    def read(*args):
        calls.append(now[0])
        if len(calls) < 5:
            raise ConnectionError("DNS")
        return [], []

    service._read_account = read
    service.sync_now()
    # Erst vor, dann jeweils genau zur nächsten Fälligkeit aufwachen.
    ticks = iter([1059, 1060, 1359, 1360, 2259, 2260, 5859, 5860])

    def wait(seconds):
        try:
            now[0] = next(ticks)
            return False
        except StopIteration:
            return True

    worker = []
    runtime = SimpleNamespace(closing=SimpleNamespace(wait=wait),
                              start_worker=lambda fn, args: worker.append(fn))
    service._interval_worker = None
    service.start_interval_worker(runtime, 60)
    worker[0]()
    assert calls == [1000, 1060, 1360, 2260, 5860]
    assert service.status()["lastSync"]["ok"]
    assert service.status()["nextSync"] == 9460


@pytest.mark.parametrize("next_sync, interval, expected", [
    (None, 60, [1000]),
    (900, 60, [1000]),
    (1100, 60, [1100]),
    (None, 0, []),
])
def test_calendar_immediate_startup_and_legacy_status(app_with_kalender, next_sync, interval, expected):
    from types import SimpleNamespace

    service = app_with_kalender.extensions["material_runtime"].plugins.contexts["kalender"].service
    service.replace_settings({
        "accounts": [{"label": "Mailbox", "url": "https://example.test/dav"}],
        "syncIntervalMinutes": interval,
    })
    service.storage.write_json(service._status_path(), {
        "lastSync": {"ok": False, "time": 900, "message": "old DNS failure"},
        "nextSync": next_sync,
    })
    now = [1000]
    service.clock = lambda: now[0]
    calls = []
    service._read_account = lambda *args: (calls.append(now[0]) or [], [])
    ticks = iter([1000, 1005, 1029, 1030, 1099, 1100])

    def wait(seconds):
        now[0] = next(ticks, None)
        return now[0] is None

    worker = []
    runtime = SimpleNamespace(closing=SimpleNamespace(wait=wait),
                              start_worker=lambda fn, args: worker.append(fn))
    service._interval_worker = None
    service.start_interval_worker(runtime, 60)
    worker[0]()
    assert calls == expected


@pytest.mark.parametrize("fails", [False, True])
def test_calendar_reports_background_sync_running(app_with_kalender, fails):
    service = app_with_kalender.extensions["material_runtime"].plugins.contexts["kalender"].service
    service.replace_settings({"accounts": [{"label": "Mailbox", "url": "https://example.test/dav"}]})

    def read(*args):
        assert service.status()["syncRunning"] is True
        if fails:
            raise ConnectionError("DNS")
        return [], []

    service._read_account = read
    assert service.status()["syncRunning"] is False
    service.sync_now()
    assert service.status()["syncRunning"] is False
    assert service.status()["lastSync"]["ok"] is not fails


def test_calendar_recognises_wrapped_dns_failure(app_with_kalender):
    import socket
    from requests.exceptions import ConnectionError as RequestsConnectionError
    from urllib3.exceptions import MaxRetryError, NameResolutionError

    module = sys.modules["material_ui_plugins.kalender.service"]
    dns = NameResolutionError("dav.mailbox.org", None, socket.gaierror(-3, "Temporary failure"))
    wrapped = RequestsConnectionError(MaxRetryError(None, "/caldav/", dns))
    message, retryable = module._sync_error(wrapped)
    assert retryable
    assert "gerade nicht erreichbar" in message
    assert "HTTPSConnectionPool" not in message


def test_local_todo_is_assigned_to_one_day(app_with_kalender):
    client = app_with_kalender.test_client()
    response = client.post('/api/plugins/kalender/events', json={
        'title': 'Bretzel-Abfrage 10c', 'kind': 'todo', 'date': '2026-11-06',
    })
    assert response.status_code == 201
    todo = response.get_json()
    assert todo['kind'] == 'todo' and todo['allDay']
    for day, expected in [('2026-11-05', False), ('2026-11-06', True), ('2026-11-07', False)]:
        entries = client.get(f'/api/plugins/kalender/events?from={day}&to={day}').get_json()['events']
        assert any(entry['key'] == todo['key'] for entry in entries) is expected


def lesson_source(context, day='2026-11-10'):
    def provider(start, end):
        _ = start, end
        return [
            source_event('stunde-1', title='10C MA', start=f'{day}T07:55:00+01:00',
                         end=f'{day}T08:40:00+01:00', startDate=day, endDate=day, location='G02'),
            source_event('aufsicht', title='EOST', start=f'{day}T09:30:00+01:00',
                         end=f'{day}T09:45:00+01:00', startDate=day, endDate=day),
            source_event('stunde-2', title='05C MA', start=f'{day}T09:45:00+01:00',
                         end=f'{day}T10:30:00+01:00', startDate=day, endDate=day, location='E32'),
            source_event('ganztag', title='Feiertag', start=day, end=day,
                         startDate=day, endDate=day, allDay=True),
            source_event('anderer-tag', title='10C MA', start='2026-11-11T07:55:00+01:00',
                         end='2026-11-11T08:40:00+01:00', startDate='2026-11-11', endDate='2026-11-11'),
        ]
    context.service('calendar').register_source(provider)


LESSON = {'start': '2026-11-10T07:55:00+01:00', 'title': '10C MA',
          'end': '2026-11-10T08:40:00+01:00', 'location': 'G02'}


def test_lessons_endpoint_returns_only_timed_events_of_the_day(app_with_kalender):
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    lesson_source(context)
    client = app_with_kalender.test_client()
    data = client.get('/api/plugins/kalender/lessons?date=2026-11-10').get_json()
    assert [lesson['start'] for lesson in data['lessons']] == [
        '2026-11-10T07:55:00+01:00', '2026-11-10T09:30:00+01:00', '2026-11-10T09:45:00+01:00']
    assert data['lessons'][0]['title'] == '10C MA' and data['lessons'][0]['location'] == 'G02'
    assert data['lessons'][0]['id'] == data['lessons'][0]['start']
    assert data['sourceErrors'] == []
    other = client.get('/api/plugins/kalender/lessons?date=2026-11-11').get_json()
    assert [lesson['start'] for lesson in other['lessons']] == ['2026-11-11T07:55:00+01:00']
    for bad in ['', '2026-11-1', '10.11.2026', '2026-13-01', 'unsinn']:
        assert client.get(f'/api/plugins/kalender/lessons?date={bad}').status_code == 400


def test_lessons_endpoint_reports_source_errors_without_details(app_with_kalender):
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    def broken(start, end):
        raise RuntimeError('geheime interne Details')
    context.service('calendar').register_source(broken, source_id='kalender')
    data = app_with_kalender.test_client().get('/api/plugins/kalender/lessons?date=2026-11-10').get_json()
    assert data['lessons'] == []
    assert data['sourceErrors'][0]['source'] == 'kalender'
    assert 'geheime interne Details' not in json.dumps(data)


def test_local_todo_lesson_link_roundtrip_and_validation(app_with_kalender):
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    lesson_source(context)
    client = app_with_kalender.test_client()
    response = client.post('/api/plugins/kalender/events', json={
        'kind': 'todo', 'title': 'WiFe: Essen organisieren', 'date': '2026-11-10', 'lesson': LESSON})
    assert response.status_code == 201
    todo = response.get_json()
    assert todo['lesson'] == LESSON
    task = next(t for t in client.get('/api/plugins/kalender/tasks').get_json()['tasks']
                if t['key'] == todo['key'])
    assert task['lesson']['start'] == LESSON['start']
    entry = next(e for e in client.get('/api/plugins/kalender/events?from=2026-11-10&to=2026-11-10').get_json()['events']
                 if e['key'] == todo['key'])
    assert entry['lesson']['title'] == '10C MA'
    patch = {'kind': 'todo', 'title': 'WiFe: Essen organisieren', 'date': '2026-11-10',
             'key': todo['key'], 'originalAccount': '', 'originalCalendar': 'Lokale Termine'}
    # Verknüpfung auf eine andere Stunde des Tages ändern
    other = {'start': '2026-11-10T09:45:00+01:00', 'title': '05C MA',
             'end': '2026-11-10T10:30:00+01:00', 'location': 'E32'}
    updated = client.patch('/api/plugins/kalender/events', json={**patch, 'lesson': other})
    assert updated.status_code == 200 and updated.get_json()['lesson']['start'] == other['start']
    # Unveränderte Verknüpfung bleibt auch ohne erreichbare Quelle erhalten
    context.service.calendar_interface.clear()
    kept = client.patch('/api/plugins/kalender/events', json={**patch, 'lesson': other})
    assert kept.status_code == 200 and kept.get_json()['lesson']['start'] == other['start']
    # Verknüpfung entfernen
    cleared = client.patch('/api/plugins/kalender/events', json={**patch, 'lesson': None})
    assert cleared.status_code == 200 and cleared.get_json()['lesson'] is None
    # Validierung: nur Stunden des gewählten Tages, nur für TODOs mit Datum
    for invalid in [{**LESSON, 'start': '2026-11-11T07:55:00+01:00'},
                    {**LESSON, 'start': '2026-11-10T07:55:00'},
                    {**LESSON, 'start': 'unsinn'},
                    {'start': '2026-11-10T07:55:00+01:00'},
                    '2026-11-10T07:55:00+01:00',
                    {'start': '2026-11-10T23:30:00+01:00', 'title': 'Nachmittag'}]:
        assert client.post('/api/plugins/kalender/events', json={
            'kind': 'todo', 'title': 'Fehler', 'date': '2026-11-10', 'lesson': invalid}).status_code == 400
    assert client.post('/api/plugins/kalender/events', json={
        'kind': 'todo', 'title': 'Ohne Frist', 'lesson': LESSON}).status_code == 400
    assert client.post('/api/plugins/kalender/events', json={
        'title': 'Termin', 'date': '2026-11-10', 'lesson': LESSON}).status_code == 400


def test_remote_todo_lesson_is_stored_as_ical_property_and_synced(app_with_kalender, monkeypatch):
    from icalendar import Calendar
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    lesson_source(context)
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/settings', json={
        'accounts': [{'label': 'Schule', 'url': 'https://example.test/dav',
                      'calendars': ['Persönlich']}], 'syncIntervalMinutes': 0,
    })
    saved = []
    monkeypatch.setattr(FakeCalendar, 'get_supported_components', lambda self: ['VTODO'], raising=False)
    monkeypatch.setattr(FakeCalendar, 'save_todo', lambda self, data: saved.append(data), raising=False)
    monkeypatch.setattr(FakeCalendar, 'todos', lambda self, **kw: [FakeResource(data) for data in saved], raising=False)
    response = client.post('/api/plugins/kalender/events', json={
        'kind': 'todo', 'title': 'Kopieren', 'date': '2026-11-10', 'account': 'Schule',
        'calendar': 'Persönlich', 'lesson': LESSON})
    assert response.status_code == 201
    assert response.get_json()['lesson']['start'] == LESSON['start']
    component = Calendar.from_ical(saved[0]).walk('VTODO')[0]
    assert json.loads(str(component.get('x-material-lesson')))['start'] == LESSON['start']
    context.service.sync_now()
    entries = client.get('/api/plugins/kalender/events?from=2026-11-10&to=2026-11-10').get_json()['events']
    todo = next(e for e in entries if e.get('kind') == 'todo')
    assert todo['lesson']['title'] == '10C MA' and todo['lesson']['location'] == 'G02'


def test_todo_calendar_rejects_events_and_syncs_tasks(app_with_kalender, monkeypatch):
    from icalendar import Calendar
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/settings', json={
        'accounts': [{'label': 'Schule', 'url': 'https://example.test/dav',
                      'calendars': ['Persönlich']}], 'syncIntervalMinutes': 0,
    })
    saved = []
    monkeypatch.setattr(FakeCalendar, 'get_supported_components', lambda self: ['VTODO'], raising=False)
    monkeypatch.setattr(FakeCalendar, 'save_todo', lambda self, data: saved.append(data), raising=False)
    monkeypatch.setattr(FakeCalendar, 'todos', lambda self, **kw: [FakeResource(data) for data in saved], raising=False)
    payload = {'title': 'Bretzel-Abfrage 10c', 'date': '2026-11-06', 'account': 'Schule', 'calendar': 'Persönlich'}
    response = client.post('/api/plugins/kalender/events', json=payload)
    assert response.status_code == 400
    assert 'Eintragstyp' in response.get_json()['error']['message']
    response = client.post('/api/plugins/kalender/events', json={**payload, 'kind': 'todo'})
    assert response.status_code == 201
    component = Calendar.from_ical(saved[0]).walk('VTODO')[0]
    assert component.decoded('due') == date(2026, 11, 6)
    assert not Calendar.from_ical(saved[0]).walk('VEVENT')
    service = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender'].service
    service.sync_now()
    entries = client.get('/api/plugins/kalender/events?from=2026-11-06&to=2026-11-06').get_json()['events']
    assert len(entries) == 1 and entries[0]['kind'] == 'todo'


def test_today_tasks_include_old_and_undated_and_preserve_deadline(app_with_kalender):
    client = app_with_kalender.test_client()
    for title, day in [('Alt', '2001-01-01'), ('Eingang', ''), ('Später', '2099-01-01')]:
        assert client.post('/api/plugins/kalender/events', json={
            'kind': 'todo', 'title': title, 'date': day, 'unitPath': 'unterricht/einheit',
        }).status_code == 201
    tasks = client.get('/api/plugins/kalender/tasks').get_json()['tasks']
    assert len(tasks) == 3
    old = next(t for t in tasks if t['title'] == 'Alt')
    assert old['unitPath'] == 'unterricht/einheit'
    assert client.post('/api/plugins/kalender/tasks', json={
        'id': old['id'], 'action': 'plan', 'plannedDate': '2026-11-06',
    }).status_code == 200
    old = next(t for t in client.get('/api/plugins/kalender/tasks').get_json()['tasks'] if t['title'] == 'Alt')
    assert old['plannedDate'] == '2026-11-06' and old['startDate'] == '2001-01-01'
    assert client.post('/api/plugins/kalender/tasks', json={
        'id': old['id'], 'action': 'plan', 'plannedDate': 'unsinn',
    }).status_code == 400
    assert client.post('/api/plugins/kalender/tasks', json={'id': old['id'], 'action': 'complete'}).status_code == 200
    assert len(client.get('/api/plugins/kalender/tasks').get_json()['tasks']) == 2
    assert client.get('/api/plugins/kalender/events?from=2001-01-01&to=2001-01-01').get_json()['events'] == []
    assert client.post('/api/plugins/kalender/tasks', json={'id': old['id'], 'action': 'complete'}).status_code == 400


def test_remote_task_completion_and_failure(app_with_kalender, monkeypatch):
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/settings', json={
        'accounts': [{'label': 'Schule', 'url': 'https://example.test/dav', 'calendars': ['Persönlich']}],
        'syncIntervalMinutes': 0,
    })
    saved = []
    monkeypatch.setattr(FakeCalendar, 'get_supported_components', lambda self: ['VTODO'], raising=False)
    monkeypatch.setattr(FakeCalendar, 'save_todo', lambda self, data: saved.append(data), raising=False)
    resource = []
    monkeypatch.setattr(FakeCalendar, 'todos', lambda self, **kw: resource, raising=False)
    assert client.post('/api/plugins/kalender/events', json={
        'kind': 'todo', 'title': 'Ohne Frist', 'account': 'Schule', 'calendar': 'Persönlich',
    }).status_code == 201
    task = client.get('/api/plugins/kalender/tasks').get_json()['tasks'][0]
    assert task['startDate'] == ''
    remote = FakeResource(saved[0])
    resource.append(remote)
    def fail():
        raise ConnectionError('secret connection details')
    remote.complete = fail
    response = client.post('/api/plugins/kalender/tasks', json={'id': task['id'], 'action': 'complete'})
    assert response.status_code == 400 and 'secret' not in response.get_data(as_text=True)
    assert len(client.get('/api/plugins/kalender/tasks').get_json()['tasks']) == 1
    completed = []
    remote.complete = lambda: completed.append(True)
    assert client.post('/api/plugins/kalender/tasks', json={'id': task['id'], 'action': 'complete'}).status_code == 200
    assert completed == [True]
    assert client.get('/api/plugins/kalender/tasks').get_json()['tasks'] == []


def test_browser_today_plans_and_completes_tasks(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/events', json={'kind': 'todo', 'title': 'Kopieren', 'date': '2001-01-01'})
    client.post('/api/plugins/kalender/events', json={'kind': 'todo', 'title': 'Idee'})
    with LiveServer(app_with_kalender, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        # Ohne Ansicht-Wahl startet die App inzwischen in den Unterrichtseinheiten;
        # dieser Test prueft die Heute-Ansicht und waehlt sie daher explizit.
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:active-view", "heute")')
        page.goto(url, wait_until='networkidle')
        page.wait_for_selector('#viewSection-heute:not([hidden]) .kal-task')
        page.set_viewport_size({'width': 480, 'height': 900})
        # Unter 1200 px liegt der Index (und damit die Heute-Ansicht) in der Navigationsschublade.
        page.locator('#workspaceNavigation').click()
        section = page.locator('#viewSection-heute')
        for kind, label in [('event', 'Termin'), ('todo', 'TODO')]:
            section.get_by_role('button', name=f'{label} für heute erstellen').click()
            modal = page.locator('#kalCreateModal')
            assert modal.locator('[name=kind]').input_value() == kind
            assert modal.locator('[name=date]').input_value() == page.evaluate(
                "new Date().toLocaleDateString('sv-SE')")
            modal.get_by_role('button', name='Schließen').click()
        row = page.locator('.kal-task').filter(has_text='Kopieren')
        assert row.locator('.kal-task-content .kal-task-actions').count() == 1
        assert not row.locator('.kal-task-plan').evaluate('(el) => el.open')
        row.get_by_role('button', name='Heute einplanen').click()
        page.wait_for_function("document.querySelector('[data-today-tasks]').textContent.includes('Geplant:')")
        assert '01.01.2001' in row.inner_text()
        assert row.get_by_role('button', name='Heute einplanen').count() == 0
        assert 'Heute eingeplant' in row.inner_text()
        row.get_by_role('checkbox', name='Kopieren erledigen').check()
        page.wait_for_selector(".kal-task-completed")
        assert row.get_by_role('checkbox').is_checked()
        assert row.locator('.kal-event-title').evaluate("el => getComputedStyle(el).textDecorationLine") == 'line-through'
        page.reload(wait_until='networkidle')
        page.locator('#workspaceNavigation').click()
        page.get_by_text('Eingang · ohne Datum', exact=False).click()
        page.wait_for_selector('.kal-task')
        assert page.locator('.kal-task-completed').count() == 1
        assert 'Idee' in page.locator('.kal-task:not(.kal-task-completed)').inner_text()
        assert not errors
        browser.close()


class _CompletableResource(FakeResource):
    def __init__(self, ics: str, on_complete):
        super().__init__(ics)
        self._on_complete = on_complete

    def complete(self, *args, **kwargs):
        self._on_complete(args, kwargs)


def _caldav_todo_service(app, rrule, on_complete):
    """Service mit einem synchronisierten CalDAV-TODO, dessen complete() aufgezeichnet wird."""
    ics = (
        'BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTODO\nUID:aufgabe-1\nDTSTAMP:20261020T080000Z\n'
        'DUE:20261109\n' + rrule + 'SUMMARY:Kopieren\nEND:VTODO\nEND:VCALENDAR\n'
    )

    class TodoCalendar(FakeCalendar):
        def get_supported_components(self):
            return ['VTODO']

        def todos(self, include_completed=False):
            _ = include_completed
            return [_CompletableResource(ics, on_complete)]

    service = app.extensions['material_runtime'].plugins.contexts['kalender'].service
    service.client_factory = lambda account: FakeClient([TodoCalendar('Aufgaben', ics)])
    client = app.test_client()
    client.post('/api/plugins/kalender/settings', json={
        'accounts': [{'label': 'Schule', 'url': 'https://example.test/dav', 'calendars': ['Aufgaben']}],
        'syncIntervalMinutes': 0,
    })
    assert service.sync_now()['ok']
    tasks = client.get('/api/plugins/kalender/tasks').get_json()['tasks']
    assert len(tasks) == 1
    return client, tasks[0]


@pytest.mark.parametrize('rrule,expected', [
    ('RRULE:FREQ=WEEKLY\n', {'handle_rrule': True}),
    ('', {}),
])
def test_completing_caldav_todo_keeps_series_alive(app_with_kalender, rrule, expected):
    """P1 aus heute-todos-2026-11-06: Erledigen einer Serie darf sie nicht beenden;
    caldav legt nur mit handle_rrule=True die naechste Wiederholung an."""
    calls = []
    client, task = _caldav_todo_service(app_with_kalender, rrule, lambda args, kwargs: calls.append((args, kwargs)))
    assert task['recurring'] is bool(rrule)
    response = client.post('/api/plugins/kalender/tasks', json={'id': task['id'], 'action': 'complete'})
    assert response.status_code == 200, response.get_json()
    assert calls == [((), expected)]


def test_completing_recurring_caldav_todo_fails_safe_on_old_caldav(app_with_kalender):
    """Kennt caldav handle_rrule nicht, darf die Serie weder beendet noch lokal als erledigt markiert werden."""
    def old_caldav(args, kwargs):
        if kwargs:
            raise TypeError("complete() got an unexpected keyword argument 'handle_rrule'")
        raise AssertionError('Ohne handle_rrule darf eine Serie nie abgeschlossen werden')

    client, task = _caldav_todo_service(app_with_kalender, 'RRULE:FREQ=WEEKLY\n', old_caldav)
    response = client.post('/api/plugins/kalender/tasks', json={'id': task['id'], 'action': 'complete'})
    assert response.status_code == 400
    assert 'Wiederkehrende Aufgaben' in response.get_json()['error']['message'] or 'nicht abgeschlossen' in response.get_json()['error']['message']
    remaining = client.get('/api/plugins/kalender/tasks').get_json()['tasks']
    assert [entry['id'] for entry in remaining] == [task['id']]
    assert not remaining[0].get('completed') and remaining[0].get('status') != 'COMPLETED'


def test_browser_failed_plan_restores_confirmed_date(app_with_kalender):
    """P2 aus heute-todos-2026-11-06: Lehnt der Server das Einplanen ab, darf das Feld
    nicht das abgelehnte Datum zeigen."""
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/events', json={'kind': 'todo', 'title': 'Kopieren', 'date': '2001-01-01'})
    with LiveServer(app_with_kalender, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:active-view", "heute")')
        page.route('**/api/plugins/kalender/tasks', lambda route: route.fulfill(
            status=400, json={'error': {'code': 'invalid_input', 'message': 'Bitte ein gültiges Planungsdatum angeben.'}}
        ) if route.request.method == 'POST' else route.continue_())
        page.goto(url, wait_until='networkidle')
        page.wait_for_selector('#viewSection-heute:not([hidden]) .kal-task')
        row = page.locator('.kal-task').filter(has_text='Kopieren')
        row.locator('.kal-task-plan summary').click()
        field = row.locator('[data-task-plan]')
        assert field.input_value() == ''
        field.fill('2030-05-05')
        page.wait_for_function("document.body.textContent.includes('gültiges Planungsdatum')")
        assert page.locator('[data-task-plan]').first.input_value() == ''
        browser.close()


def test_sync_keeps_tasks_outside_event_window(app_with_kalender, monkeypatch):
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/settings', json={
        'accounts': [{'label': 'Schule', 'url': 'https://example.test/dav', 'calendars': ['Persönlich']}],
        'syncIntervalMinutes': 0,
    })
    saved = []
    monkeypatch.setattr(FakeCalendar, 'get_supported_components', lambda self: ['VTODO'], raising=False)
    monkeypatch.setattr(FakeCalendar, 'save_todo', lambda self, data: saved.append(data), raising=False)
    monkeypatch.setattr(FakeCalendar, 'todos', lambda self, **kw: [FakeResource(data) for data in saved], raising=False)
    for day in ['', '2001-01-01', '2099-01-01']:
        assert client.post('/api/plugins/kalender/events', json={
            'kind': 'todo', 'title': 'Vorbereitung', 'date': day,
            'account': 'Schule', 'calendar': 'Persönlich', 'unitPath': 'unterricht/einheit',
        }).status_code == 201
    service = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender'].service
    assert service.sync_now()['ok']
    tasks = client.get('/api/plugins/kalender/tasks').get_json()['tasks']
    assert {t['startDate'] for t in tasks} == {'', '2001-01-01', '2099-01-01'}
    assert all(t['unitPath'] == 'unterricht/einheit' for t in tasks)


@pytest.mark.parametrize('scenario', ['loading', 'missing', 'error', 'settings', 'stale'])
def test_browser_calendar_initialization_safety(app_with_kalender, scenario):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    with LiveServer(app_with_kalender, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:active-view", "agenda")')
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.route('**/api/plugins/kalender/settings', lambda route: route.fulfill(json={
            'accounts': [], 'timezone': 'Europe/Berlin', 'syncIntervalMinutes': 0,
            'windowPastDays': 30, 'windowFutureDays': 120,
            'defaultEventCalendar': {'account': 'Schule', 'name': 'Persönlich'},
        }))
        pending = []
        page.route('**/api/plugins/kalender/calendars', lambda route: pending.append(route))
        page.goto(url, wait_until='networkidle')
        section = page.locator('#viewSection-agenda')
        if scenario == 'settings':
            section.locator('.kal-tools summary').click()
            section.locator('[data-kal=settings]').click()
            page.wait_for_selector('#kalSettingsModal.open')
            assert pending  # Der Dialog ist schon vor der Remote-Antwort benutzbar.
            page.locator('[data-kal-field=timezone]').fill('Europe/London')
            pending.pop().fulfill(json={'calendars': [], 'errors': []})
            page.wait_for_function("!document.querySelector('[data-kal-settings-hint]').textContent.includes('werden geladen')")
            assert page.locator('[data-kal-field=timezone]').input_value() == 'Europe/London'
        else:
            section.get_by_role('button', name='Termin erstellen', exact=True).click()
            form = page.locator('#kalCreateModal form')
            save = form.locator('[type=submit]')
            form.locator('[name=title]').fill('Audit')
            assert save.is_disabled()
            assert form.locator('[name=calendarTarget]').is_disabled()
            if scenario == 'stale':
                old = pending.pop()
                page.locator('#kalCreateModal [data-close]').last.click()
                section.get_by_role('button', name='Termin erstellen', exact=True).click()
                form.locator('[name=title]').fill('Neuer Dialog')
                old.fulfill(json={'calendars': [{'account': 'Alt', 'name': 'Veraltet'}], 'errors': []})
                page.wait_for_timeout(100)
                assert save.is_disabled()
                assert form.locator('[name=calendarTarget] option').count() == 1
            if scenario == 'error':
                pending.pop().abort()
            else:
                calendars = [{'account': 'Schule', 'name': 'Persönlich'}] if scenario in ('loading', 'stale') else []
                pending.pop().fulfill(json={'calendars': calendars, 'errors': []})
            page.wait_for_function("!document.querySelector('#kalCreateModal [name=calendarTarget]').disabled")
            if scenario in ('loading', 'stale'):
                assert save.is_enabled()
                assert 'Persönlich' in form.locator('[name=calendarTarget]').input_value()
            else:
                assert save.is_disabled()
                assert 'Bitte einen Kalender auswählen' in form.locator('[data-calendar-hint]').inner_text()
                form.locator('[name=calendarTarget]').select_option('')  # Bewusst lokal speichern.
                assert save.is_enabled()
                page.route('**/api/plugins/kalender/events', lambda route: route.fulfill(status=201, json={}))
                with page.expect_request(lambda r: r.method == 'POST' and r.url.endswith('/kalender/events')) as request:
                    save.click()
                assert request.value.post_data_json['account'] == ''
        browser.close()


def test_visibility_survives_refresh_and_filters_tasks_and_events(app_with_kalender):
    client = app_with_kalender.test_client()
    service = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender'].service
    # Synchronisierte Daten zweier Kalender, ohne Remote-Schreibzugriff.
    entries = [dict(key=uid, uid=uid, title=uid, kind=kind, account='Familie',
                    calendar=calendar, startDate='2026-11-06', endDate='2026-11-06',
                    allDay=True, start='2026-11-06', end='2026-11-06')
               for uid, kind, calendar in [('fremd', 'todo', 'Partnerin'),
                                           ('termin', 'event', 'Partnerin'),
                                           ('eigen', 'todo', 'Privat')]]
    service.storage.write_json(service._cache_path(), {'events': entries})
    calendar_id = service._calendar_identity(entries[0])
    def events():
        return client.get('/api/plugins/kalender/events?from=2026-11-06&to=2026-11-06').get_json()['events']
    def tasks():
        return client.get('/api/plugins/kalender/tasks').get_json()['tasks']
    assert len(events()) == 3
    assert client.post('/api/plugins/kalender/visibility', json={
        'scope': 'calendars', 'id': calendar_id, 'hidden': True, 'label': 'Partnerin',
    }).status_code == 200
    assert [t['uid'] for t in tasks()] == ['eigen']
    assert [e['uid'] for e in events()] == ['eigen']
    # Ein erneuter Sync darf die lokale Auswahl nicht überschreiben.
    service.storage.write_json(service._cache_path(), {'events': entries})
    assert len(events()) == 1
    client.post('/api/plugins/kalender/visibility', json={
        'scope': 'calendars', 'id': calendar_id, 'hidden': False})
    task_id = service._task_identity(entries[0])
    client.post('/api/plugins/kalender/visibility', json={
        'scope': 'entries', 'id': task_id, 'hidden': True, 'label': 'fremd'})
    entries[0]['title'] = 'Umbenannt'
    service.storage.write_json(service._cache_path(), {'events': entries})
    assert len(tasks()) == 1
    assert len(events()) == 2
    assert client.get('/api/plugins/kalender/visibility').get_json()['hiddenEntries'] == {task_id: 'fremd'}
    client.post('/api/plugins/kalender/visibility', json={
        'scope': 'entries', 'id': task_id, 'hidden': False})
    assert len(tasks()) == 2
    assert len(events()) == 3


@pytest.mark.parametrize('payload', [{}, {'scope': 'entries', 'id': 'x', 'hidden': 'false'},
                                     {'scope': 'invalid', 'id': 'x', 'hidden': True}])
def test_visibility_rejects_invalid_payload(app_with_kalender, payload):
    assert app_with_kalender.test_client().post('/api/plugins/kalender/visibility', json=payload).status_code == 400


def test_browser_hide_and_restore_task(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/events', json={
        'kind': 'todo', 'title': 'Fremde Aufgabe', 'date': '2001-01-01'})
    with LiveServer(app_with_kalender, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:active-view", "heute")')
        page.goto(url, wait_until='networkidle')
        section = page.locator('#viewSection-heute')
        section.locator('[data-task-action=hide]').click()
        page.wait_for_function('document.querySelectorAll("#viewSection-heute .kal-task").length === 0')
        section.get_by_role('button', name='Sichtbarkeit', exact=True).click()
        modal = page.locator('#kalVisibilityModal')
        modal.get_by_label('Fremde Aufgabe', exact=True).check()
        page.wait_for_function('document.querySelectorAll("#viewSection-heute .kal-task").length === 1')
        assert '1 überfällig' in section.locator('[data-today-summary]').inner_text()
        browser.close()


def test_today_badge_updates_without_fetching_events_on_other_views(app_with_kalender):
    """Das Rail-Badge haengt nur am guenstigen tasks-Endpunkt; events() (externe
    Kalenderquellen + Einheiten-Abgleich) wird nur geladen, waehrend 'Heute' sichtbar ist."""
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/events', json={
        'kind': 'todo', 'title': 'Ueberfaellig', 'date': '2001-01-01'})
    with LiveServer(app_with_kalender, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:active-view", "folder")')
        requests = []
        page.on('request', lambda request: requests.append(request.url))
        page.goto(url, wait_until='networkidle')
        page.wait_for_function(
            "document.querySelector('#viewButton-heute .kal-today-badge')?.textContent === '1'")
        assert not any('/api/plugins/kalender/events' in u for u in requests)
        page.locator('#viewButton-heute').click()
        page.wait_for_selector('#viewSection-heute .kal-task')
        page.wait_for_timeout(200)
        assert any('/api/plugins/kalender/events' in u for u in requests)
        browser.close()


def test_browser_today_event_context_and_narrow_layout(app_with_kalender, tmp_path):
    from datetime import datetime

    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    client = app_with_kalender.test_client()
    day = date.today().isoformat()
    for title, start, end in [('Vorbei', '09:00', '10:00'), ('Unterricht', '11:00', '13:00'), ('Konferenz', '14:00', '15:30')]:
        response = client.post('/api/plugins/kalender/events', json={
            'title': title, 'date': day, 'time': start, 'endTime': end, 'location': 'Raum 204',
        })
        assert response.status_code < 300
    with LiveServer(app_with_kalender, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        page.clock.set_fixed_time(datetime.combine(date.today(), datetime.min.time()).replace(hour=12))
        page.add_init_script('localStorage.setItem("material-ui:active-view", "heute")')
        page.goto(url, wait_until='networkidle')
        section = page.locator('#viewSection-heute')
        section.locator('.kal-today-event').first.wait_for()
        assert section.locator('.kal-event-past').inner_text().find('Vorbei') >= 0
        current = section.locator('.kal-today-event').filter(has_text='Unterricht')
        assert 'Läuft gerade' in current.inner_text()
        assert '11:00–13:00' in current.inner_text()
        assert 'Raum 204' in current.inner_text()
        assert 'Als Nächstes' in section.locator('.kal-today-event').filter(has_text='Konferenz').inner_text()
        assert section.evaluate("el => !!(el.querySelector('[data-today-events]').compareDocumentPosition(el.querySelector('[data-today-tasks]')) & Node.DOCUMENT_POSITION_FOLLOWING)")
        page.set_viewport_size({'width': 390, 'height': 844})
        assert section.evaluate('el => el.scrollWidth <= el.clientWidth + 1')
        page.screenshot(path=str(tmp_path / 'heute.png'), full_page=True)
        browser.close()


def test_browser_today_can_switch_to_morgen(app_with_kalender):
    """Die Heute-Seite schaltet per Umschalter auf morgen um: Termine, Aufgabengruppen,
    Einplanen und Erstellen beziehen sich dann auf den morgigen Tag (Vorbereitung)."""
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    from datetime import timedelta
    client = app_with_kalender.test_client()
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert client.post('/api/plugins/kalender/events', json={
        'kind': 'todo', 'title': 'Heute faellig', 'date': today}).status_code == 201
    assert client.post('/api/plugins/kalender/events', json={
        'kind': 'todo', 'title': 'Morgen faellig', 'date': tomorrow}).status_code == 201
    assert client.post('/api/plugins/kalender/events', json={
        'title': 'Morgen-Termin', 'date': tomorrow, 'time': '08:00', 'endTime': '09:00'}).status_code == 201
    # Stundenplan-Quelle fuer morgen; eine Stunde wird als Ausfall markiert.
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    stunden = [
        source_event('stunde-1', title='10C MA', start=f'{tomorrow}T07:55:00+01:00',
                     end=f'{tomorrow}T08:40:00+01:00', startDate=tomorrow, endDate=tomorrow, location='G02'),
        source_event('stunde-2', title='05C MA', start=f'{tomorrow}T09:45:00+01:00',
                     end=f'{tomorrow}T10:30:00+01:00', startDate=tomorrow, endDate=tomorrow, location='E32'),
    ]
    context.service('calendar').register_source(lambda start, end: [e for e in stunden if start <= e['startDate'] <= end])
    lesson_event = next(e for e in client.get(
        f'/api/plugins/kalender/events?from={tomorrow}&to={tomorrow}').get_json()['events']
        if e['title'] == '10C MA')
    assert client.post('/api/plugins/kalender/lesson-cancellation', json={
        'id': lesson_event['lessonId'], 'datum': tomorrow, 'cancelled': True}).status_code == 200
    with LiveServer(app_with_kalender, free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:active-view", "heute")')
        page.goto(url, wait_until='networkidle')
        section = page.locator('#viewSection-heute')
        section.locator('.kal-task').first.wait_for()
        # Standard ist die heutige Ansicht; das Rail-Badge zaehlt nur heute.
        assert 'für heute' in section.locator('[data-today-summary]').inner_text()
        assert section.locator('[data-today-title]').text_content() == 'Heute'
        assert section.locator('#kalTodayEventsTitle').text_content() == 'Heutige Termine'
        assert 'Morgen-Termin' not in section.locator('[data-today-events]').inner_text()
        assert section.locator('.kal-task-group', has_text='Morgen fällig').count() == 0
        # Heute gibt es keine Unterrichtsstunden: der Stundenblock bleibt versteckt.
        assert section.locator('[data-today-lessons-section]').is_hidden()
        page.wait_for_function(
            "document.querySelector('#viewButton-heute .kal-today-badge')?.textContent === '1'")
        # Umschalten auf morgen
        section.get_by_role('button', name='Morgen', exact=True).click()
        page.wait_for_function(
            "document.querySelector('#viewSection-heute [data-today-summary]').textContent.includes('für morgen')")
        assert section.locator('[data-today-mode="morgen"]').get_attribute('aria-pressed') == 'true'
        assert section.locator('[data-today-title]').text_content() == 'Morgen'
        assert section.locator('#kalTodayEventsTitle').text_content() == 'Morgige Termine'
        expected_date = page.evaluate(
            "d => new Date(d + 'T12:00:00').toLocaleDateString('de-DE',"
            " { weekday: 'long', day: '2-digit', month: 'long' })", tomorrow)
        assert section.locator('[data-today-date]').inner_text() == expected_date
        events_text = section.locator('[data-today-events]').inner_text()
        assert 'Morgen-Termin' in events_text and '08:00' in events_text
        # Stundenblock zeigt die morgigen Unterrichtsstunden inkl. Ausfall-Markierung.
        lessons_block = section.locator('[data-today-lessons-section]')
        lessons_block.wait_for(state='visible')
        assert section.locator('#kalTodayLessonsTitle').text_content() == 'Morgige Unterrichtsstunden'
        row10 = lessons_block.locator('.kal-lesson', has_text='10C MA')
        assert '07:55–08:40' in row10.inner_text() and 'G02' in row10.inner_text()
        assert row10.locator('.kal-lesson-cancelled-tag').count() == 1
        assert 'Ausfall' in row10.inner_text()
        assert lessons_block.locator('.kal-lesson', has_text='05C MA').count() == 1
        # Klick auf eine Stunde oeffnet den Termindialog.
        lessons_block.locator('.kal-lesson', has_text='05C MA').get_by_role('button', name='05C MA').click()
        page.wait_for_selector('#kalEventModal.open')
        assert '05C MA' in page.locator('#kalEventModal').inner_text()
        page.locator('#kalEventModal').get_by_role('button', name='Schließen').click()
        # Relativ zu morgen ist "Heute faellig" ueberfaellig, "Morgen faellig" faellig.
        assert '2 offene Aufgaben für morgen · 1 überfällig' in section.locator('[data-today-summary]').inner_text()
        assert 'Heute faellig' in section.locator('.kal-task-group', has_text='Überfällig').inner_text()
        assert 'Morgen faellig' in section.locator('.kal-task-group', has_text='Morgen fällig / eingeplant').inner_text()
        # Erstellen und Einplanen beziehen sich auf morgen.
        section.get_by_role('button', name='Termin für morgen erstellen').click()
        modal = page.locator('#kalCreateModal')
        assert modal.locator('[name=date]').input_value() == tomorrow
        modal.get_by_role('button', name='Schließen').click()
        row = section.locator('.kal-task').filter(has_text='Morgen faellig')
        row.get_by_role('button', name='Morgen einplanen').click()
        page.wait_for_function(
            "document.querySelector('#viewSection-heute').textContent.includes('Morgen eingeplant')")
        planned = next(t for t in client.get('/api/plugins/kalender/tasks').get_json()['tasks']
                       if t['title'] == 'Morgen faellig')
        assert planned['plannedDate'] == tomorrow
        # Der Modus bleibt ueber einen Reload hinaus gespeichert.
        page.reload(wait_until='networkidle')
        section.locator('.kal-task').first.wait_for()
        page.wait_for_function(
            "document.querySelector('#viewSection-heute [data-today-summary]').textContent.includes('für morgen')")
        assert section.locator('[data-today-mode="morgen"]').get_attribute('aria-pressed') == 'true'
        assert section.locator('[data-today-title]').text_content() == 'Morgen'
        # Zurück auf heute
        section.get_by_role('button', name='Heute', exact=True).click()
        page.wait_for_function(
            "document.querySelector('#viewSection-heute [data-today-summary]').textContent.includes('für heute')")
        assert section.locator('[data-today-title]').text_content() == 'Heute'
        assert 'Morgen-Termin' not in section.locator('[data-today-events]').inner_text()
        assert section.locator('[data-today-lessons-section]').is_hidden()
        assert section.get_by_role('button', name='Termin für heute erstellen').count() == 1
        assert not errors
        browser.close()


def test_browser_agenda_shows_undated_overdue_and_planned_todos(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    client = app_with_kalender.test_client()
    today = date.today().isoformat()
    for title, day in [('Ohne Datum', ''), ('Überfällige Aufgabe', '2001-01-01'), ('Heute fällig', today), ('Eingeplant', '')]:
        assert client.post('/api/plugins/kalender/events', json={
            'kind': 'todo', 'title': title, 'date': day,
        }).status_code == 201
    planned = next(t for t in client.get('/api/plugins/kalender/tasks').get_json()['tasks'] if t['title'] == 'Eingeplant')
    from datetime import timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert client.post('/api/plugins/kalender/tasks', json={
        'id': planned['id'], 'action': 'plan', 'plannedDate': tomorrow,
    }).status_code == 200
    with LiveServer(app_with_kalender, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:active-view", "agenda")')
        page.goto(url, wait_until='networkidle')
        section = page.locator('#viewSection-agenda')
        section.get_by_role('button', name='Ohne Datum', exact=True).wait_for()
        today_entries = section.locator('.kal-agenda-day.today + .kal-agenda-events')
        assert 'Ohne Datum' in today_entries.inner_text()
        assert 'Überfällige Aufgabe' in today_entries.inner_text()
        assert 'Heute fällig' in today_entries.inner_text()
        assert 'Eingeplant' not in today_entries.inner_text()
        assert 'Ohne Frist' in today_entries.inner_text()
        assert 'Überfällig seit' in today_entries.inner_text()
        assert section.get_by_role('button', name='Eingeplant', exact=True).count() == 1
        section.get_by_role('button', name='Ohne Datum', exact=True).click()
        assert page.locator('#kalEventModal').inner_text().find('Ohne Datum') >= 0
        browser.close()


def test_calendar_selection_filters_events_and_todos_separately(app_with_kalender):
    service = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender'].service
    service.replace_settings({
        **service.settings_payload(),
        'selectedEventCalendars': [{'account': '', 'name': 'Stundenplan'}],
        'selectedTodoCalendars': [],
    })
    visibility = {'entries': {}, 'calendars': {}}
    assert not service._is_hidden(source_event(), visibility)
    assert service._is_hidden(source_event(calendar='Andere'), visibility)
    assert service._is_hidden(source_event(kind='todo'), visibility)


@pytest.mark.parametrize('kind', ['event', 'todo'])
def test_edit_entry_preserves_identity_and_validates(app_with_kalender, kind):
    client = app_with_kalender.test_client()
    original = client.post('/api/plugins/kalender/events', json={
        'kind': kind, 'title': 'Vorher', 'date': '2026-11-06', 'description': 'Details',
    }).json
    payload = {'key': original['key'], 'originalAccount': '', 'originalCalendar': 'Lokale Termine',
               'kind': kind, 'title': 'Nachher', 'date': '2026-11-07', 'calendar': 'Lokale Termine'}
    response = client.patch('/api/plugins/kalender/events', json=payload)
    assert response.status_code == 200
    assert response.json['key'] == original['key']
    entries = client.get('/api/plugins/kalender/events?from=2026-11-06&to=2026-11-08').json['events']
    assert [(e['title'], e['startDate']) for e in entries] == [('Nachher', '2026-11-07')]
    assert client.patch('/api/plugins/kalender/events', json={**payload, 'title': ''}).status_code == 400
    assert client.patch('/api/plugins/kalender/events', json={**payload, 'key': 'missing'}).status_code == 400


def test_edit_local_entry_moves_to_hidden_calendar(app_with_kalender, monkeypatch):
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/settings', json={
        'accounts': [{'label': 'Schule', 'url': 'https://example.test/dav'}],
        'selectedEventCalendars': [], 'syncIntervalMinutes': 0,
    })
    saved = []
    monkeypatch.setattr(FakeCalendar, 'save_event', lambda self, data: saved.append((self.name, data)), raising=False)
    original = client.post('/api/plugins/kalender/events', json={'title': 'Verschieben', 'date': '2026-11-06'}).json
    response = client.patch('/api/plugins/kalender/events', json={
        'key': original['key'], 'originalAccount': '', 'originalCalendar': 'Lokale Termine',
        'title': 'Verschoben', 'date': '2026-11-06', 'account': 'Schule', 'calendar': 'Persönlich',
    })
    assert response.status_code == 200
    assert len(saved) == 1
    assert saved[0][0] == 'Persönlich'
    service = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender'].service
    assert service.storage.read_json(service.storage.path('local-events.json'), default=[]) == []


@pytest.mark.parametrize('move,fail_delete', [(False, False), (True, False), (True, True)])
def test_edit_remote_preserves_properties_and_rolls_back_move(app_with_kalender, monkeypatch, move, fail_delete):
    from icalendar import Calendar
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/settings', json={
        'accounts': [{'label': 'Schule', 'url': 'https://example.test/dav'}], 'syncIntervalMinutes': 0,
    })
    document = Calendar.from_ical(ICS)
    component = document.walk('VEVENT')[0]
    component.add('x-custom', 'behalten')
    document.subcomponents = [component]
    resource = FakeResource(document.to_ical())
    calls = []
    monkeypatch.setattr(FakeCalendar, 'events', lambda self: [resource], raising=False)
    monkeypatch.setattr(resource, 'save', lambda: calls.append('save'), raising=False)
    def delete():
        calls.append('delete')
        if fail_delete:
            raise RuntimeError('delete failed')
    monkeypatch.setattr(resource, 'delete', delete, raising=False)
    class Saved:
        def delete(self):
            calls.append('rollback')
    def save(self, data):
        assert 'X-CUSTOM:behalten' in data
        assert 'SUMMARY:Geändert' in data
        calls.append('target')
        return Saved()
    monkeypatch.setattr(FakeCalendar, 'save_event', save, raising=False)
    service = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender'].service
    from zoneinfo import ZoneInfo
    original = service._normalise_occurrence(component, 'Schule', 'Persönlich', ZoneInfo('Europe/Berlin'))
    service.storage.write_json(service._cache_path(), {'events': [original]})
    response = client.patch('/api/plugins/kalender/events', json={
        'key': original['key'], 'originalAccount': 'Schule', 'originalCalendar': 'Persönlich',
        'account': 'Schule', 'calendar': 'Gemietet' if move else 'Persönlich',
        'title': 'Geändert', 'date': '2026-11-05', 'time': '12:00', 'endTime': '13:00',
    })
    assert response.status_code == (400 if fail_delete else 200)
    assert calls == (['target', 'delete', 'rollback'] if fail_delete else ['target', 'delete'] if move else ['save'])
    entries = service.storage.read_json(service._cache_path())['events']
    assert len(entries) == 1
    assert entries[0]['title'] == ('Gesamtkonferenz' if fail_delete else 'Geändert')


def test_completed_tasks_remain_only_on_completion_day(app_with_kalender):
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/events', json={'kind': 'todo', 'title': 'Abhaken'})
    task = client.get('/api/plugins/kalender/tasks').get_json()['tasks'][0]
    assert client.post('/api/plugins/kalender/tasks', json={'id': task['id'], 'action': 'complete'}).status_code == 200
    result = client.get('/api/plugins/kalender/tasks').get_json()
    assert result['tasks'] == []
    assert result['completedTasks'][0]['title'] == 'Abhaken'
    assert result['completedTasks'][0]['status'] == 'COMPLETED'
    service = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender'].service
    path = service.storage.path('completed-tasks.json')
    completed = service.storage.read_json(path, default={})
    completed[task['id']]['completedDate'] = '2000-01-01'
    service.storage.write_json(path, completed)
    result = client.get('/api/plugins/kalender/tasks').get_json()
    assert result['tasks'] == []
    assert result['completedTasks'] == []


@pytest.mark.parametrize('kind', ['event', 'todo'])
def test_browser_edits_popup_entry(app_with_kalender, kind):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    app = app_with_kalender
    try:
        client = app.test_client()
        client.get("/api/plugins")
        response = client.post('/api/plugins/kalender/events', json={
            'kind': kind, 'title': 'Popup bearbeiten', 'date': date.today().isoformat(),
        })
        assert response.status_code == 201
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.add_init_script('localStorage.setItem("material-ui:active-view", "heute")')
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until='networkidle')
            page.locator('#viewSection-heute [data-event-key]', has_text='Popup bearbeiten').first.click()
            page.locator('#kalEventModal [data-edit-entry]').click()
            editor = page.locator('#kalCreateModal')
            assert editor.locator('[name=title]').input_value() == 'Popup bearbeiten'
            editor.locator('[name=title]').fill('Popup geändert')
            editor.get_by_role('button', name='Speichern', exact=True).click()
            page.wait_for_function("!document.querySelector('#kalCreateModal').classList.contains('open')")
            page.locator('#viewSection-heute [data-event-key]', has_text='Popup geändert').first.wait_for()
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


# ---------------------------------------------------------------- Regressionen


def test_recurring_todo_angelegt_und_als_recurring_markiert(app_with_kalender):
    """Wiederkehrendes TODO anlegen: RRULE landet im lokalen Eintrag."""
    client = app_with_kalender.test_client()
    response = client.post('/api/plugins/kalender/events', json={
        'kind': 'todo', 'title': 'Wöchentlich', 'date': '2026-11-09',
        'recurrence': {'freq': 'WEEKLY', 'interval': 1, 'until': ''},
    })
    assert response.status_code == 201
    event = response.get_json()
    assert event['recurring'] is True
    tasks = client.get('/api/plugins/kalender/tasks').get_json()['tasks']
    assert tasks and tasks[0]['recurring'] is True


def test_recurring_todo_abgelehnte_freq(app_with_kalender):
    client = app_with_kalender.test_client()
    response = client.post('/api/plugins/kalender/events', json={
        'kind': 'todo', 'title': 'Kaputt', 'date': '2026-11-09',
        'recurrence': {'freq': 'YEARLY', 'interval': 1},
    })
    assert response.status_code == 201  # Unbekannte freq wird als keine Wiederholung behandelt
    assert response.get_json()['recurring'] is False


def test_recurring_caldav_todo_erkennen(app_with_kalender, monkeypatch):
    """Serien-TODO aus CalDAV wird als recurring markiert, damit das Erledigen
    nicht die ganze Serie beendet (P1 aus heute-todos-2026-11-06)."""
    service_module = sys.modules['material_ui_plugins.kalender.service']
    ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:serie-1
DTSTAMP:20261020T080000Z
DTSTART:20261109
DUE:20261109
RRULE:FREQ=WEEKLY
SUMMARY:Wöchentliche Aufgabe
END:VTODO
END:VCALENDAR
"""
    class TodoCalendar(FakeCalendar):
        def get_supported_components(self):
            return ['VEVENT', 'VTODO']

        def todos(self, include_completed=False):
            _ = include_completed
            return [FakeResource(ics)]

    monkeypatch.setattr(service_module, 'default_client_factory',
                        lambda account: FakeClient([TodoCalendar('Aufgaben', ics)]))
    app = create_app(config=AppConfig(app_with_kalender.extensions['material_runtime'].config.root))
    app.testing = True
    try:
        app.test_client().post('/api/plugins/kalender/settings', json={
            'accounts': [{'label': 'Test', 'url': 'https://example.com/dav', 'username': 'u', 'password': 'p', 'calendars': 'Aufgaben'}],
        })
        app.test_client().post('/api/plugins/kalender/sync')
        import time as _time
        for _ in range(20):
            status = app.test_client().get('/api/plugins/kalender/status').get_json()
            if (status.get('lastSync') or {}).get('ok'):
                break
            _time.sleep(0.2)
        tasks = app.test_client().get('/api/plugins/kalender/tasks').get_json()['tasks']
        assert any(t.get('recurring') for t in tasks), 'Serien-TODO muss als recurring markiert sein'
    finally:
        app.extensions['material_runtime'].close()


def test_holiday_calendar_marks_events(app_with_kalender):
    """Ferienkalender-Einstellung: Termine des gewählten Kalenders werden als holiday markiert."""
    client = app_with_kalender.test_client()
    # Lokalen ganztägigen Termin anlegen und als Ferienkalender konfigurieren
    client.post('/api/plugins/kalender/settings', json={
        'accounts': [],
        'holidayCalendar': {'account': '', 'name': 'Lokale Termine'},
    })
    client.post('/api/plugins/kalender/events', json={
        'kind': 'event', 'title': 'Herbstferien', 'date': '2026-10-26', 'endDate': '2026-10-30',
    })
    data = client.get('/api/plugins/kalender/events?from=2026-10-01&to=2026-11-30').get_json()
    assert data['holidayCalendar'] == {'account': '', 'name': 'Lokale Termine'}
    assert any(e.get('holiday') for e in data['events'])
    holidays = client.get('/api/plugins/kalender/holidays?from=2026-10-01&to=2026-11-30').get_json()
    assert '2026-10-26' in holidays['days']
    assert '2026-10-30' in holidays['days']
    assert len(holidays['days']) == 5  # 26.10. bis 30.10.


def test_holiday_calendar_ohne_kalender(app_with_kalender):
    client = app_with_kalender.test_client()
    holidays = client.get('/api/plugins/kalender/holidays?from=2026-10-01&to=2026-11-30').get_json()
    assert holidays['days'] == []
    assert holidays['calendar'] is None


def test_update_task_plan_invalid_date_rejected(app_with_kalender):
    """P2-Nachweis: ungültiges Planungsdatum wird mit 400 abgelehnt, lokaler Stand bleibt."""
    client = app_with_kalender.test_client()
    client.post('/api/plugins/kalender/events', json={'kind': 'todo', 'title': 'Plan-Test', 'date': '2026-11-09'})
    task = client.get('/api/plugins/kalender/tasks').get_json()['tasks'][0]
    response = client.post('/api/plugins/kalender/tasks', json={
        'id': task['id'], 'action': 'plan', 'plannedDate': 'kein-datum',
    })
    assert response.status_code == 400
    # Gültiges Datum danach weiterhin möglich
    ok = client.post('/api/plugins/kalender/tasks', json={
        'id': task['id'], 'action': 'plan', 'plannedDate': '2026-11-10',
    })
    assert ok.status_code == 200


def test_lesson_cancellation_is_local_persistent_and_reversible(app_with_kalender):
    service = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender'].service
    event = source_event(title='05C MA', uid='series')
    other = source_event(key='other', title='05C MA', uid='series', start='2026-11-11T08:00:00+01:00', startDate='2026-11-11', endDate='2026-11-11')
    service.storage.write_json(service.storage.path('local-events.json'), [event, other])
    client = app_with_kalender.test_client()
    url = '/api/plugins/kalender/events?from=2026-11-10&to=2026-11-10'
    lesson = client.get(url).get_json()['events'][0]
    assert lesson['teaching'] == {'klasse': 'klasse-05', 'fach': 'mathematik', 'lerngruppe': '05C'}
    payload = {'id': lesson['lessonId'], 'datum': '2026-11-10', 'cancelled': True}
    assert client.post('/api/plugins/kalender/lesson-cancellation', json=payload).status_code == 200
    assert client.get(url).get_json()['events'][0]['cancelled'] is True
    assert client.get(url.replace('2026-11-10', '2026-11-11')).get_json()['events'][0]['cancelled'] is False
    assert service.storage.read_json(service.storage.path('local-events.json'), default=[]) == [event, other]
    payload['cancelled'] = False
    assert client.post('/api/plugins/kalender/lesson-cancellation', json=payload).status_code == 200
    assert client.get(url).get_json()['events'][0]['cancelled'] is False
    payload['id'] = 'missing'
    assert client.post('/api/plugins/kalender/lesson-cancellation', json=payload).status_code == 400


def test_browser_unit_planning_creates_and_cancels_lesson(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    app = app_with_kalender
    day = date.today().isoformat()
    client = app.test_client()
    assert client.post('/api/units/new', json={
        'fach': 'mathematik', 'klasse': '05', 'thema': 'Zahlen', 'titel': 'Vorhanden', 'datum': day,
    }).status_code == 201
    service = app.extensions['material_runtime'].plugins.contexts['kalender'].service
    # Ein Datum ohne Lerngruppe muss auch ohne Schuljahresvorgabe die
    # Unterrichtsstunde belegen statt zusaetzlich als offen zu erscheinen.
    service.save_group_defaults([])
    first_year = date.today().year - (date.today().month < 8)
    last_lesson = f'{first_year + 1}-07-30'
    service.storage.write_json(service.storage.path('local-events.json'), [source_event(
        title='05C MA', start=f'{day}T08:00:00+01:00', end=f'{day}T09:00:00+01:00', startDate=day, endDate=day),
        source_event(key='later-other-class', title='10C MA', start=f'{last_lesson}T08:00:00+02:00',
                     end=f'{last_lesson}T09:00:00+02:00', startDate=last_lesson, endDate=last_lesson)])
    with LiveServer(app, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script('localStorage.setItem("material-ui:active-view", "units")')
        page.goto(url, wait_until='networkidle')
        page.wait_for_selector('.unit-plan-assigned', state='attached')
        assert page.locator('[data-groups] > .unit-plan-day').count() == 0
        assert page.locator('.unit-planning').count() == 0
        assert page.locator('.unit-plan-boundary', has_text=f'Schuljahr {first_year + 1}/{first_year + 2}').count() == 0
        page.locator('.unit-card > summary').first.click()
        page.locator('.unit-plan-day > summary').first.click()
        page.locator('.unit-plan-slot [data-cancel]').click()
        page.wait_for_selector('.unit-plan-slot.is-cancelled')
        assert page.locator('.unit-plan-slot [data-create]').is_disabled()
        assert page.locator('.unit-card > summary .unit-plan-cancelled').inner_text() == '1 Ausfall'
        page.locator('.unit-plan-slot [data-cancel]').click()
        page.wait_for_selector('.unit-plan-slot:not(.is-cancelled)')
        page.locator('.unit-plan-slot [data-create]').click()
        form = page.locator('.unit-create-form')
        assert form.locator('[name=datum]').input_value() == day
        form.locator('[name=titel]').fill('Geplant')
        # Thema ist eine Auswahlliste vorhandener Themen der Jahrgangsstufe.
        form.locator('[name=thema]').select_option('Zahlen')
        form.locator('[type=submit]').click()
        page.wait_for_function("() => [...document.querySelectorAll('.unit-title')].some(el => el.textContent === 'Geplant')")
        page.wait_for_selector('.unit-plan-boundary')
        assert page.locator('.unit-plan-boundary').count() >= 1
        from datetime import timedelta
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        assigned = source_event(title='05C MA', start=f'{day}T08:00:00+01:00',
                                end=f'{day}T09:00:00+01:00', startDate=day, endDate=day)
        service.storage.write_json(service.storage.path('local-events.json'), [assigned, *[source_event(
            key=f'free-{hour}', title='05C MA', start=f'{tomorrow}T{hour}:00:00+01:00',
            end=f'{tomorrow}T10:00:00+01:00', startDate=tomorrow, endDate=tomorrow,
        ) for hour in ['08', '09']]])
        page.reload(wait_until='networkidle')
        free_day = page.locator('[data-groups] > .unit-plan-day')
        free_day.wait_for()
        assert free_day.count() == 1
        assert 'Noch offen · 2 Std.' in free_day.locator('summary').inner_text()
        assert not free_day.locator('[data-create]').first.is_visible()
        free_day.locator('summary').click()
        assert free_day.locator('[data-create]').count() == 2
        # Multi-day holidays suppress assigned and free slots, even when their
        # calendar is hidden in the regular calendar selection.
        assert client.post('/api/plugins/kalender/settings', json={
            'accounts': [], 'holidayCalendar': {'account': '', 'name': 'Ferien'},
            'selectedEventCalendars': [{'account': '', 'name': 'Stundenplan'}],
        }).status_code == 200
        local_path = service.storage.path('local-events.json')
        lessons = service.storage.read_json(local_path, default=[])
        service.storage.write_json(local_path, [*lessons, source_event(
            key='holiday', title='Ferien', calendar='Ferien', allDay=True,
            startDate=day, endDate=tomorrow, start=day, end=tomorrow,
        )])
        page.reload(wait_until='networkidle')
        page.wait_for_selector('.unit-plan-boundary')
        assert page.locator('.unit-plan-day').count() == 0
        assert page.locator('.unit-card').count() == 2
        # Without an explicit selection the loaded Ferien calendar is detected.
        assert client.post('/api/plugins/kalender/settings', json={
            'accounts': [], 'holidayCalendar': None, 'selectedEventCalendars': None,
        }).status_code == 200
        page.reload(wait_until='networkidle')
        page.wait_for_selector('.unit-plan-boundary')
        assert page.locator('.unit-plan-day').count() == 0
        # Removing the holiday event restores slots without modifying units.
        service.storage.write_json(local_path, lessons)
        page.reload(wait_until='networkidle')
        page.locator('[data-groups] > .unit-plan-day').wait_for()
        assert page.locator('.unit-plan-assigned').count() == 2
        page.locator('[data-add-menu] > summary').click()
        page.locator('[data-new-marker]').click()
        form = page.locator('.unit-marker-dialog form')
        form.locator('[name=titel]').fill('Notenschluss')
        form.locator('[name=datum]').fill(tomorrow)
        form.locator('[name=farbe]').fill('#dd5533')
        form.locator('[type=submit]').click()
        page.locator('.unit-plan-marker').wait_for()
        assert 'Notenschluss' in page.locator('.unit-plan-marker').inner_text()
        assert page.locator('.unit-plan-marker').evaluate("el => el.style.getPropertyValue('--marker-color')") == '#dd5533'
        page.locator('#viewButton-agenda').click()
        calendar_marker = page.locator('#viewSection-agenda .kal-agenda-entry', has_text='Notenschluss')
        calendar_marker.wait_for()
        assert calendar_marker.locator('.kal-agenda-time').inner_text() == 'ganztägig'
        assert calendar_marker.evaluate("el => el.style.getPropertyValue('--kal-event')") == '#dd5533'
        page.locator('#viewButton-units').click()
        page.reload(wait_until='networkidle')
        page.locator('.unit-plan-marker button').click()
        page.locator('.unit-marker-dialog [name=titel]').fill('Noteneintragung')
        page.locator('.unit-marker-dialog [name=datum]').fill(f'{first_year - 1}-01-15')
        page.locator('.unit-marker-dialog [type=submit]').click()
        page.wait_for_function("() => document.querySelector('.unit-plan-marker')?.textContent.includes('Noteneintragung')")
        assert f'15.01.{first_year - 1}' in page.locator('.unit-plan-marker').inner_text()
        page.reload(wait_until='networkidle')
        page.locator('.unit-plan-marker').wait_for()
        assert f'15.01.{first_year - 1}' in page.locator('.unit-plan-marker').inner_text()
        page.locator('.unit-plan-marker button').click()
        page.locator('.unit-marker-dialog [data-delete]').click()
        page.wait_for_function("() => !document.querySelector('.unit-plan-marker')")
        browser.close()
    planned = next(unit for unit in client.get('/api/units').get_json()['units'] if unit['data']['titel'] == 'Geplant')
    assert planned['data']['einsatz'] == [{'datum': day, 'lerngruppe': '05C'}]


def test_holidays_automatically_detect_loaded_holiday_calendar(app_with_kalender):
    service = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender'].service
    service.storage.write_json(service.storage.path('local-events.json'), [source_event(
        key='christmas', calendar='Ferien und Feiertage', title='Weihnachtsferien 2026 Hessen',
        allDay=True, startDate='2026-12-23', endDate='2027-01-12', start='2026-12-23', end='2027-01-12',
    )])
    client = app_with_kalender.test_client()
    response = client.get('/api/plugins/kalender/holidays?from=2026-12-01&to=2027-02-01')
    assert response.status_code == 200
    assert response.json['automatic'] is True
    assert '2026-12-29' in response.json['days']
    assert '2027-01-12' in response.json['days']
    assert '2027-01-13' not in response.json['days']


def test_planning_markers_roundtrip_and_conflicts(app_with_kalender):
    client = app_with_kalender.test_client()
    url = '/api/plugins/kalender/planning-markers'
    payload = {'titel': 'Notenschluss', 'datum': '2026-12-18', 'farbe': '#F08030', 'klasse': ''}
    marker = client.post(url, json=payload).json
    assert marker['farbe'] == '#f08030'
    assert client.get(url).json['rows'] == [marker]
    # Calendar appearances use the same persisted record, including existing markers.
    def calendar_events(day):
        return client.get(f'/api/plugins/kalender/events?from={day}&to={day}').json['events']
    events = calendar_events('2026-12-18')
    assert len(events) == 1
    event = events[0]
    assert event['title'] == 'Notenschluss'
    assert event['allDay'] is True
    assert event['start'] == event['end'] == event['startDate'] == event['endDate'] == '2026-12-18'
    assert event['color'] == '#f08030'
    assert calendar_events('2026-12-18')[0]['key'] == event['key']
    assert calendar_events('2026-12-19') == []
    updated = client.post(url, json={**marker, 'titel': 'Noteneintragung', 'klasse': 'klasse-05', 'datum': '2026-12-19'}).json
    assert updated['id'] == marker['id']
    assert updated['revision'] != marker['revision']
    assert calendar_events('2026-12-18') == []
    assert calendar_events('2026-12-19')[0]['title'] == 'Noteneintragung'
    assert calendar_events('2026-12-19')[0]['key'] == event['key']
    assert client.post(url, json={**marker, 'delete': True}).status_code == 400
    assert client.get(url).json['rows'] == [updated]
    assert client.post(url, json={**updated, 'delete': True}).status_code == 200
    assert client.get(url).json['rows'] == []
    assert calendar_events('2026-12-19') == []
    for patch in [{'datum': '2026-02-30'}, {'farbe': 'red'}, {'klasse': '../05'}, {'titel': ''}]:
        assert client.post(url, json={**payload, **patch}).status_code == 400
    assert client.get(url).json['rows'] == []


def test_browser_edit_preserves_lesson_when_loading_fails(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    lesson_source(context)
    client = app_with_kalender.test_client()
    response = client.post('/api/plugins/kalender/events', json={
        'kind': 'todo', 'title': 'Stundenverknüpfung erhalten',
        'date': '2026-11-10', 'lesson': LESSON})
    assert response.status_code == 201
    with LiveServer(app_with_kalender, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        # Die Testtermine sind fest datiert; ohne feste Uhr werden sie mit der Zeit ueberfaellig.
        page.clock.set_fixed_time(datetime(2026, 11, 9, 8, 0))
        page.add_init_script('localStorage.setItem("material-ui:active-view", "agenda")')
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.route('**/api/plugins/kalender/lessons?*', lambda route: route.fulfill(
            status=503, json={'error': {'message': 'Stundenquelle nicht erreichbar'}}))
        page.goto(url, wait_until='networkidle')
        page.locator('[data-kal="agenda-jump"]').fill('2026-11-10')
        page.locator('#viewSection-agenda').get_by_role(
            'button', name='Stundenverknüpfung erhalten', exact=True).click()
        page.get_by_role('dialog', name='Stundenverknüpfung erhalten').get_by_role(
            'button', name='Bearbeiten', exact=True).click()
        form = page.locator('#kalCreateModal form')
        page.wait_for_function("!document.querySelector('#kalCreateModal [name=calendarTarget]').disabled")
        assert form.locator('[name=lesson]').input_value() == LESSON['start']
        with page.expect_request(lambda request: request.method == 'PATCH'
                                 and request.url.endswith('/kalender/events')) as request:
            form.get_by_role('button', name='Speichern', exact=True).click()
        assert request.value.post_data_json['lesson'] == LESSON
        page.wait_for_selector('#kalCreateModal.open', state='hidden')
        browser.close()


def test_browser_create_and_edit_todo_lesson_for_selected_day(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    context = app_with_kalender.extensions['material_runtime'].plugins.contexts['kalender']
    lesson_source(context)
    with LiveServer(app_with_kalender, free_port()) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        # Die Testtermine sind fest datiert; ohne feste Uhr werden sie mit der Zeit ueberfaellig.
        page.clock.set_fixed_time(datetime(2026, 11, 9, 8, 0))
        page.add_init_script('localStorage.setItem("material-ui:active-view", "agenda")')
        page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
        page.goto(url, wait_until='networkidle')
        agenda = page.locator('#viewSection-agenda')
        agenda.get_by_role('button', name='TODO erstellen', exact=True).click()
        form = page.locator('#kalCreateModal form')
        form.locator('[name=title]').fill('Stunde vorbereiten')
        form.locator('[name=date]').fill('2026-11-10')
        lesson = form.locator('[name=lesson]')
        page.wait_for_function("!document.querySelector('#kalCreateModal [name=lesson]').disabled")
        lesson.select_option(LESSON['start'])
        form.get_by_role('button', name='Speichern', exact=True).click()
        page.wait_for_selector('#kalCreateModal.open', state='hidden')
        agenda.locator('[data-kal=agenda-jump]').fill('2026-11-10')
        agenda.get_by_role('button', name='Stunde vorbereiten', exact=True).click()
        dialog = page.get_by_role('dialog', name='Stunde vorbereiten')
        assert '10C MA' in dialog.inner_text()
        dialog.get_by_role('button', name='Bearbeiten', exact=True).click()
        page.wait_for_function("!document.querySelector('#kalCreateModal [name=lesson]').disabled")
        assert lesson.input_value() == LESSON['start']
        with page.expect_response('**/api/plugins/kalender/lessons?date=2026-11-11'):
            form.locator('[name=date]').fill('2026-11-11')
        page.wait_for_function("!document.querySelector('#kalCreateModal [name=lesson]').disabled")
        assert lesson.input_value() == ''
        assert lesson.locator('option').count() == 2
        next_start = '2026-11-11T07:55:00+01:00'
        lesson.select_option(next_start)
        form.get_by_role('button', name='Speichern', exact=True).click()
        page.wait_for_selector('#kalCreateModal.open', state='hidden')
        tasks = app_with_kalender.test_client().get('/api/plugins/kalender/tasks').get_json()['tasks']
        task = next(t for t in tasks if t['title'] == 'Stunde vorbereiten')
        assert task['startDate'] == '2026-11-11'
        assert task['lesson']['start'] == next_start
        browser.close()


def test_calendar_interface_feeds_agenda_and_reports_source_errors(app_with_kalender):
    """Plugins liefern Termine über das Interface @calendar; Fehler bleiben je Quelle isoliert."""
    runtime = app_with_kalender.extensions['material_runtime']
    assert 'calendar' in runtime.plugins.manifests['kalender'].provides
    interface = runtime.plugins.service('calendar')
    unregister = interface.register_source(lambda start, end: [source_event()], source_id='demo', name='Demo')

    def broken(start, end):
        raise RuntimeError('kaputt')

    interface.register_source(broken, source_id='defekt', name='Defekt')
    with pytest.raises(TypeError):
        interface.register_source(None)
    client = app_with_kalender.test_client()
    data = client.get('/api/plugins/kalender/events?from=2026-11-09&to=2026-11-15').json
    assert [event['key'] for event in data['events']] == ['source']
    assert [(error['source'], error['name']) for error in data['sourceErrors']] == [('defekt', 'Defekt')]
    unregister()
    assert [entry[0] for entry in interface.sources()] == ['kalender', 'defekt']


def test_browser_assigns_existing_unit_to_free_lesson_and_undoes(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    from datetime import timedelta
    app = app_with_kalender
    day = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    client = app.test_client()
    for title, datum in [('Vorhanden', day), ('Frei verfügbar', '2020-01-06')]:
        assert client.post('/api/units/new', json={
            'fach': 'mathematik', 'klasse': '05', 'thema': 'Zahlen', 'titel': title, 'datum': datum,
        }).status_code == 201
    service = app.extensions['material_runtime'].plugins.contexts['kalender'].service
    service.storage.write_json(service.storage.path('local-events.json'), [
        source_event(title='05C MA', start=f'{day}T08:00:00+01:00', end=f'{day}T09:00:00+01:00', startDate=day, endDate=day),
        source_event(key='free', title='05C MA', start=f'{tomorrow}T08:00:00+01:00',
                     end=f'{tomorrow}T09:00:00+01:00', startDate=tomorrow, endDate=tomorrow)])
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:active-view", "units")')
            page.goto(url, wait_until='networkidle')
            free_day = page.locator('[data-groups] > .unit-plan-day')
            free_day.wait_for()
            free_day.locator('summary').click()
            free_day.locator('[data-assign]').click()
            picker = page.locator('.unit-assign-picker')
            picker.wait_for()
            # Noch nie eingesetzte Einheiten stehen zuerst; die Suche grenzt ein.
            assert picker.locator('[data-assign-index]').first.inner_text().startswith('Frei verfügbar')
            picker.locator('[data-assign-search]').fill('vorhanden')
            assert picker.locator('[data-assign-index]').count() == 1
            picker.locator('[data-assign-search]').fill('frei')
            picker.locator('[data-assign-index]').first.click()
            status = page.locator('[data-status]')
            status.locator('[data-assign-undo]').wait_for()
            assert 'Frei verfügbar' in status.inner_text()
            assert page.locator('[data-groups] > .unit-plan-day').count() == 0
            saved = [u for u in client.get('/api/units').get_json()['units'] if u['data']['titel'] == 'Frei verfügbar'][0]
            assert any(use['datum'] == tomorrow for use in saved['data']['einsatz'])
            status.locator('[data-assign-undo]').click()
            page.locator('[data-groups] > .unit-plan-day').wait_for()
            saved = [u for u in client.get('/api/units').get_json()['units'] if u['data']['titel'] == 'Frei verfügbar'][0]
            assert [use['datum'] for use in saved['data']['einsatz']] == ['2020-01-06']
            # Escape schließt die Auswahl und gibt den Fokus zurück.
            page.locator('[data-groups] > .unit-plan-day summary').click()
            page.locator('[data-assign]').click()
            page.locator('[data-assign-search]').press('Escape')
            assert page.locator('.unit-assign-picker').count() == 0
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_browser_drags_unit_onto_free_lesson(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    from datetime import timedelta
    app = app_with_kalender
    day = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    client = app.test_client()
    for title, datum in [('Vorhanden', day), ('Frei verfügbar', '2020-01-06')]:
        assert client.post('/api/units/new', json={
            'fach': 'mathematik', 'klasse': '05', 'thema': 'Zahlen', 'titel': title, 'datum': datum,
        }).status_code == 201
    service = app.extensions['material_runtime'].plugins.contexts['kalender'].service
    service.storage.write_json(service.storage.path('local-events.json'), [
        source_event(title='05C MA', start=f'{day}T08:00:00+01:00', end=f'{day}T09:00:00+01:00', startDate=day, endDate=day),
        source_event(key='free', title='05C MA', start=f'{tomorrow}T08:00:00+01:00',
                     end=f'{tomorrow}T09:00:00+01:00', startDate=tomorrow, endDate=tomorrow)])
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 1400})
            page.add_init_script('localStorage.setItem("material-ui:active-view", "units")')
            page.goto(url, wait_until='networkidle')
            page.locator('[data-groups] > .unit-plan-day').wait_for()
            handle = page.locator('.unit-card', has_text='Frei verfügbar').locator('.unit-drag-handle')
            box = handle.bounding_box()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(box['x'] + 20, box['y'] + 20, steps=4)
            # Beim Start des Ziehens klappen freie Tage auf, damit ihre Stunden Ziele sind.
            slot = page.locator('[data-free-slot]')
            slot.wait_for(state='visible')
            target = slot.bounding_box()
            page.mouse.move(target['x'] + 30, target['y'] + target['height'] / 2, steps=6)
            assert 'unit-drop-target' in slot.get_attribute('class')
            page.mouse.up()
            page.locator('[data-assign-undo]').wait_for()
            saved = [u for u in client.get('/api/units').get_json()['units'] if u['data']['titel'] == 'Frei verfügbar'][0]
            assert any(use['datum'] == tomorrow for use in saved['data']['einsatz'])
            # Escape bricht das Ziehen ab: nichts wird eingetragen.
            page.locator('[data-assign-undo]').click()
            page.locator('[data-groups] > .unit-plan-day').wait_for()
            handle = page.locator('.unit-card', has_text='Frei verfügbar').locator('.unit-drag-handle')
            box = handle.bounding_box()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(box['x'] + 20, box['y'] + 20, steps=4)
            slot = page.locator('[data-free-slot]'); slot.wait_for(state='visible')
            target = slot.bounding_box()
            page.mouse.move(target['x'] + 30, target['y'] + target['height'] / 2, steps=6)
            page.keyboard.press('Escape')
            page.mouse.up()
            page.wait_for_timeout(300)
            saved = [u for u in client.get('/api/units').get_json()['units'] if u['data']['titel'] == 'Frei verfügbar'][0]
            assert [use['datum'] for use in saved['data']['einsatz']] == ['2020-01-06']
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_browser_drag_scrolls_at_the_edge_and_never_undoes_an_existing_assignment(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    from datetime import timedelta
    app = app_with_kalender
    client = app.test_client()
    # Eine Einheit im laufenden Schuljahr, damit dieses Schuljahr angezeigt wird.
    for title, datum in [('Vorhanden', date.today().isoformat()), ('Frei verfügbar', '2020-01-06')]:
        assert client.post('/api/units/new', json={
            'fach': 'mathematik', 'klasse': '05', 'thema': 'Zahlen', 'titel': title, 'datum': datum,
        }).status_code == 201
    service = app.extensions['material_runtime'].plugins.contexts['kalender'].service
    events = []
    for offset in range(1, 40):
        day = (date.today() + timedelta(days=offset)).isoformat()
        events.append(source_event(key=f'free-{offset}', title='05C MA', start=f'{day}T08:00:00+01:00',
                                   end=f'{day}T09:00:00+01:00', startDate=day, endDate=day))
    service.storage.write_json(service.storage.path('local-events.json'), events)
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 700})
            page.add_init_script('localStorage.setItem("material-ui:active-view", "units")')
            page.goto(url, wait_until='networkidle')
            page.locator('[data-groups] > .unit-plan-day').first.wait_for()
            handle = page.locator('.unit-card', has_text='Frei verfügbar').locator('.unit-drag-handle')
            box = handle.bounding_box()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(box['x'] + 20, box['y'] + 20, steps=4)
            section = page.locator('.units-view').first
            before = section.evaluate('node => node.scrollTop')
            rect = section.bounding_box()
            page.mouse.move(rect['x'] + rect['width'] / 2, rect['y'] + rect['height'] - 8, steps=5)
            page.wait_for_timeout(600)
            after = section.evaluate('node => node.scrollTop')
            assert after > before, 'Am unteren Rand muss die Ansicht automatisch scrollen'
            page.keyboard.press('Escape')
            page.mouse.up()
            page.wait_for_timeout(300)
            saved = [u for u in client.get('/api/units').get_json()['units'] if u['data']['titel'] == 'Frei verfügbar'][0]
            assert [use['datum'] for use in saved['data']['einsatz']] == ['2020-01-06']
            # Schon eingetragen: kein Rückgängig, das einen vorhandenen Eintrag löschen könnte.
            result = page.evaluate("""async () => {
              const { assignUnit, isAssigned } = await import('/static/unit-assign.js');
              const unit = { path: 'u', revision: 'r1', data: { einsatz: [{ datum: '2026-03-02', lerngruppe: '05C' }] } };
              const event = { startDate: '2026-03-02', teaching: { klasse: '05', lerngruppe: '05 c' } };
              const calls = [];
              const same = await assignUnit(async (path, init) => { calls.push(JSON.parse(init.body)); return { revision: 'r2', data: { einsatz: unit.data.einsatz } }; }, unit, event);
              const other = { startDate: '2026-03-03', teaching: event.teaching };
              const fresh = await assignUnit(async () => ({ revision: 'r2', data: { einsatz: [...unit.data.einsatz, { datum: '2026-03-03', lerngruppe: '05C' }] } }), unit, other);
              return { assigned: isAssigned(unit, event), notAssigned: isAssigned(unit, other),
                undoExisting: same.undo, undoNew: typeof fresh.undo };
            }""")
            assert result == {'assigned': True, 'notAssigned': False, 'undoExisting': None, 'undoNew': 'function'}
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def _planning_app(app):
    """Zwei Einheiten (eine eingesetzt, eine frei) und eine freie Stunde morgen; liefert (client, heute, morgen)."""
    from datetime import timedelta
    day = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    client = app.test_client()
    for title, datum in [('Vorhanden', day), ('Frei verfügbar', '2020-01-06')]:
        assert client.post('/api/units/new', json={
            'fach': 'mathematik', 'klasse': '05', 'thema': 'Zahlen', 'titel': title, 'datum': datum,
        }).status_code == 201
    service = app.extensions['material_runtime'].plugins.contexts['kalender'].service
    service.storage.write_json(service.storage.path('local-events.json'), [
        source_event(title='05C MA', start=f'{day}T08:00:00+01:00', end=f'{day}T09:00:00+01:00', startDate=day, endDate=day),
        source_event(key='free', title='05C MA', start=f'{tomorrow}T08:00:00+01:00',
                     end=f'{tomorrow}T09:00:00+01:00', startDate=tomorrow, endDate=tomorrow)])
    return client, day, tomorrow


def _unit(client, title):
    return [u for u in client.get('/api/units').get_json()['units'] if u['data']['titel'] == title][0]


def test_browser_assign_conflict_is_reported_and_writes_nothing(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    app = app_with_kalender
    client, _day, tomorrow = _planning_app(app)
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(60_000)
            page.add_init_script('localStorage.setItem("material-ui:active-view", "units")')
            page.goto(url, wait_until='networkidle')
            free_day = page.locator('[data-groups] > .unit-plan-day')
            free_day.wait_for()
            free_day.locator('summary').click()
            free_day.locator('[data-assign]').click()
            picker = page.locator('.unit-assign-picker')
            picker.wait_for()
            # Ein zweites Fenster ändert die Einheit, bevor die Auswahl bestätigt wird.
            stale = _unit(client, 'Frei verfügbar')
            assert client.post('/api/units/dates', json={
                'path': stale['path'], 'revision': stale['revision'], 'dates': ['2020-02-03']}).status_code == 200
            picker.locator('[data-assign-search]').fill('frei')
            picker.locator('[data-assign-index]').first.click()
            picker.locator('[data-assign-status]').filter(has_text='zwischenzeitlich geändert').wait_for()
            assert picker.locator('[data-assign-index]').first.is_enabled()
            saved = _unit(client, 'Frei verfügbar')
            assert sorted(use['datum'] for use in saved['data']['einsatz']) == ['2020-01-06', '2020-02-03']
            assert tomorrow not in [use['datum'] for use in saved['data']['einsatz']]
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_browser_cancelled_lesson_is_no_assign_or_drop_target(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    app = app_with_kalender
    client, _day, _tomorrow = _planning_app(app)
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 1400})
            page.set_default_timeout(60_000)
            page.add_init_script('localStorage.setItem("material-ui:active-view", "units")')
            page.goto(url, wait_until='networkidle')
            free_day = page.locator('[data-groups] > .unit-plan-day')
            free_day.wait_for()
            free_day.locator('summary').click()
            free_day.locator('[data-cancel]').click()
            page.locator('[data-groups] > .unit-plan-day [data-cancel][aria-pressed="true"]').wait_for()
            assert page.locator('[data-assign]').is_disabled()
            assert page.locator('[data-free-slot]').count() == 0
            # Ziehen auf die ausgefallene Stunde trägt nichts ein.
            handle = page.locator('.unit-card', has_text='Frei verfügbar').locator('.unit-drag-handle')
            box = handle.bounding_box()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(box['x'] + 20, box['y'] + 20, steps=4)
            target = page.locator('.unit-plan-slot.is-cancelled').bounding_box()
            page.mouse.move(target['x'] + 30, target['y'] + target['height'] / 2, steps=6)
            page.mouse.up()
            page.wait_for_timeout(300)
            assert [use['datum'] for use in _unit(client, 'Frei verfügbar')['data']['einsatz']] == ['2020-01-06']
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_browser_unit_filters_survive_reload(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    app = app_with_kalender
    client, _day, _tomorrow = _planning_app(app)
    for subject, title in [('mathematik', 'Ohne Termin'), ('deutsch', 'Lesen')]:
        assert client.post('/api/units/new', json={
            'fach': subject, 'klasse': '05', 'thema': 'Planung', 'titel': title,
        }).status_code == 201
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(60_000)
            page.add_init_script('if (!sessionStorage.getItem("seen")) { sessionStorage.setItem("seen", "1"); localStorage.setItem("material-ui:active-view", "units"); }')
            page.goto(url, wait_until='networkidle')
            page.locator('.unit-filters summary').wait_for()
            page.locator('[data-show-undated]').check()
            page.locator('.unit-filters summary').click()
            page.locator('[data-subject-filter]').select_option('mathematik')
            page.locator('[data-group-filter]').select_option('05C')
            page.locator('[data-only-undated]').check()
            page.wait_for_function("document.querySelectorAll('.unit-card').length === 1")
            assert 'Ohne Termin' in page.locator('.unit-card').inner_text()
            page.locator('[data-completion-filter]').select_option('open')
            page.locator('[data-tag-filter]').fill('zz-kein-treffer')
            page.locator('[data-tag-filter]').dispatch_event('change')
            assert 'aktiv' in page.locator('.unit-filters summary').inner_text()
            page.reload(wait_until='networkidle')
            page.locator('.unit-filters summary').wait_for()
            assert 'aktiv' in page.locator('.unit-filters summary').inner_text()
            page.locator('.unit-filters summary').click()
            assert page.locator('[data-subject-filter]').input_value() == 'mathematik'
            assert page.locator('[data-group-filter]').input_value() == '05C'
            assert page.locator('[data-only-undated]').is_checked()
            assert page.locator('[data-show-undated]').is_checked()
            assert page.locator('[data-completion-filter]').input_value() == 'open'
            assert page.locator('[data-tag-filter]').input_value() == 'zz-kein-treffer'
            assert page.locator('.unit-card').count() == 0
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def _open_assigned_day(page, title):
    """Karte der Einheit und ihren eingetragenen Tag aufklappen; liefert die Stundenzeile."""
    card = page.locator('.unit-card').filter(has=page.locator('.unit-title', has_text=title)).first
    card.locator(':scope > summary').click()
    card.locator('.unit-plan-assigned .unit-plan-day > summary').first.click()
    return card.locator('.unit-plan-assigned .unit-plan-slot').first


def test_browser_moves_existing_use_by_drag_and_undoes(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    app = app_with_kalender
    client, day, tomorrow = _planning_app(app)
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 1400})
            page.set_default_timeout(60_000)
            page.add_init_script('localStorage.setItem("material-ui:active-view", "units")')
            page.goto(url, wait_until='networkidle')
            page.locator('[data-groups] > .unit-plan-day').wait_for()
            slot = _open_assigned_day(page, 'Vorhanden')
            box = slot.locator('.unit-move-handle').bounding_box()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(box['x'] + 20, box['y'] + 20, steps=4)
            free = page.locator('[data-free-slot]')
            free.wait_for(state='visible')
            target = free.bounding_box()
            page.mouse.move(target['x'] + 30, target['y'] + target['height'] / 2, steps=6)
            assert 'unit-drop-target' in free.get_attribute('class')
            page.mouse.up()
            page.locator('[data-assign-undo]').wait_for()
            assert 'verschoben' in page.locator('[data-status]').inner_text()
            # Das Datum wurde geändert, nichts wurde doppelt angelegt.
            assert [use['datum'] for use in _unit(client, 'Vorhanden')['data']['einsatz']] == [tomorrow]
            with page.expect_response(lambda response: response.url.endswith('/api/units/dates')
                                      and response.request.method == 'POST'):
                page.locator('[data-assign-undo]').click()
            page.locator('[data-groups] > .unit-plan-day').wait_for()
            assert [use['datum'] for use in _unit(client, 'Vorhanden')['data']['einsatz']] == [day]
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_browser_moves_existing_use_with_keyboard_picker(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    app = app_with_kalender
    client, day, tomorrow = _planning_app(app)
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 1400})
            page.set_default_timeout(60_000)
            page.add_init_script('localStorage.setItem("material-ui:active-view", "units")')
            page.goto(url, wait_until='networkidle')
            page.locator('[data-groups] > .unit-plan-day').wait_for()
            slot = _open_assigned_day(page, 'Vorhanden')
            slot.locator('[data-move]').click()
            picker = page.locator('.unit-move-picker')
            picker.wait_for()
            picker.locator('[data-move-target]').press('Escape')
            assert page.locator('.unit-move-picker').count() == 0
            slot.locator('[data-move]').click()
            page.locator('.unit-move-picker [type=submit]').click()
            page.locator('[data-assign-undo]').wait_for()
            assert [use['datum'] for use in _unit(client, 'Vorhanden')['data']['einsatz']] == [tomorrow]
            browser.close()
    finally:
        app.extensions['material_runtime'].close()


def test_move_rejects_duplicate_day_and_stale_revision(app_with_kalender):
    app = app_with_kalender
    client, day, tomorrow = _planning_app(app)
    try:
        unit = _unit(client, 'Vorhanden')
        added = client.post('/api/units/dates', json={'path': unit['path'], 'revision': unit['revision'], 'dates': [tomorrow]})
        assert added.status_code == 200
        fresh = added.get_json()
        # Verschieben auf einen Tag, an dem derselbe Einsatz schon steht, wird abgelehnt.
        clash = client.post('/api/units/dates', json={'path': unit['path'], 'revision': fresh['revision'],
                                                      'updates': [{'index': 0, 'datum': tomorrow}]})
        assert clash.status_code == 400
        # Veraltete Revision: Konflikt, Datum bleibt.
        stale = client.post('/api/units/dates', json={'path': unit['path'], 'revision': unit['revision'],
                                                      'updates': [{'index': 0, 'datum': '2030-01-01'}]})
        assert stale.status_code == 409
        assert sorted(use['datum'] for use in _unit(client, 'Vorhanden')['data']['einsatz']) == sorted([day, tomorrow])
    finally:
        app.extensions['material_runtime'].close()


def test_browser_today_assigns_existing_unit_to_lesson(app_with_kalender):
    if sync_playwright is None:
        pytest.skip('Playwright ist nicht installiert')
    from datetime import timedelta
    app = app_with_kalender
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    client = app.test_client()
    assert client.post('/api/units/new', json={
        'fach': 'mathematik', 'klasse': '05', 'thema': 'Zahlen', 'titel': 'Aus Heute', 'datum': '2020-01-06',
    }).status_code == 201
    context = app.extensions['material_runtime'].plugins.contexts['kalender']
    stunden = [source_event('stunde-2', title='05C MA', start=f'{tomorrow}T09:45:00+01:00',
                            end=f'{tomorrow}T10:30:00+01:00', startDate=tomorrow, endDate=tomorrow, location='E32')]
    context.service('calendar').register_source(lambda start, end: [e for e in stunden if start <= e['startDate'] <= end])
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(60_000)
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:active-view", "heute")')
            page.goto(url, wait_until='networkidle')
            section = page.locator('#viewSection-heute')
            section.get_by_role('button', name='Morgen', exact=True).click()
            lessons = section.locator('[data-today-lessons-section]')
            lessons.wait_for(state='visible')
            row = lessons.locator('.kal-lesson', has_text='05C MA')
            row.locator('[data-kal-assign]').click()
            picker = page.locator('.unit-assign-picker')
            picker.wait_for()
            picker.locator('[data-assign-index]').first.click()
            page.locator('#viewSection-heute [data-assign-undo]').wait_for()
            # Heute lädt neu: die Stunde zeigt jetzt die Einheit, der Knopf ist weg.
            lessons.locator('.kal-lesson', has_text='05C MA').locator('[data-kal-unit]').wait_for()
            assert lessons.locator('.kal-lesson', has_text='05C MA').locator('[data-kal-assign]').count() == 0
            assert any(use['datum'] == tomorrow for use in _unit(client, 'Aus Heute')['data']['einsatz'])
            browser.close()
    finally:
        app.extensions['material_runtime'].close()

# -- Serien bearbeiten ------------------------------------------------------------------------------------

SERIES_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Serie//DE
BEGIN:VEVENT
UID:serie-1@schule
DTSTAMP:20261020T080000Z
DTSTART;TZID=Europe/Berlin:20261102T083000
DTEND;TZID=Europe/Berlin:20261102T090000
SUMMARY:Ringstunde
RRULE:FREQ=WEEKLY;BYDAY=MO
END:VEVENT
END:VCALENDAR
"""

EXCEPTION_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Ausnahme//DE
BEGIN:VEVENT
UID:serie-1@schule
DTSTAMP:20261020T080000Z
RECURRENCE-ID;TZID=Europe/Berlin:20261109T083000
DTSTART;TZID=Europe/Berlin:20261109T083000
DTEND;TZID=Europe/Berlin:20261109T090000
SUMMARY:Ringstunde (Ausnahme)
END:VEVENT
END:VCALENDAR
"""


class _SeriesResource:
    def __init__(self, ics):
        import icalendar

        self.icalendar_instance = icalendar.Calendar.from_ical(ics)
        self.saved = 0

    def save(self):
        self.saved += 1


class _SeriesCalendar:
    name = "Persönlich"
    id = "/calendars/test/persoenlich"

    def __init__(self, resource):
        self._resource = resource

    def get_supported_components(self):
        return ["VEVENT", "VTODO"]

    def events(self):
        return [self._resource]

    def todos(self, include_completed=False):
        return []

    def save_event(self, ics):
        raise AssertionError("save_event darf bei gleicher Ressource nicht aufgerufen werden")

    def save_todo(self, ics):
        raise AssertionError("save_todo darf bei gleicher Ressource nicht aufgerufen werden")


class _SeriesClient:
    def __init__(self, resource):
        self._resource = resource

    def principal(self):
        calendar = _SeriesCalendar(self._resource)

        class _Principal:
            def calendars(self):
                return [calendar]

        return _Principal()


def _seed_series_cache(service):
    service.storage.write_json(service._cache_path(), {"events": [{
        "key": "serie-1@schule@2026-11-02T08:30:00+01:00", "uid": "serie-1@schule", "account": "Schule",
        "calendar": "Persönlich", "kind": "event", "title": "Ringstunde",
        "start": "2026-11-02T08:30:00+01:00", "end": "2026-11-02T09:00:00+01:00",
        "startDate": "2026-11-02", "endDate": "2026-11-02", "allDay": False, "location": "",
        "description": "", "unitPath": "", "url": "", "status": "",
        "recurring": True, "recurrence": {"freq": "WEEKLY", "interval": 1}, "recurrenceId": True,
    }]})


def _series_payload(**overrides):
    payload = {
        "key": "serie-1@schule@2026-11-02T08:30:00+01:00", "originalAccount": "Schule", "originalCalendar": "Persönlich",
        "kind": "event", "title": "Ringstunde II", "date": "2026-11-02", "time": "08:30", "endTime": "09:00",
        "recurrence": {"freq": "DAILY", "interval": 2, "until": "2026-12-31"},
        "account": "Schule", "calendar": "Persönlich", "location": "", "description": "",
    }
    payload.update(overrides)
    return payload


def test_series_master_can_be_edited_and_recurrence_changed(app_with_kalender, monkeypatch):
    resource = _SeriesResource(SERIES_ICS)
    client = app_with_kalender.test_client()
    assert client.post("/api/plugins/kalender/settings", json={
        "accounts": [{"label": "Schule", "url": "https://cal.schule.example/dav/", "username": "l", "password": "p"}],
    }).status_code == 200
    service = app_with_kalender.extensions["material_runtime"].plugins.contexts["kalender"].own_service
    monkeypatch.setattr(service, "client_factory", lambda account: _SeriesClient(resource))
    _seed_series_cache(service)

    response = client.patch("/api/plugins/kalender/events", json=_series_payload())
    assert response.status_code == 200, response.get_json()
    assert resource.saved == 1
    component = resource.icalendar_instance.walk("VEVENT")[0]
    assert str(component["summary"]) == "Ringstunde II"
    assert str(component["rrule"].get("freq")) == "DAILY"
    assert int(component["rrule"].get("interval")) == 2
    assert "until" in component["rrule"]
    # Das Vorkommen traegt die Serienregel des Masters.
    assert response.get_json()["recurring"] is True
    assert response.get_json()["recurrence"] == {"freq": "DAILY", "interval": 2, "until": "2026-12-31"}

    # Wiederholung entfernen beendet die Serie auf dem Master.
    response = client.patch("/api/plugins/kalender/events", json=_series_payload(recurrence=None, title="Einmalig"))
    assert response.status_code == 200
    assert resource.icalendar_instance.walk("VEVENT")[0].get("rrule") is None


def test_series_exception_instance_stays_rejected(app_with_kalender, monkeypatch):
    resource = _SeriesResource(EXCEPTION_ICS)
    client = app_with_kalender.test_client()
    assert client.post("/api/plugins/kalender/settings", json={
        "accounts": [{"label": "Schule", "url": "https://cal.schule.example/dav/", "username": "l", "password": "p"}],
    }).status_code == 200
    service = app_with_kalender.extensions["material_runtime"].plugins.contexts["kalender"].own_service
    monkeypatch.setattr(service, "client_factory", lambda account: _SeriesClient(resource))
    _seed_series_cache(service)
    response = client.patch("/api/plugins/kalender/events", json=_series_payload())
    assert response.status_code == 400
    assert "ursprünglichen Kalender" in response.get_json()["error"]["message"]
    assert resource.saved == 0


def test_recurrence_of_parses_rrule_components():
    import icalendar

    from material_ui_plugins.kalender.helpers import _recurrence_of

    component = icalendar.Calendar.from_ical(SERIES_ICS).walk("VEVENT")[0]
    assert _recurrence_of(component) == {"freq": "WEEKLY", "interval": 1}
    with_until = icalendar.Calendar.from_ical(SERIES_ICS.replace(
        "RRULE:FREQ=WEEKLY;BYDAY=MO", "RRULE:FREQ=MONTHLY;INTERVAL=3;UNTIL=20261231").replace(
        "BEGIN:VEVENT", "BEGIN:VEVENT", 1)).walk("VEVENT")[0]
    parsed = _recurrence_of(with_until)
    assert parsed["freq"] == "MONTHLY" and parsed["interval"] == 3 and parsed["until"] == "2026-12-31"
    single = icalendar.Calendar.from_ical(ICS).walk("VEVENT")[0]
    assert _recurrence_of(single) is None
