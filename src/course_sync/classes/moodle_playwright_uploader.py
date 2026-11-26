from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from course_sync.config.settings import FENCE_RE

@dataclass(slots=True)
class MoodleH5PUploadPackage:
    identifier: str
    title: str
    path: Path
    points: int = 2


@dataclass(slots=True)
class MoodleH5PUploadResult:
    identifier: str
    title: str
    action: str
    activity_id: int | None = None


@dataclass(slots=True)
class MoodleTextLabelUploadItem:
    identifier: str
    title: str
    markdown: str
    before_identifier: str | None = None


@dataclass(slots=True)
class MoodleSectionCleanupResult:
    title: str
    section_number: int
    action: str
    modules: list[str]


def normalize_moodle_identifier(value: str) -> str:
    normalized = value.strip().lower()
    for source, target in {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }.items():
        normalized = normalized.replace(source, target)
    normalized = unicodedata.normalize("NFKD", normalized)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return re.sub(r"-+", "-", slug)


def normalize_moodle_section_title(value: str) -> str:
    normalized = value.strip().lower()
    for source, target in {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }.items():
        normalized = normalized.replace(source, target)
    normalized = unicodedata.normalize("NFKD", normalized)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = re.sub(r"\bund\b|\band\b", " ", ascii_value)
    ascii_value = re.sub(r"[^a-z0-9]+", " ", ascii_value)
    return re.sub(r"\s+", " ", ascii_value).strip()


def _launch_moodle_browser(playwright: Any, *, headless: bool) -> Any:
    launch_options: dict[str, Any] = {"headless": headless}
    executable_path = os.environ.get("COURSE_SYNC_BROWSER_EXECUTABLE", "").strip()
    if executable_path:
        launch_options["executable_path"] = executable_path
    channel = os.environ.get("COURSE_SYNC_BROWSER_CHANNEL", "").strip()
    if channel:
        launch_options["channel"] = channel
    return playwright.chromium.launch(**launch_options)


def _slugify_identifier_part(value: str) -> str:
    normalized = value.strip().lower()
    for source, target in {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }.items():
        normalized = normalized.replace(source, target)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return re.sub(r"-+", "-", slug) or "inhalt"


