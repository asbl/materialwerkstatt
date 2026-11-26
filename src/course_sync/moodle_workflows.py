from __future__ import annotations

from material_core.filesystem import atomic_write_text

import dataclasses
import html
import json
import os
import re
from pathlib import Path
from typing import (
    Any,
    NamedTuple,
)
from urllib.parse import parse_qs, urlparse
from zipfile import ZipFile


from course_sync.classes import (
    SyncMetadataEntry,
    apply_secret_replacements,
    resolve_secret_replacements,
    sanitize_h5p_package,
)
from course_sync.classes.platform_sync_state import record_target_sync_state
from course_sync.classes.python_runner_policy import contains_miniworlds_package
from course_sync.classes.moodle_playwright_uploader import (
    MoodleH5PUploadPackage,
    MoodleH5PUploadResult,
    MoodleSectionCleanupResult,
    MoodleTextLabelUploadItem,
    format_h5p_activity_title,
    infer_h5p_package_points,
    normalize_moodle_identifier,
    read_h5p_package_title,
)


def _normalize_verification_text(value: str) -> str:
    """Compare text signals independently of Markdown and rendered whitespace."""
    value = re.sub(r"[`*_#>\-]+", " ", html.unescape(value))
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\s+([.,:;!?()])", r"\1", value).casefold()


class ChapterPlanItem(NamedTuple):
    slug: str
    title: str
    synced: bool = True



