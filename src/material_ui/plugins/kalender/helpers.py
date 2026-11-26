"""Reine Hilfsfunktionen des Kalender-Plugins: DAV-Fehlerabbildung, Zeitzonen,
RRULE-Parsing, Terminvalidierung und -sortierung. Ohne Service-Zustand."""

import json
import re
import logging
import socket
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from material_ui.errors import InvalidInput

DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
DEFAULT_SETTINGS: dict[str, Any] = {
    "accounts": [],
    "defaultEventCalendar": None,
    "defaultTodoCalendar": None,
    "selectedEventCalendars": None,
    "selectedTodoCalendars": None,
    "holidayCalendar": None,
    "timezone": "Europe/Berlin",
    "syncIntervalMinutes": 60,
    "windowPastDays": 30,
    "windowFutureDays": 120,
}
logger = logging.getLogger(__name__)
RETRY_DELAYS = (60, 300, 900)

ACCOUNT_FIELDS = ("label", "url", "username", "password")


def missing_dependency() -> ImportError:
    return ImportError(
        "Die Kalender-Bibliotheken fehlen. Bitte das Extra installieren: "
        "pip install -e '.[kalender]'")


def default_client_factory(account: dict[str, Any]):
    try:
        from caldav import DAVClient
    except ModuleNotFoundError:
        raise missing_dependency() from None
    return DAVClient(
        account.get("url", ""),
        username=account.get("username") or None,
        password=account.get("password") or None,
        timeout=15,
    )


def _sync_error(error: Exception) -> tuple[str, bool]:
    """Transportfehler können durch urllib3/requests/CalDAV verschachtelt sein."""
    pending = [error]
    seen = set()
    transient = False
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        status = getattr(getattr(current, "response", None), "status_code", None)
        if status in (401, 403) or type(current).__name__ in ("AuthorizationError", "AuthenticationError"):
            return "Anmeldung fehlgeschlagen. Bitte Benutzername, Passwort und Zugriffsrechte in den Einstellungen prüfen.", False
        if (isinstance(current, (ConnectionError, TimeoutError, socket.gaierror))
                or type(current).__name__ in ("ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout",
                                             "NameResolutionError", "NewConnectionError")
                or status in (408, 429, 500, 502, 503, 504)):
            transient = True
        for nested in (getattr(current, "__cause__", None), getattr(current, "__context__", None),
                       getattr(current, "reason", None), *getattr(current, "args", ())):
            if isinstance(nested, BaseException):
                pending.append(nested)
    if transient:
        return "Der Kalenderdienst ist gerade nicht erreichbar.", True
    return "Der Abgleich ist fehlgeschlagen. Bitte die Kalendereinstellungen prüfen.", False


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise InvalidInput(f"Unbekannte Zeitzone: {name}") from error


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _parse_recurrence(value: Any):
    """RRULE aus dem Erstellungsdialog. None = keine Wiederholung."""
    if not isinstance(value, dict):
        return None
    freq = str(value.get("freq", "")).upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY"):
        return None
    interval = value.get("interval", 1)
    if not isinstance(interval, int) or interval < 1 or interval > 366:
        raise InvalidInput("Wiederholungsintervall muss zwischen 1 und 366 liegen.")
    rule = {"freq": freq, "interval": interval}
    until = value.get("until", "")
    if until:
        try:
            rule["until"] = date.fromisoformat(str(until))
        except (ValueError, TypeError):
            raise InvalidInput("Ungültiges Wiederholungsende (JJJJ-MM-TT).") from None
    return rule


def _recurrence_of(component) -> dict[str, Any] | None:
    """RRULE eines iCalendar-Components als Dialog-Werte (freq/interval/until als ISO-Text)."""
    rule = component.get("rrule") if component is not None else None
    if not rule:
        return None

    def first(value):
        return value[0] if isinstance(value, (list, tuple)) else value

    freq = str(first(rule.get("freq")) or "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY"):
        return None
    interval = first(rule.get("interval"))
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        interval = 1
    result: dict[str, Any] = {"freq": freq, "interval": max(1, interval)}
    until = first(rule.get("until"))
    if until is not None:
        result["until"] = until.isoformat() if hasattr(until, "isoformat") else str(until)
    return result


def _recurrence_json(rule: dict[str, Any] | None) -> dict[str, Any] | None:
    """Dialog-RRULE (mit date-Objekt fuer until) JSON-serialisierbar machen."""
    if not rule:
        return None
    result = {"freq": rule["freq"], "interval": rule["interval"]}
    until = rule.get("until")
    if until is not None:
        result["until"] = until.isoformat() if hasattr(until, "isoformat") else str(until)
    return result


def _normalise_dates(start: str, end: str, zone: ZoneInfo) -> tuple[date, date]:
    for value, name in ((start, "from"), (end, "to")):
        if not DATE_PATTERN.fullmatch(value or ""):
            raise InvalidInput(f"{name} erwartet ein Datum im Format JJJJ-MM-TT.")
    begin = date.fromisoformat(start)
    finish = date.fromisoformat(end)
    if finish < begin:
        raise InvalidInput("Das Ende des Zeitraums liegt vor dem Anfang.")
    _ = zone
    return begin, finish


def _event_sort_key(event: dict[str, Any], zone: ZoneInfo) -> tuple:
    if event["allDay"]:
        local_day = date.fromisoformat(event["startDate"])
        instant = datetime.combine(local_day, datetime.min.time(), tzinfo=zone)
    else:
        instant = datetime.fromisoformat(event["start"])
        if instant.utcoffset() is None:
            raise ValueError("Termin braucht einen Zeitzonenoffset.")
        local_day = instant.astimezone(zone).date()
    return local_day, 0 if event["allDay"] else 1, instant.astimezone(timezone.utc), event["key"]


def _validate_source_events(events, zone: ZoneInfo) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        raise ValueError("Kalenderquelle muss eine Liste liefern.")
    string_fields = ("key", "title", "start", "end", "startDate", "endDate",
                     "calendar", "account", "location", "description", "url")
    for event in events:
        if (not isinstance(event, dict)
                or any(not isinstance(event.get(field), str) for field in string_fields)
                or not isinstance(event.get("allDay"), bool)):
            raise ValueError("Ungültiges Terminformat einer Kalenderquelle.")
        begin, finish = date.fromisoformat(event["startDate"]), date.fromisoformat(event["endDate"])
        if finish < begin or not event["key"]:
            raise ValueError("Ungültiger Terminzeitraum oder leerer Terminschlüssel.")
        _event_sort_key(event, zone)
        if event["allDay"]:
            if date.fromisoformat(event["end"]) < date.fromisoformat(event["start"]):
                raise ValueError("Ungültiges Terminende.")
        else:
            end = datetime.fromisoformat(event["end"])
            if end.utcoffset() is None or end < datetime.fromisoformat(event["start"]):
                raise ValueError("Ungültiges Terminende.")
    return events


LESSON_FIELDS = ("start", "title", "end", "location")


def _lesson_to_property(lesson):
    """Verknüpfte Unterrichtsstunde als kompaktes JSON in einer X-Property."""
    if not lesson:
        return None
    return json.dumps({key: str(lesson.get(key, "")) for key in LESSON_FIELDS},
                      ensure_ascii=False, sort_keys=True)


def _lesson_from_property(raw):
    if not raw:
        return None
    try:
        value = json.loads(str(raw))
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("start"), str) or not value["start"]:
        return None
    return {key: value.get(key) if isinstance(value.get(key), str) else ""
            for key in LESSON_FIELDS}
