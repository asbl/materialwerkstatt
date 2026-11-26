from __future__ import annotations

import threading
from typing import Any, Callable


class CalendarInterface:
    """Das Interface `@calendar`: Andere Plugins liefern damit Termine in Kalender und Agenda
    und lesen Termine/TODOs des Kalenders.

    Plugins deklarieren `"dependsOn": {"@calendar": ">=0.3.0"}` und holen es mit
    `ctx.service("calendar")`; der Paketmanager stellt so sicher, dass das Kalender-Plugin
    vorhanden ist. `provider(from_iso, to_iso)` gibt eine Liste von Terminen zurück.
    `events(from_iso, to_iso)` und `tasks()` liefern die aktuell gecachten Termine und
    offenen TODOs (lesend, inkl. lokaler Einträge) – etwa für Erinnerungen.
    """

    def __init__(self, service: Any = None) -> None:
        self._lock = threading.Lock()
        self._entries: list[tuple[str, str, Callable]] = []
        self._service = service

    def register_source(self, provider: Callable, *, source_id: str = "", name: str = "") -> Callable[[], None]:
        if not callable(provider):
            raise TypeError("Eine Kalenderquelle muss aufrufbar sein.")
        entry = (source_id or getattr(provider, "__qualname__", "quelle"), name or source_id or "Kalenderquelle", provider)
        with self._lock:
            self._entries.append(entry)

        def unregister() -> None:
            with self._lock:
                if entry in self._entries:
                    self._entries.remove(entry)

        return unregister

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def sources(self) -> tuple[tuple[str, str, Callable], ...]:
        with self._lock:
            return tuple(self._entries)

    def events(self, from_iso: str, to_iso: str) -> list[dict[str, Any]]:
        """Gecachte Termine im Fenster (lesend; ohne Remote-Zugriff)."""
        if self._service is None:
            return []
        return self._service.events(from_iso, to_iso)["events"]

    def tasks(self) -> list[dict[str, Any]]:
        """Offene TODOs (lesend; lokale und CalDAV-Cache-Einträge)."""
        if self._service is None:
            return []
        return self._service.tasks()["tasks"]

    def timezone(self) -> str:
        """Zeitzone der Kalender-Einstellungen (Default Europe/Berlin)."""
        if self._service is None:
            return "Europe/Berlin"
        return str(self._service.settings().get("timezone") or "Europe/Berlin")
