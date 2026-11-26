from __future__ import annotations

import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from excalideck.generator import DeckDependencyError
from material_core.builds import BuildFailure
from material_core.render_inputs import render_content
from material_core.layout import check_layout
from material_ui.jobs import JobBusy
from material_ui.diagnostics import preflight, PreflightFailure


def render_error_summary(output: str) -> str:
    output = plain_render_output(output)
    lines = [
        line.strip()
        for line in output.splitlines()
        if line.strip() and not re.fullmatch(r"(?:error|fehler)\s*:?", line.strip(), re.IGNORECASE)
    ]
    for marker in ("ERROR", "Error", "Fehler", "LaTeX Error", "Typst", "Pandoc"):
        match = next((line for line in reversed(lines) if marker in line and not line.startswith("WARN")), None)
        if match:
            return match[:240]
    return lines[-1][:240] if lines else "Render fehlgeschlagen."


def plain_render_output(output: str) -> str:
    return re.sub(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])", "", output)


WARNING_PATTERNS = (
    re.compile(r"^\s*(?:WARNING|Warnung)\s*:?", re.IGNORECASE),
    re.compile(r"^\s*LaTeX\s+Warning\s*:?", re.IGNORECASE),
    re.compile(r"^\s*(?:Overfull|Underfull)\s+\\"),
    re.compile(r"^\s*Package\s+\S+\s+Warning\s*:?", re.IGNORECASE),
    re.compile(r"^\s*Typst\s+warning\s*:?", re.IGNORECASE),
    re.compile(r"^\s*warning\s*:?", re.IGNORECASE),
)
MAX_WARNINGS = 20


def render_warnings(output: str) -> list[str]:
    """Sammelt Warnzeilen aus der Renderausgabe, ohne Fehlerzeilen."""
    warnings: list[str] = []
    for line in plain_render_output(output).splitlines():
        clean = line.rstrip()
        if not clean:
            continue
        if any(pattern.match(clean) for pattern in WARNING_PATTERNS):
            if len(warnings) < MAX_WARNINGS:
                warnings.append(clean[:240])
            else:
                warnings.append("… weitere Warnungen wurden gekürzt.")
                break
    return warnings


def render_detail(
    source: str,
    status: str,
    output: str,
    returncode: int | None = None,
    command: list[str] | None = None,
) -> dict[str, Any]:
    plain = plain_render_output(output) if output else ""
    warnings = render_warnings(plain)
    return {
        "source": source,
        "status": status,
        "returncode": returncode,
        "command": " ".join(command or []),
        "log": plain,
        "warnings": warnings,
        "warning_count": len(warnings),
    }


