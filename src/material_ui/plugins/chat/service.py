"""Sitzungsverwaltung fuer das Chat-Panel: waehlt den Provider, haelt Sitzungen in-memory.

Die App laeuft lokal fuer einen Nutzer (siehe ``desktop.py``), daher reicht ein
einfaches In-Memory-Dict ohne Persistenz ueber Neustarts hinweg. Sitzungen, die
laenger ungenutzt sind (z. B. Tab geschlossen ohne "Neuer Chat"), werden nach
``IDLE_SESSION_SECONDS`` geschlossen.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

from .events import ChatEvent, error_event
from .providers import ChatProvider, ClaudeCliProvider, CodexCliProvider, VibeCliProvider
from material_ui.config import AppConfig
from material_ui.errors import InvalidInput

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
MAX_CONCURRENT_CHAT_PROCESSES = 4
IDLE_SESSION_SECONDS = 3600.0


@dataclass
class _Entry:
    provider: ChatProvider
    session: Any
    turn_lock: threading.Lock = field(default_factory=threading.Lock)
    last_used: float = 0.0
    # Serverseitiger Zustand je Sitzung, z. B. welches Dokument der Provider schon kennt.
    state: dict[str, Any] = field(default_factory=dict)


class ChatService:
    def __init__(
        self,
        config: AppConfig,
        providers: Iterable[ChatProvider] | None = None,
        idle_seconds: float = IDLE_SESSION_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._base_url_value = DEFAULT_BASE_URL
        self._idle_seconds = idle_seconds
        self._clock = clock
        if providers is None:
            providers = (
                ClaudeCliProvider(config, self._base_url),
                CodexCliProvider(config, self._base_url),
                VibeCliProvider(config, self._base_url),
            )
        self._providers: dict[str, ChatProvider] = {provider.name: provider for provider in providers}
        self._sessions: dict[str, _Entry] = {}
        self._sessions_lock = threading.Lock()
        # Chat-Subprozesse laufen ausserhalb von ProcessRunner (anderes Streaming-Modell als
        # dessen log-Datei-basierte ManagedProcess); dieses Semaphore gibt ihnen trotzdem eine
        # obere Grenze, analog zu ProcessRunner.max_processes fuer Render/Build/Preview.
        self._process_slots = threading.BoundedSemaphore(MAX_CONCURRENT_CHAT_PROCESSES)

    def _base_url(self) -> str:
        return self._base_url_value

    def set_base_url(self, url: str) -> None:
        self._base_url_value = url.rstrip("/")

    def providers_status(self) -> list[dict[str, Any]]:
        self.sweep()
        status = []
        for provider in self._providers.values():
            available = provider.available()
            models = getattr(provider, "models", None)
            efforts = getattr(provider, "efforts", None)
            status.append({
                "id": provider.name,
                "available": available,
                "blocked": self._restriction(provider),
                "experimental": provider.experimental,
                "models": models() if callable(models) else [],
                "efforts": efforts() if callable(efforts) else [],
                "default_effort": provider.default_effort() if callable(getattr(provider, "default_effort", None)) else None,
                "usage_hint": provider.usage_hint() if available else None,
            })
        return status

    @staticmethod
    def _restriction(provider: ChatProvider) -> str | None:
        check = getattr(provider, "restriction", None)
        return check() if callable(check) else None

    def sweep(self) -> int:
        """Schliesst Sitzungen ohne laufende Antwort, die laenger als ``idle_seconds`` ungenutzt sind."""
        now = self._clock()
        with self._sessions_lock:
            expired = [
                session_id for session_id, entry in self._sessions.items()
                if now - entry.last_used > self._idle_seconds and not entry.turn_lock.locked()
            ]
            entries = [self._sessions.pop(session_id) for session_id in expired]
        for entry in entries:
            entry.provider.close_session(entry.session)
        return len(entries)

    def create_session(self, provider_id: str, model: str | None = None, effort: str | None = None) -> str:
        self.sweep()
        provider = self._providers.get(provider_id)
        if provider is None:
            raise InvalidInput(f"Unbekannter Provider: {provider_id}")
        if not provider.available():
            raise InvalidInput(f"Provider nicht verfügbar: {provider_id}")
        blocked = self._restriction(provider)
        if blocked:
            raise InvalidInput(blocked)
        checker = getattr(provider, "check_model", None)
        if model and not callable(checker):
            raise InvalidInput(f"Dieser Provider unterstützt keine Modellwahl: {provider_id}")
        chosen = checker(model) if callable(checker) else None
        effort_checker = getattr(provider, "check_effort", None)
        if effort and not callable(effort_checker):
            raise InvalidInput(f"Dieser Provider unterstützt keine Aufwandswahl: {provider_id}")
        chosen_effort = effort_checker(effort) if callable(effort_checker) else None
        session = provider.create_session()
        if chosen:
            session.model = chosen
        if chosen_effort:
            session.effort = chosen_effort
        session_id = str(uuid.uuid4())
        with self._sessions_lock:
            self._sessions[session_id] = _Entry(provider, session, last_used=self._clock())
        return session_id

    def _entry(self, session_id: str) -> _Entry | None:
        with self._sessions_lock:
            return self._sessions.get(session_id)

    def session_state(self, session_id: str) -> dict[str, Any] | None:
        entry = self._entry(session_id)
        return entry.state if entry else None

    def send_message(self, session_id: str, text: str) -> Iterator[ChatEvent]:
        self.sweep()
        entry = self._entry(session_id)
        if entry is None:
            yield error_event("Unbekannte Chat-Sitzung.", code="session_unknown")
            return
        if not entry.turn_lock.acquire(blocking=False):
            yield error_event("Es läuft bereits eine Antwort für diese Sitzung.")
            return
        try:
            if not self._process_slots.acquire(blocking=False):
                yield error_event("Zu viele gleichzeitige Chat-Anfragen. Bitte kurz warten.")
                return
            try:
                entry.last_used = self._clock()
                yield from entry.provider.send(entry.session, text)
            finally:
                entry.last_used = self._clock()
                self._process_slots.release()
        finally:
            entry.turn_lock.release()

    def cancel_turn(self, session_id: str) -> bool:
        """Bricht die laufende Antwort ab, die Sitzung (und ihr Verlauf) bleibt bestehen."""
        entry = self._entry(session_id)
        if entry is None:
            return False
        cancel = getattr(entry.provider, "cancel_turn", None)
        if callable(cancel):
            cancel(entry.session)
        return True

    def close_session(self, session_id: str) -> None:
        with self._sessions_lock:
            entry = self._sessions.pop(session_id, None)
        if entry is not None:
            entry.provider.close_session(entry.session)

    def close(self) -> None:
        with self._sessions_lock:
            entries = list(self._sessions.values())
            self._sessions.clear()
        for entry in entries:
            entry.provider.close_session(entry.session)
