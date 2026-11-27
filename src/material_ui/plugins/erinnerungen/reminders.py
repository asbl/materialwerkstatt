"""Reine Reminder-Logik des Erinnerungen-Plugins.

Berechnung (``due_reminders``) und Benachrichtigung (``ReminderNotifier``) sind
getrennt, damit Tests ohne ``notify-send`` laufen. Pro Tag wird jede Erinnerung
genau einmal gesendet (Dedup ueber ``reminders.json`` im Plugin-Speicher).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import date, datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger(__name__)

MAX_BODY = 240
REMINDER_RETENTION_DAYS = 7


def _parse_start(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def due_reminders(events, tasks, *, now: datetime, window_minutes: int = 15,
                  today: date | None = None) -> list[dict[str, Any]]:
    """Termine, die innerhalb des Erinnerungsfensters beginnen, plus heute faellige TODOs.

    Feiertage, ausgefallene Stunden und TODOs als Termineintraege werden nicht erinnert.
    """
    today = today or now.date()
    horizon = now + timedelta(minutes=window_minutes)
    items: list[dict[str, Any]] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        if event.get("kind") == "todo" or event.get("holiday") or event.get("cancelled"):
            continue
        start = _parse_start(event.get("start"))
        if start is None or not now <= start <= horizon:
            continue
        if str(event.get("startDate") or "")[:10] != today.isoformat():
            continue
        title = str(event.get("title") or "(ohne Titel)")
        body = f"{start.strftime('%H:%M')} Uhr"
        if event.get("location"):
            body += f" · {event['location']}"
        calendar = str(event.get("calendar") or "")
        if calendar and calendar != "Lokale Termine":
            body += f" · Kalender: {calendar}"
        items.append({
            "key": f"event:{event.get('key') or event.get('uid') or title}@{start.isoformat()}",
            "title": title,
            "body": body[:MAX_BODY],
            "start": start.isoformat(),
        })
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        start_date = str(task.get("startDate") or "")[:10]
        planned = str(task.get("plannedDate") or "")[:10]
        if start_date != today.isoformat() and planned != today.isoformat():
            continue
        title = str(task.get("title") or "TODO")
        if start_date == today.isoformat():
            body = "Heute fällig"
        elif planned == today.isoformat():
            body = "Heute eingeplant" + (f" · fällig am {start_date}" if start_date else "")
        else:
            body = "Heute fällig"
        lesson = task.get("lesson")
        if isinstance(lesson, dict) and lesson.get("title"):
            body += f" · {lesson['title']}"
        items.append({
            "key": f"task:{task.get('id') or task.get('key') or title}",
            "title": title,
            "body": body[:MAX_BODY],
            "start": "",
        })
    items.sort(key=lambda item: item["start"])
    return items


def default_notify(title: str, body: str) -> bool:
    """``notify-send`` mit App-Name und Icon, wenn vorhanden; sonst nur Log.

    Argumente als Liste mit ``--`` vor Summary/Body: keine Shell, keine
    Optionsinjektion durch Titel. Wirft nie eine Exception.
    """
    binary = shutil.which("notify-send")
    if not binary:
        logger.info("Erinnerung (kein notify-send installiert): %s – %s", title, body)
        return False
    try:
        subprocess.run(
            [binary, "--app-name=Material-UI", "--icon=appointment-soon", "--", title, body],
            timeout=5, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        logger.warning("notify-send fehlgeschlagen", exc_info=True)
        return False


class ReminderNotifier:
    """Dedup pro Tag ueber ``reminders.json``; ``notify`` ist fuer Tests austauschbar."""

    def __init__(self, storage, *, notify: Callable[[str, str], Any] | None = None):
        self.storage = storage
        self._notify = notify or default_notify

    def tick(self, items, *, today: date) -> list[dict[str, Any]]:
        day = today.isoformat()
        path = self.storage.shared_path("reminders.json")
        data = self.storage.read_json(path, default={})
        if not isinstance(data, dict):
            data = {}
        notified = {str(key) for key in data.get(day) or []}
        sent: list[dict[str, Any]] = []
        for item in items or []:
            key = str(item.get("key") or "")
            if not key or key in notified:
                continue
            self._notify(str(item.get("title") or ""), str(item.get("body") or ""))
            notified.add(key)
            sent.append(item)
        cutoff = (today - timedelta(days=REMINDER_RETENTION_DAYS)).isoformat()
        pruned = {key: value for key, value in data.items() if isinstance(key, str) and key >= cutoff}
        # Ohne Erinnerung keinen leeren Tag anlegen: sonst schreibt jeder Rechner taeglich.
        if notified:
            pruned[day] = sorted(notified)
        # Nur schreiben, wenn sich etwas geaendert hat (neue Erinnerung oder Aufraeumen).
        # private=True (0600): Keys koennen als Fallback Termintitel enthalten.
        if sent or pruned != data:
            self.storage.write_json(path, pruned, private=True)
        return sent

    def sent_on(self, today: date) -> list[str]:
        data = self.storage.read_json(self.storage.shared_path("reminders.json"), default={})
        if not isinstance(data, dict):
            return []
        return [str(key) for key in data.get(today.isoformat()) or []]
