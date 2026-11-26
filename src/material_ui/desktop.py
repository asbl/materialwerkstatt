from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


CODE = Path(__file__).resolve().parents[2]
SRC = CODE / "src"
# Der GNOME-Launcher startet dieses Skript als `python -I <pfad>/desktop.py`:
# Dabei landen weder PYTHONPATH noch das Arbeitsverzeichnis auf sys.path, nur das
# Skriptverzeichnis (src/material_ui). Damit `import material_ui...` in jedem Zweig
# (Launcher, --server, --serve) funktioniert, src/ explizit vormerken.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from material_core import workspace  # noqa: E402

# Inhaltsordner: Dokumente, build/ und Zustand. Programmdateien liegen unter CODE.
ROOT = workspace.root()
APP_ID = "material-ui"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
BASE_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"


def base_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    return f"http://{host}:{port}"


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))


def state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / APP_ID


def application_version() -> str:
    digest = hashlib.sha256()
    source_root = Path(__file__).resolve().parent.parent
    sources = [source_root / "quarto_render_guard.py"]
    for package in ("material_ui", "material_core", "course_sync", "excalideck"):
        for directory, names, files in os.walk(source_root / package):
            names[:] = [name for name in names if name not in {"node_modules", "dist", "__pycache__"}]
            sources.extend(Path(directory) / name for name in files)
    # Auch nachinstallierte Plugins (XDG-Verzeichnis oder MATERIAL_UI_PLUGIN_PATHS)
    # veraendern den Serverstand; der Starter startet sie deshalb mit neu.
    from material_ui.plugins.paths import external_plugin_directories

    for plugin_root in dict.fromkeys([*external_plugin_directories(), source_root.parent / "plugins", ROOT / "plugins"]):
        # followlinks: Entwicklungsinstallationen sind Symlinks auf das Arbeitsverzeichnis.
        for directory, names, files in os.walk(plugin_root, followlinks=True):
            names[:] = [name for name in names if name not in {"node_modules", "dist", "__pycache__", ".git"}]
            sources.extend(Path(directory) / name for name in files)
    for source in sorted(sources):
        if source.is_file() and source.suffix in {".py", ".js", ".jsx", ".css", ".html", ".svg", ".json"}:
            try:
                key = source.relative_to(source_root).as_posix()
            except ValueError:
                # Nachinstallierte Plugins liegen ausserhalb des Quellbaums; ihr absoluter
                # Pfad stabalisiert den Fingerprint zusaetzlich zum Inhalt.
                key = source.as_posix()
            digest.update(key.encode())
            digest.update(source.read_bytes())
    return digest.hexdigest()