def _markdown_section_title(source: str, fallback: str) -> str:
    for line in source.splitlines():
        match = re.match(r"^\s{0,3}#{2,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            return match.group(1).strip()
    return fallback


def _markdown_section_display_title(source: str, fallback: str) -> str:
    """Like _markdown_section_title, but for a heading-less segment (e.g. a chapter's
    lead-in paragraph before its first question) falls back to a short excerpt of the
    prose itself instead of a generic placeholder, so the Moodle course navigation shows
    something more useful than a bare "Inhalt" label for every such segment."""
    heading_title = _markdown_section_title(source, "")
    if heading_title:
        return heading_title
    for line in source.splitlines():
        text = line.strip().lstrip("#").strip()
        if not text:
            continue
        excerpt = re.sub(r"\s+", " ", text)
        if len(excerpt) > 60:
            excerpt = excerpt[:57].rstrip() + "…"
        return excerpt
    return fallback


def _markdown_question_identifier(h5p_subdir: str, markdown_source: str, used_identifiers: set[str]) -> str:
    title = _markdown_section_title(markdown_source, "Inhalt")
    base_identifier = _slugify_identifier_part(f"{h5p_subdir}-{title}")
    identifier = base_identifier
    suffix = 2
    while identifier in used_identifiers:
        identifier = f"{base_identifier}-{suffix}"
        suffix += 1
    used_identifiers.add(identifier)
    return identifier


def read_h5p_package_title(package_path: Path) -> str:
    with package_path.open("rb") as archive_file:
        import zipfile

        with zipfile.ZipFile(archive_file) as archive:
            metadata = json.loads(archive.read("h5p.json").decode("utf-8"))
    title = str(metadata.get("title") or package_path.stem).strip()
    return title or package_path.stem


def infer_h5p_package_points(package_path: Path) -> int:
    """Infer Moodle grade points for one H5P package.

    Rule: graded questions get 2 points, non-graded questions get 0 points.
    """
    try:
        with package_path.open("rb") as archive_file:
            import zipfile

            with zipfile.ZipFile(archive_file) as archive:
                metadata = json.loads(archive.read("h5p.json").decode("utf-8"))
                content = json.loads(archive.read("content/content.json").decode("utf-8"))
    except Exception:
        # Fallback for unusual packages: keep graded default.
        return 2

    main_library = str(metadata.get("mainLibrary") or "").strip()
    grading_settings = content.get("gradingSettings")
    grading_method = ""
    if isinstance(grading_settings, dict):
        grading_method = str(grading_settings.get("gradingMethod") or "").strip()

    if main_library == "H5P.PythonQuestion":
        if grading_method in {"", "please_choose"}:
            return 0
        return 2

    if grading_method and grading_method != "please_choose":
        return 2
    if isinstance(grading_settings, dict) and "gradingMethod" in grading_settings:
        return 0
    return 2


def format_h5p_activity_title(title: str, points: int) -> str:
    normalized_title = title.strip()
    if points <= 0 or normalized_title.lower().startswith("test:"):
        return normalized_title
    return f"Test: {normalized_title}"


# Historischer Name, wird weiter intern verwendet.
_format_h5p_activity_title = format_h5p_activity_title


def _resolve_chapter_mdx_path(course_dir: Path, chapter: str) -> Path | None:
    chapter_slug = chapter.strip().strip("/")
    chapter_path = course_dir / "chapters" / f"{chapter_slug}.mdx"
    if chapter_path.is_file():
        return chapter_path
    chapter_dir = course_dir / "chapters" / chapter_slug
    if chapter_dir.is_dir():
        chapter_content_path = chapter_dir / "content.mdx"
        if chapter_content_path.is_file():
            return chapter_content_path
        candidates = sorted(path for path in chapter_dir.rglob("*.mdx") if path.name != "content.mdx")
        if candidates:
            return candidates[0]
    return None


def read_chapter_question_order(course_dir: Path, chapter: str) -> list[str]:
    chapter_slug = chapter.strip().strip("/")
    chapter_path = _resolve_chapter_mdx_path(course_dir, chapter_slug)
    if chapter_path is None:
        return []

    source = chapter_path.read_text(encoding="utf-8")
    tag_re = re.compile(
        r"<(?:PythonQuestion|JavaQuestion|SQLQuestion|AutomataQuestion)\b(?P<attrs>.*?)\/>",
        flags=re.DOTALL,
    )
    tag_matches = list(tag_re.finditer(source))
    ordered_identifiers: list[str] = []
    for match in tag_matches:
        identifier_match = re.search(
            r"\bidentifier\s*=\s*['\"]([^'\"]+)['\"]",
            match.group("attrs"),
            flags=re.DOTALL,
        )
        identifier = identifier_match.group(1).strip() if identifier_match else ""
        if identifier:
            ordered_identifiers.append(identifier)
    return ordered_identifiers


def collect_moodle_text_labels(course_dir: Path, chapter: str) -> list[MoodleTextLabelUploadItem]:
    chapter_slug = chapter.strip().strip("/")
    chapter_path = _resolve_chapter_mdx_path(course_dir, chapter_slug)
    if chapter_path is None:
        return []

    source = chapter_path.read_text(encoding="utf-8")
    # Question payloads belong to the H5P, never to standalone Moodle labels.
    def strip_question_payload(match: re.Match[str]) -> str:
        parts = match.group("spec").split()
        return "" if len(parts) >= 2 and parts[1].startswith("question:") else match.group(0)

    source = FENCE_RE.sub(strip_question_payload, source)
    tag_re = re.compile(
        r"<(?:PythonQuestion|JavaQuestion|SQLQuestion|AutomataQuestion)\b(?P<attrs>.*?)\/>",
        flags=re.DOTALL,
    )
    heading_re = re.compile(r"^###\s+.+$", re.MULTILINE)
    events: list[tuple[int, int, str, str | None]] = []
    for match in tag_re.finditer(source):
        identifier_match = re.search(
            r"\bidentifier\s*=\s*['\"]([^'\"]+)['\"]",
            match.group("attrs"),
            flags=re.DOTALL,
        )
        identifier = identifier_match.group(1).strip() if identifier_match else None
        events.append((match.start(), match.end(), "tag", identifier))
    events.extend((match.start(), match.end(), "heading", None) for match in heading_re.finditer(source))
    events.sort(key=lambda item: (item[0], 0 if item[2] == "heading" else 1))

    used_identifiers: set[str] = set()
    labels: list[MoodleTextLabelUploadItem] = []
    section_start = 0

    def append_label(markdown_source: str, before_identifier: str | None) -> None:
        markdown_source = markdown_source.strip()
        if not markdown_source:
            return
        identifier = _markdown_question_identifier(chapter_slug, markdown_source, used_identifiers)
        marker = f"<!-- course-sync-text:{identifier} -->"
        labels.append(
            MoodleTextLabelUploadItem(
                identifier=identifier,
                title=_markdown_section_display_title(markdown_source, "Inhalt"),
                markdown=marker + "\n\n" + markdown_source,
                before_identifier=before_identifier,
            )
        )

    for event_start, event_end, event_type, event_identifier in events:
        if event_start > section_start:
            append_label(source[section_start:event_start], event_identifier if event_type == "tag" else None)
        section_start = event_end if event_type == "tag" else event_start
    if len(source) > section_start:
        append_label(source[section_start:], None)

    return labels


def collect_h5p_upload_packages(course_dir: Path, chapter: str, *, build_dir: Path | None = None) -> list[MoodleH5PUploadPackage]:
    chapter_slug = chapter.strip().strip("/")
    if not chapter_slug:
        raise ValueError("Kapitel-Slug fehlt.")

    source_dir = (build_dir if build_dir is not None else course_dir / "build") / "h5p" / chapter_slug
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Build-Ordner fuer Kapitel '{chapter_slug}' wurde nicht gefunden: {source_dir}")

    packages_by_identifier = {}
    for package_path in source_dir.glob("*.h5p"):
        points = infer_h5p_package_points(package_path)
        packages_by_identifier[package_path.stem] = MoodleH5PUploadPackage(
            identifier=package_path.stem,
            title=_format_h5p_activity_title(read_h5p_package_title(package_path), points),
            path=package_path,
            points=points,
        )
    ordered_identifiers = read_chapter_question_order(course_dir, chapter_slug)
    if ordered_identifiers:
        packages = [
            packages_by_identifier[identifier]
            for identifier in ordered_identifiers
            if identifier in packages_by_identifier
        ]
    else:
        packages = [packages_by_identifier[identifier] for identifier in sorted(packages_by_identifier)]
    if not packages:
        raise FileNotFoundError(f"Keine H5P-Pakete fuer Kapitel '{chapter_slug}' gefunden.")
    return packages


class MoodlePlaywrightUploader:
    def __init__(
        self,
        *,
        course_url: str,
        section_title: str | None = None,
        username: str | None = None,
        password: str | None = None,
        storage_state: Path | None = None,
        existing_activity_ids: dict[str, int] | None = None,
        headless: bool = False,
        timeout_ms: int = 30_000,
        sph_login_method: str | None = None,
    ) -> None:
        self.course_url = course_url
        self.section_title = section_title.strip() if section_title else ""
        self.username = username
        self.password = password
        self.storage_state = storage_state
        self.existing_activity_ids = existing_activity_ids or {}
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.sph_login_method = sph_login_method or os.environ.get("COURSE_SYNC_SPH_LOGIN_METHOD", "http")
        if self.sph_login_method not in {"http", "browser"}:
            raise ValueError("COURSE_SYNC_SPH_LOGIN_METHOD muss http oder browser sein.")

    def reconcile_course_sections(
        self,
        *,
        desired_section_titles: list[str],
        prune_extra_sections: bool = False,
    ) -> list[MoodleSectionCleanupResult]:
        if not prune_extra_sections:
            return []
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "Playwright ist nicht installiert. Installiere zuerst: "
                "python -m pip install -r requirements.txt && python -m playwright install chromium"
            ) from error

        with sync_playwright() as playwright:
            browser = _launch_moodle_browser(playwright, headless=self.headless)
            context_kwargs: dict[str, Any] = {}
            if self.storage_state and self.storage_state.exists():
                context_kwargs["storage_state"] = str(self.storage_state)
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                print(f"Oeffne Moodle-Kurs: {self.course_url}", flush=True)
                self._goto_login_resilient(page, self.course_url)
                self._login_if_needed(page)
                self._wait_for_manual_login_confirmation(page)
                self._return_to_course_after_login(page)
                self._wait_for_editing_controls_after_manual_login(page)
                print("Schalte Moodle-Bearbeitungsmodus ein.", flush=True)
                self._turn_editing_on(page)
                return self._prune_extra_course_sections(page, desired_section_titles)
            except PlaywrightTimeoutError as error:
                self._write_debug_artifacts(page, "timeout-course-section-cleanup")
                raise RuntimeError(
                    self._format_timeout_error(error, current_step="Moodle-Sections bereinigen", package=None)
                ) from error
            finally:
                if self.storage_state:
                    self.storage_state.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(self.storage_state))
                context.close()
                browser.close()

    def delete_h5p_activities(self, activity_ids: list[int]) -> list[int]:
        """Loescht die genannten H5P-Aktivitaeten im Kurs und gibt die entfernten IDs zurueck.

        Es werden nur IDs angefasst, die der Aufrufer als eigene (von course-sync angelegte)
        Aktivitaeten kennt. Jede ID wird vor dem Loeschen geoeffnet und muss eine
        H5P-Aktivitaet sein; andere Modultypen werden uebersprungen.
        """
        if not activity_ids:
            return []
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "Playwright ist nicht installiert. Installiere zuerst: "
                "python -m pip install -r requirements.txt && python -m playwright install chromium"
            ) from error

        deleted: list[int] = []
        with sync_playwright() as playwright:
            browser = _launch_moodle_browser(playwright, headless=self.headless)
            context_kwargs: dict[str, Any] = {}
            if self.storage_state and self.storage_state.exists():
                context_kwargs["storage_state"] = str(self.storage_state)
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                print(f"Oeffne Moodle-Kurs: {self.course_url}", flush=True)
                self._goto_login_resilient(page, self.course_url)
                self._login_if_needed(page)
                self._wait_for_manual_login_confirmation(page)
                self._return_to_course_after_login(page)
                self._wait_for_editing_controls_after_manual_login(page)
                self._turn_editing_on(page)
                base = urljoin(self.course_url, "/")
                for activity_id in activity_ids:
                    page.goto(f"{base}mod/h5pactivity/view.php?id={activity_id}", wait_until="domcontentloaded")
                    if "/mod/h5pactivity/" not in self._current_page_url(page):
                        print(f"Ueberspringe ID {activity_id}: keine H5P-Aktivitaet mehr vorhanden.", flush=True)
                        continue
                    title = page.title()
                    print(f"Loesche veraltete H5P-Aktivitaet {activity_id}: {title}", flush=True)
                    params = {"delete": str(activity_id), "sesskey": self._moodle_sesskey(page)}
                    page.goto(urljoin(base, "course/mod.php") + "?" + urlencode(params), wait_until="domcontentloaded")
                    self._confirm_section_delete_if_needed(page)
                page.goto(self.course_url, wait_until="domcontentloaded")
                remaining = {
                    int(match)
                    for match in page.evaluate(
                        """() => [...document.querySelectorAll('a[href*="/mod/h5pactivity/view.php"]')]
                            .map(link => new URL(link.href).searchParams.get('id')).filter(Boolean)"""
                    )
                }
                deleted = [activity_id for activity_id in activity_ids if activity_id not in remaining]
                still_there = [activity_id for activity_id in activity_ids if activity_id in remaining]
                if still_there:
                    print(f"Warnung: Diese Aktivitaeten sind weiterhin vorhanden: {still_there}", flush=True)
            except PlaywrightTimeoutError as error:
                self._write_debug_artifacts(page, "timeout-delete-activities")
                raise RuntimeError(
                    self._format_timeout_error(error, current_step="Veraltete H5P-Aktivitaeten loeschen", package=None)
                ) from error
            finally:
                if self.storage_state:
                    self.storage_state.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(self.storage_state))
                context.close()
                browser.close()
        return deleted

    def upload_packages(self, packages: list[MoodleH5PUploadPackage]) -> list[MoodleH5PUploadResult]:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "Playwright ist nicht installiert. Installiere zuerst: "
                "python -m pip install -r requirements.txt && python -m playwright install chromium"
            ) from error

        results: list[MoodleH5PUploadResult] = []
        with sync_playwright() as playwright:
            browser = _launch_moodle_browser(playwright, headless=self.headless)
            context_kwargs: dict[str, Any] = {}
            if self.storage_state and self.storage_state.exists():
                context_kwargs["storage_state"] = str(self.storage_state)
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.set_default_timeout(self.timeout_ms)
            current_package: MoodleH5PUploadPackage | None = None
            current_step = "Moodle-Kurs oeffnen"

            try:
                print(f"Oeffne Moodle-Kurs: {self.course_url}", flush=True)
                self._goto_login_resilient(page, self.course_url)
                current_step = "Login pruefen"
                self._login_if_needed(page)
                self._wait_for_manual_login_confirmation(page)
                self._return_to_course_after_login(page)
                self._wait_for_editing_controls_after_manual_login(page)
                print("Schalte Moodle-Bearbeitungsmodus ein.", flush=True)
                current_step = "Bearbeitungsmodus einschalten"
                self._turn_editing_on(page)
                section: dict[str, str | int] | None = None
                known_activities: dict[str, int] = {}

                def ensure_section() -> dict[str, str | int]:
                    nonlocal section, known_activities, current_step
                    if section is not None:
                        return section
                    current_step = "Moodle-Section suchen"
                    print(f"Suche Moodle-Section: {self.section_title or '(erste gefundene Section)'}", flush=True)
                    section = self._find_or_create_section(page, packages)
                    print(f"Verwende Moodle-Section {section['number']}. Sammle vorhandene H5P-Aktivitaeten.", flush=True)
                    current_step = f"H5P-Aktivitaeten in Section {section['number']} sammeln"
                    known_activities = self._collect_section_h5p_activities(page, section["selector"])
                    return section

                def restore_course_section_context() -> None:
                    nonlocal section, known_activities, current_step
                    if section is None:
                        return
                    section_selector = str(section["selector"])
                    selector_is_present = False
                    if self._course_page_is_open(page):
                        try:
                            selector_is_present = page.locator(section_selector).count() > 0
                        except Exception:
                            selector_is_present = False
                    if selector_is_present:
                        return
                    current_step = "Moodle-Kursseite wieder oeffnen"
                    if not self._course_page_is_open(page):
                        page.goto(self.course_url, wait_until="domcontentloaded")
                    self._turn_editing_on(page)
                    section_number = int(section["number"])
                    section = self._section_by_number(page, section_number)
                    if section is None:
                        raise RuntimeError(f"Moodle-Section {section_number} wurde nach dem Speichern nicht gefunden.")
                    known_activities = {}

                for package in packages:
                    current_package = package
                    current_step = f"H5P-Paket verarbeiten: {package.identifier}"
                    print(f"Verarbeite H5P-Paket: {package.identifier} ({package.title})", flush=True)
                    restore_course_section_context()
                    activity_id: int | None = None
                    target_section_number: int | None = None
                    # Try a previously recorded activity id before resolving/creating a Moodle
                    # section at all. Some course formats (e.g. format_tiles/"Kachelformat") do not
                    # render section content on the main course page, which makes section discovery
                    # unreliable there; an already-known activity can be updated in place via its own
                    # id (course/modedit.php?update=<id>) without needing the section to be found.
                    preresolved_activity_id = self._resolve_existing_activity_id(
                        package,
                        {},
                        require_section_match=False,
                    )
                    if preresolved_activity_id is not None:
                        activity_id = preresolved_activity_id
                    elif self.section_title:
                        target_section = ensure_section()
                        target_section_number = int(target_section["number"])
                        activity_id = self._resolve_existing_activity_id(
                            package,
                            known_activities,
                            require_section_match=False,
                        )
                    else:
                        activity_id = self._resolve_existing_activity_id(
                            package,
                            known_activities,
                            require_section_match=False,
                        )

                    if activity_id is not None:
                        current_step = f"H5P-Aktivitaet aktualisieren: {package.identifier}"
                        print(f"Aktualisiere H5P-Aktivitaet {activity_id}: {package.title}", flush=True)
                        result = self._update_h5p_activity(
                            page,
                            activity_id,
                            package,
                            section_number=target_section_number,
                        )
                        if result is not None:
                            results.append(result)
                            continue
                        print(
                            f"Warnung: H5P-Aktivitaet {activity_id} konnte nicht geoeffnet werden. "
                            "Lege sie neu an.",
                            flush=True,
                        )
                        section = None
                        known_activities = {}
                        self.existing_activity_ids.pop(package.identifier, None)
                        self.existing_activity_ids.pop(normalize_moodle_identifier(package.identifier), None)
                        self.existing_activity_ids.pop(normalize_moodle_identifier(package.title), None)
                        page.goto(self.course_url, wait_until="domcontentloaded")
                        self._turn_editing_on(page)

                    target_section = ensure_section()
                    section_number = int(target_section["number"])
                    known_activities = self._collect_section_h5p_activities(page, target_section["selector"])
                    refreshed_activity_id = self._resolve_existing_activity_id(
                        package,
                        known_activities,
                        require_section_match=True,
                    )
                    if refreshed_activity_id is not None:
                        current_step = f"H5P-Aktivitaet aktualisieren: {package.identifier}"
                        print(f"Aktualisiere H5P-Aktivitaet {refreshed_activity_id}: {package.title}", flush=True)
                        result = self._update_h5p_activity(
                            page,
                            refreshed_activity_id,
                            package,
                            section_number=section_number,
                        )
                        if result is not None:
                            results.append(result)
                            continue
                        print(
                            f"Warnung: H5P-Aktivitaet {refreshed_activity_id} konnte nicht geoeffnet werden. "
                            "Lege sie neu an.",
                            flush=True,
                        )
                        section = None
                        known_activities = {}
                        page.goto(self.course_url, wait_until="domcontentloaded")
                        self._turn_editing_on(page)
                        target_section = ensure_section()
                        section_number = int(target_section["number"])

                    print(f"Lege neue H5P-Aktivitaet an: {package.title}", flush=True)
                    current_step = f"H5P-Aktivitaet anlegen: {package.identifier}"
                    result = self._create_h5p_activity(page, section_number, package)
                    if result.activity_id:
                        known_activities[normalize_moodle_identifier(package.identifier)] = result.activity_id
                        known_activities[normalize_moodle_identifier(package.title)] = result.activity_id
                    results.append(result)

                if packages:
                    current_package = None
                    current_step = "H5P-Aktivitaeten sortieren"
                    restore_course_section_context()
                    target_section = ensure_section()
                    self._sort_section_h5p_activities(page, int(target_section["number"]), packages)

                if self.storage_state:
                    current_step = "Moodle-Login-Status speichern"
                    print(f"Speichere Moodle-Login-Status: {self.storage_state}", flush=True)
                    self.storage_state.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(self.storage_state))
            except PlaywrightTimeoutError as error:
                debug_label = normalize_moodle_identifier(current_step)
                self._write_debug_artifacts(page, f"timeout-{debug_label}")
                raise RuntimeError(
                    self._format_timeout_error(error, current_step=current_step, package=current_package)
                ) from error
            finally:
                context.close()
                browser.close()

        return results

    def sync_text_labels(
        self,
        labels: list[MoodleTextLabelUploadItem],
        *,
        anchor_activity_ids: dict[str, int] | None = None,
        chapter: str = "",
    ) -> list[MoodleH5PUploadResult]:
        if not labels and not chapter:
            return []
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "Playwright ist nicht installiert. Installiere zuerst: "
                "python -m pip install -r requirements.txt && python -m playwright install chromium"
            ) from error

        results: list[MoodleH5PUploadResult] = []
        current_label: MoodleTextLabelUploadItem | None = None
        current_step = "Moodle-Kurs oeffnen"
        anchor_activity_ids = anchor_activity_ids or {}
        with sync_playwright() as playwright:
            browser = _launch_moodle_browser(playwright, headless=self.headless)
            context_kwargs: dict[str, Any] = {}
            if self.storage_state and self.storage_state.exists():
                context_kwargs["storage_state"] = str(self.storage_state)
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                self._goto_login_resilient(page, self.course_url)
                self._login_if_needed(page)
                self._return_to_course_after_login(page)
                self._wait_for_editing_controls_after_manual_login(page)
                self._disable_user_text_editor_if_needed(page)
                page.goto(self.course_url, wait_until="domcontentloaded")
                self._turn_editing_on(page)
                section = self._find_or_create_section(page, [])
                section_number = int(section["number"])

                for label in labels:
                    current_label = label
                    current_step = f"Textfeld synchronisieren: {label.identifier}"
                    print(f"Synchronisiere Moodle-Textfeld: {label.identifier} ({label.title})", flush=True)
                    page.goto(self.course_url, wait_until="domcontentloaded")
                    self._turn_editing_on(page)
                    section = self._section_by_number(page, section_number)
                    if section is None:
                        raise RuntimeError(f"Moodle-Section {section_number} wurde nicht gefunden.")
                    existing_activity_id = self._find_text_label_activity_id(
                        page,
                        str(section["selector"]),
                        label.identifier,
                        title=label.title,
                    )
                    if existing_activity_id is None:
                        existing_activity_id = self._find_text_label_activity_id_via_section_page(
                            page,
                            section,
                            section_number,
                            label,
                        )
                    before_activity_id = (
                        anchor_activity_ids.get(label.before_identifier or "")
                        or anchor_activity_ids.get(normalize_moodle_identifier(label.before_identifier or ""))
                    )
                    if existing_activity_id is None:
                        result = self._create_text_label(
                            page,
                            section_number,
                            label,
                            before_activity_id=before_activity_id,
                        )
                    else:
                        result = self._update_text_label(page, existing_activity_id, label)
                        if before_activity_id:
                            self._move_activity_before(page, existing_activity_id, before_activity_id)
                    results.append(result)

                if chapter:
                    self._prune_stale_text_labels(page, section_number, chapter, {label.identifier for label in labels})

                if self.storage_state:
                    self.storage_state.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(self.storage_state))
            except PlaywrightTimeoutError as error:
                debug_label = normalize_moodle_identifier(current_step)
                self._write_debug_artifacts(page, f"timeout-{debug_label}")
                raise RuntimeError(
                    self._format_timeout_error(error, current_step=current_step, package=None)
                ) from error
            finally:
                context.close()
                browser.close()
        return results

    def _managed_text_labels(self, page: Any, section: dict[str, Any]) -> list[dict[str, Any]]:
        return page.locator(str(section["selector"])).evaluate(
            r"""section => [...section.querySelectorAll('[data-cmid], li.activity[id^="module-"]')]
                .filter(module => !module.parentElement?.closest('[data-cmid], li.activity[id^="module-"]'))
                .filter(module => !module.querySelector('a[href*="/mod/h5pactivity/"]'))
                .flatMap(module => {
                    const match = module.innerHTML.match(/<!--\s*course-sync-text:([^\s>]+)\s*-->/);
                    const id = Number(module.dataset.cmid || (module.id.match(/module-(\d+)/) || [])[1]);
                    return match && id ? [{id, identifier: match[1]}] : [];
                })"""
        )

    def _prune_stale_text_labels(
        self, page: Any, section_number: int, chapter: str, expected: set[str],
    ) -> None:
        page.goto(self.course_url, wait_until="domcontentloaded")
        section = self._section_by_number(page, section_number)
        if section is None:
            raise RuntimeError(f"Moodle-Section {section_number} fuer Textabgleich fehlt.")
        section = self._goto_populated_section_page(page, section, section_number) or section
        stale = [item for item in self._managed_text_labels(page, section)
                 if str(item["identifier"]).startswith(chapter + "-") and item["identifier"] not in expected]
        for item in stale:
            print(f"Entferne veraltetes Moodle-Textfeld: {item['identifier']} (ID {item['id']})", flush=True)
            params = {"delete": str(item["id"]), "sesskey": self._moodle_sesskey(page)}
            page.goto(urljoin(self.course_url, "/course/mod.php") + "?" + urlencode(params), wait_until="domcontentloaded")
            self._confirm_section_delete_if_needed(page)
        if stale:
            page.goto(self.course_url, wait_until="domcontentloaded")
            section = self._section_by_number(page, section_number)
            if section is None:
                raise RuntimeError(f"Moodle-Section {section_number} nach Textabgleich fehlt.")
            section = self._goto_populated_section_page(page, section, section_number) or section
            remaining = {int(item["id"]) for item in self._managed_text_labels(page, section)}
            if remaining.intersection(int(item["id"]) for item in stale):
                raise RuntimeError("Veraltete Moodle-Textfelder konnten nicht vollstaendig entfernt werden.")

    def ensure_section_hidden(self) -> None:
        """Legt die Kapitel-Section bei Bedarf an und verbirgt sie fuer Lernende.

        Laeuft bewusst vor dem Aktivitaets-Upload, damit neue Inhalte nie sichtbar sind.
        """
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "Playwright ist nicht installiert. Installiere zuerst: "
                "python -m pip install -r requirements.txt && python -m playwright install chromium"
            ) from error
        if not self.section_title:
            raise RuntimeError("Section verbergen benoetigt einen Section-Titel.")

        current_step = "Moodle-Kurs oeffnen"
        with sync_playwright() as playwright:
            browser = _launch_moodle_browser(playwright, headless=self.headless)
            context_kwargs: dict[str, Any] = {}
            if self.storage_state and self.storage_state.exists():
                context_kwargs["storage_state"] = str(self.storage_state)
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                self._goto_login_resilient(page, self.course_url)
                current_step = "Login pruefen"
                self._login_if_needed(page)
                self._wait_for_manual_login_confirmation(page)
                self._return_to_course_after_login(page)
                self._wait_for_editing_controls_after_manual_login(page)
                self._turn_editing_on(page)
                current_step = "Moodle-Section suchen"
                section = self._find_or_create_section(page, [])
                current_step = f"Section {section['number']} verbergen"
                self._hide_section(page, int(section["number"]))
                if self.storage_state:
                    self.storage_state.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(self.storage_state))
            except PlaywrightTimeoutError as error:
                self._write_debug_artifacts(page, f"timeout-{normalize_moodle_identifier(current_step)}")
                raise RuntimeError(
                    self._format_timeout_error(error, current_step=current_step, package=None)
                ) from error
            finally:
                context.close()
                browser.close()

    def ensure_section_visible(self) -> None:
        """Legt die Kapitel-Section bei Bedarf an und macht sie fuer Lernende sichtbar.

        Laeuft bewusst vor dem Aktivitaets-Upload, damit eine zuvor verborgene Section
        nicht verborgen bleibt, nachdem sie lokal als nicht mehr `hidden` markiert wurde.
        """
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "Playwright ist nicht installiert. Installiere zuerst: "
                "python -m pip install -r requirements.txt && python -m playwright install chromium"
            ) from error
        if not self.section_title:
            raise RuntimeError("Section sichtbar machen benoetigt einen Section-Titel.")

        current_step = "Moodle-Kurs oeffnen"
        with sync_playwright() as playwright:
            browser = _launch_moodle_browser(playwright, headless=self.headless)
            context_kwargs: dict[str, Any] = {}
            if self.storage_state and self.storage_state.exists():
                context_kwargs["storage_state"] = str(self.storage_state)
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                self._goto_login_resilient(page, self.course_url)
                current_step = "Login pruefen"
                self._login_if_needed(page)
                self._wait_for_manual_login_confirmation(page)
                self._return_to_course_after_login(page)
                self._wait_for_editing_controls_after_manual_login(page)
                self._turn_editing_on(page)
                current_step = "Moodle-Section suchen"
                section = self._find_or_create_section(page, [])
                current_step = f"Section {section['number']} sichtbar machen"
                self._show_section(page, int(section["number"]))
                if self.storage_state:
                    self.storage_state.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(self.storage_state))
            except PlaywrightTimeoutError as error:
                self._write_debug_artifacts(page, f"timeout-{normalize_moodle_identifier(current_step)}")
                raise RuntimeError(
                    self._format_timeout_error(error, current_step=current_step, package=None)
                ) from error
            finally:
                context.close()
                browser.close()

    def _moodle_ajax(self, page: Any, method: str, args: dict[str, Any]) -> Any:
        return page.evaluate(
            """
            ({ method, args }) => new Promise((resolve, reject) => {
              require(['core/ajax'], (Ajax) => {
                Ajax.call([{ methodname: method, args }])[0]
                  .then(resolve)
                  .catch((error) => reject(new Error((error && (error.message || error.error)) || String(error))));
              });
            })
            """,
            {"method": method, "args": args},
        )

    def _course_section_state(self, page: Any, section_number: int) -> dict[str, Any] | None:
        raw_state = self._moodle_ajax(page, "core_courseformat_get_state", {"courseid": self._course_id()})
        state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
        for entry in (state or {}).get("section", []):
            if int(entry.get("number", -1)) == section_number:
                return entry
        return None

    def _hide_section(self, page: Any, section_number: int) -> None:
        section_state = self._course_section_state(page, section_number)
        if section_state is None:
            raise RuntimeError(f"Moodle-Section {section_number} wurde im Kurs-Status nicht gefunden.")
        if not section_state.get("visible", True):
            print(f"Moodle-Section {section_number} ist bereits verborgen.", flush=True)
            return
        print(f"Verberge Moodle-Section {section_number} '{self.section_title}'.", flush=True)
        self._moodle_ajax(
            page,
            "core_courseformat_update_course",
            {"action": "section_hide", "courseid": self._course_id(), "ids": [int(section_state["id"])]},
        )
        page.goto(self.course_url, wait_until="domcontentloaded")
        section_state = self._course_section_state(page, section_number)
        if section_state is None or section_state.get("visible", True):
            self._write_debug_artifacts(page, f"hide-section-{section_number}-failed")
            raise RuntimeError(f"Moodle-Section {section_number} konnte nicht verborgen werden.")
        print(f"Moodle-Section {section_number} ist jetzt verborgen.", flush=True)

    def _show_section(self, page: Any, section_number: int) -> None:
        section_state = self._course_section_state(page, section_number)
        if section_state is None:
            raise RuntimeError(f"Moodle-Section {section_number} wurde im Kurs-Status nicht gefunden.")
        if section_state.get("visible", True):
            print(f"Moodle-Section {section_number} ist bereits sichtbar.", flush=True)
            return
        print(f"Mache Moodle-Section {section_number} '{self.section_title}' sichtbar.", flush=True)
        self._moodle_ajax(
            page,
            "core_courseformat_update_course",
            {"action": "section_show", "courseid": self._course_id(), "ids": [int(section_state["id"])]},
        )
        page.goto(self.course_url, wait_until="domcontentloaded")
        section_state = self._course_section_state(page, section_number)
        if section_state is None or not section_state.get("visible", True):
            self._write_debug_artifacts(page, f"show-section-{section_number}-failed")
            raise RuntimeError(f"Moodle-Section {section_number} konnte nicht sichtbar gemacht werden.")
        print(f"Moodle-Section {section_number} ist jetzt sichtbar.", flush=True)

    def _disable_user_text_editor_if_needed(self, page: Any) -> None:
        page.goto(urljoin(self.course_url, "/user/editor.php"), wait_until="domcontentloaded")
        editor_select = page.locator('select[name="preference_htmleditor"], #id_preference_htmleditor')
        if editor_select.count() == 0:
            return
        current_value = str(editor_select.first.input_value()).strip()
        if current_value != "textarea":
            editor_select.first.select_option(value="textarea")
            self._click_first_by_text(
                page,
                [
                    "Änderungen speichern",
                    "Save changes",
                    "Speichern",
                    "Save",
                ],
            )
            page.wait_for_load_state("domcontentloaded")

    def _prune_extra_course_sections(
        self,
        page: Any,
        desired_section_titles: list[str],
    ) -> list[MoodleSectionCleanupResult]:
        desired_titles = {
            normalize_moodle_section_title(title)
            for title in desired_section_titles
            if normalize_moodle_section_title(title)
        }
        if not desired_titles:
            return []

        results: list[MoodleSectionCleanupResult] = []
        for _ in range(20):
            page.goto(self.course_url, wait_until="domcontentloaded")
            self._turn_editing_on(page)
            sections = self._course_sections_snapshot(page)
            extra_sections = [
                section
                for section in sections
                if int(section["number"]) > 0
                and normalize_moodle_section_title(str(section.get("title") or "")) not in desired_titles
            ]
            if not extra_sections:
                return results

            section = extra_sections[-1]
            modules = [str(module.get("name") or module.get("modname") or "") for module in section.get("modules", [])]
            unsafe_modules = [
                module
                for module in section.get("modules", [])
                if str(module.get("modname") or "") not in {"", "h5pactivity"}
            ]
            if unsafe_modules:
                unsafe_labels = ", ".join(str(module.get("name") or module.get("modname") or "") for module in unsafe_modules)
                raise RuntimeError(
                    f"Ueberzaehlige Moodle-Section '{section.get('title')}' "
                    f"(Section {section.get('number')}) enthaelt Nicht-H5P-Inhalte: {unsafe_labels}. "
                    "Automatisches Loeschen wurde abgebrochen."
                )

            print(
                f"Loesche ueberzaehlige Moodle-Section {section['number']}: {section.get('title') or '(ohne Titel)'}",
                flush=True,
            )
            if not self._delete_section(page, section):
                raise RuntimeError(
                    f"Ueberzaehlige Moodle-Section '{section.get('title')}' "
                    f"(Section {section.get('number')}) konnte nicht geloescht werden."
                )
            results.append(
                MoodleSectionCleanupResult(
                    title=str(section.get("title") or ""),
                    section_number=int(section["number"]),
                    action="deleted",
                    modules=modules,
                )
            )
        raise RuntimeError("Moodle-Section-Bereinigung wurde nach zu vielen Loeschversuchen abgebrochen.")

    def _course_sections_snapshot(self, page: Any) -> list[dict[str, Any]]:
        payload = page.evaluate(
            """
            () => {
              const sectionSelector = 'li.section, li.course-section, section.course-section';
              const sections = [...document.querySelectorAll(sectionSelector)].filter((section) =>
                !section.parentElement?.closest(sectionSelector)
              );
              return sections
                .filter((section) => !section.classList.contains('delegated-section') && !section.classList.contains('subsection'))
                .map((section) => {
                  const numberValue = section.getAttribute('data-number')
                    || section.getAttribute('data-section')
                    || (section.id.match(/section-(\\d+)/) || [])[1]
                    || section.querySelector('[data-sectionnum]')?.getAttribute('data-sectionnum');
                  const number = Number.parseInt(numberValue || '', 10);
                  const marker = `course-sync-section-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                  section.setAttribute('data-course-sync-section', marker);
                  const modules = [...section.querySelectorAll('li.activity, [data-activityname]')]
                    .filter((activity, index, all) => all.findIndex((item) => item === activity || item.contains(activity)) === index)
                    .map((activity) => {
                      const link = activity.querySelector('a[href*="/mod/"]');
                      const href = link?.href || '';
                      const modMatch = href.match(/\\/mod\\/([^/]+)\\//);
                      const name = activity.getAttribute('data-activityname')
                        || activity.querySelector('[data-value]')?.getAttribute('data-value')
                        || link?.textContent
                        || activity.textContent
                        || '';
                      return {
                        id: Number.parseInt(new URL(href || window.location.href).searchParams.get('id') || '', 10) || 0,
                        modname: modMatch ? modMatch[1] : '',
                        name: name.trim(),
                      };
                    });
                  return {
                    selector: `[data-course-sync-section="${marker}"]`,
                    number,
                    title: (section.getAttribute('data-sectionname') || section.querySelector('.sectionname, .section-title, h3, h4')?.textContent || '').trim(),
                    sectionDbId: section.getAttribute('data-id') || section.getAttribute('data-sectionid') || '',
                    modules,
                  };
                })
                .filter((section) => !Number.isNaN(section.number));
            }
            """
        )
        return [dict(section) for section in payload if isinstance(section, dict)]

    def _delete_section(self, page: Any, section: dict[str, Any]) -> bool:
        if self._delete_section_by_link(page, section):
            return True
        return self._delete_section_by_url(page, section)

    def _delete_section_by_link(self, page: Any, section: dict[str, Any]) -> bool:
        delete_href = page.locator(str(section["selector"])).evaluate(
            """
            (section) => {
              const links = [...section.querySelectorAll('a[href]')];
              const byHref = links.find((link) => /deletesection|delete(section)?=1|sectiondelete/i.test(link.href || ''));
              if (byHref) return byHref.href;
              const byLabel = links.find((link) =>
                /Abschnitt löschen|Abschnitt loeschen|Delete section|Delete topic/i.test(
                  link.textContent || link.getAttribute('aria-label') || link.getAttribute('title') || ''
                )
              );
              return byLabel ? byLabel.href : '';
            }
            """
        )
        if not delete_href:
            return False
        page.goto(str(delete_href), wait_until="domcontentloaded")
        self._confirm_section_delete_if_needed(page)
        page.goto(self.course_url, wait_until="domcontentloaded")
        return not self._section_still_exists(page, section)

    def _delete_section_by_url(self, page: Any, section: dict[str, Any]) -> bool:
        section_number = int(section["number"])
        sesskey = self._moodle_sesskey(page)
        if not sesskey:
            return False
        urls = [
            urljoin(self.course_url, "/course/format/topics/deletesection.php")
            + "?"
            + urlencode({"courseid": str(self._course_id()), "section": str(section_number), "confirm": "1", "sesskey": sesskey}),
            urljoin(self.course_url, "/course/changenumsections.php")
            + "?"
            + urlencode({"courseid": str(self._course_id()), "deletesection": str(section_number), "sesskey": sesskey}),
        ]
        for target_url in urls:
            try:
                page.goto(target_url, wait_until="domcontentloaded")
                self._confirm_section_delete_if_needed(page)
                page.goto(self.course_url, wait_until="domcontentloaded")
            except Exception:
                continue
            if not self._section_still_exists(page, section):
                return True
        return False

    def _section_still_exists(self, page: Any, deleted_section: dict[str, Any]) -> bool:
        deleted_title = normalize_moodle_section_title(str(deleted_section.get("title") or ""))
        deleted_db_id = str(deleted_section.get("sectionDbId") or "").strip()
        for section in self._course_sections_snapshot(page):
            if deleted_db_id and str(section.get("sectionDbId") or "").strip() == deleted_db_id:
                return True
            if deleted_title and normalize_moodle_section_title(str(section.get("title") or "")) == deleted_title:
                return True
        return False

    def _confirm_section_delete_if_needed(self, page: Any) -> None:
        selectors = [
            ".modal-dialog button:has-text('Löschen')",
            ".modal-dialog button:has-text('Loeschen')",
            ".modal-dialog button:has-text('Delete')",
            ".modal-dialog button:has-text('Fortfahren')",
            ".modal-dialog button:has-text('Continue')",
            "[role='dialog'] button:has-text('Löschen')",
            "[role='dialog'] button:has-text('Loeschen')",
            "[role='dialog'] button:has-text('Delete')",
            "[role='dialog'] button:has-text('Fortfahren')",
            "[role='dialog'] button:has-text('Continue')",
            "form[action*='deletesection'] button[type='submit']",
            "form[action*='deletesection'] input[type='submit']",
            "form button[type='submit']:has-text('Löschen')",
            "form button[type='submit']:has-text('Delete')",
        ]
        for selector in selectors:
            locator = page.locator(selector)
            button = self._first_clickable(locator)
            if button is not None:
                button.click()
                page.wait_for_load_state("domcontentloaded")
                return
        for label in ["Delete", "Löschen", "Loeschen", "Fortfahren", "Continue", "Ja", "Yes"]:
            button = self._first_clickable(page.get_by_role("button", name=re.compile(f"^{re.escape(label)}$", re.IGNORECASE)))
            if button is not None:
                button.click()
                page.wait_for_load_state("domcontentloaded")
                return
            locator = page.get_by_role("link", name=re.compile(label, re.IGNORECASE))
            link = self._first_clickable(locator)
            if link is not None:
                link.click()
                page.wait_for_load_state("domcontentloaded")
                return

    def _resolve_existing_activity_id(
        self,
        package: MoodleH5PUploadPackage,
        section_activities: dict[str, int],
        *,
        require_section_match: bool,
    ) -> int | None:
        identifier_keys = [
            package.identifier,
            normalize_moodle_identifier(package.identifier),
        ]
        title_keys = [
            normalize_moodle_identifier(package.title),
        ]
        for key in identifier_keys:
            activity_id = self.existing_activity_ids.get(key)
            if activity_id is None:
                continue
            if require_section_match and activity_id not in set(section_activities.values()):
                continue
            return activity_id

        for key in identifier_keys:
            activity_id = section_activities.get(key)
            if activity_id is not None:
                return activity_id

        if self._looks_like_generated_markdown_package(package):
            return None

        for key in title_keys:
            activity_id = self.existing_activity_ids.get(key)
            if activity_id is None:
                continue
            if require_section_match and activity_id not in set(section_activities.values()):
                continue
            return activity_id
        for key in title_keys:
            activity_id = section_activities.get(key)
            if activity_id is not None:
                return activity_id
        return None

    def _looks_like_generated_markdown_package(self, package: MoodleH5PUploadPackage) -> bool:
        chapter_slug = package.path.parent.name
        return bool(chapter_slug) and package.identifier.startswith(f"{chapter_slug}-")

    def _login_if_needed(self, page: Any) -> None:
        if self.username and self.password:
            self._login_with_credentials_if_needed(page)
            return

        if not self._login_is_required(page):
            return

        if self.headless:
            raise RuntimeError(
                "Moodle verlangt Login oder die gespeicherte Session ist nur als Gast angemeldet "
                "(wahrscheinlich abgelaufener SSO-Storage-State oder falscher Storage-State). "
                "Fuehre den Upload einmal ohne --headless aus oder setze Moodle-Zugangsdaten "
                "(MOODLE_USERNAME/MOODLE_PASSWORD, kursbezogene MOODLE_<KURS>_USERNAME/MOODLE_<KURS>_PASSWORD "
                "oder --username/--password), damit Headless automatisch neu einloggen kann. "
                f"Aktuelle URL: {self._current_page_url(page) or 'unbekannt'}"
            )

        print("Moodle verlangt Login. Bitte im Browser anmelden.")
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if not self._login_is_required(page):
                return
            page.wait_for_timeout(1000)
        raise RuntimeError("Login wurde nicht innerhalb von 5 Minuten abgeschlossen.")

    def _goto_login_resilient(self, page: Any, url: str) -> None:
        """Navigate through slow SSO redirect chains without requiring a load event."""
        navigation_timeout = min(self.timeout_ms, 20_000)
        try:
            page.goto(url, wait_until="commit", timeout=navigation_timeout)
        except Exception as error:
            # Schulportal may keep replacing the document while its SAML chain is
            # still progressing. Once a URL is committed, inspect that page instead
            # of treating the missing load event as a failed login.
            if not self._current_page_url(page):
                raise
            print(
                "SSO-Navigation laeuft noch; pruefe die bereits erreichte Loginseite weiter.",
                flush=True,
            )

        deadline = time.monotonic() + (self.timeout_ms / 1000)
        while time.monotonic() < deadline:
            try:
                if self._looks_logged_in(page):
                    return
                current = urlparse(self._current_page_url(page))
                target = urlparse(self.course_url)
                # Moodle can send anonymous visitors to enrolment before showing
                # a login form. Hand that page to _login_if_needed as well.
                if current.netloc == target.netloc and current.path == "/enrol/index.php":
                    return
                if current.netloc == target.netloc and not self._login_is_required(page):
                    return
                if self._schulportal_hessen_login_page_is_open(page):
                    return
                if self._first_visible_enabled_locator(
                    page,
                    [
                        'input[name="username"]',
                        'input[name="user"]',
                        'input[name="login"]',
                        'input[type="email"]',
                        'input[type="text"]',
                    ],
                ) is not None:
                    return
            except Exception:
                # A redirect replaced the execution context between two probes.
                pass
            page.wait_for_timeout(250)

        raise RuntimeError(
            "Die Moodle-/SSO-Seite wurde erreicht, stellte aber weder Kurs noch Loginformular bereit. "
            f"Aktuelle URL: {self._current_page_url(page) or 'unbekannt'}"
        )

    def _login_with_credentials_if_needed(self, page: Any) -> None:
        if self._looks_logged_in(page):
            return
        if not self._login_is_required(page):
            return

        if self._schulportal_hessen_login_page_is_open(page):
            self._login_with_schulportal_hessen_credentials(page)
            self._finish_credential_login(page)
            return

        login_url = urljoin(self.course_url, "/login/index.php")
        print("Melde mit hinterlegten Moodle-Zugangsdaten an.", flush=True)
        if page.locator('input[name="username"]').count() == 0:
            self._goto_login_resilient(page, login_url)

        if self._schulportal_hessen_login_page_is_open(page):
            self._login_with_schulportal_hessen_credentials(page)
            self._finish_credential_login(page)
            return

        username_input = self._first_visible_enabled_locator(
            page,
            [
                'input[name="username"]',
                'input[name="user"]',
                'input[name="login"]',
                'input[name="email"]',
                'input[type="email"]',
                'input[type="text"]',
            ],
        )
        password_input = self._first_visible_enabled_locator(page, ['input[name="password"]', 'input[type="password"]'])
        if username_input is None or password_input is None:
            if self._external_login_page_is_open(page):
                raise RuntimeError(
                    "Moodle hat auf einen externen SSO-Login umgeleitet. "
                    "Die hinterlegten MOODLE_USERNAME/MOODLE_PASSWORD koennen dort nicht automatisch verwendet werden. "
                    "Bitte den Storage-State im headed Browser neu erzeugen und den Upload erneut starten. "
                    f"Aktuelle URL: {self._current_page_url(page) or 'unbekannt'}"
                )
            raise RuntimeError("Moodle-Loginformular wurde nicht gefunden, obwohl Zugangsdaten gesetzt sind.")

        username_input.fill(self.username or "")
        password_input.fill(self.password or "")
        submit = self._first_visible_enabled_locator(
            page,
            [
                "#loginbtn",
                'button[type="submit"]',
                'input[type="submit"]',
                'button[name="submit"]',
            ],
        )
        if submit is not None:
            submit.click()
        else:
            self._click_first_by_text(page, ["Log in", "Login", "Einloggen", "Anmelden"])
        page.wait_for_load_state("domcontentloaded")

        if page.locator('input[name="username"]').count() > 0:
            raise RuntimeError("Moodle-Login mit den hinterlegten Zugangsdaten ist fehlgeschlagen.")

        self._finish_credential_login(page)

    def _finish_credential_login(self, page: Any) -> None:
        self._goto_login_resilient(page, self.course_url)
        if self._login_is_required(page):
            raise RuntimeError(
                "Moodle verlangt nach dem Login erneut Zugangsdaten. "
                "Bitte pruefe Benutzername/Passwort oder erneuere den SSO-Login im sichtbaren Browser. "
                f"Aktuelle URL: {self._current_page_url(page) or 'unbekannt'}"
            )

    def _login_with_schulportal_hessen_credentials(self, page: Any) -> None:
        if self.sph_login_method == "http":
            try:
                from sph_login import Credentials, InteractionRequired, SphSession
            except ImportError:
                raise RuntimeError(
                    "Die Schulportal-Anmeldung benoetigt das optionale Paket sph-login "
                    "(pip install -e src/sph_login oder pip install '.[schulportal]'). "
                    "Alternativ COURSE_SYNC_SPH_LOGIN_METHOD=browser verwenden."
                ) from None

            login_url = self._schulportal_hessen_login_url()
            school_id = parse_qs(urlparse(login_url).query).get("i", [""])[0]
            if not school_id:
                school_id = parse_qs(urlparse(self._current_page_url(page)).query).get("i", [""])[0]
            if not school_id:
                raise RuntimeError("Schul-ID fehlt fuer SPH-Login; COURSE_SYNC_SPH_LOGIN_METHOD=browser verwenden.")
            account_key = hashlib.sha256(f"{school_id}:{self.username}".encode()).hexdigest()
            state_root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "sph-login"
            print("Melde ueber sph-login am Schulportal an.", flush=True)
            with SphSession(Credentials(school_id, self.username or "", self.password or ""),
                            timeout=self.timeout_ms / 1000,
                            state_path=state_root / f"{account_key}.json") as session:
                for force in (False, True):
                    try:
                        if force:
                            session.login(force=True)
                        else:
                            session.login()
                        session.install_in_browser(page.context)
                        # The target verifies authentication; LANiS is not required.
                        self._goto_login_resilient(page, self.course_url)
                        if not self._login_is_required(page):
                            return
                    except InteractionRequired as error:
                        if self.headless:
                            raise
                        session.install_in_browser(page.context)
                        self._wait_for_sph_browser_login(page, error.continuation_url)
                        return
                if self.headless:
                    raise InteractionRequired("Moodle-SSO verlangt eine interaktive Anmeldung.")
                self._wait_for_sph_browser_login(page)
                return

        print("Melde ueber Schulportal Hessen SSO an.", flush=True)
        schulportal_login_url = self._schulportal_hessen_login_url()
        if schulportal_login_url and not self._current_schulportal_login_url_has_instance(page):
            self._goto_login_resilient(page, schulportal_login_url)

        self._choose_schulportal_hessen_school_context_if_available(page)
        if self._looks_logged_in(page) and not self._login_is_required(page):
            return
        current_host = urlparse(self._current_page_url(page)).netloc.lower()
        course_host = urlparse(self.course_url).netloc.lower()
        if current_host == course_host and not self._login_is_required(page):
            return

        username_input = self._first_visible_enabled_locator(
            page,
            [
                'input[name="username"]',
                'input[name="user"]',
                'input[name="login"]',
                'input[name="email"]',
                'input[name="kennung"]',
                'input[id*="username" i]',
                'input[id*="login" i]',
                'input[id*="email" i]',
                'input[type="email"]',
                'input[type="text"]',
            ],
        )
        if username_input is None:
            raise RuntimeError(
                "Schulportal-Hessen-Loginfeld wurde nicht gefunden. "
                f"Aktuelle URL: {self._current_page_url(page) or 'unbekannt'}"
            )
        username_input.fill(self.username or "")

        password_input = self._first_visible_enabled_locator(page, ['input[name="password"]', 'input[type="password"]'])
        if password_input is None:
            self._click_first_by_text(page, ["Weiter", "Next", "Fortfahren"])
            page.wait_for_load_state("domcontentloaded")
            password_input = self._first_visible_enabled_locator(page, ['input[name="password"]', 'input[type="password"]'])
        if password_input is None:
            raise RuntimeError(
                "Schulportal-Hessen-Passwortfeld wurde nicht gefunden. "
                f"Aktuelle URL: {self._current_page_url(page) or 'unbekannt'}"
            )
        password_input.fill(self.password or "")

        submit = self._first_existing_locator(
            page,
            [
                'button[type="submit"]',
                'input[type="submit"]',
                'button[name="submit"]',
                'button[id*="login" i]',
            ],
        )
        if submit is not None:
            submit.click()
        else:
            self._click_first_by_text(page, ["Anmelden", "Einloggen", "Login", "Log in", "Weiter"])
        page.wait_for_load_state("domcontentloaded")
        self._continue_schulportal_hessen_login(page)

    def _wait_for_sph_browser_login(self, page: Any, continuation_url: str | None = None) -> None:
        """Let the user finish a pending step without restarting credential login."""
        if continuation_url:
            self._goto_login_resilient(page, continuation_url)
        print("Bitte die SPH-Anmeldung im Browser abschliessen (z. B. zweiten Faktor).", flush=True)
        deadline = time.monotonic() + 300
        course_host = urlparse(self.course_url).netloc.lower()
        while time.monotonic() < deadline:
            current_host = urlparse(self._current_page_url(page)).netloc.lower()
            if current_host == course_host and not self._login_is_required(page):
                return
            if current_host != "login.schulportal.hessen.de" and self._looks_logged_in(page):
                self._goto_login_resilient(page, self.course_url)
                if not self._login_is_required(page):
                    return
            page.wait_for_timeout(500)
        raise RuntimeError("Interaktive SPH-Anmeldung wurde nicht innerhalb von 5 Minuten abgeschlossen.")

    def _choose_schulportal_hessen_school_context_if_available(self, page: Any) -> None:
        school_login_button = page.locator('#typeselect button[data-nr="0"], button[data-nr="0"]')
        for index in range(school_login_button.count()):
            candidate = school_login_button.nth(index)
            try:
                if not candidate.is_visible() or not candidate.is_enabled():
                    continue
                candidate.click(timeout=5_000)
                page.wait_for_load_state("domcontentloaded")
                return
            except Exception:
                continue

        labels = [
            "Login mit Schulbezug",
            "Anmeldung mit Schulbezug",
            "mit Schulbezug",
            "Schulbezug",
        ]
        for label in labels:
            pattern = re.compile(label, re.IGNORECASE)
            for role in ["button", "link"]:
                try:
                    locator = page.get_by_role(role, name=pattern)
                    if locator.count() > 0:
                        locator.first.click(timeout=5_000)
                        page.wait_for_load_state("domcontentloaded")
                        return
                except Exception:
                    continue
            try:
                locator = page.get_by_text(pattern)
                if locator.count() > 0:
                    locator.first.click(timeout=5_000)
                    page.wait_for_load_state("domcontentloaded")
                    return
            except Exception:
                continue

    def _continue_schulportal_hessen_login(self, page: Any) -> None:
        for _ in range(3):
            if not self._schulportal_hessen_login_page_is_open(page):
                return
            try:
                self._click_first_by_text(page, ["Weiter", "Fortfahren", "Zustimmen", "Akzeptieren", "Erlauben"])
            except RuntimeError:
                return
            page.wait_for_load_state("domcontentloaded")

    def _first_existing_locator(self, page: Any, selectors: list[str]) -> Any | None:
        for selector in selectors:
            locator = page.locator(selector)
            if locator.count() > 0:
                return locator.first
        return None

    def _first_visible_enabled_locator(self, page: Any, selectors: list[str]) -> Any | None:
        for selector in selectors:
            locator = page.locator(selector)
            for index in range(locator.count()):
                candidate = locator.nth(index)
                try:
                    if not candidate.is_visible() or not candidate.is_enabled():
                        continue
                except Exception:
                    continue
                return candidate
        return None

    def _return_to_course_after_login(self, page: Any) -> None:
        if page.url == self.course_url and self._looks_logged_in(page):
            return
        self._goto_login_resilient(page, self.course_url)
        if self.username and self.password and self._login_is_required(page):
            raise RuntimeError(
                "Moodle verlangt nach dem Login erneut Zugangsdaten auf der Kursseite. "
                f"Aktuelle URL: {self._current_page_url(page) or 'unbekannt'}"
            )
        if self.headless and not self.username and not self.password and self._login_is_required(page):
            raise RuntimeError(
                "Moodle verlangt Login nach dem Wechsel auf die Kursseite "
                "(wahrscheinlich abgelaufener SSO-Storage-State). "
                "Bitte den Storage-State im headed Browser neu erzeugen und den Upload erneut starten. "
                f"Aktuelle URL: {self._current_page_url(page) or 'unbekannt'}"
            )

    def _looks_logged_in(self, page: Any) -> bool:
        if self._guest_or_enrol_page_is_open(page):
            return False
        if page.locator('input[name="username"]').count() > 0:
            return False
        if page.locator(".logininfo a[href*='login/index.php'], a[href*='login/index.php']").count() > 0:
            return False
        return page.locator(
            ".usermenu, [data-region='usermenu'], a[href*='login/logout.php'], "
            ".logininfo a[href*='login/logout.php']"
        ).count() > 0

    def _login_is_required(self, page: Any) -> bool:
        return (
            page.locator('input[name="username"]').count() > 0
            or self._external_login_page_is_open(page)
            or self._guest_or_enrol_page_is_open(page)
        )

    def _guest_or_enrol_page_is_open(self, page: Any) -> bool:
        current_url = self._current_page_url(page)
        if "/enrol/index.php" in current_url:
            return True
        login_info = page.locator(".logininfo, .usermenu, [data-region='usermenu']")
        for index in range(login_info.count()):
            try:
                text = login_info.nth(index).inner_text(timeout=500).lower()
            except Exception:
                continue
            if "gast" in text or "guest" in text:
                return True
        return False

    def _external_login_page_is_open(self, page: Any) -> bool:
        current_url = self._current_page_url(page)
        if not current_url:
            return False
        current = urlparse(current_url)
        course = urlparse(self.course_url)
        if not current.netloc or current.netloc == course.netloc:
            return False
        auth_markers = ("login", "saml", "sso", "singleSignOn", "oauth", "openid", "idp", "auth")
        haystack = f"{current.netloc}{current.path}".lower()
        return any(marker.lower() in haystack for marker in auth_markers)

    def _schulportal_hessen_login_page_is_open(self, page: Any) -> bool:
        current_url = self._current_page_url(page)
        if not current_url:
            return False
        host = urlparse(current_url).netloc.lower()
        return host == "login.schulportal.hessen.de"

    def _current_schulportal_login_url_has_instance(self, page: Any) -> bool:
        current_url = self._current_page_url(page)
        if not current_url:
            return False
        parsed = urlparse(current_url)
        if parsed.netloc.lower() != "login.schulportal.hessen.de":
            return False
        return bool(parse_qs(parsed.query).get("i", [""])[0])

    def _schulportal_hessen_login_url(self) -> str:
        course_host = urlparse(self.course_url).netloc.lower()
        match = re.search(r"\bmo(\d+)\.", course_host)
        if not match:
            return ""
        return f"https://login.schulportal.hessen.de/?i={match.group(1)}"

    def _current_page_url(self, page: Any) -> str:
        try:
            return str(page.url)
        except Exception:
            return ""

    def _course_page_is_open(self, page: Any) -> bool:
        current_url = self._current_page_url(page)
        if not current_url:
            return False
        current = urlparse(current_url)
        course = urlparse(self.course_url)
        return current.netloc == course.netloc and current.path == course.path

    def _wait_for_manual_login_confirmation(self, page: Any) -> None:
        if self.username and self.password:
            return
        if self.headless:
            return
        if os.environ.get("COURSE_SYNC_AUTO_CONFIRM_LOGIN", "").strip():
            page.goto(self.course_url, wait_until="domcontentloaded")
            return

        input(
            "Bitte im Browser anmelden. Wenn du wieder auf der Moodle-Kursseite bist, "
            "druecke hier Enter, dann startet der Upload: "
        )
        page.goto(self.course_url, wait_until="domcontentloaded")

    def _turn_editing_on(self, page: Any) -> None:
        if self._course_is_in_edit_mode(page):
            return

        if self.headless and not self.username and not self.password and self._login_is_required(page):
            raise RuntimeError(
                "Konnte den Moodle-Bearbeitungsmodus nicht einschalten, weil die Seite im Login steht "
                "(wahrscheinlich abgelaufener SSO-Storage-State). "
                "Bitte den Storage-State im headed Browser neu erzeugen und den Upload erneut starten. "
                f"Aktuelle URL: {self._current_page_url(page) or 'unbekannt'}"
            )

        if self._click_editing_switch(page):
            return

        for label in self._editing_toggle_labels():
            switch = page.get_by_role("switch", name=re.compile(label, re.IGNORECASE))
            if switch.count() > 0:
                switch.first.click()
                page.wait_for_load_state("domcontentloaded")
                if self._course_is_in_edit_mode(page):
                    return
            locator = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
            if locator.count() > 0:
                locator.first.click()
                page.wait_for_load_state("domcontentloaded")
                if self._course_is_in_edit_mode(page):
                    return
            link = page.get_by_role("link", name=re.compile(label, re.IGNORECASE))
            if link.count() > 0:
                link.first.click()
                page.wait_for_load_state("domcontentloaded")
                if self._course_is_in_edit_mode(page):
                    return

        if self._turn_editing_on_by_url(page):
            return

        if not self.headless:
            print(
                "Der Bearbeitungsmodus-Schalter wurde nicht automatisch erkannt. "
                "Bitte im Browser den Bearbeitungsmodus einschalten und danach hier Enter druecken.",
                flush=True,
            )
            input("Enter druecken, sobald der Bearbeitungsmodus aktiv ist: ")
            page.goto(self.course_url, wait_until="domcontentloaded")
            if self._course_is_in_edit_mode(page):
                return

        current_url = self._current_page_url(page)
        if self.headless and not self.username and not self.password and self._login_is_required(page):
            raise RuntimeError(
                "Konnte den Moodle-Bearbeitungsmodus nicht einschalten, weil die Seite im Login steht "
                "(wahrscheinlich abgelaufener SSO-Storage-State). "
                "Bitte den Storage-State im headed Browser neu erzeugen und den Upload erneut starten. "
                f"Aktuelle URL: {current_url or 'unbekannt'}"
            )

        raise RuntimeError(
            "Konnte den Moodle-Bearbeitungsmodus nicht einschalten. "
            f"Aktuelle URL: {current_url or 'unbekannt'}\n"
            "Hinweis: Stellen Sie sicher, dass der Playwright-Nutzer (fuer Browser-Uploads) "
            "UND der Webservice-Nutzer (fuer API-Zugriffe) Zugriff auf den Kurs haben. "
            "Es reicht nicht, nur einen der beiden einzuschreiben."
        )

    def _click_editing_switch(self, page: Any) -> bool:
        selectors = [
            '.editmode-switch-form input[type="checkbox"]',
            'input[name="setmode"]',
            '[data-action="toggle-editing"]',
            'a[href*="setmode=1"]',
            'a[href*="edit=on"]',
        ]
        for selector in selectors:
            locator = page.locator(selector)
            if locator.count() == 0:
                continue
            first = locator.first
            try:
                if selector.startswith("input") or "input" in selector:
                    if first.is_checked():
                        return self._course_is_in_edit_mode(page)
                first.click()
                page.wait_for_load_state("domcontentloaded")
            except Exception:
                continue
            if self._course_is_in_edit_mode(page):
                return True
        return False

    def _turn_editing_on_by_url(self, page: Any) -> bool:
        sesskey = self._moodle_sesskey(page)
        url_variants: list[dict[str, str]] = []
        if sesskey:
            url_variants.extend(
                [
                    {"sesskey": sesskey, "edit": "on"},
                    {"sesskey": sesskey, "setmode": "1"},
                ]
            )
        # Some Moodle setups accept edit toggles without an exposed sesskey.
        url_variants.extend(
            [
                {"edit": "on"},
                {"setmode": "1"},
            ]
        )

        for extra in url_variants:
            parsed = urlparse(self.course_url)
            query = parse_qs(parsed.query)
            for key, value in extra.items():
                query[key] = [value]
            target = parsed._replace(query=urlencode(query, doseq=True)).geturl()
            for _ in range(2):
                try:
                    page.goto(target, wait_until="domcontentloaded")
                except Exception:
                    page.wait_for_timeout(500)
                    continue
                if self._course_is_in_edit_mode(page):
                    return True
                break
        return False

    def _wait_for_editing_controls_after_manual_login(self, page: Any) -> None:
        if self.username and self.password:
            return
        if self.headless:
            return
        if self._course_is_in_edit_mode(page) or self._editing_toggle_is_visible(page):
            return

        print(
            "Bitte im Browser anmelden und zur Kursseite zurueckkehren. "
            "Das Tool wartet, bis der Bearbeitungsmodus verfuegbar ist."
            " Falls hier nichts weiter passiert, pruefe, ob du wirklich auf der Kursseite bist.",
            flush=True,
        )
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self._course_is_in_edit_mode(page) or self._editing_toggle_is_visible(page):
                return
            page.wait_for_timeout(1000)
        raise RuntimeError(
            "Nach 5 Minuten war kein Moodle-Bearbeitungsmodus sichtbar. "
            "Bitte pruefe, ob du eingeloggt bist und Bearbeitungsrechte fuer den Kurs hast."
        )

    def _editing_toggle_is_visible(self, page: Any) -> bool:
        if page.locator(
            '.editmode-switch-form input[type="checkbox"], input[name="setmode"], '
            '[data-action="toggle-editing"], a[href*="setmode=1"], a[href*="edit=on"]'
        ).count() > 0:
            return True
        for label in self._editing_toggle_labels():
            pattern = re.compile(label, re.IGNORECASE)
            if page.get_by_role("switch", name=pattern).count() > 0:
                return True
            if page.get_by_role("button", name=pattern).count() > 0:
                return True
            if page.get_by_role("link", name=pattern).count() > 0:
                return True
        return False

    def _editing_toggle_labels(self) -> list[str]:
        return [
            "Turn editing on",
            "Edit mode",
            "Bearbeiten einschalten",
            "Bearbeitungsmodus",
            "Bearbeiten",
        ]

    def _course_is_in_edit_mode(self, page: Any) -> bool:
        body_classes = page.locator("body").get_attribute("class") or ""
        if "editing" in body_classes:
            return True
        return page.locator(
            '[data-action="add-chooser-option"], [data-region="add-activity"], '
            '.editing_move, .activity-add, .section-modchooser'
        ).count() > 0

    def _find_or_create_section(self, page: Any, packages: list[MoodleH5PUploadPackage]) -> dict[str, str | int]:
        if hasattr(page, "goto"):
            page.goto(self.course_url, wait_until="domcontentloaded")
            self._turn_editing_on(page)
            if not self._course_is_in_edit_mode(page):
                raise RuntimeError("Bearbeitungsmodus ist nicht aktiv, obwohl die Section-Anlage gestartet wurde.")
        section = self._find_section(page)
        if section is not None:
            # If the target section exists by name, keep using it consistently.
            if self.section_title:
                return section
            if packages and not self._section_contains_packages(page, section, packages):
                package_section = self._find_section_containing_packages(page, packages)
                if package_section is not None:
                    print(
                        f"Moodle-Section '{self.section_title}' wurde gefunden, "
                        f"aber die H5Ps dieses Kapitels liegen in Section {package_section['number']}. "
                        "Verwende diese Section.",
                        flush=True,
                    )
                    if self.section_title:
                        package_section = self._ensure_section_title(page, package_section, self.section_title)
                    return package_section
            return section
        section = self._find_section_containing_packages(page, packages)
        if section is not None:
            print(
                f"Moodle-Section '{self.section_title}' wurde nicht gefunden, "
                f"aber Section {section['number']} enthaelt bereits H5Ps dieses Kapitels. Verwende diese Section.",
                flush=True,
            )
            if self.section_title:
                section = self._ensure_section_title(page, section, self.section_title)
            return section
        if not self.section_title:
            raise RuntimeError("Konnte Moodle-Section nicht finden.")

        print(f"Moodle-Section '{self.section_title}' existiert noch nicht. Lege sie am Kursende an.")
        section = self._create_section_at_end(page)
        rename_ok = False
        try:
            rename_ok = self._rename_section(page, int(section["number"]), self.section_title)
        except Exception as rename_error:
            self._write_debug_artifacts(page, f"section-rename-error-{section['number']}")
            print(
                f"Warnung: Section-Umbenennung hat eine Ausnahme ausgeloest: {rename_error}",
                flush=True,
            )
        if not rename_ok:
            raise RuntimeError(
                f"Die neue Moodle-Section {section['number']} wurde angelegt, konnte aber nicht in "
                f"'{self.section_title}' umbenannt werden."
            )
        section = None
        for attempt in range(3):
            page.goto(self.course_url, wait_until="domcontentloaded")
            # format_tiles renders section/tile titles dynamically after the initial DOM load
            # (see _find_text_label_activity_id_via_section_page), so a freshly renamed section's
            # tile may still show its old/default title right at domcontentloaded; give it a
            # moment before searching by the new title.
            page.wait_for_timeout(800)
            self._turn_editing_on(page)
            section = self._find_section(page)
            if section is not None:
                break
        if section is None:
            try:
                print(f"Aktuell sichtbare Section-Titel: {self._debug_all_section_titles(page)}", flush=True)
            except Exception as debug_error:
                print(f"Section-Titel-Debug fehlgeschlagen: {debug_error}", flush=True)
            self._write_debug_artifacts(page, "section-not-found-after-create")
            raise RuntimeError(f"Moodle-Section '{self.section_title}' wurde angelegt, aber danach nicht gefunden.")
        return section

    def _debug_all_section_titles(self, page: Any) -> list[dict[str, object]]:
        return page.evaluate(
            """
            () => {
              const sectionSelector = 'li.section, li.course-section, section.course-section';
              const sections = [...document.querySelectorAll(sectionSelector)].filter((section) =>
                !section.parentElement?.closest(sectionSelector)
              );
              const fromSections = sections.map((section) => {
                const numberValue = section.getAttribute('data-number')
                  || section.getAttribute('data-section')
                  || (section.id.match(/section-(\\d+)/) || [])[1];
                const titleNode = section.querySelector('.sectionname, .section-title, h3, h4');
                return {
                  source: 'section',
                  number: numberValue || null,
                  title: (titleNode ? titleNode.textContent : section.textContent || '').trim().slice(0, 120),
                  sectionDbId: section.getAttribute('data-id') || section.getAttribute('data-sectionid') || '',
                };
              });
              const tileLinks = [...document.querySelectorAll('li.tile a.tile-link[aria-label]')];
              const fromTiles = tileLinks.map((link) => ({
                source: 'tile',
                number: link.getAttribute('data-section') || link.closest('li.tile')?.getAttribute('data-section') || null,
                title: (link.getAttribute('aria-label') || '').slice(0, 160),
              }));
              return [...fromSections, ...fromTiles];
            }
            """
        )

    def _section_contains_packages(
        self,
        page: Any,
        section: dict[str, str | int],
        packages: list[MoodleH5PUploadPackage],
    ) -> bool:
        activities = self._collect_section_h5p_activities(page, str(section["selector"]))
        wanted = {normalize_moodle_identifier(package.identifier) for package in packages}
        wanted.update(normalize_moodle_identifier(package.title) for package in packages)
        return any(identifier in activities for identifier in wanted if identifier)

    def _ensure_section_title(
        self,
        page: Any,
        section: dict[str, str | int],
        title: str,
    ) -> dict[str, str | int]:
        current_title = str(section.get("title") or "")
        if normalize_moodle_section_title(current_title) == normalize_moodle_section_title(title):
            return section

        section_number = int(section["number"])
        print(f"Benenne Moodle-Section {section_number} in '{title}' um.", flush=True)
        if not self._rename_section(page, section_number, title):
            raise RuntimeError(f"Moodle-Section {section_number} konnte nicht in '{title}' umbenannt werden.")

        page.goto(self.course_url, wait_until="domcontentloaded")
        self._turn_editing_on(page)
        renamed_section = self._section_by_number(page, section_number) or self._find_section(page)
        if renamed_section is None:
            raise RuntimeError(f"Moodle-Section {section_number} wurde umbenannt, aber danach nicht gefunden.")
        renamed_title = str(renamed_section.get("title") or "")
        if normalize_moodle_section_title(renamed_title) != normalize_moodle_section_title(title):
            raise RuntimeError(
                f"Moodle-Section {section_number} existiert nach dem Umbenennen weiter, "
                f"traegt aber nicht den erwarteten Titel '{title}' (gefunden: '{renamed_title}')."
            )
        return renamed_section

    def _find_section_containing_packages(
        self,
        page: Any,
        packages: list[MoodleH5PUploadPackage],
    ) -> dict[str, str | int] | None:
        wanted = {normalize_moodle_identifier(package.identifier) for package in packages}
        wanted.update(normalize_moodle_identifier(package.title) for package in packages)
        wanted = {item for item in wanted if item}
        if not wanted:
            return None

        return page.evaluate(
            """
            (wantedValues) => {
              const wanted = new Set(wantedValues);
                            const sectionSelector = 'li.section, li.course-section, section.course-section';
                            const topLevelSection = (section) => {
                                let current = section;
                                while (current?.parentElement) {
                                    const parent = current.parentElement.closest(sectionSelector);
                                    if (!parent) {
                                        break;
                                    }
                                    current = parent;
                                }
                                return current;
                            };
              const normalize = (value) => (value || '')
                .trim()
                .toLowerCase()
                .replace(/ä/g, 'ae')
                .replace(/ö/g, 'oe')
                .replace(/ü/g, 'ue')
                .replace(/ß/g, 'ss')
                .normalize('NFKD')
                .replace(/[\\u0300-\\u036f]/g, '')
                .replace(/[^a-z0-9]+/g, '-')
                .replace(/^-+|-+$/g, '')
                .replace(/-+/g, '-');
              const activityLabel = (link) => {
                const activity = link.closest('[data-activityname], li.activity, .activity');
                const card = activity?.querySelector('[data-activityname]') || activity;
                const editable = activity?.querySelector('[data-value]');
                if (card?.getAttribute('data-activityname')) return card.getAttribute('data-activityname');
                if (editable?.getAttribute('data-value')) return editable.getAttribute('data-value');
                const clone = link.cloneNode(true);
                clone.querySelectorAll('.accesshide, .sr-only').forEach((node) => node.remove());
                return clone.textContent || link.getAttribute('aria-label') || '';
              };
                const links = [...document.querySelectorAll('a[href*="/mod/h5pactivity/view.php"]')];
              for (const link of links) {
                if (!wanted.has(normalize(activityLabel(link)))) {
                  continue;
                }
                                const section = topLevelSection(link.closest(sectionSelector));
                if (!section) continue;
                const numberValue = section.getAttribute('data-number')
                  || section.getAttribute('data-section')
                  || (section.id.match(/section-(\\d+)/) || [])[1]
                  || section.querySelector('[data-sectionnum]')?.getAttribute('data-sectionnum');
                const number = Number.parseInt(numberValue || '', 10);
                if (Number.isNaN(number)) continue;
                const marker = `course-sync-section-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                section.setAttribute('data-course-sync-section', marker);
                const title = section.getAttribute('data-sectionname') || section.querySelector('.sectionname')?.textContent || '';
                const sectionDbId = section.getAttribute('data-id') || section.getAttribute('data-sectionid') || '';
                return { selector: `[data-course-sync-section="${marker}"]`, number, title, sectionDbId };
              }
              return null;
            }
            """,
            sorted(wanted),
        )

    def _find_section(self, page: Any) -> dict[str, str | int] | None:
        section_payload = page.evaluate(
            """
            (sectionTitle) => {
                            const sectionSelector = 'li.section, li.course-section, section.course-section';
              const normalize = (value) => (value || '')
                .trim()
                .toLowerCase()
                .replace(/ä/g, 'ae')
                .replace(/ö/g, 'oe')
                .replace(/ü/g, 'ue')
                .replace(/ß/g, 'ss')
                .normalize('NFKD')
                .replace(/[\\u0300-\\u036f]/g, '')
                .replace(/\\b(?:und|and)\\b/g, ' ')
                .replace(/[^a-z0-9]+/g, ' ')
                .replace(/\\s+/g, ' ')
                .trim();
              const wanted = normalize(sectionTitle);
                            const sections = [...document.querySelectorAll(sectionSelector)].filter((section) =>
                                !section.parentElement?.closest(sectionSelector)
                            );
              for (const section of sections) {
                                if (section.classList.contains('delegated-section') || section.classList.contains('subsection')) {
                  continue;
                }
                const titleNode = section.querySelector('.sectionname, .section-title, h3, h4');
                const title = normalize(titleNode ? titleNode.textContent : section.textContent);
                if (wanted && title !== wanted) {
                  continue;
                }
                const numberValue = section.getAttribute('data-number')
                  || section.getAttribute('data-section')
                  || (section.id.match(/section-(\\d+)/) || [])[1]
                  || section.querySelector('[data-sectionnum]')?.getAttribute('data-sectionnum');
                const number = Number.parseInt(numberValue || '', 10);
                if (!Number.isNaN(number)) {
                  const marker = `course-sync-section-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                  section.setAttribute('data-course-sync-section', marker);
                  const sectionDbId = section.getAttribute('data-id') || section.getAttribute('data-sectionid') || '';
                  return { selector: `[data-course-sync-section="${marker}"]`, number, title, sectionDbId };
                }
              }
              if (!wanted) {
                return null;
              }
              // Some course formats (e.g. format_tiles/"Kachelformat") render section titles and
              // progress only on a separate tile launcher element, leaving the matching li.section
              // itself untitled and empty until its own tile is opened. Fall back to reading the
              // title from the tile link's aria-label ("<title>, oeffnet Details in Popup") and
              // resolve the corresponding (still empty) section via the shared data-section number.
              const tileLinks = [...document.querySelectorAll('li.tile a.tile-link[aria-label]')];
              for (const link of tileLinks) {
                const label = link.getAttribute('aria-label') || '';
                // Splitting on the first comma breaks for section titles that contain a comma
                // themselves (e.g. "Beziehungen, Kapselung und miniworlds"); strip only the
                // known trailing popup-hint suffix instead.
                const title = normalize(
                  label.replace(/,\s*(?:oeffnet|öffnet)\s+details\s+in\s+popup\s*$/i, '')
                );
                if (!title || title !== wanted) {
                  continue;
                }
                const numberValue = link.getAttribute('data-section')
                  || link.closest('li.tile')?.getAttribute('data-section');
                const number = Number.parseInt(numberValue || '', 10);
                if (Number.isNaN(number)) {
                  continue;
                }
                const section = sections.find((candidate) => {
                  const candidateNumber = candidate.getAttribute('data-number')
                    || candidate.getAttribute('data-section')
                    || (candidate.id.match(/section-(\\d+)/) || [])[1];
                  return Number.parseInt(candidateNumber || '', 10) === number;
                });
                if (!section) {
                  continue;
                }
                const marker = `course-sync-section-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                section.setAttribute('data-course-sync-section', marker);
                const sectionDbId = section.getAttribute('data-id')
                  || section.getAttribute('data-sectionid')
                  || link.closest('li.tile')?.getAttribute('data-true-sectionid')
                  || '';
                return { selector: `[data-course-sync-section="${marker}"]`, number, title, sectionDbId };
              }
              return null;
            }
            """,
            self.section_title,
        )
        return section_payload

    def _create_section_at_end(self, page: Any) -> dict[str, str | int]:
        before = self._last_section_number(page)
        if self._create_section_by_url(page, before):
            section = self._last_section(page)
            if section is not None and int(section["number"]) > before:
                return section

        if self._create_section_by_ui(page, before):
            section = self._last_section(page)
            if section is not None and int(section["number"]) > before:
                return section

        self._write_debug_artifacts(page, "create-section-at-end-error")
        raise RuntimeError(
            "Moodle konnte keine neue Section am Kursende anlegen "
            f"(letzte erkannte Section-Nummer vor dem Versuch: {before}). "
            "Der Upload wird abgebrochen, damit keine Inhalte in einer falschen Section landen."
        )

    def _create_section_by_url(self, page: Any, before: int) -> bool:
        if not self._course_is_in_edit_mode(page):
            page.goto(self.course_url, wait_until="domcontentloaded")
            self._turn_editing_on(page)
        if not self._course_is_in_edit_mode(page):
            raise RuntimeError("Bearbeitungsmodus ist nicht aktiv. Moodle-Section kann nicht angelegt werden.")

        sesskey = self._moodle_sesskey(page)
        if not sesskey:
            return False

        print("Versuche Moodle-Section ueber changenumsections.php anzulegen.", flush=True)
        target_urls: list[str] = []
        add_section_link = self._add_section_href(page)
        if add_section_link:
            target_urls.append(add_section_link)
        target_urls.append(
            urljoin(self.course_url, "/course/changenumsections.php")
            + "?"
            + urlencode(
                {
                    "courseid": str(self._course_id()),
                    "insertsection": "0",
                    "sesskey": sesskey,
                }
            )
        )

        for target_url in target_urls:
            page.goto(target_url, wait_until="domcontentloaded")
            page.goto(self.course_url, wait_until="domcontentloaded")
            self._turn_editing_on(page)
            if self._last_section_number(page) > before:
                return True

        page.goto(self.course_url, wait_until="domcontentloaded")
        self._turn_editing_on(page)
        return self._last_section_number(page) > before

    def _add_section_href(self, page: Any) -> str:
        selectors = [
            'a[data-action="addSection"][href*="/course/changenumsections.php"]',
            'a.add-section[href*="/course/changenumsections.php"]',
            'a[data-add-sections][href*="/course/changenumsections.php"]',
        ]
        for selector in selectors:
            locator = page.locator(selector)
            count = locator.count()
            if count == 0:
                continue
            if hasattr(locator, "nth"):
                candidates = [locator.nth(index) for index in range(count)]
            else:
                first = getattr(locator, "first", None)
                candidates = [first] if first is not None else []
            for candidate in candidates:
                href = candidate.get_attribute("href")
                if not href:
                    continue
                absolute_href = urljoin(self.course_url, href)
                if self._is_top_level_add_section_href(absolute_href):
                    return absolute_href
        return ""

    def _is_top_level_add_section_href(self, href: str) -> bool:
        parsed = urlparse(urljoin(self.course_url, href))
        insert_sections = parse_qs(parsed.query).get("insertsection", [])
        return any(value == "0" for value in insert_sections)

    def _create_section_by_ui(self, page: Any, before: int) -> bool:
        print("Versuche Moodle-Section ueber die Kursoberflaeche anzulegen.", flush=True)
        page.goto(self.course_url, wait_until="domcontentloaded")
        self._turn_editing_on(page)
        if not self._course_is_in_edit_mode(page):
            raise RuntimeError("Bearbeitungsmodus ist nicht aktiv. Moodle-Section kann nicht ueber die UI angelegt werden.")

        selectors = [
            'a[href*="changenumsections.php"][href*="insertsection=0"]',
            '[data-action="addSection"]',
            '[data-action="add-section"]',
            '[data-add-sections]',
            '.add-sections button',
            '.add-sections a',
            'button[name="addsection"]',
            'a[href*="changenumsections.php"][href*="insertsection="]',
        ]
        for selector in selectors:
            locator = page.locator(selector)
            if locator.count() > 0 and self._click_add_section_control(page, locator.first, before):
                return True

        labels = [
            "Add section",
            "Add sections",
            "Add topic",
            "Add week",
            "Abschnitt hinzufügen",
            "Abschnitte hinzufügen",
            "Thema hinzufügen",
            "Woche hinzufügen",
        ]
        for label in labels:
            pattern = re.compile(label, re.IGNORECASE)
            for role in ["button", "link"]:
                locator = page.get_by_role(role, name=pattern)
                if locator.count() > 0 and self._click_add_section_control(page, locator.first, before):
                    return True
            text = page.get_by_text(pattern)
            if text.count() > 0 and self._click_add_section_control(page, text.first, before):
                return True

        return False

    def _click_add_section_control(self, page: Any, locator: Any, before: int) -> bool:
        try:
            href = locator.get_attribute("href") if hasattr(locator, "get_attribute") else None
            if href and "changenumsections.php" in href:
                absolute_href = urljoin(self.course_url, href)
                if not self._is_top_level_add_section_href(absolute_href):
                    return False
                page.goto(absolute_href, wait_until="domcontentloaded")
            else:
                locator.click()
                page.wait_for_timeout(750)
                self._confirm_add_section_dialog_if_needed(page)
                page.wait_for_load_state("domcontentloaded")
        except Exception:
            return False

        page.goto(self.course_url, wait_until="domcontentloaded")
        self._turn_editing_on(page)
        return self._last_section_number(page) > before

    def _confirm_add_section_dialog_if_needed(self, page: Any) -> None:
        number_input = page.locator(
            '.modal-dialog input[type="number"], .modal-dialog input[name*="num"], '
            '.modal-dialog input[name*="section"]'
        )
        if number_input.count() > 0:
            number_input.first.fill("1")

        for label in [
            "Add sections",
            "Add section",
            "Create",
            "Save changes",
            "Abschnitte hinzufügen",
            "Abschnitt hinzufügen",
            "Erstellen",
            "Änderungen speichern",
            "Aenderungen speichern",
        ]:
            button = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
            if button.count() > 0:
                button.first.click()
                page.wait_for_timeout(750)
                return

    def _last_section_number(self, page: Any) -> int:
        section = self._last_section(page)
        return int(section["number"]) if section is not None else 0

    def _last_section(self, page: Any) -> dict[str, str | int] | None:
        return page.evaluate(
            """
            () => {
                            const sectionSelector = 'li.section, li.course-section, section.course-section';
                            const sections = [...document.querySelectorAll(sectionSelector)].filter((section) =>
                                !section.parentElement?.closest(sectionSelector)
                            );
              let best = null;
              for (const section of sections) {
                                if (section.classList.contains('delegated-section') || section.classList.contains('subsection')) continue;
                const numberValue = section.getAttribute('data-number')
                  || section.getAttribute('data-section')
                  || section.getAttribute('data-sectionid')
                  || (section.id.match(/section-(\\d+)/) || [])[1]
                  || section.querySelector('[data-sectionnum]')?.getAttribute('data-sectionnum');
                const number = Number.parseInt(numberValue || '', 10);
                if (Number.isNaN(number)) continue;
                if (!best || number > best.number) {
                  const marker = `course-sync-section-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                  section.setAttribute('data-course-sync-section', marker);
                                    const title = (section.getAttribute('data-sectionname') || section.querySelector('.sectionname, .section-title, h3, h4')?.textContent || '').trim();
                  const sectionDbId = section.getAttribute('data-id') || section.getAttribute('data-sectionid') || '';
                                    best = { selector: `[data-course-sync-section="${marker}"]`, number, title, sectionDbId };
                }
              }
              return best;
            }
            """
        )

    def _rename_section(self, page: Any, section_number: int, title: str) -> bool:
        try:
            if self._rename_section_from_course_page(page, section_number, title):
                return True
        except Exception as err:
            print(f"Warnung: _rename_section_from_course_page hat Ausnahme ausgeloest: {err}", flush=True)
            self._write_debug_artifacts(page, f"editsection-{section_number}-from-course-page-error")

        params = {
            "courseid": str(self._course_id()),
            "section": str(section_number),
        }
        page.goto(urljoin(self.course_url, "/course/editsection.php") + "?" + urlencode(params), wait_until="domcontentloaded")
        self._write_debug_artifacts(page, f"editsection-{section_number}-form")

        default_name_checkbox = page.locator('input[name="usedefaultname"], #id_usedefaultname')
        if default_name_checkbox.count() > 0 and default_name_checkbox.first.is_checked():
            default_name_checkbox.first.uncheck()

        name_input = page.locator('input[name="name"], #id_name')
        if name_input.count() == 0:
            return False
        name_input.first.fill(title)

        try:
            self._click_first_by_text(
                page,
                [
                    "Save changes",
                    "Save and return",
                    "Änderungen speichern",
                    "Aenderungen speichern",
                    "Speichern",
                ],
            )
        except RuntimeError:
            self._write_debug_artifacts(page, f"editsection-{section_number}-no-save-button")
            name_input.first.press("Enter")
        page.wait_for_load_state("domcontentloaded")
        return True

    def _rename_section_from_course_page(self, page: Any, section_number: int, title: str) -> bool:
        page.goto(self.course_url, wait_until="domcontentloaded")
        self._turn_editing_on(page)
        section = self._section_by_number(page, section_number)
        if section is None:
            return False

        edit_href = page.locator(section["selector"]).evaluate(
            """
            (section) => {
              const links = [...section.querySelectorAll('a[href]')];
              const byHref = links.find((link) =>
                /\\/course\\/editsection\\.php/i.test(link.href || '')
                && !/[?&]delete=1(?:&|$)/i.test(link.href || '')
              );
              if (byHref) return byHref.href;
              const byLabel = links.find((link) =>
                /Einstellungen bearbeiten|Edit settings/i.test(link.textContent || link.getAttribute('aria-label') || '')
              );
              return byLabel ? byLabel.href : '';
            }
            """
        )

        if not edit_href:
            section_db_id = str(section.get("sectionDbId", "")).strip()
            if not section_db_id:
                print(f"Warnung: Kein Edit-Link und keine sectionDbId fuer Section {section_number}. section={section}", flush=True)
                return False
            edit_href = urljoin(self.course_url, "/course/editsection.php") + "?id=" + section_db_id

        print(f"Oeffne Abschnitts-Formular: {edit_href}", flush=True)
        page.goto(str(edit_href), wait_until="domcontentloaded")
        self._write_debug_artifacts(page, f"editsection-{section_number}-form-from-course-page")
        default_name_checkbox = page.locator('input[name="usedefaultname"], #id_usedefaultname')
        if default_name_checkbox.count() > 0 and default_name_checkbox.first.is_checked():
            default_name_checkbox.first.uncheck()

        name_input = page.locator('input[name="name"], #id_name')
        if name_input.count() == 0:
            return False
        name_input.first.fill(title)
        self._click_first_by_text(
            page,
            [
                "Save changes",
                "Save and return",
                "Änderungen speichern",
                "Aenderungen speichern",
                "Speichern",
            ],
        )
        page.wait_for_load_state("domcontentloaded")
        return True

    def _section_by_number(self, page: Any, section_number: int) -> dict[str, str | int] | None:
        return page.evaluate(
            """
            (wantedNumber) => {
                            const sectionSelector = 'li.section, li.course-section, section.course-section';
                            const sections = [...document.querySelectorAll(sectionSelector)].filter((section) =>
                                !section.parentElement?.closest(sectionSelector)
                            );
              for (const section of sections) {
                                if (section.classList.contains('delegated-section') || section.classList.contains('subsection')) continue;
                const numberValue = section.getAttribute('data-number')
                  || section.getAttribute('data-section')
                  || section.getAttribute('data-sectionid')
                  || (section.id.match(/section-(\\d+)/) || [])[1]
                  || section.querySelector('[data-sectionnum]')?.getAttribute('data-sectionnum');
                const number = Number.parseInt(numberValue || '', 10);
                if (number !== wantedNumber) continue;
                const marker = `course-sync-section-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                section.setAttribute('data-course-sync-section', marker);
                                const title = (section.getAttribute('data-sectionname') || section.querySelector('.sectionname, .section-title, h3, h4')?.textContent || '').trim();
                const sectionDbId = section.getAttribute('data-id') || section.getAttribute('data-sectionid') || '';
                                return { selector: `[data-course-sync-section="${marker}"]`, number, title, sectionDbId };
              }
              return null;
            }
            """,
            section_number,
        )

    def _moodle_sesskey(self, page: Any) -> str:
        sesskey = page.evaluate(
            """
            () => {
              if (window.M && window.M.cfg && window.M.cfg.sesskey) {
                return window.M.cfg.sesskey;
              }
              const input = document.querySelector('input[name="sesskey"]');
              if (input && input.value) {
                return input.value;
              }
              const match = document.documentElement.innerHTML.match(/sesskey=([^"'&<>]+)/);
              return match ? decodeURIComponent(match[1]) : '';
            }
            """
        )
        return str(sesskey or "")

    def _collect_section_h5p_activities(self, page: Any, section_selector: str) -> dict[str, int]:
        payload = page.locator(section_selector).evaluate(
            """
            (section) => {
              const activities = {};
              const normalize = (value) => (value || '')
                .trim()
                .toLowerCase()
                .replace(/ä/g, 'ae')
                .replace(/ö/g, 'oe')
                .replace(/ü/g, 'ue')
                .replace(/ß/g, 'ss')
                .normalize('NFKD')
                .replace(/[\\u0300-\\u036f]/g, '')
                .replace(/[^a-z0-9]+/g, '-')
                .replace(/^-+|-+$/g, '')
                .replace(/-+/g, '-');
              const activityLabel = (link) => {
                const activity = link.closest('[data-activityname], li.activity, .activity');
                const card = activity?.querySelector('[data-activityname]') || activity;
                const editable = activity?.querySelector('[data-value]');
                if (card?.getAttribute('data-activityname')) return card.getAttribute('data-activityname');
                if (editable?.getAttribute('data-value')) return editable.getAttribute('data-value');
                const clone = link.cloneNode(true);
                clone.querySelectorAll('.accesshide, .sr-only').forEach((node) => node.remove());
                return clone.textContent || link.getAttribute('aria-label') || '';
              };
              const links = [...section.querySelectorAll('a[href*="/mod/h5pactivity/view.php"]')];
              for (const link of links) {
                const href = link.href || '';
                const cmid = new URL(href).searchParams.get('id');
                if (!cmid) continue;
                const label = activityLabel(link);
                activities[normalize(label)] = Number.parseInt(cmid, 10);
              }
              return activities;
            }
            """
        )
        return {str(key): int(value) for key, value in payload.items() if value}

    def _collect_section_h5p_activity_order(self, page: Any, section_selector: str) -> list[dict[str, Any]]:
        payload = page.locator(section_selector).evaluate(
            """
            (section) => {
              const normalize = (value) => (value || '')
                .trim()
                .toLowerCase()
                .replace(/ä/g, 'ae')
                .replace(/ö/g, 'oe')
                .replace(/ü/g, 'ue')
                .replace(/ß/g, 'ss')
                .normalize('NFKD')
                .replace(/[\\u0300-\\u036f]/g, '')
                .replace(/[^a-z0-9]+/g, '-')
                .replace(/^-+|-+$/g, '')
                .replace(/-+/g, '-');
              const activityLabel = (link) => {
                const activity = link.closest('[data-activityname], li.activity, .activity');
                const card = activity?.querySelector('[data-activityname]') || activity;
                const editable = activity?.querySelector('[data-value]');
                if (card?.getAttribute('data-activityname')) return card.getAttribute('data-activityname');
                if (editable?.getAttribute('data-value')) return editable.getAttribute('data-value');
                const clone = link.cloneNode(true);
                clone.querySelectorAll('.accesshide, .sr-only').forEach((node) => node.remove());
                return clone.textContent || link.getAttribute('aria-label') || '';
              };
              const seen = new Set();
              const activities = [];
              const links = [...section.querySelectorAll('a[href*="/mod/h5pactivity/view.php"]')];
              for (const link of links) {
                const href = link.href || '';
                const cmid = Number.parseInt(new URL(href).searchParams.get('id') || '', 10);
                if (!cmid || seen.has(cmid)) continue;
                seen.add(cmid);
                const label = activityLabel(link);
                activities.push({ id: cmid, title: label.trim(), identifier: normalize(label) });
              }
              return activities;
            }
            """
        )
        return [
            {"id": int(item["id"]), "title": str(item.get("title") or ""), "identifier": str(item.get("identifier") or "")}
            for item in payload
            if item.get("id")
        ]

    def _resolve_desired_activity_order(
        self,
        packages: list[MoodleH5PUploadPackage],
        desired_keys: list[tuple[str, str]],
        activities: list[dict[str, int | str]],
    ) -> list[int]:
        id_by_key: dict[str, int] = {}
        for activity in activities:
            identifier = str(activity["identifier"])
            if identifier and identifier not in id_by_key:
                id_by_key[identifier] = int(activity["id"])
        available_ids = {int(activity["id"]) for activity in activities}

        desired_ids: list[int] = []
        for package, (identifier_key, title_key) in zip(packages, desired_keys, strict=True):
            activity_id = (
                id_by_key.get(identifier_key)
                or id_by_key.get(title_key)
                or self.existing_activity_ids.get(package.identifier)
                or self.existing_activity_ids.get(identifier_key)
                or self.existing_activity_ids.get(title_key)
            )
            if activity_id is not None and int(activity_id) in available_ids:
                desired_ids.append(activity_id)
        return desired_ids

    def _sort_section_h5p_activities(
        self,
        page: Any,
        section_number: int,
        packages: list[MoodleH5PUploadPackage],
    ) -> None:
        desired_keys = [
            (normalize_moodle_identifier(package.identifier), normalize_moodle_identifier(package.title))
            for package in packages
        ]
        if len(desired_keys) < 2:
            return

        print("Pruefe Reihenfolge der H5P-Aktivitaeten in der Moodle-Section.", flush=True)
        section = self._section_by_number(page, section_number)
        if section is None:
            return

        activities = self._collect_section_h5p_activity_order(page, str(section["selector"]))
        desired_ids = self._resolve_desired_activity_order(packages, desired_keys, activities)

        use_section_page = False
        if len(desired_ids) < 2:
            # format_tiles (and similar formats) don't render section content on the main
            # course page, so the scrape above can come up empty there. Retry on the
            # section's own page, where the content is always populated.
            populated_section = self._goto_populated_section_page(page, section, section_number)
            if populated_section is not None:
                section = populated_section
                activities = self._collect_section_h5p_activity_order(page, str(section["selector"]))
                desired_ids = self._resolve_desired_activity_order(packages, desired_keys, activities)
                use_section_page = True

        if len(desired_ids) < 2:
            return

        current_desired_ids = [int(activity["id"]) for activity in activities if int(activity["id"]) in set(desired_ids)]
        if current_desired_ids == desired_ids:
            print("H5P-Reihenfolge stimmt bereits.", flush=True)
            return

        print("Sortiere H5P-Aktivitaeten nach Kapitelreihenfolge.", flush=True)
        for index in range(len(desired_ids) - 2, -1, -1):
            self._move_activity_before(page, desired_ids[index], desired_ids[index + 1])
        for attempt in range(3):
            if use_section_page:
                section = self._goto_populated_section_page(page, section, section_number)
            else:
                page.goto(self.course_url, wait_until="domcontentloaded")
                self._turn_editing_on(page)
                section = self._section_by_number(page, section_number)
            if section is None:
                raise RuntimeError("Konnte Moodle-Section nach dem Sortieren nicht erneut finden.")
            activities = self._collect_section_h5p_activity_order(page, str(section["selector"]))
            current_desired_ids = [int(activity["id"]) for activity in activities if int(activity["id"]) in set(desired_ids)]
            if current_desired_ids == desired_ids:
                return

            if attempt < 2:
                page.wait_for_timeout(1500)
                for index in range(len(desired_ids) - 2, -1, -1):
                    self._move_activity_before(page, desired_ids[index], desired_ids[index + 1])

        raise RuntimeError(
            "Moodle-H5P-Reihenfolge stimmt nach mehreren Sortier-Versuchen noch nicht mit der "
            "Kapitelreihenfolge ueberein. Abbruch, damit kein Kurs mit falscher Reihenfolge online bleibt."
        )

    def _move_activity_before(self, page: Any, activity_id: int, before_activity_id: int) -> None:
        sesskey = self._moodle_sesskey(page)
        if not sesskey:
            raise RuntimeError("Moodle-Sesskey fehlt; Aktivitaeten koennen nicht sortiert werden.")

        page.goto(
            urljoin(self.course_url, "/course/mod.php") + "?" + urlencode({"sesskey": sesskey, "copy": str(activity_id)}),
            wait_until="domcontentloaded",
        )
        page.goto(
            urljoin(self.course_url, "/course/mod.php")
            + "?"
            + urlencode({"moveto": str(before_activity_id), "sesskey": sesskey}),
            wait_until="domcontentloaded",
        )

    def _create_h5p_activity(self, page: Any, section_number: int, package: MoodleH5PUploadPackage) -> MoodleH5PUploadResult:
        params = {
            "add": "h5pactivity",
            "type": "",
            "course": str(self._course_id()),
            "section": str(section_number),
            "return": "0",
            "sr": str(section_number),
        }
        page.goto(urljoin(self.course_url, "/course/modedit.php") + "?" + urlencode(params), wait_until="domcontentloaded")
        self._fill_h5p_form(page, package)
        activity_id = self._activity_id_from_current_page(page)
        if activity_id is None:
            # Ohne Aktivitaets-ID blieb Moodle auf dem Formular (z. B. Validierungsfehler
            # wegen fehlender Paketdatei). Ein stiller "created"-Erfolg ohne tatsaechlich
            # angelegte Aktivitaet waere ein False Positive im Sync-Bericht.
            self._write_debug_artifacts(page, f"create-without-id-{normalize_moodle_identifier(package.identifier)}")
            raise RuntimeError(
                f"H5P-Aktivitaet {package.identifier} wurde nicht angelegt: "
                "Moodle ist nach dem Speichern auf dem Formular stehen geblieben "
                "(haeufigste Ursache: die Paketdatei hat es nicht in den Dateimanager geschafft). "
                f"Aktuelle URL: {self._current_page_url(page) or 'unbekannt'}"
            )
        return MoodleH5PUploadResult(package.identifier, package.title, "created", activity_id)

    def _update_h5p_activity(
        self,
        page: Any,
        activity_id: int,
        package: MoodleH5PUploadPackage,
        *,
        section_number: int | None = None,
    ) -> MoodleH5PUploadResult | None:
        params = {"update": str(activity_id), "return": "0"}
        page.goto(urljoin(self.course_url, "/course/modedit.php") + "?" + urlencode(params), wait_until="domcontentloaded")
        if not self._h5p_form_is_available(page):
            self._write_debug_artifacts(page, f"invalid-update-{activity_id}")
            return None
        self._fill_h5p_form(page, package, section_number=section_number)
        if section_number is not None:
            self._move_activity_to_section_number(page, activity_id, section_number)
        return MoodleH5PUploadResult(package.identifier, package.title, "updated", activity_id)

    def _find_text_label_activity_id(
        self,
        page: Any,
        section_selector: str,
        identifier: str,
        *,
        title: str = "",
    ) -> int | None:
        payload = page.locator(section_selector).evaluate(
            """(section, payload) => {
                const { identifier, title } = payload;
                // The identifier is embedded as an HTML comment (<!-- course-sync-text:<id> -->)
                // in the label's markdown source, not as a queryable element attribute. Comment
                // nodes are not matched by querySelector, but their text is still part of
                // innerHTML, so search for the marker text directly.
                const markerText = `<!-- course-sync-text:${identifier} -->`;
                const markerModules = [...section.querySelectorAll('[data-cmid], li.activity[id^="module-"]')]
                  .filter((module) => !module.parentElement?.closest('[data-cmid], li.activity[id^="module-"]'));
                for (const module of markerModules) {
                  if (!module.innerHTML.includes(markerText)) continue;
                  const cmid = module.getAttribute('data-cmid')
                    || (module.id.match(/module-(\\d+)/) || [])[1]
                    || '';
                  if (cmid) return Number.parseInt(cmid, 10);
                }

                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const expectedTitle = normalize(title);
                if (!expectedTitle) return null;
                const modules = [...section.querySelectorAll('[data-cmid], li.activity[id^="module-"]')]
                  .filter((module) => !module.parentElement?.closest('[data-cmid], li.activity[id^="module-"]'));
                for (const module of modules) {
                  if (module.querySelector('a[href*="/mod/h5pactivity/view.php"]')) continue;
                  const moduleText = normalize(module.textContent || '');
                  if (!moduleText.includes(expectedTitle)) continue;
                  const moduleCmid = module.getAttribute('data-cmid')
                    || (module.id.match(/module-(\\d+)/) || [])[1]
                    || '';
                  if (moduleCmid) return Number.parseInt(moduleCmid, 10);
                }
                return null;
            }""",
            {"identifier": identifier, "title": title},
        )
        return int(payload) if payload else None

    def _goto_populated_section_page(
        self,
        page: Any,
        section: dict[str, str | int],
        section_number: int,
    ) -> dict[str, str | int] | None:
        """Navigate to the section's own page, where its content is always populated.

        Some course formats (e.g. format_tiles/"Kachelformat") never render section content
        on the main course page, which makes DOM-based section scraping there unreliable."""
        section_db_id = str(section.get("sectionDbId") or "").strip()
        if not section_db_id:
            return None
        section_page_url = urljoin(self.course_url, "/course/section.php") + "?" + urlencode({"id": section_db_id})
        page.goto(section_page_url, wait_until="domcontentloaded")
        # format_tiles renders section content dynamically after the initial DOM load, so give
        # it a moment before querying; _turn_editing_on() is a no-op (and thus no extra wait) when
        # editing is already on, which it typically is by the time this fallback runs.
        page.wait_for_timeout(800)
        self._turn_editing_on(page)
        return self._section_by_number(page, section_number)

    def _find_text_label_activity_id_via_section_page(
        self,
        page: Any,
        section: dict[str, str | int],
        section_number: int,
        label: MoodleTextLabelUploadItem,
    ) -> int | None:
        """Fallback for course formats (e.g. format_tiles/"Kachelformat") whose main course
        page never renders section content, so the initial marker/title search always comes
        up empty there and would otherwise create a duplicate label on every sync. Navigate to
        the section's own page (where its content is populated) and search again."""
        populated_section = self._goto_populated_section_page(page, section, section_number)
        if populated_section is None:
            return None
        return self._find_text_label_activity_id(
            page,
            str(populated_section["selector"]),
            label.identifier,
            title=label.title,
        )

    def _create_text_label(
        self,
        page: Any,
        section_number: int,
        label: MoodleTextLabelUploadItem,
        *,
        before_activity_id: int | None = None,
    ) -> MoodleH5PUploadResult:
        params = {
            "add": "label",
            "type": "",
            "course": str(self._course_id()),
            "section": str(section_number),
            "return": "0",
            "sr": str(section_number),
        }
        if before_activity_id:
            params["beforemod"] = str(before_activity_id)
        page.goto(urljoin(self.course_url, "/course/modedit.php") + "?" + urlencode(params), wait_until="domcontentloaded")
        self._fill_text_label_form(page, label)
        activity_id = self._activity_id_from_current_page(page)
        if activity_id is None:
            self._write_debug_artifacts(page, f"label-create-no-id-{normalize_moodle_identifier(label.identifier)}")
            raise RuntimeError(
                f"Moodle-Textfeld fuer {label.identifier} wurde gespeichert, aber es konnte keine Aktivitaets-ID "
                "aus der Ziel-URL ermittelt werden."
            )
        if before_activity_id:
            self._move_activity_before(page, activity_id, before_activity_id)
        return MoodleH5PUploadResult(label.identifier, label.title, "label-created", activity_id)

    def _update_text_label(
        self,
        page: Any,
        activity_id: int,
        label: MoodleTextLabelUploadItem,
    ) -> MoodleH5PUploadResult:
        params = {"update": str(activity_id), "return": "0"}
        page.goto(urljoin(self.course_url, "/course/modedit.php") + "?" + urlencode(params), wait_until="domcontentloaded")
        self._fill_text_label_form(page, label)
        return MoodleH5PUploadResult(label.identifier, label.title, "label-updated", activity_id)

    def _fill_text_label_form(self, page: Any, label: MoodleTextLabelUploadItem) -> None:
        name_input = page.locator('input[name="name"], #id_name')
        if name_input.count() > 0:
            name_input.first.fill(label.title)

        intro_editor = page.locator('textarea[name="introeditor[text]"], #id_introeditor')
        if intro_editor.count() == 0:
            self._write_debug_artifacts(page, f"missing-label-editor-{normalize_moodle_identifier(label.identifier)}")
            raise RuntimeError(f"Kein Moodle-Textfeld-Editor fuer {label.identifier} gefunden.")
        self._set_form_control_value(intro_editor.first, label.markdown)

        intro_format = page.locator('input[name="introeditor[format]"], select[name="introeditor[format]"]')
        if intro_format.count() > 0:
            self._set_form_control_value(intro_format.first, "4")

        self._click_first_by_text(
            page,
            [
                "Speichern und zum Kurs",
                "Save and return to course",
                "Speichern",
                "Save",
            ],
        )
        page.wait_for_load_state("domcontentloaded")
        if page.locator('textarea[name="introeditor[text]"], #id_introeditor').count() > 0:
            self._write_debug_artifacts(page, f"label-save-failed-{normalize_moodle_identifier(label.identifier)}")
            raise RuntimeError(
                f"Moodle-Textfeld fuer {label.identifier} konnte nicht gespeichert werden "
                "(Formular wurde nach dem Speichern erneut angezeigt, vermutlich ein Validierungsfehler)."
            )

    def _h5p_form_is_available(self, page: Any) -> bool:
        if page.locator('input[name="name"], #id_name').count() > 0:
            return True
        if page.locator("#fitem_id_packagefile, input[name='packagefile']").count() > 0:
            return True
        return False

    def _fill_h5p_form(
        self,
        page: Any,
        package: MoodleH5PUploadPackage,
        *,
        section_number: int | None = None,
    ) -> None:
        if not self._upload_h5p_package_file(page, package):
            self._write_debug_artifacts(page, "missing-file-input")
            raise RuntimeError(
                f"Kein Datei-Uploadfeld im H5P-Formular fuer {package.identifier} gefunden. "
                "Der Upload wurde abgebrochen, damit kein altes H5P-Paket als erfolgreich synchronisiert gilt."
            )
        else:
            self._confirm_file_overwrite_if_needed(page)
            self._close_open_moodle_dialogues(page)

        # Set the activity title after package upload because Moodle may prefill
        # the title from package metadata during upload processing.
        name_input = page.locator('input[name="name"], #id_name')
        if name_input.count() > 0:
            name_input.first.fill(package.title)

        if section_number is not None:
            self._set_activity_section(page, section_number)
        self._set_activity_points(page, package.points)
        if package.points > 0:
            self._set_completion_tracking(page, gradepass=1)
        else:
            self._disable_completion_tracking(page)

        self._click_first_by_text(
            page,
            [
                "Speichern und anzeigen",
                "Save and display",
                "Speichern und zum Kurs",
                "Save and return to course",
                "Speichern",
            ],
        )
        page.wait_for_load_state("domcontentloaded")

    def _h5p_package_filemanager_has_file(self, page: Any) -> bool:
        files = page.locator("#fitem_id_packagefile .fp-file, #fitem_id_packagefile .fp-filename")
        return files.count() > 0

    def _set_activity_section(self, page: Any, section_number: int) -> None:
        value = str(section_number)
        section_select = page.locator('select[name="section"], #id_section')
        if section_select.count() > 0:
            try:
                section_select.first.select_option(value=value)
                return
            except Exception:
                pass

        section_input = page.locator('input[name="section"], input#id_section')
        if section_input.count() > 0:
            self._set_form_control_value(section_input.first, value)

    def _move_activity_to_section_number(self, page: Any, activity_id: int, section_number: int) -> None:
        page.goto(self.course_url, wait_until="domcontentloaded")
        self._turn_editing_on(page)
        section = self._section_by_number(page, section_number)
        if section is None:
            raise RuntimeError(f"Ziel-Section {section_number} wurde nach dem Speichern nicht gefunden.")
        section_db_id = str(section.get("sectionDbId") or "").strip()
        if not section_db_id:
            raise RuntimeError(f"Ziel-Section {section_number} hat keine Moodle-Section-ID; Aktivitaet kann nicht verschoben werden.")
        self._move_activity_to_section_db_id(page, activity_id, section_db_id)

    def _move_activity_to_section_db_id(self, page: Any, activity_id: int, section_db_id: str) -> None:
        sesskey = self._moodle_sesskey(page)
        if not sesskey:
            raise RuntimeError("Moodle-Sesskey fehlt; Aktivitaet kann nicht in die Ziel-Section verschoben werden.")
        page.goto(
            urljoin(self.course_url, "/course/mod.php") + "?" + urlencode({"sesskey": sesskey, "copy": str(activity_id)}),
            wait_until="domcontentloaded",
        )
        page.goto(
            urljoin(self.course_url, "/course/mod.php") + "?" + urlencode({"movetosection": section_db_id, "sesskey": sesskey}),
            wait_until="domcontentloaded",
        )
        page.goto(self.course_url, wait_until="domcontentloaded")

    def _set_activity_points(self, page: Any, points: int) -> None:
        point_value = int(points)
        if point_value <= 0:
            for selector in (
                'select[name="grade[modgrade_type]"]',
                '#id_grade_modgrade_type',
                'select[name="gradetype"]',
                '#id_gradetype',
            ):
                grade_type = page.locator(selector)
                if grade_type.count() == 0:
                    continue
                try:
                    self._set_form_control_value(grade_type.first, "none")
                    return
                except Exception:
                    continue
            return

        value = str(point_value)

        # Explicitly select Moodle's point grading type where the form exposes it.
        for selector in (
            'select[name="grade[modgrade_type]"]',
            '#id_grade_modgrade_type',
            'select[name="gradetype"]',
            '#id_gradetype',
        ):
            grade_type = page.locator(selector)
            if grade_type.count() == 0:
                continue
            for option in ("point", "1", "value"):
                try:
                    self._set_form_control_value(grade_type.first, option)
                    break
                except Exception:
                    continue
            break

        # Moodle variants use either a plain numeric field or a select.
        selectors = (
            'input[name="grade[modgrade_point]"]',
            '#id_grade_modgrade_point',
            'input[name="grade"]',
            '#id_grade',
            'input[name="maxgrade"]',
            'select[name="grade"]',
            '#id_grademethod + select',
        )
        for selector in selectors:
            control = page.locator(selector)
            if control.count() == 0:
                continue
            field = control.first
            try:
                self._set_form_control_value(field, value)
                return
            except Exception:
                pass
            try:
                field.select_option(value=value)
                return
            except Exception:
                continue
        page.evaluate(
            """(value) => {
                const candidates = [
                  'input[name="grade[modgrade_point]"]',
                  '#id_grade_modgrade_point',
                  'input[name="grade"]',
                  '#id_grade',
                  'input[name="maxgrade"]'
                ];
                for (const selector of candidates) {
                  const element = document.querySelector(selector);
                  if (!element) continue;
                  element.value = value;
                  element.dispatchEvent(new Event('input', { bubbles: true }));
                  element.dispatchEvent(new Event('change', { bubbles: true }));
                  return;
                }
            }""",
            value,
        )

    def _set_completion_tracking(self, page: Any, gradepass: int = 1) -> None:
        # Set the passing grade in the grade section (gradepass field).
        gradepass_input = page.locator('input[name="gradepass"], #id_gradepass')
        if gradepass_input.count() > 0:
            self._set_form_control_value(gradepass_input.first, str(gradepass))

        # Enable completion tracking if not already set to "show activity as complete
        # when conditions are met" (value 2).
        completion_select = page.locator('select[name="completion"], #id_completion')
        if completion_select.count() > 0:
            try:
                completion_select.first.select_option(value="2")
            except Exception:
                pass
        else:
            completion_radio = page.locator('input[type="radio"][name="completion"][value="2"], #id_completion_2')
            if completion_radio.count() > 0 and not completion_radio.first.is_checked():
                self._set_checkbox_checked(completion_radio.first)

        # Condition: student must receive a grade (completionusegrade = 1).
        # Moodle's advcheckbox pattern renders a hidden <input> carrying the "unchecked"
        # value right before the real checkbox, both sharing the same name= attribute; a
        # bare name selector can match the hidden one first, which is not checkable.
        page.wait_for_timeout(300)
        grade_condition = page.locator(
            'input[type="checkbox"][name="completionusegrade"], #id_completionusegrade'
        )
        if grade_condition.count() > 0 and not grade_condition.first.is_checked():
            self._set_checkbox_checked(grade_condition.first)

        # Condition: student must reach the passing grade (completionpassgrade = 1).
        # Moodle 4.x exposes this as a separate checkbox that only appears after
        # completionusegrade is checked, so wait briefly for it to become visible.
        page.wait_for_timeout(300)
        passgrade_condition = page.locator(
            'input[type="checkbox"][name="completionpassgrade"], #id_completionpassgrade'
        )
        if passgrade_condition.count() > 0 and not passgrade_condition.first.is_checked():
            self._set_checkbox_checked(passgrade_condition.first)

    def _disable_completion_tracking(self, page: Any) -> None:
        completion_select = page.locator('select[name="completion"], #id_completion')
        if completion_select.count() > 0:
            self._set_form_control_value(completion_select.first, "0")
            return

        completion_radio = page.locator(
            'input[type="radio"][name="completion"][value="0"], '
            'input[type="radio"][name="completion"][value="none"], '
            '#id_completion_0'
        )
        if completion_radio.count() > 0 and not completion_radio.first.is_checked():
            self._set_checkbox_checked(completion_radio.first)

    def _set_form_control_value(self, locator: Any, value: str) -> None:
        try:
            if locator.is_visible():
                locator.fill(value)
                return
        except Exception:
            pass
        locator.evaluate(
            """(element, value) => {
                element.value = value;
                element.dispatchEvent(new Event('input', { bubbles: true }));
                element.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            value,
        )

    def _set_checkbox_checked(self, locator: Any) -> None:
        try:
            if locator.is_visible():
                locator.check()
                return
        except Exception:
            pass
        locator.evaluate(
            """(element) => {
                element.checked = true;
                element.dispatchEvent(new Event('input', { bubbles: true }));
                element.dispatchEvent(new Event('change', { bubbles: true }));
            }"""
        )

    def _upload_h5p_package_file(self, page: Any, package: MoodleH5PUploadPackage) -> bool:
        def debug(message: str) -> None:
            if os.environ.get("COURSE_SYNC_DEBUG_MOODLE_FILEMANAGER"):
                print(f"Filemanager-Debug: {message}", flush=True)

        direct_input = page.locator('input[type="file"]')
        debug(f"direct file inputs: {direct_input.count()}")
        if direct_input.count() > 0:
            direct_input.first.set_input_files(str(package.path))
            return True

        try:
            page.wait_for_selector("#fitem_id_packagefile .filemanager", timeout=10_000)
            page.wait_for_function(
                """
                () => {
                  const manager = document.querySelector('#fitem_id_packagefile .filemanager');
                  return manager && !manager.classList.contains('fm-loading');
                }
                """,
                timeout=20_000,
            )
        except Exception:
            pass
        page.wait_for_timeout(1500)

        add_button = page.locator(
            '#fitem_id_packagefile .fp-btn-add a, '
            '#fitem_id_packagefile a[title*="Datei hinzufügen"], '
            '#fitem_id_packagefile a[title*="Add file"], '
            '#fitem_id_packagefile button[title*="Datei hinzufügen"], '
            '#fitem_id_packagefile button[title*="Add file"]'
        )
        existing_file = page.locator("#fitem_id_packagefile .fp-file")
        debug(
            "before delete: "
            f"files={existing_file.count()} file_visible={self._locator_has_visible_item(existing_file)} "
            f"add={add_button.count()} add_visible={self._locator_has_visible_item(add_button)}"
        )
        if existing_file.count() > 0 and self._locator_has_visible_item(existing_file):
            self._delete_existing_h5p_package_file_if_needed(page)
            add_button = page.locator(
                '#fitem_id_packagefile .fp-btn-add a, '
                '#fitem_id_packagefile a[title*="Datei hinzufügen"], '
                '#fitem_id_packagefile a[title*="Add file"], '
                '#fitem_id_packagefile button[title*="Datei hinzufügen"], '
                '#fitem_id_packagefile button[title*="Add file"]'
            )
            try:
                add_button.first.wait_for(state="visible", timeout=8_000)
            except Exception:
                pass
            debug(
                "after delete existing: "
                f"files={page.locator('#fitem_id_packagefile .fp-file').count()} "
                f"file_visible={self._locator_has_visible_item(page.locator('#fitem_id_packagefile .fp-file'))} "
                f"add={add_button.count()} add_visible={self._locator_has_visible_item(add_button)}"
            )
        elif add_button.count() > 0 and not self._locator_has_visible_item(add_button):
            self._delete_existing_h5p_package_file_if_needed(page)
            add_button = page.locator(
                '#fitem_id_packagefile .fp-btn-add a, '
                '#fitem_id_packagefile a[title*="Datei hinzufügen"], '
                '#fitem_id_packagefile a[title*="Add file"], '
                '#fitem_id_packagefile button[title*="Datei hinzufügen"], '
                '#fitem_id_packagefile button[title*="Add file"]'
            )
            try:
                add_button.first.wait_for(state="visible", timeout=8_000)
            except Exception:
                pass
            debug(
                "after hidden add delete: "
                f"files={page.locator('#fitem_id_packagefile .fp-file').count()} "
                f"file_visible={self._locator_has_visible_item(page.locator('#fitem_id_packagefile .fp-file'))} "
                f"add={add_button.count()} add_visible={self._locator_has_visible_item(add_button)}"
            )
        if add_button.count() == 0:
            debug("no add button")
            return False
        if not self._locator_has_visible_item(add_button):
            # The filemanager toolbar can briefly re-render and hide the add
            # button although no file is present. Wait once and re-check.
            try:
                add_button.first.wait_for(state="visible", timeout=8_000)
            except Exception:
                pass
            add_button = page.locator(
                '#fitem_id_packagefile .fp-btn-add a, '
                '#fitem_id_packagefile a[title*="Datei hinzufügen"], '
                '#fitem_id_packagefile a[title*="Add file"], '
                '#fitem_id_packagefile button[title*="Datei hinzufügen"], '
                '#fitem_id_packagefile button[title*="Add file"]'
            )
            if not self._locator_has_visible_item(add_button):
                self._close_open_moodle_dialogues(page)
                debug("add button not visible")
                return False

        try:
            self._click_first_visible(add_button)
        except Exception:
            if page.locator("#fitem_id_packagefile .fp-file").count() > 0:
                self._close_open_moodle_dialogues(page)
                debug("click add failed while file exists")
                return False
            raise
        page.wait_for_timeout(1000)
        debug(
            "after add click: "
            f"dialogs={page.locator('.modal.show, .moodle-dialogue-base[aria-hidden=\"false\"]').count()} "
            f"file_inputs={page.locator('input[type=\"file\"]').count()}"
        )

        upload_repo_labels = ["Datei hochladen", "Upload a file"]
        for label in upload_repo_labels:
            repo = page.get_by_text(re.compile(label, re.IGNORECASE))
            if repo.count() > 0:
                repo.first.click()
                page.wait_for_timeout(500)
                break

        picker_input = page.locator('input[type="file"]')
        try:
            picker_input.first.wait_for(state="attached", timeout=15_000)
        except Exception:
            debug("picker input missing")
            return False
        picker_input.first.set_input_files(str(package.path))

        for label in ["Datei hochladen", "Upload this file", "Upload", "Hochladen"]:
            button = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
            if button.count() > 0:
                button.first.click()
                # Der Upload laeuft als Hintergrund-Request im Datei-Picker; bei grossen
                # Paketen (z. B. mit gebuendeltem Pyodide) dauert er je nach Anbindung
                # deutlich laenger als eine feste Wartezeit. Der Dialog schliesst sich von
                # selbst, sobald die Datei im Entwurfsbereich liegt; erst dann darf er
                # geschlossen werden, sonst wird der Upload abgebrochen und das Speichern
                # scheitert spaeter am leeren Pflichtfeld.
                try:
                    page.wait_for_selector(
                        "#fitem_id_packagefile .fp-file, #fitem_id_packagefile .fp-filename",
                        timeout=180_000,
                    )
                except Exception:
                    debug("file did not appear in filemanager after upload")
                    self._write_debug_artifacts(page, f"upload-timeout-{normalize_moodle_identifier(package.identifier)}")
                    self._close_open_moodle_dialogues(page)
                    return False
                self._close_open_moodle_dialogues(page)
                return True

        return True

    def _delete_existing_h5p_package_file_if_needed(self, page: Any) -> None:
        file_locator = page.locator("#fitem_id_packagefile .fp-file")
        try:
            page.wait_for_selector("#fitem_id_packagefile .fp-file:visible", timeout=20_000)
        except Exception:
            return

        # Moodle's filemanager can need one click to select a file and a second
        # one to open its action dialogue, depending on whether the YUI
        # filemanager has finished binding handlers. Try a few gentle variants
        # before giving up; maxfiles=1 keeps the upload button hidden until this
        # existing file is really deleted.
        opened_dialogue = False
        click_targets = page.locator(
            "#fitem_id_packagefile .fp-file a.d-block, "
            "#fitem_id_packagefile .fp-file, "
            "#fitem_id_packagefile .fp-filename, "
            "#fitem_id_packagefile .fp-contextmenu"
        )
        for index in range(click_targets.count()):
            click_target = click_targets.nth(index)
            try:
                if not self._locator_item_is_clickable(click_target):
                    continue
                click_target.click()
                page.locator(
                    ".moodle-dialogue-base[aria-hidden='false'] .fp-file-delete, "
                    ".modal.show .fp-file-delete"
                ).first.wait_for(state="visible", timeout=2_500)
                opened_dialogue = True
                break
            except Exception:
                page.wait_for_timeout(500)
                continue
        if not opened_dialogue:
            return
        page.locator(
            ".moodle-dialogue-base[aria-hidden='false'] .fp-file-delete, "
            ".modal.show .fp-file-delete"
        ).first.click()
        confirmed = self._confirm_file_delete_if_needed(page)
        if confirmed:
            page.wait_for_timeout(1500)

        self._close_open_moodle_dialogues(page)
        try:
            page.locator("#fitem_id_packagefile .fp-btn-add a").first.wait_for(state="visible", timeout=15_000)
        except Exception:
            page.wait_for_timeout(1500)

    def _confirm_file_delete_if_needed(self, page: Any) -> bool:
        confirmation_targets = [
            page.locator(".modal.show .btn-primary"),
            page.locator(".modal.show [data-action='save']"),
            page.locator(".moodle-dialogue-base[aria-hidden='false'] .fp-dlg-butconfirm"),
        ]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for target in confirmation_targets:
                visible_button = self._first_clickable(target)
                if visible_button is not None:
                    visible_button.click()
                    return True
            for dialog_selector in [".modal.show", ".moodle-dialogue-base[aria-hidden='false']"]:
                dialog = page.locator(dialog_selector)
                if dialog.count() == 0:
                    continue
                for label in ["Ja", "Yes", "OK", "Löschen", "Delete"]:
                    visible_button = self._first_clickable(
                        dialog.last.get_by_role("button", name=re.compile(label, re.IGNORECASE))
                    )
                    if visible_button is not None:
                        visible_button.click()
                        return True
            page.wait_for_timeout(250)
        return False

    def _close_open_moodle_dialogues(self, page: Any) -> None:
        for _ in range(3):
            open_dialogs = page.locator('.moodle-dialogue-base[aria-hidden="false"], .modal.show')
            if open_dialogs.count() == 0:
                return
            close_button = page.locator(
                '.moodle-dialogue-base[aria-hidden="false"] .closebutton, '
                '.moodle-dialogue-base[aria-hidden="false"] .fp-file-cancel, '
                '.modal.show button[aria-label="Schließen"], '
                '.modal.show button[aria-label="Close"], '
                '.modal.show .btn-secondary'
            )
            clicked = False
            for index in range(close_button.count()):
                candidate = close_button.nth(index)
                try:
                    if candidate.is_visible():
                        candidate.click()
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                page.keyboard.press("Escape")
            page.wait_for_timeout(500)

    def _locator_has_visible_item(self, locator: Any) -> bool:
        for index in range(locator.count()):
            try:
                if self._locator_item_is_clickable(locator.nth(index)):
                    return True
            except Exception:
                continue
        return False

    def _click_first_visible(self, locator: Any) -> None:
        candidate = self._first_clickable(locator)
        if candidate is not None:
            candidate.click()
            return
        locator.first.click(force=True)

    def _first_clickable(self, locator: Any) -> Any | None:
        for index in range(locator.count()):
            candidate = locator.nth(index)
            try:
                if self._locator_item_is_clickable(candidate):
                    return candidate
            except Exception:
                continue
        return None

    def _locator_item_is_clickable(self, locator: Any) -> bool:
        if not locator.is_visible():
            return False
        box = locator.bounding_box()
        if not box:
            return False
        return bool(box.get("width", 0) > 0 and box.get("height", 0) > 0)

    def _confirm_file_overwrite_if_needed(self, page: Any) -> None:
        for label in ["Overwrite", "Ersetzen", "Überschreiben"]:
            button = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
            if button.count() > 0:
                button.first.click()
                page.wait_for_timeout(500)
                return

    def _write_debug_artifacts(self, page: Any, label: str) -> None:
        debug_dir = Path("build") / "scratch" / "temp" / "moodle-upload-debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "-", label).strip("-") or "page"
        html_path = debug_dir / f"{safe_label}.html"
        screenshot_path = debug_dir / f"{safe_label}.png"
        try:
            html_path.write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"Debug gespeichert: {html_path} und {screenshot_path}", flush=True)
        except Exception as error:
            print(f"Debug konnte nicht gespeichert werden: {error}", flush=True)

    def _format_timeout_error(
        self,
        error: Exception,
        *,
        current_step: str,
        package: MoodleH5PUploadPackage | None,
    ) -> str:
        raw_lines = [line.strip() for line in str(error).splitlines() if line.strip()]
        summary = raw_lines[0] if raw_lines else error.__class__.__name__
        details = [
            "Moodle-Upload hat zu lange gewartet.",
            f"Schritt: {current_step}",
            f"Kurs: {self.course_url}",
        ]
        if package is not None:
            details.extend(
                [
                    f"H5P-Paket: {package.identifier}",
                    f"Titel: {package.title}",
                    f"Datei: {package.path}",
                ]
            )
        details.extend(
            [
                f"Playwright: {summary}",
                "Debug: build/scratch/temp/moodle-upload-debug/timeout-*.html und .png",
            ]
        )
        return "\n".join(details)

    def _click_first_by_text(self, page: Any, labels: list[str]) -> None:
        for label in labels:
            pattern = re.compile(label, re.IGNORECASE)
            button = page.get_by_role("button", name=pattern)
            if button.count() > 0:
                button.first.click()
                return
            link = page.get_by_role("link", name=pattern)
            if link.count() > 0:
                link.first.click()
                return
            submit = page.locator('input[type="submit"]').filter(has_text=pattern)
            if submit.count() > 0:
                submit.first.click()
                return
            submit_by_value = page.locator(f'input[type="submit"][value*="{label}"]')
            if submit_by_value.count() > 0:
                submit_by_value.first.click()
                return
            text = page.get_by_text(pattern)
            if text.count() > 0:
                text.first.click()
                return
        raise RuntimeError(f"Keinen passenden Moodle-Button gefunden: {', '.join(labels)}")

    def _course_id(self) -> int:
        parsed = urlparse(self.course_url)
        course_ids = parse_qs(parsed.query).get("id", [])
        if not course_ids:
            raise RuntimeError(f"Course-ID fehlt in Moodle-URL: {self.course_url}")
        return int(course_ids[0])

    def _activity_id_from_current_page(self, page: Any) -> int | None:
        parsed = urlparse(page.url)
        ids = parse_qs(parsed.query).get("id", [])
        if ids:
            return int(ids[0])
        return None
