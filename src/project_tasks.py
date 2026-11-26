from __future__ import annotations

import importlib.util
import json
import os
import re
import signal
import shlex
import shutil
import sys
import tempfile
import time
from pathlib import Path
from subprocess import DEVNULL, CalledProcessError, TimeoutExpired, run

from invoke import task
import yaml


SRC_DIR = Path(__file__).resolve().parent
from material_core import workspace  # noqa: E402

CODE_DIR = SRC_DIR.parent
ROOT_DIR = workspace.root()
sys.path.insert(0, str(SRC_DIR))
import foerder_online  # noqa: E402  (liegt in src/)
from material_core.import_helpers import slugify  # noqa: E402
import pdf_erschliessung  # noqa: E402  (liegt in src/)
from material_core.builds import BuildFailure, BuildService
from material_core.filesystem import atomic_write_text, text_revision
from material_core.metadata import output_filename, read_metadata, set_fields, split_frontmatter
from quarto_render_guard import managed_render_environment
QUARTO = os.environ.get("QUARTO", "quarto")
PDFLATEX = os.environ.get("PDFLATEX", "pdflatex")
PDFTOCAIRO = os.environ.get("PDFTOCAIRO", "pdftocairo")
MARKDOWNLINT = os.environ.get("MARKDOWNLINT", "npx --yes markdownlint-cli2")
MARKDOWNLINT_TIMEOUT = int(os.environ.get("MARKDOWNLINT_TIMEOUT", "20"))
BUILD_DIR_NAME = "build"
PDF_DIR_NAME = "pdf"
ARTEFAKT_DIR_NAME = "artefakte"
QUARTO_CONFIG = "_quarto.yml"
SCRATCH_ARTIFACT_DIRS = [
    Path("build") / "scratch" / "temp",
    Path("build") / "scratch" / "wissen-autoerschliessen",
    Path("build") / "scratch" / "audit",
]
CLEAN_OUTPUT_ROOTS = [Path("unterricht"), Path("wissen")]
CLEAN_OUTPUT_DIR_NAMES = {BUILD_DIR_NAME, PDF_DIR_NAME}
ARTIFACT_SUFFIXES = {
    ".aux",
    ".fdb_latexmk",
    ".fls",
    ".lof",
    ".log",
    ".lot",
    ".out",
    ".pdf",
    ".synctex.gz",
    ".tex",
    ".toc",
    ".typ",
}


def _source_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    return path if path.is_absolute() else ROOT_DIR / path


def _build_hint(output: Path) -> str:
    """inv-build-Angabe mit relativem Pfad; ausserhalb des Repos bleibt er absolut."""
    relative = output.relative_to(ROOT_DIR) if output.is_relative_to(ROOT_DIR) else output
    return f"inv build --source {relative}"


def _run(command: list[str], *, cwd: Path = ROOT_DIR, **kwargs):
    options = {"check": True, **kwargs}
    if command[:2] in ([QUARTO, "render"], [QUARTO, "preview"]):
        options["env"] = {**managed_render_environment(), **options.get("env", {})}
    return run(command, cwd=cwd, **options)


def _configured_output_file(source_path: Path) -> Path:
    return BuildService(ROOT_DIR, _run).configured_output_file(source_path)


