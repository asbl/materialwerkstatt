from __future__ import annotations

from flask import Flask, jsonify, request

from material_ui.errors import InvalidInput, MarketplaceUnavailable
from material_ui.plugins.host import PluginHost
from material_ui.plugins.manifest import require_plugin_id
from material_ui.plugins.marketplace import Marketplace, scan_catalog
from material_ui.plugins.versions import parse_version


CATALOG_FRESH_SECONDS = 600


def register_marketplace_routes(app: Flask, runtime, host: PluginHost, asset_version: str) -> None:
    """Paketmanager-API: Katalog-Übersicht, Installieren, Deinstallieren, Aktualisieren."""

    def marketplace() -> Marketplace:
        return Marketplace(runtime.config.root)

    @app.get("/api/marketplace")
    def marketplace_overview():
        mp = marketplace()
        with mp.operation_lock():
            return overview(mp)

    def overview(mp):
        try:
            # Die Übersicht wird nach jeder Aktion neu geladen; ein git pull unter der globalen
            # Sperre nur, wenn der Katalog fehlt oder älter als die Frist ist ("refresh" erzwingt ihn).
            catalog, info = mp._catalog(refresh=not mp.catalog_is_fresh(CATALOG_FRESH_SECONDS))
        except MarketplaceUnavailable:
            info = {**mp._cached_info(), "warning": "Katalog nicht erreichbar; Cache-Stand wird angezeigt."}
            catalog = scan_catalog(mp.catalog_root, info.get("commit", ""), [])
        installed = host.installed_manifests()
        lock = mp.lock.plugins()
        warnings = []
        for plugin_id, pinned in lock.items():
            manifest = installed.get(plugin_id)
            expected = pinned.get("version")
            actual = manifest.version if manifest else None
            if expected != actual:
                warnings.append(
                    f"Plugin {plugin_id}: Projekt erwartet {expected}, global installiert ist "
                    f"{actual or 'keine Version'}. Die Installation kann in einem anderen Projekt geändert worden sein.")
        warnings.extend(f"Plugin-Ordner nicht ladbar: {message}" for message in host.problems())
        if warnings:
            info = {**info, "warning": " ".join(filter(None, [info.get("warning"), *warnings]))}
        entries = []
        for plugin_id in sorted(set(catalog) | set(installed)):
            manifest = installed.get(plugin_id)
            catalog_entries = catalog.get(plugin_id, [])
            newest = max((entry.version for entry in catalog_entries), default=None)
            latest_manifest = max(catalog_entries, key=lambda e: e.version).manifest if catalog_entries else None
            installed_version = parse_version(manifest.version) if manifest is not None else None
            entries.append({
                "id": plugin_id,
                "name": manifest.name if manifest else (latest_manifest.name if latest_manifest else plugin_id),
                "description": latest_manifest and next(
                    (e.description for e in reversed(catalog_entries) if e.description), "") or "",
                "installed": manifest is not None,
                "source": manifest.source if manifest else None,
                "installedVersion": manifest.version if manifest else None,
                "status": host.installed_status(manifest) if manifest else None,
                "loadedVersion": host.manifests[plugin_id].version
                    if host.states.get(plugin_id) == "loaded" and plugin_id in host.manifests else None,
                "enabled": host.is_enabled(manifest) if manifest else False,
                "message": host.load_errors.get(plugin_id, "") if manifest else "",
                "lock": lock.get(plugin_id),
                "availableVersion": str(newest) if newest else None,
                "updateAvailable": bool(
                    manifest is not None and manifest.source != "builtin"
                    and newest is not None and installed_version is not None and newest > installed_version),
                "capabilities": list((manifest or latest_manifest).capabilities),
                "dependsOn": [{"target": t, "constraint": c} for t, c in (manifest or latest_manifest).depends_on],
                "provides": list((manifest or latest_manifest).provides),
            })
        return jsonify({"catalog": info, "plugins": entries})

    @app.post("/api/marketplace/refresh")
    def marketplace_refresh():
        return jsonify({"catalog": marketplace().refresh()})

    @app.post("/api/marketplace/install")
    def marketplace_install():
        data = request.get_json(force=True)
        plugin_id = data.get("id")
        if not isinstance(plugin_id, str):
            raise InvalidInput("id muss eine Zeichenkette sein.")
        version = data.get("version", "*")
        if not isinstance(version, str):
            raise InvalidInput("version muss eine Zeichenkette sein.")
        result = marketplace().install(require_plugin_id(plugin_id), version)
        host.refresh()
        return jsonify(result)

    @app.post("/api/marketplace/uninstall")
    def marketplace_uninstall():
        data = request.get_json(force=True)
        plugin_id = data.get("id")
        if not isinstance(plugin_id, str):
            raise InvalidInput("id muss eine Zeichenkette sein.")
        purge = data.get("purge", False)
        force = data.get("force", False)
        if not isinstance(purge, bool) or not isinstance(force, bool):
            raise InvalidInput("purge und force müssen boolesch sein.")
        result = marketplace().uninstall(require_plugin_id(plugin_id), purge=purge, force=force)
        host.forget(plugin_id)
        return jsonify(result)

    @app.post("/api/marketplace/update")
    def marketplace_update():
        data = request.get_json(force=True)
        target = data.get("id", "all")
        if not isinstance(target, str):
            raise InvalidInput("id muss eine Zeichenkette sein.")
        result = marketplace().update(target)
        host.refresh()
        return jsonify(result)
