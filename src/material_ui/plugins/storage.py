from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from material_core import state
from material_core.filesystem import atomic_write_text
from material_ui.errors import InvalidInput

PASSWORD_PLACEHOLDER = "••••"
_SETTINGS_MODE = 0o600


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: (PASSWORD_PLACEHOLDER if key == "password" else _mask(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask(item) for item in value]
    return value


def _unmask(current: Any, incoming: Any) -> Any:
    """Setzt Platzhalter durch vorhandene Werte, damit GET keine Passwörter ausliefern muss."""
    if isinstance(incoming, dict):
        if not isinstance(current, dict):
            current = {}
        merged: dict[str, Any] = {}
        for key, item in incoming.items():
            if isinstance(item, (dict, list)):
                merged[key] = _unmask(current.get(key), item)
            elif key == "password" and isinstance(item, str) and item == PASSWORD_PLACEHOLDER:
                merged[key] = current.get(key, "")
            else:
                merged[key] = item
        return merged
    if isinstance(incoming, list):
        if not isinstance(current, list):
            current = []
        return [_unmask(current[index] if index < len(current) else None, item)
                for index, item in enumerate(incoming)]
    return incoming


class PluginStorage:
    """Plugin-eigener Datenspeicher.

    `path()` ist rechnerlokal (<repo>/.material-ui/plugins/<id>/): Caches, Zugangsdaten.
    `shared_path()` liegt unter <repo>/daten/plugins/<id>/ und wird mitsynchronisiert.
    """

    def __init__(self, base: Path, shared_base: Path | None = None) -> None:
        self.base = base
        self.shared_base = shared_base
        self.lock = threading.RLock()

    def path(self, *parts: str) -> Path:
        return self._inside(self.base, parts)

    def shared_path(self, *parts: str) -> Path:
        """Gemeinsame Datei; uebernimmt beim ersten Zugriff den bisher lokalen Stand."""
        if self.shared_base is None:
            return self.path(*parts)
        target = self._inside(self.shared_base, parts)
        with self.lock:
            state.adopt(self.path(*parts), target)
        return target

    @staticmethod
    def _inside(base: Path, parts: tuple[str, ...]) -> Path:
        candidate = base.joinpath(*[part for part in parts if part])
        resolved = candidate.resolve()
        if resolved != base.resolve() and not resolved.is_relative_to(base.resolve()):
            raise InvalidInput("Plugin-Speicherpfad liegt ausserhalb des Plugin-Bereichs.")
        return candidate

    def read_json(self, relative: Path, default: Any = None) -> Any:
        with self.lock:
            try:
                return json.loads(relative.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return default

    def write_json(self, relative: Path, data: Any, *, private: bool = False) -> None:
        mode = _SETTINGS_MODE if private else None
        with self.lock:
            relative.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(relative, json.dumps(data, ensure_ascii=False, indent=2), mode=mode)


class PluginSettings:
    """Einstellungen je Plugin als 0600-JSON; Passwörter werden nie ausgeliefert."""

    def __init__(self, storage: PluginStorage, filename: str = "settings.json") -> None:
        self.storage = storage
        self.file = storage.path(filename)

    def load(self) -> dict[str, Any]:
        self.storage.path(self.file.name)  # Erneut prüfen: nachträglich gesetzte Symlinks abweisen.
        if self.file.exists():
            self.file.chmod(_SETTINGS_MODE)
        data = self.storage.read_json(self.file, default={})
        return data if isinstance(data, dict) else {}

    def replace(self, incoming: dict[str, Any]) -> dict[str, Any]:
        self.storage.path(self.file.name)
        self.file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file.parent.chmod(0o700)
        merged = _unmask(self.load(), incoming)
        self.storage.write_json(self.file, merged, private=True)
        return merged

    def masked(self) -> dict[str, Any]:
        return _mask(self.load())


class PluginEnabledStore:
    """Aktivierungszustand aller Plugins, dauerhaft unter daten/plugins.json."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()

    def _read(self) -> dict[str, bool]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        entries = data.get("enabled") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            return {}
        return {key: bool(value) for key, value in entries.items() if isinstance(key, str) and isinstance(value, bool)}

    def is_enabled(self, plugin_id: str, default: bool) -> bool:
        with self.lock:
            return self._read().get(plugin_id, default)

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        with self.lock:
            entries = self._read()
            entries[plugin_id] = enabled
            mode = (self.path.stat().st_mode & 0o777) if self.path.exists() else 0o600
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.path, json.dumps({"enabled": entries}, ensure_ascii=False, indent=2), mode=mode)