def _render_patterns() -> list[str]:
    config_path = ROOT_DIR / QUARTO_CONFIG
    if not config_path.exists():
        return ["**/*.qmd", "!**/*-old.qmd", "!**/*-entwurf.qmd"]
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    render = config.get("project", {}).get("render", [])
    if isinstance(render, str):
        return [render]
    return [str(pattern) for pattern in render]


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Quarto-Glob-Semantik: * ueberschreitet keine Verzeichnisgrenze, ** beliebig tief."""
    pattern = pattern.lstrip("/")
    regex: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("/**/", index):
            regex.append("(?:/.*)?/")
            index += 4
        elif pattern.startswith("**/", index):
            regex.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            regex.append(".*")
            index += 2
        elif pattern[index] == "*":
            regex.append("[^/]*")
            index += 1
        else:
            end = index
            while end < len(pattern) and pattern[end] != "*":
                end += 1
            regex.append(re.escape(pattern[index:end]))
            index = end
    return re.compile("".join(regex))


def _pattern_matches(path: Path, pattern: str) -> bool:
    rel = path.relative_to(ROOT_DIR).as_posix()
    return _glob_regex(pattern).fullmatch(rel) is not None


def _is_excluded_material(path: Path) -> bool:
    """Altmaterial-Ausschluss (frueher per Negations-Glob in _quarto.yml)."""
    parts = path.relative_to(ROOT_DIR).parts
    return path.stem.endswith(("-old", "-entwurf")) or "alt" in parts


def _is_configured_qmd_source(path: Path, patterns: list[str] | None = None) -> bool:
    if path.suffix != ".qmd" or path.name.startswith("material-ui-render-"):
        return False
    if any(part.startswith(".") for part in path.relative_to(ROOT_DIR).parts):
        return False
    if _is_excluded_material(path):
        return False
    patterns = patterns if patterns is not None else _render_patterns()
    included = any(
        _pattern_matches(path, pattern)
        for pattern in patterns
        if not pattern.startswith("!")
    )
    excluded = any(
        _pattern_matches(path, pattern[1:])
        for pattern in patterns
        if pattern.startswith("!")
    )
    return included and not excluded


def _qmd_sources() -> list[Path]:
    patterns = _render_patterns()
    return sorted(
        source_path
        for source_path in ROOT_DIR.glob("**/*.qmd")
        if _is_configured_qmd_source(source_path, patterns)
    )


def _output_relpath(source_path: Path) -> Path:
    return source_path.parent.relative_to(ROOT_DIR)


def _build_dir(source_path: Path) -> Path:
    return ROOT_DIR / BUILD_DIR_NAME / ARTEFAKT_DIR_NAME / _output_relpath(source_path)


def _pdf_dir(source_path: Path) -> Path:
    return ROOT_DIR / BUILD_DIR_NAME / PDF_DIR_NAME / _output_relpath(source_path)


def _artifact_candidates(source_path: Path) -> set[Path]:
    return BuildService(ROOT_DIR, _run).artifact_candidates(source_path)


def _is_build_artifact_file(path: Path) -> bool:
    return path.is_file() and (
        path.suffix in ARTIFACT_SUFFIXES or path.name.endswith(".synctex.gz")
    )


def _is_build_artifact_dir(path: Path) -> bool:
    return path.is_dir() and path.name.endswith("_files")


def _is_build_artifact(path: Path) -> bool:
    return _is_build_artifact_file(path) or _is_build_artifact_dir(path)


def _generated_artifacts_in_dir(directory: Path) -> set[Path]:
    if not directory.exists():
        return set()
    return {
        artifact_path
        for artifact_path in directory.iterdir()
        if _is_build_artifact(artifact_path)
    }


def _relocate_build_artifacts(sources: list[Path], existing: set[Path] | None = None) -> None:
    return BuildService(ROOT_DIR, _run).relocate_build_artifacts(sources, existing)


def _generated_outputs() -> set[Path]:
    outputs: set[Path] = set()
    for source_path in _qmd_sources():
        outputs.update(_artifact_candidates(source_path))
        for artifact_path in _artifact_candidates(source_path):
            outputs.add(_build_dir(source_path) / artifact_path.name)
            outputs.add(_pdf_dir(source_path) / artifact_path.name)
        build_dir = _build_dir(source_path)
        pdf_dir = _pdf_dir(source_path)
        outputs.update(_generated_artifacts_in_dir(build_dir))
        outputs.update(_generated_artifacts_in_dir(pdf_dir))
    return outputs


def _cleanup_targets(*, include_scratch: bool) -> set[Path]:
    targets: set[Path] = {
        ROOT_DIR / ".quarto",
    }
    build_root = ROOT_DIR / BUILD_DIR_NAME
    if include_scratch:
        # Scratch-Ordner liegen unter build/scratch/: beim Komplett-Entfernen
        # von build/ reicht der Wurzelpfad, sie sind darin enthalten.
        targets.add(build_root)
    elif build_root.exists():
        # Ohne --artefakte bleibt build/scratch/ unberuehrt (bewusst nicht
        # automatisch entfernte Scratch-/Debug-Ausgaben); alles andere unter
        # build/ ist regulaeres, jederzeit regenerierbares Build-Artefakt.
        scratch_root = build_root / "scratch"
        targets.update(path for path in build_root.iterdir() if path != scratch_root)
    if include_scratch:
        targets.update(ROOT_DIR / path for path in SCRATCH_ARTIFACT_DIRS)
    for root in CLEAN_OUTPUT_ROOTS:
        root_path = ROOT_DIR / root
        if root_path.exists():
            targets.update(
                path
                for path in root_path.rglob("*")
                if path.is_dir() and path.name in CLEAN_OUTPUT_DIR_NAMES
            )
    targets.update(output_path for output_path in _generated_outputs() if output_path.exists())
    for source_path in _qmd_sources():
        for output_dir in (_build_dir(source_path), _pdf_dir(source_path)):
            if output_dir.exists() and not any(output_dir.iterdir()):
                targets.add(output_dir)
    return targets


def _remove_cleanup_targets(targets: set[Path], *, dry_run: bool) -> None:
    existing = sorted(
        {path for path in targets if path.exists()},
        key=lambda path: (
            -len(path.relative_to(ROOT_DIR).parts) if path.is_relative_to(ROOT_DIR) else 0,
            path.relative_to(ROOT_DIR).as_posix() if path.is_relative_to(ROOT_DIR) else str(path),
        ),
    )
    if dry_run:
        if not existing:
            print("Keine aufraeumbaren Build-Artefakte gefunden.")
            return
        print("Wuerde folgende Build-Artefakte entfernen:")
        for path in existing:
            print(f"  - {path.relative_to(ROOT_DIR)}")
        return
    for path in existing:
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _tikz_svg_sources() -> list[Path]:
    sources: list[Path] = []
    for source_path in ROOT_DIR.glob("**/assets/*.tex"):
        if any(part.startswith(".") for part in source_path.relative_to(ROOT_DIR).parts):
            continue
        if source_path.stem.endswith("-lib"):
            continue
        if not re.search(r"^\s*\\documentclass\b", source_path.read_text(encoding="utf-8"), re.MULTILINE):
            continue
        sources.append(source_path)
    return sorted(sources)


def _build_tikz_svg_assets() -> None:
    for source_path in _tikz_svg_sources():
        output_path = source_path.with_suffix(".svg")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run(
                [
                    PDFLATEX,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-output-directory",
                    str(tmp_path),
                    str(source_path.name),
                ],
                cwd=source_path.parent,
                check=True,
                stdout=DEVNULL,
            )
            pdf_path = tmp_path / f"{source_path.stem}.pdf"
            _run([
                PDFTOCAIRO,
                "-svg",
                str(pdf_path),
                str(output_path),
            ])


def _is_standalone_tex(source_path: Path) -> bool:
    """Eigenstaendig baubares LaTeX-Dokument?

    Entweder mit eigener documentclass oder als Instanz, die per \\input/\\include
    eine Vorlage einbindet (z. B. Elternbriefe: 2526/brief.tex inputet
    templates/elternbrief-template.tex).
    """
    text = source_path.read_text(encoding="utf-8")
    if re.search(r"^\s*\\documentclass\b", text, re.MULTILINE):
        return True
    return bool(re.search(r"^\s*\\(?:input|include)\{", text, re.MULTILINE))


def _git_ignored(paths: list[Path]) -> set[Path]:
    """Gitignore-Filter fuer die Quell-Entdeckung (archiv/, _eingang/, private Bestaende)."""
    if not paths:
        return set()
    try:
        result = run(
            ["git", "-C", str(ROOT_DIR), "check-ignore", "--stdin", "-z"],
            input="\0".join(str(path) for path in paths),
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return set()
    if result.returncode not in (0, 1):
        return set()
    return {Path(line) for line in result.stdout.split("\0") if line}


def _tex_sources() -> list[Path]:
    """Eigenstaendige LaTeX-Dokumente (z. B. Elternbriefe) als inv-build-Quellen.

    TikZ-Zeichnungen unter assets/, Quarto-Templates unter src/ und Vorlagen unter
    templates/ (gebaut werden ihre Instanzen) zaehlen nicht dazu; Fragmente ohne
    documentclass und ohne \\input-Wurzel sind Includes, keine Dokumente.
    """
    candidates: list[Path] = []
    for source_path in ROOT_DIR.glob("**/*.tex"):
        parts = source_path.relative_to(ROOT_DIR).parts
        if any(part.startswith(".") for part in parts):
            continue
        if BUILD_DIR_NAME in parts or "assets" in parts or "src" in parts or "templates" in parts:
            continue
        if _is_excluded_material(source_path):
            continue
        if not _is_standalone_tex(source_path):
            continue
        candidates.append(source_path)
    ignored = _git_ignored(candidates)
    return sorted(path for path in candidates if path not in ignored)


def _build_tex_document(source_path: Path) -> Path:
    """Eigenstaendiges LaTeX-Dokument per pdflatex in den zentralen Build-Ordner bauen.

    Hilfsdateien (.aux, .log, ...) bleiben unter build/artefakte/<quellpfad>/,
    das PDF wandert nach build/pdf/<quellpfad>/.
    """
    output_dir = _build_dir(source_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    _run(
        [
            PDFLATEX,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory",
            str(output_dir),
            str(source_path.name),
        ],
        cwd=source_path.parent,
    )
    pdf_path = output_dir / f"{source_path.stem}.pdf"
    if not pdf_path.is_file():
        raise SystemExit(f"pdflatex hat kein PDF erzeugt: {source_path}")
    pdf_dir = _pdf_dir(source_path)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    target = pdf_dir / pdf_path.name
    pdf_path.replace(target)
    return target


BUILD_MANIFEST_NAME = ".build-manifest.json"
# Frischepruefung: nur echte Build-Rueckstaende ignorieren, .tex/.pdf zaehlen als Eingaben.
FRESHNESS_IGNORE_SUFFIXES = {
    ".aux",
    ".fdb_latexmk",
    ".fls",
    ".lof",
    ".log",
    ".lot",
    ".out",
    ".synctex.gz",
    ".toc",
    ".typ",
}


def _build_manifest_path() -> Path:
    return ROOT_DIR / BUILD_DIR_NAME / BUILD_MANIFEST_NAME


def _load_build_manifest() -> dict:
    try:
        return json.loads(_build_manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _store_build_manifest(manifest: dict) -> None:
    path = _build_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def _manifest_eintrag_setzen(manifest: dict, source_path: Path, revision: str, pdf_path: Path | None) -> None:
    key = source_path.relative_to(ROOT_DIR).as_posix()
    eintrag = {"revision": revision}
    if source_path.suffix in {".qmd", ".md"}:
        eintrag["render_signature"] = BuildService(ROOT_DIR, _run).render_signature(
            source_path, source_path.read_text(encoding="utf-8"))
    if pdf_path is not None:
        eintrag["pdf"] = pdf_path.relative_to(ROOT_DIR).as_posix() if pdf_path.is_relative_to(ROOT_DIR) else str(pdf_path)
    manifest[key] = eintrag


def _inputs_neuer_als_pdf(source_path: Path, pdf_path: Path) -> bool:
    """True, wenn im Quellordner (ohne Build-Rueckstaende) etwas neuer ist als das PDF.

    Deckt neben der Quelle selbst auch Includes, Assets und Bilder im Quellordner.
    Zentrale Templates und Filter prüft _build_ist_aktuell zusätzlich über die
    Render-Signatur.
    """
    if not pdf_path.is_file():
        return True
    pdf_mtime = pdf_path.stat().st_mtime
    for directory, subdirectories, filenames in os.walk(source_path.parent):
        subdirectories[:] = [
            name
            for name in subdirectories
            if not name.startswith(".") and name not in {BUILD_DIR_NAME, PDF_DIR_NAME, "node_modules"} and not name.endswith("_files")
        ]
        for name in filenames:
            if name.startswith("material-ui-render-"):
                continue
            path = Path(directory) / name
            if path.suffix in FRESHNESS_IGNORE_SUFFIXES:
                continue
            if path.stat().st_mtime > pdf_mtime:
                return True
    return False


def _build_ist_aktuell(manifest: dict, source_path: Path) -> bool:
    """Nur bei unveränderter Quelle, Render-Signatur und lokalen Inputs überspringen."""
    eintrag = manifest.get(source_path.relative_to(ROOT_DIR).as_posix())
    if not eintrag:
        return False
    try:
        revision = text_revision(source_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if eintrag.get("revision") != revision:
        return False
    if source_path.suffix in {".qmd", ".md"}:
        signature = BuildService(ROOT_DIR, _run).render_signature(
            source_path, source_path.read_text(encoding="utf-8"))
        if eintrag.get("render_signature") != signature:
            return False
    pdf_rel = eintrag.get("pdf")
    if not pdf_rel:
        return False
    pdf_path = Path(pdf_rel)
    if not pdf_path.is_absolute():
        pdf_path = ROOT_DIR / pdf_path
    return not _inputs_neuer_als_pdf(source_path, pdf_path)


@task(name="build-assets")
def build_assets(_ctx) -> None:
    """Compile TikZ drawing assets to SVG."""
    _build_tikz_svg_assets()


@task(name="editor-bundle")
def editor_bundle(_ctx) -> None:
    """Build the CodeMirror editor bundle for material-ui (src/editor-app -> static/editor.bundle.js)."""
    _run(["npm", "run", "build"], cwd=CODE_DIR / "src" / "editor-app")


PYTHON_PACKAGE_MODULES = [
    ("flask", "Material-UI"),
    ("ruamel.yaml", "course-sync"),
    ("playwright", "Moodle-Upload"),
    ("fitz", "PDF-Verarbeitung (pymupdf)"),
    ("numpy", "Zeichnungen"),
    ("yaml", "Build-Konfiguration (PyYAML)"),
]


def _doctor_findings() -> list[tuple[str, bool, bool, str]]:
    """Umgebungspruefung als (Label, ok, erforderlich, Hinweis)-Liste."""
    findings: list[tuple[str, bool, bool, str]] = []

    def add(label: str, ok: bool, hint: str = "", required: bool = True) -> None:
        findings.append((label, ok, required, hint))

    add(
        f"Python {sys.version_info.major}.{sys.version_info.minor} (>= 3.12)",
        sys.version_info >= (3, 12),
        "Python 3.12 oder neuer installieren: https://www.python.org/downloads/",
    )
    from material_core import systemcheck

    manager = systemcheck.detect_manager()
    for tool in systemcheck.check_tools():
        if tool["key"] in {"python", "venv"}:
            continue  # Python wird oben bzw. ueber die Paketpruefung abgedeckt
        plan = systemcheck.install_plan([tool], manager)
        command = systemcheck.install_command(plan)
        hint = command or tool.get("hint", "") or ("AUR: " + " ".join(plan["aur"]) if plan["aur"] else "")
        add(
            f"{tool['key']} ({tool['purpose']})",
            tool["ok"],
            hint,
            required=tool["level"] in systemcheck.REQUIRED_LEVELS,
        )
    missing_modules = [
        name for name, _purpose in PYTHON_PACKAGE_MODULES if importlib.util.find_spec(name) is None
    ]
    add(
        "Python-Pakete installiert (inv setup)",
        not missing_modules,
        "pip install -e . im Repo-Root ausfuehren (oder inv setup)"
        + (f"; fehlt: {', '.join(missing_modules)}" if missing_modules else ""),
    )
    add(
        "Schulportal-Anmeldung (sph_login, nur fuer Moodle-Ziele mit Schulportal)",
        importlib.util.find_spec("sph_login") is not None,
        "optional: inv setup --schulportal (installiert src/sph_login)",
        required=False,
    )
    playwright_browsers = Path.home() / ".cache" / "ms-playwright"
    add(
        "Playwright-Browser",
        any(playwright_browsers.glob("chromium*")),
        "playwright install chromium (noetig fuer Moodle-Uploads)",
        required=False,
    )
    add(
        ".env (Moodle-Zugangsdaten)",
        (ROOT_DIR / ".env").is_file(),
        "cp .env.example .env und Moodle-Zugangsdaten eintragen (noetig fuer Moodle-Uploads)",
        required=False,
    )
    return findings


@task(name="doctor")
def doctor(_ctx) -> None:
    """Pruefe alle benoetigten Werkzeuge; bei Fehlendem erscheint ein Installationshinweis."""
    findings = _doctor_findings()
    missing_required = 0
    for label, ok, required, hint in findings:
        state = "ok" if ok else ("FEHLT" if required else "fehlt")
        print(f"  [{state:>5}] {label}")
        if not ok and hint:
            print(f"          -> {hint}")
        if not ok and required:
            missing_required += 1
    if missing_required:
        raise SystemExit(
            f"{missing_required} erforderliche(s) Werkzeug(e) fehlen -- Installation siehe Hinweise oben."
        )
    print("Alle erforderlichen Werkzeuge sind vorhanden.")


def _project_python() -> str:
    """Python-Interpreter des Projekts: .venv, falls vorhanden, sonst der laufende."""
    venv_python = CODE_DIR / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def _pip_install_editable(schulportal: bool = False, entwicklung: bool = False) -> None:
    """Installiert das Projekt; `entwicklung` mit Testwerkzeugen, `schulportal` mit src/sph_login."""
    target = ".[dev]" if entwicklung else "."
    packages = ["-e", target] + (["-e", "src/sph_login"] if schulportal else [])
    venv_pip = CODE_DIR / ".venv" / "bin" / "pip"
    if venv_pip.exists():
        _run([str(venv_pip), "install", *packages], cwd=CODE_DIR)
        return
    try:
        _run([sys.executable, "-m", "pip", "install", *packages], cwd=CODE_DIR)
    except CalledProcessError:
        raise SystemExit(
            f"pip install -e '{target}' ist gescheitert. Ist die Python-Umgebung 'externally managed'\n"
            "(PEP 668, z. B. Arch Linux, Debian 12+)? Dann ein virtuelles Environment anlegen:\n"
            "  python3 -m venv .venv\n"
            f"  .venv/bin/pip install -e '{target}'\n"
            "Anschliessend setup wiederholen und Tasks ueber .venv/bin/inv ... aufrufen."
        ) from None


@task(
    name="setup",
    optional=["skip-h5p", "skip-playwright", "schulportal", "entwicklung"],
    help={
        "skip-h5p": "H5P-Libraries nicht herunterladen",
        "skip-playwright": "Playwright-Browser nicht installieren",
        "schulportal": "Optional: Schulportal-Anmeldung (src/sph_login) fuer Moodle-Ziele installieren",
        "entwicklung": "Zusaetzlich die Testwerkzeuge installieren (pip-Extra dev)",
    },
)
def setup(ctx, skip_h5p: bool = False, skip_playwright: bool = False, schulportal: bool = False,
          entwicklung: bool = False) -> None:
    """Projekt einmalig einrichten: Python-Paket, .env, H5P-Libraries, Playwright, dann doctor."""
    if workspace.installed():
        print("1/4 Paketinstallation: Python-Pakete kommen vom Paketmanager.")
    else:
        print(f"1/4 Installiere Python-Paket (pip install -e '{'.[dev]' if entwicklung else '.'}'"
              + (" -e src/sph_login" if schulportal else "") + ") ...")
        _pip_install_editable(schulportal, entwicklung)
    env_path = ROOT_DIR / ".env"
    if not env_path.exists() and (CODE_DIR / ".env.example").is_file():
        shutil.copy(CODE_DIR / ".env.example", env_path)
        print("2/4 .env aus .env.example angelegt -- Moodle-Zugangsdaten eintragen (nur fuer Moodle noetig).")
    else:
        print("2/4 .env bereits vorhanden -- nichts zu tun.")
    if skip_h5p:
        print("3/4 H5P-Libraries uebersprungen (--skip-h5p).")
    else:
        print("3/4 Lade H5P-Libraries (inv kurse.update-h5p-libraries) ...")
        import course_sync_tasks

        course_sync_tasks.update_h5p_libraries(ctx)
    if skip_playwright or importlib.util.find_spec("playwright") is None:
        print("4/4 Playwright-Browser uebersprungen.")
    else:
        print("4/4 Installiere Playwright-Browser (chromium) ...")
        _run([_project_python(), "-m", "playwright", "install", "chromium"])
    print("Setup abgeschlossen. Umgebungspruefung:")
    doctor(ctx)


def _teaching_qmd_sources() -> list[Path]:
    return list((ROOT_DIR / "unterricht").rglob("*.qmd"))


@task(name="template-versions-check")
def template_versions_check(_ctx) -> None:
    """Validate frozen releases and reject edits to already tracked versions."""
    _run([_project_python(), "-m", "material_core.template_versions", "check", "--root", str(ROOT_DIR)])


@task(name="template-versions-migrate", help={"write": "Versionsbindungen in QMDs speichern; sonst nur Bericht"})
def template_versions_migrate(_ctx, write=False) -> None:
    """Freeze template defaults and pin existing QMDs to v1."""
    command = [_project_python(), "-m", "material_core.template_versions", "migrate", "--root", str(ROOT_DIR)]
    if write:
        command.append("--write")
    _run(command)


@task(name="check-output-layout")
def check_output_layout(_ctx) -> None:
    """Reject misplaced PDF and Typst build artifacts, including ignored files."""
    service = BuildService(ROOT_DIR, _run)
    misplaced = set()
    for source in _teaching_qmd_sources():
        if source.name.startswith("material-ui-render-"):
            continue
        if any(part.startswith(".") or part in {BUILD_DIR_NAME, PDF_DIR_NAME, "assets"} for part in source.relative_to(ROOT_DIR).parts):
            continue
        candidates = {source.with_suffix(".pdf"), service.configured_output_file(source)}
        candidates.update(source.parent / PDF_DIR_NAME / path.name for path in list(candidates))
        misplaced.update(path for path in candidates if path.suffix == ".pdf" and path.is_file())
    for directory, subdirectories, filenames in os.walk(ROOT_DIR):
        subdirectories[:] = [name for name in subdirectories if not name.startswith(".") and name not in {BUILD_DIR_NAME, "node_modules", "__pycache__"}]
        misplaced.update(Path(directory) / name for name in filenames if name.endswith(".typ") and not name.startswith("material-ui-render-"))
    for directory, subdirectories, filenames in os.walk(ROOT_DIR / "unterricht"):
        subdirectories[:] = [name for name in subdirectories if not name.startswith(".")]
        misplaced.update(Path(directory) / name for name in filenames if name.endswith(".pdf"))
    if misplaced:
        paths = "\n".join(f"  {path.relative_to(ROOT_DIR)}" for path in sorted(misplaced))
        raise SystemExit(
            "Falsch abgelegte Build-Artefakte gefunden "
            f"(PDF: {BUILD_DIR_NAME}/{PDF_DIR_NAME}/, .typ: {BUILD_DIR_NAME}/{ARTEFAKT_DIR_NAME}/;\n"
            "PDF-Quellen und importierte Original-PDFs gehoeren in die Wissensbasis unter wissen/ "
            "und werden mit `inv pdf-erschliessen` dorthin verschoben):\n"
            f"{paths}\nMit inv build --source <pfad.qmd> bauen."
        )
    print(f"Ausgabeablage korrekt: PDFs in {BUILD_DIR_NAME}/{PDF_DIR_NAME}/, .typ-Dateien in {BUILD_DIR_NAME}/{ARTEFAKT_DIR_NAME}/.")


@task(name="build", optional=["source", "alles"])
def build(_ctx, source: str | None = None, alles: bool = False, template_update: str = "ask") -> None:
    """Build QMDs (Quarto) and standalone LaTeX documents (.tex) into build/pdf/; unchanged sources are skipped (--alles rebuilds)."""
    from material_core.template_updates import review_before_build
    from invoke.exceptions import Exit
    if template_update not in {"ask", "keep", "latest"}:
        raise Exit("--template-update muss ask, keep oder latest sein.", code=2)
    source_path = _source_path(source)
    if source_path is not None and source_path.suffix == ".tex":
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        manifest = _load_build_manifest()
        if not alles and _build_ist_aktuell(manifest, source_path):
            print(f"= {source_path.relative_to(ROOT_DIR)} (unveraendert, PDF aktuell)")
            return
        pdf = _build_tex_document(source_path)
        print(f"PDF: {pdf.relative_to(ROOT_DIR)}")
        _manifest_eintrag_setzen(manifest, source_path, text_revision(source_path.read_text(encoding="utf-8")), pdf)
        _store_build_manifest(manifest)
        return
    service = BuildService(ROOT_DIR, _run)
    manifest = {} if alles else _load_build_manifest()
    veraendert = False
    sources = [source_path] if source_path is not None else _qmd_sources()
    for document in sources:
        if not document.is_file():
            raise FileNotFoundError(document)
        try:
            review_before_build(ROOT_DIR, document, template_update)
        except (ValueError, EOFError) as error:
            raise Exit(str(error) or "Template-Entscheidung abgebrochen.", code=2) from error
        if not alles and _build_ist_aktuell(manifest, document):
            print(f"= {document.relative_to(ROOT_DIR)} (unveraendert, PDF aktuell)")
            continue
        try:
            result = service.build_document(document, quarto=QUARTO)
        except BuildFailure as error:
            if error.result.stdout:
                print(error.result.stdout)
            raise
        if result.stdout:
            print(result.stdout)
        _manifest_eintrag_setzen(manifest, document, result.source_revision, result.pdf_path)
        veraendert = True
    if source_path is None:
        for tex_source in _tex_sources():
            if not alles and _build_ist_aktuell(manifest, tex_source):
                print(f"= {tex_source.relative_to(ROOT_DIR)} (unveraendert, PDF aktuell)")
                continue
            pdf = _build_tex_document(tex_source)
            print(f"PDF: {pdf.relative_to(ROOT_DIR)}")
            _manifest_eintrag_setzen(manifest, tex_source, text_revision(tex_source.read_text(encoding="utf-8")), pdf)
            veraendert = True
    if veraendert:
        _store_build_manifest(manifest)


@task(name="layout-pruefen", optional=["source"])
def layout_pruefen(_ctx, source: str | None = None) -> None:
    """Gebaute PDFs gegen die Original-PDFs der Erschliessung pruefen (Seitenzahl, -format, Bildplatzierung)."""
    import layout_regression

    service = BuildService(ROOT_DIR, _run)
    if source is not None:
        qmds = [_source_path(source)]
    else:
        qmds = [
            path
            for path in sorted(ROOT_DIR.glob("unterricht/**/*.qmd"))
            if not path.name.startswith("material-ui-render-")
            and not any(part.startswith(".") for part in path.relative_to(ROOT_DIR).parts)
        ]
    berichte = []
    for qmd in qmds:
        if qmd is None or not qmd.is_file():
            raise FileNotFoundError(qmd)
        referenz = layout_regression.source_pdf_referenz(qmd.read_text(encoding="utf-8"))
        if referenz is None:
            if source is not None:
                raise SystemExit(f"{qmd} hat keine material.import.source-pdf-Referenz im Frontmatter.")
            continue
        original = ROOT_DIR / referenz
        try:
            gebaut = service.expected_pdf(qmd)
        except ValueError:
            gebaut = None
        berichte.append(layout_regression.pruefe_dokument(qmd, gebaut, original))
    if not berichte:
        print("Keine QMDs mit source-pdf-Referenz gefunden.")
        return
    fehler = 0
    for bericht in berichte:
        if bericht.status == "ok":
            print(f"[ok] {bericht.quelle}")
        elif bericht.status == "offen":
            print(f"[offen] {bericht.quelle} -- noch nicht gebaut (inv build --source <pfad>)")
        elif bericht.status == "original-fehlt":
            fehler += 1
            print(f"[original-fehlt] {bericht.quelle}")
        else:
            fehler += 1
            print(f"[abweichung] {bericht.quelle}")
            for abweichung in bericht.abweichungen:
                print(f"    - {abweichung.art}: {abweichung.detail}")
    if fehler:
        raise SystemExit(f"{fehler} Dokument(e) mit Abweichungen oder fehlendem Original.")
    print(f"{len(berichte)} Dokument(e) geprueft, keine Abweichungen.")


@task(name="material-index")
def material_index(_ctx) -> None:
    """Textindex ueber den erschlossenen PDF-Bestand (wissen/) neu bauen: build/material-index.json."""
    import material_suche

    index = material_suche.baue_index(ROOT_DIR / "wissen")
    ohne_text = sum(dokument["ohne_text"] for dokument in index["dokumente"].values())
    print(
        f"Index gebaut: {len(index['dokumente'])} PDF(s) aus wissen/_pdf-erschliessung.json, "
        f"{ohne_text} Seite(n) ohne Text (Scan? OCR mit inv wissen-ocr noetig)."
    )


@task(name="material-suche", positional=["begriff"], optional=["limit", "aktualisieren"])
def material_suche_task(_ctx, begriff: str, limit: int = 20, aktualisieren: bool = False) -> None:
    """Erschlossene PDFs der Wissensbasis durchsuchen (baut den Index, falls er fehlt; --aktualisieren erzwingt Neubau)."""
    import material_suche

    index = material_suche.lade_index(ROOT_DIR)
    if index is None or aktualisieren:
        index = material_suche.baue_index(ROOT_DIR / "wissen")
    treffer = material_suche.suche(index, begriff, int(limit))
    if not treffer:
        print("Keine Treffer.")
        return
    for treffer in treffer:
        print(f"[{treffer.pfad} · Seite {treffer.seite}]\n    {treffer.ausschnitt}")


@task(
    name="deck",
    optional=["source", "force"],
    help={
        "source": "Pfad zur Markdown-Outline (## = Folie, Bullets = Text, ![]() = Bild)",
        "force": "Existierendes Deck bewusst neu generieren (annotierte Decks gehen verloren)",
    },
)
def deck(_ctx, source: str | None = None, force: bool = False) -> None:
    """Excalidraw-Deck aus einer Markdown-Outline erzeugen (One-Shot-Scaffold)."""
    from excalideck.generator import DeckExistsError, generate_deck

    source_path = _source_path(source)
    if source_path is None or not source_path.is_file():
        raise FileNotFoundError(source_path or "<outline fehlt>")
    output = BuildService(ROOT_DIR, _run).build_dir(source_path) / f"{source_path.stem}.excalidraw"
    try:
        output = generate_deck(source_path, output_path=output, force=force)
    except DeckExistsError as error:
        raise SystemExit(
            f"{error.path} existiert bereits und wird nicht ueberschrieben "
            "(annotierte Decks sind die Quelle der Wahrheit). "
            "Mit --force bewusst neu generieren."
        ) from error
    print(f"Deck erzeugt: {output}")


@task(
    name="deck-print",
    optional=["source", "force"],
    help={
        "source": "Pfad zur Markdown-Outline (## = Folie, Bullets = Text, ![]() = Bild)",
        "force": "Existierende QMD bewusst neu generieren (manuelle Aenderungen gehen verloren)",
    },
)
def deck_print(_ctx, source: str | None = None, force: bool = False) -> None:
    """Druckbare QMD aus einer Markdown-Outline erzeugen (baubar mit inv build)."""
    from excalideck.printable import PrintableExistsError, generate_printable

    source_path = _source_path(source)
    if source_path is None or not source_path.is_file():
        raise FileNotFoundError(source_path or "<outline fehlt>")
    try:
        output = generate_printable(source_path, force=force)
    except PrintableExistsError as error:
        raise SystemExit(
            f"{error.path} existiert mit abweichendem Inhalt und wird nicht ueberschrieben "
            "(manuelle Aenderungen bleiben erhalten). Mit --force bewusst neu generieren."
        ) from error
    print(f"Druckbare QMD erzeugt: {output}")
    print(f"Drucken mit: {_build_hint(output)}")


@task(
    name="deck-slides",
    optional=["source", "force"],
    help={
        "source": "Pfad zur Markdown-Outline (## = Folie, Bullets = Text, ![]() = Bild)",
        "force": "Existierende Slide-QMD bewusst neu generieren (manuelle Aenderungen gehen verloren)",
    },
)
def deck_slides(_ctx, source: str | None = None, force: bool = False) -> None:
    """Slide-QMD (16:9, Excalidraw-aehnliche Schrift) aus einer Outline erzeugen."""
    from excalideck.printable import PrintableExistsError, generate_printable

    source_path = _source_path(source)
    if source_path is None or not source_path.is_file():
        raise FileNotFoundError(source_path or "<outline fehlt>")
    try:
        output = generate_printable(source_path, force=force, variant="slides")
    except PrintableExistsError as error:
        raise SystemExit(
            f"{error.path} existiert mit abweichendem Inhalt und wird nicht ueberschrieben "
            "(manuelle Aenderungen bleiben erhalten). Mit --force bewusst neu generieren."
        ) from error
    print(f"Slide-QMD erzeugt: {output}")
    print(f"Rendern mit: {_build_hint(output)}")


@task(
    name="deck-present",
    optional=["port", "rebuild"],
    help={
        "port": "Port des lokalen Servers (Standard: 4180)",
        "rebuild": "App neu bauen, auch wenn dist/ bereits existiert",
    },
)
def deck_present(_ctx, port: int = 4180, rebuild: bool = False) -> None:
    """Present-App fuer Excalidraw-Decks bauen und lokal ausliefern (Strg+C beendet)."""
    app_dir = SRC_DIR / "excalideck" / "present"
    dist_dir = app_dir / "dist"
    if rebuild or not (dist_dir / "index.html").is_file():
        if not (app_dir / "node_modules").is_dir():
            _run(["npm", "install"], cwd=app_dir)
        _run(["npm", "run", "build"], cwd=app_dir)
    print(f"Present-App: http://127.0.0.1:{port}/  (Strg+C beendet den Server)")
    print("Deck ueber 'Oeffnen' laden oder .excalidraw ins Fenster ziehen;")
    print("PageDown/PageUp = Folie weiter/zurueck, Zeichnen jederzeit moeglich.")
    _run(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "-d", str(dist_dir)]
    )


@task(
    name="foerder-online",
    optional=["ziel"],
    help={
        "ziel": "Zielordner (Standard: $FOERDER_ONLINE_ZIEL oder build/foerder-online)",
        "build": "Fehlende und veraltete PDFs vorher über den verwalteten Build neu bauen",
        "loesungen": "Musterlösungen zusätzlich in je einen Unterordner Loesungen kopieren",
        "alles": "Auch Ordner kopieren, die online (noch) nicht vorkommen (ueberschlag, unterrichtsmaterial)",
        "aufraeumen": "PDFs im Ziel löschen, die nicht mehr zur Quelle gehören",
        "trocken": "Nur anzeigen, nichts bauen, kopieren oder löschen",
    },
)
def foerder_online_cmd(
    _ctx,
    ziel: str | None = None,
    build: bool = False,
    loesungen: bool = False,
    alles: bool = False,
    aufraeumen: bool = False,
    trocken: bool = False,
) -> None:
    """Fördermaterial online: PDFs in die Ordnerstruktur der Online-Plattform kopieren."""
    ziel_pfad = Path(ziel or os.environ.get("FOERDER_ONLINE_ZIEL") or ROOT_DIR / foerder_online.ZIEL_STANDARD)
    if not ziel_pfad.is_absolute():
        ziel_pfad = ROOT_DIR / ziel_pfad
    plan = foerder_online.plane(ROOT_DIR, ziel_pfad, loesungen=loesungen, alles=alles)

    zu_bauen = [e for e in plan.eintraege if e.fehlt or e.veraltet]
    if build and zu_bauen:
        quellen = sorted({e.qmd for e in zu_bauen})
        print(f"Baue {len(quellen)} Datei(en) neu, nacheinander ...")
        if not trocken:
            service = BuildService(ROOT_DIR, _run)
            for quelle in quellen:
                print(f"  Baue {quelle.relative_to(ROOT_DIR)}")
                service.build_document(quelle, quarto=QUARTO)
            plan = foerder_online.plane(ROOT_DIR, ziel_pfad, loesungen=loesungen, alles=alles)

    ergebnis = foerder_online.kopiere(plan, trocken=trocken)
    entfernt = foerder_online.aufraeumen(plan, ziel_pfad, trocken=trocken) if aufraeumen else []

    marke = " (trocken)" if trocken else ""
    print(f"Ziel: {ziel_pfad}{marke}")
    print(f"  kopiert: {len(ergebnis['kopiert'])}, unverändert: {len(ergebnis['unveraendert'])}, "
          f"gelöscht: {len(entfernt)}")
    for pfad in ergebnis["kopiert"]:
        print(f"  + {pfad.relative_to(ziel_pfad)}")
    for pfad in entfernt:
        print(f"  - {pfad.relative_to(ziel_pfad)}")
    if plan.uebersprungen:
        print("Nicht in der Online-Struktur (mit --alles mitkopieren):")
        for pfad in plan.uebersprungen:
            print(f"  {pfad.relative_to(ROOT_DIR)}")
    veraltet = [e for e in plan.eintraege if e.veraltet]
    if veraltet:
        print("WARNUNG: PDF älter als Quelltext oder Header (mit --build neu bauen):")
        for e in veraltet:
            print(f"  {e.pdf.relative_to(ROOT_DIR)}")
    if ergebnis["fehlend"]:
        print("FEHLER: PDF fehlt (mit --build bauen):")
        for pfad in ergebnis["fehlend"]:
            print(f"  {pfad.relative_to(ROOT_DIR)}")
        raise SystemExit(1)


@task(name="preview", optional=["source"], positional=["source"])
def preview(_ctx, source: str = "unterricht/informatik/klasse-11/klausuren/klausur-e2-25-26/klausur-e2.qmd") -> None:
    """Start a Quarto preview for one document."""
    _build_tikz_svg_assets()
    source_path = _source_path(source)
    if source_path is None or not source_path.exists():
        raise FileNotFoundError(source_path)
    _relocate_build_artifacts([source_path])
    existing = {path for path in _artifact_candidates(source_path) if path.exists()}
    try:
        _run([QUARTO, "preview", str(source_path.relative_to(ROOT_DIR))])
    finally:
        _relocate_build_artifacts([source_path], existing)


@task(name="material-ui-install")
def material_ui_install(_ctx) -> None:
    """Install Material UI launcher and QMD file association for the current user."""
    from material_ui.desktop import install

    install()


@task(name="material-ui-server")
def material_ui_server(_ctx, action: str = "status") -> None:
    """Manage the local app server: status, start, stop or restart."""
    if action not in {"status", "start", "stop", "restart"}:
        raise ValueError("Erlaubt: status, start, stop, restart")
    from material_ui.desktop import manage_server

    manage_server(action)


@task(name="material-ui", optional=["host", "port"], help={"no_open": "Browser nicht automatisch öffnen"})
def material_ui(_ctx, host: str = "127.0.0.1", port: int = 8765, no_open: bool = False, debug: bool = False) -> None:
    """Start the local worksheet material import web app."""
    _restart_existing_material_ui(host, int(port))
    try:
        from material_ui.app import run as run_material_ui
    except ModuleNotFoundError as error:
        if error.name == "flask":
            raise SystemExit("Flask fehlt. Installiere es z. B. mit: python -m pip install flask") from None
        raise
    run_material_ui(host=host, port=port, open_browser=not no_open, debug=debug)


@task(
    name="import-onlyoffice",
    optional=["source", "ziel"],
    help={
        "source": "DOCX-Datei oder Ordner mit DOCX-Dateien",
        "ziel": "Zielordner fuer die erzeugten QMDs",
        "overwrite": "Vorhandene QMDs ueberschreiben",
        "no_draft": "Keinen editierbaren Pandoc-Entwurf erzeugen",
        "no_validate": "Nicht rendern und Seitenzahl nicht pruefen",
    },
)
def import_onlyoffice(
    _ctx,
    source: str = "_eingang/onlyoffice",
    ziel: str = "unterricht/mathematik/klasse-10/trigonometrie/arbeitsblaetter",
    overwrite: bool = False,
    no_draft: bool = False,
    no_validate: bool = False,
) -> None:
    """Onlyoffice-DOCX seitenstabil nach QMD importieren."""
    _require_plugin("office")
    from material_ui.plugins.office import converter

    source_path = _source_path(source)
    ziel_pfad = _source_path(ziel)
    if source_path is None or ziel_pfad is None:
        raise FileNotFoundError(source or ziel)
    sources = converter._docx_sources(source_path)
    if not sources:
        raise SystemExit(f"Keine DOCX-Dateien gefunden: {source_path}")
    for docx in sources:
        result = converter.import_docx(
            docx,
            ziel_pfad,
            overwrite=overwrite,
            draft=not no_draft,
            validate=not no_validate,
        )
        status = f"{result.source_pages} Seite(n)"
        if result.rendered_pages is not None:
            status += f", validiert: {result.rendered_pages}"
        print(f"+ {result.qmd.relative_to(ROOT_DIR)} ({status})")
        if result.draft_qmd is not None:
            print(f"  Entwurf: {result.draft_qmd.relative_to(ROOT_DIR)}")


def _verlinse_importierte_pdfs(qmd_ordner: Path, ziel_rel: str, trocken: bool) -> None:
    ziel_dir = ROOT_DIR / pdf_erschliessung.WISSEN_DIR_NAME / ziel_rel.strip("/")
    verlinkt = 0
    for qmd in sorted(qmd_ordner.glob("*.qmd")):
        try:
            metadata = read_metadata(qmd.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        material = metadata.get("material")
        import_block = material.get("import") if isinstance(material, dict) else None
        quelle = import_block.get("source") if isinstance(import_block, dict) else None
        if not isinstance(quelle, str) or not quelle.endswith(".docx"):
            continue
        slug = slugify(Path(quelle).stem)
        pdf = ziel_dir / f"{slug}.pdf"
        if not pdf.is_file():
            continue
        referenz = pdf.relative_to(ROOT_DIR).as_posix()
        if trocken:
            print(f"  wuerde verlinken: {qmd.relative_to(ROOT_DIR)} -> source-pdf: {referenz}")
        else:
            pdf_erschliessung.verlinse_import_pdf(qmd, referenz)
            print(f"  verlinkt: {qmd.relative_to(ROOT_DIR)} -> source-pdf: {referenz}")
        verlinkt += 1
    print(f"{verlinkt} QMD(s) mit source-pdf-Referenz {'versehen' if not trocken else 'zu versehen'}.")


@task(
    name="pdf-erschliessen",
    optional=["quelle", "ziel", "verlinken"],
    help={
        "quelle": "PDF-Datei oder Ordner mit PDFs (Standard: _eingang)",
        "ziel": "Zielordner unter wissen/ (z. B. arbeitsblatt/mathematik/klasse-10/trigonometrie)",
        "trocken": "Nur anzeigen, was erschlossen wuerde",
        "verlinken": "QMD-Ordner, dessen material.import-Quellen auf die erschlossenen PDFs verlinkt werden",
    },
)
def pdf_erschliessen(
    _ctx,
    quelle: str = "_eingang",
    ziel: str = "",
    trocken: bool = False,
    verlinken: str = "",
) -> None:
    """PDFs nach wissen/<ziel>/ erschliessen; identische PDFs werden nur einmal gespeichert."""
    if not ziel.strip():
        raise SystemExit("Zielordner unter wissen/ fehlt, z. B. --ziel arbeitsblatt/mathematik/klasse-10/trigonometrie")
    quelle_pfad = _source_path(quelle)
    if quelle_pfad is None or not quelle_pfad.exists():
        raise FileNotFoundError(quelle or ziel)
    pdfs = [quelle_pfad] if quelle_pfad.is_file() else sorted(quelle_pfad.rglob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"Keine PDF-Dateien gefunden: {quelle_pfad}")
    erschlossen = 0
    dubletten = 0
    for pdf in pdfs:
        ergebnis = pdf_erschliessung.erschliessen(pdf, ziel, trocken=trocken)
        if ergebnis.status == pdf_erschliessung.STATUS_DUPLIKAT:
            dubletten += 1
            print(f"= {pdf.relative_to(ROOT_DIR)} -> Dublikat von {ergebnis.duplikat_von.relative_to(ROOT_DIR)}")
        elif ergebnis.status == pdf_erschliessung.STATUS_TROCKEN:
            print(f"~ wuerde erschliessen: {pdf.relative_to(ROOT_DIR)} -> {ergebnis.ziel.relative_to(ROOT_DIR)}")
        else:
            erschlossen += 1
            print(f"+ {ergebnis.ziel.relative_to(ROOT_DIR)}")
    if trocken:
        print(f"{erschlossen} PDF(s) wuerden erschlossen, {dubletten} Dublette(n) uebersprungen.")
    else:
        print(f"{erschlossen} PDF(s) erschlossen, {dubletten} Dublette(n) uebersprungen.")
    if verlinken:
        qmd_ordner = _source_path(verlinken)
        if qmd_ordner is None or not qmd_ordner.is_dir():
            raise FileNotFoundError(verlinken)
        _verlinse_importierte_pdfs(qmd_ordner, ziel, trocken)


def _restart_existing_material_ui(host: str, port: int) -> None:
    pids = _listening_pids(port)
    if not pids:
        return
    own_pids = [pid for pid in pids if _is_material_ui_process(pid)]
    unknown_pids = sorted(set(pids) - set(own_pids))
    if unknown_pids:
        rendered = ", ".join(str(pid) for pid in unknown_pids)
        raise SystemExit(f"Port {host}:{port} ist durch einen fremden Prozess belegt: {rendered}")
    for pid in sorted(set(own_pids)):
        print(f"Beende laufende Material-UI auf {host}:{port} (PID {pid}) ...")
        _terminate_process(pid)


def _listening_pids(port: int) -> list[int]:
    if shutil.which("lsof"):
        result = run(
            ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
        )
        return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]
    return _listening_pids_from_proc(port)


def _listening_pids_from_proc(port: int) -> list[int]:
    inodes: set[str] = set()
    port_hex = f"{port:04X}"
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        if not table.exists():
            continue
        for line in table.read_text(encoding="utf-8").splitlines()[1:]:
            columns = line.split()
            if len(columns) < 10:
                continue
            local_address, state, inode = columns[1], columns[3], columns[9]
            if state == "0A" and local_address.rsplit(":", 1)[-1] == port_hex:
                inodes.add(inode)
    if not inodes:
        return []
    pids: set[int] = set()
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            # Fremde Prozesse (andere Benutzer) lassen ihre Dateideskriptoren nicht lesen.
            descriptors = list((proc / "fd").iterdir())
        except OSError:
            continue
        for fd in descriptors:
            try:
                target = fd.readlink()
            except OSError:
                continue
            match = re.fullmatch(r"socket:\[(\d+)\]", str(target))
            if match and match.group(1) in inodes:
                pids.add(int(proc.name))
                break
    return sorted(pids)


def _is_material_ui_process(pid: int) -> bool:
    proc = Path("/proc") / str(pid)
    try:
        cwd = proc.joinpath("cwd").resolve()
        command = proc.joinpath("cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return False
    # Der eigene Server ist an seinem Pfad erkennbar, auch mit frueher anderem Inhaltsordner.
    if str(CODE_DIR / "src/material_ui/desktop.py") in command:
        return True
    if cwd not in {ROOT_DIR, CODE_DIR}:
        return False
    return "material-ui" in command or "material_ui.app" in command


def _terminate_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(20):
        if not (Path("/proc") / str(pid)).exists():
            return
        time.sleep(0.1)
    os.kill(pid, signal.SIGKILL)


@task(
    name="konventionen",
    help={
        "pfad": "Ordner oder QMD-Datei (Standard: unterricht)",
        "regel": "Nur diese Regel anzeigen, z. B. ueberschrift-trenner",
        "kurz": "Nur die Zusammenfassung je Regel ausgeben",
        "streng": "Mit Fehlercode enden, wenn klare Verstoesse (Warnungen) vorliegen",
    },
)
def konventionen(_ctx, pfad: str = "unterricht", regel: str = "", kurz: bool = False, streng: bool = False) -> None:
    """Material-Konventionen aus AGENTS.md pruefen (dieselben Regeln wie die Editor-Diagnose)."""
    from collections import Counter

    from material_core.conventions import scan

    target = Path(pfad)
    target = target if target.is_absolute() else ROOT_DIR / target
    if not target.exists():
        raise SystemExit(f"Pfad nicht gefunden: {pfad}")
    results = [row for row in scan(target) if not regel or row[2].code == regel]
    if not kurz:
        for path, line, finding in results:
            try:
                shown = path.relative_to(ROOT_DIR)
            except ValueError:
                shown = path
            marker = "!" if finding.level == "warning" else "i"
            print(f"{shown}{f':{line}' if line else ''}: {marker} [{finding.code}] {finding.title}")
    summary = Counter((finding.code, finding.level) for _path, _line, finding in results)
    files = Counter()
    for code in {code for code, _level in summary}:
        files[code] = len({path for path, _line, finding in results if finding.code == code})
    for (code, level), count in sorted(summary.items()):
        label = "Verstoesse" if level == "warning" else "Hinweise"
        print(f"{count:5d} {label:10s} {code} ({files[code]} Datei{'' if files[code] == 1 else 'en'})")
    warnings = sum(count for (_code, level), count in summary.items() if level == "warning")
    print(f"{warnings} klare Verstoesse, {len(results) - warnings} Hinweise zum Pruefen.")
    if streng and warnings:
        raise SystemExit(1)


HOOK_MARKER = "# Von `inv konventionen-hook` erzeugt."


@task(
    name="konventionen-hook",
    help={
        "pfad": "Arbeitskopie des Materialbestands (Standard: unterricht)",
        "entfernen": "Den pre-commit-Hook wieder entfernen",
    },
)
def konventionen_hook(_ctx, pfad: str = "unterricht", entfernen: bool = False) -> None:
    """Git-pre-commit im Materialrepo installieren: Commits mit klaren Konventionsverstoessen abbrechen."""
    target = Path(pfad)
    target = target if target.is_absolute() else ROOT_DIR / target
    git_dir = target / ".git"
    if not git_dir.is_dir():
        raise SystemExit(f"Kein Git-Repo gefunden: {target}")
    hook = git_dir / "hooks" / "pre-commit"
    if hook.exists() and HOOK_MARKER not in hook.read_text(encoding="utf-8", errors="replace"):
        raise SystemExit(f"Fremder pre-commit-Hook vorhanden, nicht ueberschrieben: {hook}")
    if entfernen:
        hook.unlink(missing_ok=True)
        print(f"Hook entfernt: {hook}")
        return
    guard = CODE_DIR / "src" / "material_core" / "conventions_guard.py"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n"
        f"{HOOK_MARKER}\n"
        "# Prueft nur die Dateien dieses Commits; Umgehen bewusst mit `git commit --no-verify`.\n"
        'root="$(git rev-parse --show-toplevel)"\n'
        "git diff --cached --name-only --diff-filter=ACMR -z \\\n"
        f'  | xargs -0 -r python3 -I "{guard}" files --root "$root"\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    print(f"Hook installiert: {hook}")


OSS_HOOK_MARKER = "# Von `inv oss-hook` erzeugt."


@task(name="templates-pruefen")
def templates_pruefen(_ctx) -> None:
    """Pruefen, dass in den eingebauten Vorlagenordnern nur ausdruecklich freigegebene Dateien liegen."""
    from material_core import template_policy

    problems = template_policy.check(CODE_DIR)
    if problems:
        raise SystemExit("Vorlagen-Richtlinie verletzt:\n  " + "\n  ".join(problems))
    print("Eingebaute Vorlagen entsprechen src/quarto/builtin-templates.json.")


@task(
    name="template-freigeben",
    help={
        "name": "Name der privaten Vorlage ohne Endung, z. B. worksheet-meine-vorlage",
        "lizenz-bestaetigt": "Ausdrueckliche Bestaetigung: Vorlage, Grafiken, Namen und Schriften sind frei verwendbar",
        "probelauf": "Nur Abhaengigkeiten und Pruefung anzeigen, nichts verschieben",
    },
    optional=["lizenz-bestaetigt", "probelauf"],
)
def template_freigeben(_ctx, name: str, lizenz_bestaetigt: bool = False, probelauf: bool = False) -> None:
    """Eine private Vorlage ausdruecklich in den eingebauten (versionierbaren) Bestand aufnehmen."""
    from material_core import template_policy

    try:
        if ROOT_DIR != CODE_DIR:
            raise SystemExit("Vorlagen freigeben: private Vorlage zuerst nach src/quarto/_local/ im "
                             f"Programmverzeichnis {CODE_DIR} legen und mit MATERIAL_HOME={CODE_DIR} ausfuehren.")
        for line in template_policy.freigeben(ROOT_DIR, name, lizenz_bestaetigt=lizenz_bestaetigt, dry_run=probelauf):
            print(line)
    except template_policy.PolicyError as error:
        raise SystemExit(str(error)) from None


@task(name="oss-pruefen", help={"staged": "Nur fuer den Commit vorgemerkte Dateien pruefen"}, optional=["staged"])
def oss_pruefen(_ctx, staged: bool = False) -> None:
    """Versionierten Bestand auf private Pfade, Namen, Zugangsdaten und nicht freigegebene Vorlagen pruefen."""
    from material_core import oss_check

    if oss_check.main(["--root", str(CODE_DIR), *(["--staged"] if staged else [])]):
        raise SystemExit(1)


@task(name="oss-hook", help={"entfernen": "Den pre-commit-Hook wieder entfernen"}, optional=["entfernen"])
def oss_hook(_ctx, entfernen: bool = False) -> None:
    """Git-pre-commit fuer das Werkzeug-Repo installieren: Commits mit privaten Inhalten abbrechen."""
    # `git rev-parse --git-path hooks` beruecksichtigt Worktrees (.git als Datei) und core.hooksPath.
    located = run(["git", "rev-parse", "--git-path", "hooks"], cwd=CODE_DIR, capture_output=True, text=True)
    if located.returncode != 0:
        raise SystemExit(f"Kein Git-Repo gefunden: {CODE_DIR}")
    hooks = Path(located.stdout.strip())
    hooks = hooks if hooks.is_absolute() else CODE_DIR / hooks
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    if hook.exists() and OSS_HOOK_MARKER not in hook.read_text(encoding="utf-8", errors="replace"):
        raise SystemExit(f"Fremder pre-commit-Hook vorhanden, nicht ueberschrieben: {hook}")
    if entfernen:
        hook.unlink(missing_ok=True)
        print(f"Hook entfernt: {hook}")
        return
    hook.write_text(
        "#!/bin/sh\n"
        f"{OSS_HOOK_MARKER}\n"
        "# Prueft die fuer den Commit vorgemerkten Dateien; Umgehen nur bewusst mit `git commit --no-verify`.\n"
        'root="$(git rev-parse --show-toplevel)"\n'
        'PYTHONPATH="$root/src" python3 -m material_core.oss_check --staged --root "$root" || exit 1\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    print(f"Hook installiert: {hook}")


@task(name="lint")
def lint(_ctx) -> None:
    """Run markdownlint-cli2 using the project configuration."""
    command = shlex.split(MARKDOWNLINT)
    try:
        run(command, cwd=ROOT_DIR, check=True, timeout=MARKDOWNLINT_TIMEOUT)
    except TimeoutExpired as exc:
        rendered = " ".join(command)
        raise SystemExit(
            f"markdownlint timed out after {MARKDOWNLINT_TIMEOUT}s: {rendered}"
        ) from exc


@task(
    name="clean",
    help={
        "trocken": "Nur anzeigen, welche Build-Artefakte entfernt wuerden",
        "artefakte": "Auch Scratch-Ordner unter build/scratch/ entfernen",
    },
)
def clean(_ctx, trocken: bool = False, artefakte: bool = False) -> None:
    """Delete generated Quarto build artifacts."""
    if not trocken:
        from material_ui.config import AppConfig
        from material_ui.worksheets import WorksheetStore
        WorksheetStore(AppConfig(ROOT_DIR)).migrate_all()
    _remove_cleanup_targets(_cleanup_targets(include_scratch=artefakte), dry_run=trocken)


def _legacy_output_dirs() -> list[tuple[Path, Path]]:
    """Alte pdf/- und build/-Ordner neben dem Material, mit zentralem Zielordner.

    Kurs-Builds (unterricht/kurse/*/build), der Vorlagen-Katalog
    (wissen/*/vorlagen/build) und der foerder-online-Zielordner bleiben
    unberuehrt: beides ist selbst zusammengehoeriger Bestand, kein verstreutes
    Einzeldokument bzw. keine QMD-Build-Ausgabe.
    """
    pairs: list[tuple[Path, Path]] = []
    for root in CLEAN_OUTPUT_ROOTS:
        root_path = ROOT_DIR / root
        if not root_path.exists():
            continue
        for directory in sorted(root_path.rglob("*")):
            if not directory.is_dir() or directory.name not in CLEAN_OUTPUT_DIR_NAMES:
                continue
            relative = directory.relative_to(ROOT_DIR).parts
            if relative[:2] == ("unterricht", "kurse"):
                continue
            if "vorlagen" in relative and directory.name == BUILD_DIR_NAME:
                continue
            if Path(*relative) == foerder_online.ZIEL_STANDARD:
                continue
            relpath = directory.relative_to(ROOT_DIR).parent
            target_name = PDF_DIR_NAME if directory.name == PDF_DIR_NAME else ARTEFAKT_DIR_NAME
            pairs.append((directory, ROOT_DIR / BUILD_DIR_NAME / target_name / relpath))
    return pairs


def _migrate_legacy_dir(source_dir: Path, target_dir: Path, *, dry_run: bool) -> list[Path]:
    moved: list[Path] = []
    if not source_dir.is_dir():
        return moved
    for path in sorted(source_dir.rglob("*"), reverse=True):
        if path.is_symlink():
            continue
        if path.is_dir():
            if not dry_run and not any(path.iterdir()):
                path.rmdir()
            continue
        destination = target_dir / path.relative_to(source_dir)
        if destination.exists() and destination.stat().st_mtime >= path.stat().st_mtime:
            if not dry_run:
                path.unlink()
        elif not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.replace(destination)
        moved.append(destination)
    if not dry_run and source_dir.is_dir() and not any(source_dir.iterdir()):
        source_dir.rmdir()
    return moved


def _rewrite_manifest_paths(manifest: Path) -> bool:
    """Artifact-Eintraege in .material-ui.json auf die zentralen Pfade umschreiben."""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    rewritten = []
    for entry in data.get("artifacts", []):
        parts = Path(entry).parts
        if len(parts) >= 3 and parts[-2] in {PDF_DIR_NAME, BUILD_DIR_NAME}:
            target = PDF_DIR_NAME if parts[-2] == PDF_DIR_NAME else ARTEFAKT_DIR_NAME
            rewritten.append(str(Path(BUILD_DIR_NAME, target, *parts[:-2], parts[-1])))
        else:
            rewritten.append(entry)
    if rewritten == list(data.get("artifacts", [])):
        return False
    data["artifacts"] = rewritten
    atomic_write_text(manifest, json.dumps(data, indent=2))
    return True


def _migrate_site_export(*, dry_run: bool) -> str | None:
    """Site-Export nach build/site verschieben und am alten Ort einen Symlink hinterlassen."""
    old_site = ROOT_DIR / "unterricht" / "kurse" / "build" / "site"
    new_site = ROOT_DIR / BUILD_DIR_NAME / "site"
    if not old_site.is_dir() or old_site.is_symlink():
        return None
    if dry_run:
        return f"{old_site.relative_to(ROOT_DIR)} -> {new_site.relative_to(ROOT_DIR)}"
    new_site.parent.mkdir(parents=True, exist_ok=True)
    if new_site.exists():
        raise SystemExit(f"Ziel existiert bereits: {new_site}. Bitte manuell zusammenfuehren.")
    old_site.replace(new_site)
    old_site.parent.mkdir(parents=True, exist_ok=True)
    old_site.symlink_to(f"../../../{BUILD_DIR_NAME}/site", target_is_directory=True)
    return f"{old_site.relative_to(ROOT_DIR)} -> {new_site.relative_to(ROOT_DIR)} (Symlink am alten Ort)"


@task(name="build-migrate", optional=["trocken"], help={"trocken": "Nur anzeigen, was verschoben wuerde"})
def build_migrate(_ctx, trocken: bool = False) -> None:
    """Alte pdf/- und build/-Ordner in den zentralen Build-Ordner (build/) verschieben."""
    moved_count = 0
    for source_dir, target_dir in _legacy_output_dirs():
        moved = _migrate_legacy_dir(source_dir, target_dir, dry_run=trocken)
        if moved:
            print(f"{'wuerde' if trocken else 'habe'} {len(moved)} Datei(en) {source_dir.relative_to(ROOT_DIR)} -> {target_dir.relative_to(ROOT_DIR)}")
            moved_count += len(moved)
    site_action = _migrate_site_export(dry_run=trocken)
    if site_action:
        print(site_action)
    if not trocken:
        for manifest in (ROOT_DIR / BUILD_DIR_NAME / ARTEFAKT_DIR_NAME).rglob("*.material-ui.json"):
            _rewrite_manifest_paths(manifest)
    if moved_count == 0 and site_action is None:
        print("Keine verstreuten Build-Ordner gefunden.")


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def _orphan_pdfs() -> list[Path]:
    """PDFs im zentralen Ordner, deren zugehoerige QMD-Quelle fehlt."""
    pdf_root = ROOT_DIR / BUILD_DIR_NAME / PDF_DIR_NAME
    if not pdf_root.exists():
        return []
    orphans: list[Path] = []
    for pdf in sorted(pdf_root.rglob("*.pdf")):
        source_folder = ROOT_DIR / pdf.relative_to(pdf_root).parent
        expected: set[str] | None = None
        if source_folder.is_dir():
            expected = set()
            for qmd in source_folder.glob("*.qmd"):
                expected.add(f"{qmd.stem}.pdf")
                try:
                    expected.add(output_filename(qmd.read_text(encoding="utf-8"), f"{qmd.stem}.pdf"))
                except ValueError:
                    continue
            for tex in source_folder.glob("*.tex"):
                expected.add(f"{tex.stem}.pdf")
        if expected is None or pdf.name not in expected:
            orphans.append(pdf)
    return orphans


def _stale_export_temps() -> list[Path]:
    """Verwaiste .course-export-*-Temps abgebrochener export-site-Laufe.

    Der Export selbst raeumt beim Start unter dem Workspace-Lock auf; dieser
    Helper greift, wenn seitdem kein Export lief. Junge Temps (jünger als einen
    Tag) bleiben liegen, um einen moeglicherweise laufenden Export nicht zu treffen.
    """
    temps: list[Path] = []
    for parent in (ROOT_DIR / BUILD_DIR_NAME, ROOT_DIR / "unterricht" / "kurse" / BUILD_DIR_NAME):
        if not parent.is_dir():
            continue
        for temp in sorted(parent.glob(".course-export-*")):
            if temp.is_dir() and time.time() - temp.stat().st_mtime > 86400:
                temps.append(temp)
    return temps


def _stale_render_caches() -> list[Path]:
    """Regenerierbare Render-Rueckstaende im Materialbaum: .quarto-Caches und *_files-Ordner."""
    caches: list[Path] = []
    for directory, subdirectories, _filenames in os.walk(ROOT_DIR / "unterricht"):
        treffer = [name for name in subdirectories if name == ".quarto" or name.endswith("_files")]
        caches.extend(Path(directory) / name for name in treffer)
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in treffer and not name.startswith(".") and name not in {BUILD_DIR_NAME, "node_modules"}
        ]
    return caches


@task(name="build-status")
def build_status(_ctx) -> None:
    """Groessen und Statistik des zentralen Build-Ordners anzeigen."""
    build_root = ROOT_DIR / BUILD_DIR_NAME
    if not build_root.exists():
        print("Zentraler Build-Ordner existiert noch nicht (noch nichts gebaut).")
        return
    for name in ("pdf", ARTEFAKT_DIR_NAME, "site"):
        area = build_root / name
        if area.exists():
            print(f"  {name + '/':<12} {_human_size(_dir_size(area))}")
    print(f"  {'gesamt':<12} {_human_size(_dir_size(build_root))}")
    pdfs = sorted((build_root / PDF_DIR_NAME).rglob("*.pdf"), key=lambda p: p.stat().st_size, reverse=True) if (build_root / PDF_DIR_NAME).exists() else []
    print(f"PDFs: {len(pdfs)}")
    if pdfs:
        print("Groesste PDFs:")
        for pdf in pdfs[:10]:
            print(f"  {_human_size(pdf.stat().st_size):>10}  {pdf.relative_to(ROOT_DIR)}")
    orphans = _orphan_pdfs()
    if orphans:
        print(f"Verwaiste PDFs (Quelle geloescht/umbenannt): {len(orphans)} -- aufraeumen mit: inv build-prune --trocken")
    export_temps = _stale_export_temps()
    if export_temps:
        print("Verwaiste Export-Temps abgebrochener export-site-Laeufe:")
        for temp in export_temps:
            print(f"  {_human_size(_dir_size(temp)):>10}  {temp.relative_to(ROOT_DIR)}")
        print("-- aufraeumen mit: inv build-prune --trocken")


@task(
    name="build-prune",
    optional=["aelter_als", "trocken"],
    help={
        "aelter_als": "Zusaetzlich PDFs loeschen, die aelter als X Tage sind (regenerierbar)",
        "trocken": "Nur anzeigen, was geloescht wuerde",
    },
)
def build_prune(_ctx, aelter_als: int | None = None, trocken: bool = False) -> None:
    """Verwaiste PDFs, Export-Temps und Render-Rueckstaende loeschen, optional auch alte PDFs."""
    pdf_root = ROOT_DIR / BUILD_DIR_NAME / PDF_DIR_NAME
    orphans = set(_orphan_pdfs())
    candidates: list[tuple[Path, str]] = []
    for pdf in sorted(pdf_root.rglob("*.pdf")):
        if pdf in orphans:
            candidates.append((pdf, "verwaist"))
        elif aelter_als is not None and time.time() - pdf.stat().st_mtime > aelter_als * 86400:
            candidates.append((pdf, f"aelter als {aelter_als} Tage"))
    for temp in _stale_export_temps():
        candidates.append((temp, "verwaister Export-Temp"))
    for cache in _stale_render_caches():
        candidates.append((cache, "Render-Rueckstand (.quarto/*_files)"))
    if not candidates:
        print("Nichts zu bereinigen.")
        return
    for path, reason in candidates:
        print(f"  - {path.relative_to(ROOT_DIR)} ({reason})")
    if trocken:
        print(f"{len(candidates)} Objekt(e) wuerden geloescht. Ausfuehren ohne --trocken.")
        return
    for path, _reason in candidates:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    for directory in sorted((path for path in pdf_root.rglob("*") if path.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    print(f"{len(candidates)} Objekt(e) geloescht.")


@task(name="wissen-update", optional=["fach"])
def wissen_update(_ctx, fach: str | None = None, no_index: bool = False, ocr: bool = False,
                  komprimieren: bool = False, bilder: bool = False) -> None:
    """Scan ressourcen/quellen/<fach>/, extract texts, refresh the index. --ocr reads scans, --komprimieren shrinks PDFs, --bilder extracts images."""
    if ocr:
        _require_plugin("ocr", "tesseract")
    if komprimieren:
        _require_plugin("ocr", "ghostscript")
    from wissensbasis import pipeline

    pipeline.update(fach, reindex=not no_index, ocr_all=ocr, compress=komprimieren, extract_images=bilder)


@task(name="wissen-web", positional=["url"], optional=["fach", "name"])
def wissen_web(_ctx, url: str, fach: str = "mathematik", name: str | None = None,
               no_update: bool = False) -> None:
    """Save a web page as a readable copy in ressourcen/quellen/<fach>/web/ and index it (--name sets the file name)."""
    from wissensbasis import pipeline, web
    from wissensbasis.config import discover

    subject = discover(fach)[0]
    _, status = web.holen(url, subject, name)
    if status != "unveraendert" and not no_update:
        pipeline.update(fach)


@task(name="wissen-status", optional=["fach"])
def wissen_status(_ctx, fach: str | None = None) -> None:
    """Show the state of the knowledge base without scanning."""
    from wissensbasis import pipeline

    pipeline.status(fach)


@task(name="wissen-ocr", optional=["fach", "match", "limit"])
def wissen_ocr(_ctx, fach: str | None = None, match: str | None = None, limit: int | None = None) -> None:
    """OCR scanned documents (flagged needs_ocr); --match narrows by path, --limit caps the document count."""
    _require_plugin("ocr", "tesseract")
    from wissensbasis import pipeline

    pipeline.ocr(fach, match, int(limit) if limit else None)


@task(name="wissen-komprimieren", optional=["fach", "match", "limit"])
def wissen_komprimieren(_ctx, fach: str | None = None, match: str | None = None, limit: int | None = None,
                        trocken: bool = False, erneut: bool = False) -> None:
    """Shrink PDFs (profile per Quellenart), test quality, replace the original and update hashes. --trocken changes nothing."""
    _require_plugin("ocr", "ghostscript", "tesseract")
    from wissensbasis import pipeline

    pipeline.compress(fach, match, int(limit) if limit else None, dry_run=trocken, again=erneut)


@task(name="wissen-bilder", optional=["fach", "match"])
def wissen_bilder(_ctx, fach: str | None = None, match: str | None = None, erneut: bool = False) -> None:
    """Extract embedded PDF images with page references into wissen/<fach>/bilder/. Use --match to narrow by source."""
    from wissensbasis import pipeline

    pipeline.images(fach, match, overwrite=erneut)


@task(name="wissen-test")
def wissen_test(ctx) -> None:
    """Run the automated tests of the knowledge base tooling."""
    ctx.run("python3 -m pytest src/tests/wissensbasis -q", pty=False)


@task(name="wissen-suche", positional=["query"], optional=["fach", "quellenart", "limit"])
def wissen_suche(_ctx, query: str, fach: str | None = None, quellenart: str | None = None,
                 limit: int = 10, karten: bool = False, ohne_literatur: bool = False) -> None:
    """Full-text search over sources, cards and dossiers (--karten: cards/dossiers only, --ohne-literatur: hide bibliography pages)."""
    from wissensbasis import index

    result = index.search(query, fach, quellenart, int(limit), only_notes=karten, without_references=ohne_literatur)
    if result.skipped:
        print(f"Zu kurz (unter 3 Zeichen), ignoriert: {', '.join(result.skipped)}")
    for term, extra in result.expanded.items():
        print(f"Erweitert: {term} -> {', '.join(extra)}")
    for hit in result.hits:
        place = hit.fundstelle
        note = " [Literaturverzeichnis]" if hit.literatur else ""
        print(f"[{hit.kind}] {hit.pfad} ({place}){note}\n    {hit.text}")
    if not result.hits:
        print("Keine Treffer.")


@task(name="wissen-lies", positional=["dokument"], optional=["fach", "von", "bis"])
def wissen_lies(_ctx, dokument: str, von: int = 1, bis: int | None = None, fach: str | None = None) -> None:
    """Print pages of a source (by id or part of its path), e.g. wissen-lies grundvorstellungen --von 2 --bis 4."""
    from wissensbasis import pipeline

    pipeline.read(dokument, int(von), int(bis) if bis else None, fach)


@task(name="wissen-check", optional=["fach"])
def wissen_check(_ctx, fach: str | None = None) -> None:
    """Validate dossiers and cards: tags, page ranges, quotes actually present on the cited page."""
    from wissensbasis import pipeline

    if pipeline.check_all(fach):
        raise SystemExit(1)


@task(name="wissen-aufnehmen", optional=["fach"])
def wissen_aufnehmen(_ctx, fach: str | None = None) -> None:
    """Neue Karten nach Prüfung aufnehmen oder zurückstellen."""
    from wissensbasis import pipeline

    if pipeline.apply_checks(fach, admit=True):
        raise SystemExit(1)


@task(name="wissen-freigeben", optional=["fach"])
def wissen_freigeben(_ctx, fach: str | None = None) -> None:
    """Fehlerfreie Dossiers, Karten und Vorlagen ausdrücklich freigeben."""
    from wissensbasis import pipeline

    if pipeline.apply_checks(fach, release=True):
        raise SystemExit(1)


@task(name="wissen-pflegen", optional=["fach"])
def wissen_pflegen(_ctx, fach: str | None = None) -> None:
    """Prüfen, aufnehmen, freigeben und einsortieren."""
    from wissensbasis import pipeline

    if pipeline.maintain_all(fach):
        raise SystemExit(1)


@task(name="wissen-sortieren", optional=["fach"])
def wissen_sortieren(_ctx, fach: str | None = None, trocken: bool = False) -> None:
    """Sort cards into karten/<bereich>/<quelle>/<name #kategorie #prioN>.md (auch Teil von wissen-pflegen)."""
    from wissensbasis import pipeline

    pipeline.sort_all(fach, trocken)


