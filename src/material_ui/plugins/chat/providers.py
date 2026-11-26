"""Provider-Vertrag fuer das Chat-Panel: Claude-, Codex- und Mistral-Vibe-CLI.

Alle drei Provider laufen ueber die jeweils lokal eingeloggte Abo-CLI als
Subprozess (kein separates API-Key-Billing für den Chat selbst). Jede CLI
bekommt dieselben Such-, Lese- und Vorschlagswerkzeuge
über einen gemeinsamen MCP-Server (``chat/mcp_server.py``),
den sie selbst als eigenen Subprozess startet - das ersetzt eine handgerollte
Tool-Loop pro Provider.

``CliChatProvider`` kapselt die gemeinsame Subprozess-/Watchdog-Logik; die drei
Unterklassen liefern nur noch Kommandozeile, Parsing und Einmal-Setup.
"""

from __future__ import annotations

import collections
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol, runtime_checkable

import httpx

from . import sandbox
from .events import ChatEvent, done_event, error_event, text_event, tool_call_event, tool_result_event
from material_ui.config import AppConfig
from material_ui.errors import InvalidInput

MISTRAL_USAGE_URL = "https://api.mistral.ai/v1/admin/usage"


@runtime_checkable
class ChatProvider(Protocol):
    name: str
    experimental: bool

    def available(self) -> bool:
        """Ob der Provider grundsaetzlich nutzbar ist (CLI installiert und eingeloggt)."""

    def restriction(self) -> str | None:
        """Grund, warum der Provider aus Sicherheitsgruenden gesperrt ist, sonst ``None``."""

    def usage_hint(self) -> dict[str, Any]:
        """Anzeige fuer die Nutzungsleiste: {"kind": "bar", ...} oder {"kind": "link", "message": ...}."""

    def create_session(self) -> Any:
        """Legt eine neue, providerspezifische Sitzung an."""

    def send(self, session: Any, text: str) -> Iterator[ChatEvent]:
        """Sendet eine Nutzernachricht und liefert die Ereignisse der Antwort, zuletzt ein done/error-Ereignis."""

    def close_session(self, session: Any) -> None:
        """Beendet eine Sitzung (z. B. laufenden Subprozess abbrechen)."""


@dataclass
class CliSession:
    resume_token: str | None = None
    process: subprocess.Popen | None = None
    tool_names: dict[str, str] = field(default_factory=dict)
    closed: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    # Vom Nutzer gewaehltes Modell (None = Standard der CLI).
    model: str | None = None
    # Denkaufwand der Sitzung (nur Claude; None = Konfigurationsstandard).
    effort: str | None = None
    # Gesetzt, wenn die laufende Runde ausdruecklich abgebrochen wurde (Sitzung bleibt erhalten).
    cancelled: bool = False


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")


def _format_seconds(value: float) -> str:
    return f"{value:g}"


class _Watchdog:
    """Beendet einen Prozess bei Inaktivitaet (keine Ausgabezeile) oder nach harter Gesamtzeit.

    ``touch()`` setzt die Inaktivitaetsuhr zurueck; eine laufende, noch streamende Antwort wird
    deshalb nicht abgebrochen, solange sie Ausgabe liefert (bis zur harten Obergrenze)."""

    def __init__(self, idle_seconds: float, max_seconds: float, on_expire: Callable[[], None]) -> None:
        self.idle_seconds = idle_seconds
        self.max_seconds = max_seconds
        self.reason: str | None = None
        self._on_expire = on_expire
        self._started = time.monotonic()
        self._last = self._started
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="chat-watchdog", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def touch(self) -> None:
        self._last = time.monotonic()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        interval = max(0.02, min(0.5, self.idle_seconds / 4))
        while not self._stop.wait(interval):
            now = time.monotonic()
            if now - self._started >= self.max_seconds:
                self.reason = "limit"
            elif now - self._last >= self.idle_seconds:
                self.reason = "idle"
            else:
                continue
            self._on_expire()
            return


