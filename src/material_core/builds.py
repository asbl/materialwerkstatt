from __future__ import annotations

import os
import io
import re
import shutil
import subprocess
import tempfile
import time
import json
import hashlib
import threading
from collections import OrderedDict
import pymupdf
from collections.abc import Mapping
from pathlib import Path

from material_core.filesystem import atomic_write_text, text_revision
from material_core.render_inputs import render_content
from quarto_render_guard import managed_render_environment
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from material_core.metadata import enforce_min_fontsize, output_filename, read_metadata, split_frontmatter, template_value, yaml_parser
from material_core import template_roots

ASSET_FOLDER = "assets"
# Zentraler Build-Ordner auf Repo-Ebene: alle PDFs unter build/pdf/, alle
# sonstigen Build-Artefakte unter build/artefakte/, jeweils gespiegelt nach
# Quellpfad. BUILD_FOLDER/PDF_FOLDER bleiben als Legacy-Ablagen fuer
# bestehende Ordner neben der Quelle (Rueckfall in find_pdf).
OUTPUT_ROOT = "build"
OUTPUT_PDF_DIR = "pdf"
OUTPUT_ARTIFACT_DIR = "artefakte"
BUILD_FOLDER = "build"
PDF_FOLDER = "pdf"
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


@dataclass(frozen=True)
class BuildResult:
    pdf_path: Path | None
    source_revision: str
    command: list[str]
    stdout: str
    returncode: int | None


class BuildFailure(ValueError):
    def __init__(self, message: str, result: BuildResult) -> None:
        super().__init__(message)
        self.result = result


def _concurrent_render_race(output: str, own_copy: Path) -> bool:
    """Renderfehler durch eine parallel verschwundene Renderkopie einer anderen Baustelle.

    Quartos Projektkontext listet Eingabedateien in zwei getrennten Verzeichnis-
    laeufen (Include- und Exclude-Globs). Eine Renderkopie, die zwischen diesen
    Laeufen angelegt oder entfernt wird, bleibt ohne Exclude-Ausschluss in der
    Include-Liste und laesst den Render mit NotFound scheitern. Ein erneuter
    Versuch loest das zuverlaessig auf, weil die Kopie dann nicht mehr existiert.
    """
    return any(
        "material-ui-render-" in line and "NotFound" in line and own_copy.name not in line
        for line in output.splitlines()
    )


RENDER_LOCK_TIMEOUT = float(os.environ.get("MATERIAL_RENDER_LOCK_TIMEOUT", "120"))


