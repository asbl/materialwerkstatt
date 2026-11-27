from __future__ import annotations

from pathlib import Path
import logging

from material_core.state import shared_file
from material_ui.errors import PluginConflict
from material_ui.plugins.context import PluginContext, load_plugin_module
from material_ui.plugins.manifest import PluginManifest, dependency_matches, discover_manifests
from material_ui.plugins.paths import plugin_search_paths, project_plugin_paths
from material_ui.plugins.storage import PluginEnabledStore
from material_ui.plugins.versions import parse_version, satisfies
from material_ui.protocol import API_VERSION


class PluginHost:
    """Entdeckt Plugins, hält Manifeste und lädt aktivierte Plugins mit Fehlerisolation."""

    def __init__(self, runtime, config, search_paths: list[tuple[Path, str]] | None = None) -> None:
        self.runtime = runtime
        self.config = config
        self.enabled_store = PluginEnabledStore(shared_file(config.root, "plugins.json"))
        self.manifests: dict[str, PluginManifest] = {}
        self.contexts: dict[str, PluginContext] = {}
        self.load_errors: dict[str, str] = {}
        self.states: dict[str, str] = {}
        self.services: dict[str, tuple[str, object]] = {}  # Interface-Name -> (Plugin-ID, Objekt)
        self.extra_search_paths: list[tuple[Path, str]] = [*project_plugin_paths(config.root), *(search_paths or [])]
        self.closed = False
        for manifest, error in discover_manifests(tuple(self.extra_search_paths)):
            if manifest is not None:
                self.manifests[manifest.id] = manifest
                self.states[manifest.id] = "disabled"
            elif error is not None:
                self.load_errors[f"unbenannt-{len(self.load_errors)}"] = error

    def is_enabled(self, manifest: PluginManifest) -> bool:
        return self.enabled_store.is_enabled(manifest.id, default=manifest.active_by_default)

    def state_dir(self, manifest: PluginManifest) -> Path:
        return self.config.root / ".material-ui" / "plugins" / manifest.id

    def dependents_of(self, plugin_id: str) -> list[str]:
        """IDs aktivierter Plugins, die von plugin_id abhängen (ID oder @interface)."""
        installed = self.installed_manifests()
        manifest = installed.get(plugin_id)
        if manifest is None:
            return []
        return sorted(
            other.id for other in installed.values()
            if other.id != plugin_id and self.is_enabled(other)
            and any(dependency_matches(target, manifest)
                    and not any(p.id != plugin_id and self.is_enabled(p)
                                and dependency_matches(target, p)
                                and satisfies(parse_version(p.version), constraint)
                                for p in installed.values())
                    for target, constraint in other.depends_on))

    def require_can_disable(self, plugin_id: str) -> None:
        """Deaktivieren sperren, solange aktivierte Plugins abhängen (409 über PluginConflict)."""
        dependents = self.dependents_of(plugin_id)
        if dependents:
            raise PluginConflict(
                f"„{plugin_id}“ wird noch von folgenden aktivierten Plugins benötigt: {', '.join(dependents)}. "
                "Bitte zuerst diese Plugins deaktivieren.")

    def dependency_state(self, manifest: PluginManifest) -> tuple[str, str] | None:
        """Prüft dependsOn gegen die bekannten Manifeste: ("missing-dependency"|"blocked", Meldung)."""
        missing = [target for target, _c in manifest.depends_on
                   if not any(dependency_matches(target, other) for other in self.manifests.values())]
        if missing:
            return "missing-dependency", "Nicht installiert: " + ", ".join(missing)
        problems = []
        for target, constraint in manifest.depends_on:
            providers = [other for other in self.manifests.values() if dependency_matches(target, other)]
            available = [p for p in providers if self.is_enabled(p)
                         and satisfies(parse_version(p.version), constraint)
                         and self.states.get(p.id) == "loaded"]
            if not available:
                details = ", ".join(
                    f"{p.id} {p.version}: " + (self.states.get(p.id, "nicht geladen")
                                              if self.is_enabled(p) else "deaktiviert")
                    for p in providers)
                problems.append(f"Kein geladener Anbieter für „{target}“ ({constraint}); {details}")
        if problems:
            return "blocked", "; ".join(problems)
        return None

    def _ordered_manifests(self) -> tuple[list[PluginManifest], set[str]]:
        """Topologische Reihenfolge nach dependsOn; Zyklus-Mitglieder als zweite Menge."""
        ids = set(self.manifests)
        edges = {}
        for pid, manifest in self.manifests.items():
            providers = set()
            for target, _c in manifest.depends_on:
                if target.startswith("@"):
                    iface = target[1:]
                    providers.update(other.id for other in self.manifests.values() if iface in other.provides)
                elif target in ids:
                    providers.add(target)
            edges[pid] = providers - {pid}
        ordered: list[PluginManifest] = []
        state = {pid: 0 for pid in ids}  # 0=unbesucht, 1=aktiv, 2=fertig
        cyclic: set[str] = set()
        stack: list[str] = []

        def visit(pid: str) -> None:
            state[pid] = 1
            stack.append(pid)
            for nxt in sorted(edges.get(pid, ())):
                if state.get(nxt) == 1:
                    cyclic.update(stack[stack.index(nxt):])
                elif state.get(nxt) == 0:
                    visit(nxt)
            stack.pop()
            state[pid] = 2
            ordered.append(self.manifests[pid])  # Zyklische Mitglieder landen auch in der Liste (load() markiert sie)

        for pid in sorted(ids):
            if state[pid] == 0:
                visit(pid)
        # Post-Order: Abhängigkeiten stehen bereits vor ihren Nutzern.
        return ordered, cyclic

    def refresh(self) -> list[str]:
        """Neu hinzugekommene Manifeste entdecken (z. B. nach Marketplace-Installation)."""
        added: list[str] = []
        for manifest, error in discover_manifests(tuple(self.extra_search_paths)):
            if manifest is not None and manifest.id not in self.manifests:
                self.manifests[manifest.id] = manifest
                self.states[manifest.id] = "restart-pending" if self.is_enabled(manifest) else "disabled"
                added.append(manifest.id)
            elif error is not None:
                self.load_errors.setdefault(f"unbenannt-{len(self.load_errors)}", error)
        return added

    def installed_manifests(self) -> dict[str, PluginManifest]:
        return {m.id: m for m, _ in discover_manifests(tuple(self.extra_search_paths)) if m is not None}

    def installed_status(self, manifest: PluginManifest) -> str:
        current = self.manifests.get(manifest.id)
        if current is None or current != manifest:
            return "restart-pending"
        return self.states.get(manifest.id, "disabled")

    def forget(self, plugin_id: str) -> None:
        """Deinstalliertes Plugin aus dem Host entfernen (wirkt vollständig nach Neustart)."""
        self.manifests.pop(plugin_id, None)
        self.states.pop(plugin_id, None)
        self.load_errors.pop(plugin_id, None)

    def load(self) -> None:
        """Importiert und registriert alle aktivierten, kompatiblen Plugins (Abhängigkeiten zuerst)."""
        pending = []
        for manifest in self.manifests.values():
            if manifest.min_app_api is not None and manifest.min_app_api > API_VERSION:
                self.states[manifest.id] = "incompatible"
                self.load_errors[manifest.id] = (
                    f"Das Plugin benötigt mindestens Material-UI-API {manifest.min_app_api}, "
                    f"der Server bietet {API_VERSION}. Bitte den Server aktualisieren.")
            elif not self.is_enabled(manifest):
                self.states[manifest.id] = "disabled"
            else:
                self.states[manifest.id] = "enabled"
                pending.append(manifest)
        # A consumer becomes ready only after one suitable provider actually loaded.
        # This also permits a working alternative to a failed interface provider.
        while pending:
            ready = next((m for m in pending if self.dependency_state(m) is None), None)
            if ready is None:
                _, cyclic = self._ordered_manifests()
                for m in pending:
                    state, message = self.dependency_state(m)
                    if m.id in cyclic:
                        state, message = "error", "Zyklische Plugin-Abhängigkeit; bitte dependsOn korrigieren."
                    self.states[m.id] = state
                    self.load_errors[m.id] = message
                break
            manifest = ready
            pending.remove(manifest)
            if manifest.python_entry is None and manifest.js_entry is None:
                self.states[manifest.id] = "error"
                self.load_errors[manifest.id] = "Das Plugin deklariert weder Python- noch Frontend-Einstieg."
                continue
            if manifest.python_entry is None:
                # Reines Frontend-Plugin: kein Python-Kontext nötig, Assets bleiben ladbar.
                self.states[manifest.id] = "loaded"
                continue
            context = None
            try:
                module = load_plugin_module(manifest)
                register = getattr(module, manifest.python_entry)
                context = self.contexts.get(manifest.id) or PluginContext(
                    manifest, runtime=self.runtime, state_dir=self.state_dir(manifest), host=self)
                register(context)
            except ModuleNotFoundError as error:
                self.states[manifest.id] = "missing-dependency"
                self.load_errors[manifest.id] = (
                    f"Fehlende Abhängigkeit: {error.name}. "
                    f"Bitte das zugehörige Extra installieren (z. B. pip install -e '.[{manifest.id}]').")
                self._rollback_registration(manifest.id, context)
                continue
            except Exception as error:  # noqa: BLE001 - Fehler eines Plugins bricht den Kern nicht ab.
                self.states[manifest.id] = "error"
                self.load_errors[manifest.id] = f"{type(error).__name__}: {error}"
                self._rollback_registration(manifest.id, context)
                continue
            self.contexts[manifest.id] = context
            self.states[manifest.id] = "loaded"

    def _rollback_registration(self, plugin_id: str, context: PluginContext | None) -> None:
        self.contexts.pop(plugin_id, None)
        for name, (owner, _obj) in list(self.services.items()):
            if owner == plugin_id:
                del self.services[name]
        if context is not None:
            try:
                context.close()
            except Exception:
                logging.getLogger(__name__).exception("Plugin %s konnte nicht vollständig aufgeräumt werden", plugin_id)

    def register_service(self, manifest: PluginManifest, name: str, obj: object) -> None:
        """Registriert ein Plugin-Interface (provides); Doppelbelegung ist ein Fehler."""
        if name not in manifest.provides:
            raise ValueError(f"Plugin {manifest.id} darf das Interface {name!r} nicht registrieren (fehlt in provides).")
        existing = self.services.get(name)
        if existing is not None and existing[0] != manifest.id:
            raise ValueError(f"Interface {name!r} ist bereits von Plugin {existing[0]} belegt.")
        self.services[name] = (manifest.id, obj)

    def service(self, name: str) -> object:
        entry = self.services.get(name)
        if entry is None:
            raise LookupError(f"Kein geladenes Plugin stellt das Interface @{name} bereit.")
        plugin_id, obj = entry
        if self.states.get(plugin_id) != "loaded":
            raise LookupError(f"Der Anbieter für @{name} ist nicht erfolgreich geladen.")
        # Liegt am Anbieter-Kontext ein aktuelles `<name>_service`-Attribut (z. B. in
        # Tests ausgetauscht), gewinnt dieses vor dem bei register_service übergebenen Objekt.
        context = self.contexts.get(plugin_id)
        if context is not None:
            current = getattr(context, f"{name}_service", None)
            if current is not None:
                return current
        return obj

    def run_start(self) -> None:
        for context in list(self.contexts.values()):
            context.lifecycle.run_start()

    def close(self) -> None:
        self.closed = True
        for context in list(self.contexts.values()):
            context.close()

    def default_search_paths(self) -> list[tuple[Path, str]]:
        return list(plugin_search_paths())

    def problems(self) -> list[str]:
        """Meldungen zu Plugin-Ordnern, die gar nicht erst als Plugin erkannt wurden (z. B. kaputtes Manifest)."""
        return [message for key, message in self.load_errors.items() if key not in self.manifests]

    def payload(self, asset_version: str) -> list[dict]:
        """Statusapi für das Frontend; Assets nur für geladene oder zustandsbehaftete Plugins."""
        entries = []
        for manifest in sorted(self.manifests.values(), key=lambda item: (item.source, item.id)):
            state = self.states.get(manifest.id, "disabled")
            assets_loadable = state == "loaded"
            entry = {
                "id": manifest.id,
                "name": manifest.name,
                "version": manifest.version,
                "source": manifest.source,
                "enabled": self.is_enabled(manifest),
                "status": state,
                "message": self.load_errors.get(manifest.id, ""),
                "capabilities": list(manifest.capabilities),
                "dependsOn": [{"target": target, "constraint": constraint} for target, constraint in manifest.depends_on],
                "provides": list(manifest.provides),
                "hostApis": list(manifest.host_apis),
                "jsUrl": f"/plugins/{manifest.id}/{manifest.js_entry}?v={asset_version}" if assets_loadable and manifest.js_entry else None,
                "cssUrls": [f"/plugins/{manifest.id}/{style}?v={asset_version}" for style in manifest.styles] if assets_loadable else [],
                "iconsHref": f"/plugins/{manifest.id}/{manifest.icons}?v={asset_version}" if assets_loadable and manifest.icons else None,
            }
            entries.append(entry)
        return entries
