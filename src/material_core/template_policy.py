"""Richtlinie fuer eingebaute und private Vorlagen.

Vorlagen sind standardmaessig privat. Eingebaut (und damit versionierbar) ist nur, was in
`src/quarto/builtin-templates.json` steht und in `src/quarto/templates/` bzw.
`src/quarto/template-releases/` liegt. Die Aufnahme erfolgt ausdruecklich ueber
`freigeben()` (`inv template-freigeben`), nie implizit.

Kommandozeile (auch fuer den pre-commit-Hook):
    python -m material_core.template_policy check [--root WURZEL]
    python -m material_core.template_policy freigeben NAME --lizenz-bestaetigt [--root WURZEL]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from material_core.template_roots import BUILTIN_MANIFEST, private_dirname

# Hinweise auf eingebettete Fremdgrafiken in Vorlagen (Bilddaten gehoeren nie in eingebaute Dateien).
EMBEDDED_IMAGE = re.compile(r"data:image/|base64,|\bbytes\(\s*\"[A-Za-z0-9+/=]{400,}")
DENYLIST_FILE = "brand-denylist.txt"      # privat, optional: ein Begriff (Regex) je Zeile
PARTIAL = re.compile(r"\$([\w-]+\.typst)\(\)\$")
IMPORT = re.compile(r'#(?:import|include)\s+"([^"@]+)"')
IMAGE = re.compile(r'\bimage\(\s*"([^"@]+)"')
FONT = re.compile(r'font:\s*"([^"]+)"')


class PolicyError(ValueError):
    pass


def paths(root: Path) -> dict[str, Path]:
    support = root / "src/quarto"
    private = support / private_dirname()
    return {
        "support": support,
        "manifest": support / BUILTIN_MANIFEST,
        "templates": support / "templates",
        "releases": support / "template-releases",
        "designs": root / "src/material_core/template-designs.json",
        "private": private,
        "private_templates": private / "templates",
        "private_releases": private / "template-releases",
        "private_designs": private / "template-designs.json",
    }


def load_manifest(root: Path) -> dict:
    path = paths(root)["manifest"]
    if not path.is_file():
        raise PolicyError(f"Freigabeliste fehlt: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("templates", "release-stems", "designs"):
        if not isinstance(data.get(key), list):
            raise PolicyError(f"{BUILTIN_MANIFEST}: Feld {key} fehlt oder ist keine Liste.")
    return data


def save_manifest(root: Path, data: dict) -> None:
    for key in ("templates", "release-stems", "designs"):
        data[key] = sorted(set(data[key]))
    paths(root)["manifest"].write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def denylist(root: Path) -> list[re.Pattern]:
    path = paths(root)["private"] / DENYLIST_FILE
    if not path.is_file():
        return []
    return [re.compile(line.strip(), re.IGNORECASE) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


def allowed_paths(root: Path) -> list[re.Pattern]:
    """Bewusst belassene Treffer (privat, optional): Pfad-Regexe, die von der Namenspruefung ausgenommen sind."""
    path = paths(root)["private"] / "oss-allow.txt"
    if not path.is_file():
        return []
    return [re.compile(line.strip()) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def referenced_layouts(root: Path, stems: list[str]) -> set[str]:
    releases = paths(root)["releases"]
    layouts: set[str] = set()
    for stem in stems:
        for release in (releases / stem).glob("v*.json"):
            layouts.add(json.loads(release.read_text(encoding="utf-8"))["layout"].rsplit("/", 1)[-1])
    return layouts


def _scan(path: Path, patterns: list[re.Pattern]) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return [f"{path}: Binaerdatei in eingebauten Vorlagen"] if path.suffix not in {".json"} else []
    problems = []
    if EMBEDDED_IMAGE.search(text):
        problems.append(f"{path}: eingebettete Bilddaten")
    for pattern in patterns:
        if pattern.search(text):
            problems.append(f"{path}: gesperrter Begriff {pattern.pattern!r}")
    return problems


def check(root: Path) -> list[str]:
    """Findet alles, was in den eingebauten Ordnern liegt, ohne ausdruecklich freigegeben zu sein."""
    where = paths(root)
    manifest = load_manifest(root)
    problems: list[str] = []
    patterns = denylist(root)
    allow = allowed_paths(root)
    allowed_files = set(manifest["templates"])
    for path in sorted(where["templates"].rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(where["templates"]).as_posix()
        if relative not in allowed_files:
            problems.append(f"{path.relative_to(root)}: nicht freigegeben (Vorlagen sind standardmaessig privat; "
                            "ausdruecklich mit `inv template-freigeben` aufnehmen)")
        else:
            relative_to_root = path.relative_to(root).as_posix()
            skip = any(pattern.search(relative_to_root) for pattern in allow)
            problems += [p.replace(str(root) + "/", "") for p in _scan(path, [] if skip else patterns)]
    for name in sorted(allowed_files):
        if not (where["templates"] / name).is_file():
            problems.append(f"{BUILTIN_MANIFEST}: {name} ist eingetragen, fehlt aber in templates/")
    stems = set(manifest["release-stems"])
    if where["releases"].is_dir():
        for entry in sorted(where["releases"].iterdir()):
            if entry.name in {"layouts", "contexts"} or not entry.is_dir():
                continue
            if entry.name not in stems:
                problems.append(f"{entry.relative_to(root)}: Freigabe-Ordner nicht freigegeben")
        wanted = referenced_layouts(root, [s for s in stems if (where["releases"] / s).is_dir()])
        layouts = where["releases"] / "layouts"
        for layout in sorted(layouts.iterdir()) if layouts.is_dir() else []:
            if layout.name not in wanted:
                problems.append(f"{layout.relative_to(root)}: Layout wird von keiner freigegebenen Vorlage verwendet")
            else:
                for path in layout.rglob("*"):
                    if path.is_file() and path.suffix in {".typst", ".tex", ".lua", ".json"}:
                        # Eingefrorene Freigaben sind unveraenderlich: nur auf Bilddaten pruefen.
                        problems += [p.replace(str(root) + "/", "") for p in _scan(path, [])]
    catalog = json.loads(where["designs"].read_text(encoding="utf-8")) if where["designs"].is_file() else []
    allowed_designs = set(manifest["designs"])
    for design in catalog:
        if design["id"] not in allowed_designs:
            problems.append(f"template-designs.json: Design {design['id']} nicht freigegeben")
    return problems


def tracked_outside_manifest(root: Path) -> list[str]:
    """Getrackte Dateien in den eingebauten Ordnern, die nicht zur Freigabeliste passen (fuer den Hook)."""
    where = paths(root)
    manifest = load_manifest(root)
    stems = set(manifest["release-stems"])
    wanted = referenced_layouts(root, [s for s in stems if (where["releases"] / s).is_dir()])
    result = subprocess.run(["git", "ls-files", "-z", "--", "src/quarto/templates", "src/quarto/template-releases"],
                            cwd=root, capture_output=True, text=True, check=True)
    problems = []
    for name in filter(None, result.stdout.split("\0")):
        parts = Path(name).parts
        if parts[:3] == ("src", "quarto", "templates"):
            if "/".join(parts[3:]) not in manifest["templates"]:
                problems.append(name)
        elif len(parts) > 3 and parts[3] not in {"layouts", "contexts"} and parts[3] not in stems:
            problems.append(name)
        elif len(parts) > 4 and parts[3] == "layouts" and parts[4] not in wanted:
            problems.append(name)
    return problems


def _closure(root: Path, name: str) -> tuple[Path, list[Path]]:
    """Vorlagendatei und alle privaten Abhaengigkeiten (Partials, Includes, Assets)."""
    where = paths(root)
    template = next((where["private_templates"] / f"{name}{suffix}" for suffix in (".typst", ".tex")
                     if (where["private_templates"] / f"{name}{suffix}").is_file()), None)
    if template is None:
        raise PolicyError(f"Keine private Vorlage {name!r} in {where['private_templates'].relative_to(root)}.")
    files: list[Path] = []
    seen: set[Path] = set()

    def visit(path: Path) -> None:
        if path in seen:
            return
        seen.add(path)
        files.append(path)
        if path.suffix not in {".typst", ".tex"}:
            return
        text = path.read_text(encoding="utf-8")
        for ref in [*PARTIAL.findall(text), *IMPORT.findall(text), *IMAGE.findall(text)]:
            candidate = path.parent / ref
            if candidate.is_file() and candidate.resolve().is_relative_to(where["private_templates"].resolve()):
                visit(candidate.resolve())

    visit(template.resolve())
    return template, files


def freigeben(root: Path, name: str, *, lizenz_bestaetigt: bool, dry_run: bool = False) -> list[str]:
    """Nimmt eine private Vorlage ausdruecklich in den eingebauten Bestand auf.

    Ablauf: Abhaengigkeiten ermitteln, automatisch pruefen (Fremdbegriffe aus dem privaten
    Sperrliste, eingebettete Bilddaten, nicht gebuendelte Schriften als Hinweis), dann Dateien,
    Freigaben, Layouts und Katalogeintrag verschieben und die Freigabeliste ergaenzen.
    Es wird nichts ins Git aufgenommen; die Meldung nennt die Pfade fuer `git add`.
    """
    where = paths(root)
    manifest = load_manifest(root)
    template, files = _closure(root, name)
    patterns = denylist(root)
    blockers: list[str] = []
    for path in files:
        blockers += _scan(path, patterns)
    # Auch die mitwandernden Freigaben (Snapshot-JSON, Motive) und eingefrorenen Layouts pruefen.
    release_dir = where["private_releases"] / template.stem
    if (where["releases"] / template.stem).exists():
        blockers.append(f"{(where['releases'] / template.stem).relative_to(root)}: Freigabe-Ordner existiert bereits im eingebauten Bestand")
    for path in sorted(release_dir.glob("v*.json")) if release_dir.is_dir() else []:
        blockers += _scan(path, patterns)
        layout_id = json.loads(path.read_text(encoding="utf-8")).get("layout", "").rsplit("/", 1)[-1]
        layout_dir = where["private_releases"] / "layouts" / layout_id
        for layout_file in sorted(layout_dir.rglob("*")) if layout_id and layout_dir.is_dir() else []:
            if layout_file.is_file():
                blockers += _scan(layout_file, patterns)
    notes = []
    for path in files:
        if path.suffix in {".typst", ".tex"}:
            for font in sorted(set(FONT.findall(path.read_text(encoding="utf-8")))):
                notes.append(f"Schrift {font!r} in {path.name}: Lizenz und Bereitstellung pruefen (gebuendelt sind nur OFL-Schriften unter src/quarto/fonts).")
    if blockers:
        raise PolicyError("Freigabe abgelehnt:\n  " + "\n  ".join(blockers))
    if dry_run:
        return ["(Probelauf: nichts verschoben)", f"Dateien: {', '.join(p.name for p in files)}", *notes,
                "Keine Sperrbegriffe, keine eingebetteten Bilddaten."]
    if not lizenz_bestaetigt:
        raise PolicyError(
            "Freigabe erfordert die ausdrueckliche Bestaetigung (--lizenz-bestaetigt): Vorlage, Grafiken, Motive, "
            "Namen und Schriften sind frei verwendbar und enthalten keine Fremdmarken.\n" + "\n".join(notes)
        )
    report = [f"Dateien: {', '.join(p.name for p in files)}", *notes]
    moved: list[str] = []
    for path in files:
        relative = path.relative_to(where["private_templates"].resolve())
        destination = where["templates"] / relative
        if destination.exists():
            continue                      # bereits eingebaut (gemeinsames Partial)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
        moved.append(destination.relative_to(root).as_posix())
        manifest["templates"].append(relative.as_posix())
    # Freigaben und Layouts
    stem = template.stem
    private_stem = where["private_releases"] / stem
    if private_stem.is_dir():
        shutil.move(str(private_stem), str(where["releases"] / stem))
        manifest["release-stems"].append(stem)
        moved.append((where["releases"] / stem).relative_to(root).as_posix() + "/")
        for layout_id in sorted(referenced_layouts(root, [stem])):
            source = where["private_releases"] / "layouts" / layout_id
            destination = where["releases"] / "layouts" / layout_id
            if source.is_dir() and not destination.exists():
                shutil.copytree(source, destination)
                moved.append(destination.relative_to(root).as_posix() + "/")
    # Katalogeintrag
    design_id = stem.split("-", 1)[1] if stem.split("-", 1)[0] in {"worksheet", "slide"} and "-" in stem else stem
    if where["private_designs"].is_file():
        private = json.loads(where["private_designs"].read_text(encoding="utf-8"))
        match = [d for d in private if d["id"] == design_id]
        if match:
            catalog = json.loads(where["designs"].read_text(encoding="utf-8"))
            catalog.append({k: v for k, v in match[0].items() if k != "local_only"})
            where["designs"].write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            where["private_designs"].write_text(
                json.dumps([d for d in private if d["id"] != design_id], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            manifest["designs"].append(design_id)
            moved.append(where["designs"].relative_to(root).as_posix())
    save_manifest(root, manifest)
    moved.append(where["manifest"].relative_to(root).as_posix())
    return [*report, "Aufgenommen (mit `git add` pruefen und committen):", *[f"  {item}" for item in moved]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("tracked")
    promote = sub.add_parser("freigeben")
    promote.add_argument("name")
    promote.add_argument("--lizenz-bestaetigt", action="store_true")
    promote.add_argument("--probelauf", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "check":
            problems = check(root)
            if problems:
                print("Vorlagen-Richtlinie verletzt:\n  " + "\n  ".join(problems))
                return 1
            print("Eingebaute Vorlagen entsprechen der Freigabeliste.")
        elif args.command == "tracked":
            problems = tracked_outside_manifest(root)
            if problems:
                print("Nicht freigegebene Vorlagen-Dateien im Git (Commit abgebrochen):\n  " + "\n  ".join(problems[:40]))
                return 1
        else:
            print("\n".join(freigeben(root, args.name, lizenz_bestaetigt=args.lizenz_bestaetigt, dry_run=args.probelauf)))
    except PolicyError as error:
        print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