@task(name="wissen-auswahl", positional=["thema"], optional=["fach", "zweck", "klasse", "anzahl"],
      help={"thema": "Themen-Kürzel, Bereich (arithmetik) oder Stichwort", "zweck": "stundenentwurf, aufgaben, pruefen, foerdern"})
def wissen_auswahl(_ctx, thema: str, fach: str = "mathematik", zweck: str | None = None, klasse: int | None = None,
                   anzahl: int = 10) -> None:
    """The most important cards for a topic: lead sources first, then ranked by priority points."""
    from wissensbasis import pipeline

    pipeline.select(thema, fach, zweck, int(klasse) if klasse else None, int(anzahl))


@task(name="wissen-build", optional=["fach"])
def wissen_build(_ctx, fach: str | None = None) -> None:
    """Regenerate INDEX.md and the topic/principle/competence pages from the cards."""
    from wissensbasis import pipeline

    pipeline.build_all(fach)


@task(name="wissen-vorlagen-build", optional=["fach"], help={"ohne_pdf": "Nur den Katalog (.qmd) schreiben, nicht rendern"})
def wissen_vorlagen_build(_ctx, fach: str = "mathematik", ohne_pdf: bool = False) -> None:
    """Render all template examples with the Fördermaterial header into wissen/<fach>/vorlagen/build/vorlagen-katalog.pdf."""
    from wissensbasis.config import discover
    from wissensbasis import vorlagen

    for subject in discover(fach):
        built, problems = vorlagen.build(subject, render=not ohne_pdf)
        print(f"[{subject.name}] {len(built)} Vorlagen im Katalog {subject.vorlagen / vorlagen.BUILD_DIR}")
        for problem in problems:
            print(f"  WARNUNG: {problem}")