class CliChatProvider:
    """Gemeinsame Subprozess-Steuerung fuer Claude-, Codex- und Vibe-CLI.

    Unterklassen liefern nur noch ``binary()``, ``_build_command()`` und
    ``_parse_line()``; Popen-Lifecycle, Zeilen-Lesen und Watchdog-Timeout
    sind hier einmal implementiert.
    """

    name: str = ""
    experimental: bool = False
    # True: Die CLI hat eingebaute Datei-/Shell-Werkzeuge, die sich nicht abschalten lassen.
    # Sie laeuft dann nur innerhalb der bubblewrap-Sandbox (``sandbox.py``) oder gar nicht.
    needs_sandbox: bool = False
    sandbox_env_prefixes: tuple[str, ...] = ()
    # Inaktivitaets-Timeout: so lange darf die CLI ohne jede Ausgabezeile bleiben.
    timeout_seconds: float = 120.0
    # Harte Obergrenze fuer eine einzelne Runde, auch wenn dauernd Ausgabe kommt.
    max_seconds: float = 900.0
    # Claude liest den Prompt von stdin (``-p`` ohne Textargument); Codex und Vibe
    # bekommen ihn als CLI-Argument und ueberschreiben dies mit False, damit stdin
    # nur geschlossen (EOF) statt zusaetzlich beschrieben wird.
    send_prompt_via_stdin: bool = True

    def __init__(self, config: AppConfig, base_url: Callable[[], str]) -> None:
        self.config = config
        self._base_url = base_url
        self._prepared = False
        self._prepare_lock = threading.Lock()

    # -- von Unterklassen zu implementieren -------------------------------
    def binary(self) -> str:
        raise NotImplementedError

    def usage_hint(self) -> dict[str, Any]:
        raise NotImplementedError

    def _build_command(self, session: CliSession, text: str) -> list[str]:
        raise NotImplementedError

    def _parse_line(self, line: str, session: CliSession) -> ChatEvent | list[ChatEvent] | None:
        """Eine NDJSON-Zeile in null, ein oder mehrere ChatEvents uebersetzen.

        Eine Liste wird gebraucht, wenn ein CLI-Format Tool-Aufruf und -Ergebnis in
        einem einzigen Eintrag buendelt (Vibe: ein "effect"-Eintrag pro Tool-Call)
        statt wie Claude/Codex als zwei getrennte Zeilen.
        """
        raise NotImplementedError

    def prepare(self) -> None:
        """Einmaliges Setup (MCP-Registrierung, Agent-Profile, ...). Default: nichts zu tun."""
        return None

    # -- gemeinsame Logik --------------------------------------------------
    def available(self) -> bool:
        return shutil.which(self.binary()) is not None

    def create_session(self) -> CliSession:
        return CliSession()

    # -- Modellwahl ----------------------------------------------------------
    def models(self) -> list[dict[str, str]]:
        """Auswaehlbare Modelle (``id``/``label``); leer = der Provider bietet keine Wahl."""
        return []

    def efforts(self) -> list[dict[str, str]]:
        """Auswaehlbare Denkaufwand-Stufen; leer = der Provider bietet keine Wahl."""
        return []

    def default_effort(self) -> str | None:
        return None

    def check_effort(self, effort: str | None) -> str | None:
        if not effort:
            return None
        if effort not in {entry["id"] for entry in self.efforts()}:
            raise InvalidInput(f"Denkaufwand nicht verfügbar für {self.name}: {effort}")
        return effort

    def check_model(self, model: str | None) -> str | None:
        """Prueft eine Modellwahl gegen die Liste und liefert die ID (None = Standard)."""
        if not model:
            return None
        allowed = {entry["id"] for entry in self.models() if entry["id"]}
        if model not in allowed or not MODEL_PATTERN.fullmatch(model):
            raise InvalidInput(f"Modell nicht verfügbar für {self.name}: {model}")
        return model

    def cancel_turn(self, session: CliSession) -> None:
        """Bricht nur die laufende Runde ab; Sitzung und Resume-Token bleiben erhalten."""
        with session.lock:
            process = session.process
            if process is not None and process.poll() is None:
                session.cancelled = True
        self._terminate_process(process)

    # -- Sandbox ------------------------------------------------------------
    def confined(self) -> bool:
        """Ob die CLI in einer Dateisystem-Sandbox laeuft."""
        return self.needs_sandbox and sandbox.sandbox_available()

    def restriction(self) -> str | None:
        if not self.needs_sandbox or self.confined():
            return None
        if getattr(self.config, "chat_allow_unsandboxed", False):
            return None
        return (
            f"{self.name} ist gesperrt: Die CLI hat eingebaute Datei- und Shell-Werkzeuge und darf nur "
            "in einer Dateisystem-Sandbox laufen. Bitte bubblewrap installieren (Paket `bubblewrap`, "
            f"Programm `bwrap`) oder die Sperre bewusst mit {sandbox.ALLOW_UNSANDBOXED_ENV}=1 aufheben."
        )

    def _sandbox_readonly(self) -> list[Path]:
        """Nur lesend eingebundene Pfade ausser dem System: Material, Quellbaum, Python, CLI."""
        root = self.config.root
        # Der Textindex fuer search_wissen liegt im (sonst verborgenen) build/-Ordner.
        paths = [root / "wissen", root / "unterricht", root / "build" / "material-index.json",
                 *sandbox.python_mounts()]
        paths += [Path(entry) for entry in self._mcp_server_env().get("PYTHONPATH", "").split(os.pathsep) if entry]
        paths += self._cli_readonly()
        return [Path(os.path.realpath(path)) for path in paths if path.exists()]

    def _cli_readonly(self) -> list[Path]:
        return []

    def _cli_writable(self) -> list[Path]:
        """Konfigurations-/Anmeldeordner der CLI (Token-Aktualisierung, Sitzungen)."""
        return []

    def _confine(self, command: list[str], env: dict[str, str]) -> list[str]:
        if not self.needs_sandbox or not self.confined():
            return command
        home = Path.home().resolve()
        # Das Binary liegt meist unter ~/.local/bin, das in der Sandbox nicht sichtbar ist;
        # deshalb den aufgeloesten Pfad (Installationsordner ist eingebunden) starten.
        found = shutil.which(command[0])
        if found:
            command = [os.path.realpath(found), *command[1:]]
        return sandbox.build_command(
            command,
            cwd=self.config.root / "wissen",
            home=home,
            readonly=self._sandbox_readonly(),
            writable=[path for path in self._cli_writable() if path.exists()],
            env=sandbox.filter_env(env, self.sandbox_env_prefixes),
        )

    def _ensure_prepared(self) -> None:
        """Fuehrt prepare() genau einmal pro Provider-Instanz aus, nicht bei jeder Nachricht."""
        if self._prepared:
            return
        with self._prepare_lock:
            if self._prepared:
                return
            self.prepare()
            self._prepared = True

    def _terminate_process(self, process: subprocess.Popen | None) -> None:
        """Beendet nur den Subprozess der laufenden Runde, ohne die Sitzung selbst zu schliessen
        (wird auch vom Watchdog aufgerufen - ein Timeout darf kuenftige Nachrichten derselben
        Sitzung nicht blockieren)."""
        if process is not None and process.poll() is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired, ChildProcessError):
                process.wait(timeout=5)

    def close_session(self, session: CliSession) -> None:
        with session.lock:
            session.closed = True
            process = session.process
        self._terminate_process(process)

    def _plugin_dir(self) -> Path:
        return Path(__file__).resolve().parent

    def _mcp_server_env(self) -> dict[str, str]:
        # Der MCP-Server läuft als eigener Subprozess und importiert dieses Plugin als
        # Top-Level-Paket (PYTHONPATH enthält das Plugin-Suchverzeichnis); material_ui
        # und material_suche kommen aus der installierten Umgebung bzw. src/.
        plugins_dir = self._plugin_dir().parent
        src_dir = plugins_dir.parent.parent
        env = dict(os.environ)
        env["MATERIAL_UI_ROOT"] = str(self.config.root)
        env["MATERIAL_UI_BASE_URL"] = self._base_url()
        paths = [str(plugins_dir)]
        if (src_dir / "material_ui").is_dir():
            paths.append(str(src_dir))
        env["PYTHONPATH"] = os.pathsep.join([*paths, env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        return env

    def _mcp_server_command(self) -> list[str]:
        package = self._plugin_dir().name.replace("-", "_")
        return [sys.executable, "-m", f"{package}.mcp_server"]

    def send(self, session: CliSession, text: str) -> Iterator[ChatEvent]:
        reason = self.restriction()
        if reason:
            yield error_event(reason)
            return
        self._ensure_prepared()
        with session.lock:
            if session.closed:
                yield error_event("Sitzung wurde geschlossen.")
                return
        session.cancelled = False
        env = self._mcp_server_env()
        command = self._confine(self._build_command(session, text), env)
        wissen_dir = self.config.root / "wissen"
        try:
            process = subprocess.Popen(
                command,
                cwd=str(wissen_dir),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except OSError as error:
            yield error_event(f"{self.name}-CLI konnte nicht gestartet werden: {error}")
            return
        with session.lock:
            if session.closed:
                # Sitzung wurde waehrend des Starts geschlossen (DELETE-Request lief dazwischen).
                self._terminate_process(process)
                yield error_event("Sitzung wurde geschlossen.")
                return
            session.process = process
        watchdog = _Watchdog(self.timeout_seconds, self.max_seconds, lambda: self._terminate_process(process))
        watchdog.start()
        tail: collections.deque[str] = collections.deque(maxlen=8)
        try:
            if process.stdin is not None:
                with contextlib.suppress(BrokenPipeError):
                    if self.send_prompt_via_stdin:
                        process.stdin.write(text)
                    process.stdin.close()
            assert process.stdout is not None
            saw_done = False
            produced = False
            for raw_line in process.stdout:
                watchdog.touch()
                line = raw_line.strip()
                if not line:
                    continue
                if line[0] not in "{[":
                    # Klartext der CLI (z. B. "Not logged in"): fuer eine spaetere Fehlermeldung merken.
                    tail.append(ANSI_ESCAPE.sub("", line)[:300])
                    continue
                try:
                    result = self._parse_line(line, session)
                except ValueError:
                    tail.append(ANSI_ESCAPE.sub("", line)[:300])
                    continue
                except (KeyError, TypeError, AttributeError):
                    continue
                if result is None:
                    continue
                events = result if isinstance(result, (list, tuple)) else (result,)
                for event in events:
                    yield event
                    if event.type in ("done", "error"):
                        saw_done = True
                    else:
                        produced = True
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
            returncode = process.poll()
            if session.cancelled:
                yield done_event(session.resume_token)
            elif watchdog.reason == "idle":
                yield error_event(f"Keine Antwort seit {_format_seconds(self.timeout_seconds)} s - Anfrage abgebrochen.")
            elif watchdog.reason == "limit":
                yield error_event(f"Zeitlimit von {_format_seconds(self.max_seconds)} s erreicht - Anfrage abgebrochen.")
            elif not saw_done:
                if (returncode not in (0, None)) or (tail and not produced):
                    detail = " | ".join(tail) or "keine Ausgabe"
                    code = f" (Exit {returncode})" if returncode not in (0, None) else ""
                    yield error_event(f"{self.name}-CLI meldet einen Fehler{code}: {detail}")
                else:
                    yield done_event(session.resume_token)
        finally:
            watchdog.stop()
            self._terminate_process(process)


class ClaudeCliProvider(CliChatProvider):
    name = "claude"
    experimental = False
    MCP_TOOLS = "mcp__wissen__search_wissen,mcp__wissen__search_unterricht,mcp__wissen__read_file,mcp__wissen__show_task_image,mcp__wissen__propose_document_edit,mcp__wissen__check_document,mcp__wissen__read_unit,mcp__wissen__list_templates,mcp__wissen__propose_new_document"

    def binary(self) -> str:
        return self.config.claude_bin

    def usage_hint(self) -> dict[str, Any]:
        return {"kind": "link", "message": "Nutzungsstand in der Claude-CLI pruefen: `/usage`."}

    # Anzeigenamen der Aliase (Stand: aktuelle Claude-5-Familie); unbekannte Namen erscheinen unveraendert.
    MODEL_LABELS = {"sonnet": "Sonnet 5.5", "opus": "Opus 5.5", "haiku": "Haiku 5.5", "fable": "Fable 5.2"}

    def models(self) -> list[dict[str, str]]:
        """Das erste konfigurierte Modell (Sonnet) ist der Standard; es gibt keinen unbenannten Eintrag."""
        configured = list(getattr(self.config, "claude_models", ()))
        return [{"id": name, "label": self.MODEL_LABELS.get(name, name)} for name in configured]

    EFFORT_LABELS = {"low": "niedrig", "medium": "mittel", "high": "hoch", "xhigh": "sehr hoch", "max": "maximal"}
    # In der Oberflaeche angebotene Stufen; weitere lassen sich ueber CLAUDE_EFFORT als Standard setzen.
    EFFORT_CHOICES = ("low", "medium", "high")

    def efforts(self) -> list[dict[str, str]]:
        choices = list(self.EFFORT_CHOICES)
        default = self._effort()
        if default and default not in choices:
            choices.append(default)
        return [{"id": name, "label": self.EFFORT_LABELS[name]} for name in choices]

    def default_effort(self) -> str | None:
        return self._effort() or "medium"

    def _effort(self) -> str | None:
        effort = str(getattr(self.config, "claude_effort", "") or "").lower()
        return effort if effort in self.EFFORT_LABELS else None

    def check_model(self, model: str | None) -> str | None:
        if not model:
            configured = list(getattr(self.config, "claude_models", ()))
            return configured[0] if configured else None
        return super().check_model(model)

    def _mcp_config_path(self) -> Path:
        return self.config.root / "build" / ".material-ui" / "chat-mcp-claude.json"

    def prepare(self) -> None:
        """Schreibt die MCP-Config-Datei einmal pro Provider-Instanz statt bei jeder Nachricht."""
        path = self._mcp_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "mcpServers": {
                "wissen": {
                    "command": self._mcp_server_command()[0],
                    "args": self._mcp_server_command()[1:],
                    "env": {"MATERIAL_UI_ROOT": str(self.config.root), "MATERIAL_UI_BASE_URL": self._base_url()},
                }
            }
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _build_command(self, session: CliSession, text: str) -> list[str]:
        token = session.resume_token or str(uuid.uuid4())
        session.resume_token = token
        unterricht_dir = self.config.root / "unterricht"
        command = [
            self.binary(), "-p",
            "--output-format", "stream-json", "--include-partial-messages", "--verbose",
            "--permission-mode", "dontAsk", "--permission-prompts", "none",
            "--allowedTools", self.MCP_TOOLS,
            "--restricted", "--add-dir", str(unterricht_dir),
            "--mcp-config", str(self._mcp_config_path()), "--strict-mcp-config",
            "--tools", self.MCP_TOOLS,
        ]
        if session.model:
            command += ["--model", session.model]
        effort = session.effort or self._effort()
        if effort:
            command += ["--effort", effort]
        if session.process is not None:
            command += ["-r", token]
        else:
            command += ["--session-id", token]
        return command

    def _parse_line(self, line: str, session: CliSession) -> ChatEvent | None:
        data = json.loads(line)
        kind = data.get("type")
        if kind == "stream_event":
            delta = (data.get("event") or {}).get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                return text_event(delta["text"])
            return None
        if kind == "assistant":
            # Text kommt bereits inkrementell ueber stream_event/text_delta; die "assistant"-
            # Zeile liefert denselben Text zusaetzlich als Komplettblock - nur tool_use melden.
            for block in (data.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    name = block.get("name", "?")
                    if block.get("id"):
                        session.tool_names[block["id"]] = name
                    return tool_call_event(name, block.get("input"))
            return None
        if kind == "user":
            for block in (data.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_result":
                    tool_use_id = block.get("tool_use_id", "?")
                    name = session.tool_names.get(tool_use_id, tool_use_id)
                    return tool_result_event(name, block.get("content"), bool(block.get("is_error")) or None)
            return None
        if kind == "result":
            session.resume_token = data.get("session_id") or session.resume_token
            if data.get("is_error"):
                return error_event(str(data.get("result") or "Unbekannter Fehler."))
            return done_event(session.resume_token)
        return None


class CodexCliProvider(CliChatProvider):
    """Codex exec mit JSONL-Ereignissen und MCP-Konfiguration pro Aufruf.

    Die eingebauten Lesewerkzeuge bleiben verfuegbar; ``--sandbox read-only`` verhindert
    nur Aenderungen, nicht das Lesen beliebiger Dateien. Deshalb laeuft Codex zusaetzlich in der
    bubblewrap-Sandbox aus ``sandbox.py`` (ohne ``bwrap`` gesperrt). Editoraenderungen erfolgen
    ueber das MCP-Vorschlagswerkzeug und die Uebernahme in der UI.
    """

    name = "codex"
    experimental = True
    needs_sandbox = True
    sandbox_env_prefixes = ("OPENAI_", "CODEX_")
    send_prompt_via_stdin = True

    def binary(self) -> str:
        return self.config.codex_bin

    def models(self) -> list[dict[str, str]]:
        names = [name for name in (self.config.codex_model, *getattr(self.config, "codex_models", ())) if name]
        unique = list(dict.fromkeys(names))
        return [{"id": "", "label": f"Standard ({self.config.codex_model})" if self.config.codex_model else "Standard"},
                *({"id": name, "label": name} for name in unique)] if len(unique) > 1 else []

    def _cli_readonly(self) -> list[Path]:
        root = sandbox.installation_root(self.binary(), marker="node_modules")
        return [root] if root else []

    def _cli_writable(self) -> list[Path]:
        return [Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")]

    def usage_hint(self) -> dict[str, Any]:
        return {"kind": "link", "message": "Nutzungsstand in der Codex-CLI pruefen: `/status`."}

    def _build_command(self, session: CliSession, text: str) -> list[str]:
        wissen_dir = self.config.root / "wissen"
        server_command = self._mcp_server_command()
        server_env = self._mcp_server_env()
        env_config = ", ".join(
            f"{key} = {json.dumps(server_env[key])}"
            for key in ("MATERIAL_UI_ROOT", "MATERIAL_UI_BASE_URL", "PYTHONPATH")
        )
        mcp_config = (
            f"mcp_servers.wissen={{command = {json.dumps(server_command[0])}, "
            f"args = {json.dumps(server_command[1:])}, env = {{{env_config}}}}}"
        )
        command = [self.binary(), "exec", "--json", "--sandbox", "read-only", "-C", str(wissen_dir),
                   "-c", mcp_config]
        model = session.model or self.config.codex_model
        if model:
            command += ["--model", model]
        if session.resume_token:
            command += ["resume", session.resume_token]
        command.append("-")
        return command

    def _parse_line(self, line: str, session: CliSession) -> ChatEvent | list[ChatEvent] | None:
        data = json.loads(line)
        kind = data.get("type")
        if kind == "thread.started":
            session.resume_token = data.get("thread_id") or session.resume_token
            return None
        if kind in {"item.started", "item.completed"}:
            item = data.get("item") or {}
            item_type = item.get("type")
            if item_type == "mcp_tool_call":
                tool = item.get("tool") or item.get("name", "?")
                if kind == "item.started":
                    arguments = item.get("arguments") or item.get("input") or {}
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    return tool_call_event(tool, arguments)
                if item.get("error"):
                    error = item["error"]
                    message = error.get("message") if isinstance(error, dict) else str(error)
                    return [tool_result_event(tool, item.get("result"), True), error_event(message or "Codex-Werkzeug fehlgeschlagen.")]
                return tool_result_event(tool, item.get("result"))
            if kind != "item.completed":
                return None
            if item_type == "error":
                return error_event(str(item.get("message") or "Unbekannter Codex-Fehler."))
            if item_type in {"agent_message", "assistant_message", "message"} and item.get("text"):
                return text_event(item["text"])
            if item_type == "command_execution":
                # Eingebautes Shell-Werkzeug von Codex (laeuft in der Sandbox).
                exit_code = item.get("exit_code")
                return [
                    tool_call_event("shell", item.get("command")),
                    tool_result_event("shell", item.get("aggregated_output"), bool(exit_code) if exit_code is not None else None),
                ]
            if item_type in {"tool_call", "function_call"}:
                return tool_call_event(item.get("tool") or item.get("name", "?"), item.get("input") or item.get("arguments") or item.get("command"))
            if item_type in {"mcp_tool_result", "tool_result", "function_call_output"}:
                return tool_result_event(item.get("tool") or item.get("name", "?"), item.get("output") or item.get("result"))
            return None
        if kind == "turn.completed":
            return done_event(session.resume_token)
        if kind == "turn.failed":
            return error_event(str((data.get("error") or {}).get("message") or "Codex-Anfrage fehlgeschlagen."))
        if kind == "error":
            return error_event(str(data.get("message") or "Unbekannter Codex-Fehler."))
        return None


class VibeCliProvider(CliChatProvider):
    """Gegen echte vibe-cli 3.0.2 (pip install mistral-vibe) end-to-end verifiziert: echte
    MCP-Tool-Aufrufe (search_wissen/read_file ueber mcp_wissen.*) und Mehrturn-Sitzungen
    (--resume) funktionieren nachweislich, inklusive korrekt durchgesetzter Pfadpruefung
    (ein echter Aufruf von mcp_wissen.read_file ausserhalb wissen/unterricht wurde vom
    MCP-Server selbst mit "Pfad liegt ausserhalb des Projekts" abgelehnt).

    Die eingebauten Werkzeuge der CLI (``file_system.bash``/``file_system.read_file``) lassen
    sich weder mit ``--enabled-tools`` noch mit ``--disabled-tools`` zuverlaessig abschalten
    (``--enabled-tools`` legt sogar die MCP-Discovery lahm). Deshalb laeuft die CLI in der
    bubblewrap-Sandbox aus ``sandbox.py``; ohne ``bwrap`` ist der Provider gesperrt.
    Real verifiziert: ``cat ~/.gitconfig`` ueber ``file_system.bash`` scheitert in der
    Sandbox, ``mcp_wissen.search_wissen`` funktioniert. ``experimental`` bleibt True."""

    name = "mistral"
    experimental = True
    needs_sandbox = True
    sandbox_env_prefixes = ("MISTRAL_", "VIBE_")
    send_prompt_via_stdin = False
    MCP_SERVER_NAME = "wissen"

    def binary(self) -> str:
        return self.config.vibe_bin

    def _cli_readonly(self) -> list[Path]:
        root = sandbox.installation_root(self.binary())
        return [root] if root else []

    def _cli_writable(self) -> list[Path]:
        return [Path(os.environ.get("VIBE_HOME") or Path.home() / ".vibe")]

    def _usage_key(self) -> str:
        return self.config.mistral_admin_api_key

    # Die Nutzungsabfrage ist ein externer HTTP-Aufruf; ohne Cache wuerde jedes Oeffnen des
    # Panels (GET /api/chat/providers) darauf warten.
    USAGE_TTL = 60.0
    USAGE_ERROR_TTL = 30.0
    USAGE_TIMEOUT = 3.0
    _clock: Callable[[], float] = staticmethod(time.monotonic)
    _usage_cache: tuple[float, dict[str, Any]] | None = None

    def usage_hint(self) -> dict[str, Any]:
        key = self._usage_key()
        if not key:
            return {"kind": "link", "message": "Nutzungsstand in der Vibe-CLI pruefen (vibe usage)."}
        cached = self._usage_cache
        if cached is not None and self._clock() < cached[0]:
            return cached[1]
        hint, ttl = self._fetch_usage(key)
        self._usage_cache = (self._clock() + ttl, hint)
        return hint

    def _fetch_usage(self, key: str) -> tuple[dict[str, Any], float]:
        unavailable = {"kind": "link", "message": "Mistral-Nutzungsdaten nicht verfügbar."}
        try:
            response = httpx.get(MISTRAL_USAGE_URL, headers={"Authorization": f"Bearer {key}"}, timeout=self.USAGE_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return unavailable, self.USAGE_ERROR_TTL
        used, limit = data.get("used"), data.get("limit")
        if used is None or limit is None:
            return unavailable, self.USAGE_ERROR_TTL
        return {"kind": "bar", "used": used, "limit": limit, "label": "Mistral-Nutzung"}, self.USAGE_TTL

    def prepare(self) -> None:
        """``vibe mcp add`` mit demselben Namen schlaegt beim zweiten Mal fehl ("already
        configured") - mit check=False harmlos, macht die Registrierung idempotent."""
        command = self._mcp_server_command()
        args = [
            self.binary(), "mcp", "add", self.MCP_SERVER_NAME,
            "--transport", "stdio", "--command", command[0],
            # "--arg -m" wuerde vibe als eigene Flag -m interpretieren statt als Argumentwert -
            # das "--arg=<value>"-Gleichheitszeichen-Format umgeht das.
            f"--arg={command[1]}", f"--arg={command[2]}",
            "--env", f"MATERIAL_UI_ROOT={self.config.root}",
            "--env", f"MATERIAL_UI_BASE_URL={self._base_url()}",
        ]
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            subprocess.run(args, capture_output=True, timeout=10, check=False)

    def _build_command(self, session: CliSession, text: str) -> list[str]:
        unterricht_dir = self.config.root / "unterricht"
        wissen_dir = self.config.root / "wissen"
        # Kein --enabled-tools/--disabled-tools: im echten Test hat JEDE --enabled-tools-Angabe
        # (egal in welchem Namensformat) die MCP-Tool-Discovery komplett lahmgelegt (das Modell
        # fand search_wissen & co. dann gar nicht mehr) - ohne die Einschraenkung funktionieren
        # die MCP-Werkzeuge, bleiben aber eben neben den eingebauten Werkzeugen verfuegbar
        # (siehe Klassendocstring: bestaetigte, ungeloeste Sandbox-Luecke).
        command = [
            self.binary(), "-p", text,
            "--output", "streaming",
            "--workdir", str(wissen_dir), "--add-dir", str(unterricht_dir),
            "--auto-approve",
        ]
        if session.resume_token:
            command += ["--resume", session.resume_token]
        return command

    def _parse_line(self, line: str, session: CliSession) -> ChatEvent | list[ChatEvent] | None:
        data = json.loads(line)
        if data.get("sessionId"):
            session.resume_token = data["sessionId"]
        kind = data.get("type")
        if kind == "message":
            if data.get("role") != "assistant":
                return None
            text = "".join(block.get("text", "") for block in data.get("content") or [] if block.get("type") == "text")
            return text_event(text) if text else None
        if kind == "effect":
            # Vibe buendelt Tool-Aufruf und -Ergebnis in einem einzigen "effect"-Eintrag
            # (anders als Claude/Codex mit getrennten Zeilen) - hier als zwei Events gemeldet.
            detail = data.get("detail") or {}
            tool_name = detail.get("toolName", "?")
            state = data.get("state") or {}
            events = [tool_call_event(tool_name, detail.get("input"))]
            if state.get("status") == "completed":
                events.append(tool_result_event(tool_name, state.get("outputText") or state.get("output")))
            elif state.get("status") in {"error", "failed"}:
                events.append(tool_result_event(tool_name, state.get("outputText") or state.get("output"), True))
            return events
        if kind == "error":
            return error_event(str(data.get("message") or "Unbekannter Vibe-Fehler."))
        return None
