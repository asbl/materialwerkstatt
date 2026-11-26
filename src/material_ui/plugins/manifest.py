from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from material_ui.errors import InvalidInput
from material_ui.plugins.paths import plugin_search_paths
from material_ui.plugins.versions import VersionError, validate_constraint

ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")
INTERFACE_KEY_PATTERN = re.compile(r"@[a-z0-9][a-z0-9-]*")   # dependsOn-Ziel für ein Interface
INTERFACE_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")    # provides-Eintrag (ohne @)
KNOWN_CAPABILITIES = frozenset({"network-outbound", "repo-read", "state-write"})
ASSET_SUFFIXES = {".js", ".css", ".svg", ".json", ".html"}


class ManifestError(ValueError):
    def __init__(self, message: str, plugin_id: str = "") -> None:
        super().__init__(message)
        self.plugin_id = plugin_id


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    source: str                     # builtin | user | project
    directory: Path
    min_app_api: int | None
    capabilities: tuple[str, ...]
    python_entry: str | None
    js_entry: str | None
    styles: tuple[str, ...]
    icons: str | None
    modules: tuple[str, ...] = ()   # zusätzliche JS-Module (vom jsEntry importiert)
    depends_on: tuple[tuple[str, str], ...] = ()  # (Ziel: Plugin-ID oder "@interface", kommagetrennte Bedingung)
    provides: tuple[str, ...] = ()                # angebotene Interfaces (ohne @)
    host_apis: tuple[str, ...] = ()               # Frontend-Schnittstellen des Hosts, die das JS-Modul braucht

    def asset_files(self) -> list[tuple[str, Path]]:
        """Nur Manifest-benannte Dateien dürfen über die Asset-Route ausgeliefert werden."""
        assets: list[tuple[str, Path]] = []
        if self.js_entry:
            assets.append((self.js_entry, self.directory / self.js_entry))
        if self.icons:
            assets.append((self.icons, self.directory / self.icons))
        for style in self.styles:
            assets.append((style, self.directory / style))
        for module in self.modules:
            assets.append((module, self.directory / module))
        return assets


def _safe_entry(value, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"Manifest-Feld {field} muss eine nicht leere Zeichenkette sein.")
    if value != Path(value).as_posix() or ".." in Path(value).parts or value.startswith("/"):
        raise ManifestError(f"Manifest-Feld {field} muss ein sicherer relativer Pfad sein.")
    if Path(value).suffix.lower() not in ASSET_SUFFIXES:
        raise ManifestError(f"Manifest-Feld {field} hat einen nicht erlaubten Dateityp.")
    return value


