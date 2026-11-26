from __future__ import annotations

import sys
import io
import json
import urllib.error
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_ui import desktop


def test_desktop_script_starts_without_shadowing_standard_library():
    result = subprocess.run(
        [sys.executable, "-I", str(Path(desktop.__file__).resolve()), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--install" in result.stdout


def test_launcher_mode_with_isolated_python_can_start_and_stop_server(tmp_path):
    # Regression: Der GNOME-Launcher startet `python -I desktop.py` ohne PYTHONPATH
    # und ohne src/ auf sys.path; application_version() (Plugin-Fingerprint) darf
    # dort nicht mit ModuleNotFoundError fehlschlagen.
    import os
    import socket

    desktop_script = Path(desktop.__file__).resolve()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "XDG_STATE_HOME": str(tmp_path),
    }
    start = subprocess.run(
        [sys.executable, "-I", str(desktop_script), "--server", "start", "--port", str(port)],
        capture_output=True, text=True, env=env, timeout=90,
    )
    assert start.returncode == 0, start.stderr
    assert "gestartet" in start.stdout
    stop = subprocess.run(
        [sys.executable, "-I", str(desktop_script), "--server", "stop", "--port", str(port)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert stop.returncode == 0, stop.stderr
    assert "gestoppt" in stop.stdout


def test_document_path_accepts_local_file_uri(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    source = tmp_path / "Mathe üben.qmd"
    source.touch()
    assert desktop.document_path(source.as_uri()) == source.name


def test_document_path_returns_external_path_for_import(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = tmp_path / "outside.qmd"
    source.touch()
    monkeypatch.setattr(desktop, "ROOT", root)
    assert desktop.document_path(str(source)) == str(source)
    (root / "link.qmd").symlink_to(source)
    assert desktop.document_path(str(root / "link.qmd")) == str(source)


def test_document_path_accepts_course_mdx_inside_repository(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    chapter = root / "unterricht" / "kurse" / "demo-kurs" / "chapters" / "001-einstieg.mdx"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("# Einstieg\n", encoding="utf-8")
    monkeypatch.setattr(desktop, "ROOT", root)
    assert desktop.document_path(str(chapter)) == "unterricht/kurse/demo-kurs/chapters/001-einstieg.mdx"
    assert desktop.document_path(chapter.as_uri()) == "unterricht/kurse/demo-kurs/chapters/001-einstieg.mdx"


def test_document_path_rejects_mdx_outside_course_folder(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(desktop, "ROOT", root)
    other = root / "wissen" / "notiz.mdx"
    other.parent.mkdir()
    other.write_text("# Notiz\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Kurse"):
        desktop.document_path(str(other))
    external = tmp_path / "external.mdx"
    external.write_text("# Extern\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Repository"):
        desktop.document_path(str(external))
    missing = root / "unterricht" / "kurse" / "demo-kurs" / "chapters" / "fehlt.mdx"
    with pytest.raises(ValueError, match="Keine MDX-Datei"):
        desktop.document_path(str(missing))


def test_install_registers_launcher_and_mime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    run = Mock()
    monkeypatch.setattr(desktop.subprocess, "run", run)
    desktop.install()
    application = tmp_path / f"applications/{desktop.APP_ID}.desktop"
    content = application.read_text()
    assert " %f\n" in content
    assert f"StartupWMClass={desktop.APP_ID}" in content
    assert "text/x-quarto-markdown" in content
    assert "text/x-mdx" in content
    icon_name = next(line.removeprefix("Icon=") for line in content.splitlines() if line.startswith("Icon="))
    assert icon_name.startswith(f"{desktop.APP_ID}-")
    assert (tmp_path / f"icons/hicolor/scalable/apps/{icon_name}.svg").read_bytes() == (Path(desktop.__file__).parent / "static/favicon.svg").read_bytes()
    assert any(call.args[0][0] == "gtk-update-icon-cache" for call in run.call_args_list)
    default_calls = [call.args[0] for call in run.call_args_list if call.args[0][:3] == ["xdg-mime", "default", application.name]]
    assert default_calls == [
        ["xdg-mime", "default", application.name, "text/x-quarto-markdown"],
        ["xdg-mime", "default", application.name, "text/x-mdx"],
    ]


def test_launcher_passes_encoded_path_to_app_window(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":0")
    desktop.state_home().mkdir()
    source = tmp_path / "Mathe & Üben.qmd"
    source.touch()
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["material-ui", str(source)])
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/chromium")
    ensure_server = Mock()
    monkeypatch.setattr(desktop, "ensure_server", ensure_server)
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: {"windows": 0})
    registration = Mock()
    monkeypatch.setattr(desktop, "wait_for_window_registration", registration)
    popen = Mock()
    popen.return_value.wait.return_value = 0
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    desktop.main()
    ensure_server.assert_called_once()
    registration.assert_called_once()
    command = popen.call_args.args[0]
    assert "--app=http://127.0.0.1:8765/?path=Mathe+%26+%C3%9Cben.qmd" in command
    assert f"--class={desktop.APP_ID}" in command
    assert "--ozone-platform=x11" in command
    assert "--lang=de-DE" in command
    assert "--start-maximized" in command
    assert popen.call_args.kwargs["stderr"] != subprocess.DEVNULL


def test_launcher_stages_external_qmd_for_import(tmp_path, monkeypatch):
    from material_ui.qmd_imports import pending_import

    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    desktop.state_home().mkdir(parents=True)
    source = tmp_path / "external.qmd"
    source.write_text("# Original", encoding="utf-8")
    monkeypatch.setattr(desktop, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["material-ui", str(source)])
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/chromium")
    monkeypatch.setattr(desktop, "ensure_server", Mock())
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: {"windows": 0})
    monkeypatch.setattr(desktop, "REGISTRATION_TIMEOUT", 0.0)
    popen = Mock()
    popen.return_value.wait.return_value = 0
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    desktop.main()
    app_argument = next(value for value in popen.call_args.args[0] if value.startswith("--app="))
    token = app_argument.split("?import=", 1)[1]
    assert pending_import(token)["text"] == "# Original"
    assert not list(root.iterdir())
    assert source.read_text() == "# Original"


def test_browser_failure_is_reported_with_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    desktop.state_home().mkdir()
    monkeypatch.setattr(sys, "argv", ["material-ui"])
    monkeypatch.setattr(desktop, "ensure_server", Mock())
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: {"windows": 0})
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/chromium" if name == "chromium" else None)
    popen = Mock()
    popen.return_value.wait.return_value = 3
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    with pytest.raises(SystemExit):
        desktop.main()
    assert "browser.log" in capsys.readouterr().err


def test_server_readiness_detects_changed_source(monkeypatch):
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: {"version": "old"})
    assert not desktop.server_ready()
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: {"version": desktop.application_version()})
    assert desktop.server_ready()


def test_server_stop_checks_identity_before_terminating(tmp_path, monkeypatch):
    import project_tasks

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    restart = Mock()
    monkeypatch.setattr(project_tasks, "_restart_existing_material_ui", restart)
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: {"root": str(desktop.ROOT)})
    desktop.manage_server("stop")
    restart.assert_called_once_with("127.0.0.1", 8765)
    restart.reset_mock()
    monkeypatch.setattr(desktop, "server_status", Mock(side_effect=RuntimeError("fremder Server")))
    with pytest.raises(RuntimeError, match="fremder"):
        desktop.manage_server("stop")
    restart.assert_not_called()