class RenderService:
    def __init__(self, config, documents, builds, jobs, submit, *, slides=None):
        self.config = config
        self.documents = documents
        self.builds = builds
        self.jobs = jobs
        self.submit = submit
        if slides is None:
            from material_ui.slides import SlidesService
            slides = SlidesService(config, repository=documents)
        self.slides = slides
        self.lock = threading.RLock()
        self.pending: OrderedDict[str, str] = OrderedDict()
        self.latest_id = None
        self.closed = False

    def command(self, source: Path) -> list[str]:
        return [self.config.quarto, "render", self.config.relative(source)]

    def _activate(self, source: Path, identifier: str) -> None:
        self.jobs.retain(identifier, self.latest_id)
        self.latest_id = identifier
        resource = self.config.relative(source)
        self.jobs.update(identifier, status="running", running=True, current=resource,
                         ok=None, message="Render läuft …", pdf=None,
                         detail=render_detail(resource, "running", "", command=self.command(source)))

    def start(self, source: Path) -> str:
        from material_ui.document_types import ensure_renderable
        ensure_renderable(source)
        preflight(self.builds, source, self.documents.read(source)["text"])
        resource = self.config.relative(source)
        with self.lock:
            if self.closed:
                raise JobBusy("Renderverwaltung ist beendet.")
            if self.latest_id and self.jobs.get(self.latest_id)["running"]:
                if resource not in self.pending and len(self.pending) >= 32:
                    raise JobBusy("Render-Warteschlange ist voll. Bitte später erneut versuchen.")
                return self._enqueue(resource)
            identifier = self.jobs.create(resource, "render")
            self._activate(source, identifier)
            try:
                self._submit(source)
            except Exception as error:
                self.jobs.update(identifier, running=False, ok=False, status="failed", message=str(error))
                raise
            return identifier

    def _enqueue(self, resource: str) -> str:
        if resource not in self.pending:
            self.pending[resource] = self.jobs.create(resource, "render", "queued")
            self.jobs.update(self.pending[resource], current=resource, message="Render vorgemerkt.")
        self.pending.move_to_end(resource)
        return self.pending[resource]

    def _submit(self, source: Path) -> None:
        self.submit(self.worker, (source,))

    def finish(self, ok: bool, message: str, pdf_path: Path | None, detail=None) -> None:
        while True:
            with self.lock:
                if self.closed:
                    return
                if self.latest_id is not None:
                    resource = self.jobs.get(self.latest_id)["resource"]
                    self.jobs.update(self.latest_id, running=False, ok=ok, message=message,
                                     pdf=self.config.relative(pdf_path), detail=detail,
                                     next_job_id=self.pending.get(resource),
                                     status="succeeded" if ok else "failed")
                if not self.pending:
                    return
                resource, identifier = self.pending.popitem(last=False)
                source = self.config.safe_path(resource)
                self._activate(source, identifier)
            try:
                self._submit(source)
                return
            except Exception as error:
                ok, message, pdf_path, detail = False, str(error), None, None

    def state_payload(self) -> dict:
        with self.lock:
            result = self.jobs.get(self.latest_id) if self.latest_id else {
                "job_id": None, "running": False, "current": None, "ok": None,
                "message": "Noch nicht gerendert.", "detail": None, "pdf": None, "updated": 0.0,
            }
            result.update(queue=list(self.pending), queued=next(reversed(self.pending), None))
            return result

    def close(self) -> None:
        with self.lock:
            self.closed = True
            if self.latest_id and self.jobs.get(self.latest_id)["running"]:
                self.jobs.update(self.latest_id, running=False, ok=False, status="failed", message="Anwendung beendet.")
            for identifier in self.pending.values():
                self.jobs.update(identifier, running=False, ok=False, status="failed", message="Anwendung beendet.")
            self.pending.clear()

    def worker(self, source: Path) -> None:
        with self.lock:
            if self.closed:
                return
            if self.latest_id is None or not self.jobs.get(self.latest_id)["running"]:
                self._activate(source, self.jobs.create(self.config.relative(source), "render"))
        snapshot = None
        try:
            snapshot = self.documents.read(source)
            preflight(self.builds, source, snapshot["text"])

            def before_publish():
                if self.closed:
                    raise ValueError("Anwendung wurde während des Renderns beendet.")

            result = self.builds.build_document(
                source,
                quarto=self.config.quarto,
                snapshot=snapshot,
                before_publish=before_publish,
                publish_lock=self.documents.lock,
                asset_builder=self.builds.build_tikz_assets,
                error_summary=render_error_summary,
                allow_source_changes=True,
            )
            from material_core.designs import template_slide_design

            deck = None
            slide_warning = None
            if render_content(self.documents.read(source)["text"], source) == render_content(snapshot["text"], source) and template_slide_design(snapshot["text"])[0]:
                try:
                    deck, _ = self.slides.rebuild(source)
                except (ValueError, DeckDependencyError) as error:
                    from material_core.metadata import template_value

                    if not Path(template_value(snapshot["text"])).name.startswith("worksheet-"):
                        raise
                    # A worksheet PDF remains usable when its optional deck cannot be
                    # built: richer structure than slides allow, or a missing dependency.
                    slide_warning = f"PDF erstellt; zusätzliche Folien konnten nicht erzeugt werden: {error}"
            detail = render_detail(self.config.relative(source) or str(source), "ok", result.stdout, result.returncode, result.command)
            detail["source_revision"] = result.source_revision
            detail["layout_issues"] = check_layout(result.pdf_path, deck, slides=template_slide_design(snapshot["text"])[0])
            detail["warnings"].extend(item["detail"] for item in detail["layout_issues"])
            detail["warning_count"] = len(detail["warnings"])
            count = len(detail["layout_issues"])
            message = "Render fertig." if not count else f"Render fertig. {count} Layout-Hinweis{'e' if count != 1 else ''}."
            if slide_warning:
                detail["warnings"].append(slide_warning)
                detail["warning_count"] = len(detail["warnings"])
                message = slide_warning
            ok, pdf_path = True, result.pdf_path
        except Exception as error:
            if isinstance(error, BuildFailure):
                result = error.result
                output, returncode, command = result.stdout, result.returncode, result.command
            else:
                output, returncode, command = "", None, self.command(source)
            message = str(error) if isinstance(error, ValueError) else f"{type(error).__name__}: {error}"
            ok, pdf_path = False, None
            detail = render_detail(self.config.relative(source) or str(source), "failed", f"{output}\n{message}", returncode, command=command)
            if isinstance(error, PreflightFailure):
                detail["preflight_issues"] = error.issues
            if snapshot is not None:
                detail["source_revision"] = snapshot["revision"]
        with self.documents.lock, self.lock:
            if not self.closed and snapshot is not None and source.is_file():
                current_text = self.documents.read(source)["text"]
                try:
                    changed = render_content(current_text, source) != render_content(snapshot["text"], source)
                except ValueError:
                    changed = self.documents.read(source)["revision"] != snapshot["revision"]
                if changed:
                    self._enqueue(self.config.relative(source))
            self.finish(ok, message, pdf_path, detail)
