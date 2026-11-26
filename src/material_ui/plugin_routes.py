from __future__ import annotations

from flask import Flask, jsonify, request, send_file

from material_ui.errors import InvalidInput
from material_ui.plugins.host import PluginHost
from material_ui.plugins.marketplace import Marketplace
from material_ui.plugins.manifest import asset_path, require_plugin_id


def register_plugin_routes(app: Flask, runtime, host: PluginHost, asset_version: str) -> None:
    @app.get("/api/plugins")
    def list_plugins():
        return jsonify({"plugins": host.payload(asset_version), "problems": host.problems()})

    @app.post("/api/plugins/<plugin_id>/enabled")
    def set_plugin_enabled(plugin_id):
        require_plugin_id(plugin_id)
        with Marketplace(runtime.config.root).operation_lock():
            if plugin_id not in host.installed_manifests():
                raise InvalidInput("Unbekanntes Plugin.")
            data = request.get_json(force=True)
            enabled = data.get("enabled")
            if not isinstance(enabled, bool):
                raise InvalidInput("enabled muss true oder false sein.")
            if not enabled:
                host.require_can_disable(plugin_id)
            host.enabled_store.set_enabled(plugin_id, enabled)
        return jsonify({"ok": True, "enabled": enabled, "restartRequired": True,
                        "message": "Der Stand wird erst nach einem Serverneustart wirksam."})

    @app.get("/plugins/<plugin_id>/<path:filename>")
    def plugin_asset(plugin_id, filename):
        manifest = host.manifests.get(require_plugin_id(plugin_id))
        # Nicht geladene Plugins (deaktiviert, Fehler, inkompatibel) liefern keine Assets aus.
        if manifest is None or host.states.get(plugin_id) != "loaded":
            raise InvalidInput("Plugin steht nicht zur Verfügung.")
        candidate = asset_path(manifest, filename)
        if candidate is None or not candidate.is_file():
            raise InvalidInput("Datei ist nicht Teil des Plugin-Manifests.")
        return send_file(candidate)

    for context in host.contexts.values():
        for blueprint in context.blueprints:
            app.register_blueprint(blueprint)