@task(
    name="wissen-autoerschliessen",
    optional=["fach", "match", "limit", "max_pages", "max_cards", "budget_usd"],
    help={
        "fach": "Fachordner, Standard: mathematik",
        "match": "Nur Quellen, deren ID oder Dossiertext diesen Begriff enthält",
        "limit": "Anzahl Quellenpakete in diesem Lauf",
        "max_pages": "Maximale Zahl noch nicht belegter Quellseiten pro Paket",
        "max_cards": "Maximale Zahl neuer Karten pro Paket",
        "llm": "Claude CLI aufrufen und JSON erzeugen",
        "apply": "LLM-Ergebnis anwenden, Karten/Dossier schreiben und prüfen",
        "no_build": "Nach erfolgreichem Check keinen wissen-build ausführen",
        "budget_usd": "Optionales Kostenlimit für claude -p",
    },
)
def wissen_autoerschliessen(
    _ctx,
    fach: str = "mathematik",
    match: str | None = None,
    limit: int = 1,
    max_pages: int = 18,
    max_cards: int = 6,
    llm: bool = False,
    apply: bool = False,
    no_build: bool = False,
    budget_usd: float | None = None,
) -> None:
    """Prepare or run semi-automatic source extraction for partially covered dossiers."""
    from wissensbasis import autoerschliessen

    autoerschliessen.run(
        fach,
        match=match,
        limit=int(limit),
        max_pages=int(max_pages),
        max_cards=int(max_cards),
        llm=llm,
        apply=apply,
        build=not no_build,
        budget_usd=float(budget_usd) if budget_usd is not None else None,
    )



