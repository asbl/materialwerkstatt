"""Programm-Updates: neuestes Release erkennen und einen Git-Klon aktualisieren.

Ein Release ist ein Tag `vX.Y.Z` im oeffentlichen Repository; die installierte Version steht
in `pyproject.toml`. Abgefragt wird mit `git ls-remote`, es werden keine Daten ueber den
Rechner oder die Inhalte uebertragen. `MATERIAL_UI_UPDATE_CHECK=0` schaltet die Abfrage ab,
`MATERIAL_UI_UPDATE_URL` waehlt eine andere Quelle (z. B. einen Fork). Nur Standardbibliothek.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from material_core import workspace

CHECK_ENV = "MATERIAL_UI_UPDATE_CHECK"
URL_ENV = "MATERIAL_UI_UPDATE_URL"
CACHE_SECONDS = 24 * 3600
RETRY_SECONDS = 3600
_RELEASE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


class UpdateError(RuntimeError):
    """Verstaendliche Meldung fuer die Oberflaeche."""


def enabled() -> bool:
    return os.environ.get(CHECK_ENV, "").strip().lower() not in {"0", "false", "no", "nein", "off"}


def _project(code_root: Path | None = None) -> dict:
    """Abschnitt `[project]` der `pyproject.toml`; leer, wenn sie fehlt oder unlesbar ist."""
    try:
        text = ((code_root or workspace.CODE_ROOT) / "pyproject.toml").read_text(encoding="utf-8")
        return tomllib.loads(text).get("project", {})
    except (OSError, ValueError):
        return {}


def source_url() -> str:
    """Eingestellte Quelle, sonst `project.urls.Repository` der installierten Version."""
    return os.environ.get(URL_ENV, "").strip() or str(_project().get("urls", {}).get("Repository", ""))


def parse_release(text: str) -> tuple[int, int, int] | None:
    """`v1.2.3` oder `1.2.3`; Vorabversionen und andere Tags zaehlen nicht."""
    match = _RELEASE.fullmatch(str(text).strip())
    return tuple(int(part) for part in match.groups()) if match else None


def is_newer(candidate: str | None, current: str | None) -> bool:
    new, old = parse_release(candidate or ""), parse_release(current or "")
    return new is not None and old is not None and new > old


def current_version(code_root: Path | None = None) -> str | None:
    version = _project(code_root).get("version")
    return str(version) if version else None


def install_kind(code_root: Path | None = None) -> str:
    """`git` (selbst aktualisierbar), `package` (Paketverwaltung) oder `manual`."""
    code_root = code_root or workspace.CODE_ROOT
    if workspace.installed(code_root):
        return "package"
    return "git" if (code_root / ".git").exists() else "manual"


def _run(command: list[str], timeout: float, cwd: Path | None = None) -> str:
    # Ohne Terminal darf git nie auf eine Passworteingabe warten.
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        result = subprocess.run(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as error:
        raise UpdateError(f"{command[0]} ist nicht installiert.") from error
    except subprocess.TimeoutExpired as error:
        raise UpdateError(f"Zeitüberschreitung bei {Path(command[0]).name}.") from error
    if result.returncode:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise UpdateError(" ".join(lines[-3:]) or f"{command[0]} ist fehlgeschlagen.")
    return result.stdout.strip()


def latest_release(url: str) -> str | None:
    """Hoechste Versionsnummer unter den Tags der Quelle (ohne `v`)."""
    if not url:
        raise UpdateError("Keine Update-Quelle eingetragen.")
    output = _run(["git", "ls-remote", "--tags", "--refs", "--", url], timeout=15)
    releases = [parsed for line in output.splitlines()
                if (parsed := parse_release(line.rpartition("refs/tags/")[2])) is not None]
    return ".".join(map(str, max(releases))) if releases else None


def latest_cached(cache: Path, *, refresh: bool = False) -> dict:
    """`{latest, checkedAt, error}`; fragt hoechstens einmal taeglich an (`refresh` erzwingt es)."""
    url = source_url()
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("url") != url:
            data = {}
    except (OSError, ValueError):
        data = {}
    age = time.time() - (data.get("checkedAt") or 0)
    if not refresh and data and age < (RETRY_SECONDS if data.get("error") else CACHE_SECONDS):
        return data
    try:
        data = {"url": url, "latest": latest_release(url), "error": ""}
    except UpdateError as error:
        # Offline: den zuletzt bekannten Stand behalten.
        data = {"url": url, "latest": data.get("latest"), "error": str(error)}
    data["checkedAt"] = time.time()
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
    return data


def apply(version: str, code_root: Path | None = None) -> str:
    """Git-Klon per Fast-Forward auf das Release setzen und Abhaengigkeiten nachziehen.

    Lokale Aenderungen oder eigene Commits werden nie ueberschrieben. Scheitert die
    Installation der Abhaengigkeiten, wird der vorherige Stand wiederhergestellt.
    """
    code_root = code_root or workspace.CODE_ROOT
    if install_kind(code_root) != "git":
        raise UpdateError("Diese Installation ist kein Git-Klon und kann sich nicht selbst aktualisieren.")
    if not is_newer(version, current_version(code_root)):
        raise UpdateError("Diese Version ist bereits installiert.")

    def git(*args: str) -> str:
        return _run(["git", *args], timeout=180, cwd=code_root)

    if git("status", "--porcelain", "--untracked-files=no"):
        raise UpdateError("Im Programmordner gibt es lokale Änderungen. Bitte erst committen oder verwerfen.")
    previous = git("rev-parse", "HEAD")
    git("fetch", "--quiet", "--", source_url(), f"refs/tags/v{version}")
    try:
        git("merge", "--ff-only", "--quiet", "FETCH_HEAD")
    except UpdateError as error:
        raise UpdateError("Der lokale Stand enthält eigene Commits oder Dateien, die dem Update im Weg "
                          f"stehen. Bitte von Hand mit git aktualisieren. ({error})") from error
    if sys.prefix == sys.base_prefix:
        return (f"Auf {version} aktualisiert. Ohne virtuelle Umgebung bitte neue Abhängigkeiten "
                "selbst installieren (pip install -e .).")
    try:
        _run([sys.executable, "-m", "pip", "install", "--quiet", "-e", str(code_root)], timeout=600)
    except UpdateError as error:
        git("reset", "--quiet", "--keep", previous)
        raise UpdateError(f"Abhängigkeiten ließen sich nicht installieren, der alte Stand bleibt: {error}") from error
    return f"Auf {version} aktualisiert."