def document_path(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme == "file":
        if parsed.netloc not in {"", "localhost"}:
            raise ValueError("Nur lokale Dateien können geöffnet werden.")
        source = Path(urllib.parse.unquote(parsed.path))
    elif parsed.scheme:
        raise ValueError("Erwartet wird ein lokaler Dateipfad.")
    else:
        source = Path(value).expanduser()
    source = source.resolve()
    if source.suffix == ".mdx":
        return course_mdx_path(source)
    if source.suffix != ".qmd" or not source.is_file():
        raise ValueError(f"Keine QMD-Datei: {source}")
    try:
        return source.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(source)


def course_mdx_path(source: Path) -> str:
    if not source.is_file():
        raise ValueError(f"Keine MDX-Datei: {source}")
    try:
        relative = source.relative_to(ROOT.resolve())
    except ValueError:
        raise ValueError("MDX-Dateien können nur aus dem Repository geöffnet werden.") from None
    if relative.parts[:2] != ("unterricht", "kurse"):
        raise ValueError("MDX-Dateien werden nur für Kurse unterstützt.")
    return relative.as_posix()


def server_status(url: str = BASE_URL) -> dict | None:
    try:
        with urllib.request.urlopen(f"{url}/api/desktop-status", timeout=1) as response:
            status = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise RuntimeError("Port 8765 wird von einer anderen Anwendung verwendet.") from error
        try:
            with urllib.request.urlopen(f"{url}/api/qmds", timeout=10) as response:
                legacy = json.load(response)
            if legacy.get("root") == str(ROOT) and isinstance(legacy.get("qmds"), list):
                return {"application": "material-ui", "root": str(ROOT), "version": None}
        except (urllib.error.URLError, TimeoutError, ValueError, AttributeError):
            pass
        raise RuntimeError("Port 8765 wird von einer anderen Anwendung oder einem anderen Repository verwendet.") from error
    except (urllib.error.URLError, TimeoutError):
        return None
    except ValueError as error:
        raise RuntimeError("Port 8765 liefert keine Material-UI-Antwort.") from error
    # Dasselbe Programm mit anderem Inhaltsordner bleibt erkennbar (Neustart nach Umstellung).
    if not isinstance(status, dict) or status.get("application") != "material-ui" or (
            status.get("root") != str(ROOT) and status.get("code") != str(CODE)):
        raise RuntimeError("Port 8765 wird von einer anderen Anwendung oder einem anderen Repository verwendet.")
    return status


def server_ready(url: str = BASE_URL) -> bool:
    status = server_status(url)
    return (status is not None and status.get("root", str(ROOT)) == str(ROOT)
            and status.get("version") == application_version())


def stop_existing_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    sys.path.insert(0, str(SRC))
    from project_tasks import _restart_existing_material_ui

    _restart_existing_material_ui(host, port)


def manage_server(action: str, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    url = base_url(host, port)
    if action == "status":
        status = server_status(url)
        if status is None:
            print("Material-UI ist gestoppt.")
        else:
            version = "aktuell" if status.get("version") == application_version() else "veraltet"
            print(f"Material-UI läuft ({version}): {url}")
        return
    directory = state_home()
    directory.mkdir(parents=True, exist_ok=True)
    if action in {"stop", "restart"}:
        with (directory / "startup.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if server_status(url) is not None:
                stop_existing_server(host, port)
        print("Material-UI gestoppt.")
    if action in {"start", "restart"}:
        ensure_server(host, port)
        print(f"Material-UI gestartet: {url}")


def ensure_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    url = base_url(host, port)
    directory = state_home()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "startup.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        status = server_status(url)
        if status is not None:
            if status.get("version") == application_version() and status.get("root", str(ROOT)) == str(ROOT):
                return
            stop_existing_server(host, port)
        with (directory / "server.log").open("a") as log:
            process = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).resolve()), "--serve",
                 "--host", host, "--port", str(port)],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True,
            )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if server_ready(url):
                return
            if process.poll() is not None:
                break
            time.sleep(0.2)
        raise RuntimeError(f"Material-UI konnte nicht starten. Details: {directory / 'server.log'}")


def spawn_restart_helper(host: str, port: int) -> None:
    """Server-Neustart ueber einen entkoppelten Hilfsprozess anstossen.

    Der Hilfsprozess beendet den laufenden Server und startet ihn neu. Er ist
    bewusst vom aktuellen Serverprozess abgekoppelt (start_new_session), weil
    der Server den Neustart nicht selbst ueberleben kann.
    """
    directory = state_home()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "server.log").open("a") as log:
        subprocess.Popen(
            [sys.executable, "-I", str(Path(__file__).resolve()), "--server", "restart",
             "--host", host, "--port", str(port)],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True,
        )


def desktop_quote(value: str) -> str:
    escaped = value.replace("%", "%%")
    for character in ("\\", '"', "`", "$"):
        escaped = escaped.replace(character, "\\" + character)
    return '"' + escaped + '"'


