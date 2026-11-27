from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path

from material_core.state import SHARED_DIR, shared_file
from material_core.filesystem import atomic_write_text
from material_ui.errors import InvalidInput, MarketplaceUnavailable, PluginConflict
from material_ui.plugins.manifest import (
    ManifestError,
    PluginManifest,
    dependency_matches,
    discover_manifests,
    load_manifest,
    require_plugin_id,
)
from material_ui.plugins.paths import plugin_search_paths, project_plugin_paths
from material_ui.plugins.storage import PluginEnabledStore
from material_ui.protocol import API_VERSION
from material_ui.plugins.versions import Version, VersionError, parse_version, satisfies, validate_constraint

CATALOG_REPO_ENV = "MATERIAL_UI_MARKETPLACE_REPO"
# Kein vorgegebener Katalog: Der Marketplace braucht ein git-Repository (SSH-/https-URL oder
# lokaler Pfad), das ueber MATERIAL_UI_MARKETPLACE_REPO (auch in .env) eingestellt wird.
DEFAULT_CATALOG_REPO = ""

_GIT_TIMEOUT_SECONDS = 120


def catalog_repo_url() -> str:
    return os.environ.get(CATALOG_REPO_ENV) or DEFAULT_CATALOG_REPO


def catalog_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return data_home / "material-ui" / "marketplace" / "catalog"


def user_plugin_dir() -> Path:
    for base, source in plugin_search_paths():
        if source == "user":
            return base
    return plugin_search_paths()[-1][0]


def discover_installed(extra_search_paths: tuple[tuple[Path, str], ...] = ()) -> dict[str, PluginManifest]:
    installed: dict[str, PluginManifest] = {}
    for manifest, _error in discover_manifests(extra_search_paths):
        if manifest is not None:
            installed[manifest.id] = manifest
    return installed


