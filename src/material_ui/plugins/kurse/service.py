from __future__ import annotations

import os
import json
import re
import subprocess
import sys
from functools import partial
from pathlib import Path
from typing import Any

from material_ui.plugins.kurse import adapter as course_adapter
from material_ui.plugins.kurse.chapters import group_questions_by_chapter
from material_ui.plugins.kurse.sync_overview import SyncOverview, SyncOverviewCache
from material_ui.plugins.kurse.targets import MoodleTargets
from material_ui.caching import TTLCache
from material_ui.errors import InvalidInput
from material_ui.jobs import OperationChannel
from material_core import workspace


MOODLE_TASK_BY_OPERATION = {
    "verify": "verify-moodle",
    "upload-chapter": "upload-chapter-moodle",
    "upload-course": "upload-course-moodle",
    "publish": "publish",
}

MOODLE_LABEL_BY_OPERATION = {
    "verify": "Remote-Status pruefen",
    "upload-chapter": "Kapitel hochladen",
    "upload-course": "Kurs hochladen",
    "publish": "Veroeffentlichen",
}


def tail(text: str, lines: int = 30) -> str:
    return "\n".join(text.splitlines()[-lines:])


def kurs_audit_summary(output: str) -> str:
    match = re.search(r"Audit:\s*errors=(\d+),\s*warnings=(\d+),\s*checks=(\d+)", output)
    if match:
        errors, warnings, checks = match.groups()
        return f"{errors} Fehler, {warnings} Warnungen ({checks} Checks)."
    return tail(output, 1)[:240] if output.strip() else "Audit fehlgeschlagen."


def kurs_audit_detail(
    source: str,
    status: str,
    output: str,
    returncode: int | None = None,
    command: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "status": status,
        "returncode": returncode,
        "command": " ".join(command or []),
        "log": tail(output, 80) if output else "",
    }


def kurs_moodle_summary(output: str) -> str:
    return tail(output, 1)[:240] if output.strip() else "Fertig."


