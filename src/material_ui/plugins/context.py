from __future__ import annotations

import importlib.util
import sys
import threading
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from flask import Blueprint

from material_ui.jobs import JobRegistry, OperationChannel
from material_ui.plugins.manifest import PluginManifest
from material_ui.plugins.storage import PluginSettings, PluginStorage

PLUGIN_MODULE_PREFIX = "material_ui_plugins."


@dataclass
class PluginJobs:
    """Auftragsfassade: ein exklusiver Ausführungskanal je Plugin über die JobRegistry."""

    registry: JobRegistry
    start_worker: Callable
    channels: dict = field(default_factory=dict)

    def get(self, identifier):
        return self.registry.get(identifier)

    def create(self, *args, **kwargs):
        return self.registry.create(*args, **kwargs)

    def update(self, *args, **kwargs):
        return self.registry.update(*args, **kwargs)

    def retain(self, *args, **kwargs):
        return self.registry.retain(*args, **kwargs)

    def release(self, identifier):
        return self.registry.release(identifier)

    def channel(self, name: str) -> OperationChannel:
        key = name
        if key not in self.channels:
            self.channels[key] = OperationChannel(self.registry, self.start_worker)
        return self.channels[key]

    def close(self) -> None:
        for channel in self.channels.values():
            channel.close()


@dataclass
class PluginLifecycle:
    start_callbacks: list = field(default_factory=list)
    shutdown_callbacks: list = field(default_factory=list)
    started: bool = False

    def on_start(self, callback) -> None:
        if self.started:
            callback()
        else:
            self.start_callbacks.append(callback)

    def run_start(self) -> None:
        self.started = True
        callbacks, self.start_callbacks = self.start_callbacks, []
        for callback in callbacks:
            callback()

    def on_shutdown(self, callback) -> None:
        self.shutdown_callbacks.append(callback)

    def run_shutdown(self) -> None:
        callbacks, self.shutdown_callbacks = self.shutdown_callbacks, []
        errors = []
        for callback in callbacks:
            try:
                callback()
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("Fehler beim Beenden des Plugins", errors)


class PluginUnits:
    """Lesender Einheitenzugriff für Kalender und weitere Plugin-Ansichten."""

    def __init__(self, service):
        self._service = service

    def _unit_service(self):
        return self._service

    def scheduled(self):
        service = self._unit_service()
        return service.scheduled_units() if service is not None else []


class PluginWorkers:
    """Shutdown-Signal und verwalteter Workerstart statt vollständiger Runtime."""

    def __init__(self, runtime):
        self.closing = runtime.closing
        self.start_worker = runtime.start_worker


class PluginIndex:
    """Index-Provider-Fassade: Plugins speisen zusätzliche Einträge in /api/qmds ein."""

    def __init__(self, extras):
        self._extras = extras

    def register(self, provider, invalidator=None) -> Callable[[], None]:
        return self._extras.register(provider, invalidator)

    def invalidate(self) -> None:
        self._extras.invalidate()


class _ServiceAccessor:
    """`ctx.service`: aufrufbar für Interfaces anderer Plugins, sonst der eigene Dienst des Plugins.

    Viele Plugins setzen `ctx.service = <eigener Dienst>`. Damit das den Interface-Zugriff
    `ctx.service("chat")` nicht überdeckt (und umgekehrt), bleibt `ctx.service` immer dieser
    Zugriffsobjekt: Aufruf → Dienst eines anderen Plugins, Attribute → eigener Dienst.
    """

    __slots__ = ("_context", "_own")

    def __init__(self, context, own=None):
        object.__setattr__(self, "_context", context)
        object.__setattr__(self, "_own", own)

    def __call__(self, name: str):
        return self._context._plugin_host().service(name)

    def _target(self):
        own = object.__getattribute__(self, "_own")
        if own is None:
            raise AttributeError("Das Plugin hat keinen eigenen Dienst (ctx.service) gesetzt.")
        return own

    def __getattr__(self, name):
        return getattr(self._target(), name)

    def __setattr__(self, name, value):
        setattr(self._target(), name, value)

    def __delattr__(self, name):
        delattr(self._target(), name)

    def __repr__(self):
        return f"<ctx.service {object.__getattribute__(self, '_own')!r}>"


