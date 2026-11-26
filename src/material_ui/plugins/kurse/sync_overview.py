"""Sync-Uebersicht: welcher Kurs liegt zu welchem Grad auf welcher Plattform.

Die Auswertung ist rein lokal und lesend. Sie vergleicht den aktuellen Inhalts-Hash
jeder Aktivitaet mit dem, was course-sync beim letzten Upload bzw. Export festgehalten
hat -- es gibt keinen Remote-Zugriff. Ob die Plattform seither von Hand veraendert
wurde, zeigt weiterhin nur `inv kurse.verify-moodle`.

Status je Aktivitaet und Plattform:

- ``synced``:  liegt dort, mit dem aktuellen lokalen Stand
- ``changed``: liegt dort, wurde aber seither lokal geaendert
- ``unknown``: liegt dort, der uebertragene Stand wurde nicht erfasst
- ``missing``: liegt dort nicht
- ``excluded``: Kapitel ist per ``synced={false}`` vom Kurs-Sync ausgenommen
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from course_sync.classes.platform_sync_state import (
    load_site_export_state,
    load_target_sync_state,
    site_export_state_path,
    target_sync_state_path,
)
from material_ui.plugins.kurse.chapters import group_questions_by_chapter


COUNTED_STATUSES = ("synced", "changed", "unknown", "missing")
TARGET_FILE_PATTERNS = (
    (".moodle-target-", ".yml"),
    (".moodle-activity-ids-", ".json"),
    (".moodle-sync-state-", ".json"),
)


def _iso(timestamp: float | None) -> str | None:
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def _mtime(*paths: Path) -> float | None:
    stamps = []
    for path in paths:
        try:
            stamps.append(path.stat().st_mtime)
        except OSError:
            continue
    return max(stamps) if stamps else None


def _percent(part: int, total: int) -> int:
    """Ganzzahliger Anteil; 0 und 100 nur, wenn sie exakt zutreffen."""
    if total <= 0 or part <= 0:
        return 0
    if part >= total:
        return 100
    return min(99, max(1, round(100 * part / total)))


def _host(url: str) -> str:
    return urlparse(url).netloc if url else ""


class SyncOverviewCache:
    """Kurzzeit-Cache der Uebersicht, dessen Auswertung keine Sperre haelt.

    Die Auswertung parst alle Kurse und dauert Sekunden. `invalidate` (Speichern einer
    Aktivitaet, Jobende) darf deshalb nie auf eine laufende Auswertung warten. Wird
    waehrend einer Auswertung invalidiert, gilt deren Ergebnis als ueberholt: Es wird
    ausgeliefert, aber nicht gemerkt.
    """

    def __init__(self, ttl: float, build: Callable[[], dict[str, Any]]) -> None:
        self.ttl = ttl
        self._build = build
        self._state = threading.Lock()   # schuetzt Wert, Ablauf und Generation (nur kurz gehalten)
        self._single = threading.Lock()  # eine Auswertung gleichzeitig; Wartende nutzen ihr Ergebnis
        self._value: dict[str, Any] | None = None
        self._expires = 0.0
        self._generation = 0

    def _fresh(self) -> dict[str, Any] | None:
        return self._value if self._value is not None and self._expires > time.time() else None

    def get(self, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            self.invalidate()
        with self._state:
            cached = self._fresh()
        if cached is not None:
            return cached
        with self._single:
            with self._state:
                cached = self._fresh()
                generation = self._generation
            if cached is not None:
                return cached
            value = self._build()
            with self._state:
                if generation == self._generation:
                    self._value, self._expires = value, time.time() + self.ttl
            return value

    def invalidate(self) -> None:
        with self._state:
            self._generation += 1
            self._expires = 0.0


class SyncOverview:
    def __init__(self, root: Path, adapter) -> None:
        self.root = root
        self.adapter = adapter

    # -- Einstieg ---------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        kurse_dir = self.root / "unterricht" / "kurse"
        site = self._site()
        courses = [
            self._course(kurse_dir / str(summary["slug"]), summary, site)
            for summary in self.adapter.list_course_summaries(kurse_dir)
        ]
        return {
            "generatedAt": _iso(datetime.now(timezone.utc).timestamp()),
            "site": {"available": site is not None, "host": site["host"] if site else ""},
            "courses": courses,
        }

    # -- Kurs -------------------------------------------------------------------

    def _course(self, course_dir: Path, summary: dict[str, Any], site: dict[str, Any] | None) -> dict[str, Any]:
        slug = course_dir.name
        course: dict[str, Any] = {
            "slug": slug,
            "title": summary.get("title") or slug,
            "path": f"unterricht/kurse/{slug}",
            "activities": 0,
            "chapters": [],
            "platforms": [],
            "error": None,
        }
        try:
            self._fill_course(course, course_dir, site)
        except Exception as error:  # noqa: BLE001 - ein kaputter Kurs darf die Uebersicht nicht kippen
            return {**course, "activities": 0, "chapters": [], "platforms": [],
                    "error": f"{type(error).__name__}: {error}"}
        return course

    def _fill_course(self, course: dict[str, Any], course_dir: Path, site: dict[str, Any] | None) -> None:
        application = self.adapter.application()
        _, questions, _ = application.parse_course(course_dir)
        hashes = {question.identifier: application.compute_question_hash(question) for question in questions}
        chapters = self._chapters(application, course_dir, questions)
        platforms = []
        default = self._default_moodle(application, course_dir, chapters, hashes)
        if default is not None:
            platforms.append(default)
        for target in self._targets(course_dir):
            platforms.append(self._target_moodle(application, course_dir, target, chapters, hashes))
        if site is not None:
            platforms.append(self._website(course_dir.name, site, chapters, hashes))
        course["activities"] = len(questions)
        course["chapters"] = [
            {
                "slug": chapter["slug"],
                "title": chapter["title"],
                "synced": chapter["synced"],
                "activities": [{"id": question.identifier, "title": question.title} for question in chapter["questions"]],
            }
            for chapter in chapters
        ]
        course["platforms"] = platforms

    def _chapters(self, application, course_dir: Path, questions: list) -> list[dict[str, Any]]:
        synced_flags: dict[str, bool] = {}
        try:
            synced_flags = {item.slug: item.synced for item in application._course_chapter_plan(course_dir)}
        except (OSError, ValueError):
            pass
        grouped = group_questions_by_chapter(
            self.adapter.list_course_chapters(course_dir), questions,
            lambda chapter: self.adapter.read_chapter_question_order(course_dir, chapter),
        )
        # Kapitel koennen als `<slug>.mdx` oder `<slug>/content.mdx` eingebunden sein; der
        # Kapitelplan kennt nur den Ordner-Slug.
        return [
            {**chapter, "synced": synced_flags.get(chapter["slug"], synced_flags.get(str(chapter["slug"]).split("/")[0], True))}
            for chapter in grouped
        ]

    # -- Plattformen ------------------------------------------------------------

    def _default_moodle(self, application, course_dir: Path, chapters, hashes) -> dict[str, Any] | None:
        try:
            metadata = application.load_sync_metadata(course_dir)
        except Exception:  # noqa: BLE001 - unlesbare Metadaten wie "nicht eingerichtet" behandeln
            metadata = None
        if metadata is None:
            return None
        base_url = metadata.moodle_base_url.rstrip("/")
        url = f"{base_url}/course/view.php?id={metadata.remote_course_id}" if base_url and metadata.remote_course_id else base_url

        def status(question) -> str:
            entry = metadata.entries.get(question.identifier)
            if entry is None or not entry.remote_activity_id:
                return "missing"
            if not entry.local_hash:
                return "unknown"
            return "synced" if entry.local_hash == hashes[question.identifier] else "changed"

        local_ids = set(hashes)
        return self._platform(
            identifier="moodle",
            kind="moodle",
            label="Moodle",
            target="",
            url=url,
            host=_host(base_url),
            chapters=chapters,
            status=status,
            respects_chapter_sync=True,
            remote_only=sum(1 for identifier in metadata.entries if identifier not in local_ids),
            updated=_mtime(application._SYNC_METADATA_STORE.path(course_dir)),
        )

    def _targets(self, course_dir: Path) -> list[str]:
        names: set[str] = set()
        for prefix, suffix in TARGET_FILE_PATTERNS:
            for path in course_dir.glob(f"{prefix}*{suffix}"):
                name = path.name.removeprefix(prefix).removesuffix(suffix)
                if name:
                    names.add(name)
        return sorted(names)

    def _target_moodle(self, application, course_dir: Path, target: str, chapters, hashes) -> dict[str, Any]:
        activity_ids = application._load_target_activity_ids(course_dir, target)
        state = load_target_sync_state(course_dir, target)
        try:
            url = application._resolve_moodle_course_url(course_dir, None, target)
        except Exception:  # noqa: BLE001 - Ziel ohne hinterlegte Kurs-URL
            url = ""

        def status(question) -> str:
            if not activity_ids.get(question.identifier):
                return "missing"
            recorded = state.get(question.identifier, {}).get("hash")
            if not recorded:
                return "unknown"
            return "synced" if recorded == hashes[question.identifier] else "changed"

        local_ids = set(hashes)
        return self._platform(
            identifier=f"moodle:{target}",
            kind="moodle",
            label=f"Moodle „{target}“",
            target=target,
            url=url,
            host=_host(url),
            chapters=chapters,
            status=status,
            respects_chapter_sync=True,
            remote_only=sum(1 for identifier in activity_ids if identifier not in local_ids),
            updated=_mtime(
                application._target_activity_ids_path(course_dir, target),
                target_sync_state_path(course_dir, target),
            ),
        )

    def _site(self) -> dict[str, Any] | None:
        site_dir = self.root / "build" / "site"
        if not (site_dir / "index.html").is_file():
            return None
        host = ""
        try:
            host = (site_dir / "CNAME").read_text(encoding="utf-8").strip()
        except OSError:
            pass
        build_root = self.adapter.application().COURSE_BUILD_DIR
        return {
            "dir": site_dir,
            "host": host,
            "state": load_site_export_state(build_root, site_dir),
            "state_path": site_export_state_path(build_root, site_dir),
        }

    def _website(self, slug: str, site: dict[str, Any], chapters, hashes) -> dict[str, Any]:
        site_dir: Path = site["dir"]
        packages_dir = site_dir / "h5p" / slug
        state = site["state"].get(slug, {})

        def status(question) -> str:
            relative = Path(question.h5p_subdir) / question.package_path.name if question.h5p_subdir else Path(question.package_path.name)
            if not (packages_dir / relative).is_file():
                return "missing"
            recorded = state.get(question.identifier)
            if not recorded:
                return "unknown"
            return "synced" if recorded == hashes[question.identifier] else "changed"

        course_index = site_dir / "courses" / slug / "index.html"
        host = site["host"]
        return self._platform(
            identifier="website",
            kind="website",
            label="Website",
            target="",
            url=f"https://{host}/courses/{slug}/" if host and course_index.is_file() else "",
            host=host or "build/site",
            chapters=chapters,
            status=status,
            respects_chapter_sync=False,
            remote_only=0,
            updated=_mtime(course_index, site["state_path"]) if course_index.is_file() else None,
        )

    def _platform(self, *, identifier, kind, label, target, url, host, chapters, status,
                  respects_chapter_sync, remote_only, updated) -> dict[str, Any]:
        counts = dict.fromkeys(COUNTED_STATUSES, 0)
        excluded = 0
        chapter_rows = []
        for chapter in chapters:
            chapter_excluded = respects_chapter_sync and not chapter["synced"]
            statuses = []
            for question in chapter["questions"]:
                value = status(question)
                # Ausgenommene Kapitel zaehlen nicht zum Soll -- ausser sie liegen doch dort.
                if chapter_excluded and value == "missing":
                    value = "excluded"
                    excluded += 1
                else:
                    counts[value] += 1
                statuses.append(value)
            chapter_rows.append({"slug": chapter["slug"], "statuses": statuses})
        total = sum(counts.values())
        present = total - counts["missing"]
        return {
            "id": identifier,
            "kind": kind,
            "label": label,
            "target": target,
            "url": url,
            "host": host,
            "total": total,
            "counts": counts,
            "excluded": excluded,
            "remoteOnly": remote_only,
            "present": present,
            # Ohne erfassten Stand laesst sich nur "vorhanden" belegen, nicht "aktuell".
            "tracked": counts["unknown"] == 0,
            "percent": _percent(counts["synced"] if counts["unknown"] == 0 else present, total),
            "updatedAt": _iso(updated),
            "chapters": chapter_rows,
        }
