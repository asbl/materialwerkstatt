from __future__ import annotations

import os
from pathlib import Path
from material_core import workspace

# Überschreibt für Tests und lokale Umgebungen alle Suchorte; os.pathsep-getrennt.
PLUGIN_PATHS_ENV = "MATERIAL_UI_PLUGIN_PATHS"


def plugin_search_paths() -> list[tuple[Path, str]]:
    """Suchorte für Plugin-Ordner als (Verzeichnis, Quelle)-Paare in Discovery-Reihenfolge.

    Quelle "builtin": mit dem Paket ausgeliefert unter src/material_ui/plugins/<id>/.
    Quelle "user": XDG-Datenverzeichnis (~/.local/share/material-ui/plugins/<id>/).
    """
    override = os.environ.get(PLUGIN_PATHS_ENV)
    if override:
        return [(Path(part).expanduser(), "user") for part in override.split(os.pathsep) if part]
    builtin = Path(__file__).resolve().parent
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return [(builtin, "builtin"), (data_home / "material-ui" / "plugins", "user")]


def project_plugin_paths(root: Path) -> list[tuple[Path, str]]:
    """Projektlokale, nicht versionierte Plugins unter `<repo>/plugins/<id>/` (Quelle "project").

    Sie sind der Weg fuer private Plugins (z. B. Wissensbasis): Der Ordner ist git-ignoriert, der
    Marketplace verwaltet ihn nie (Installieren, Aktualisieren und Entfernen betreffen nur den
    Benutzerordner), und eine gleichnamige Marketplace-ID wird abgelehnt. Das Ueberschreiben der
    Suchorte per MATERIAL_UI_PLUGIN_PATHS (Tests) blendet auch diesen Ort aus.
    """
    if os.environ.get(PLUGIN_PATHS_ENV):
        return []
    paths = [(root / "plugins", "project")]
    # Mit eigenem Inhaltsordner koennen Plugins auch beim Programm liegen (`<programm>/plugins/`).
    if root != workspace.CODE_ROOT and root == workspace.root():
        paths.append((workspace.CODE_ROOT / "plugins", "project"))
    return paths


def external_plugin_directories() -> list[Path]:
    """Externe Plugin-Wurzeln (ohne eingebauten Paketordner) für den Server-Fingerprint."""
    roots: list[Path] = []
    for directory, source in plugin_search_paths():
        if source != "builtin":
            roots.append(directory)
    return roots
