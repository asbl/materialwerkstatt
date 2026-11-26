"""Synchronous change notifications, owned by one application runtime."""
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class MaterialChange:
    kind: str
    paths: tuple[Path, ...] = ()


class MaterialChanges:
    def __init__(self):
        self._lock = threading.RLock()
        self._listeners: list[Callable[[MaterialChange], None]] = []

    def subscribe(self, listener):
        with self._lock:
            self._listeners.append(listener)
        def unsubscribe():
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)
        return unsubscribe

    def publish(self, change: MaterialChange):
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(change)
            except Exception:
                logging.getLogger(__name__).exception("Material change listener failed (%s)", change.kind)