def test_server_reuses_legacy_ui_only_for_same_repository(monkeypatch):
    from unittest.mock import patch

    unavailable = urllib.error.HTTPError("url", 404, "Not Found", {}, None)
    response = io.BytesIO(json.dumps({"root": str(desktop.ROOT), "qmds": []}).encode())
    with patch.object(desktop.urllib.request, "urlopen", side_effect=[unavailable, response]):
        assert desktop.server_status()["version"] is None
    response = io.BytesIO(json.dumps({"root": str(desktop.ROOT), "qmds": []}).encode())
    with patch.object(desktop.urllib.request, "urlopen", side_effect=[unavailable, response]):
        assert not desktop.server_ready()
    response = io.BytesIO(json.dumps({"root": "/other/repo", "qmds": []}).encode())
    with patch.object(desktop.urllib.request, "urlopen", side_effect=[unavailable, response]):
        with pytest.raises(RuntimeError, match="Repository"):
            desktop.server_ready()


def test_ensure_server_does_not_restart_running_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: {"version": desktop.application_version()})
    stop = Mock()
    monkeypatch.setattr(desktop, "stop_existing_server", stop)
    popen = Mock()
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    desktop.ensure_server()
    popen.assert_not_called()
    stop.assert_not_called()


def test_ensure_server_starts_background_process_and_waits_for_readiness(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(desktop, "server_status", Mock(side_effect=[None, None, {"version": desktop.application_version()}]))
    popen = Mock()
    popen.return_value.poll.return_value = None
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    desktop.ensure_server()
    popen.assert_called_once()
    command = popen.call_args.args[0]
    assert command[1] == "-I"
    assert command[3:] == ["--serve", "--host", "127.0.0.1", "--port", "8765"]
    assert popen.call_args.kwargs["start_new_session"] is True


@pytest.mark.parametrize("version", ["old", None])
def test_ensure_server_restarts_outdated_ui(tmp_path, monkeypatch, version):
    import project_tasks

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(desktop, "server_status", Mock(side_effect=[
        {"version": version}, {"version": desktop.application_version()},
    ]))
    operations = Mock()
    monkeypatch.setattr(project_tasks, "_restart_existing_material_ui", operations.stop)
    monkeypatch.setattr(desktop.subprocess, "Popen", operations.start)
    desktop.ensure_server()
    operations.stop.assert_called_once_with("127.0.0.1", 8765)
    operations.start.assert_called_once()
    assert [call[0] for call in operations.mock_calls] == ["stop", "start"]


def test_ensure_server_rejects_foreign_server(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(desktop, "server_status", Mock(side_effect=RuntimeError("fremder Server")))
    stop = Mock()
    popen = Mock()
    monkeypatch.setattr(desktop, "stop_existing_server", stop)
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    with pytest.raises(RuntimeError, match="fremder"):
        desktop.ensure_server()
    stop.assert_not_called()
    popen.assert_not_called()


def test_launcher_forwards_open_request_to_running_window(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    desktop.state_home().mkdir(parents=True)
    source = tmp_path / "blatt.qmd"
    source.touch()
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["material-ui", str(source)])
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/chromium" if name == "chromium" else None)
    monkeypatch.setattr(desktop, "ensure_server", Mock())
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: {"windows": 1})
    forward = Mock(return_value=True)
    monkeypatch.setattr(desktop, "forward_open_request", forward)
    raise_windows = Mock()
    monkeypatch.setattr(desktop, "raise_app_windows", raise_windows)
    popen = Mock()
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)

    desktop.main()

    forward.assert_called_once_with({"path": "blatt.qmd"})
    raise_windows.assert_called_once()
    popen.assert_not_called()


