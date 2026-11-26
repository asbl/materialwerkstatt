"""Dateisystem-Sandbox (bubblewrap) fuer Chat-CLIs ohne eigenes Werkzeug-Whitelisting.

Nur die Claude-CLI laesst sich ueber ``--tools``/``--restricted`` so einschraenken, dass
sie ausschliesslich die drei MCP-Werkzeuge sieht. Codex und Vibe behalten ihre eingebauten
Datei- und Shell-Werkzeuge; ein Modell koennte damit beliebige Dateien des Nutzers lesen
(``~/.git-credentials``, ``foerderempfehlungen/`` mit Schuelerdaten, ...). Deshalb starten
diese Provider ihre CLI innerhalb von ``bwrap``:

* Wurzel-Dateisystem nur lesend (``/usr``, ``/etc``, ...), ``$HOME`` ist ein leeres tmpfs.
* Von Repo und Home sind ausschliesslich ``wissen/``, ``unterricht/``, der Quellbaum fuer den
  MCP-Server, die Installation der CLI selbst und deren Konfigurationsordner sichtbar.
* ``foerderempfehlungen/``, ``.git``, ``.env`` & Co. liegen ausserhalb der Sandbox.
* Das Netz bleibt offen (die CLI braucht die Modell-API und die lokale Material-UI).
* Die Umgebung wird geleert; nur eine kleine Allowlist wird durchgereicht.

Ist ``bwrap`` nicht vorhanden, sperrt der Chat-Dienst diese Provider (siehe ``restriction``
in ``providers.py``), statt sie ungeschuetzt zu starten.
"""

from __future__ import annotations

import os
import shutil
import site
import sys
from pathlib import Path
from typing import Iterable, Mapping

ALLOW_UNSANDBOXED_ENV = "MATERIAL_UI_CHAT_ALLOW_UNSANDBOXED"

# Nur lesend eingebunden; fehlende Eintraege werden uebersprungen (bind-try).
SYSTEM_READONLY = ("/usr", "/etc", "/opt", "/lib", "/lib64", "/bin", "/sbin", "/run/systemd/resolve")

# Umgebungsvariablen, die in die Sandbox durchgereicht werden. Alles andere
# (Tokens, SSH-Agent, Cloud-Zugaenge, ...) bleibt draussen.
ENV_EXACT = frozenset({
    "PATH", "LANG", "LANGUAGE", "TERM", "TZ", "USER", "LOGNAME",
    "PYTHONPATH", "MATERIAL_UI_ROOT", "MATERIAL_UI_BASE_URL",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
})
ENV_PREFIXES = ("LC_",)
# Auch mit passendem Praefix niemals durchreichen.
ENV_DENIED = frozenset({"MISTRAL_ADMIN_API_KEY"})


def bwrap_binary() -> str | None:
    return shutil.which("bwrap")


def sandbox_available() -> bool:
    return bwrap_binary() is not None


def _depth(path: Path) -> int:
    return len(path.parts)


def filter_env(env: Mapping[str, str], extra_prefixes: Iterable[str] = ()) -> dict[str, str]:
    """Reduziert ``env`` auf die Allowlist (plus providerspezifische Praefixe)."""
    prefixes = (*ENV_PREFIXES, *extra_prefixes)
    return {
        key: value for key, value in env.items()
        if key not in ENV_DENIED and (key in ENV_EXACT or key.startswith(prefixes))
    }


def python_mounts() -> list[Path]:
    """Python-Installation(en), die der MCP-Server braucht und die nicht unter ``/usr`` liegen."""
    candidates: list[str] = [sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix]
    candidates += site.getsitepackages()
    with_user = getattr(site, "getusersitepackages", None)
    if with_user is not None:
        candidates.append(with_user())
    home = Path.home().resolve()
    result: list[Path] = []
    for value in candidates:
        path = Path(value).resolve()
        if not path.exists() or path in result:
            continue
        # Nie ein Verzeichnis einbinden, das $HOME oder die Wurzel enthaelt.
        if path == Path("/") or home.is_relative_to(path):
            continue
        if any(path.is_relative_to(prefix) for prefix in map(Path, SYSTEM_READONLY)):
            continue
        result.append(path)
    return result


def build_command(
    command: list[str],
    *,
    cwd: Path,
    home: Path,
    readonly: Iterable[Path],
    writable: Iterable[Path],
    env: Mapping[str, str],
    bwrap: str | None = None,
) -> list[str]:
    """Verpackt ``command`` in einen ``bwrap``-Aufruf mit den angegebenen Freigaben."""
    executable = bwrap or bwrap_binary()
    if executable is None:
        raise FileNotFoundError("bwrap ist nicht installiert.")
    args = [
        executable, "--die-with-parent", "--new-session",
        "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--clearenv",
    ]
    for path in SYSTEM_READONLY:
        args += ["--ro-bind-try", path, path]
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", str(home)]
    # Reihenfolge: Eltern vor Kindern, damit ein spaeter eingebundener Elternordner
    # keinen bereits eingebundenen Unterordner verdeckt.
    for path in sorted({Path(item) for item in readonly}, key=_depth):
        args += ["--ro-bind-try", str(path), str(path)]
    for path in sorted({Path(item) for item in writable}, key=_depth):
        args += ["--bind-try", str(path), str(path)]
    sandbox_env = dict(env)
    sandbox_env["HOME"] = str(home)
    for key, value in sorted(sandbox_env.items()):
        args += ["--setenv", key, value]
    args += ["--chdir", str(cwd), "--", *command]
    return args


def allow_unsandboxed(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "ja", "on"}


def installation_root(binary: str, marker: str | None = None) -> Path | None:
    """Ordner, der die Installation einer CLI enthaelt (damit er in die Sandbox eingebunden wird).

    Ohne ``marker``: Elternordner von ``bin/`` des aufgeloesten Binaries (Venv-Installationen).
    Mit ``marker`` (z. B. ``node_modules``): der naechstliegende Vorfahr mit diesem Namen.
    """
    found = shutil.which(binary)
    if not found:
        return None
    resolved = Path(os.path.realpath(found))
    if marker:
        for parent in resolved.parents:
            if parent.name == marker:
                return parent
        return resolved.parent
    return resolved.parent.parent if resolved.parent.name == "bin" else resolved.parent