@task(optional=["path"])
def test(_ctx, path: str = "src/tests") -> None:
    """Run the local test suite with pytest, including unittest test cases."""
    _run([sys.executable, "-m", "pytest", path, "-q"], cwd=CODE_DIR,
         env={**os.environ, workspace.ENV: str(CODE_DIR)})


@task(name="test-inhalte", help={"kurs": "Nur die Tests dieses Kurses"})
def test_inhalte(_ctx, kurs: str = "") -> None:
    """Tests der Inhalte: unterricht/kurse/<kurs>/tests und private Vorlagentests."""
    from material_core import content_tests

    if content_tests.run(ROOT_DIR, kurs, _project_python()):
        raise SystemExit("Inhaltstests fehlgeschlagen.")


_PLAIN_TAG = re.compile(r"^[A-Za-z0-9ÄÖÜäöüß][A-Za-z0-9ÄÖÜäöüß ._-]*$")


def insert_tags(text: str, tags: list) -> str:
    """Fuegt einen tags-Block ein, ohne den bestehenden Header neu zu formatieren.

    Im Gegensatz zu set_fields wird der YAML-Header nicht neu geschrieben; es
    wird nur der tags-Block textuell vor den schliessenden Begrenzer gesetzt.
    Tags mit Sonderzeichen fallen auf set_fields zurueck, da nur schlichte
    Skalare textuell sicher sind.
    """
    if not tags or not all(_PLAIN_TAG.match(tag) for tag in tags):
        return set_fields(text, {"tags": tags})
    block = "tags:\n" + "".join(f"  - {tag}\n" for tag in tags)
    parts = split_frontmatter(text)
    if parts is None:
        return f"---\n{block}---\n\n{text}"
    header = parts.header if parts.header.endswith("\n") else parts.header + "\n"
    if "\r\n" in parts.prefix or "\r\n" in parts.header:
        block = block.replace("\n", "\r\n")
    return f"{parts.prefix}{header}{block}{parts.closing}{parts.body}"


