"""Plugin-Zustand ausserhalb des Servers, fuer System-Check und Kommandozeile. Nur Standardbibliothek."""
from __future__ import annotations

import shutil

from material_core import workspace
from material_core.state import shared_file
from material_ui.plugins.manifest import PluginManifest, discover_manifests
from material_ui.plugins.paths import project_plugin_paths
from material_ui.plugins.storage import PluginEnabledStore


class PluginUnavailable(RuntimeError):
    """Das Plugin ist aus oder ihm fehlt ein Programm; die Meldung nennt den naechsten Schritt."""


def enabled_manifests() -> list[PluginManifest]:
    """Im Arbeitsbereich aktivierte Plugins (wie sie der Server beim Start laden wuerde)."""
    root = workspace.root()
    store = PluginEnabledStore(shared_file(root, "plugins.json"))
    return [manifest for manifest, _error in discover_manifests(tuple(project_plugin_paths(root)))
            if manifest is not None and store.is_enabled(manifest.id, default=manifest.active_by_default)]


def require(plugin_id: str, *keys: str) -> None:
    """Verlangt ein aktives Plugin und die Programme seiner genannten Anforderungen."""
    manifest = next((item for item in enabled_manifests() if item.id == plugin_id), None)
    if manifest is None:
        raise PluginUnavailable(f"Das Plugin „{plugin_id}“ ist nicht aktiv. Aktivieren: inv plugin-enable {plugin_id}")
    absent = [item.key for item in manifest.system_requirements
              if item.key in keys and not any(shutil.which(name) for name in item.binaries)]
    if absent:
        raise PluginUnavailable(
            f"Dem Plugin „{plugin_id}“ fehlen Programme: {', '.join(absent)}. Installationshinweise: inv doctor")
