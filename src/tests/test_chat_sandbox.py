"""Dateisystem-Sandbox und Sperre fuer Chat-Provider mit eingebauten Datei-Werkzeugen (Codex, Vibe)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from material_ui.config import AppConfig
from material_ui.plugins.context import ensure_plugin_parent

ensure_plugin_parent()

from material_ui_plugins.chat import sandbox
from material_ui_plugins.chat.providers import (
    ClaudeCliProvider,
    CliChatProvider,
    CliSession,
    CodexCliProvider,
    VibeCliProvider,
)

BASE_URL = "http://127.0.0.1:9999"


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    for name in ("wissen", "unterricht", "src", "foerderempfehlungen", "build"):
        (tmp_path / name).mkdir()
    (tmp_path / "build" / "material-index.json").write_text("{}", encoding="utf-8")
    return AppConfig(root=tmp_path)


def _bwrap_works() -> bool:
    if not sandbox.sandbox_available():
        return False
    command = sandbox.build_command(
        ["/bin/true"], cwd=Path("/"), home=Path("/home/unbenutzt"), readonly=[], writable=[], env={"PATH": "/usr/bin"},
    )
    try:
        return subprocess.run(command, capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


requires_bwrap = pytest.mark.skipif(not _bwrap_works(), reason="bwrap fehlt oder Benutzer-Namensraeume sind gesperrt")


# -- Umgebung ---------------------------------------------------------------------


def test_filter_env_keeps_only_allowlisted_variables():
    env = {
        "PATH": "/usr/bin", "LANG": "de_DE.UTF-8", "LC_TIME": "de_DE.UTF-8",
        "PYTHONPATH": "/x", "MATERIAL_UI_ROOT": "/r",
        "GITHUB_TOKEN": "geheim", "SSH_AUTH_SOCK": "/run/agent", "AWS_SECRET_ACCESS_KEY": "geheim",
        "MISTRAL_ADMIN_API_KEY": "admin", "MISTRAL_API_KEY": "key", "OPENAI_API_KEY": "key",
    }
    filtered = sandbox.filter_env(env)
    assert set(filtered) == {"PATH", "LANG", "LC_TIME", "PYTHONPATH", "MATERIAL_UI_ROOT"}


def test_filter_env_provider_prefixes_never_pass_admin_key():
    env = {"MISTRAL_ADMIN_API_KEY": "admin", "MISTRAL_API_KEY": "key", "OPENAI_API_KEY": "nein", "VIBE_HOME": "/v"}
    filtered = sandbox.filter_env(env, ("MISTRAL_", "VIBE_"))
    assert filtered == {"MISTRAL_API_KEY": "key", "VIBE_HOME": "/v"}


# -- Kommandozeile ----------------------------------------------------------------


def test_build_command_layout(tmp_path: Path):
    home = tmp_path / "home"
    command = sandbox.build_command(
        ["tool", "--flag"], cwd=tmp_path / "wissen", home=home,
        readonly=[tmp_path / "wissen" / "tief", tmp_path / "wissen"],
        writable=[home / ".codex"], env={"PATH": "/usr/bin"}, bwrap="/usr/bin/bwrap",
    )
    assert command[0] == "/usr/bin/bwrap"
    assert command[command.index("--") + 1:] == ["tool", "--flag"]
    assert {"--die-with-parent", "--unshare-pid", "--clearenv"} <= set(command)
    assert command[command.index("--chdir") + 1] == str(tmp_path / "wissen")
    # $HOME ist ein leeres tmpfs und kommt vor allen Einbindungen darunter.
    tmpfs_home = command.index(str(home))
    assert command[tmpfs_home - 1] == "--tmpfs"
    assert tmpfs_home < command.index(str(home / ".codex"))
    # Eltern vor Kindern, sonst verdeckt der Elternordner den Unterordner.
    parent = command.index(str(tmp_path / "wissen"), tmpfs_home)
    child = command.index(str(tmp_path / "wissen" / "tief"))
    assert parent < child
    # Schreibzugriff nur fuer den ausdruecklich genannten Ordner.
    writable = [command[i + 1] for i, item in enumerate(command) if item == "--bind-try"]
    assert writable == [str(home / ".codex")]
    # HOME wird gesetzt, sonst nichts ausser der Allowlist.
    setenv = {command[i + 1]: command[i + 2] for i, item in enumerate(command) if item == "--setenv"}
    assert setenv == {"PATH": "/usr/bin", "HOME": str(home)}


def test_build_command_requires_bwrap(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sandbox, "bwrap_binary", lambda: None)
    with pytest.raises(FileNotFoundError):
        sandbox.build_command(["x"], cwd=tmp_path, home=tmp_path, readonly=[], writable=[], env={})


def test_python_mounts_never_include_home_or_root(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(sys, "prefix", str(tmp_path))  # enthaelt $HOME -> verboten
    monkeypatch.setattr(sys, "base_prefix", "/")
    mounts = sandbox.python_mounts()
    assert tmp_path not in mounts and Path("/") not in mounts


# -- Provider ---------------------------------------------------------------------


@pytest.mark.parametrize("cls", [CodexCliProvider, VibeCliProvider])
def test_codex_and_vibe_require_sandbox_claude_does_not(cls, config):
    assert cls.needs_sandbox is True
    assert ClaudeCliProvider.needs_sandbox is False
    assert ClaudeCliProvider(config, lambda: BASE_URL).restriction() is None


@pytest.mark.parametrize("cls", [CodexCliProvider, VibeCliProvider])
def test_provider_is_blocked_without_bwrap(cls, config, monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: False)
    provider = cls(config, lambda: BASE_URL)
    assert provider.confined() is False
    reason = provider.restriction()
    assert reason and "bubblewrap" in reason and sandbox.ALLOW_UNSANDBOXED_ENV in reason


@pytest.mark.parametrize("cls", [CodexCliProvider, VibeCliProvider])
def test_blocked_provider_never_starts_a_process(cls, config, monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: False)

    def fail(*args, **kwargs):
        raise AssertionError("Subprozess darf nicht gestartet werden")

    monkeypatch.setattr(subprocess, "Popen", fail)
    provider = cls(config, lambda: BASE_URL)
    events = list(provider.send(CliSession(), "hallo"))
    assert [event.type for event in events] == ["error"]
    assert "bubblewrap" in events[0].message


@pytest.mark.parametrize("cls", [CodexCliProvider, VibeCliProvider])
def test_explicit_override_allows_unsandboxed_run(cls, config, monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: False)
    provider = cls(replace(config, chat_allow_unsandboxed=True), lambda: BASE_URL)
    assert provider.restriction() is None
    command = ["codex", "exec"]
    assert provider._confine(command, {"PATH": "/usr/bin"}) == command


@pytest.mark.parametrize("cls", [CodexCliProvider, VibeCliProvider])
def test_provider_is_not_blocked_with_bwrap(cls, config, monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: True)
    assert cls(config, lambda: BASE_URL).restriction() is None


def test_claude_command_is_never_wrapped(config, monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: True)
    provider = ClaudeCliProvider(config, lambda: BASE_URL)
    command = provider._build_command(CliSession(), "Text")
    assert provider._confine(command, {"PATH": "/usr/bin"}) == command


@pytest.mark.parametrize("cls,secret_env", [
    (CodexCliProvider, "OPENAI_API_KEY"), (VibeCliProvider, "MISTRAL_API_KEY"),
])
def test_confined_command_exposes_only_material_and_cli(cls, secret_env, config, monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: True)
    monkeypatch.setattr(sandbox, "bwrap_binary", lambda: "/usr/bin/bwrap")
    provider = cls(config, lambda: BASE_URL)
    env = {**provider._mcp_server_env(), "GITHUB_TOKEN": "geheim", "MISTRAL_ADMIN_API_KEY": "admin", secret_env: "cli-key"}
    command = provider._confine([provider.binary(), "--version"], env)
    assert command[0] == "/usr/bin/bwrap"
    mounts = {command[i + 1] for i, item in enumerate(command) if item in {"--ro-bind-try", "--bind-try"}}
    root = config.root.resolve()
    # Freigegeben: nur Wissensbasis, Unterricht und der Suchindex - nie das Repo als Ganzes.
    assert {str(root / "wissen"), str(root / "unterricht"), str(root / "build" / "material-index.json")} <= mounts
    assert str(root) not in mounts
    assert not any("foerderempfehlungen" in mount or mount.endswith(".git") for mount in mounts)
    home = str(Path.home().resolve())
    assert home not in mounts
    setenv = {command[i + 1] for i, item in enumerate(command) if item == "--setenv"}
    assert secret_env in setenv
    assert not {"GITHUB_TOKEN", "MISTRAL_ADMIN_API_KEY"} & setenv
    assert command[command.index("--chdir") + 1] == str(root / "wissen")


def test_cli_config_dir_is_the_only_writable_mount(config, monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "sandbox_available", lambda: True)
    monkeypatch.setattr(sandbox, "bwrap_binary", lambda: "/usr/bin/bwrap")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    provider = CodexCliProvider(config, lambda: BASE_URL)
    command = provider._confine(["codex"], provider._mcp_server_env())
    writable = [command[i + 1] for i, item in enumerate(command) if item == "--bind-try"]
    assert writable == [str(codex_home)]


# -- Echte Sandbox (bwrap) ----------------------------------------------------------


@requires_bwrap
def test_real_sandbox_hides_home_and_private_folders(config, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_rsa").write_text("privat", encoding="utf-8")
    (home / ".codex").mkdir()
    (config.root / "wissen" / "a.txt").write_text("erlaubt\n", encoding="utf-8")
    (config.root / "foerderempfehlungen" / "kind.md").write_text("personenbezogen", encoding="utf-8")
    (config.root / ".env").write_text("TOKEN=geheim", encoding="utf-8")
    outside = tmp_path.parent / "ausserhalb.txt"
    outside.write_text("fremd", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "geheim")
    root = config.root
    script = "; ".join([
        f"cat '{root}/wissen/a.txt'",
        f"cat '{root}/foerderempfehlungen/kind.md' 2>/dev/null && echo LEAK-PII",
        f"cat '{root}/.env' 2>/dev/null && echo LEAK-ENV",
        f"cat '{home}/.ssh/id_rsa' 2>/dev/null && echo LEAK-SSH",
        f"cat '{outside}' 2>/dev/null && echo LEAK-OUTSIDE",
        f"echo x > '{root}/wissen/neu.txt' 2>/dev/null && echo LEAK-WRITE",
        f"echo y > '{home}/.codex/token' && echo CONFIG-WRITE-OK",
        f"echo z > '{home}/scratch' && echo SCRATCH-OK",
        "echo KEY=${ANTHROPIC_API_KEY:-leer}",
    ])
    command = sandbox.build_command(
        ["/bin/sh", "-c", script], cwd=root / "wissen", home=home,
        readonly=[root / "wissen", root / "unterricht"], writable=[home / ".codex"],
        env=sandbox.filter_env(os.environ),
    )
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    lines = result.stdout.split()
    assert "erlaubt" in lines
    assert not [line for line in lines if line.startswith("LEAK")], result.stdout
    assert "CONFIG-WRITE-OK" in lines and "SCRATCH-OK" in lines
    assert "KEY=leer" in lines
    # Die Host-Dateien sind unveraendert: der Schreibversuch ins Repo ist gescheitert,
    # das Scratch-Verzeichnis im tmpfs-Home hat den Host nicht erreicht.
    assert not (config.root / "wissen" / "neu.txt").exists()
    assert not (home / "scratch").exists()
    assert (home / ".codex" / "token").read_text().strip() == "y"


@requires_bwrap
@pytest.mark.parametrize("cls,binary", [(CodexCliProvider, "codex"), (VibeCliProvider, "vibe")])
def test_real_cli_starts_inside_sandbox(cls, binary, config, tmp_path, monkeypatch):
    """Nur mit installierter CLI: die Sandbox bindet genug ein, damit sie startet (kein Netz noetig)."""
    if shutil.which(binary) is None:
        pytest.skip(f"{binary} nicht installiert")
    provider = cls(config, lambda: BASE_URL)
    env = provider._mcp_server_env()
    command = provider._confine([provider.binary(), "--version"], env)
    assert command[0] == sandbox.bwrap_binary()
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


class _ConfinedSleeper(CliChatProvider):
    name = "sleeper"
    needs_sandbox = True
    timeout_seconds = 0.5
    MARK = "7.31"

    def binary(self) -> str:
        return "sleep"

    def usage_hint(self):
        return {"kind": "link", "message": ""}

    def _build_command(self, session, text):
        return ["sleep", self.MARK]

    def _parse_line(self, line, session):
        return None


@requires_bwrap
def test_watchdog_kills_the_whole_sandbox(config):
    provider = _ConfinedSleeper(config, lambda: BASE_URL)
    started = time.monotonic()
    events = list(provider.send(provider.create_session(), "hallo"))
    assert time.monotonic() - started < 5
    assert events[-1].type == "error" and "Keine Antwort" in events[-1].message
    time.sleep(0.3)
    left = subprocess.run(["pgrep", "-f", f"sleep {_ConfinedSleeper.MARK}"], capture_output=True, text=True)
    assert left.stdout.strip() == "", "Sandbox-Prozess lief nach dem Timeout weiter"