class CourseService:
    def __init__(self, config, documents, jobs, runner, submit, adapter=None):
        self.config = config
        self.documents = documents
        self.jobs = jobs
        self.runner = runner
        self.adapter = adapter if adapter is not None else course_adapter.CourseAdapter(config.root)
        self.audit = OperationChannel(jobs, submit)
        self.moodle = OperationChannel(jobs, submit)
        self.cache = TTLCache(config.course_cache_ttl)
        self.targets = MoodleTargets(config.root, self.adapter)
        self.sync_cache = SyncOverviewCache(
            config.course_cache_ttl, lambda: SyncOverview(self.config.root, self.adapter).build())

    def entries(self):
        return self.kurs_entries_cached()

    def sync_overview(self, refresh: bool = False) -> dict:
        """Lokal erfasster Sync-Stand aller Kurse je Plattform (ohne Remote-Zugriff)."""
        return self.sync_cache.get(refresh=refresh)

    def moodle_targets(self, slug: str) -> dict:
        return self.targets.list(self.ensure_kurs(slug))

    def save_moodle_target(self, slug: str, target: str, data: dict, *, create: bool) -> dict:
        """Legt ein Moodle-Ziel an oder aendert es (URL, Anmeldeart, Zugangsdaten)."""
        if not isinstance(data, dict):
            raise InvalidInput("Ungültige Anfrage.")
        result = self.targets.save(self.ensure_kurs(slug), target, data, create=create)
        self.invalidate_kurs_cache()
        return result

    def index(self, slug: str) -> dict:
        course_dir = self.ensure_kurs(slug)
        _, questions, _ = self.adapter.parse_course(course_dir)
        grouped = group_questions_by_chapter(
            self.adapter.list_course_chapters(course_dir), questions,
            lambda chapter: self.adapter.read_chapter_question_order(course_dir, chapter),
        )
        return {"chapters": [
            {"slug": chapter["slug"], "title": chapter["title"],
             "activities": [{"id": item.identifier, "title": item.title} for item in chapter["questions"]]}
            for chapter in grouped
        ]}

    def activity(self, slug: str, identifier: str, data: dict | None = None) -> dict:
        course_dir = self.ensure_kurs(slug)
        _, questions, _ = self.adapter.parse_course(course_dir)
        question = next((item for item in questions if item.identifier == identifier), None)
        if question is None:
            raise InvalidInput(f"Unbekannte Aktivität: {identifier}")
        candidates = [question.exploded_dir / "content.mdx"]
        if question.h5p_content_path:
            candidates.append(course_dir / question.h5p_content_path)
        if question.source_package_path and not question.source_package_path_inferred:
            candidates.append(question.exploded_dir / "content" / "content.json")
        candidates.extend(
            course_dir / "chapters" / f'{chapter["slug"]}.mdx'
            for chapter in self.adapter.list_course_chapters(course_dir)
            if chapter["slug"].split("/")[0] == question.h5p_subdir
        )
        candidates.append(course_dir / "index.mdx")
        source = next((path.resolve() for path in candidates if path.is_file()), None)
        if source is None or not source.is_relative_to(course_dir.resolve()):
            raise InvalidInput("Keine bearbeitbare Kursquelle gefunden.")
        if data is not None:
            text = data.get("text")
            if not isinstance(text, str):
                raise InvalidInput("Text muss als Zeichenkette angegeben werden.")
            if source.suffix == ".json":
                json.loads(text)
            result = self.documents.save(source, text, data.get("revision"))
            snapshot = {"text": text, **result}
            self.invalidate_kurs_cache()
        else:
            snapshot = self.documents.read(source)
        return {"path": self.config.relative(source), **snapshot, "title": question.title}

    def start_audit(self, slug: str) -> str:
        command = [sys.executable, "-m", "course_sync.main", "audit", slug]
        return self.audit.start(slug, "audit", partial(self._execute, slug, command, False),
                                current=slug, message="Audit läuft …",
                                detail=kurs_audit_detail(slug, "running", "", command=command))

    def start_moodle(self, slug: str, operation: str, extra_args: list[str]) -> str:
        command = ["inv", f"kurse.{MOODLE_TASK_BY_OPERATION[operation]}", f"--course={slug}", *extra_args]
        return self.moodle.start(slug, operation, partial(self._execute, slug, command, True),
                                 slug=slug, message=f"{MOODLE_LABEL_BY_OPERATION[operation]} läuft …",
                                 detail=kurs_audit_detail(slug, "running", "", command=command))

    def _execute(self, slug: str, command: list[str], remote: bool) -> dict:
        try:
            return self._run_command(slug, command, remote)
        finally:
            # Upload, Publish und Audit veraendern den Sync-Stand; eine bis dahin zwischen-
            # gespeicherte Uebersicht waere sonst noch bis zu einer TTL lang veraltet.
            self.sync_cache.invalidate()

    def _run_command(self, slug: str, command: list[str], remote: bool) -> dict:
        try:
            result = self.runner(command, cwd=self.config.root, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=600 if remote else 180,
                                 check=False, env=self.course_sync_env())
            ok = result.returncode == 0
            message = (kurs_moodle_summary(result.stdout) if ok else f"Fehlgeschlagen (Exit-Code {result.returncode}).") if remote else kurs_audit_summary(result.stdout)
            return {"ok": ok, "message": message,
                    "detail": kurs_audit_detail(slug, "ok" if ok else "failed", result.stdout, result.returncode, command)}
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            return {"ok": False, "message": message,
                    "detail": kurs_audit_detail(slug, "failed", message, command=command)}

    def audit_payload(self) -> dict:
        return {"current": None, **self.audit.payload()}

    def moodle_payload(self) -> dict:
        return {"slug": None, **self.moodle.payload()}

    def close(self) -> None:
        self.audit.close()
        self.moodle.close()

    def kurse_dir(self) -> Path:
        return self.config.root / "unterricht" / "kurse"


    def kurs_entries_cached(self) -> list[dict[str, Any]]:
        entries = self.cache.get(lambda: [self.kurs_entry(summary) for summary in self.adapter.list_course_summaries(self.kurse_dir())])
        return list(entries)


    def invalidate_kurs_cache(self) -> None:
        self.cache.invalidate()
        self.sync_cache.invalidate()


    def kurs_entry(self, summary: dict[str, Any]) -> dict[str, Any]:
        slug = str(summary["slug"])
        index_path = self.kurse_dir() / slug / "index.mdx"
        mtime = index_path.stat().st_mtime if index_path.exists() else 0.0
        return {
            "path": f"unterricht/kurse/{slug}",
            "name": slug,
            "stem": slug,
            "slug": slug,
            "title": summary["title"],
            "folder": f"unterricht/kurse/{slug}",
            "area": "kurse",
            "subject": "",
            "grade": "",
            "thema": "",
            "kind": "Kurs (H5P)",
            "solution": False,
            "pdf": None,
            "chapters": summary["chapters"],
            "chapterList": self.adapter.list_course_chapters(self.kurse_dir() / slug),
            "moodleTargets": self.targets.names(self.kurse_dir() / slug),
            "mtime": mtime,
        }


    def ensure_kurs(self, slug: str) -> Path:
        course_dir = self.kurse_dir() / slug
        if not re.fullmatch(r"[A-Za-z0-9_-]+", slug) or not course_dir.is_dir() or not course_dir.resolve().is_relative_to(self.kurse_dir().resolve()):
            raise InvalidInput(f"Unbekannter Kurs: {slug}")
        return course_dir


    def create_kurs(self, data: dict[str, Any]) -> dict[str, Any]:
        slug = str(data.get("slug") or "").strip()
        title = str(data.get("title") or "").strip()
        language = str(data.get("language") or "de").strip()
        if not slug:
            raise InvalidInput("Kurs-Slug fehlt.")
        try:
            self.adapter.create_new_course(self.kurse_dir(), slug, title=title, language=language)
            self.adapter.sync_course(self.kurse_dir() / slug)
        except ValueError as error:
            raise InvalidInput(str(error)) from error
        self.invalidate_kurs_cache()
        summary = {"slug": slug, "title": title or slug, "chapters": len(self.adapter.list_course_chapters(self.kurse_dir() / slug))}
        return self.kurs_entry(summary)


    def course_sync_env(self) -> dict[str, str]:
        env = dict(os.environ)
        src_dir = str(workspace.CODE_SRC)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = src_dir + (os.pathsep + existing if existing else "")
        return env
