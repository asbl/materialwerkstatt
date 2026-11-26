"""Pruefung, ob der versionierte Bestand weitergegeben werden darf (Open-Source-Tauglichkeit).

Prueft die von Git verwalteten Dateien (oder nur die fuer den Commit vorgemerkten) auf

* Pfade, die nie ins Werkzeug-Repo gehoeren (Zugangsdaten, Unterrichtsmaterial, personenbezogene
  Daten, private Plugins und Vorlagen, PDFs/Office-Dateien),
* absolute Benutzerpfade (`/home/<name>/`, `/Users/<name>/`) und fremde E-Mail-Adressen,
* Begriffe aus den optionalen privaten Sperrlisten (`src/quarto/_local/oss-denylist.txt` fuer
  persoenliche Bezuege, `brand-denylist.txt` fuer Fremdmarken; eine Regex je Zeile, `#` kommentiert),
* Verstoesse gegen die Vorlagen-Richtlinie (`material_core.template_policy`).

Die Sperrlisten liegen bewusst im privaten Ordner: Sie enthalten genau die Namen, die nicht im
oeffentlichen Bestand stehen sollen. Ohne sie laufen die strukturellen Pruefungen trotzdem.

    python -m material_core.oss_check [--staged] [--root WURZEL]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from material_core import template_policy
from material_core.template_roots import private_dirname
from material_core import workspace

# Pfade, die nie versioniert werden duerfen (Regex gegen den Repo-relativen Pfad).
FORBIDDEN_PATHS = [
    (r"(^|/)\.env$", "Zugangsdaten (.env)"),
    (r"^unterricht/", "Unterrichtsmaterial gehoert ins private Inhalts-Repo"),
    (r"^foerderempfehlungen/", "personenbezogene Daten"),
    (r"^foerdermaterial/", "privater Inhaltsbereich"),
    (r"^wissen(/|$)", "Wissensbasis ist ein privates Projekt-Plugin"),
    (r"^plugins/", "private Projekt-Plugins"),
    (r"(^|/)_local/", "privater Ordner"),
    (r"(^|/)alt/", "Altmaterial"),
    (r"\.(pdf|docx|xlsx|pptx)$", "Binaerdokument"),
    (r"^archiv/", "Archiv"),
    (r"^ressourcen/quellen/", "Quellenablage (urheberrechtlich geschuetzte Fremdwerke)"),
    (r"^docs/audits/", "interne Auditberichte"),
    (r"^AGENTS\.local\.md$|^CLAUDE\.local\.md$", "lokale Agenten-Hinweise"),
]
ABSOLUTE_PATH = re.compile(r"(?<![\w.])/(?:home|Users)/[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\")
EMAIL = re.compile(r"[\w.+-]+@[A-Za-z][\w-]*(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")
ALLOWED_EMAIL_DOMAINS = {"example.test", "example.org", "example.com", "example.net", "users.noreply.github.com", "noreply.anthropic.com",
                         "anthropic.com", "git.invalid"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".ttf", ".otf", ".woff", ".woff2", ".tgz", ".gz",
                 ".zip", ".h5p", ".mo", ".pyc"}
SKIP_PATHS = re.compile(r"(^|/)(package-lock\.json|node_modules/|dist/|editor\.bundle\.js$|OFL\.txt$|LICENSE[^/]*$|NOTICE[^/]*$)")
# Eingefrorene Freigaben sind unveraenderlich (Pruefsummen): Inhalt dort nur auf Bilddaten pruefen, nicht auf Namen.
IMMUTABLE = re.compile(r"^src/quarto/template-releases/")
ALLOW_FILE = "oss-allow.txt"   # privat, optional: je Zeile eine Pfad-Regex, die von den Namenspruefungen ausgenommen ist
# Dateien, in denen der Urhebername bewusst steht.
IDENTITY_FILES = {"LICENSE", "src/sph_login/LICENSE", "pyproject.toml", "src/sph_login/pyproject.toml"}


def _git(root: Path, *args: str) -> list[str]:
    result = subprocess.run(["git", *args, "-z"], cwd=root, capture_output=True, text=True, check=True)
    return [item for item in result.stdout.split("\0") if item]


def candidate_files(root: Path, *, staged: bool) -> list[str]:
    if staged:
        return _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return _git(root, "ls-files")


def _read_lines(root: Path, name: str, *, staged: bool) -> list[str] | None:
    """Zeilen der Datei; im Staged-Modus aus dem Index (was committet wird), sonst aus dem Arbeitsbaum."""
    if staged:
        result = subprocess.run(["git", "show", f":{name}"], cwd=root, capture_output=True)
        if result.returncode != 0:
            return None
        try:
            return result.stdout.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            return None
    path = root / name
    if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file() or path.is_symlink():
        return None
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return None


def _patterns(root: Path, name: str) -> list[re.Pattern]:
    path = root / "src/quarto" / private_dirname() / name
    if not path.is_file() and root == workspace.CODE_ROOT:
        # Mit eigenem Inhaltsordner liegen die privaten Sperrlisten dort.
        path = workspace.root() / "src/quarto" / private_dirname() / name
    if not path.is_file():
        return []
    return [re.compile(line.strip(), re.IGNORECASE) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def scan(root: Path, *, staged: bool = False) -> list[str]:
    problems: list[str] = []
    personal = _patterns(root, "oss-denylist.txt")
    brands = _patterns(root, "brand-denylist.txt")
    allowed = _patterns(root, ALLOW_FILE)
    forbidden = [(re.compile(pattern), reason) for pattern, reason in FORBIDDEN_PATHS]
    for name in candidate_files(root, staged=staged):
        path = root / name
        for pattern, reason in forbidden:
            if pattern.search(name):
                problems.append(f"{name}: darf nicht versioniert werden ({reason})")
                break
        else:
            if path.suffix.lower() in SKIP_SUFFIXES or SKIP_PATHS.search(name):
                continue
            lines = _read_lines(root, name, staged=staged)
            if lines is None:
                continue
            names_checked = not IMMUTABLE.search(name) and not any(pattern.search(name) for pattern in allowed)
            for number, line in enumerate(lines, 1):
                if ABSOLUTE_PATH.search(line):
                    problems.append(f"{name}:{number}: absoluter Benutzerpfad")
                for match in EMAIL.finditer(line):
                    domain = match.group(0).rsplit("@", 1)[1].lower()
                    if domain not in ALLOWED_EMAIL_DOMAINS and not match.group(0).startswith("git@") \
                            and name not in IDENTITY_FILES:
                        problems.append(f"{name}:{number}: E-Mail-Adresse {match.group(0)}")
                for pattern in personal if names_checked else []:
                    if pattern.search(line) and name not in IDENTITY_FILES:
                        problems.append(f"{name}:{number}: persoenlicher Bezug ({pattern.pattern})")
                for pattern in brands if names_checked else []:
                    if pattern.search(line):
                        problems.append(f"{name}:{number}: Fremdmarke ({pattern.pattern})")
    try:
        problems += [f"{name}: nicht freigegebene Vorlagen-Datei (inv template-freigeben)"
                     for name in template_policy.tracked_outside_manifest(root)]
    except template_policy.PolicyError as error:
        problems.append(str(error))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--staged", action="store_true", help="nur die fuer den Commit vorgemerkten Dateien")
    parser.add_argument("--max", type=int, default=60, help="Hoechstzahl ausgegebener Befunde")
    args = parser.parse_args(argv)
    problems = scan(args.root.resolve(), staged=args.staged)
    if problems:
        shown = problems[: args.max]
        print(f"{len(problems)} Befund(e) -- so nicht weitergebbar:\n  " + "\n  ".join(shown), file=sys.stderr)
        if len(problems) > len(shown):
            print(f"  ... und {len(problems) - len(shown)} weitere", file=sys.stderr)
        return 1
    print("Keine Befunde: versionierter Bestand enthaelt keine privaten Pfade, Namen oder nicht freigegebenen Vorlagen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
