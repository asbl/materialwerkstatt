"""Lader fuer private Erweiterungen (nicht versionierte Designs, Kastenmotive, Assets).

Liegt `design_modules/design_hooks.py` im privaten Ordner (`src/quarto/_local/`, siehe
`material_core.template_roots`), wird es geladen und seine Funktionen stehen ueber `hook()` bereit.
Fehlt die Datei, liefert `hook()` den Vorgabewert: der oeffentliche Bestand ist ohne private
Designs vollstaendig lauffaehig.
"""
from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from material_core.template_roots import private_root

_MODULE_NAME = "material_private_design_hooks"
_cache: dict[str, ModuleType | None] = {}


def private_module() -> ModuleType | None:
    directory = private_root() / "design_modules"
    path = directory / "design_hooks.py"
    key = str(path)
    if key in _cache:
        return _cache[key]
    module = None
    if path.is_file():
        # Weitere private Module liegen im selben Ordner und werden ueber sys.path gefunden.
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = module
        try:
            spec.loader.exec_module(module)
        except Exception as error:  # ein defektes privates Modul darf den oeffentlichen Bestand nicht lahmlegen
            sys.modules.pop(_MODULE_NAME, None)
            module = None
            print(f"Warnung: privates Design-Modul {path} nicht ladbar ({type(error).__name__}: {error}); "
                  "private Designs bleiben ohne Sonderdarstellung.", file=sys.stderr)
    _cache[key] = module
    return module


def hook(name: str, *arguments, default=None):
    module = private_module()
    function = getattr(module, name, None) if module is not None else None
    return function(*arguments) if function is not None else default
