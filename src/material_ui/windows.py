from __future__ import annotations

import threading
import time


class WindowRegistry:
    """Verfolgt lebende App-Fenster und reicht Datei-Öffnungswünsche weiter.

    Jedes offene Fenster meldet sich regelmäßig per Herzschlag; ohne Meldung
    innerhalb des Zeitfensters gilt es als beendet. Öffnungswünsche des
    Starters landen in einer Warteschlange und werden vom nächsten Herzschlag
    eines Fensters abgeholt.
    """

    def __init__(self, timeout: float = 12.0) -> None:
        self.lock = threading.Lock()
        self.timeout = timeout
        self.seen: dict[str, float] = {}
        self.requests: list[dict] = []
        self._next_id = 0

    def heartbeat(self, session: str) -> list[dict]:
        now = time.monotonic()
        with self.lock:
            self.seen[session] = now
            self._expire(now)
            requests = self.requests
            self.requests = []
            return requests

    def close(self, session: str) -> None:
        with self.lock:
            self.seen.pop(session, None)

    def count(self) -> int:
        now = time.monotonic()
        with self.lock:
            self._expire(now)
            return len(self.seen)

    def enqueue(self, payload: dict) -> int:
        with self.lock:
            self._next_id += 1
            self.requests.append({"id": self._next_id, **payload})
            return self._next_id

    def claimed(self, identifier: int) -> bool:
        with self.lock:
            return not any(request["id"] == identifier for request in self.requests)

    def discard(self, identifier: int) -> None:
        with self.lock:
            self.requests = [request for request in self.requests if request["id"] != identifier]

    def _expire(self, now: float) -> None:
        deadline = now - self.timeout
        for session, seen in list(self.seen.items()):
            if seen < deadline:
                del self.seen[session]