def test_launcher_falls_back_to_new_window_when_no_window_claims(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    desktop.state_home().mkdir(parents=True)
    source = tmp_path / "blatt.qmd"
    source.touch()
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["material-ui", str(source)])
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/chromium" if name == "chromium" else None)
    monkeypatch.setattr(desktop, "ensure_server", Mock())
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: {"windows": 1})
    monkeypatch.setattr(desktop, "forward_open_request", Mock(return_value=False))
    raise_windows = Mock()
    monkeypatch.setattr(desktop, "raise_app_windows", raise_windows)
    monkeypatch.setattr(desktop, "REGISTRATION_TIMEOUT", 0.0)
    popen = Mock()
    popen.return_value.wait.return_value = 0
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)

    desktop.main()

    raise_windows.assert_not_called()
    assert "--app=http://127.0.0.1:8765/?path=blatt.qmd" in popen.call_args.args[0]


def test_launcher_without_source_never_forwards(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    desktop.state_home().mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["material-ui"])
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/chromium" if name == "chromium" else None)
    monkeypatch.setattr(desktop, "ensure_server", Mock())
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: {"windows": 0})
    monkeypatch.setattr(desktop, "REGISTRATION_TIMEOUT", 0.0)
    forward = Mock()
    monkeypatch.setattr(desktop, "forward_open_request", forward)
    popen = Mock()
    popen.return_value.wait.return_value = 0
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)

    desktop.main()

    forward.assert_not_called()
    assert popen.call_args.args[0][0] == "/usr/bin/chromium"


