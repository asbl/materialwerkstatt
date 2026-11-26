"""Erinnerungen-Plugin: Desktop-Benachrichtigungen bei geschlossener UI.

Liest Termine und TODOs ueber das Interface ``@calendar`` (``ctx.service("calendar")``),
prueft ueber ``ctx.windows.live_count()``, ob ein App-Fenster offen ist, und sendet
pro Tag einmal ``notify-send`` (Dedup in ``reminders.json``). Einstellungen liegen im
eigenen Plugin-Speicher (``desktopReminders``, ``reminderMinutes``).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from material_ui.errors import InvalidInput

from .reminders import ReminderNotifier, due_reminders

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "desktopReminders": True,
    "reminderMinutes": 15,
}


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Europe/Berlin")


class ReminderService:
    def __init__(self, ctx, calendar) -> None:
        self.ctx = ctx
        self.calendar = calendar
        self.settings_store = ctx.settings
        self.storage = ctx.storage
        self.notifier = ReminderNotifier(self.storage)
        self.lock = threading.RLock()
        self._worker = None

    # -- Einstellungen ------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        return {**DEFAULT_SETTINGS, **self.settings_store.load()}

    def settings_payload(self) -> dict[str, Any]:
        return self.settings()

    def replace_settings(self, incoming: Any) -> dict[str, Any]:
        if not isinstance(incoming, dict):
            raise InvalidInput("Einstellungen erwarten ein Objekt.")
        enabled = incoming.get("desktopReminders", DEFAULT_SETTINGS["desktopReminders"])
        if not isinstance(enabled, bool):
            raise InvalidInput("desktopReminders erwartet true oder false.")
        minutes = incoming.get("reminderMinutes", DEFAULT_SETTINGS["reminderMinutes"])
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= 120:
            raise InvalidInput("reminderMinutes erwartet eine ganze Zahl zwischen 1 und 120.")
        self.settings_store.replace({"desktopReminders": enabled, "reminderMinutes": minutes})
        return self.settings_payload()

    # -- Erinnerungen ------------------------------------------------------------------

    def tick(self, *, ui_open: bool, now: datetime | None = None) -> list[dict[str, Any]]:
        """Sendet faellige Erinnerungen – nur wenn kein UI-Fenster offen ist."""
        if ui_open:
            return []
        settings = self.settings()
        if not settings.get("desktopReminders"):
            return []
        zone = _zone(self.calendar.timezone() if hasattr(self.calendar, "timezone") else "Europe/Berlin")
        now = now or datetime.now(zone)
        day = now.date().isoformat()
        events = self.calendar.events(day, day)
        tasks = self.calendar.tasks()
        items = due_reminders(events, tasks, now=now, window_minutes=settings["reminderMinutes"])
        return self.notifier.tick(items, today=now.date())

    def sent_today(self) -> list[str]:
        zone = _zone(self.calendar.timezone() if hasattr(self.calendar, "timezone") else "Europe/Berlin")
        return self.notifier.sent_on(datetime.now(zone).date())

    def start_worker(self, workers, windows, interval_seconds: int = 30) -> None:
        """Hintergrund-Tick; laeuft nur, solange kein App-Fenster offen ist."""
        if self._worker is not None:
            return

        def loop():
            wait_seconds = 0
            while not workers.closing.wait(wait_seconds):
                wait_seconds = interval_seconds
                try:
                    ui_open = bool(windows is not None and windows.available and windows.live_count() > 0)
                    sent = self.tick(ui_open=ui_open)
                    if sent:
                        logger.info("Desktop-Erinnerungen versendet: %d", len(sent))
                except Exception:
                    logger.exception("Desktop-Erinnerungen fehlgeschlagen")

        workers.start_worker(loop, ())
        self._worker = loop
