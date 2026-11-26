"""Zusätzliche Index-Einträge von Plugins (z. B. Kurse) im Dokumentenindex.

Der Kern kennt keine konkreten Eintragarten; Plugins registrieren einen Provider
(und optional einen Invalidator). `DocumentService.all_entries()` hängt die
Provider-Ergebnisse an die QMD-Einträge an.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


class IndexExtras:
    def __init__(self) -> None:
        self._providers: list[Callable[[], list[dict[str, Any]]]] = []
        self._invalidators: list[Callable[[], None]] = []
        self._lock = threading.RLock()

    def register(self, provider: Callable[[], list[dict[str, Any]]],
                 invalidator: Callable[[], None] | None = None) -> Callable[[], None]:
        if not callable(provider):
            raise TypeError("Index-Provider muss aufrufbar sein.")
        with self._lock:
            self._providers.append(provider)
            if invalidator is not None:
                self._invalidators.append(invalidator)
            providers, invalidators = list(self._providers), list(self._invalidators)

        def unregister() -> None:
            with self._lock:
                if provider in self._providers:
                    self._providers.remove(provider)
                if invalidator is not None and invalidator in self._invalidators:
                    self._invalidators.remove(invalidator)

        _ = providers, invalidators
        return unregister

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            providers = list(self._providers)
        result: list[dict[str, Any]] = []
        for provider in providers:
            try:
                result.extend(provider() or [])
            except Exception:
                # Ein kaputter Provider darf den Index nicht brechen, aber sichtbar sein.
                logger.warning("Index-Provider lieferte keine Einträge: %s", type(provider).__name__, exc_info=True)
        return result

    def invalidate(self) -> None:
        with self._lock:
            invalidators = list(self._invalidators)
        for invalidator in invalidators:
            try:
                invalidator()
            except Exception:
                logger.warning("Index-Invalidator fehlgeschlagen: %s", type(invalidator).__name__, exc_info=True)