def test_launcher_without_source_raises_existing_window(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    desktop.state_home().mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["material-ui"])
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/chromium" if name == "chromium" else None)
    monkeypatch.setattr(desktop, "ensure_server", Mock())
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: {"windows": 1})
    raise_windows = Mock()
    monkeypatch.setattr(desktop, "raise_app_windows", raise_windows)
    popen = Mock()
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)

    desktop.main()

    raise_windows.assert_called_once()
    popen.assert_not_called()


def test_window_registration_wait_polls_until_window_appears(monkeypatch):
    monkeypatch.setattr(desktop, "server_status", Mock(side_effect=[{"windows": 0}, {"windows": 1}]))
    desktop.wait_for_window_registration()
    assert desktop.server_status.call_count == 2


def test_forward_open_request_reports_claimed_window(monkeypatch):
    monkeypatch.setattr(desktop, "csrf_token", lambda: "token")
    calls = []

    def request_json(path, payload=None, token=None, method="GET"):
        calls.append((path, method))
        return {"id": 3} if method == "POST" else {"claimed": True}

    monkeypatch.setattr(desktop, "request_json", request_json)
    assert desktop.forward_open_request({"path": "a.qmd"}) is True
    assert calls == [("/api/window/open", "POST"), ("/api/window/open/3", "GET")]


def test_forward_open_request_discards_unclaimed_request(monkeypatch):
    monkeypatch.setattr(desktop, "csrf_token", lambda: "token")
    calls = []

    def request_json(path, payload=None, token=None, method="GET"):
        calls.append((path, method))
        if method == "POST":
            return {"id": 7}
        if path == "/api/window/open/7":
            return {"claimed": False}
        return {"ok": True}

    monkeypatch.setattr(desktop, "request_json", request_json)
    assert desktop.forward_open_request({"path": "a.qmd"}, timeout=0.0) is False
    assert calls[-1] == ("/api/window/open/7", "DELETE")


def test_spawn_restart_helper_starts_detached_restart_process(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "state_home", lambda: tmp_path)
    popen = Mock()
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    desktop.spawn_restart_helper("127.0.0.1", 9002)
    command = popen.call_args.args[0]
    assert command[2].endswith("desktop.py")
    assert command[3:] == ["--server", "restart", "--host", "127.0.0.1", "--port", "9002"]
    assert popen.call_args.kwargs["start_new_session"] is True
    assert popen.call_args.kwargs["cwd"] == desktop.ROOT


def test_ensure_server_spawns_serve_process_with_host_and_port(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "state_home", lambda: tmp_path)
    monkeypatch.setattr(desktop, "server_status", lambda url=desktop.BASE_URL: None)
    monkeypatch.setattr(desktop, "server_ready", lambda url=desktop.BASE_URL: True)
    popen = Mock()
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    desktop.ensure_server("127.0.0.1", 9001)
    command = popen.call_args.args[0]
    assert command[2].endswith("desktop.py")
    assert command[3:] == ["--serve", "--host", "127.0.0.1", "--port", "9001"]


def test_version_includes_design_catalog_and_generator_but_ignores_dependencies(tmp_path, monkeypatch):
    sources = tmp_path / 'src'
    for name in ('material_ui', 'material_core', 'excalideck'):
        (sources / name).mkdir(parents=True)
    script = sources / 'material_ui/desktop.py'
    script.write_text('# stabil\n')
    catalog = sources / 'material_core/template-designs.json'
    catalog.write_text('[{"id": "alt"}]')
    generator = sources / 'excalideck/generator.py'
    generator.write_text('# alt\n')
    monkeypatch.setattr(desktop, '__file__', str(script))
    before = desktop.application_version()
    catalog.write_text('[{"id": "neu"}]')
    after_catalog = desktop.application_version()
    assert before != after_catalog
    generator.write_text('# neu\n')
    after_generator = desktop.application_version()
    assert after_catalog != after_generator
    ignored = sources / 'excalideck/present/node_modules/tool/package.json'
    ignored.parent.mkdir(parents=True)
    ignored.write_text('{}')
    assert desktop.application_version() == after_generator
