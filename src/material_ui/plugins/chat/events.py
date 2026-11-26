"""Gemeinsames Ereignisformat aller Chat-Provider, 1:1 auf SSE gemappt."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

EVENT_TYPES = {"text", "tool_call", "tool_result", "done", "error"}


@dataclass(frozen=True)
class ChatEvent:
    type: str
    text: str | None = None
    tool: str | None = None
    tool_input: Any = None
    tool_output: Any = None
    session_id: str | None = None
    message: str | None = None
    # tool_result: True, wenn das Werkzeug fehlgeschlagen ist (None = unbekannt).
    is_error: bool | None = None
    # error: maschinenlesbare Ursache, z. B. "session_unknown" (Sitzung abgelaufen).
    code: str | None = None

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"Unbekannter Ereignistyp: {self.type}")

    def to_sse(self) -> str:
        payload = {key: value for key, value in asdict(self).items() if value is not None}
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def text_event(text: str) -> ChatEvent:
    return ChatEvent(type="text", text=text)


def tool_call_event(tool: str, tool_input: Any) -> ChatEvent:
    return ChatEvent(type="tool_call", tool=tool, tool_input=tool_input)


def tool_result_event(tool: str, tool_output: Any, is_error: bool | None = None) -> ChatEvent:
    return ChatEvent(type="tool_result", tool=tool, tool_output=tool_output, is_error=is_error)


def done_event(session_id: str | None = None) -> ChatEvent:
    return ChatEvent(type="done", session_id=session_id)


def error_event(message: str, code: str | None = None) -> ChatEvent:
    return ChatEvent(type="error", message=message, code=code)