@task(
    name="tags-backfill",
    help={"trocken": "Nur anzeigen, welche Dateien einen tags-Eintrag erhielten, ohne zu schreiben"},
)
def tags_backfill(_ctx, trocken: bool = False) -> None:
    """Write path-derived tags (subject, class, topic, kind) into missing frontmatter tags entries."""
    from material_ui.assets import parse_tags
    from material_ui.documents import DocumentService, qmd_source_paths

    changed = 0
    skipped = 0
    for source in qmd_source_paths(ROOT_DIR):
        if source.is_relative_to(ROOT_DIR / "wissen"):
            continue
        try:
            text = source.read_text(encoding="utf-8")
            metadata = read_metadata(text)
        except (OSError, UnicodeDecodeError, ValueError) as error:
            skipped += 1
            print(f"  uebersprungen: {source.relative_to(ROOT_DIR)} ({error})")
            continue
        if parse_tags(metadata.get("tags")):
            continue
        parts = source.relative_to(ROOT_DIR).as_posix().split("/")
        candidates = [
            parts[1] if len(parts) > 1 else "",
            DocumentService.grade_part(parts),
            DocumentService.topic_part(parts),
            DocumentService.infer_kind(parts, source.name),
        ]
        tags = []
        for candidate in candidates:
            cleaned = candidate.strip()
            if cleaned and cleaned != source.name and cleaned != "Material" and cleaned not in tags:
                tags.append(cleaned)
        if not tags:
            continue
        if trocken:
            print(f"  wuerde taggen: {source.relative_to(ROOT_DIR)} -> {', '.join(tags)}")
        else:
            try:
                atomic_write_text(source, insert_tags(text, tags))
            except OSError as error:
                skipped += 1
                print(f"  uebersprungen: {source.relative_to(ROOT_DIR)} ({error})")
                continue
            print(f"  getaggt: {source.relative_to(ROOT_DIR)} -> {', '.join(tags)}")
        changed += 1
    summary = "wuerden ergaenzt" if trocken else "wurden ergaenzt"
    print(f"{changed} Dateien {summary}, {skipped} uebersprungen.")