def request_json(path: str, payload: dict | None = None, token: str | None = None, method: str = "GET") -> dict:
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Material-Token"] = token
    request = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def csrf_token() -> str:
    with urllib.request.urlopen(f"{BASE_URL}/", timeout=10) as response:
        page = response.read().decode("utf-8", "replace")
    match = re.search(r'<meta name="material-token" content="([^"]+)"', page)
    if not match:
        raise RuntimeError("Material-UI liefert kein Anfrage-Token.")
    return match.group(1)


def forward_open_request(parameters: dict, timeout: float = 5.0) -> bool:
    """Öffnungswunsch an ein laufendes Fenster übergeben.

    Wahr, wenn ein Fenster den Wunsch übernimmt; sonst wird er verworfen und
    der Aufrufer kann ein neues Fenster öffnen.
    """
    token = csrf_token()
    identifier = request_json("/api/window/open", parameters, token=token, method="POST")["id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if request_json(f"/api/window/open/{identifier}")["claimed"]:
            return True
        time.sleep(0.2)
    request_json(f"/api/window/open/{identifier}", token=token, method="DELETE")
    return False


REGISTRATION_TIMEOUT = 10.0


def wait_for_window_registration() -> None:
    """Warten, bis das gerade gestartete Fenster seinen ersten Herzschlag sendet."""
    deadline = time.monotonic() + REGISTRATION_TIMEOUT
    while time.monotonic() < deadline:
        status = server_status()
        if status is not None and status.get("windows"):
            return
        time.sleep(0.25)


def raise_app_windows() -> None:
    """Bestehendes App-Fenster nach vorn holen; ohne X11-Hilfsprogramm bewusst still."""
    if not shutil.which("xdotool"):
        return
    result = subprocess.run(["xdotool", "search", "--class", f"^{re.escape(APP_ID)}$"], capture_output=True, text=True)
    for window_id in result.stdout.split():
        subprocess.run(["xdotool", "windowactivate", window_id], check=False, capture_output=True)


def install() -> None:
    applications = data_home() / "applications"
    icons = data_home() / "icons/hicolor/scalable/apps"
    mime = data_home() / "mime/packages"
    for directory in (applications, icons, mime):
        directory.mkdir(parents=True, exist_ok=True)
    logo = Path(__file__).parent / "static/favicon.svg"
    # GNOME Shell caches icons by name across icon-theme cache updates.
    # A content-derived name makes a changed logo visible immediately.
    icon_name = f"{APP_ID}-{hashlib.sha256(logo.read_bytes()).hexdigest()[:12]}"
    shutil.copyfile(logo, icons / f"{icon_name}.svg")
    executable = " ".join(desktop_quote(value) for value in (sys.executable, "-I", str(Path(__file__).resolve())))
    desktop = applications / f"{APP_ID}.desktop"
    desktop.write_text(
        "[Desktop Entry]\nType=Application\nName=Materialwerkstatt\n"
        "Comment=Quarto-Materialien und H5P-Kurse bearbeiten\n"
        f"Exec={executable} %f\nIcon={icon_name}\nTerminal=false\n"
        f"StartupWMClass={APP_ID}\nCategories=Education;\n"
        "MimeType=text/x-quarto-markdown;text/x-mdx;\n",
        encoding="utf-8",
    )
    (mime / "material-ui-qmd.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n'
        '  <mime-type type="text/x-quarto-markdown">\n'
        '    <comment>Quarto Markdown</comment>\n'
        '    <sub-class-of type="text/plain"/>\n'
        '    <glob pattern="*.qmd"/>\n'
        '  </mime-type>\n'
        '  <mime-type type="text/x-mdx">\n'
        '    <comment>MDX Kursquelle</comment>\n'
        '    <sub-class-of type="text/plain"/>\n'
        '    <glob pattern="*.mdx"/>\n'
        '  </mime-type>\n</mime-info>\n',
        encoding="utf-8",
    )
    subprocess.run(["update-mime-database", str(data_home() / "mime")], check=True)
    subprocess.run(["update-desktop-database", str(applications)], check=True)
    subprocess.run(["gtk-update-icon-cache", "--force", "--ignore-theme-index", str(data_home() / "icons/hicolor")], check=True)
    subprocess.run(["xdg-mime", "default", desktop.name, "text/x-quarto-markdown"], check=True)
    subprocess.run(["xdg-mime", "default", desktop.name, "text/x-mdx"], check=True)
    print(f"Installiert: {desktop}\nQMD- und Kurs-MDX-Dateien öffnen sich jetzt mit Material UI.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Material UI als Desktop-App öffnen")
    parser.add_argument("source", nargs="?")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--server", choices=["status", "start", "stop", "restart"])
    parser.add_argument("--host", default=DEFAULT_HOST, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.install:
        install()
        return
    if arguments.serve:
        sys.path.insert(0, str(SRC))
        # Der Serverprozess laeuft mit -I (isoliert: ignoriert cwd und env-Variablen
        # wie PYTHONPATH als Haertung gegen Pfad-Injektion). -I blendet dabei auch
        # das User-Site-Verzeichnis aus, in das pyproject-Abhaengigkeiten wie
        # excaligen unter Arch (externally-managed-environment) standardmaessig
        # installiert werden. Pfad gezielt ergaenzen, statt die Isolation
        # aufzuweichen.
        import site

        sys.path.insert(0, site.getusersitepackages())
        import signal
        workspace.activate(strict=False)
        from material_ui.app import run

        def terminate(_signum, _frame):
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, terminate)
        run(host=arguments.host, port=arguments.port, open_browser=False)
        return
    try:
        if arguments.server:
            manage_server(arguments.server, host=arguments.host, port=arguments.port)
            return
        path = document_path(arguments.source) if arguments.source else None
        browser = next((found for name in ("chromium", "chromium-browser", "google-chrome") if (found := shutil.which(name))), None)
        if not browser:
            raise RuntimeError("Für das App-Fenster bitte Chromium oder Google Chrome installieren.")
        ensure_server()
        parameters = {}
        if path and Path(path).is_absolute():
            sys.path.insert(0, str(SRC))
            from material_ui.qmd_imports import stage_import

            parameters["import"] = stage_import(Path(path))
        elif path:
            parameters["path"] = path
        # Die Fensterphase läuft unter dem Startup-Lock: Ein frisch gestartetes
        # Fenster meldet sich erst nach dem Laden per Herzschlag. Wartet der
        # Starter die Registrierung ab, bevor er den Lock freigibt, entscheiden
        # zeitgleich gestartete Starter nacheinander, und mehrfach gewählte
        # Dateien öffnen als Tabs im selben Fenster statt in mehreren Fenstern.
        with (state_home() / "startup.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            status = server_status()
            if status is not None and status.get("windows"):
                if not parameters:
                    raise_app_windows()
                    return
                try:
                    if forward_open_request(parameters):
                        raise_app_windows()
                        return
                except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError, OSError):
                    pass  # Weiterleitung ist best effort: ohne sie öffnet unten ein neues Fenster.
            url = BASE_URL + "/" + ("?" + urllib.parse.urlencode(parameters) if parameters else "")
            profile = state_home() / "browser"   # nicht im Daten-Ordner material-ui/, der Plugins und Marketplace-Katalog enthaelt
            log_path = state_home() / "browser.log"
            with log_path.open("a") as log:
                command = [browser, f"--app={url}", f"--class={APP_ID}", f"--user-data-dir={profile}", "--start-maximized", "--no-first-run", "--no-default-browser-check", "--lang=de-DE"]
                if os.environ.get("XDG_SESSION_TYPE") == "wayland" and os.environ.get("DISPLAY"):
                    command.append("--ozone-platform=x11")
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    start_new_session=True,
                )
            try:
                returncode = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                returncode = 0
            if returncode:
                raise RuntimeError(f"Das App-Fenster konnte nicht starten (Status {returncode}). Details: {log_path}")
            wait_for_window_registration()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "Material UI", str(error)], check=False)
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
