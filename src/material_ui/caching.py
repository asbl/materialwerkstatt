from __future__ import annotations

import threading
import time
from typing import Callable


class TTLCache:
    """Zeitbegrenzter Cache mit Invalidate; die Berechnung laeuft unter dem eigenen Lock."""

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self.lock = threading.Lock()
        self.expires = 0.0
        self.value = None

    def get(self, build: Callable[[], object]):
        now = time.time()
        with self.lock:
            if self.value is not None and self.expires > now:
                return self.value
            self.value = build()
            self.expires = now + self.ttl
            return self.value

    def invalidate(self) -> None:
        with self.lock:
            self.expires = 0.0
