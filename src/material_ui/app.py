from __future__ import annotations

import weakref
import os
import threading
import webbrowser
from pathlib import Path

from flask import Flask, url_for

from material_core.dotenv import load_dotenv_file
from material_ui.config import AppConfig
from material_ui.desktop import application_version
from material_ui.runtime import RuntimeState, current_runtime
from material_ui.services import ApplicationServices
from material_ui.http import configure_http
from material_ui.document_routes import register_document_routes
from material_ui.server_routes import register_server_routes
from material_ui.job_routes import register_job_routes
from material_ui.qmd_import_routes import register_qmd_import_routes
from material_ui.folder_routes import register_folder_routes
from material_ui.tag_routes import register_tag_routes
from material_ui.unit_routes import register_unit_routes
from material_ui.deck_routes import register_deck_routes
from material_ui.worksheet_routes import register_worksheet_routes
from material_ui.slides_routes import register_slides_routes
from material_ui.window_routes import register_window_routes
from material_ui.settings_routes import register_settings_routes
from material_ui.plugins.host import PluginHost
from material_ui.plugin_routes import register_plugin_routes
from material_ui.marketplace_routes import register_marketplace_routes
from material_core import workspace


ROOT = workspace.root()


load_dotenv_file(ROOT / ".env", os.environ)

QUARTO = os.environ.get("QUARTO", "quarto")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
CODEX_MODEL = os.environ.get("CODEX_MODEL", "gpt-6.1-sol")


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    return default if raw is None else tuple(item.strip() for item in raw.split(",") if item.strip())


CLAUDE_MODELS = _env_list("CLAUDE_MODELS", ("sonnet", "opus", "haiku"))
CODEX_MODELS = _env_list("CODEX_MODELS", ())
CLAUDE_EFFORT = os.environ.get("CLAUDE_EFFORT", "medium").strip().lower() or "medium"
VIBE_BIN = os.environ.get("VIBE_BIN", "vibe")
MISTRAL_ADMIN_API_KEY = os.environ.get("MISTRAL_ADMIN_API_KEY", "")
CHAT_ALLOW_UNSANDBOXED = os.environ.get("MATERIAL_UI_CHAT_ALLOW_UNSANDBOXED", "").strip().lower() in {"1", "true", "yes", "ja", "on"}
MAX_UPLOAD_BYTES = 24 * 1024 * 1024
KURS_PREVIEW_PORT = 8767


def initialize_runtime(runtime, config=None):
    if runtime.services is None:
        runtime.config = config or runtime.config or AppConfig(
            ROOT, quarto=QUARTO, preview_port=KURS_PREVIEW_PORT,
            claude_bin=CLAUDE_BIN, codex_bin=CODEX_BIN, vibe_bin=VIBE_BIN,
            codex_model=CODEX_MODEL,
            mistral_admin_api_key=MISTRAL_ADMIN_API_KEY,
            chat_allow_unsandboxed=CHAT_ALLOW_UNSANDBOXED,
            claude_models=CLAUDE_MODELS,
            claude_effort=CLAUDE_EFFORT,
            codex_models=CODEX_MODELS,
        )
        runtime.jobs.configure_persistence(runtime.config.root / ".material-ui" / "jobs.json")
        runtime.services = ApplicationServices(runtime, runtime.config)
    elif config is not None and config != runtime.config:
        raise ValueError("Der Anwendungszustand gehört bereits zu einer anderen Konfiguration.")
    return runtime.services


def services():
    return initialize_runtime(current_runtime())


def create_app(runtime: RuntimeState | None = None, config: AppConfig | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.extensions["material_runtime"] = runtime if runtime is not None else RuntimeState()
    initialize_runtime(app.extensions["material_runtime"], config)
    if runtime is None:
        weakref.finalize(app, cleanup_runtime, app.extensions["material_runtime"])
    configure_http(app, MAX_UPLOAD_BYTES)
    desktop_version = application_version()
    app.config["MATERIAL_ASSET_VERSION"] = desktop_version

    @app.context_processor
    def asset_context():
        def asset_url(filename):
            return url_for("static", filename=filename, v=desktop_version)
        # Die Importmap aendert sich nicht zur Laufzeit; rglob ueber static/ nur einmal pro App.
        imports = app.extensions.get("material_module_imports")
        if imports is None:
            static_root = Path(__file__).parent / "static"
            imports = {"imports": {url_for("static", filename=path.relative_to(static_root).as_posix()):
                                   asset_url(path.relative_to(static_root).as_posix())
                                   for path in static_root.rglob("*.js")}}
            app.extensions["material_module_imports"] = imports
        return {"asset_url": asset_url, "module_imports": imports}

    runtime = app.extensions["material_runtime"]
    register_server_routes(app, runtime, desktop_version)
    register_job_routes(app, runtime)
    register_qmd_import_routes(app, runtime)
    register_folder_routes(app, runtime)
    register_tag_routes(app, runtime)
    register_document_routes(app, runtime, MAX_UPLOAD_BYTES)
    register_unit_routes(app, runtime)
    register_deck_routes(app, runtime)
    register_worksheet_routes(app, runtime)
    register_slides_routes(app, runtime)
    register_window_routes(app, runtime)
    register_settings_routes(app, runtime)
    # Plugin-Host ist wie die Services singleton pro Runtime: mehrere create_app-Aufrufe
    # (z. B. Tests) teilen sich Kontexte und Dienste, Blueprints werden je App registriert.
    if runtime.plugins is None:
        plugins = PluginHost(runtime, runtime.config)
        runtime.plugins = plugins
        plugins.load()
        plugins.run_start()
    else:
        plugins = runtime.plugins
    register_plugin_routes(app, runtime, plugins, desktop_version)
    register_marketplace_routes(app, runtime, plugins, desktop_version)
    return app


def warm_index(runtime) -> None:
    """Index direkt nach dem Serverstart im Hintergrund aufbauen.

    Nach einem Neustart sind alle Caches kalt; der erste /api/qmds-Aufruf zahlt
    sonst den kompletten Aufbau allein (frueher >15 s, damit clientseitiges
    Zeitlimit). Der TTLCache serialisiert konkurrierende Aufrufe ueber sein
    Lock, ein frueher Browser-Request wartet also auf diesen Warmup.
    """
    try:
        from material_ui.index_payload import qmds_payload
        services = runtime.services
        if services is not None:
            qmds_payload(runtime.config, services.documents)
    except Exception:
        import traceback
        traceback.print_exc()


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True, debug: bool = False) -> None:
    app = create_app()
    if host not in {"0.0.0.0", "::"}:
        app.config["TRUSTED_HOSTS"].append(host)
    url = f"http://{host}:{port}"
    runtime = app.extensions["material_runtime"]
    runtime.start_worker(warm_index, (runtime,))
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        # threaded=True: eine laufende Chat-Antwort (bis zu CliChatProvider.timeout_seconds)
        # oder /api/jobs/stream darf nicht den gesamten Server fuer alle anderen Anfragen blockieren.
        app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)
    finally:
        cleanup_runtime(app.extensions["material_runtime"])


def cleanup_runtime(runtime) -> None:
    runtime.close()