def _git(args: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MarketplaceUnavailable(f"git {' '.join(args)} konnte nicht ausgeführt werden: {error}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise MarketplaceUnavailable(f"git {' '.join(args)} fehlgeschlagen: {detail}")
    return result.stdout.strip()


_REFRESH_STAMP = "material-ui-refreshed"


def catalog_age_seconds(dest: Path) -> float | None:
    """Sekunden seit der letzten erfolgreichen Aktualisierung; None, wenn nie aktualisiert."""
    try:
        return max(0.0, time.time() - (dest / ".git" / _REFRESH_STAMP).stat().st_mtime)
    except OSError:
        return None


def _stamp(dest: Path) -> None:
    try:
        (dest / ".git" / _REFRESH_STAMP).touch()
    except OSError:
        pass


def _clone_replacing(url: str, dest: Path) -> None:
    """Klont in ein Nachbarverzeichnis und tauscht erst nach Erfolg; der alte Cache bleibt bei Fehlern erhalten."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=dest.parent, prefix=".catalog-clone-"))
    try:
        target = staging / "catalog"
        _git(["clone", url, str(target)])
        if dest.exists():
            shutil.rmtree(dest)
        target.rename(dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _normalized_url(url: str) -> str:
    """Vergleichsform für Remote-URLs (lokale Pfade aufgelöst, ohne Schrägstrich/.git-Endung)."""
    value = url.strip()
    if value.startswith("file://"):
        value = value[len("file://"):]
    if "://" not in value and not value.startswith("git@"):
        try:
            value = str(Path(value).expanduser().resolve())
        except OSError:
            pass
    return value.rstrip("/").removesuffix(".git")


def refresh_catalog(url: str | None = None, dest: Path | None = None) -> dict:
    """Klonen oder ff-only aktualisieren; bei Netzwerkfehler Cache-Stand mit Warnung liefern.

    Zeigt der vorhandene Klon auf eine andere Katalog-URL, wird neu geklont – der Cache
    gehört dann zu einem anderen Katalog und darf nicht als dessen Inhalt gemeldet werden.
    """
    url = url or catalog_repo_url()
    if not url:
        raise MarketplaceUnavailable(
            f"Kein Plugin-Katalog konfiguriert: {CATALOG_REPO_ENV} auf die URL eines git-Repositorys setzen (z. B. in .env).")
    dest = dest or catalog_dir()
    if (dest / ".git").is_dir():
        try:
            current_url = _git(["remote", "get-url", "origin"], cwd=dest)
        except MarketplaceUnavailable:
            current_url = ""
        if _normalized_url(current_url) != _normalized_url(url):
            _clone_replacing(url, dest)
        else:
            try:
                _git(["pull", "--ff-only"], cwd=dest)
            except MarketplaceUnavailable as error:
                return {"repo": url, "commit": _git(["rev-parse", "HEAD"], cwd=dest),
                        "warning": f"Katalog nicht aktualisierbar ({error}); Cache-Stand wird verwendet."}
    else:
        _clone_replacing(url, dest)
    _stamp(dest)
    return {"repo": url, "commit": _git(["rev-parse", "HEAD"], cwd=dest)}


@dataclass(frozen=True)
class CatalogEntry:
    manifest: PluginManifest
    version: Version
    commit: str
    description: str = ""


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def scan_catalog(catalog_root: Path, commit: str = "",
                 problems: list[str] | None = None) -> dict[str, list[CatalogEntry]]:
    """Liest plugins/<id>/<version>/plugin.json; Manifest-ID/-Version müssen zu den Ordnernamen passen.

    Ohne `problems` bricht ein ungültiger Eintrag den Scan ab (strikt, z. B. für Katalogprüfungen).
    Mit `problems` wird er übersprungen und beschrieben, damit ein einzelnes fremdes Plugin
    nicht den gesamten Marketplace lahmlegt.
    """
    entries: dict[str, list[CatalogEntry]] = {}
    index = _read_json(catalog_root / "index.json").get("plugins", {})
    plugins_root = catalog_root / "plugins"
    if not plugins_root.is_dir():
        return entries
    for plugin_dir in sorted(plugins_root.iterdir()):
        if not plugin_dir.is_dir():
            continue
        for version_dir in sorted(plugin_dir.iterdir()):
            if not version_dir.is_dir() or not (version_dir / "plugin.json").is_file():
                continue
            try:
                manifest = load_manifest(version_dir, "marketplace", check_dir_name=False)
                version = parse_version(manifest.version)
            except (ManifestError, VersionError, OSError) as error:
                message = f"Katalog-Eintrag {plugin_dir.name}/{version_dir.name} ist ungültig: {error}"
                if problems is None:
                    raise MarketplaceUnavailable(message) from None
                problems.append(message)
                continue
            if manifest.id != plugin_dir.name or manifest.version != version_dir.name:
                message = (f"Katalog-Ordner {plugin_dir.name}/{version_dir.name} passt nicht zu "
                           f"Manifest-ID {manifest.id!r} / Version {manifest.version!r}.")
                if problems is None:
                    raise MarketplaceUnavailable(message)
                problems.append(message)
                continue
            info = index.get(manifest.id, {}) if isinstance(index, dict) else {}
            entries.setdefault(manifest.id, []).append(
                CatalogEntry(manifest, version, commit, info.get("description", "") if isinstance(info, dict) else ""))
    return entries


class LockFile:
    """Installierte Marketplace-Pakete: <repo>/.material-ui/plugins.lock.json (id -> version/commit)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        data = _read_json(self.path)
        self.data = {"catalog": data.get("catalog", {}), "plugins": data.get("plugins", {})}

    def plugins(self) -> dict:
        return dict(self.data.get("plugins", {}))

    def record(self, plugin_id: str, version: str, commit: str, source: str = "marketplace") -> None:
        self.data.setdefault("plugins", {})[plugin_id] = {"version": version, "commit": commit, "source": source}
        if commit:
            self.data.setdefault("catalog", {})["commit"] = commit
        self.save()

    def remove(self, plugin_id: str) -> None:
        self.data.get("plugins", {}).pop(plugin_id, None)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(self.data, ensure_ascii=False, indent=2))


@dataclass
class Plan:
    entries: dict[str, CatalogEntry]              # gewählte Katalog-Versionen je Plugin-ID
    kept: dict[str, PluginManifest]               # eingebaute/lokal bleibende Plugins
    actions: list[dict]                           # {id, action: install|upgrade|keep, version, from}
    managed: set[str] = field(default_factory=set)


def _check_cycles(graph: dict[str, set[str]]) -> None:
    active: list[str] = []
    done: set[str] = set()

    def visit(pid):
        if pid in active:
            raise PluginConflict("Zyklische Abhängigkeit: " + " → ".join(active + [pid]))
        if pid in done:
            return
        active.append(pid)
        for dependency in sorted(graph.get(pid, ())):
            visit(dependency)
        active.pop()
        done.add(pid)

    for pid in graph:
        visit(pid)


def _is_dev_install(manifest: PluginManifest) -> bool:
    """Per Symlink eingebundene Entwicklungsinstallation: nie durch Katalogkopien ersetzen."""
    return manifest.source != "builtin" and manifest.directory.is_symlink()


def resolve(catalog: dict[str, list[CatalogEntry]], roots: dict[str, str],
            installed: dict[str, PluginManifest]) -> Plan:
    """Backtracking über den gesamten Bestand, inklusive konkreter Interface-Anbieter.

    Jede Verzweigung besitzt eigene Anforderungen und Kanten. Beim Zurückgehen
    bleiben keine Bedingungen einer verworfenen Paketversion zurück.
    """
    for pid, constraint in roots.items():
        require_plugin_id(pid)
        validate_constraint(constraint)
        if pid not in catalog and pid not in installed:
            raise InvalidInput(f"Unbekanntes Plugin: {pid}")

    def manifest(candidate):
        return candidate.manifest if isinstance(candidate, CatalogEntry) else candidate

    options = {}
    for pid in sorted(set(catalog) | set(installed)):
        current = installed.get(pid)
        if current is not None and (current.source == "builtin" or _is_dev_install(current)):
            options[pid] = [current]
            continue
        all_entries = sorted(catalog.get(pid, ()), key=lambda e: e.version, reverse=True)
        # Versionen, die ein neueres Server-API verlangen, würden nach dem Neustart "inkompatibel" sein.
        entries = [e for e in all_entries
                   if e.manifest.min_app_api is None or e.manifest.min_app_api <= API_VERSION]
        candidates = list(entries)
        if current is not None:
            same = next((e for e in entries if e.manifest.version == current.version), current)
            if same is current:
                candidates.append(current)
        options[pid] = sorted(candidates, key=lambda c: parse_version(manifest(c).version), reverse=True)

    pending = [(None, pid, constraint) for pid, constraint in roots.items()]
    pending += [(None, pid, None) for pid in sorted(installed) if pid not in roots]
    last_error = "Keine kompatible Kombination von Plugin-Versionen gefunden."

    def search(selected, requirements, edges):
        nonlocal last_error
        if not requirements:
            try:
                _check_cycles(edges)
            except PluginConflict as error:
                last_error = str(error)
                return None
            return selected, edges
        owner, target, constraint = requirements[0]
        rest = requirements[1:]
        candidates = []
        for pid, choices in options.items():
            if not target.startswith("@") and pid != target:
                continue
            available = [selected[pid]] if pid in selected else list(choices)
            if constraint is None and pid in installed:
                available.sort(key=lambda c: manifest(c).version != installed[pid].version)
            for candidate in available:
                m = manifest(candidate)
                if dependency_matches(target, m) and (constraint is None or satisfies(parse_version(m.version), constraint)):
                    candidates.append(candidate)
        if target.startswith("@"):
            candidates.sort(key=lambda c: parse_version(manifest(c).version), reverse=True)
        # Prefer an already selected provider; all alternatives remain available.
        candidates.sort(key=lambda c: manifest(c).id not in selected)
        if not candidates:
            last_error = f"Keine Version/kein Anbieter für „{target}“ erfüllt „{constraint}“."
            if target in installed and installed[target].source == "builtin":
                last_error += " Die eingebaute Version kann nicht ersetzt werden."
            elif target in installed and _is_dev_install(installed[target]):
                last_error += " Die per Symlink eingebundene Entwicklungsinstallation wird nicht ersetzt."
        for candidate in candidates:
            m = manifest(candidate)
            next_edges = {pid: set(deps) for pid, deps in edges.items()}
            next_edges.setdefault(m.id, set())
            if owner is not None:
                next_edges.setdefault(owner, set()).add(m.id)
            dependencies = [] if m.id in selected else [(m.id, t, c) for t, c in m.depends_on]
            result = search({**selected, m.id: candidate}, dependencies + rest, next_edges)
            if result is not None:
                return result
        return None

    result = search({}, pending, {})
    if result is None:
        raise PluginConflict(last_error)
    selected, edges = result
    managed = set()

    def include(pid):
        if pid in managed:
            return
        managed.add(pid)
        for dependency in edges.get(pid, ()):
            include(dependency)

    for pid in roots:
        include(pid)
    chosen = {pid: c for pid, c in selected.items() if isinstance(c, CatalogEntry)}
    kept = {pid: c for pid, c in selected.items() if not isinstance(c, CatalogEntry)}
    actions = []
    for pid, candidate in selected.items():
        m = manifest(candidate)
        current = installed.get(pid)
        action = "install" if current is None else ("keep" if current.version == m.version else "upgrade")
        if action != "keep":
            managed.add(pid)
        actions.append({"id": pid, "action": action, "version": m.version,
                        "from": current.version if current is not None and action == "upgrade" else None})
    return Plan(chosen, kept, sorted(actions, key=lambda a: a["id"]), managed)


def serialized(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self.operation_lock():
            return method(self, *args, **kwargs)
    return invoke


@contextmanager
def rollback_paths(paths):
    """Snapshot before mutation; retain backups until code and metadata commit."""
    with ExitStack() as stack:
        backups = []
        for target in dict.fromkeys(paths):
            target.parent.mkdir(parents=True, exist_ok=True)
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory(
                dir=target.parent, prefix=".package-backup-")))
            backup = directory / "original"
            if target.is_dir():
                shutil.copytree(target, backup, symlinks=True)
            elif target.exists():
                shutil.copy2(target, backup)
            backups.append((target, backup))
        try:
            yield
        except BaseException:
            for target, backup in reversed(backups):
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists() or target.is_symlink():
                    target.unlink()
                if backup.exists():
                    backup.rename(target)
            raise