def load_manifest(directory: Path, source: str, *, check_dir_name: bool = True) -> PluginManifest:
    plugin_id = directory.name
    try:
        data = json.loads((directory / "plugin.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestError("plugin.json fehlt.", plugin_id) from None
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"plugin.json ist unlesbar: {error}", plugin_id) from None
    if not isinstance(data, dict):
        raise ManifestError("plugin.json muss ein JSON-Objekt sein.", plugin_id)
    locus = data.get("id", plugin_id)
    if not isinstance(locus, str) or not ID_PATTERN.fullmatch(locus):
        raise ManifestError(f"Ungültige Plugin-ID: {locus!r}", plugin_id)
    if check_dir_name and locus != plugin_id:
        raise ManifestError(f"Plugin-ID {locus!r} passt nicht zum Ordnernamen {plugin_id!r}.", plugin_id)
    name = data.get("name")
    version = data.get("version")
    if not isinstance(name, str) or not name:
        raise ManifestError("Manifest-Feld name fehlt.", plugin_id)
    if not isinstance(version, str) or not version:
        raise ManifestError("Manifest-Feld version fehlt.", plugin_id)
    min_app_api = data.get("minAppApi")
    if min_app_api is not None and not isinstance(min_app_api, int):
        raise ManifestError("Manifest-Feld minAppApi muss eine ganze Zahl sein.", plugin_id)
    capabilities = data.get("capabilities", [])
    if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
        raise ManifestError("Manifest-Feld capabilities muss eine Liste von Zeichenketten sein.", plugin_id)
    unknown = [item for item in capabilities if item not in KNOWN_CAPABILITIES]
    if unknown:
        raise ManifestError(f"Unbekannte Fähigkeiten: {', '.join(unknown)}", plugin_id)
    raw_entry = data.get("pythonEntry")
    if raw_entry is not None and (not isinstance(raw_entry, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw_entry)):
        raise ManifestError("Manifest-Feld pythonEntry muss ein Funktionsname sein.", plugin_id)
    styles = data.get("styles", [])
    if not isinstance(styles, list) or any(not isinstance(item, str) for item in styles):
        raise ManifestError("Manifest-Feld styles muss eine Liste von Zeichenketten sein.", plugin_id)
    js_entry = data.get("jsEntry")
    icons = data.get("icons")
    modules = data.get("modules", [])
    if not isinstance(modules, list) or any(not isinstance(item, str) for item in modules):
        raise ManifestError("Manifest-Feld modules muss eine Liste von Zeichenketten sein.", plugin_id)
    provides = _parse_provides(data.get("provides", []), plugin_id)
    depends_on = _parse_depends_on(data.get("dependsOn", {}), plugin_id, provides)
    host_apis = data.get("hostApis", [])
    if not isinstance(host_apis, list) or any(
        not isinstance(item, str) or not INTERFACE_NAME_PATTERN.fullmatch(item) for item in host_apis
    ):
        raise ManifestError("Manifest-Feld hostApis muss eine Liste von Namen ([a-z0-9-]+) sein.", plugin_id)
    return PluginManifest(
        id=locus,
        name=name,
        version=version,
        source=source,
        directory=directory,
        min_app_api=min_app_api,
        capabilities=tuple(capabilities),
        python_entry=raw_entry,
        js_entry=_safe_entry(js_entry, "jsEntry") if js_entry else None,
        styles=tuple(_safe_entry(style, "styles") for style in styles),
        icons=_safe_entry(icons, "icons") if icons else None,
        modules=tuple(_safe_entry(module, "modules") for module in modules),
        depends_on=tuple(depends_on),
        provides=provides,
        host_apis=tuple(host_apis),
    )


def _parse_provides(raw, plugin_id: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or any(
        not isinstance(item, str) or not INTERFACE_NAME_PATTERN.fullmatch(item) for item in raw
    ):
        raise ManifestError("Manifest-Feld provides muss eine Liste von Interface-Namen ([a-z0-9-]+) sein.", plugin_id)
    return tuple(raw)


def _parse_depends_on(raw, plugin_id: str, provides: tuple[str, ...]) -> list[tuple[str, str]]:
    if not isinstance(raw, dict):
        raise ManifestError("Manifest-Feld dependsOn muss ein Objekt {ziel: bedingung} sein.", plugin_id)
    depends_on: list[tuple[str, str]] = []
    for target, constraint in raw.items():
        if not isinstance(target, str) or not (ID_PATTERN.fullmatch(target) or INTERFACE_KEY_PATTERN.fullmatch(target)):
            raise ManifestError(f"Ungültiges dependsOn-Ziel (Plugin-ID oder @interface erwartet): {target!r}", plugin_id)
        if target == plugin_id or (target.startswith("@") and target[1:] in provides):
            raise ManifestError(f"Plugin darf nicht von sich selbst abhängen: {target!r}", plugin_id)
        parts = [constraint] if isinstance(constraint, str) else constraint
        if not isinstance(parts, list) or not parts or any(not isinstance(part, str) for part in parts):
            raise ManifestError(f"Versionsbedingung für {target!r} muss eine Zeichenkette oder Liste von Zeichenketten sein.", plugin_id)
        for part in parts:
            try:
                validate_constraint(part)
            except VersionError as error:
                raise ManifestError(f"Ungültige Versionsbedingung für {target!r}: {error}", plugin_id) from None
        depends_on.append((target, ",".join(parts)))
    return depends_on


def dependency_matches(target: str, provider: PluginManifest) -> bool:
    """True, wenn provider ein dependsOn-Ziel erfüllt: per Plugin-ID oder per @interface über provides."""
    if target == provider.id:
        return True
    return target.startswith("@") and target[1:] in provider.provides


def discover_manifests(extra_search_paths: tuple[tuple[Path, str], ...] = ()) -> list[tuple[PluginManifest | None, str | None]]:
    """Manifeste aller Suchorte, gleiche IDs bleiben unberücksichtigt (erster Treffer gewinnt)."""
    found_ids: set[str] = set()
    results: list[tuple[PluginManifest | None, str | None]] = []
    # Private Projekt-Plugins gewinnen vor Paket- und Benutzerordner: ein gleichnamiges Benutzer-Plugin
    # (z. B. aus einer frueheren Marketplace-Installation) darf sie nicht stillschweigend verdraengen.
    project = [item for item in extra_search_paths if item[1] == "project"]
    other = [item for item in extra_search_paths if item[1] != "project"]
    for base, source in [*project, *plugin_search_paths(), *other]:
        if not base.is_dir():
            continue
        for directory in sorted(base.iterdir(), key=lambda item: item.name):
            if directory.name in found_ids or not (directory / "plugin.json").is_file():
                continue
            try:
                manifest = load_manifest(directory, source)
            except (ManifestError, OSError) as error:
                results.append((None, str(error)))
                continue
            found_ids.add(manifest.id)
            results.append((manifest, None))
    return results


def asset_path(manifest: PluginManifest, relative: str) -> Path | None:
    """Löst eine angefragte Asset-Datei nur auf, wenn sie im Manifest benannt ist."""
    normalized = Path(relative).as_posix()
    for declared, path in manifest.asset_files():
        if declared == normalized:
            return path
    return None


def require_plugin_id(plugin_id: str) -> str:
    if not ID_PATTERN.fullmatch(plugin_id or ""):
        raise InvalidInput("Ungültige Plugin-ID.")
    return plugin_id
