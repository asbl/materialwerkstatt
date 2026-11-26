from __future__ import annotations

import re
from uuid import uuid4
from urllib.parse import urlsplit
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from material_ui.errors import InvalidInput
from material_ui.plugins.storage import PASSWORD_PLACEHOLDER

from .calendar_interface import CalendarInterface

from .helpers import (  # noqa: E402
    DEFAULT_SETTINGS, RETRY_DELAYS,
    _as_list, _event_sort_key, _lesson_from_property, _lesson_to_property,
    _normalise_dates, _parse_recurrence, _recurrence_json, _recurrence_of,
    _sync_error, _validate_source_events, _zone, default_client_factory,
    logger, missing_dependency,
)



class KalenderService:
    """CalDAV-Abgleich, lokaler JSON-Cache und Abfragen für Kalender und Agenda.

    Der Cache ist bewusst einfach: Bei jedem Abgleich wird das Zeitfenster der
    Einstellungen komplett neu gelesen und der Cache ersetzt. Ansichten lesen nur
    den Cache. Bei Ausfällen bleiben die zuletzt geladenen Termine erhalten.
    """

    def __init__(self, ctx, client_factory=None, clock=time.time) -> None:
        self.ctx = ctx
        self.settings_store = ctx.settings
        self.storage = ctx.storage
        # Fabrik zur Laufzeit aufloesen: Tests klemmen einen gefaekschten CalDAV-Zugang davor.
        self.client_factory = client_factory or default_client_factory
        self.clock = clock
        self.lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._sync_running = False
        self._interval_worker = None
        self.calendar_interface = CalendarInterface()   # das Plugin-Interface @calendar

    def _calendar_sources(self):
        """Über @calendar registrierte Terminquellen (auch die eigenen Planungsmarker)."""
        return self.calendar_interface.sources()

    # ------------------------------------------------------------------ Pfade

    def _cache_path(self) -> Path:
        return self.storage.path("cache.json")

    def _status_path(self) -> Path:
        return self.storage.path("status.json")

    # ------------------------------------------------------------- Einstellungen

    def settings(self) -> dict[str, Any]:
        return {**DEFAULT_SETTINGS, **self.settings_store.load()}

    def settings_payload(self) -> dict[str, Any]:
        # Passwörter werden nie ausgeliefert; die Maske signalisiert Setzen-Behalten.
        return {**DEFAULT_SETTINGS, **self.settings_store.masked()}

    def _validate_accounts(self, accounts: Any) -> list[dict[str, Any]]:
        if not isinstance(accounts, list):
            raise InvalidInput("accounts erwartet eine Liste.")
        cleaned: list[dict[str, Any]] = []
        seen_labels: set[str] = set()
        for account in accounts:
            if not isinstance(account, dict):
                raise InvalidInput("Jedes Konto ist ein Objekt.")
            label = str(account.get("label", "")).strip()
            url = str(account.get("url", "")).strip()
            if not label or not url:
                raise InvalidInput("Jedes Konto braucht Bezeichnung und URL.")
            if label in seen_labels:
                raise InvalidInput(f"Konto-Bezeichnung mehrfach vergeben: {label}")
            try:
                parsed = urlsplit(url)
                valid = (parsed.scheme == "https" and bool(parsed.hostname)
                         and parsed.username is None and parsed.password is None
                         and not parsed.query and not parsed.fragment and parsed.port != 0
                         and not any(char.isspace() for char in url))
            except ValueError:
                valid = False
            if not valid:
                raise InvalidInput("Kalender-URL braucht HTTPS und darf keine Zugangsdaten, Query oder Fragmente enthalten.")
            seen_labels.add(label)
            cleaned.append({
                "label": label,
                "url": url,
                "username": str(account.get("username", "")),
                "password": str(account.get("password", "")),
                "calendars": _as_list(account.get("calendars")),
            })
        return cleaned

    def replace_settings(self, incoming: Any) -> dict[str, Any]:
        if not isinstance(incoming, dict):
            raise InvalidInput("Einstellungen erwarten ein Objekt.")
        accounts = self._validate_accounts(incoming.get("accounts", []))
        zone_name = str(incoming.get("timezone") or DEFAULT_SETTINGS["timezone"])
        _zone(zone_name)
        interval = incoming.get("syncIntervalMinutes", DEFAULT_SETTINGS["syncIntervalMinutes"])
        if not isinstance(interval, int) or interval < 0:
            raise InvalidInput("syncIntervalMinutes erwartet eine ganze Zahl ab 0.")
        past = incoming.get("windowPastDays", DEFAULT_SETTINGS["windowPastDays"])
        future = incoming.get("windowFutureDays", DEFAULT_SETTINGS["windowFutureDays"])
        for value, name in ((past, "windowPastDays"), (future, "windowFutureDays")):
            if not isinstance(value, int) or value < 0 or value > 3650:
                raise InvalidInput(f"{name} erwartet eine ganze Zahl zwischen 0 und 3650.")
        candidate = {
            "accounts": accounts,
            "timezone": zone_name,
            "syncIntervalMinutes": interval,
            "windowPastDays": past,
            "windowFutureDays": future,
        }
        for field in ("defaultEventCalendar", "defaultTodoCalendar", "holidayCalendar"):
            target = incoming.get(field)
            if target is not None:
                if (not isinstance(target, dict)
                        or not isinstance(target.get("account"), str)
                        or not isinstance(target.get("name"), str)
                        or not target["name"].strip()
                        or (field != "holidayCalendar" and not target["account"].strip())):
                    raise InvalidInput(f"{field} erwartet Konto und Kalendername oder null.")
                target = {"account": target["account"], "name": target["name"]}
            candidate[field] = target
        for field in ("selectedEventCalendars", "selectedTodoCalendars"):
            targets = incoming.get(field)
            if targets is not None:
                if (not isinstance(targets, list) or any(
                        not isinstance(t, dict) or not isinstance(t.get("account"), str)
                        or not isinstance(t.get("name"), str) for t in targets)):
                    raise InvalidInput(f"{field} erwartet eine Liste von Konten und Kalendernamen.")
                targets = [{"account": t["account"], "name": t["name"]} for t in targets]
            candidate[field] = targets
        # Ein unverändertes Maskenfeld im Konto behält das gespeicherte Passwort.
        stored_accounts = self.settings_store.load().get("accounts", [])
        for new_account in candidate["accounts"]:
            if new_account["password"] == PASSWORD_PLACEHOLDER:
                stored = next((item for item in stored_accounts if all(
                    item.get(key) == new_account.get(key) for key in ("label", "url", "username")
                )), {})
                new_account["password"] = str(stored.get("password", ""))
        self.settings_store.replace(candidate)
        return self.settings_payload()

    # ------------------------------------------------------------------- Abgleich

    def _window(self, settings: dict[str, Any]) -> tuple[datetime, datetime, date, date]:
        zone = _zone(settings["timezone"])
        today = datetime.now(zone).date()
        begin = today - timedelta(days=settings["windowPastDays"])
        end = today + timedelta(days=settings["windowFutureDays"])
        start_dt = datetime(begin.year, begin.month, begin.day, tzinfo=zone)
        end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=zone)
        return start_dt, end_dt, begin, end

    def _occurrences(self, resource, start_dt: datetime, end_dt: datetime) -> list:
        """Vorkommen als (Component, Serienregel) – die Serienregel des Masters, damit
        die Ansicht eine Serie bearbeiten kann, ohne das Master-Component zu kennen."""
        try:
            from recurring_ical_events import of
        except ModuleNotFoundError:
            raise missing_dependency() from None
        calendar_component = resource.icalendar_instance
        masters = calendar_component.walk("VEVENT")
        series = _recurrence_of(masters[0]) if len(masters) == 1 else None
        occurrences = of(calendar_component, skip_bad_series=True).between(start_dt, end_dt)
        return [(occurrence, series) for occurrence in occurrences]

    def _normalise_occurrence(self, component, account: str, calendar: str, zone: ZoneInfo) -> dict[str, Any]:
        def text(name: str) -> str:
            value = component.get(name)
            return "" if value is None else str(value).strip()

        start_value = component.get("dtstart")
        end_value = component.get("dtend")
        start_dt = getattr(start_value, "dt", None)
        end_dt = getattr(end_value, "dt", None)
        if start_dt is None:
            return {}
        all_day = not isinstance(start_dt, datetime)

        def iso(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, datetime):
                return value.isoformat()
            return value.isoformat()

        def day(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, datetime):
                return value.astimezone(zone).date().isoformat()
            return value.isoformat()

        end_dt = end_dt or start_dt
        end_day = day(end_dt)
        if all_day and day(start_dt) < end_day:
            # Ganztägige Ende sind im iCalendar exklusiv; fuer die Ansicht inklusiv halten.
            end_day = (date.fromisoformat(end_day) - timedelta(days=1)).isoformat()
        start_day = day(start_dt)
        uid = text("uid")
        return {
            "key": f"{uid}@{start_day}{'T' + iso(start_dt)[11:] if not all_day else ''}",
            "uid": uid,
            "account": account,
            "calendar": calendar,
            "title": text("summary") or "(ohne Titel)",
            "start": iso(start_dt),
            "end": iso(end_dt),
            "startDate": start_day,
            "endDate": end_day,
            "allDay": all_day,
            "location": text("location"),
            "description": text("description"),
            "unitPath": text("x-material-unit"),
            "url": text("url"),
            "status": text("status"),
            "categories": _as_list(component.get("categories")),
            "recurring": bool(component.get("rrule") or component.get("rdate") or component.get("recurrence-id")),
            "recurrence": _recurrence_of(component),
            "recurrenceId": bool(component.get("recurrence-id")),
        }

    @staticmethod
    def _supported_components(calendar):
        getter = getattr(calendar, "get_supported_components", None)
        return list(getter()) if getter else ["VEVENT", "VTODO"]

    def _normalise_todo(self, component, account, calendar, zone):
        if str(component.get("status", "")).upper() in ("COMPLETED", "CANCELLED"):
            return {}
        assigned = component.get("due") or component.get("dtstart")
        from icalendar import Event
        proxy = Event()
        for field in ("uid", "summary", "description", "location", "url", "status"):
            if component.get(field) is not None:
                proxy[field] = component[field]
        proxy.add("dtstart", assigned.dt if assigned else date(1970, 1, 1))
        event = self._normalise_occurrence(proxy, account, calendar, zone)
        event["kind"] = "todo"
        event["unitPath"] = str(component.get("x-material-unit", ""))
        event["lesson"] = _lesson_from_property(component.get("x-material-lesson"))
        # Wiederholungsinformation erhalten, damit das Erledigen einer Serie
        # nicht versehentlich die ganze Serie beendet.
        event["recurring"] = bool(component.get("rrule") or component.get("rdate"))
        event["recurrence"] = _recurrence_of(component)
        event["recurrenceId"] = bool(component.get("recurrence-id"))
        if assigned is None:
            for field in ("start", "end", "startDate", "endDate"):
                event[field] = ""
        return event

    def _read_account(self, account: dict[str, Any], start_dt: datetime, end_dt: datetime,
                      zone: ZoneInfo) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []
        calendars_meta: list[dict[str, Any]] = []
        allowlist = account.get("calendars") or []
        self._validate_accounts([account])
        client = self.client_factory(account)
        try:
            principal = client.principal()
            for calendar in principal.calendars():
                name = str(getattr(calendar, "name", None) or calendar.id)
                if allowlist and name not in allowlist:
                    continue
                components = self._supported_components(calendar)
                calendars_meta.append({"account": account["label"], "name": name, "components": components})
                if "VTODO" in components and hasattr(calendar, "todos"):
                    for resource in calendar.todos(include_completed=False):
                        for component in resource.icalendar_instance.walk("VTODO"):
                            event = self._normalise_todo(component, account["label"], name, zone)
                            if event:
                                events.append(event)
                found = calendar.date_search(start=start_dt, end=end_dt, expand=False) if "VEVENT" in components else []
                for resource in found:
                    for component, series in self._occurrences(resource, start_dt, end_dt):
                        event = self._normalise_occurrence(component, account["label"], name, zone)
                        if event and component.get("recurrence-id") and series:
                            # Vorkommen einer Serie: Regel des Masters mitliefern,
                            # damit die Serie in der UI bearbeitbar bleibt.
                            event["recurrence"] = series
                            event["recurring"] = True
                        if event:
                            events.append(event)
        finally:
            if hasattr(client, "close"):
                client.close()
        return events, calendars_meta

    def sync_now(self, retry_only: bool = False) -> dict[str, Any]:
        with self._sync_lock:
            self._sync_running = True
            try:
                return self._sync_now(retry_only)
            finally:
                self._sync_running = False

    def _sync_now(self, retry_only: bool) -> dict[str, Any]:
        previous = self.storage.read_json(self._status_path(), default={})
        old_cache = self.storage.read_json(self._cache_path(), default={})
        settings = self.settings()
        zone = _zone(settings["timezone"])
        start_dt, end_dt, begin, end = self._window(settings)
        events: list[dict[str, Any]] = []
        calendars_meta: list[dict[str, Any]] = []
        failures = {}
        for account in settings.get("accounts", []):
            label = account["label"]
            old_failure = previous.get("accountErrors", {}).get(label)
            if retry_only and old_failure and not old_failure["retryable"]:
                failures[label] = old_failure
                events.extend(e for e in old_cache.get("events", []) if e.get("account") == label)
                calendars_meta.extend(c for c in previous.get("calendars", []) if c.get("account") == label)
                continue
            try:
                account_events, account_calendars = self._read_account(account, start_dt, end_dt, zone)
                events.extend(account_events)
                calendars_meta.extend(account_calendars)
            except Exception as error:  # Fehler eines Kontos bricht den Rest nicht ab
                message, retryable = _sync_error(error)
                # Keine rohen Exceptions: DAV-Fehler können Zugangsdaten enthalten.
                logger.warning("Kalender-Abgleich: Fehlertyp=%s, wiederholbar=%s",
                               type(error).__name__, retryable)
                failures[label] = {"message": message, "retryable": retryable}
                events.extend(e for e in old_cache.get("events", []) if e.get("account") == label)
                calendars_meta.extend(c for c in previous.get("calendars", []) if c.get("account") == label)
        errors = [failure["message"] for failure in failures.values()]
        known: set[tuple[str, str]] = set()
        unique: list[dict[str, Any]] = []
        for event in events:
            identity = (event["account"], event["key"])
            if identity in known:
                continue
            known.add(identity)
            unique.append(event)
        unique.sort(key=lambda item: (item["startDate"], item["start"], item["title"]))
        cache = {
            "window": {"from": begin.isoformat(), "to": end.isoformat(),
                       "start": start_dt.isoformat(), "end": end_dt.isoformat()},
            "timezone": settings["timezone"],
            "events": unique,
        }
        # Bei Teilfehlern keine erweiterte Cache-Abdeckung behaupten.
        if errors:
            cache["window"] = old_cache.get("window")
        now = self.clock()
        failure_count = previous.get("failureCount", 0) + 1 if errors else 0
        interval = settings["syncIntervalMinutes"] * 60
        retryable = any(f["retryable"] for f in failures.values())
        retry_delay = RETRY_DELAYS[failure_count - 1] if retryable and failure_count <= len(RETRY_DELAYS) else None
        next_sync = now + (retry_delay or interval) if interval else None
        last_success = previous.get("lastSuccessfulSync")
        if last_success is None and previous.get("lastSync", {}).get("ok"):
            last_success = previous["lastSync"]["time"]
        status = {
            "lastSuccessfulSync": last_success if errors else now,
            "failureCount": failure_count,
            "accountErrors": failures,
            "nextSync": next_sync,
            "retryPending": bool(interval and retry_delay),
            "lastSync": {
                "time": self.clock(),
                "ok": not errors,
                "message": "; ".join(errors) if errors else f"{len(unique)} Termine synchronisiert.",
                "eventCount": len(unique),
            },
            "calendars": calendars_meta,
        }
        with self.lock:
            self.storage.write_json(self._cache_path(), cache)
            self.storage.write_json(self._status_path(), status)
        if errors:
            return {"ok": False, "message": "; ".join(errors)}
        return {"ok": True, "message": f"{len(unique)} Termine synchronisiert."}

    # ------------------------------------------------------------ Lese-APIs

    def status(self) -> dict[str, Any]:
        settings = self.settings()
        status = self.storage.read_json(self._status_path(), default={})
        last_sync = status.get("lastSync") or None
        if last_sync and not last_sync.get("ok"):
            # Auch Altbestände dürfen keine rohen DAV-Exceptions ausliefern.
            messages = {
                _sync_error(ConnectionError())[0],
                _sync_error(Exception())[0],
                "Anmeldung fehlgeschlagen. Bitte Benutzername, Passwort und Zugriffsrechte in den Einstellungen prüfen.",
            }
            message = last_sync.get("message", "")
            if not message or any(part not in messages for part in message.split("; ")):
                transport = any(marker in message for marker in (
                    "NameResolutionError", "Failed to resolve", "ConnectionError",
                    "HTTPSConnectionPool", "Timeout", "name resolution",
                ))
                last_sync = {**last_sync, "message": _sync_error(
                    ConnectionError() if transport else Exception())[0]}
        payload = {
            "configured": bool(settings.get("accounts")),
            "syncRunning": self._sync_running,
            "intervalMinutes": settings.get("syncIntervalMinutes"),
            "lastSync": last_sync,
            "lastSuccessfulSync": status.get("lastSuccessfulSync"),
            "nextSync": status.get("nextSync") if settings["syncIntervalMinutes"] else None,
            "retryPending": bool(settings["syncIntervalMinutes"] and status.get("retryPending")),
            "calendars": status.get("calendars") or [],
            "cacheWindow": (self.storage.read_json(self._cache_path(), default={}) or {}).get("window"),
        }
        return payload

    @staticmethod
    def _validate_lesson(value, kind, day, zone):
        """Nur TODOs mit Fälligkeitsdatum verknüpfen eine Unterrichtsstunde dieses Tages."""
        if value in (None, ''):
            return None
        if kind != 'todo':
            raise InvalidInput('Nur TODOs können mit einer Unterrichtsstunde verknüpft werden.')
        if (not isinstance(value, dict) or not isinstance(value.get('start'), str)
                or not isinstance(value.get('title'), str)):
            raise InvalidInput('Ungültige Unterrichtsstunde.')
        try:
            start_dt = datetime.fromisoformat(value['start'])
        except ValueError:
            raise InvalidInput('Ungültige Unterrichtsstunde.') from None
        if start_dt.utcoffset() is None:
            raise InvalidInput('Ungültige Unterrichtsstunde.')
        if day is None:
            raise InvalidInput('Ohne Fälligkeitsdatum kann keine Unterrichtsstunde verknüpft werden.')
        if start_dt.astimezone(zone).date() != day:
            raise InvalidInput('Die Unterrichtsstunde liegt nicht am gewählten Tag.')
        return {'start': value['start'], 'title': value['title'].strip(),
                'end': value.get('end') if isinstance(value.get('end'), str) else '',
                'location': value.get('location') if isinstance(value.get('location'), str) else ''}

    def create_event(self, payload, *, original=None, resource=None):
        if not isinstance(payload, dict) or not isinstance(payload.get('title'), str) or not payload['title'].strip():
            raise InvalidInput('Bitte einen Titel angeben.')
        kind = payload.get('kind', 'event')
        if kind not in ('event', 'todo'):
            raise InvalidInput('Bitte Termin oder TODO auswählen.')
        try:
            day = date.fromisoformat(payload['date']) if payload.get('date') else (None if kind == 'todo' else date.fromisoformat(''))
            zone = _zone(self.settings()['timezone'])
            timed = kind != 'todo' and bool(payload.get('time'))
            start = datetime.fromisoformat(f"{day}T{payload['time']}").replace(tzinfo=zone) if timed else day
            end_day = date.fromisoformat(payload.get('endDate') or str(day)) if day else None
            end = (datetime.fromisoformat(f"{end_day}T{payload['endTime']}").replace(tzinfo=zone)
                   if timed and payload.get('endTime') else (start if timed else end_day))
            if end is not None and start is not None and end < start:
                raise ValueError()
        except (ValueError, TypeError):
            raise InvalidInput('Bitte Datum und Uhrzeit prüfen; das Ende darf nicht vor dem Beginn liegen.') from None
        for key in ('location', 'description'):
            if not isinstance(payload.get(key, ''), str):
                raise InvalidInput('Ort und Beschreibung müssen Text sein.')
        unit_path = payload.get('unitPath', '')
        if not isinstance(unit_path, str):
            raise InvalidInput('Ungültige Unterrichtseinheit.')
        recurrence = _parse_recurrence(payload.get('recurrence'))
        lesson = self._validate_lesson(payload.get('lesson'), kind, day, zone)
        if lesson is not None:
            # Unveränderte Verknüpfung bleibt auch bei vorübergehendem Quellenfehler erhalten.
            unchanged = bool(original) and (original.get('lesson') or {}).get('start') == lesson['start']
            available = {item['start'] for item in self.lessons(day.isoformat())['lessons']}
            if not unchanged and lesson['start'] not in available:
                raise InvalidInput('Die Unterrichtsstunde ist am gewählten Tag nicht verfügbar.')
        account_label = payload.get('account', '')
        calendar_name = payload.get('calendar', 'Lokale Termine')
        if not isinstance(account_label, str) or not isinstance(calendar_name, str):
            raise InvalidInput('Bitte einen Kalender auswählen.')
        if account_label:
            account = next((item for item in self.settings()['accounts']
                            if item['label'] == account_label), None)
            if account is None or (account.get('calendars') and calendar_name not in account['calendars']):
                raise InvalidInput('Der ausgewählte Kalender ist nicht verfügbar.')
            try:
                self._validate_accounts([account])
                client = self.client_factory(account)
            except Exception:
                raise InvalidInput("Kalender-Verbindung fehlgeschlagen. Bitte Zugangsdaten prüfen.") from None
            try:
                calendar = next((item for item in client.principal().calendars()
                                 if str(getattr(item, 'name', None) or item.id) == calendar_name), None)
                if calendar is None:
                    raise InvalidInput('Der ausgewählte Kalender ist nicht verfügbar.')
                required = "VTODO" if kind == "todo" else "VEVENT"
                if required not in self._supported_components(calendar):
                    raise InvalidInput("Dieser Kalender unterstützt diesen Eintragstyp nicht. Bitte Termin / TODO oder den Kalender ändern.")
                from icalendar import Calendar, Event, Todo

                document = resource.icalendar_instance if resource else Calendar()
                component = next(iter(document.walk('VTODO' if kind == 'todo' else 'VEVENT')), None)
                if component is None:
                    component = Todo() if kind == 'todo' else Event()
                    document.add_component(component)
                for name, value in {
                    'uid': str(component.get('uid') or uuid4().hex), 'dtstamp': datetime.now(timezone.utc),
                    'dtstart': start,
                    **({'due': day, 'status': component.get('status', 'NEEDS-ACTION')} if kind == 'todo' else
                       {'dtend': end if timed else end_day + timedelta(days=1)}),
                    'summary': payload['title'].strip(), 'location': payload.get('location', ''),
                    'description': payload.get('description', ''),
                    'x-material-unit': unit_path,
                    'x-material-lesson': _lesson_to_property(lesson),
                }.items():
                    component.pop(name, None)
                    if value is not None:
                        component.add(name, value)
                component.pop('rrule', None)
                component.pop('rdate', None)
                if recurrence:
                    component.add('rrule', recurrence)
                if not resource:
                    document.add('version', '2.0')
                    document.add('prodid', '-//Materialwerkstatt//Kalender//DE')
                component.pop('duration', None)
                save = calendar.save_todo if kind == 'todo' else calendar.save_event
                same_calendar = original and original.get('account') == account_label and original.get('calendar') == calendar_name
                if resource and same_calendar:
                    resource.save()
                else:
                    saved = save(document.to_ical().decode('utf-8'))
                    if resource:
                        try:
                            resource.delete()
                        except Exception:
                            if saved is not None:
                                saved.delete()
                            raise
            except InvalidInput:
                raise
            except Exception as error:
                logger.warning('Kalender-Speichern: Fehlertyp=%s', type(error).__name__)
                raise InvalidInput('Eintrag konnte nicht gespeichert werden. ' + _sync_error(error)[0]) from None
            finally:
                if hasattr(client, 'close'):
                    try:
                        client.close()
                    except Exception:
                        pass
            event = (self._normalise_todo(component, account_label, calendar_name, zone) if kind == 'todo'
                     else self._normalise_occurrence(component, account_label, calendar_name, zone))
            with self.lock:
                cache = self.storage.read_json(self._cache_path(), default={})
                entries = cache.setdefault('events', [])
                if original:
                    entries[:] = [e for e in entries if not (e.get('key') == original['key'] and e.get('account') == original.get('account'))]
                entries.append(event)
                self.storage.write_json(self._cache_path(), cache)
            return event
        if calendar_name != 'Lokale Termine':
            raise InvalidInput('Bitte ein Konto für den Kalender auswählen.')
        event = dict(key=original['key'] if original and not original.get('account') else 'local:' + uuid4().hex, kind=kind, title=payload['title'].strip(),
                     start=start.isoformat() if start else '', end=end.isoformat() if end else '', startDate=day.isoformat() if day else '', endDate=end_day.isoformat() if end_day else '',
                     allDay=not timed, calendar='Lokale Termine', account='', location=payload.get('location', ''),
                     description=payload.get('description', ''), url='', unitPath=unit_path, recurring=bool(recurrence),
                     recurrence=_recurrence_json(recurrence), lesson=lesson)
        with self.lock:
            path = self.storage.path('local-events.json')
            events = self.storage.read_json(path, default=[])
            events = [e for e in events if not original or e['key'] != original['key']]
            events.append(event)
            self.storage.write_json(path, events)
            if resource:
                try:
                    resource.delete()
                except Exception:
                    self.storage.write_json(path, [e for e in events if e['key'] != event['key']])
                    raise
        return event

    def update_event(self, payload):
        if not isinstance(payload, dict):
            raise InvalidInput('Ungültiger Eintrag.')
        with self._sync_lock:
            cache = self.storage.read_json(self._cache_path(), default={})
            local_path = self.storage.path('local-events.json')
            local = self.storage.read_json(local_path, default=[])
            original = next((e for e in [*cache.get('events', []), *local]
                             if e.get('key') == payload.get('key') and e.get('account', '') == payload.get('originalAccount', '')
                             and e.get('calendar') == payload.get('originalCalendar')), None)
            if original is None:
                raise InvalidInput('Der Eintrag ist nicht mehr verfügbar. Bitte aktualisieren.')
            if payload.get('kind', 'event') != original.get('kind', 'event'):
                raise InvalidInput('Der Eintragstyp kann beim Bearbeiten nicht geändert werden.')
            client = None
            try:
                resource = None
                if original.get('account'):
                    account = next(a for a in self.settings()['accounts'] if a['label'] == original['account'])
                    self._validate_accounts([account])
                    client = self.client_factory(account)
                    calendar = next(c for c in client.principal().calendars()
                                    if str(getattr(c, 'name', None) or c.id) == original['calendar'])
                    resources = calendar.todos(include_completed=False) if original.get('kind') == 'todo' else calendar.events()
                    component_type = 'VTODO' if original.get('kind') == 'todo' else 'VEVENT'
                    resource = next(r for r in resources if any(str(c.get('uid', '')) == original['uid']
                                    for c in r.icalendar_instance.walk(component_type)))
                    components = resource.icalendar_instance.walk(component_type)
                    # Serien-Master (RRULE ohne RECURRENCE-ID) duerfen bearbeitet werden;
                    # Aenderungen gelten dann fuer die ganze Serie. Einzelne Ausnahmen
                    # (RECURRENCE-ID auf der Ressource) bleiben dem urspruenglichen Kalender vorbehalten.
                    if len(components) != 1 or any(c.get('recurrence-id') for c in components):
                        raise InvalidInput('Einzelne Ausnahmen einer Serie bitte im ursprünglichen Kalender bearbeiten.')
                result = self.create_event(payload, original=original, resource=resource)
                with self.lock:
                    path = self._cache_path() if original.get('account') else local_path
                    data = self.storage.read_json(path, default={} if original.get('account') else [])
                    entries = data.get('events', []) if original.get('account') else data
                    entries[:] = [e for e in entries if not (e.get('key') == original['key']
                                 and e.get('account') == original.get('account') and e != result)]
                    self.storage.write_json(path, data)
                old_id, new_id = self._task_identity(original), self._task_identity(result)
                if old_id != new_id:
                    with self.lock:
                        plan_path = self.storage.path('task-plans.json')
                        plans = self.storage.read_json(plan_path, default={})
                        if old_id in plans:
                            plans[new_id] = plans.pop(old_id)
                            self.storage.write_json(plan_path, plans)
                return result
            except InvalidInput:
                raise
            except Exception as error:
                logger.warning('Kalender-Bearbeiten: Fehlertyp=%s', type(error).__name__)
                raise InvalidInput('Eintrag konnte nicht geändert werden. ' + _sync_error(error)[0]) from None
            finally:
                if client is not None and hasattr(client, 'close'):
                    try:
                        client.close()
                    except Exception:
                        pass

    @staticmethod
    def _calendar_identity(entry):
        import json
        return json.dumps([entry.get('account', ''), entry.get('calendar', '')], ensure_ascii=False)

    def _visibility(self):
        return self.storage.read_json(self.storage.path('visibility.json'), default={'entries': {}, 'calendars': {}})

    def _is_hidden(self, entry, visibility, *, apply_selection=True):
        field = 'selectedTodoCalendars' if entry.get('kind') == 'todo' else 'selectedEventCalendars'
        selected = self.settings().get(field)
        if apply_selection and selected is not None and {'account': entry.get('account', ''),
                                     'name': entry.get('calendar', '')} not in selected:
            return True
        return (self._task_identity(entry) in visibility['entries']
                or self._calendar_identity(entry) in visibility['calendars'])

    def visibility_payload(self):
        with self.lock:
            visibility = self._visibility()
            cache = self.storage.read_json(self._cache_path(), default={})
            entries = list(cache.get('events', []))
            entries.extend(self.storage.read_json(self.storage.path('local-events.json'), default=[]))
            calendars = {self._calendar_identity(e): e for e in entries}
            for calendar in self.status().get('calendars', []):
                entry = {'account': calendar['account'], 'calendar': calendar['name']}
                calendars[self._calendar_identity(entry)] = entry
            return {'hiddenEntries': visibility['entries'], 'calendars': [
                {'id': key, 'label': ' · '.join(filter(None, [e.get('account'), e.get('calendar')])),
                 'hidden': key in visibility['calendars']} for key, e in calendars.items()],
                'hiddenCalendars': visibility['calendars']}

    def update_visibility(self, payload):
        if (not isinstance(payload, dict) or payload.get('scope') not in ('entries', 'calendars')
                or not isinstance(payload.get('id'), str) or not payload['id']
                or not isinstance(payload.get('hidden'), bool)
                or not isinstance(payload.get('label', ''), str)):
            raise InvalidInput('Ungültige Sichtbarkeitseinstellung.')
        with self.lock:
            visibility = self._visibility()
            values = visibility[payload['scope']]
            if payload['hidden']:
                values[payload['id']] = payload.get('label') or payload['id']
            else:
                values.pop(payload['id'], None)
            self.storage.write_json(self.storage.path('visibility.json'), visibility)
        return {'ok': True}

    def tasks(self):
        with self.lock:
            cache = self.storage.read_json(self._cache_path(), default={})
            entries = list(cache.get('events', []))
            entries.extend(self.storage.read_json(self.storage.path('local-events.json'), default=[]))
            plans = self.storage.read_json(self.storage.path('task-plans.json'), default={})
            completed = self.storage.read_json(self.storage.path('completed-tasks.json'), default={})
        visibility = self._visibility()
        tasks = []
        for entry in entries:
            if self._is_hidden(entry, visibility):
                continue
            if entry.get('kind') != 'todo' or entry.get('status') in ('COMPLETED', 'CANCELLED'):
                continue
            identity = self._task_identity(entry)
            if identity in completed:
                continue
            tasks.append({**entry, 'id': identity, **plans.get(identity, {})})
        day = datetime.now(_zone(self.settings()['timezone'])).date().isoformat()
        return {'tasks': tasks, 'completedTasks': [task for task in completed.values()
                if task.get('completedDate') == day and not self._is_hidden(task, visibility)]}

    @staticmethod
    def _task_identity(entry):
        # Datum und Titel dürfen sich auf dem Server ändern, die Zuordnung bleibt.
        import json
        return json.dumps([entry.get('account', ''), entry.get('calendar', ''),
                           entry.get('uid') or entry['key']], ensure_ascii=False)

    def update_task(self, payload):
        if not isinstance(payload, dict):
            raise InvalidInput('Ungültige Aufgabe.')
        with self._sync_lock:
            task = next((task for task in self.tasks()['tasks'] if task['id'] == payload.get('id')), None)
            if task is None:
                raise InvalidInput('Die Aufgabe ist nicht mehr verfügbar. Bitte aktualisieren.')
            action = payload.get('action')
            if action == 'plan':
                planned = payload.get('plannedDate', '')
                try:
                    if not isinstance(planned, str):
                        raise ValueError()
                    if planned:
                        date.fromisoformat(planned)
                except (TypeError, ValueError):
                    raise InvalidInput('Bitte ein gültiges Planungsdatum angeben.') from None
                with self.lock:
                    path = self.storage.path('task-plans.json')
                    plans = self.storage.read_json(path, default={})
                    plans[task['id']] = {'plannedDate': planned}
                    self.storage.write_json(path, plans)
                return {'ok': True}
            if action != 'complete':
                raise InvalidInput('Ungültige Aufgabenaktion.')
            if task.get('account'):
                account = next((a for a in self.settings()['accounts'] if a['label'] == task['account']), None)
                if account is None:
                    raise InvalidInput('Das Konto ist nicht mehr verfügbar.')
                client = None
                try:
                    self._validate_accounts([account])
                    client = self.client_factory(account)
                    calendar = next(c for c in client.principal().calendars()
                                    if str(getattr(c, 'name', None) or c.id) == task['calendar'])
                    resource = next(r for r in calendar.todos(include_completed=False)
                                    if any(str(c.get('uid', '')) == task['uid']
                                           for c in r.icalendar_instance.walk('VTODO')))
                    # Serientermine: complete() ohne handle_rrule beendet die ganze
                    # Serie. Mit handle_rrule=True legt caldav die nächste Wiederholung an.
                    if task.get('recurring'):
                        try:
                            resource.complete(handle_rrule=True)
                        except TypeError:
                            raise InvalidInput('Wiederkehrende Aufgaben können mit dieser caldav-Version nicht abgeschlossen werden. Bitte im ursprünglichen Kalender erledigen.') from None
                    else:
                        resource.complete()
                except Exception as error:
                    logger.warning('TODO-Abschluss: Fehlertyp=%s', type(error).__name__)
                    raise InvalidInput('Aufgabe konnte nicht abgeschlossen werden. ' + _sync_error(error)[0]) from None
                finally:
                    if client is not None and hasattr(client, 'close'):
                        try:
                            client.close()
                        except Exception:
                            pass
            with self.lock:
                path = self._cache_path() if task.get('account') else self.storage.path('local-events.json')
                data = self.storage.read_json(path, default={} if task.get('account') else [])
                entries = data.get('events', []) if task.get('account') else data
                for entry in entries:
                    if self._task_identity(entry) == task['id']:
                        entry['status'] = 'COMPLETED'
                self.storage.write_json(path, data)
                completed_path = self.storage.path('completed-tasks.json')
                completed = self.storage.read_json(completed_path, default={})
                completed[task['id']] = {**task, 'status': 'COMPLETED',
                    'completedDate': datetime.now(_zone(self.settings()['timezone'])).date().isoformat()}
                self.storage.write_json(completed_path, completed)
            return {'ok': True}

    def group_defaults(self):
        return self.storage.read_json(self.storage.path('unit-groups.json'), default=[
            {'year': '2026/2027', 'grade': '05', 'group': '05C'},
            {'year': '2026/2027', 'grade': '10', 'group': '10C'},
        ])

    def save_group_defaults(self, rows):
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not re.fullmatch(r'\d{4}/\d{4}', str(row.get('year', '')))
            or not re.fullmatch(r'\d{2}', str(row.get('grade', '')))
            or not isinstance(row.get('group'), str) or not row['group'].strip() for row in rows
        ):
            raise InvalidInput('Bitte Schuljahr, Klassenstufe und Lerngruppe ausfüllen.')
        self.storage.write_json(self.storage.path('unit-groups.json'), rows)
        return {'rows': rows}

    def link_units(self, events):
        units = self.ctx.units.scheduled()
        defaults = self.group_defaults()
        def group_key(value):
            return re.sub(r'^0+(?=[1-9])', '', value.upper().replace(' ', ''))
        subjects = {'mathematik': 'MA', 'informatik': 'IN', 'deutsch': 'DE', 'englisch': 'EN'}
        for event in events:
            if event.get('planningMarker'):
                continue
            # Oberstufe: Halbjahreskurse heissen Q1 bis Q4 (Q1/Q2 = Klasse 12, Q3/Q4 = Klasse 13).
            match = re.search(r'(?<![A-Z0-9])(Q[1-4]|0?[1-9]|1[0-3])([A-Z]?)\s+([A-Z]{2,3})(?![A-Z])', event['title'].upper())
            if not match:
                continue
            grade, suffix, subject = match.groups()
            course = ''
            if grade.startswith('Q'):
                course = grade
                grade = '12' if grade in ('Q1', 'Q2') else '13'
                suffix = ''
            grade = grade.zfill(2)
            year, month = map(int, event['startDate'][:7].split('-'))
            first = year if month >= 8 else year - 1
            school_year = f'{first}/{first + 1}'
            default = next((row['group'] for row in defaults if row['year'] == school_year and row['grade'] == grade), '')
            group = course or (grade + suffix if suffix else default.upper())
            # Mathekompensation gehört zum Mathematikkurs derselben Lerngruppe.
            if subject == 'MK':
                subject = 'MA'
            event['teaching'] = {'klasse': f'klasse-{grade}', 'lerngruppe': group,
                                 'fach': next((name for name, code in subjects.items() if code == subject), '')}
            linked = []
            for unit in units:
                if unit['klasse'] != f'klasse-{grade}' or subjects.get(unit['fach']) != subject:
                    continue
                for use in unit['data'].get('einsatz', []):
                    # Ohne explizite Gruppe oder Schuljahresvorgabe gilt der
                    # Einsatz fuer die passende Unterrichtsstunde der Klasse.
                    target = (use.get('lerngruppe') or default or group).upper().replace(' ', '')
                    if use['datum'] == event['startDate'] and group and group_key(target) == group_key(group):
                        # `material` ist der Pfad relativ zum Einheitenordner (leer: ganze Einheit);
                        # mehrere Einsätze derselben Einheit am Tag werden gesammelt.
                        entry = next((item for item in linked if item['path'] == unit['path']), None)
                        if entry is None:
                            linked.append({'path': unit['path'], 'title': unit['data']['titel'],
                                           'materials': [use['material']] if use.get('material') else []})
                        elif use.get('material') and use['material'] not in entry['materials']:
                            entry['materials'].append(use['material'])
            event['units'] = linked

    def events(self, start: str, end: str) -> dict[str, Any]:
        settings = self.settings()
        zone = _zone(settings["timezone"])
        begin, finish = _normalise_dates(start, end, zone)
        cache = self.storage.read_json(self._cache_path(), default={})
        entries = list(cache.get("events") or []) if isinstance(cache, dict) else []
        entries.extend(self.storage.read_json(self.storage.path('local-events.json'), default=[]))
        matches = []
        for event in entries or []:
            if not event.get("startDate") or event.get("status") == "COMPLETED":
                continue
            start_date = date.fromisoformat(event["startDate"])
            end_date = date.fromisoformat(event.get("endDate") or event["startDate"])
            if start_date <= finish and end_date >= begin:
                matches.append(event)
        source_errors = []
        # Pluginquellen sind nicht Teil der CalDAV-Kalenderauswahl. Explizite
        # Ausblendungen gelten weiterhin auch für ihre Termine.
        source_entries = set()
        for source_id, source_name, provider in self._calendar_sources():
            try:
                source_events = _validate_source_events(provider(start, end), zone)
            except Exception:
                source_errors.append({
                    "source": source_id, "name": source_name,
                    "message": "Termine konnten nicht geladen werden. Bitte die Kalenderquelle prüfen.",
                })
                continue
            source_entries.update(id(event) for event in source_events)
            matches.extend(source_events)
        visibility = self._visibility()
        holiday = settings.get("holidayCalendar") or {}
        holiday_key = self._calendar_identity({"account": holiday.get("account", ""), "calendar": holiday.get("name", "")})
        matches = [{**e, 'visibilityId': self._task_identity(e),
                    'holiday': self._calendar_identity(e) == holiday_key} for e in matches
                   if not self._is_hidden(e, visibility, apply_selection=id(e) not in source_entries)]
        self.link_units(matches)
        cancellations = self.storage.read_json(self.storage.path('lesson-cancellations.json'), default={})
        for event in matches:
            event['lessonId'] = self._task_identity(event) + '|' + str(event.get('start') or event['startDate'])
            event['cancelled'] = cancellations.get(event['lessonId'], False) is True
        matches.sort(key=lambda event: _event_sort_key(event, zone))
        return {"events": matches, "window": (cache or {}).get("window"), "sourceErrors": source_errors,
                "holidayCalendar": holiday or None}

    def lessons(self, day: str) -> dict[str, Any]:
        """Zeitige Quelltermine eines Tages (z. B. Stundenplan): die wählbaren
        Unterrichtsstunden für den Fälligkeitstag eines TODOs."""
        zone = _zone(self.settings()["timezone"])
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise InvalidInput("date erwartet ein Datum im Format JJJJ-MM-TT.")
        try:
            date.fromisoformat(day)
        except ValueError:
            raise InvalidInput("date erwartet ein Datum im Format JJJJ-MM-TT.") from None
        lessons = []
        source_errors = []
        for source_id, source_name, provider in self._calendar_sources():
            try:
                source_events = _validate_source_events(provider(day, day), zone)
            except Exception:
                source_errors.append({
                    "source": source_id, "name": source_name,
                    "message": "Unterrichtsstunden konnten nicht geladen werden. Bitte die Kalenderquelle prüfen.",
                })
                continue
            for event in source_events:
                if event["allDay"] or event["startDate"] != day:
                    continue
                lessons.append({"id": event["start"], "key": event["key"], "title": event["title"],
                                "start": event["start"], "end": event["end"], "location": event["location"],
                                "calendar": event["calendar"], "source": source_name})
        lessons.sort(key=lambda lesson: datetime.fromisoformat(lesson["start"]))
        return {"date": day, "lessons": lessons, "sourceErrors": source_errors}

    def cancel_lesson(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get('cancelled'), bool):
            raise InvalidInput('Ausfallmarkierung fehlt.')
        day = payload.get('datum', '')
        events = self.events(day, day)['events']
        event = next((event for event in events if event.get('lessonId') == payload.get('id')
                      and event.get('teaching')), None)
        if event is None:
            raise InvalidInput('Unterrichtstermin nicht mehr verfügbar. Bitte aktualisieren.')
        with self.lock:
            path = self.storage.path('lesson-cancellations.json')
            values = self.storage.read_json(path, default={})
            if payload['cancelled']:
                values[event['lessonId']] = True
            else:
                values.pop(event['lessonId'], None)
            self.storage.write_json(path, values)
        return {'cancelled': payload['cancelled']}

    def planning_markers(self):
        return {'rows': self.storage.read_json(self.storage.path('planning-markers.json'), default=[])}

    def planning_marker_events(self, start, end):
        # One persisted record backs both the divider and its calendar event.
        # Existing dividers therefore appear automatically, without duplicate copies.
        begin, finish = _normalise_dates(start, end, _zone(self.settings()['timezone']))
        return [
            {'key': f"planning-marker:{marker['id']}", 'uid': f"planning-marker:{marker['id']}",
             'title': marker['titel'], 'start': marker['datum'], 'end': marker['datum'],
             'startDate': marker['datum'], 'endDate': marker['datum'], 'allDay': True,
             'calendar': 'Unterrichtsplanung', 'account': '', 'kind': 'event',
             'location': '', 'url': '', 'color': marker['farbe'], 'planningMarker': marker['id'],
             'description': 'Trenner der Unterrichtsplanung. Bearbeiten unter Unterrichtseinheiten.'
                            + (f" Klasse {marker['klasse'].replace('klasse-', '')}." if marker['klasse'] else '')}
            for marker in self.planning_markers()['rows']
            if begin.isoformat() <= marker['datum'] <= finish.isoformat()
        ]

    def save_planning_marker(self, payload):
        if not isinstance(payload, dict):
            raise InvalidInput('Angaben zum Trenner fehlen.')
        deleting = payload.get('delete') is True
        if not deleting:
            title, day, color, grade = (payload.get(key, '') for key in ('titel', 'datum', 'farbe', 'klasse'))
            if not isinstance(title, str) or not title.strip() or len(title) > 120:
                raise InvalidInput('Bitte einen Titel mit höchstens 120 Zeichen angeben.')
            if not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
                raise InvalidInput('Bitte ein gültiges Datum angeben.')
            try:
                date.fromisoformat(day)
            except ValueError:
                raise InvalidInput('Bitte ein gültiges Datum angeben.') from None
            if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                raise InvalidInput('Bitte eine gültige Farbe wählen.')
            if not isinstance(grade, str) or (grade and not re.fullmatch(r'klasse-(0[1-9]|1[0-3])', grade)):
                raise InvalidInput('Ungültige Klasse.')
        with self.lock:
            rows = self.planning_markers()['rows']
            original = next((row for row in rows if row['id'] == payload.get('id')), None)
            if payload.get('id') and (original is None or original['revision'] != payload.get('revision')):
                raise InvalidInput('Der Trenner wurde inzwischen geändert. Bitte neu öffnen.')
            if deleting and original is None:
                raise InvalidInput('Trenner nicht gefunden.')
            if original:
                rows.remove(original)
            if not deleting:
                marker = {'id': original['id'] if original else str(uuid4()), 'revision': str(uuid4()),
                          'titel': title.strip(), 'datum': day, 'farbe': color.lower(), 'klasse': grade}
                rows.append(marker)
            self.storage.write_json(self.storage.path('planning-markers.json'), rows)
        return {'deleted': True} if deleting else marker

    def holidays(self, start: str, end: str) -> dict[str, Any]:
        """Ganztägige Termine des gewählten Ferienkalenders im Zeitraum."""
        settings = self.settings()
        zone = _zone(settings["timezone"])
        begin, finish = _normalise_dates(start, end, zone)
        holiday = settings.get("holidayCalendar") or {}
        cache = self.storage.read_json(self._cache_path(), default={})
        entries = list(cache.get("events") or []) if isinstance(cache, dict) else []
        entries.extend(self.storage.read_json(self.storage.path('local-events.json'), default=[]))
        holiday_key = self._calendar_identity({"account": holiday.get("account", ""), "calendar": holiday.get("name", "")})
        # Enddatum ganztägiger Ferien ist inklusiv im Event; auf Tage ausdehnen.
        expanded: set[str] = set()
        for e in entries:
            selected = self._calendar_identity(e) == holiday_key if holiday.get('name') else bool(
                re.search(r'ferien|feiertage', e.get('calendar', ''), re.IGNORECASE))
            if not selected or not e.get("allDay") or not e.get("startDate"):
                continue
            first = date.fromisoformat(e["startDate"])
            last = date.fromisoformat(e.get("endDate") or e["startDate"])
            if last < begin or first > finish:
                continue
            current = max(first, begin)
            while current <= min(last, finish):
                expanded.add(current.isoformat())
                current += timedelta(days=1)
        return {"days": sorted(expanded), "calendar": holiday or None, "automatic": not bool(holiday.get("name"))}

    def discover_calendars(self) -> dict[str, Any]:
        result = {"calendars": [], "errors": []}
        for account in self.settings().get("accounts", []):
            client = None
            try:
                self._validate_accounts([account])
                client = self.client_factory(account)
                for calendar in client.principal().calendars():
                    name = str(getattr(calendar, "name", None) or calendar.id)
                    if account.get("calendars") and name not in account["calendars"]:
                        continue
                    result["calendars"].append({"account": account["label"], "name": name,
                                                "components": self._supported_components(calendar)})
            except Exception:
                result["errors"].append("Kalender konnten nicht geladen werden. Bitte Verbindung und Zugangsdaten prüfen.")
            finally:
                if client is not None and hasattr(client, "close"):
                    client.close()
        return result

    # -------------------------------------------------------------- Intervall

    def start_interval_worker(self, runtime, interval_minutes: int) -> None:
        """Hintergrundabgleich im Intervall; der Takt bleibt kurz, damit der
        geordnete Shutdown (runtime.close) nicht auf den vollen Intervall-Turnus warten muss."""
        if self._interval_worker is not None:
            return

        def loop():
            initial_due = self.clock()
            cooldown = 0
            wait_seconds = 0
            while not runtime.closing.wait(wait_seconds):
                wait_seconds = 5
                settings = self.settings()
                interval = settings["syncIntervalMinutes"]
                if not interval or not settings.get("accounts"):
                    continue
                status = self.storage.read_json(self._status_path(), default={})
                due = max(status.get("nextSync") or initial_due, cooldown)
                if self.clock() < due:
                    continue
                initial_due = self.clock() + interval * 60
                try:
                    self.sync_now(retry_only=bool(status.get("retryPending")))
                except Exception as error:
                    cooldown = self.clock() + interval * 60
                    logger.error("Kalender-Hintergrundabgleich fehlgeschlagen: %s", type(error).__name__)


        runtime.start_worker(loop, ())
        self._interval_worker = loop
