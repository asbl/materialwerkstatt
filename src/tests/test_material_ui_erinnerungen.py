"""Erinnerungen-Plugin: Desktop-Erinnerungen bei geschlossener UI ueber @calendar >= 0.3.0."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_ui.app import create_app
from material_ui.config import AppConfig


@pytest.fixture()
def repo(tmp_path):
    previous_modules = {name: module for name, module in sys.modules.items()
                        if name.startswith("material_ui_plugins.")}
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "unterricht").mkdir()
    (repo / "unterricht" / "a.qmd").write_text("---\ntitle: A\n---\nText\n", encoding="utf-8")
    yield repo
    sys.modules.update(previous_modules)


@pytest.fixture()
def app(repo):
    application = create_app(config=AppConfig(repo))
    application.testing = True
    application.test_client().get("/api/plugins")  # Plugins laden
    yield application
    application.extensions["material_runtime"].close()
    for module in [name for name in sys.modules if name.startswith("material_ui_plugins.")]:
        del sys.modules[module]


def _contexts(application):
    return application.extensions["material_runtime"].plugins.contexts


def _kalender_service(application):
    return _contexts(application)["kalender"].own_service


def _reminder_service(application):
    return _contexts(application)["erinnerungen"].own_service


def test_plugin_loads_and_depends_on_calendar(app):
    plugins = app.test_client().get("/api/plugins").get_json()["plugins"]
    by_id = {entry["id"]: entry for entry in plugins}
    assert by_id["erinnerungen"]["status"] == "loaded"
    assert by_id["kalender"]["status"] == "loaded" and by_id["kalender"]["version"] == "0.3.0"
    depends = by_id["erinnerungen"]["dependsOn"]
    assert any(entry.get("target") == "@calendar" and entry.get("constraint") == ">=0.3.0" for entry in depends)


def test_settings_routes_defaults_and_validation(app):
    client = app.test_client()
    masked = client.get("/api/plugins/erinnerungen/settings").get_json()
    assert masked == {"desktopReminders": True, "reminderMinutes": 15}
    ok = client.post("/api/plugins/erinnerungen/settings", json={"desktopReminders": False, "reminderMinutes": 30})
    assert ok.status_code == 200
    assert ok.get_json() == {"desktopReminders": False, "reminderMinutes": 30}
    for bad in ({"desktopReminders": "an"}, {"reminderMinutes": 0}, {"reminderMinutes": 121},
                {"reminderMinutes": 15.5}, {"reminderMinutes": True}, "keine-angabe"):
        assert client.post("/api/plugins/erinnerungen/settings", json=bad).status_code == 400


def test_due_reminders_selects_window_events_and_today_tasks():
    from material_ui_plugins.erinnerungen.reminders import due_reminders

    zone = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 11, 21, 9, 0, tzinfo=zone)
    events = [
        {"key": "a", "title": "Mathe", "start": "2026-11-21T09:10:00+01:00", "startDate": "2026-11-21", "kind": "event"},
        {"key": "b", "title": "Zu spaet", "start": "2026-11-21T12:00:00+01:00", "startDate": "2026-11-21"},
        {"key": "c", "title": "Anderer Tag", "start": "2026-11-20T09:10:00+01:00", "startDate": "2026-11-20"},
        {"key": "d", "title": "Ferien", "start": "2026-11-21T09:05:00+01:00", "startDate": "2026-11-21", "holiday": True},
        {"key": "e", "title": "Ausfall", "start": "2026-11-21T09:05:00+01:00", "startDate": "2026-11-21", "cancelled": True},
        {"key": "f", "title": "Todo als Termin", "start": "2026-11-21T09:05:00+01:00", "startDate": "2026-11-21", "kind": "todo"},
        {"key": "g", "title": "Kein Zeitstempel", "start": "", "startDate": "2026-11-21"},
    ]
    tasks = [
        {"id": "1", "title": "Heft kontrollieren", "startDate": "2026-11-21"},
        {"id": "2", "title": "Morgen faellig", "startDate": "2026-11-22"},
        {"id": "3", "title": "Heute eingeplant", "plannedDate": "2026-11-21"},
        {"id": "4", "title": "Popup bearbeiten", "startDate": "2026-11-25", "plannedDate": "2026-11-21",
         "lesson": {"title": "3. Stunde MA", "start": "2026-11-21T10:00:00+01:00"}},
    ]
    items = due_reminders(events, tasks, now=now, window_minutes=15, today=now.date())
    keys = {item["key"] for item in items}
    assert "event:a@2026-11-21T09:10:00+01:00" in keys
    assert "task:1" in keys and "task:3" in keys and "task:4" in keys
    assert not keys & {"event:b@2026-11-21T12:00:00+01:00", "event:c@2026-11-20T09:10:00+01:00", "task:2"}
    assert all(not key.startswith(("event:d", "event:e", "event:f", "event:g")) for key in keys)
    bodies = {item["key"]: item["body"] for item in items}
    assert bodies["task:1"] == "Heute fällig"
    assert bodies["task:3"] == "Heute eingeplant"
    assert bodies["task:4"] == "Heute eingeplant · fällig am 2026-11-25 · 3. Stunde MA"
    assert bodies["event:a@2026-11-21T09:10:00+01:00"] == "09:10 Uhr"


def test_default_notify_uses_app_name_icon_and_argument_separator(monkeypatch):
    from material_ui_plugins.erinnerungen import reminders

    calls = []
    monkeypatch.setattr(reminders.shutil, "which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(reminders.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    assert reminders.default_notify("Elternabend", "18:00 Uhr · Aula") is True
    args, kwargs = calls[0]
    assert args[0] == "/usr/bin/notify-send"
    assert "--app-name=Material-UI" in args
    assert "--icon=appointment-soon" in args
    assert args[-3:] == ["--", "Elternabend", "18:00 Uhr · Aula"]
    assert kwargs["timeout"] == 5 and kwargs["check"] is False
    # Ohne notify-send nur Log, kein Fehler.
    monkeypatch.setattr(reminders.shutil, "which", lambda name: None)
    assert reminders.default_notify("x", "y") is False


def test_reminder_notifier_dedups_per_day(repo):
    from material_ui_plugins.erinnerungen.reminders import ReminderNotifier
    from material_ui.plugins.storage import PluginStorage

    storage = PluginStorage(repo / ".material-ui" / "plugins" / "erinnerungen")
    sent = []
    notifier = ReminderNotifier(storage, notify=lambda title, body: sent.append((title, body)))
    items = [{"key": "k1", "title": "A", "body": "b", "start": ""}]
    assert len(notifier.tick(items, today=date(2026, 11, 21))) == 1
    assert notifier.tick(items, today=date(2026, 11, 21)) == []  # gleicher Tag: Dedup
    assert len(notifier.tick(items, today=date(2026, 11, 22))) == 1  # neuer Tag: erneut
    assert sent == [("A", "b"), ("A", "b")]
    assert notifier.sent_on(date(2026, 11, 21)) == ["k1"]
    data = storage.read_json(storage.path("reminders.json"))
    assert data == {"2026-11-21": ["k1"], "2026-11-22": ["k1"]}
    # Keys koennen Termintitel enthalten -> Datei liegt schreibgeschuetzt (0600).
    assert oct(storage.path("reminders.json").stat().st_mode & 0o777) == "0o600"


def test_calendar_interface_reads_events_tasks_and_timezone(app):
    runtime = app.extensions["material_runtime"]
    interface = runtime.plugins.service("calendar")
    kalender = _kalender_service(app)
    day = "2026-11-21"
    kalender.storage.write_json(kalender.storage.path("local-events.json"), [
        {"key": "local:e1", "kind": "event", "title": "Elternabend", "start": "2026-11-21T18:00:00+01:00",
         "end": "2026-11-21T19:30:00+01:00", "startDate": day, "endDate": day, "allDay": False,
         "calendar": "Lokale Termine", "account": "", "location": "", "description": "", "url": "",
         "unitPath": "", "recurring": False, "status": ""},
        {"key": "local:t1", "kind": "todo", "title": "Hefte", "start": "", "end": "", "startDate": day,
         "endDate": "", "allDay": True, "calendar": "Lokale Termine", "account": "", "location": "",
         "description": "", "url": "", "unitPath": "", "recurring": False, "status": ""},
    ])
    events = interface.events(day, day)
    assert {event["title"] for event in events} == {"Elternabend", "Hefte"}
    assert [task["title"] for task in interface.tasks()] == ["Hefte"]
    assert interface.timezone() == "Europe/Berlin"


def test_tick_only_when_ui_closed_and_reads_calendar_via_interface(app, monkeypatch):
    client = app.test_client()
    kalender = _kalender_service(app)
    service = _reminder_service(app)
    sent = []
    monkeypatch.setattr(service.notifier, "_notify", lambda title, body: sent.append(title))
    zone = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 11, 21, 9, 0, tzinfo=zone)
    day = now.date().isoformat()
    kalender.storage.write_json(kalender.storage.path("local-events.json"), [
        {"key": "local:e1", "kind": "event", "title": "Elternabend",
         "start": (now + timedelta(minutes=10)).isoformat(), "end": (now + timedelta(minutes=70)).isoformat(),
         "startDate": day, "endDate": day, "allDay": False, "calendar": "Lokale Termine", "account": "",
         "location": "Aula", "description": "", "url": "", "unitPath": "", "recurring": False, "status": ""},
        {"key": "local:t1", "kind": "todo", "title": "Hefte einsammeln", "start": "", "end": "",
         "startDate": day, "endDate": "", "allDay": True, "calendar": "Lokale Termine", "account": "",
         "location": "", "description": "", "url": "", "unitPath": "", "recurring": False, "status": ""},
    ])
    # UI offen -> keine Erinnerung.
    assert service.tick(ui_open=True, now=now) == [] and sent == []
    # UI geschlossen -> Termin und TODO ueber das @calendar-Interface erinnert, danach Dedup.
    first = service.tick(ui_open=False, now=now)
    assert {item["title"] for item in first} == {"Elternabend", "Hefte einsammeln"}
    assert service.tick(ui_open=False, now=now) == []
    assert sorted(sent) == ["Elternabend", "Hefte einsammeln"]
    assert client.get("/api/plugins/erinnerungen/status").get_json()["sentToday"] == []  # anderer Tag (heute)
    # Deaktiviert -> keine Erinnerung an einem frischen Tag.
    service.replace_settings({"desktopReminders": False, "reminderMinutes": 15})
    assert service.tick(ui_open=False, now=now + timedelta(days=1)) == [] and len(sent) == 2
    # Status-Route meldet die gesendeten Keys des jeweiligen Tages.
    assert client.get("/api/plugins/erinnerungen/status").status_code == 200


def test_manifest_lists_all_js_modules_and_assets_are_served(app):
    import json

    plugin_dir = Path(__file__).resolve().parents[1] / "material_ui" / "plugins" / "erinnerungen"
    data = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
    js_files = sorted(path.name for path in (plugin_dir / "assets").glob("*.js"))
    assert {f"assets/{name}" for name in js_files} == {data["jsEntry"], *data.get("modules", [])}
    client = app.test_client()
    for name in js_files:
        response = client.get(f"/plugins/erinnerungen/assets/{name}")
        assert response.status_code == 200, name
    assert client.get("/plugins/erinnerungen/assets/erinnerungen.css").status_code == 200
    entry = (plugin_dir / "assets" / "plugin.js").read_text(encoding="utf-8")
    assert "export function register(ctx)" in entry


def test_worker_ticks_until_closing(app, monkeypatch):
    import threading

    service = _reminder_service(app)
    ticks = []
    monkeypatch.setattr(service, "tick", lambda **kwargs: ticks.append(kwargs) or [])
    monkeypatch.setattr(service, "_worker", None)  # beim App-Start bereits gestarteten Worker abloesen
    closing = threading.Event()
    started = []

    class _Workers:
        def __init__(self):
            self.closing = closing

        def start_worker(self, fn, args):
            started.append(fn)
            thread = threading.Thread(target=fn, args=args, daemon=True)
            thread.start()
            return thread

    class _Windows:
        available = True

        def live_count(self):
            return 0

    service.start_worker(_Workers(), _Windows(), interval_seconds=1)
    assert started, "Worker wurde nicht gestartet"
    import time

    deadline = time.time() + 5
    while len(ticks) < 2 and time.time() < deadline:
        time.sleep(0.05)
    closing.set()
    assert len(ticks) >= 2
    assert all(tick["ui_open"] is False for tick in ticks)
    # Erneuter Start ist ein No-Op (kein doppelter Worker).
    service.start_worker(_Workers(), _Windows())
    assert len(started) == 1