class MoodleWorkflows:
    def __init__(self, application) -> None:
        self.application = application

    def _chapter_slug_from_src(self, src: str) -> str:
        source_path = Path(src).with_suffix("")
        parts = source_path.parts
        if "chapters" in parts:
            chapter_index = parts.index("chapters")
            if len(parts) > chapter_index + 1:
                return parts[chapter_index + 1]
        return source_path.name


    def _chapter_path_for_slug(self, course_dir: Path, chapter: str) -> Path:
        flat_path = course_dir / "chapters" / f"{chapter}.mdx"
        if flat_path.is_file():
            return flat_path
        chapter_dir = course_dir / "chapters" / chapter
        if chapter_dir.is_dir():
            candidates = sorted(chapter_dir.glob("*.mdx"))
            if candidates:
                return candidates[0]
        return flat_path


    def _chapter_title_from_index(self, course_dir: Path, chapter: str) -> str:
        index_path = course_dir / "index.mdx"
        if index_path.exists():
            index_source = index_path.read_text(encoding="utf-8")
            pattern = re.compile(r"<Chapter\b(?P<attrs>.*?)/?>", re.IGNORECASE | re.DOTALL)
            attr_pattern = re.compile(r"\b(?P<key>src|title)=['\"](?P<value>[^'\"]+)['\"]", re.IGNORECASE)
            for match in pattern.finditer(index_source):
                attrs = {
                    item.group("key").lower(): html.unescape(item.group("value")).strip()
                    for item in attr_pattern.finditer(match.group("attrs"))
                }
                if self.application._chapter_slug_from_src(attrs.get("src", "")) == chapter:
                    return attrs.get("title", "") or chapter

        chapter_path = self.application._chapter_path_for_slug(course_dir, chapter)
        if chapter_path.exists():
            chapter_source = chapter_path.read_text(encoding="utf-8")
            heading_match = re.search(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*#*\s*$", chapter_source, re.MULTILINE)
            if heading_match:
                title = html.unescape(heading_match.group("title")).strip()
                if title:
                    return title
        return chapter


    def _chapter_hidden_from_index(self, course_dir: Path, chapter: str) -> bool:
        """True, wenn das Chapter-Tag in index.mdx `hidden` (bzw. `hidden={true}`) traegt."""
        index_path = course_dir / "index.mdx"
        if not index_path.exists():
            return False
        pattern = re.compile(r"<Chapter\b(?P<attrs>.*?)/?>", re.IGNORECASE | re.DOTALL)
        src_pattern = re.compile(r"\bsrc=['\"](?P<value>[^'\"]+)['\"]", re.IGNORECASE)
        hidden_pattern = re.compile(r"(?<![\w-])hidden(?:\s*=\s*(?:\{\s*(?P<expr>true|false)\s*\}|['\"](?P<str>true|false)['\"]))?(?![\w-])", re.IGNORECASE)
        for match in pattern.finditer(index_path.read_text(encoding="utf-8")):
            attrs = match.group("attrs")
            src_match = src_pattern.search(attrs)
            if src_match is None or self.application._chapter_slug_from_src(html.unescape(src_match.group("value")).strip()) != chapter:
                continue
            hidden_match = hidden_pattern.search(attrs)
            if hidden_match is None:
                return False
            value = (hidden_match.group("expr") or hidden_match.group("str") or "true").lower()
            return value == "true"
        return False


    def _chapter_attr_is_synced(self, attrs_source: str) -> bool:
        """Parse a ``<Chapter>`` tag's ``synced`` attribute.

        Defaults to ``True`` when the attribute is absent (a chapter is synced
        unless explicitly opted out), matching JSX boolean-shorthand semantics:
        a bare ``synced`` means ``True``, while ``synced={false}`` / ``synced="false"``
        opts the chapter out of automatic course-wide sync/upload.
        """
        match = re.search(r"\bsynced(?:=(\{(?P<jsx>[^}]*)\}|['\"](?P<quoted>[^'\"]*)['\"]))?", attrs_source, re.IGNORECASE)
        if not match:
            return True
        raw_value = match.group("jsx") if match.group("jsx") is not None else match.group("quoted")
        if raw_value is None:
            return True
        return raw_value.strip().lower() != "false"


    def _course_chapter_plan(self, course_dir: Path, *, synced_only: bool = False) -> list[ChapterPlanItem]:
        index_path = course_dir / "index.mdx"
        if not index_path.exists():
            raise FileNotFoundError(f"Kursindex wurde nicht gefunden: {index_path}")

        source = index_path.read_text(encoding="utf-8")
        chapters: list[ChapterPlanItem] = []
        pattern = re.compile(
            r"<Chapter\b(?P<attrs>.*?)/?>",
            re.IGNORECASE | re.DOTALL,
        )
        attr_pattern = re.compile(r"\b(?P<key>src|title)=['\"](?P<value>[^'\"]+)['\"]", re.IGNORECASE)
        for match in pattern.finditer(source):
            attrs_source = match.group("attrs")
            attrs = {item.group("key").lower(): html.unescape(item.group("value")).strip() for item in attr_pattern.finditer(attrs_source)}
            src = attrs.get("src", "")
            title = attrs.get("title", "")
            if not src:
                continue
            slug = self.application._chapter_slug_from_src(src)
            if slug:
                chapters.append(ChapterPlanItem(slug, title or slug, self.application._chapter_attr_is_synced(attrs_source)))
        if not chapters:
            raise ValueError(f"Kurs '{course_dir.name}' enthält keine Chapter-Einträge in index.mdx.")
        if synced_only:
            chapters = [chapter for chapter in chapters if chapter.synced]
        return chapters


    def _course_env_key(self, course_dir: Path, suffix: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", course_dir.name).strip("_").upper()
        return f"MOODLE_{normalized}_{suffix}"


    def _target_env_key(self, course_dir: Path, target: str, suffix: str) -> str:
        course_normalized = re.sub(r"[^A-Za-z0-9]+", "_", course_dir.name).strip("_").upper()
        target_normalized = re.sub(r"[^A-Za-z0-9]+", "_", target).strip("_").upper()
        return f"MOODLE_{course_normalized}_{target_normalized}_{suffix}"


    def _course_env_value(self, course_dir: Path, suffix: str, fallback_key: str) -> str:
        return os.environ.get(self.application._course_env_key(course_dir, suffix), "").strip() or os.environ.get(fallback_key, "").strip()


    def _target_env_value(self, course_dir: Path, target: str | None, suffix: str, fallback_key: str) -> str:
        if target:
            target_value = os.environ.get(self.application._target_env_key(course_dir, target, suffix), "").strip()
            if target_value:
                return target_value
        return self.application._course_env_value(course_dir, suffix, fallback_key)


    def _load_target_config(self, course_dir: Path, target: str) -> dict[str, Any]:
        config_path = course_dir / f".moodle-target-{target}.yml"
        if not config_path.exists():
            return {}
        import yaml
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}


    def _target_auth_uses_credentials(self, target_config: dict[str, Any]) -> bool:
        auth_mode = str(target_config.get("auth", "credentials")).strip().lower()
        return auth_mode in {"credentials", "sso", "schulportal", "schulportal-hessen"}


    def _secret_replacements(self, course_dir: Path, target: str | None) -> dict[str, str]:
        """Ersetzungen fuer das Ziel: Kurs-Secrets, sofern das Ziel sie nicht mit keep_secrets behaelt."""
        target_config = self.application._load_target_config(course_dir, target) if target else None
        return resolve_secret_replacements(course_dir, target_config)


    def _sanitize_packages_for_target(
        self,
        course_dir: Path,
        chapter: str,
        packages: list[MoodleH5PUploadPackage],
        replacements: dict[str, str],
        target: str | None,
    ) -> list[MoodleH5PUploadPackage]:
        """H5P-Pakete fuer ein Ziel ohne Secrets: Kopien unter build/h5p-sanitized/<ziel>/<kapitel>/.

        Dateiname (und damit die Aktivitaeten-Kennung) bleibt gleich, Titel und Punkte
        werden aus der sanitized Kopie neu gelesen, damit auch der Moodle-Aktivitaetentitel
        keine Secrets enthaelt.
        """
        sanitized_root = self.application.course_build_dir(course_dir) / "h5p-sanitized" / (target or "default") / chapter
        sanitized: list[MoodleH5PUploadPackage] = []
        for package in packages:
            sanitized_path = sanitize_h5p_package(package.path, replacements, sanitized_root / package.path.name)
            points = infer_h5p_package_points(sanitized_path)
            sanitized.append(
                dataclasses.replace(
                    package,
                    path=sanitized_path,
                    title=format_h5p_activity_title(read_h5p_package_title(sanitized_path), points),
                    points=points,
                )
            )
        return sanitized


    @staticmethod
    def _sanitize_text_labels(
        labels: list[MoodleTextLabelUploadItem],
        replacements: dict[str, str],
    ) -> list[MoodleTextLabelUploadItem]:
        return [
            dataclasses.replace(
                label,
                title=apply_secret_replacements(label.title, replacements),
                markdown=apply_secret_replacements(label.markdown, replacements),
            )
            for label in labels
        ]


    def _infer_target_from_course_url(self, course_dir: Path, course_url: str | None) -> str | None:
        """Infer a named Moodle target (and thus its auth mode/credentials) from an explicit
        --course-url by matching it against the course_url configured in each
        .moodle-target-<name>.yml file. Only infers when exactly one target matches, so an
        ambiguous match falls back to requiring an explicit --target."""
        if not course_url:
            return None
        normalized_course_url = course_url.strip().rstrip("/")
        matches: list[str] = []
        for config_path in sorted(course_dir.glob(".moodle-target-*.yml")):
            target_name = config_path.name.removeprefix(".moodle-target-").removesuffix(".yml")
            target_config = self.application._load_target_config(course_dir, target_name)
            configured_course_url = str(
                target_config.get("course_url", target_config.get("courseUrl", ""))
            ).strip().rstrip("/")
            if configured_course_url and configured_course_url == normalized_course_url:
                matches.append(target_name)
        if len(matches) == 1:
            return matches[0]
        return None


    def _resolve_moodle_course_url(self, course_dir: Path, course_url: str | None, target: str | None = None) -> str:
        if course_url:
            return course_url

        if target:
            # Reihenfolge fuer benannte Ziele: zielspezifische Variable, dann die URL aus
            # .moodle-target-<ziel>.yml, erst danach Kurs-/Globalvariablen. Sonst wuerde
            # MOODLE_<KURS>_COURSE_URL ein neu angelegtes Ziel auf den alten Kurs lenken.
            strict_env_url = os.environ.get(self.application._target_env_key(course_dir, target, "COURSE_URL"), "").strip()
            if strict_env_url:
                return strict_env_url
            target_config = self.application._load_target_config(course_dir, target)
            configured_course_url = str(
                target_config.get("course_url", target_config.get("courseUrl", ""))
            ).strip()
            if configured_course_url:
                return configured_course_url

        env_course_url = self.application._target_env_value(course_dir, target, "COURSE_URL", "MOODLE_COURSE_URL")
        if env_course_url:
            return env_course_url

        if target:
            raise ValueError(
                f"Moodle-Kurs-URL für Target '{target}' fehlt. "
                f"Setze course_url in .moodle-target-{target}.yml, "
                f"{self.application._target_env_key(course_dir, target, 'COURSE_URL')} oder gib --course-url an."
            )

        metadata = self.application._SYNC_METADATA_STORE.load(course_dir)
        if metadata is None or not metadata.moodle_base_url or not metadata.remote_course_id:
            raise ValueError(
                "Moodle-Kurs-URL fehlt. Gib --course-url an oder importiere den Kurs zuerst, damit .course-sync.json existiert."
            )
        return f"{metadata.moodle_base_url.rstrip('/')}/course/view.php?id={metadata.remote_course_id}"


    def _resolve_moodle_storage_state(self, course_dir: Path, storage_state: Path | None, target: str | None = None) -> Path:
        target_storage_state = (
            Path(self.application._target_env_value(course_dir, target, "STORAGE_STATE", "MOODLE_STORAGE_STATE")).expanduser()
            if self.application._target_env_value(course_dir, target, "STORAGE_STATE", "MOODLE_STORAGE_STATE")
            else None
        )
        return storage_state or target_storage_state or (
            course_dir / (f".moodle-storage-state-{target}.json" if target else ".moodle-storage-state.json")
        )


    def _moodle_base_url(self, course_url: str) -> str:
        parsed = urlparse(course_url)
        return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else course_url.rstrip("/")


    def _remote_verification_expectations(self, course_dir: Path, target: str | None = None) -> list[dict[str, object]]:
        metadata = self.application._SYNC_METADATA_STORE.load(course_dir)
        target_ids = self.application._load_target_activity_ids(course_dir, target) if target else {}
        secret_replacements = self._secret_replacements(course_dir, target)
        expectations: list[dict[str, object]] = []
        for chapter in self.application._course_chapter_plan(course_dir, synced_only=True):
            packages = self.application.collect_h5p_upload_packages(course_dir, chapter.slug)
            if secret_replacements:
                packages = self._sanitize_packages_for_target(course_dir, chapter.slug, packages, secret_replacements, target)
            for package in packages:
                activity_id = target_ids.get(package.identifier)
                if activity_id is None and metadata is not None and package.identifier in metadata.entries:
                    activity_id = metadata.entries[package.identifier].remote_activity_id
                expectations.append(
                    {
                        "identifier": package.identifier,
                        "title": package.title,
                        "packagePath": str(package.path),
                        "activityId": activity_id or 0,
                        "signals": self.application._h5p_package_text_signals(package.path),
                    }
                )
        return expectations


    def _recover_verification_ids(self, expected: list[dict[str, object]], activities: list[dict[str, Any]]) -> dict[str, int]:
        """Match unique exact titles first, then Moodle's optional Test: prefix."""
        occupied = {int(item.get("activityId") or 0) for item in expected}
        recovered: dict[str, int] = {}
        for strip_prefix in (False, True):
            def key(title: str) -> str:
                if strip_prefix:
                    title = re.sub(r"^test:\s*", "", title.strip(), flags=re.IGNORECASE)
                return normalize_moodle_identifier(title)

            local: dict[str, set[str]] = {}
            remote: dict[str, set[int]] = {}
            for item in expected:
                title = key(str(item.get("title") or ""))
                if title:
                    local.setdefault(title, set()).add(str(item["identifier"]))
            for activity in activities:
                title = key(str(activity.get("title") or ""))
                activity_id = int(activity.get("id") or 0)
                if title and activity_id > 0:
                    remote.setdefault(title, set()).add(activity_id)
            for item in expected:
                identifier = str(item["identifier"])
                title = key(str(item.get("title") or ""))
                candidates = remote.get(title, set())
                if not item.get("activityId") and identifier not in recovered and len(local.get(title, set())) == 1 and len(candidates) == 1:
                    activity_id = next(iter(candidates))
                    if activity_id not in occupied:
                        recovered[identifier] = activity_id
                        occupied.add(activity_id)
        return recovered


    def _h5p_package_text_signals(self, package_path: Path) -> list[str]:
        try:
            with ZipFile(package_path) as archive:
                metadata = json.loads(archive.read("h5p.json").decode("utf-8"))
                content = json.loads(archive.read("content/content.json").decode("utf-8"))
        except Exception:
            return [package_path.stem]

        signals: list[str] = []
        editor = content.get("editorSettings") if isinstance(content, dict) else {}
        editor = editor if isinstance(editor, dict) else {}
        for value in [editor.get("instructions"), editor.get("startingCode")]:
            text = str(value or "")
            for line in text.splitlines():
                cleaned = re.sub(r"[`*_#>\-]+", " ", line).strip()
                if len(cleaned) >= 18:
                    signals.append(cleaned[:80])
                    break
        contents = content.get("contents") if isinstance(content, dict) else []
        if isinstance(contents, list):
            for item in contents:
                if not isinstance(item, dict) or str(item.get("type") or "") != "text":
                    continue
                for line in str(item.get("text") or "").splitlines():
                    cleaned = re.sub(r"[`*_#>\-]+", " ", line).strip()
                    if len(cleaned) >= 18:
                        signals.append(cleaned[:80])
                        break
                if signals:
                    break
        title = str(metadata.get("title") or "").strip()
        if title:
            signals.append(title)
        return signals or [package_path.stem]


    def upload_moodle_chapter(self,
        course_dir: Path,
        chapter: str,
        course_url: str | None = None,
        section: str | None = None,
        username: str | None = None,
        password: str | None = None,
        storage_state: Path | None = None,
        headless: bool = False,
        timeout_ms: int = 30_000,
        target: str | None = None,
        verify_mbz_sync: bool = False,
        skip_sync: bool = False,
        verify_remote: bool = False,
        local_hashes: dict[str, str] | None = None,
    ) -> list[MoodleH5PUploadResult]:
        self.application.moodle_client_resolver().load_dotenv_file()
        if target is None:
            target = self.application._infer_target_from_course_url(course_dir, course_url)
        if not skip_sync:
            self.application.sync_course(course_dir)
        packages = self.application.collect_h5p_upload_packages(course_dir, chapter)
        # Hashes jetzt festhalten, nicht erst nach dem Upload: Der Upload dauert, und was
        # der Nutzer in der Zwischenzeit aendert, liegt nicht auf der Plattform.
        if local_hashes is None:
            local_hashes = self.application._current_question_hashes(
                course_dir, {package.identifier for package in packages}
            )
        text_labels = self.application.collect_moodle_text_labels(course_dir, chapter)
        metadata = self.application._SYNC_METADATA_STORE.load(course_dir)
        existing_activity_ids: dict[str, int] = {}
        if not target:
            existing_activity_ids.update(
                {
                    identifier: entry.remote_activity_id
                    for identifier, entry in (metadata.entries.items() if metadata is not None else [])
                    if entry.remote_activity_id
                }
            )
        if target:
            existing_activity_ids.update(self.application._load_target_activity_ids(course_dir, target))
        target_config = self.application._load_target_config(course_dir, target) if target else {}
        secret_replacements = self._secret_replacements(course_dir, target)
        if secret_replacements:
            # Ziel behaelt die Kurs-Secrets nicht: Pakete und Text-Labels ohne Secrets hochladen.
            packages = self._sanitize_packages_for_target(course_dir, chapter, packages, secret_replacements, target)
            text_labels = self._sanitize_text_labels(text_labels, secret_replacements)
            print(
                f"Secrets werden fuer Ziel '{target or 'default'}' ersetzt ({len(secret_replacements)} Eintraege).",
                flush=True,
            )
        use_credentials = self.application._target_auth_uses_credentials(target_config)
        resolved_course_url = self.application._resolve_moodle_course_url(course_dir, course_url, target)
        existing_activity_ids.update(self.application._load_existing_h5p_activity_ids_from_moodle(course_dir, resolved_course_url, packages))
        resolved_section = section or self.application._chapter_title_from_index(course_dir, chapter)
        target_storage_state = (
            Path(self.application._target_env_value(course_dir, target, "STORAGE_STATE", "MOODLE_STORAGE_STATE")).expanduser()
            if self.application._target_env_value(course_dir, target, "STORAGE_STATE", "MOODLE_STORAGE_STATE")
            else None
        )
        resolved_storage_state = storage_state or target_storage_state or (
            course_dir / (f".moodle-storage-state-{target}.json" if target else ".moodle-storage-state.json")
        )

        uploader = self.application.MoodlePlaywrightUploader(
            course_url=resolved_course_url,
            section_title=resolved_section,
            username=username or (self.application._target_env_value(course_dir, target, "USERNAME", "MOODLE_USERNAME") if use_credentials else None),
            password=password or (self.application._target_env_value(course_dir, target, "PASSWORD", "MOODLE_PASSWORD") if use_credentials else None),
            storage_state=resolved_storage_state,
            existing_activity_ids=existing_activity_ids,
            headless=headless,
            timeout_ms=timeout_ms,
        )
        before_backup = self.application._download_course_backup_snapshot(course_dir, resolved_course_url, "before") if verify_mbz_sync else None
        if self.application._chapter_hidden_from_index(course_dir, chapter):
            # Vor dem Upload verbergen, damit Lernende die Section nie sichtbar sehen.
            uploader.ensure_section_hidden()
        else:
            # Eine zuvor verborgene Section darf nicht verborgen bleiben, nur weil sie es
            # in einem frueheren Sync einmal war.
            uploader.ensure_section_visible()
        results = uploader.upload_packages(packages)
        anchor_activity_ids = dict(existing_activity_ids)
        for result in results:
            if result.activity_id:
                anchor_activity_ids[result.identifier] = result.activity_id
                anchor_activity_ids[normalize_moodle_identifier(result.identifier)] = result.activity_id
                anchor_activity_ids[normalize_moodle_identifier(result.title)] = result.activity_id
        if hasattr(uploader, "sync_text_labels"):
            uploader.sync_text_labels(text_labels, anchor_activity_ids=anchor_activity_ids, chapter=chapter)
        if verify_mbz_sync and before_backup is not None:
            after_backup = self.application._download_course_backup_snapshot(course_dir, resolved_course_url, "after")
            analysis = self.application.moodle_backup_diff_analyzer().analyze(before_backup, after_backup)
            print(self.application.moodle_backup_diff_analyzer().format_report(analysis), flush=True)
        if not target:
            self.application._store_uploaded_activity_ids(course_dir, results, local_hashes)
        if target:
            self.application._store_target_activity_ids(course_dir, target, results, local_hashes)
        if verify_remote:
            verification = self.application.verify_moodle_course(
                course_dir,
                course_url=resolved_course_url,
                username=username,
                password=password,
                storage_state=resolved_storage_state,
                headless=headless,
                timeout_ms=timeout_ms,
                target=target,
            )
            failed = [item for item in verification if not bool(item.get("ok"))]
            if failed:
                raise RuntimeError(f"Remote-Verifikation fehlgeschlagen: {len(failed)} Aktivitäten.")
        return results


    def upload_moodle_course(self,
        course_dir: Path,
        course_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        storage_state: Path | None = None,
        headless: bool = False,
        timeout_ms: int = 30_000,
        target: str | None = None,
        verify_mbz_sync: bool = False,
        prune_extra_sections: bool = False,
        verify_remote: bool = False,
    ) -> list[MoodleH5PUploadResult | MoodleSectionCleanupResult]:
        self.application.sync_course(course_dir)
        local_hashes = self.application._current_question_hashes(course_dir)
        full_chapter_plan = self.application._course_chapter_plan(course_dir)
        synced_chapter_plan = [chapter for chapter in full_chapter_plan if chapter.synced]
        skipped_chapters = [chapter for chapter in full_chapter_plan if not chapter.synced]
        if skipped_chapters:
            print(
                "Ueberspringe nicht synchronisierte Kapitel (synced=false): "
                + ", ".join(chapter.slug for chapter in skipped_chapters),
                flush=True,
            )
        results: list[MoodleH5PUploadResult | MoodleSectionCleanupResult] = []
        for chapter in synced_chapter_plan:
            results.extend(
                self.application.upload_moodle_chapter(
                    course_dir=course_dir,
                    chapter=chapter.slug,
                    course_url=course_url,
                    section=chapter.title,
                    username=username,
                    password=password,
                    storage_state=storage_state,
                    headless=headless,
                    timeout_ms=timeout_ms,
                    target=target,
                    verify_mbz_sync=verify_mbz_sync,
                    skip_sync=True,
                    verify_remote=False,
                    local_hashes=local_hashes,
                )
            )

        self.application.moodle_client_resolver().load_dotenv_file()
        target_config = self.application._load_target_config(course_dir, target) if target else {}
        use_credentials = self.application._target_auth_uses_credentials(target_config)
        resolved_course_url = self.application._resolve_moodle_course_url(course_dir, course_url, target)
        target_storage_state = (
            Path(self.application._target_env_value(course_dir, target, "STORAGE_STATE", "MOODLE_STORAGE_STATE")).expanduser()
            if self.application._target_env_value(course_dir, target, "STORAGE_STATE", "MOODLE_STORAGE_STATE")
            else None
        )
        resolved_storage_state = storage_state or target_storage_state or (
            course_dir / (f".moodle-storage-state-{target}.json" if target else ".moodle-storage-state.json")
        )
        if prune_extra_sections and target:
            self.application._delete_stale_target_activities(
                course_dir,
                target,
                current_identifiers=set(local_hashes),
                course_url=resolved_course_url,
                username=username or (self.application._target_env_value(course_dir, target, "USERNAME", "MOODLE_USERNAME") if use_credentials else None),
                password=password or (self.application._target_env_value(course_dir, target, "PASSWORD", "MOODLE_PASSWORD") if use_credentials else None),
                storage_state=resolved_storage_state,
                headless=headless,
                timeout_ms=timeout_ms,
            )
        cleanup_results = self.application.MoodlePlaywrightUploader(
            course_url=resolved_course_url,
            section_title="",
            username=username or (self.application._target_env_value(course_dir, target, "USERNAME", "MOODLE_USERNAME") if use_credentials else None),
            password=password or (self.application._target_env_value(course_dir, target, "PASSWORD", "MOODLE_PASSWORD") if use_credentials else None),
            storage_state=resolved_storage_state,
            headless=headless,
            timeout_ms=timeout_ms,
        ).reconcile_course_sections(
            desired_section_titles=[chapter.title for chapter in full_chapter_plan],
            prune_extra_sections=prune_extra_sections,
        )
        results.extend(cleanup_results)
        if verify_remote:
            verification = self.application.verify_moodle_course(
                course_dir,
                course_url=resolved_course_url,
                username=username,
                password=password,
                storage_state=resolved_storage_state,
                headless=headless,
                timeout_ms=timeout_ms,
                target=target,
            )
            failed = [item for item in verification if not bool(item.get("ok"))]
            if failed:
                raise RuntimeError(f"Remote-Verifikation fehlgeschlagen: {len(failed)} Aktivitäten.")
        return results


    def audit_course(self, course_dir: Path) -> dict[str, object]:
        questions = self.application.sync_course(course_dir)
        question_ids = {question.identifier for question in questions}
        issues: list[dict[str, object]] = []
        checks = 0
        build_dir = self.application.course_build_dir(course_dir)

        for chapter in self.application._course_chapter_plan(course_dir):
            chapter_path = self.application._chapter_path_for_slug(course_dir, chapter.slug)
            if chapter_path.exists():
                source = chapter_path.read_text(encoding="utf-8")
                for pattern, message in [
                    (r"\bdetect_actors\s*\(", "Möglicherweise falsche miniworlds-API: nutze detect(...) für einzelne Actors."),
                    (r"\bCircle\s*\(\s*self\.mouse_x\s*,", "Circle-Aufruf braucht eine Positions-Tupel-Form: miniworlds.Circle((x, y), r)."),
                    (r"direction\s*=\s*['\"](?:right|left|up|down)['\"]", "Richtungen sollten in den Beispielen numerisch oder erklärt verwendet werden."),
                ]:
                    checks += 1
                    if re.search(pattern, source):
                        issues.append({"severity": "warning", "path": str(chapter_path), "message": message})

        for package_path in sorted((build_dir / "h5p").glob("*/*.h5p")):
            checks += 1
            try:
                with ZipFile(package_path) as archive:
                    metadata = json.loads(archive.read("h5p.json").decode("utf-8"))
                    content = json.loads(archive.read("content/content.json").decode("utf-8"))
            except Exception as error:
                issues.append({"severity": "error", "path": str(package_path), "message": f"H5P-Paket ist nicht lesbar: {error}"})
                continue

            identifier = package_path.stem
            if identifier not in question_ids:
                issues.append({"severity": "warning", "path": str(package_path), "message": "Paket ist gebaut, aber nicht im Kurs referenziert."})

            if str(metadata.get("mainLibrary") or "") == "H5P.PythonQuestion":
                editor = content.get("editorSettings") if isinstance(content, dict) else {}
                editor = editor if isinstance(editor, dict) else {}
                instructions = str(editor.get("instructions") or "").strip()
                visible_text = instructions
                contents = content.get("contents")
                if not visible_text and isinstance(contents, list):
                    visible_text = "\n".join(
                        str(item.get("text") or "").strip()
                        for item in contents
                        if isinstance(item, dict) and str(item.get("type") or "") == "text"
                    ).strip()
                starting_code = str(editor.get("startingCode") or "").strip()
                content_type = str(content.get("contentType") or "")
                if content_type in {"ide_only", "text_and_ide", "text_only"} and not visible_text:
                    issues.append({"severity": "error", "path": str(package_path), "message": "PythonQuestion enthält keine sichtbaren Instructions."})
                if content_type in {"ide_only", "text_and_ide"} and not starting_code:
                    issues.append({"severity": "warning", "path": str(package_path), "message": "IDE-Aktivität enthält keinen Startcode."})
                runner = str(content.get("pythonRunner") or "")
                packages = content.get("pyodideOptions", {}).get("packages", []) if isinstance(content.get("pyodideOptions"), dict) else []
                content_blob = json.dumps(content, ensure_ascii=False)
                executes_code = content_type in {"ide_only", "text_and_ide"}
                if executes_code and "import miniworlds" in content_blob:
                    if runner != "pyodide":
                        issues.append({"severity": "error", "path": str(package_path), "message": "miniworlds-Aktivität sollte pythonRunner=pyodide nutzen."})
                    if not contains_miniworlds_package(packages):
                        issues.append({"severity": "error", "path": str(package_path), "message": "miniworlds wird importiert, fehlt aber in pyodideOptions.packages."})

                grading_settings = content.get("gradingSettings") if isinstance(content, dict) else {}
                grading_settings = grading_settings if isinstance(grading_settings, dict) else {}
                if str(grading_settings.get("gradingMethod") or "") == "multipleChoice":
                    multiple_choice = grading_settings.get("multipleChoice")
                    multiple_choice = multiple_choice if isinstance(multiple_choice, dict) else {}
                    choices = multiple_choice.get("choices")
                    choices = choices if isinstance(choices, list) else []
                    if len(choices) < 2:
                        issues.append({"severity": "error", "path": str(package_path), "message": "Multiple-Choice-Aufgabe hat weniger als zwei Antwortoptionen."})
                    correct_count = sum(1 for choice in choices if isinstance(choice, dict) and choice.get("correct") is True)
                    empty_texts = sum(1 for choice in choices if not isinstance(choice, dict) or not str(choice.get("text") or "").strip())
                    if empty_texts:
                        issues.append({"severity": "error", "path": str(package_path), "message": "Multiple-Choice-Aufgabe enthält eine Antwortoption ohne Text."})
                    if correct_count == 0:
                        issues.append({"severity": "error", "path": str(package_path), "message": "Multiple-Choice-Aufgabe hat keine richtige Antwortoption."})
                    if not multiple_choice.get("allowMultiple") and correct_count > 1:
                        issues.append({"severity": "error", "path": str(package_path), "message": "Multiple-Choice-Aufgabe erlaubt nur eine Antwort, hat aber mehrere korrekte Optionen."})

        hashes_dir = build_dir / "hashes"
        hash_files = {path.relative_to(hashes_dir) for path in hashes_dir.glob("**/*.build-hash")}
        expected_hashes = {
            (Path(question.h5p_subdir) / f"{question.identifier}.build-hash") if question.h5p_subdir else Path(f"{question.identifier}.build-hash")
            for question in questions
        }
        stale_hashes = hash_files - expected_hashes
        checks += len(hash_files)
        for stale in sorted(stale_hashes):
            issues.append({"severity": "warning", "path": str(hashes_dir / stale), "message": "Veraltete Build-Hash-Datei."})

        errors = sum(1 for issue in issues if issue.get("severity") == "error")
        warnings = sum(1 for issue in issues if issue.get("severity") != "error")
        return {"course": course_dir.name, "checks": checks, "errors": errors, "warnings": warnings, "issues": issues}


    def verify_moodle_course(self,
        course_dir: Path,
        course_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        storage_state: Path | None = None,
        headless: bool = False,
        timeout_ms: int = 30_000,
        target: str | None = None,
        missing_ids_only: bool = False,
    ) -> list[dict[str, object]]:
        if missing_ids_only and not target:
            raise ValueError("--missing-ids-only benoetigt ein benanntes --target.")
        self.application.moodle_client_resolver().load_dotenv_file()
        self.application.sync_course(course_dir)
        resolved_course_url = self.application._resolve_moodle_course_url(course_dir, course_url, target)
        resolved_storage_state = self.application._resolve_moodle_storage_state(course_dir, storage_state, target)
        target_config = self.application._load_target_config(course_dir, target) if target else {}
        use_credentials = self.application._target_auth_uses_credentials(target_config)
        resolved_username = username or (self.application._target_env_value(course_dir, target, "USERNAME", "MOODLE_USERNAME") if use_credentials else None)
        resolved_password = password or (self.application._target_env_value(course_dir, target, "PASSWORD", "MOODLE_PASSWORD") if use_credentials else None)
        expected = self.application._remote_verification_expectations(course_dir, target)

        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "Playwright ist nicht installiert. Installiere zuerst: "
                "python -m pip install -r requirements.txt && python -m playwright install chromium"
            ) from error

        uploader = self.application.MoodlePlaywrightUploader(
            course_url=resolved_course_url,
            username=resolved_username,
            password=resolved_password,
            storage_state=resolved_storage_state,
            headless=headless,
            timeout_ms=timeout_ms,
        )
        results: list[dict[str, object]] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context_kwargs: dict[str, Any] = {}
            if resolved_storage_state and resolved_storage_state.exists():
                context_kwargs["storage_state"] = str(resolved_storage_state)
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(resolved_course_url, wait_until="domcontentloaded")
            uploader._login_if_needed(page)
            uploader._wait_for_manual_login_confirmation(page)
            uploader._return_to_course_after_login(page)
            recovered = {}
            content_only_recovered = set()
            if target and any(not item.get("activityId") for item in expected):
                activities = uploader._collect_section_h5p_activity_order(page, "body")
                # Moodle can show the course as a list of section links without activities.
                section_urls = page.evaluate("""() => [...new Set([...document.querySelectorAll('a[href]')]
                    .map(a => a.href).filter(href => {
                        const url = new URL(href);
                        const current = new URL(window.location.href);
                        return url.origin === current.origin && (
                            url.pathname.endsWith('/course/section.php') && url.searchParams.has('id') ||
                            url.pathname.endsWith('/course/view.php') &&
                            url.searchParams.get('id') === current.searchParams.get('id') &&
                            url.searchParams.has('section'));
                    }))]""")
                print(f"Pruefe {len(section_urls)} verlinkte Kapitelansichten ({urlparse(page.url).path}).", flush=True)
                for section_url in section_urls:
                    page.goto(section_url, wait_until="domcontentloaded")
                    activities.extend(uploader._collect_section_h5p_activity_order(page, "body"))
                activities = list({(item["id"], item["title"]): item for item in activities}.values())
                recovered = self._recover_verification_ids(expected, activities)
                unresolved = [item for item in expected if not item.get("activityId") and str(item["identifier"]) not in recovered]
                known_ids = set(self.application._load_target_activity_ids(course_dir, target).values()) | set(recovered.values())
                unassigned = {int(item["id"]) for item in activities} - known_ids
                # A renamed last activity needs content or its title confirmed inside H5P.
                if len(unresolved) == len(unassigned) == 1:
                    identifier = str(unresolved[0]["identifier"])
                    recovered[identifier] = next(iter(unassigned))
                    content_only_recovered.add(identifier)
                print(f"Remote-Inventar: {len(activities)} H5P-Aktivitaeten, {len(recovered)} eindeutige ID-Kandidaten.", flush=True)
            confirmed = {}
            for item in expected:
                if missing_ids_only and item.get("activityId"):
                    continue
                identifier = str(item["identifier"])
                activity_id = int(item.get("activityId") or recovered.get(identifier) or 0)
                signals = [str(signal) for signal in item.get("signals", []) if str(signal).strip()]
                if activity_id <= 0:
                    results.append({"identifier": identifier, "activityId": activity_id, "ok": False, "message": "Keine Remote-Activity-ID bekannt."})
                    continue
                page.goto(f"{self.application._moodle_base_url(resolved_course_url)}/mod/h5pactivity/view.php?id={activity_id}", wait_until="domcontentloaded")
                page.wait_for_timeout(4_000)
                frame_texts: list[str] = []
                for frame in page.frames:
                    if frame == page.main_frame:
                        continue
                    try:
                        frame_texts.append(frame.locator("body").inner_text(timeout=1_500))
                    except Exception:
                        pass
                combined = "\n".join(frame_texts)
                remote_contents = []
                for frame in page.frames:
                    try:
                        payloads = frame.evaluate("""() => Object.values(window.H5PIntegration?.contents || {})
                            .map(item => item.jsonContent).filter(Boolean)""")
                        for payload in payloads:
                            remote_contents.append(json.loads(payload) if isinstance(payload, str) else payload)
                    except Exception:
                        pass
                local_content = None
                if item.get("packagePath"):
                    with ZipFile(str(item["packagePath"])) as archive:
                        local_content = json.loads(archive.read("content/content.json"))
                content_equal = local_content is not None and local_content in remote_contents
                searchable = combined + "\n" + "\n".join(json.dumps(content, ensure_ascii=False) for content in remote_contents)
                normalized_searchable = _normalize_verification_text(searchable)
                matched = [signal for signal in signals if (
                    _normalize_verification_text(signal)
                    and _normalize_verification_text(signal) in normalized_searchable
                )]
                normalized_title = normalize_moodle_identifier(re.sub(r"^test:\s*", "", str(item.get("title") or "").strip(), flags=re.IGNORECASE))
                title_in_content = bool(normalized_title) and f"-{normalized_title}-" in f"-{normalize_moodle_identifier(combined)}-"
                ok = content_equal or (bool(matched) and (identifier not in content_only_recovered or title_in_content))
                message = "H5P-Inhalt stimmt vollstaendig ueberein." if content_equal else (
                    f"matched={matched[0]}" if matched else "Kein erwartetes Textsignal im H5P-Inhalt gefunden.")
                identity_confirmed = ok
                if not ok and identifier in recovered and identifier not in content_only_recovered and combined.strip():
                    try:
                        headings = page.locator("h1, h2").all_text_contents()
                        title_key = lambda value: normalize_moodle_identifier(re.sub(r"^test:\s*", "", value.strip(), flags=re.IGNORECASE))
                        expected_title = title_key(str(item.get("title") or ""))
                        identity_confirmed = bool(expected_title) and any(title_key(heading) == expected_title for heading in headings)
                    except Exception:
                        pass
                if identity_confirmed and identifier in recovered:
                    confirmed[identifier] = activity_id
                    message += "; Remote-ID bestaetigt" + (" und Inhalt geprueft" if ok else "; Inhaltsstand nicht bestaetigt")
                print(f"{'OK' if ok else 'FEHLER'}: {identifier} (ID {activity_id})", flush=True)
                results.append({"identifier": identifier, "activityId": activity_id, "ok": ok, "message": message, "chars": len(combined), "contentEqual": content_equal})
            if target and confirmed:
                # A presence check does not prove an upload of the current local revision.
                # Preserve existing hashes and do not invent a sync timestamp or content hash.
                activity_ids = self.application._load_target_activity_ids(course_dir, target)
                activity_ids.update(confirmed)
                atomic_write_text(self.application._target_activity_ids_path(course_dir, target), json.dumps(activity_ids, indent=2, ensure_ascii=False) + "\n")
                print(f"{len(confirmed)} bestaetigte Remote-IDs lokal ergaenzt.", flush=True)
            if resolved_storage_state:
                resolved_storage_state.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(resolved_storage_state))
            context.close()
            browser.close()
        return results


    def _download_course_backup_snapshot(self, course_dir: Path, course_url: str, label: str) -> Path:
        parsed = urlparse(course_url)
        course_id = int(parse_qs(parsed.query).get("id", ["0"])[0])
        if course_id <= 0:
            raise RuntimeError(f"Moodle-Kurs-ID fehlt in Kurs-URL: {course_url}")
        base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
        if not base_url:
            raise RuntimeError(f"Moodle-Basis-URL konnte nicht aus Kurs-URL gelesen werden: {course_url}")

        backup_url = self.application.moodle_backup_extractor().discover_course_backup_url(base_url, course_id, course_url)
        if not backup_url:
            raise RuntimeError(
                "Kein Moodle-.mbz-Backup-Link im Kurs gefunden. "
                "Lege vor dem verifizierten Sync ein Kursbackup mit allen Aktivitäten an oder führe ohne --verify-mbz-sync aus."
            )

        backups_dir = self.application.course_build_dir(course_dir) / "moodle-backups"
        self.application.ensure_directory(backups_dir)
        existing_count = len(list(backups_dir.glob(f"{label}-*.mbz")))
        destination = backups_dir / f"{label}-{existing_count + 1:03d}.mbz"
        print(f"Lade Moodle-MBZ-Snapshot ({label}): {backup_url}", flush=True)
        self.application.download_file(backup_url, destination)
        return destination


    def _load_existing_h5p_activity_ids_from_moodle(self,
        course_dir: Path,
        course_url: str,
        packages: list[object],
    ) -> dict[str, int]:
        try:
            course_id = int(parse_qs(urlparse(course_url).query).get("id", ["0"])[0])
        except (TypeError, ValueError):
            return {}
        if course_id <= 0:
            return {}

        identifier_lookup: dict[str, str] = {}
        title_lookup: dict[str, set[str]] = {}
        for package in packages:
            identifier = str(getattr(package, "identifier", "") or "")
            title = str(getattr(package, "title", "") or "")
            if identifier:
                identifier_lookup[normalize_moodle_identifier(identifier)] = identifier
            if title:
                key = normalize_moodle_identifier(title)
                title_lookup.setdefault(key, set()).add(identifier)

        if not identifier_lookup and not title_lookup:
            return {}

        try:
            client = self.application.resolve_moodle_client()
            activities = client.list_course_h5p_activities(course_id)
        except Exception:
            return {}

        result: dict[str, int] = {}
        for activity in activities:
            remote_id = int(getattr(activity, "activity_id", 0) or 0)
            title = str(getattr(activity, "title", "") or "")
            key = normalize_moodle_identifier(title)
            identifier = identifier_lookup.get(key)
            if identifier is None:
                candidates = title_lookup.get(key, set())
                if len(candidates) == 1:
                    identifier = next(iter(candidates))
            if identifier and remote_id:
                result[identifier] = remote_id
        return result


    def _delete_stale_target_activities(
        self,
        course_dir: Path,
        target: str,
        *,
        current_identifiers: set[str],
        course_url: str,
        username: str | None,
        password: str | None,
        storage_state: Path | None,
        headless: bool,
        timeout_ms: int,
    ) -> list[int]:
        """Loescht Aktivitaeten, die lokal nicht mehr vorkommen, aber auf dem Ziel angelegt wurden.

        Grundlage ist ausschliesslich die lokale ID-Zuordnung des Ziels: Nur Aktivitaeten, die
        course-sync selbst angelegt hat und deren Bezeichner im Kurs nicht mehr vorkommt,
        werden entfernt. Fremde Aktivitaeten bleiben unberuehrt.
        """
        import json
        if not current_identifiers:
            return []
        known = self.application._load_target_activity_ids(course_dir, target)
        current_ids = {activity_id for key, activity_id in known.items() if key in current_identifiers}
        stale = {key: activity_id for key, activity_id in known.items()
                 if key not in current_identifiers and activity_id not in current_ids}
        if not stale:
            print("Keine veralteten H5P-Aktivitaeten zu loeschen.", flush=True)
            return []
        print("Veraltete H5P-Aktivitaeten: " + ", ".join(f"{key} ({value})" for key, value in sorted(stale.items())), flush=True)
        deleted = self.application.MoodlePlaywrightUploader(
            course_url=course_url,
            section_title="",
            username=username,
            password=password,
            storage_state=storage_state,
            headless=headless,
            timeout_ms=timeout_ms,
        ).delete_h5p_activities(sorted(set(stale.values())))
        gone = {key for key, activity_id in stale.items() if activity_id in set(deleted)}
        if gone:
            remaining = {key: value for key, value in known.items() if key not in gone}
            atomic_write_text(
                self.application._target_activity_ids_path(course_dir, target),
                json.dumps(remaining, indent=2, ensure_ascii=False) + "\n",
            )
            try:
                from .classes.platform_sync_state import forget_target_sync_state
                forget_target_sync_state(course_dir, target, gone)
            except Exception as error:  # noqa: BLE001 - Zustandsdatei ist optional
                print(f"Hinweis: Sync-Stand nicht bereinigt: {error}", flush=True)
        return deleted


    def _target_activity_ids_path(self, course_dir: Path, target: str) -> Path:
        return course_dir / f".moodle-activity-ids-{target}.json"


    def _load_target_activity_ids(self, course_dir: Path, target: str) -> dict[str, int]:
        import json
        path = self.application._target_activity_ids_path(course_dir, target)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {str(k): int(v) for k, v in raw.items() if v}
        except Exception:
            return {}


    def _store_target_activity_ids(
        self,
        course_dir: Path,
        target: str,
        results: list[MoodleH5PUploadResult],
        local_hashes: dict[str, str] | None = None,
    ) -> None:
        import json
        path = self.application._target_activity_ids_path(course_dir, target)
        existing = self.application._load_target_activity_ids(course_dir, target)
        for result in results:
            if result.activity_id:
                existing[result.identifier] = result.activity_id
        atomic_write_text(path, json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
        self.application._record_target_sync_state(course_dir, target, results, local_hashes)


    def _current_question_hashes(self, course_dir: Path, identifiers: set[str] | None = None) -> dict[str, str]:
        """Inhalts-Hash der Aktivitaeten im aktuellen lokalen Stand (leer, wenn nicht bestimmbar).

        Reiner Zustand fuer die Sync-Uebersicht: Ein Fehler hier darf einen Upload weder
        verhindern noch nachtraeglich scheitern lassen.
        """
        try:
            _, questions, _ = self.application.parse_course(course_dir)
            return {
                question.identifier: self.application.compute_question_hash(question)
                for question in questions
                if identifiers is None or question.identifier in identifiers
            }
        except Exception as error:  # noqa: BLE001 - Zustandsdatei ist optional
            print(f"Hinweis: Inhalts-Hashes fuer den Sync-Stand nicht bestimmbar: {error}", flush=True)
            return {}


    def _record_target_sync_state(
        self,
        course_dir: Path,
        target: str,
        results: list[MoodleH5PUploadResult],
        local_hashes: dict[str, str] | None = None,
    ) -> None:
        """Haelt fest, mit welchem Inhalts-Hash die Aktivitaeten auf dem Ziel liegen."""
        uploaded = {result.identifier for result in results if result.activity_id}
        if not uploaded:
            return
        if local_hashes is None:
            local_hashes = self.application._current_question_hashes(course_dir, uploaded)
        try:
            record_target_sync_state(
                course_dir, target, {identifier: local_hashes.get(identifier, "") for identifier in uploaded}
            )
        except Exception as error:  # noqa: BLE001 - Zustandsdatei ist optional
            print(f"Hinweis: Sync-Stand fuer Ziel '{target}' konnte nicht gespeichert werden: {error}", flush=True)


    def _store_uploaded_activity_ids(
        self,
        course_dir: Path,
        results: list[MoodleH5PUploadResult],
        local_hashes: dict[str, str] | None = None,
    ) -> None:
        metadata = self.application._SYNC_METADATA_STORE.load(course_dir)
        if metadata is None:
            return
        if local_hashes is None:
            local_hashes = self.application._current_question_hashes(
                course_dir, {result.identifier for result in results if result.activity_id}
            )
        base_url = metadata.moodle_base_url.rstrip("/")
        changed = False
        for result in results:
            if not result.activity_id:
                continue
            local_hash = local_hashes.get(result.identifier, "")
            remote_url = f"{base_url}/mod/h5pactivity/view.php?id={result.activity_id}" if base_url else ""
            entry = metadata.entries.get(result.identifier)
            if entry is None:
                entry = SyncMetadataEntry(
                    identifier=result.identifier,
                    remote_activity_id=result.activity_id,
                    remote_instance_id=None,
                    remote_title=result.title,
                    remote_url=remote_url,
                    remote_visible=True,
                    local_hash=local_hash,
                    remote_hash=local_hash,
                    status="tracked",
                )
                metadata.entries[result.identifier] = entry
                changed = True
                continue
            if entry.remote_activity_id != result.activity_id:
                entry.remote_activity_id = result.activity_id
                changed = True
            if entry.remote_title != result.title:
                entry.remote_title = result.title
                changed = True
            if remote_url and entry.remote_url != remote_url:
                entry.remote_url = remote_url
                changed = True
            if local_hash and entry.local_hash != local_hash:
                entry.local_hash = local_hash
                changed = True
            if local_hash and entry.remote_hash != local_hash:
                entry.remote_hash = local_hash
                changed = True
            if entry.status != "tracked":
                entry.status = "tracked"
                changed = True
            if not entry.remote_visible:
                entry.remote_visible = True
                changed = True
        if changed:
            self.application._SYNC_METADATA_STORE.save(course_dir, metadata)