@task(help={"source": "Gebautes A5-Querformat-PDF unter build/pdf/."})
def a5_druck(_ctx, source: str) -> None:
    """Jede A5-Seite zweimal auf ein A4-Druckblatt setzen (ohne Skalierung)."""
    from a5_druck import zwei_auf_eins

    path = _source_path(source)
    if path is None or not path.is_file():
        raise FileNotFoundError(path or "<PDF fehlt>")
    if not path.resolve().is_relative_to((ROOT_DIR / "build/pdf").resolve()):
        raise ValueError("Das PDF muss unter build/pdf/ liegen.")
    if path.stem.endswith("-2auf1"):
        raise ValueError("Die Datei ist bereits eine 2-auf-1-Druckfassung.")
    target = path.with_stem(path.stem + "-2auf1")
    print(zwei_auf_eins(path, target))


def _plugin_enabled_store():
    from material_ui.plugins.storage import PluginEnabledStore

    return PluginEnabledStore(ROOT_DIR / ".material-ui" / "plugins.json")


@task(name="plugin-list")
def plugin_list(_ctx) -> None:
    """Material-UI-Plugins mit Quelle, Version und Aktivierungszustand anzeigen."""
    from material_ui.plugins.manifest import discover_manifests
    from material_ui.plugins.paths import project_plugin_paths

    store = _plugin_enabled_store()
    rows = []
    for manifest, error in discover_manifests(tuple(project_plugin_paths(ROOT_DIR))):
        if manifest is None:
            rows.append(("-", "fehlerhaft", "-", "-", error or ""))
            continue
        enabled = store.is_enabled(manifest.id, default=manifest.active_by_default)
        rows.append((manifest.id, manifest.source, "aktiv" if enabled else "aus", manifest.version, manifest.name))
    if not rows:
        print("Keine Plugins gefunden.")
        return
    print("Eine Aktivierungsänderung wirkt erst nach einem Neustart der Material-UI.")
    for plugin_id, source, state, version, name in sorted(rows):
        print(f"{plugin_id:<16} {source:<8} {state:<5} {version:<8} {name}")


