"""Orte fuer eingebaute und private Vorlagen.

Grundregel: Vorlagen sind standardmaessig **privat**. Neue Vorlagen, Layout-Partials,
Freigaben (Releases) und Designs entstehen im ignorierten privaten Ordner
`src/quarto/_local/` (Unterordner `templates/`, `template-releases/`, ...), der wie der
eingebaute Bestand funktioniert, aber nie versioniert wird. In `src/quarto/templates/`
und `src/quarto/template-releases/` liegt nur, was ausdruecklich freigegeben wurde
(`inv template-freigeben`) und in `src/quarto/builtin-templates.json` eingetragen ist.

Eine Vorlage wird ueber ihren Dateinamen aufgeloest; der logische Pfad
`src/quarto/templates/<name>` bleibt fuer Oberflaeche und Frontmatter stabil, auch wenn die
Datei physisch im privaten Ordner liegt.

Der private Ordnername ist ueber `MATERIAL_PRIVATE_DIR` (relativ zu `src/quarto/`)
ueberschreibbar; Tests setzen ihn auf einen nicht vorhandenen Ordner, um den oeffentlichen
Bestand ohne private Vorlagen zu pruefen.
"""
from __future__ import annotations

import os
from pathlib import Path
from material_core import workspace

SUPPORT = workspace.root() / "src" / "quarto"
PRIVATE_DIR_ENV = "MATERIAL_PRIVATE_DIR"
DEFAULT_PRIVATE_DIR = "_local"
BUILTIN_MANIFEST = "builtin-templates.json"


def private_dirname() -> str:
    value = os.environ.get(PRIVATE_DIR_ENV) or DEFAULT_PRIVATE_DIR
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{PRIVATE_DIR_ENV} muss ein relativer Ordnername unterhalb von src/quarto sein.")
    return path.as_posix()


def private_root(support: Path = SUPPORT) -> Path:
    return support / private_dirname()


def builtin_templates(support: Path = SUPPORT) -> Path:
    return support / "templates"


def private_templates(support: Path = SUPPORT) -> Path:
    return private_root(support) / "templates"


def template_dirs(support: Path = SUPPORT) -> list[Path]:
    """Suchreihenfolge: eingebaut, dann privat (nur vorhandene Ordner)."""
    return [path for path in (builtin_templates(support), private_templates(support)) if path.is_dir()]


def find_template(name: str, support: Path = SUPPORT) -> Path | None:
    """Datei einer Vorlage, eines Partials oder Includes anhand des Dateinamens."""
    clean = Path(str(name).replace("\\", "/")).name
    if not clean:
        return None
    for directory in template_dirs(support):
        candidate = directory / clean
        if candidate.is_file():
            return candidate
    return None


def template_path(name: str, support: Path = SUPPORT) -> Path:
    """Wie find_template, liefert aber auch fuer fehlende Vorlagen einen (eingebauten) Pfad; fuer Tests."""
    return find_template(name, support) or builtin_templates(support) / Path(name).name


def all_template_names(support: Path = SUPPORT, *suffixes: str) -> set[str]:
    suffixes = suffixes or (".typst", ".tex")
    return {path.name for directory in template_dirs(support)
            for path in directory.iterdir() if path.is_file() and path.suffix in suffixes}


def all_template_files(support: Path = SUPPORT, *suffixes: str) -> list[Path]:
    """Alle Vorlagendateien beider Ordner; bei gleichem Namen gewinnt der eingebaute Ordner."""
    suffixes = suffixes or (".typst", ".tex")
    found: dict[str, Path] = {}
    for directory in template_dirs(support):
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix in suffixes:
                found.setdefault(path.name, path)
    return list(found.values())


def is_template_dir(path: Path, support: Path = SUPPORT) -> bool:
    resolved = Path(path).resolve()
    return any(resolved == directory.resolve() for directory in template_dirs(support))


def is_private(path: Path, support: Path = SUPPORT) -> bool:
    return Path(path).resolve().is_relative_to(private_root(support).resolve())


def sibling(path: Path, name: str, support: Path = SUPPORT) -> Path:
    """Nachbardatei von `path`; fehlt sie dort, wird im jeweils anderen Vorlagenordner gesucht.

    Private Vorlagen duerfen eingebaute Partials und Assets (und umgekehrt private Partials
    aus eingebauten Vorlagen, falls vorhanden) wie Geschwisterdateien verwenden.
    """
    direct = path.with_name(name)
    if direct.exists():
        return direct
    for directory in template_dirs(support):
        base = directory.resolve()
        if Path(path).resolve().is_relative_to(base):
            relative = Path(path).resolve().parent.relative_to(base)
            for other in template_dirs(support):
                candidate = other / relative / name
                if candidate.exists():
                    return candidate
    return direct


def logical_relative(path: Path, support: Path = SUPPORT) -> str:
    """Pfad relativ zu `src/quarto`, wobei der private Ordner dem eingebauten entspricht.

    `src/quarto/_local/templates/x.typst` wird zu `templates/x.typst`; dadurch bleiben
    Layout-Hashes (Pruefsummen ueber diese Namen) unabhaengig vom physischen Ort.
    """
    resolved = Path(path).resolve()
    private = private_root(support).resolve()
    if resolved.is_relative_to(private):
        return resolved.relative_to(private).as_posix()
    return resolved.relative_to(support.resolve()).as_posix()