class PluginContext:
    """Versionierte Fassade, über die ein Plugin auf Host-Dienste zugreift."""

    def __init__(self, manifest: PluginManifest, *, runtime, state_dir: Path, host=None) -> None:
        self.manifest = manifest
        self._host = host
        # runtime/config bleiben vorerst für ältere Plugins verfügbar (keine Sandbox);
        # neue Plugins nutzen die Fassaden workers/units/jobs/lifecycle; Kalenderquellen laufen
        # über das Interface @calendar des Kalender-Plugins (ctx.service("calendar")).
        self.runtime = runtime
        self.config = runtime.config
        from material_ui.plugins.ports import (PluginDocuments, PluginProcesses, PluginBuilds,
                                               PluginRender, PluginSearch, PluginWindows)
        # Dienste sind beim Laden aus Tests oder Werkzeugen nicht zwingend verdrahtet.
        services = getattr(runtime, "services", None)
        self.api_version = 1
        self.documents = PluginDocuments(runtime.config, runtime.documents, getattr(services, "documents", None))
        self.processes = PluginProcesses(runtime.processes)
        self.builds = PluginBuilds(getattr(services, "builds", None))
        self.render = PluginRender(runtime.config, getattr(services, "render", None))
        self.search = PluginSearch(getattr(services, "search", None))
        self.windows = PluginWindows(getattr(services, "windows", None))
        self.unit_service = getattr(services, "units", None)
        self.course_application = runtime.course_application
        self.storage = PluginStorage(state_dir)
        self.settings = PluginSettings(self.storage)
        self.jobs = PluginJobs(runtime.jobs, runtime.start_worker)
        self.lifecycle = PluginLifecycle()
        self.blueprints: list[Blueprint] = []
        self.workers = PluginWorkers(runtime)
        self.units = PluginUnits(self.unit_service)
        from material_ui.index_extras import IndexExtras
        extras = services.index_extras if services is not None and hasattr(services, "index_extras") else IndexExtras()
        self.index = PluginIndex(extras)
        self.lock = threading.RLock()
        self._service_accessor = _ServiceAccessor(self)

    def register_routes(self, blueprint: Blueprint) -> None:
        """Registriert den Blueprint unverändert; Plugins tragen volle Routenpfade selbst.

        Ohne url_prefix gelten die Blueprint-Regeln direkt; die Pfade unter
        /api/plugins/<id>/… wählt das Plugin selbst (vgl. Kurs-Routen unter /api/kurse/…).
        """
        with self.lock:
            self.blueprints.append(blueprint)

    def _plugin_host(self):
        host = self._host or getattr(self.runtime, "plugins", None)
        if host is None:
            raise RuntimeError("Plugin-Host ist nicht verfügbar.")
        return host

    def register_service(self, name: str, obj) -> None:
        """Stellt ein in `provides` deklariertes Interface anderen Plugins zur Verfügung."""
        self._plugin_host().register_service(self.manifest, name, obj)

    @property
    def service(self):
        """`ctx.service("name")` liefert das Interface-Objekt eines anderen Plugins (`provides`);
        `ctx.service = <Dienst>` hinterlegt den eigenen Dienst, dessen Attribute über `ctx.service.…`
        erreichbar bleiben. Beides stört sich nicht."""
        return self._service_accessor

    @service.setter
    def service(self, own) -> None:
        # Ein erneutes Zuweisen des Zugriffsobjekts selbst (z. B. ctx.service = ctx.service) ändert nichts.
        if isinstance(own, _ServiceAccessor):
            return
        self._service_accessor = _ServiceAccessor(self, own)

    @property
    def own_service(self):
        """Der vom Plugin selbst gesetzte Dienst (oder None), ohne Zugriffsobjekt."""
        return object.__getattribute__(self._service_accessor, "_own")

    def require_service(self, name: str):
        """Wie `ctx.service(name)`; ausdrücklich für Aufrufer, die nur Interfaces anderer Plugins wollen."""
        return self._plugin_host().service(name)

    def close(self) -> None:
        try:
            self.lifecycle.run_shutdown()
        finally:
            self.jobs.close()


def ensure_plugin_parent() -> None:
    """Legt das Namespace-Paket `material_ui_plugins` an (für direkte Plugin-Imports in Tests)."""
    parent_name = PLUGIN_MODULE_PREFIX.rstrip(".")
    if parent_name not in sys.modules:
        parent = types.ModuleType(parent_name)
        parent.__path__ = [str(Path(__file__).resolve().parent)]
        sys.modules[parent_name] = parent


def load_plugin_module(manifest: PluginManifest):
    """Importiert das Plugin-Paket aus seinem Ordner; Namenskollisionen sind ausgeschlossen."""
    module_name = f"{PLUGIN_MODULE_PREFIX}{manifest.id}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    # Parent-Paket anlegen, damit `from . import submodul` im Plugin-__init__ auflösbar ist.
    ensure_plugin_parent()
    entry = manifest.directory / "__init__.py"
    if not entry.is_file():
        raise ImportError(f"Plugin {manifest.id} hat keine __init__.py.")
    # Ein Paket-Ordner als Wurzel: submodule_search_locations macht relative Importe
    # der Plugin-Module (z. B. `from .service import ...`) moeglich.
    spec = importlib.util.spec_from_file_location(module_name, entry)
    if spec is None or spec.loader is None:
        raise ImportError(f"Plugin {manifest.id} lässt sich nicht als Modul laden.")
    module = importlib.util.module_from_spec(spec)
    module.__path__ = [str(manifest.directory)]  # noqa: B009 - Paketwurzel fuer relative Importe
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module