class Marketplace:
    """Paketverwaltung: Katalog (git) + Resolver + Lockfile + Installieren/Deinstallieren."""

    def __init__(self, root: Path, *, user_dir: Path | None = None, catalog_root: Path | None = None,
                 repo_url: str | None = None, enabled_store: PluginEnabledStore | None = None,
                 lock: LockFile | None = None) -> None:
        self.root = Path(root)
        self.user_dir = Path(user_dir) if user_dir is not None else user_plugin_dir()
        self.catalog_root = Path(catalog_root) if catalog_root is not None else catalog_dir()
        self.repo_url = repo_url or catalog_repo_url()
        self.enabled_store = enabled_store or PluginEnabledStore(shared_file(self.root, "plugins.json"))
        self.lock = lock or LockFile(self.root / ".material-ui" / "plugins.lock.json")

    @contextmanager
    def operation_lock(self):
        # Same global code/catalog locks across projects, plus project metadata.
        paths = {self.user_dir.parent / f".{self.user_dir.name}.marketplace.lock",
                 self.catalog_root.parent / f".{self.catalog_root.name}.marketplace.lock",
                 self.root / ".material-ui" / ".marketplace.lock"}
        with ExitStack() as stack:
            for path in sorted(paths, key=lambda p: str(p.resolve())):
                path.parent.mkdir(parents=True, exist_ok=True)
                handle = stack.enter_context(path.open("a+"))
                fcntl.flock(handle, fcntl.LOCK_EX)
            self.lock.data = LockFile(self.lock.path).data
            yield

    @serialized
    def refresh(self) -> dict:
        return refresh_catalog(self.repo_url, self.catalog_root)

    def catalog_is_fresh(self, max_age_seconds: float) -> bool:
        age = catalog_age_seconds(self.catalog_root)
        return age is not None and age <= max_age_seconds

    def _cached_info(self) -> dict:
        commit = ""
        if (self.catalog_root / ".git").is_dir():
            commit = _git(["rev-parse", "HEAD"], cwd=self.catalog_root)
        return {"repo": self.repo_url, "commit": commit}

    def _catalog(self, refresh: bool) -> tuple[dict[str, list[CatalogEntry]], dict]:
        info = refresh_catalog(self.repo_url, self.catalog_root) if refresh else self._cached_info()
        problems: list[str] = []
        catalog = scan_catalog(self.catalog_root, info.get("commit", ""), problems)
        if problems:
            info = {**info, "warning": " ".join(filter(None, [info.get("warning"),
                    "Übersprungene Katalog-Einträge: " + "; ".join(problems)]))}
        return catalog, info

    def installed(self) -> dict[str, PluginManifest]:
        return discover_installed(tuple(project_plugin_paths(self.root)))

    @serialized
    def install(self, plugin_id: str, constraint: str = "*", *, refresh: bool = True) -> dict:
        """Installiert ein Plugin inkl. aller Abhängigkeiten und aktiviert es (wirkt nach Neustart)."""
        require_plugin_id(plugin_id)
        catalog, info = self._catalog(refresh)
        plan = resolve(catalog, {plugin_id: constraint}, self.installed())
        return self._apply(plan, info, activate=True)

    @serialized
    def uninstall(self, plugin_id: str, *, purge: bool = False, force: bool = False) -> dict:
        """Deinstalliert ein User-Plugin; eingebaute Plugins sind nur deaktivierbar."""
        require_plugin_id(plugin_id)
        installed = self.installed()
        manifest = installed.get(plugin_id)
        if manifest is None:
            raise InvalidInput("Unbekanntes Plugin.")
        if manifest.source != "user":
            raise InvalidInput(
                f"„{manifest.name}“ ist als „{manifest.source}“ ausgeliefert und kann nur deaktiviert, "
                "nicht deinstalliert werden.")
        user_root = self.user_dir.resolve()
        target = manifest.directory.resolve()
        if target == user_root or not target.is_relative_to(user_root):
            raise InvalidInput("Das Plugin liegt nicht im Benutzerverzeichnis.")
        dependents = sorted(
            other_id for other_id, other in installed.items()
            if other_id != plugin_id and any(dependency_matches(t, manifest) for t, _c in other.depends_on))
        if dependents and not force:
            raise PluginConflict(
                f"„{plugin_id}“ wird noch von folgenden Plugins benötigt: {', '.join(dependents)}. "
                "Deinstallation blockiert (force umgeht die Sperre).")
        state = self.root / ".material-ui" / "plugins" / plugin_id
        shared = self.root / SHARED_DIR / "plugins" / plugin_id
        paths = [target, self.lock.path, self.enabled_store.path] + ([state, shared] if purge else [])
        try:
            with rollback_paths(paths):
                shutil.rmtree(target)
                self.lock.remove(plugin_id)
                self.enabled_store.set_enabled(plugin_id, False)
                if purge:
                    for directory in (state, shared):
                        if directory.exists():
                            shutil.rmtree(directory)
        except BaseException:
            self.lock.data = LockFile(self.lock.path).data
            raise
        return {"ok": True, "restartRequired": True, "removed": plugin_id, "purged": bool(purge),
                "dependents": dependents}

    @serialized
    def update(self, target: str = "all", *, refresh: bool = True) -> dict:
        """Aktualisiert Marketplace-Pakete auf die neueste kompatible Katalog-Version."""
        catalog, info = self._catalog(refresh)
        installed = self.installed()
        if target != "all":
            require_plugin_id(target)
            ids = [target] if target in installed else []
            if not ids:
                raise InvalidInput(f"Unbekanntes oder nicht installiertes Plugin: {target}")
            if _is_dev_install(installed[target]):
                raise InvalidInput(f"„{target}“ ist eine Entwicklungsinstallation (Symlink) und wird nicht aktualisiert.")
        else:
            # Nur Pakete, die der Marketplace selbst installiert hat (Lockfile); von Hand
            # kopierte oder per Symlink eingebundene Plugins bleiben unangetastet.
            ids = sorted(pid for pid in self.lock.plugins()
                         if pid in installed and not _is_dev_install(installed[pid]))
        plan = resolve(catalog, {pid: "*" for pid in ids if pid in installed}, installed)
        return self._apply(plan, info, activate=False)

    def _reject_private(self, plugin_ids) -> None:
        """Private Projekt-Plugins (<repo>/plugins/) liegen ausserhalb des Marketplace: nie ueberschreiben."""
        for base, _source in project_plugin_paths(self.root):
            for plugin_id in plugin_ids:
                if (base / plugin_id / "plugin.json").is_file():
                    raise InvalidInput(
                        f"„{plugin_id}“ ist ein privates Projekt-Plugin ({base.name}/{plugin_id}) und wird nicht "
                        "über den Marketplace verwaltet.")

    def _apply(self, plan: Plan, info: dict, *, activate: bool) -> dict:
        changes = [a for a in plan.actions if a["action"] != "keep"]
        self._reject_private([a["id"] for a in changes])
        paths = [self.user_dir / a["id"] for a in changes]
        paths += [self.lock.path, self.enabled_store.path]
        self.user_dir.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=self.user_dir, prefix=".package-stage-") as temporary:
                staged = {}
                # Prepare and validate every package before touching any installed code.
                for action in changes:
                    entry = plan.entries[action["id"]]
                    directory = Path(temporary) / entry.manifest.id
                    shutil.copytree(entry.manifest.directory, directory)
                    m = load_manifest(directory, "user")
                    if m.id != entry.manifest.id or m.version != entry.manifest.version:
                        raise MarketplaceUnavailable("Paket wurde während der Vorbereitung verändert.")
                    staged[m.id] = CatalogEntry(m, entry.version, entry.commit, entry.description)
                with rollback_paths(paths):
                    for action in changes:
                        self._install_entry(staged[action["id"]])
                    previous_lock = self.lock.plugins()
                    for action in plan.actions:
                        pid = action["id"]
                        if pid not in plan.managed:
                            continue
                        entry = plan.entries.get(pid)
                        m = entry.manifest if entry else plan.kept[pid]
                        commit = entry.commit if entry else previous_lock.get(pid, {}).get("commit", "")
                        self.lock.record(pid, m.version, commit)
                        if activate or action["action"] == "install":
                            self.enabled_store.set_enabled(pid, True)
        except BaseException:
            self.lock.data = LockFile(self.lock.path).data
            raise
        actions = [{**a, "name": (plan.entries[a["id"]].manifest if a["id"] in plan.entries
                                  else plan.kept[a["id"]]).name} for a in plan.actions]
        return {"ok": True, "restartRequired": True, "catalog": info, "actions": actions}

    def _install_entry(self, entry: CatalogEntry) -> None:
        """Ersetzt ein vorbereitetes Paket; Metadaten/Rollback übernimmt _apply."""
        source = entry.manifest.directory
        if not source.is_dir():
            raise MarketplaceUnavailable(f"Katalog-Quellordner fehlt: {source}")
        self.user_dir.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(dir=self.user_dir, prefix=f".{entry.manifest.id}."))
        try:
            shutil.copytree(source, temporary, dirs_exist_ok=True)
            manifest = load_manifest(temporary, "user", check_dir_name=False)
            if manifest.id != entry.manifest.id or manifest.version != entry.manifest.version:
                raise MarketplaceUnavailable(
                    f"Katalog-Version {entry.manifest.id}/{entry.manifest.version} ist nach dem Kopieren ungültig.")
            destination = self.user_dir / entry.manifest.id
            with tempfile.TemporaryDirectory(dir=self.user_dir, prefix=".package-replaced-") as previous:
                backup = Path(previous) / "original"
                if destination.exists():
                    destination.rename(backup)
                try:
                    temporary.rename(destination)
                except OSError:
                    if backup.exists():
                        backup.rename(destination)
                    raise
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
