"""Arbeitsbereich: Inhalte getrennt vom Programmcode.

`CODE_ROOT` ist der Klon des Werkzeugs. Der **Arbeitsbereich** enthaelt alle Inhalte
(`unterricht/`, `wissen/`, private Vorlagen, `build/`, ...). Ohne Einstellung sind beide
dasselbe Verzeichnis, dann verhaelt sich alles wie bisher.

Auswahl: Umgebungsvariable `MATERIAL_HOME`, sonst die Einstellung dieses Rechners in
`$XDG_CONFIG_HOME/material-ui/workspace.json` (je Programmverzeichnis), sonst `CODE_ROOT`.

Dokumente verweisen relativ auf Filter und Vorlagen (`src/quarto/...`), und Quarto braucht
`_quarto.yml` im Projekt. Deshalb bekommt ein eigener Arbeitsbereich eine **verwaltete Kopie**
genau dieser Dateien (`prepare`). Sie wird bei jedem Start abgeglichen; eigene Dateien
(vor allem `src/quarto/_local/`) bleiben unberuehrt. Nur Standardbibliothek.
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import tempfile
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]
CODE_SRC = CODE_ROOT / "src"
ENV = "MATERIAL_HOME"
MANIFEST = ".material-werkzeuge.json"
# Liegt im Programmverzeichnis einer Paketinstallation (z. B. /usr/share/material-ui).
SYSTEM_MARKER = ".system-install"
# Aus dem Code-Verzeichnis gespiegelt: Dateien und Ordner (rekursiv).
MIRRORED_FILES = ("_quarto.yml", "src/quarto_render_guard.py", ".markdownlint-cli2.yaml")
MIRRORED_GLOBS = ("src/material_core/*.json",)
MIRRORED_TREES = ("src/quarto",)
SKIPPED_DIRS = {"_local", "__pycache__", ".quarto", ".pytest_cache"}

# Damit `inv ...` auch im Arbeitsbereich funktioniert. Ohne rechnerspezifische Pfade, weil der
# Arbeitsbereich zwischen Rechnern synchronisiert wird.
TASKS_SHIM = '''"""Von Material-UI erzeugt: fuehrt die Tasks des Werkzeugs in diesem Arbeitsbereich aus."""
import json
import os
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "material-ui" / "workspace.json"
ENTRIES = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.is_file() else {}
CODE = next((Path(code) for code, home in ENTRIES.items() if Path(home) == HERE), None)
# Paketinstallation mit Standard-Inhaltsordner: es gibt keinen Eintrag.
if CODE is None and Path("/usr/share/material-ui/tasks.py").is_file():
    CODE = Path("/usr/share/material-ui")
if CODE is None:
    raise SystemExit(f"{HERE} ist auf diesem Rechner nicht als Inhaltsordner eingestellt (Einstellungen, Reiter Ordner).")
os.environ["MATERIAL_HOME"] = str(HERE)
namespace = runpy.run_path(str(CODE / "tasks.py"))["namespace"]
'''


class WorkspaceError(ValueError):
    """Verstaendliche Meldung fuer Oberflaeche und Kommandozeile."""


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "material-ui" / "workspace.json"


def _read_config() -> dict:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise WorkspaceError(f"{config_path()} ist nicht lesbar: {error}") from error
    if not isinstance(data, dict):
        raise WorkspaceError(f"{config_path()} hat ein unerwartetes Format.")
    return data


def configured(code_root: Path | None = None) -> Path | None:
    """Eingestellter Arbeitsbereich dieses Rechners (ohne Umgebungsvariable)."""
    code_root = code_root or CODE_ROOT
    value = _read_config().get(str(code_root))
    return Path(value) if value else None


def installed(code_root: Path | None = None) -> bool:
    """Paketinstallation: das Programmverzeichnis darf nicht beschrieben werden."""
    code_root = code_root or CODE_ROOT
    return (code_root / SYSTEM_MARKER).exists() or not os.access(code_root, os.W_OK)


def _documents() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    try:
        for line in (base / "user-dirs.dirs").read_text(encoding="utf-8").splitlines():
            if line.startswith("XDG_DOCUMENTS_DIR="):
                value = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(Path.home()))
                if Path(value).is_absolute() and Path(value) != Path.home():
                    return Path(value)
    except OSError:
        pass
    return Path.home() / "Documents"


def default_home(code_root: Path | None = None) -> Path:
    """Inhaltsordner ohne Einstellung: beim Klon das Programmverzeichnis, sonst Dokumente/material."""
    code_root = code_root or CODE_ROOT
    return _documents() / "material" if installed(code_root) else code_root


def _ensure_default(target: Path) -> None:
    """Den Standardordner einer Paketinstallation beim ersten Start anlegen."""
    if installed() and target == default_home():
        target.mkdir(parents=True, exist_ok=True)


def selected(code_root: Path | None = None) -> Path:
    """Gewuenschter Arbeitsbereich; er muss nicht existieren."""
    code_root = code_root or CODE_ROOT
    value = os.environ.get(ENV)
    if value:
        return Path(value).expanduser().resolve()
    return configured(code_root) or default_home(code_root)


def root() -> Path:
    """Verwendbarer Arbeitsbereich; fehlt der gewaehlte Ordner, der Standardordner.

    Der Rueckfall haelt die Einstellungen erreichbar. Kommandozeilenwerkzeuge rufen `require`.
    """
    target = selected()
    _ensure_default(target)
    if target.is_dir():
        return target
    fallback = default_home()
    _ensure_default(fallback)
    return fallback


def require() -> Path:
    target = selected()
    _ensure_default(target)
    if not target.is_dir():
        raise WorkspaceError(f"Der Inhaltsordner {target} fehlt (Sync noch nicht eingerichtet?).")
    return target


def check(target: Path, code_root: Path | None = None) -> None:
    code_root = code_root or CODE_ROOT
    if not target.is_absolute():
        raise WorkspaceError("Bitte einen vollständigen Pfad angeben (beginnt mit / oder ~).")
    if target == Path(target.anchor) or target == Path.home():
        raise WorkspaceError("Das Wurzel- oder Benutzerverzeichnis ist zu weit gefasst.")
    if target == code_root and not installed(code_root):
        return
    if target.is_relative_to(code_root) or code_root.is_relative_to(target):
        raise WorkspaceError(f"Der Inhaltsordner darf nicht im Programmverzeichnis {code_root} liegen oder es enthalten.")
    if "foerderempfehlungen" in target.parts:
        raise WorkspaceError("Der Bereich für personenbezogene Daten kann nicht Inhaltsordner sein.")
    if (target / "pyproject.toml").exists() or (target / "src" / "material_ui").exists():
        raise WorkspaceError(f"{target} ist ein Programmverzeichnis; dort würden Dateien überschrieben.")


def save(value: str, *, create: bool = False, code_root: Path | None = None) -> Path:
    """Arbeitsbereich dieses Rechners speichern und vorbereiten. Leer = Programmverzeichnis."""
    code_root = code_root or CODE_ROOT
    raw = str(value or "").strip()
    target = default = default_home(code_root)
    if raw:
        target = Path(os.path.expanduser(raw))
        check(target, code_root)
        target = target.resolve()
        check(target, code_root)
        if target.exists() and not target.is_dir():
            raise WorkspaceError(f"{target} ist kein Ordner.")
        if not target.exists():
            if not create:
                raise WorkspaceError(f"{target} gibt es nicht. „Ordner anlegen“ wählen.")
            target.mkdir(parents=True)
    elif installed(code_root):
        target.mkdir(parents=True, exist_ok=True)
    data = _read_config()
    if target == default:
        prepare(target, code_root)
        data.pop(str(code_root), None)
    else:
        prepare(target, code_root)
        data[str(code_root)] = str(target)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        temporary = Path(handle.name)
    temporary.replace(path)
    return target


def _tool_files(code_root: Path) -> dict[str, Path]:
    files = {name: code_root / name for name in MIRRORED_FILES if (code_root / name).is_file()}
    for pattern in MIRRORED_GLOBS:
        files.update({path.relative_to(code_root).as_posix(): path for path in code_root.glob(pattern)})
    for tree in MIRRORED_TREES:
        for directory, names, filenames in os.walk(code_root / tree):
            names[:] = [name for name in names if name not in SKIPPED_DIRS]
            for filename in filenames:
                path = Path(directory) / filename
                files[path.relative_to(code_root).as_posix()] = path
    return files


def prepare(target: Path, code_root: Path | None = None) -> list[str]:
    """Werkzeugdateien im Arbeitsbereich abgleichen; liefert die geaenderten Pfade."""
    code_root = code_root or CODE_ROOT
    if target == code_root:
        return []
    check(target, code_root)
    manifest = target / MANIFEST
    try:
        previous = set(json.loads(manifest.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        previous = set()
    wanted = _tool_files(code_root)
    changed = []
    for name, source in wanted.items():
        destination = target / name
        if destination.is_file() and filecmp.cmp(source, destination, shallow=False):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        changed.append(name)
    shim = target / "tasks.py"
    if not shim.exists() or shim.read_text(encoding="utf-8") != TASKS_SHIM:
        shim.write_text(TASKS_SHIM, encoding="utf-8")
        changed.append("tasks.py")
    # Nur entfernen, was frueher von hier kam.
    for name in previous - set(wanted):
        stale = target / name
        if not Path(name).is_absolute() and ".." not in Path(name).parts and stale.is_file():
            stale.unlink()
            changed.append(name)
    if changed or not manifest.is_file():
        manifest.write_text(json.dumps(sorted(wanted), indent=1), encoding="utf-8")
    return changed


def export_pythonpath() -> None:
    """Unterprozesse (`python -m ...`) finden die Pakete auch ohne pip-Installation."""
    paths = [str(CODE_SRC), *(p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p and p != str(CODE_SRC))]
    os.environ["PYTHONPATH"] = os.pathsep.join(paths)


def activate(*, strict: bool = True) -> Path:
    """Beim Start eines Einstiegspunkts: Arbeitsbereich bestimmen und Werkzeugdateien abgleichen."""
    export_pythonpath()
    target = require() if strict else root()
    prepare(target)
    return target