@contextmanager
def render_lock(root: Path, timeout: float = RENDER_LOCK_TIMEOUT):
    """Prozessuebergreifende Serialisierung von Quarto-Rendern.

    Quartos Projektkontext scannt das gesamte Repo; zwei parallel laufende
    Renderkopien (z. B. inv build und Material-UI) bringen einander mit
    NotFound-Fehlern aus dem Takt (siehe _concurrent_render_race). Das Lock
    im zentralen Build-Ordner serialisiert die Renderphasen ueber alle
    BuildService-Nutzer. Laeuft es nach `timeout` Sekunden nicht frei, wird
    ohne Lock weitergebaut; die Retry-Logik bleibt Rueckfallebene.
    """
    try:
        import fcntl
    except ImportError:
        yield
        return
    lock_dir = root / OUTPUT_ROOT
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
        handle = (lock_dir / ".render.lock").open("w")
    except OSError:
        yield
        return
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                time.sleep(0.2)
        yield
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class BuildService:
    def __init__(self, root: Path, runner) -> None:
        self.root = root
        self.run_process = runner
        self._digest_cache = OrderedDict()
        self._digest_lock = threading.Lock()

    def dependency_digest(self, path: Path) -> bytes:
        """Reuse hashes of unchanged dependencies, bounded independently of asset size."""
        def fingerprint():
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino, stat.st_dev

        stamp = fingerprint()
        with self._digest_lock:
            cached = self._digest_cache.get(path)
            if cached and cached[0] == stamp:
                self._digest_cache.move_to_end(path)
                return cached[1]
        with path.open('rb') as handle:
            value = hashlib.file_digest(handle, 'sha256').digest()
        if fingerprint() == stamp:
            with self._digest_lock:
                self._digest_cache[path] = (stamp, value)
                self._digest_cache.move_to_end(path)
                while len(self._digest_cache) > 2048:
                    self._digest_cache.popitem(last=False)
        return value

    def render_environment(self, text):
        env = managed_render_environment()
        # Also discover bundled faces for managed renders outside Quarto's project
        # tree (e.g. previews). Do not rely on a user's installed font versions.
        fonts = template_roots.SUPPORT / "fonts/static"
        if fonts.is_dir():
            env["TYPST_FONT_PATHS"] = os.pathsep.join(
                [str(fonts), *filter(None, [env.get("TYPST_FONT_PATHS", "")])]
            )
        env.pop("MATERIAL_TEMPLATE_FILTER_DIR", None)
        reference = read_metadata(text).get("template-release")
        if reference:
            from material_core.template_versions import TemplateVersions
            versions = TemplateVersions(self.root)
            release = versions.load(reference)
            env["MATERIAL_TEMPLATE_FILTER_DIR"] = str(versions.path(release["layout"]) / "filters")
        return env

    def render_text(self, source: Path, text: str) -> str:
        """Gestaltete Vorlagen bringen ihre Abhängigkeiten auch ohne Quarto-Projekt mit.

        Vorlagen und Filter werden anhand ihres Dateinamens gegen
        src/quarto/templates bzw. src/quarto/filters aufgelöst, damit das
        Frontmatter nur den Dateinamen nennen muss statt eines von der
        Ordnertiefe der Quelle abhängigen Relativpfads (der dann bei jeder
        Verschiebung neu gezählt werden müsste).
        """
        from material_core.template_versions import TemplateVersions
        versioned = TemplateVersions(self.root).render(source, text)
        if versioned is not None:
            return versioned
        from material_core.designs import slide_templates
        from material_core.template_roots import all_template_names, find_template, sibling

        support = template_roots.SUPPORT
        template_dir = support / "templates"
        filter_dir = support / "filters"

        def resolve_builtin(value: str, builtin_dir: Path) -> str:
            # Eine lokale, gleichnamige Datei neben der Quelle geht der zentralen
            # Vorlage/dem zentralen Filter vor (wie bei render_signature, render_content
            # und resolve_relative) - sonst wuerde eine bewusste lokale Abweichung
            # stillschweigend durch die zentrale Datei ersetzt.
            if (source.parent / value).resolve().is_file():
                return value
            candidate = find_template(value) if builtin_dir == template_dir else builtin_dir / Path(value).name
            if candidate is None or not candidate.is_file():
                return value
            return os.path.relpath(candidate, source.parent)

        value = template_value(text)
        names = {Path(entry["path"]).name for entry in slide_templates()}
        slide_template = Path(value).name in names
        builtins = all_template_names(support)
        if Path(value).name not in builtins:
            return text
        resolved_template = resolve_builtin(value, template_dir)
        local_template = (source.parent / value).resolve()
        template = local_template if local_template.is_file() else (find_template(value) or template_dir / Path(value).name).resolve()
        metadata = read_metadata(text)
        fields = {}
        format_value = metadata.get("format")
        engine = None
        if isinstance(format_value, Mapping):
            engine = next((key for key in ("pdf", "typst", "beamer")
                           if isinstance(format_value.get(key), Mapping) and "template" in format_value[key]), None)
        if engine is not None:
            format_fields = dict(format_value)
            engine_fields = dict(format_fields[engine])
            engine_fields["template"] = resolved_template
            for key in ("include-in-header", "include-before-body", "include-after-body"):
                if isinstance(engine_fields.get(key), str):
                    engine_fields[key] = resolve_builtin(engine_fields[key], template_dir)
            format_fields[engine] = engine_fields
            fields["format"] = format_fields
        elif "template" in metadata:
            fields["template"] = resolved_template
        template_text = template.read_text(encoding="utf-8") if template.is_file() else ""
        previous = metadata.get("template-partials") or []
        previous = [previous] if isinstance(previous, str) else list(previous)
        overrides = {Path(value).name: (source.parent / value).resolve()
                     for value in previous if isinstance(value, str)}
        partials = []
        visited_partials = {template.resolve()}

        def collect_partials(path, content):
            for name in re.findall(r"\$([a-z-]+\.typst)\(\)\$", content):
                partial = overrides.get(name, sibling(path, name)).resolve()
                if partial in visited_partials:
                    continue
                visited_partials.add(partial)
                if name not in overrides:
                    partials.append(os.path.relpath(partial, source.parent))
                if partial.is_file():
                    collect_partials(partial, partial.read_text(encoding="utf-8"))

        collect_partials(template, template_text)
        if partials:
            fields["template-partials"] = [*previous, *partials]
        previous = metadata.get("filters") or []
        previous = [previous] if isinstance(previous, str) else list(previous)
        previous = [resolve_builtin(item, filter_dir) if isinstance(item, str) else item for item in previous]
        # Frontmatter-Filter funktionieren sowohl innerhalb als auch außerhalb
        # der festen project.render-Globs. exam.lua muss vor der Seitengruppierung laufen.
        additions = [filter_dir / "exam.lua"]
        if slide_template:
            additions.append(filter_dir / "slide-pages.lua")
        names = {Path(item).name for item in previous if isinstance(item, str)}
        fields["filters"] = [*previous, *(os.path.relpath(path, source.parent) for path in additions if path.name not in names)]
        # Render-Metadaten dürfen auch konfigurierte Filterobjekte enthalten.
        # Nur die temporäre Renderquelle wird angepasst, die Datei bleibt unverändert.
        metadata.update(fields)
        enforce_min_fontsize(metadata, default="11pt")
        header = io.StringIO()
        yaml_parser().dump(metadata, header)
        parts = split_frontmatter(text)
        if parts is None:
            return f"---\n{header.getvalue()}---\n\n{text}"
        return f"{parts.prefix}{header.getvalue()}{parts.closing}{parts.body}"

    def render_signature(self, source: Path, text: str) -> str:
        """Ausgabeinhalt und deklarierte Abhängigkeiten, ohne reine Indexfelder."""
        from material_core.template_roots import find_template, sibling
        from material_core.template_versions import TemplateVersions
        versions = TemplateVersions(self.root)
        versioned = versions.render(source, text)
        if versioned is not None:
            text = versioned
        digest = hashlib.sha256(render_content(text, source).encode('utf-8'))
        reference = read_metadata(text).get("template-release")
        if reference:
            digest.update(versions.path(reference).read_bytes())
        dependencies = set()
        visited = set()
        support = template_roots.SUPPORT
        dependencies.update((support / "filters").glob("*.lua"))
        dependencies.add(support / "fonts/static-manifest.json")
        dependencies.update((support / "fonts/static").rglob("*.ttf"))

        def add(path):
            path = path.resolve()
            if path in visited:
                return
            visited.add(path)
            dependencies.add(path)
            if path.is_file() and path.suffix in {".qmd", ".md", ".typst", ".tex"}:
                content = path.read_text(encoding="utf-8")
                references(content, path.parent)
                for name in re.findall(r"\$([a-z-]+\.typst)\(\)\$", content):
                    add(sibling(path, name))

        def references(content, base):
            for pattern in (r"!\[[^\]]*\]\(([^)]+)\)", r"\{\{<\s*include\s+([^>]+?)\s*>}}", r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}"):
                for value in re.findall(pattern, content):
                    value = value.strip().strip('"')
                    if value.startswith("<") and ">" in value:
                        value = value[1:value.index(">")]
                    else:
                        value = re.split(r"\s+[\"']", value)[0]
                    if not re.match(r"(?:[a-z]+:|#)", value):
                        add(base / value.split("#", 1)[0].split("?", 1)[0])

        path_keys = {"template", "template-partials", "filters", "include-in-header", "include-before-body", "include-after-body", "bibliography", "csl", "css"}
        builtin_dirs = {
            "template": support / "templates", "template-partials": support / "templates",
            "include-in-header": support / "templates", "include-before-body": support / "templates",
            "include-after-body": support / "templates", "filters": support / "filters",
        }
        def resolve_path(key, value, base):
            candidate = base / value
            if candidate.is_file():
                return candidate
            builtin_dir = builtin_dirs.get(key)
            if builtin_dir is not None:
                alt = find_template(value) if builtin_dir == support / "templates" else builtin_dir / Path(value).name
                if alt is not None and alt.is_file():
                    return alt
            return candidate
        def config_paths(value, base, key=""):
            if isinstance(value, dict):
                for name, item in value.items():
                    config_paths(item, base, name if name != "path" else key)
            elif isinstance(value, list):
                for item in value:
                    config_paths(item, base, key)
            elif isinstance(value, str) and key in path_keys and not re.match(r"[a-z]+://", value):
                add(resolve_path(key, value, base))

        config_paths(read_metadata(text), source.parent)
        references(text, source.parent)
        current = source.parent
        while current.is_relative_to(self.root.resolve()):
            for name in ("_quarto.yml", "_metadata.yml"):
                config = current / name
                if config.is_file():
                    dependencies.add(config)
                    config_paths(yaml_parser().load(config.read_text()) or {}, current)
            if current == self.root.resolve():
                break
            current = current.parent
        for path in sorted(dependencies):
            digest.update(str(path).encode('utf-8'))
            if path.is_file():
                digest.update(self.dependency_digest(path))
            else:
                digest.update(b"missing")
        return digest.hexdigest()

    def render_stamp(self, source: Path) -> Path:
        return self.build_dir(source) / f"{source.stem}.render.json"

    def pdf_is_current(self, source: Path, text: str | None = None) -> bool | None:
        try:
            state = json.loads(self.render_stamp(source).read_text())
            pdf = self.find_pdf(source, text=text)
            if not pdf or not isinstance(state, dict):
                return False
            stat = pdf.stat()
            return (state.get("pdf") == str(pdf.relative_to(self.root))
                    and state.get("mtime_ns") == stat.st_mtime_ns and state.get("size") == stat.st_size
                    and state.get("signature") == self.render_signature(source, text if text is not None else source.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    def build_document(self, source: Path, *, quarto: str | None = None, snapshot: dict[str, str] | None = None,
                       before_publish=None, publish_lock=None, asset_builder=None, error_summary=None,
                       allow_source_changes: bool = False) -> BuildResult:
        source = source.resolve()
        if not source.is_relative_to(self.root.resolve()) or source.suffix not in {".qmd", ".md"}:
            raise ValueError("Bitte eine Markdown-/QMD-Quelle innerhalb des Projekts wählen.")
        executable = quarto or os.environ.get("QUARTO", "quarto")
        command = [executable, "render", str(source)]
        output = ""
        returncode = None
        source_revision = ""
        try:
            snapshot = snapshot if snapshot is not None else {"text": source.read_text(encoding="utf-8")}
            source_revision = snapshot.get("revision") or text_revision(snapshot["text"])
            input_signature = self.render_signature(source, snapshot["text"])
            (asset_builder or self.build_tikz_assets)(source.parent)
            existing = {path for path in self.artifact_candidates(source) if path.exists()}
            artifacts = []
            with render_lock(self.root), tempfile.TemporaryDirectory(dir=source.parent, prefix=".material-render-") as temporary:
                staging = Path(temporary)
                filename = f"material-ui-render-{staging.name.removeprefix('.material-render-')}.pdf"
                snapshot_source = source.parent / Path(filename).with_suffix(".qmd")
                command = [executable, "render", str(snapshot_source), "--output", filename]
                try:
                    atomic_write_text(snapshot_source, self.render_text(source, snapshot["text"]), overwrite=False)
                    for _attempt in range(3):
                        result = self.run_process(
                            command, cwd=source.parent, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=90, check=False,
                            env=self.render_environment(snapshot["text"]),
                        )
                        output = result.stdout or ""
                        returncode = result.returncode
                        if returncode == 0 or not _concurrent_render_race(output, snapshot_source):
                            break
                    rendered = snapshot_source.with_suffix(".pdf")
                    if rendered.is_file():
                        rendered.replace(staging / filename)
                finally:
                    snapshot_source.unlink(missing_ok=True)
                    artifacts.extend(self.collect_snapshot_artifacts(snapshot_source, source))
                self.relocate_build_artifacts([source], existing, include_pdf=False)
                self.record_artifacts(source, artifacts)
                if returncode != 0:
                    message = error_summary(output) if error_summary is not None else f"Render fehlgeschlagen (Exitcode {returncode})."
                    raise ValueError(message)
                staged_pdf = staging / filename
                if not staged_pdf.is_file() or not staged_pdf.stat().st_size:
                    raise ValueError("Render hat kein neues, nicht leeres PDF erzeugt.")
                self.validate_pdf(staged_pdf)

                def verify_revision():
                    if not allow_source_changes and text_revision(source.read_text(encoding="utf-8")) != source_revision:
                        raise ValueError("Die Quelldatei wurde während des Renderns geändert.")
                    if before_publish is not None:
                        before_publish()

                destination = self.pdf_dir(source) / self.configured_output_file(source).name
                self.record_artifacts(source, [*artifacts, destination])
                with publish_lock if publish_lock is not None else nullcontext():
                    pdf_path = self.publish_pdf(staged_pdf, source, verify_revision)
            if input_signature == self.render_signature(source, snapshot["text"]):
                stat = pdf_path.stat()
                atomic_write_text(self.render_stamp(source), json.dumps({
                    "signature": input_signature, "pdf": str(pdf_path.relative_to(self.root)),
                    "mtime_ns": stat.st_mtime_ns, "size": stat.st_size,
                }))
            else:
                self.render_stamp(source).unlink(missing_ok=True)
            return BuildResult(pdf_path, source_revision, command, output, returncode)
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else f"{type(error).__name__}: {error}"
            raise BuildFailure(message, BuildResult(None, source_revision, command, output, returncode)) from error

    def record_artifacts(self, source: Path, artifacts: list[Path]) -> None:
        if not artifacts:
            return
        manifest = self.build_dir(source) / f"{source.stem}.material-ui.json"
        previous = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
        paths = set(previous.get("artifacts", []))
        paths.update(path.relative_to(self.root).as_posix() for path in artifacts)
        atomic_write_text(manifest, json.dumps({"source": source.relative_to(self.root).as_posix(), "artifacts": sorted(paths)}, indent=2))

    def validate_pdf(self, source: Path) -> None:
        try:
            with pymupdf.open(source) as document:
                if not document.is_pdf or document.needs_pass or document.page_count < 1:
                    raise ValueError("PDF enthält keine lesbaren Seiten.")
                for page_number in range(document.page_count):
                    document.load_page(page_number)
        except (RuntimeError, OSError) as error:
            raise ValueError(f"Ungültige PDF-Ausgabe: {error}") from error

    def publish_pdf(self, source: Path, document: Path, before_replace) -> Path:
        destination = self.pdf_dir(document) / self.configured_output_file(document).name
        if not destination.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("PDF-Ziel liegt ausserhalb des Projekts.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".publish-", delete=False) as handle:
                temporary = Path(handle.name)
                with source.open("rb") as original:
                    shutil.copyfileobj(original, handle)
                handle.flush()
                os.fsync(handle.fileno())
            before_replace()
            temporary.replace(destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return destination

    def collect_snapshot_artifacts(self, snapshot: Path, document: Path) -> list[Path]:
        collected = []
        for artifact in snapshot.parent.glob(f"{snapshot.stem}*"):
            if artifact == snapshot or artifact.name == snapshot.stem:
                continue
            if artifact.suffix == ".pdf":
                artifact.unlink(missing_ok=True)
                continue
            if artifact.suffix not in ARTIFACT_SUFFIXES and not artifact.name.endswith("_files"):
                continue
            destination = self.build_dir(document)
            if not destination.resolve().is_relative_to(self.root.resolve()):
                raise ValueError("Build-Ziel liegt ausserhalb des Projekts.")
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / artifact.name.replace(snapshot.stem, document.stem, 1)
            if artifact.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.move(str(artifact), str(target))
            else:
                artifact.replace(target)
            collected.append(target)
        return collected

    def build_tikz_assets(self, directory: Path) -> None:
        pdflatex = os.environ.get("PDFLATEX", "pdflatex")
        pdftocairo = os.environ.get("PDFTOCAIRO", "pdftocairo")
        for source in sorted((directory / ASSET_FOLDER).glob("*.tex")):
            if any(part.startswith(".") for part in source.relative_to(self.root).parts):
                continue
            if source.stem.endswith("-lib"):
                continue
            if not re.search(r"(?m)^\s*\\documentclass\b", source.read_text(encoding="utf-8")):
                continue
            output = source.with_suffix(".svg")
            if output.exists() and output.stat().st_mtime >= source.stat().st_mtime:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                self.run_process(
                    [
                        pdflatex,
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "-output-directory",
                        str(tmp_path),
                        source.name,
                    ],
                    cwd=source.parent,
                    stdout=subprocess.DEVNULL,
                    timeout=90,
                    check=True,
                )
                self.run_process(
                    [pdftocairo, "-svg", str(tmp_path / f"{source.stem}.pdf"), str(output)],
                    cwd=self.root,
                    timeout=30,
                    check=True,
                )

    def configured_output_file(self, source: Path, text: str | None = None, *, metadata=None) -> Path:
        filename = output_filename(source.read_text(encoding="utf-8") if text is None else text,
                                   f"{source.stem}.pdf", metadata=metadata)
        candidate = source.parent / filename
        if not candidate.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Ausgabepfad liegt ausserhalb des Projekts.")
        return candidate

    def expected_pdf(self, source: Path) -> Path:
        built = self.configured_output_file(source)
        moved = self.pdf_dir(source) / built.name
        return moved if moved.exists() else built

    def pdf_candidates(self, source: Path, text: str | None = None, *, metadata=None) -> list[Path]:
        configured = self.configured_output_file(source, text, metadata=metadata)
        return [
            self.pdf_dir(source) / configured.name,
            self.pdf_dir(source) / f"{source.stem}.pdf",
            configured,
            source.with_suffix(".pdf"),
            source.parent / PDF_FOLDER / configured.name,
            source.parent / BUILD_FOLDER / configured.name,
            source.parent / PDF_FOLDER / f"{source.stem}.pdf",
            source.parent / BUILD_FOLDER / f"{source.stem}.pdf",
        ]

    def find_pdf(self, source: Path, text: str | None = None) -> Path | None:
        seen: set[Path] = set()
        for candidate in self.pdf_candidates(source, text):
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.exists() and candidate.suffix.lower() == ".pdf":
                return candidate
        return None

    def _output_relpath(self, source: Path) -> Path:
        return source.parent.relative_to(self.root)

    def build_dir(self, source: Path) -> Path:
        return self.root / OUTPUT_ROOT / OUTPUT_ARTIFACT_DIR / self._output_relpath(source)

    def pdf_dir(self, source: Path) -> Path:
        return self.root / OUTPUT_ROOT / OUTPUT_PDF_DIR / self._output_relpath(source)

    def artifact_candidates(self, source: Path) -> set[Path]:
        stems = {source.with_suffix(""), self.configured_output_file(source).with_suffix("")}
        outputs: set[Path] = set()
        for stem in stems:
            for suffix in ARTIFACT_SUFFIXES:
                outputs.add(stem.parent / f"{stem.name}{suffix}")
            outputs.add(stem.parent / f"{stem.name}_files")
        return outputs

    def generated_artifacts(self, directory: Path) -> set[Path]:
        if not directory.exists():
            return set()
        return {
            path
            for path in directory.iterdir()
            if (path.is_dir() and path.name.endswith("_files")) or (path.is_file() and path.suffix in ARTIFACT_SUFFIXES)
        }

    def relocate_build_artifacts(self, sources: list[Path], existing: set[Path] | None = None, *, include_pdf: bool = True) -> None:
        for source in sources:
            moved = []
            paths = self.artifact_candidates(source)
            for artifact in sorted(paths):
                if not include_pdf and artifact.suffix == ".pdf":
                    continue
                if not artifact.exists():
                    continue
                if artifact.suffix in {".tex", ".typ"} and (existing is None or artifact in existing):
                    continue
                destination = self.pdf_dir(source) if artifact.suffix == ".pdf" else self.build_dir(source)
                if artifact.parent == destination:
                    continue
                destination.mkdir(parents=True, exist_ok=True)
                target = destination / artifact.name
                if artifact.is_file():
                    artifact.replace(target)
                else:
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.move(str(artifact), str(target))
                moved.append(target.relative_to(self.root).as_posix())
            if moved:
                manifest = self.build_dir(source) / f"{source.stem}.material-ui.json"
                atomic_write_text(manifest, json.dumps({"source": source.relative_to(self.root).as_posix(), "artifacts": moved}, indent=2))