def _set_plugin_enabled(plugin_id: str, enabled: bool) -> None:
    from material_ui.plugins.manifest import ID_PATTERN, discover_manifests
    from material_ui.plugins.paths import project_plugin_paths

    if not ID_PATTERN.fullmatch(plugin_id or ""):
        raise ValueError(f"Ungültige Plugin-ID: {plugin_id!r}")
    with _marketplace().operation_lock():
        known = {manifest.id: manifest for manifest, _error in discover_manifests(tuple(project_plugin_paths(ROOT_DIR))) if manifest is not None}
        if plugin_id not in known:
            raise ValueError(f"Unbekanntes Plugin: {plugin_id}")
        _plugin_enabled_store().set_enabled(plugin_id, enabled)
    print(f"{plugin_id} ist jetzt {'aktiviert' if enabled else 'deaktiviert'}. "
          "Der Material-UI-Server muss neu gestartet werden.")
    if enabled:
        _print_missing_programs(known[plugin_id])


def _print_missing_programs(manifest) -> None:
    from material_core import systemcheck

    tools = [systemcheck.requirement_tool(manifest.id, item) for item in manifest.system_requirements]
    absent = systemcheck.missing(systemcheck.check_tools(tools))
    if not absent:
        return
    print("Noch fehlende Programme: " + ", ".join(tool["key"] for tool in absent))
    plan = systemcheck.install_plan(absent, systemcheck.detect_manager())
    if command := systemcheck.install_command(plan):
        print(f"  {command}")
    for key, hint in plan["manual"]:
        print(f"  {key}: {hint}")


def _require_plugin(plugin_id: str, *keys: str) -> None:
    """Bricht verstaendlich ab, wenn das Plugin aus ist oder ihm eines der genannten Programme fehlt."""
    from material_core import plugin_state

    try:
        plugin_state.require(plugin_id, *keys)
    except plugin_state.PluginUnavailable as error:
        raise SystemExit(str(error)) from None


@task(name="plugin-enable", positional=["plugin_id"])
def plugin_enable(_ctx, plugin_id: str) -> None:
    """Ein Material-UI-Plugin aktivieren (wirkt nach Serverneustart)."""
    _set_plugin_enabled(plugin_id, True)


@task(name="plugin-disable", positional=["plugin_id"])
def plugin_disable(_ctx, plugin_id: str) -> None:
    """Ein Material-UI-Plugin deaktivieren (wirkt nach Serverneustart)."""
    _set_plugin_enabled(plugin_id, False)


def _marketplace():
    from material_ui.plugins.marketplace import Marketplace

    return Marketplace(ROOT_DIR)


@task(name="plugin-refresh")
def plugin_refresh(_ctx) -> None:
    """Marketplace-Katalog (git) klonen bzw. aktualisieren."""
    info = _marketplace().refresh()
    suffix = f" — {info['warning']}" if info.get("warning") else ""
    print(f"Katalog {info['repo']} @ {(info.get('commit') or '?')[:12]}{suffix}")


@task(name="plugin-install", positional=["plugin_id"])
def plugin_install(_ctx, plugin_id: str, version: str = "*", no_refresh: bool = False) -> None:
    """Plugin aus dem Marketplace installieren (Abhängigkeiten inklusive, auto-aktiviert)."""
    result = _marketplace().install(plugin_id, version, refresh=not no_refresh)
    for action in result["actions"]:
        print(f"{action['action']:>9}  {action['id']} {action['version']}  {action.get('name') or ''}")
    print("Die Installation wirkt nach einem Neustart der Material-UI.")


@task(name="plugin-uninstall", positional=["plugin_id"])
def plugin_uninstall(_ctx, plugin_id: str, purge: bool = False, force: bool = False) -> None:
    """Installiertes Marketplace-Plugin deinstallieren (--purge löscht auch gespeicherte Daten)."""
    result = _marketplace().uninstall(plugin_id, purge=purge, force=force)
    print(f"{result['removed']} deinstalliert (Daten {'gelöscht' if result['purged'] else 'behalten'}). "
          "Wirkt nach einem Neustart der Material-UI.")


@task(name="plugin-update")
def plugin_update(_ctx, plugin_id: str = "all", no_refresh: bool = False) -> None:
    """Marketplace-Plugins aktualisieren (einzeln oder alle)."""
    result = _marketplace().update(plugin_id, refresh=not no_refresh)
    for action in result["actions"]:
        print(f"{action['action']:>9}  {action['id']} {action['version']}  {action.get('name') or ''}")
    print("Updates wirken nach einem Neustart der Material-UI.")
