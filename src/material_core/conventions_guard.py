"""Sperren fuer die Material-Konventionen: Agent-Hook und Git-pre-commit.

Beide Wege rufen dieselben Regeln auf wie ``inv konventionen`` und die Editor-Diagnose
(``material_core.conventions``). Es blockieren nur klare Verstoesse (Warnungen); Hinweise zum
Pruefen bleiben dem Menschen ueberlassen.

Aufrufe (stdlib genuegt, daher auch mit ``python3 -I`` lauffaehig):

    conventions_guard.py hook                 # Claude-Code-Hook (PostToolUse), JSON auf stdin
    conventions_guard.py files --root DIR F…  # Git-pre-commit: F… relativ zu DIR (Repo-Wurzel)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in {None, ""}:  # direkter Aufruf: src/ in den Suchpfad, nicht den Modulordner
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != Path(__file__).resolve().parent]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_core.conventions import SKIP_DIRS, check_conventions, check_file_name, position  # noqa: E402

MATERIAL_DIR = "unterricht"
MAX_LINES = 8


def is_material(path: Path, material_root: Path) -> bool:
    """Liegt ``path`` im Materialbestand (nicht in alt/, build/, kurse/ oder Punktordnern)?"""
    try:
        parts = path.resolve().relative_to(material_root.resolve()).parts
    except ValueError:
        return False
    return not any(part in SKIP_DIRS or part.startswith(".") for part in parts[:-1])


def violations(path: Path) -> list[str]:
    """Klare Verstoesse einer Datei als Zeilen ``pfad:zeile: [regel] titel - detail``."""
    lines: list[str] = []
    findings = [(0, finding) for finding in check_file_name(path)]
    if path.suffix == ".qmd" and path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        findings += [(position(text, finding.offset)[0], finding) for finding in check_conventions(path, text)]
    for line, finding in findings:
        if finding.level == "warning":
            lines.append(f"{path}{f':{line}' if line else ''}: [{finding.code}] {finding.title} – {finding.detail}")
    return lines


def report(lines: list[str], hint: str) -> str:
    shown = lines[:MAX_LINES]
    if len(lines) > MAX_LINES:
        shown.append(f"… und {len(lines) - MAX_LINES} weitere Stelle(n).")
    return "Material-Konventionen verletzt:\n" + "\n".join(shown) + f"\n{hint}\n"


def hook(stdin: str, project_dir: Path) -> tuple[int, str]:
    """Claude-Code-Hook: Exitcode 2 liefert die Meldung an den Agenten zurueck."""
    try:
        payload = json.loads(stdin or "{}")
    except ValueError:
        return 0, ""
    raw = (payload.get("tool_input") or {}).get("file_path")
    if not isinstance(raw, str) or not raw:
        return 0, ""
    path = Path(raw)
    if not path.is_absolute():
        path = project_dir / path
    if not is_material(path, project_dir / MATERIAL_DIR):
        return 0, ""
    lines = violations(path)
    if not lines:
        return 0, ""
    return 2, report(lines, "Bitte in dieser Datei beheben (Regeln: AGENTS.md, „Konventionsprüfung“; Details mit `inv konventionen --pfad <datei>`).")


def check_files(root: Path, names: list[str]) -> tuple[int, str]:
    """Git-pre-commit: prueft die uebergebenen Dateien relativ zur Repo-Wurzel ``root``."""
    lines: list[str] = []
    for name in names:
        path = root / name
        if path.is_file() and is_material(path, root):
            lines.extend(violations(path))
    if not lines:
        return 0, ""
    return 1, report(lines, "Commit abgebrochen. Verstöße beheben oder bewusst mit `git commit --no-verify` übergehen.")


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else ""
    if mode == "hook":
        project = Path(__import__("os").environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
        code, message = hook(sys.stdin.read(), project)
    elif mode == "files" and len(argv) >= 3 and argv[1] == "--root":
        code, message = check_files(Path(argv[2]), argv[3:])
    else:
        print(__doc__, file=sys.stderr)
        return 64
    if message:
        print(message, file=sys.stderr, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
