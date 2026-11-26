from __future__ import annotations

import html
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, NamedTuple
from urllib.parse import parse_qs, urlparse
from zipfile import ZipFile

from course_sync._http_client import (
    download_file,
    extract_h5p_package_url_from_activity_html,
    fetch_json,
    fetch_text,
)

from course_sync.classes import (
    CourseOrchestrator,
    ContentStore,
    H5PFileService,
    H5PImportMapper,
    H5PLibraryManager,
    H5PPackageBuilder,
    MarkdownRenderer,
    MdxCourseParser,
    MoodleH5PActivity,
    PreviewController,
    PreviewViewBuilder,
    CourseActivity,
    RuntimeCliService,
    RuntimePreparationService,
    RuntimeHtmlRewriter,
    SourceFile,
    SyncMetadata,
    SyncMetadataEntry,
    TemplateRenderer,
    TestCase,
    TextOperations,
)
from course_sync.classes.cli import (
    build_arg_parser as build_cli_arg_parser,
    print_course_status as print_cli_course_status,
    print_moodle_ping_report as print_cli_moodle_ping_report,
    run_cli_command,
    serve_preview as serve_preview_impl,
)
from course_sync.classes.cli.runner import list_course_chapters
from course_sync.classes.component_sync import ComponentSyncer
from course_sync.classes.content_types import ImportedQuestionFactory
from course_sync.classes.sync_metadata_store import SyncMetadataStore
from course_sync.classes.workspace_io import WorkspaceIO
from course_sync.config import AppConfig, settings
from course_sync.classes.h5p_runtime_manager import quote_path_segment as quote_path_segment_helper
from course_sync.classes.h5p_runtime_manager.runtime_manager import H5PRuntimeManager
from course_sync.classes.moodle_sync import MoodleSyncer
from course_sync.classes.moodle_sync import MoodleApiClient
from course_sync.classes.moodle_sync import MoodleBackupDiffAnalyzer
from course_sync.classes.moodle_sync import MoodleBackupExtractor
from course_sync.classes.moodle_sync import MoodleBackupImporter
from course_sync.classes.moodle_sync import MoodleClientResolver
from course_sync.classes.python_runner_policy import contains_miniworlds_package
from course_sync.classes.moodle_playwright_uploader import (
    MoodleH5PUploadPackage,
    MoodleH5PUploadResult,
    MoodlePlaywrightUploader,
    MoodleSectionCleanupResult,
    collect_h5p_upload_packages as _collect_h5p_upload_packages,
    collect_moodle_text_labels,
    normalize_moodle_identifier,
)
from course_sync._services import application_service
from course_sync.site_export import StaticSiteExporter
from course_sync.moodle_workflows import ChapterPlanItem, MoodleWorkflows


class CourseApplication:
    def __init__(self, config: AppConfig | None = None) -> None:
        config = deepcopy(config if config is not None else settings.build_app_config())
        self.APP_CONFIG = config
        self.ROOT_DIR = self.APP_CONFIG.root_dir
        self.COURSES_DIR = self.APP_CONFIG.courses_dir
        self.COURSE_BUILD_DIR = self.APP_CONFIG.course_build_dir
        self.DEFAULT_PORT = self.APP_CONFIG.default_port
        self.DOTENV_FILE = self.APP_CONFIG.dotenv_file
        self.H5P_RUNTIME_DIR = self.APP_CONFIG.h5p_runtime_dir
        self.H5P_RUNTIME_CONTENT_DIR = self.APP_CONFIG.h5p_runtime_content_dir
        self.H5P_RUNTIME_LIBRARIES_DIR = self.APP_CONFIG.h5p_runtime_libraries_dir
        self.H5P_RUNTIME_DOWNLOADS_DIR = self.APP_CONFIG.h5p_runtime_downloads_dir
        self.H5P_RUNTIME_PORT = self.APP_CONFIG.h5p_runtime_port
        self.RUNTIME_PROXY_PREFIX = self.APP_CONFIG.runtime_proxy_prefix
        self.H5P_LIBRARY_RELEASE_REPO = self.APP_CONFIG.h5p_library_release_repo
        self.H5P_LIBRARY_RELEASE_TAG = self.APP_CONFIG.h5p_library_release_tag
        self.H5P_LIBRARY_ASSET_PREFIXES = self.APP_CONFIG.h5p_library_asset_prefixes
        self.H5P_LIBRARY_EXTRA_ASSETS = self.APP_CONFIG.h5p_library_extra_assets
        self.CUSTOM_H5P_LIBRARY_SHORT_NAMES = self.APP_CONFIG.custom_h5p_library_short_names
        self.PYTHON_QUESTION_MACHINE_NAME = self.APP_CONFIG.python_question_machine_name
        self.PLACEHOLDER_TEMPLATE = self.APP_CONFIG.placeholder_template
        self.SYNC_METADATA_FILE = self.APP_CONFIG.sync_metadata_file
        self.H5P_SIDECAR_DIRNAME = self.APP_CONFIG.h5p_sidecar_dirname
        self.WORKSPACE_LOCK = threading.RLock()
        self.PREVIEW_CACHE: dict[str, tuple[str, list[CourseActivity], str]] = {}
        self.H5P_RUNTIME_LIBRARIES_READY = False
        self.MINIWORLDS_ROBOT_WHEEL_NAME = "miniworlds_robot-0.1.1-py3-none-any.whl"
        self.MINIWORLDS_ROBOT_WHEEL_QUERY = "v=20260703-pyodide"
        self.MINIWORLDS_ROBOT_WHEEL_URL = f"/wheels/{self.MINIWORLDS_ROBOT_WHEEL_NAME}?{self.MINIWORLDS_ROBOT_WHEEL_QUERY}"
        self.PYTHON_QUESTION_ROBOT_RESOLVER_NEEDLE = (
            'const t=Ce,n=t.miniworldsWheelPromises.get(e);if(n)return n;'
            'const i=xe(`resolve:${e}`,(async()=>{var t,n;if("undefined"==typeof window||'
            '"function"!=typeof window.fetch)throw new Error("The browser cannot resolve '
            'the Miniworlds package.");'
        )
        self.PYTHON_QUESTION_ROBOT_RESOLVER_REPLACEMENT = (
            'const t=Ce,n=t.miniworldsWheelPromises.get(e);if(n)return n;'
            'if("miniworlds-robot"===e){const o=Promise.resolve("undefined"!=typeof window&&'
            f'window.location?new URL("{self.MINIWORLDS_ROBOT_WHEEL_URL}",window.location.href).toString():'
            f'"{self.MINIWORLDS_ROBOT_WHEEL_URL}");return t.miniworldsWheelPromises.set(e,o),o}}'
            'const i=xe(`resolve:${e}`,(async()=>{var t,n;if("undefined"==typeof window||'
            '"function"!=typeof window.fetch)throw new Error("The browser cannot resolve '
            'the Miniworlds package.");'
        )
        self.CONTENT_STORE = ContentStore()
        self.WORKSPACE_IO = WorkspaceIO(content_store=self.CONTENT_STORE)
        self.RUNTIME_PREPARATION = RuntimePreparationService(self.H5P_RUNTIME_CONTENT_DIR)
        self.TAG_RE = self.APP_CONFIG.tag_re
        self.FENCE_RE = self.APP_CONFIG.fence_re
        self.HTML_TAG_RE = self.APP_CONFIG.html_tag_re
        self.WHITESPACE_RE = self.APP_CONFIG.whitespace_re
        self.MBZ_LINK_RE = self.APP_CONFIG.mbz_link_re
        self._services_lock = threading.RLock()
        self._services: dict[str, object] = {}
        self._SYNC_METADATA_STORE = SyncMetadataStore(
            sync_metadata_file=self.SYNC_METADATA_FILE,
            ensure_directory=self.ensure_directory,
        )
        self.fetch_text = fetch_text
        self.fetch_json = fetch_json
        self.download_file = download_file
        self.MoodlePlaywrightUploader = MoodlePlaywrightUploader
        self.collect_moodle_text_labels = collect_moodle_text_labels
        self.site_exporter = StaticSiteExporter(self)
        self.moodle_workflows = MoodleWorkflows(self)

    def __getattr__(self, name):
        for service_name in ("site_exporter", "moodle_workflows"):
            service = self.__dict__.get(service_name)
            if service is not None:
                try:
                    return getattr(service, name)
                except AttributeError:
                    pass
        raise AttributeError(name)

    def moodle_backup_extractor(self) -> MoodleBackupExtractor:
        # Intentionally not cached so test monkeypatches on module-level helpers stay effective.
        return MoodleBackupExtractor(
            mbz_link_re=self.MBZ_LINK_RE,
            fetch_text=self.fetch_text,
            download_file=self.download_file,
            ensure_directory=self.ensure_directory,
        )


    def moodle_backup_diff_analyzer(self) -> MoodleBackupDiffAnalyzer:
        return MoodleBackupDiffAnalyzer()


    def normalize_whitespace(self, value: str) -> str:
        return self.text_operations().normalize_whitespace(value)


    def strip_html(self, value: str) -> str:
        return self.text_operations().strip_html(value)


    def compact_text(self, value: str) -> str:
        return self.text_operations().compact_text(value)


    def make_stable_identifier(self, title: str, existing_identifiers: set[str]) -> str:
        return self.text_operations().make_stable_identifier(title, existing_identifiers)


    def build_source_package_sidecar_path(self, question: CourseActivity) -> str:
        return self.h5p_file_service().build_source_package_sidecar_path(question)


    def write_source_package_sidecar(self, question: CourseActivity, source_archive: Path) -> str:
        return self.h5p_file_service().write_source_package_sidecar(question, source_archive)


    def load_h5p_payload_from_path(self, source_path: Path) -> tuple[dict[str, object], dict[str, object]] | None:
        return self.h5p_file_service().load_h5p_payload_from_path(source_path)


    def source_tree_mtime_ns(self, path: Path | None) -> int:
        return self.h5p_file_service().source_tree_mtime_ns(path)


    def source_tree_fingerprint(self, path: Path | None) -> str:
        return self.h5p_file_service().source_tree_fingerprint(path)


    def populate_imported_h5p_directory(self, source_path: Path, target_dir: Path, metadata_payload: dict[str, object], content_payload: dict[str, object]) -> None:
        self.h5p_file_service().populate_imported_h5p_directory(source_path, target_dir, metadata_payload, content_payload)


    def build_imported_question_from_sidecar(self, course_dir: Path, identifier: str, source_package_path: str) -> CourseActivity | None:
        payload = self.load_h5p_payload_from_path(course_dir / source_package_path)
        if payload is None:
            return None

        metadata_payload, content_payload = payload
        question = self.build_imported_question_from_h5p_package(
            course_dir.name,
            MoodleH5PActivity(
                identifier=identifier,
                title=str(metadata_payload.get("title") or identifier),
                course_id=0,
                activity_id=0,
                instance_id=None,
            ),
            metadata_payload,
            content_payload,
        )
        if question is None:
            return None
        question.course_dir = course_dir
        question.build_dir = self.course_build_dir(course_dir)
        question.source_package_path = source_package_path
        return question


    def infer_source_package_sidecar_path(self, question: CourseActivity) -> str:
        if question.course_dir is None:
            return ""
        if question.h5p_subdir:
            chapter_dir = Path("chapters") / question.h5p_subdir
            if question.identifier == "content" and any(
                (question.course_dir / chapter_dir / candidate).exists()
                for candidate in ("content.mdx", "content.yml", "content.yaml", "content.json", "h5p.json")
            ):
                return chapter_dir.as_posix()
            chapter_source_dir = Path("chapters") / question.h5p_subdir / question.identifier
            if any(
                (question.course_dir / chapter_source_dir / candidate).exists()
                for candidate in ("content.mdx", "content.yml", "content.yaml", "content.json", "h5p.json")
            ):
                return chapter_source_dir.as_posix()

        relative_path = self.build_source_package_sidecar_path(question)
        if (question.course_dir / relative_path).exists():
            return relative_path
        return ""


    def load_h5p_payload_from_source_package(self, question: CourseActivity) -> tuple[dict[str, object], dict[str, object]] | None:
        if question.course_dir is None or not question.source_package_path:
            return None

        archive_path = question.course_dir / question.source_package_path
        if not archive_path.exists():
            return None
        return self.load_h5p_payload_from_path(archive_path)


    def build_imported_question_from_h5p_package(self,
        course_slug: str,
        activity: MoodleH5PActivity,
        metadata_payload: dict[str, object],
        content_payload: dict[str, object],
    ) -> CourseActivity | None:
        return self.imported_question_factory().create_from_h5p_package(
            course_slug=course_slug,
            activity=activity,
            metadata_payload=metadata_payload,
            content_payload=content_payload,
        )


    def render_imported_question_mdx(self, question: CourseActivity) -> list[str]:
        return self.component_syncer().render_imported_question_mdx(question)


    def escape_mdx_attribute(self, value: str) -> str:
        return html.escape(value, quote=True)


    def parse_course(self, course_dir: Path) -> tuple[str, list[CourseActivity], str]:
        return self.mdx_course_parser().parse_course(course_dir)


    def course_build_dir(self, course_dir: Path) -> Path:
        return self.COURSE_BUILD_DIR / course_dir.name


    def collect_h5p_upload_packages(self, course_dir: Path, chapter: str) -> list[MoodleH5PUploadPackage]:
        return _collect_h5p_upload_packages(course_dir, chapter, build_dir=self.course_build_dir(course_dir))


    def load_sync_metadata(self, course_dir: Path) -> SyncMetadata | None:
        return self._SYNC_METADATA_STORE.load(course_dir)


    def save_sync_metadata(self, course_dir: Path, metadata: SyncMetadata) -> Path:
        return self._SYNC_METADATA_STORE.save(course_dir, metadata)


    def compute_question_hash(self, question: CourseActivity) -> str:
        return self.component_syncer().compute_question_hash(question)


    def import_moodle_course(self, course: str, remote_course_id: int, client: MoodleApiClient) -> Path:
        return self.moodle_syncer().import_moodle_course(
            course=course,
            remote_course_id=remote_course_id,
            client=client,
        )


    def import_moodle_from_mbz(self,
        course: str,
        mbz_path: Path,
        remote_course_id: int = 0,
        base_url: str = "",
    ) -> Path:
        importer = MoodleBackupImporter(
            mbz_path=mbz_path,
            base_url=base_url or "",
            backup_extractor=self.moodle_backup_extractor(),
            make_stable_identifier=self.make_stable_identifier,
            strip_html=self.strip_html,
            build_imported_question_from_h5p_package=self.build_imported_question_from_h5p_package,
            write_source_package_sidecar=self.write_source_package_sidecar,
        )
        return self.import_moodle_course(course, remote_course_id, importer)


    def push_moodle_course(self, course_dir: Path, remote_course_id: int, client: MoodleApiClient) -> list[CourseActivity]:
        return self.moodle_syncer().push_moodle_course(
            course_dir=course_dir,
            remote_course_id=remote_course_id,
            client=client,
            sync_course=self.sync_course,
        )


    def build_course_status(self, course_dir: Path) -> dict[str, object]:
        return self.course_orchestrator().build_course_status(course_dir)


    def build_moodle_ping_report(self, client: MoodleApiClient) -> dict[str, object]:
        return MoodleSyncer.build_moodle_ping_report(client)


    def resolve_moodle_client(self, base_url: str | None = None, token: str | None = None) -> MoodleApiClient:
        return self.moodle_client_resolver().resolve_moodle_client(base_url, token)


    def ensure_directory(self, path: Path) -> None:
        self.WORKSPACE_IO.ensure_directory(path)


    def read_json(self, path: Path) -> dict:
        return self.WORKSPACE_IO.read_json(path)


    def read_yaml(self, path: Path) -> object:
        return self.WORKSPACE_IO.read_yaml(path)


    def read_json_or_default(self, path: Path, default: dict) -> dict:
        return self.WORKSPACE_IO.read_json_or_default(path, default)


    def write_json(self, path: Path, payload: dict) -> None:
        self.WORKSPACE_IO.write_json(path, payload)


    def read_h5p_content_payload(self, source_dir: Path) -> dict[str, object]:
        return self.WORKSPACE_IO.read_h5p_content_payload(source_dir)


    def write_h5p_content_files(self,
        target_dir: Path, payload: dict[str, object], *, use_frontmatter: bool = False
    ) -> None:
        self.WORKSPACE_IO.write_h5p_content_files(target_dir, payload, use_frontmatter=use_frontmatter)


    def write_h5p_archive_from_directory(self,
        archive: ZipFile,
        source_dir: Path,
        *,
        shared_libraries: Iterable[Path] = (),
        shared_libraries_root: Path | None = None,
        metadata_payload: dict[str, object] | None = None,
        content_payload: dict[str, object] | None = None,
    ) -> None:
        self.h5p_file_service().write_h5p_archive_from_directory(
            archive,
            source_dir,
            shared_libraries=shared_libraries,
            shared_libraries_root=shared_libraries_root,
            metadata_payload=metadata_payload,
            content_payload=content_payload,
        )


    def find_library_dir(self, machine_name: str, major_version: int | None = None, minor_version: int | None = None) -> Path:
        return self.h5p_library_manager().find_library_dir(machine_name, major_version, minor_version)


    def ensure_h5p_runtime_libraries(self) -> None:
        if self.H5P_RUNTIME_LIBRARIES_READY:
            return
        self.h5p_library_manager().ensure_h5p_runtime_libraries()
        self.H5P_RUNTIME_LIBRARIES_READY = True


    def update_h5p_libraries_from_github(self, tag: str | None = None) -> list[dict[str, str]]:
        updated_libraries = self.h5p_library_manager().update_custom_libraries_from_github(tag)
        self.patch_python_question_miniworlds_robot_resolver()
        return updated_libraries

    def update_h5p_libraries_from_local_export(self, export_dir: Path) -> list[dict[str, str]]:
        updated_libraries = self.h5p_library_manager().update_custom_libraries_from_local_export(export_dir)
        self.patch_python_question_miniworlds_robot_resolver()
        self.RUNTIME_PREPARATION.invalidate_persisted_hashes()
        return updated_libraries


    def patch_python_question_miniworlds_robot_resolver(self) -> None:
        library_path = self.ROOT_DIR / "ressourcen" / "libraries" / "H5P.PythonQuestion-6.108" / "dist" / "h5p-python-question.js"
        if not library_path.exists():
            return
        source = library_path.read_text("utf-8")
        if self.MINIWORLDS_ROBOT_WHEEL_URL in source:
            return
        if self.PYTHON_QUESTION_ROBOT_RESOLVER_NEEDLE not in source:
            raise RuntimeError(
                "PythonQuestion Miniworlds-Resolver konnte nicht gepatcht werden; "
                "die erwartete PyPI-Resolver-Stelle wurde nicht gefunden."
            )
        library_path.write_text(
            source.replace(
                self.PYTHON_QUESTION_ROBOT_RESOLVER_NEEDLE,
                self.PYTHON_QUESTION_ROBOT_RESOLVER_REPLACEMENT,
                1,
            ),
            "utf-8",
        )


    def collect_required_library_dirs(self, machine_name: str, major_version: int | None = None, minor_version: int | None = None, seen: set[str] | None = None) -> list[Path]:
        return self.h5p_library_manager().collect_required_library_dirs(machine_name, major_version, minor_version, seen)


    def collect_required_library_dirs_from_metadata(self, metadata_payload: dict[str, object]) -> list[Path]:
        return self.h5p_library_manager().collect_required_library_dirs_from_metadata(metadata_payload)


    def ensure_h5p_runtime_server(self, port: int | None = None) -> subprocess.Popen[str] | None:
        return self.runtime_cli_service().ensure_h5p_runtime_server(self.H5P_RUNTIME_PORT if port is None else port)


    def import_question_into_runtime(self, question: CourseActivity) -> None:
        self.runtime_cli_service().import_question_into_runtime(question)


    def build_runtime_proxy_path(self, question: CourseActivity, mode: str, *, simple: bool = False) -> str:
        return self.h5p_runtime_manager().build_runtime_proxy_path(question, mode, simple=simple)


    def build_h5p_metadata(self, question: CourseActivity) -> dict:
        return self.h5p_package_builder().build_h5p_metadata(question)


    def build_h5p_content(self, question: CourseActivity) -> dict:
        return self.h5p_package_builder().build_h5p_content(question)


    def write_h5p_package(self, question: CourseActivity) -> Path:
        self.patch_python_question_miniworlds_robot_resolver()
        return self.h5p_package_builder().write_h5p_package(question)


    @application_service
    def preview_view_builder(self) -> PreviewViewBuilder:
        return PreviewViewBuilder(
            runtime_proxy_prefix=self.RUNTIME_PROXY_PREFIX,
            quote_path_segment=self.quote_path_segment,
            escape_inline=self.escape_inline,
            build_runtime_proxy_path=self.build_runtime_proxy_path,
        )


    @application_service
    def preview_controller(self) -> PreviewController:
        return PreviewController(
            courses_dir=self.COURSES_DIR,
            load_course_preview_state=self.load_course_preview_state,
            get_runtime_preparation_state=self.get_runtime_preparation_state,
            start_runtime_question_preparation=self.start_runtime_question_preparation,
            rebuild_runtime_question=self.rebuild_runtime_question,
            invalidate_course_preview_cache=self.invalidate_course_preview_cache,
            is_runtime_question_ready=self.is_runtime_question_ready,
            build_runtime_proxy_path=self.build_runtime_proxy_path,
            render_preview_waiting_page=self.render_preview_waiting_page,
        )


    @application_service
    def markdown_renderer(self) -> MarkdownRenderer:
        return MarkdownRenderer(escape_inline=self.escape_inline)


    @application_service
    def template_renderer(self) -> TemplateRenderer:
        return TemplateRenderer(escape_inline=self.escape_inline, dotenv_file=self.DOTENV_FILE)


    def _load_python_question_semantics(self) -> list[dict[str, object]]:
        payload = self.read_json(self.find_library_dir(self.PYTHON_QUESTION_MACHINE_NAME) / "semantics.json")
        if not isinstance(payload, list):
            raise ValueError("semantics.json für H5P.PythonQuestion muss ein JSON-Array sein.")
        return [field for field in payload if isinstance(field, dict)]


    @application_service
    def component_syncer(self) -> ComponentSyncer:
        return ComponentSyncer(
            python_question_machine_name=self.PYTHON_QUESTION_MACHINE_NAME,
            load_python_question_semantics=self._load_python_question_semantics,
            load_h5p_payload_from_source_package=self.load_h5p_payload_from_source_package,
            build_h5p_metadata=self.build_h5p_metadata,
        )


    def h5p_library_manager(self) -> H5PLibraryManager:
        # Intentionally not cached so tests can monkeypatch module-level dependencies safely.
        return H5PLibraryManager(
            workspace_lock=self.WORKSPACE_LOCK,
            runtime_dir=self.H5P_RUNTIME_DIR,
            runtime_content_dir=self.H5P_RUNTIME_CONTENT_DIR,
            runtime_libraries_dir=self.H5P_RUNTIME_LIBRARIES_DIR,
            runtime_downloads_dir=self.H5P_RUNTIME_DOWNLOADS_DIR,
            shared_libraries_dir=self.ROOT_DIR / "ressourcen" / "libraries",
            courses_dir=self.COURSES_DIR,
            release_repo=self.H5P_LIBRARY_RELEASE_REPO,
            release_tag=self.H5P_LIBRARY_RELEASE_TAG,
            asset_prefixes=self.H5P_LIBRARY_ASSET_PREFIXES,
            extra_assets=self.H5P_LIBRARY_EXTRA_ASSETS,
            custom_short_names=self.CUSTOM_H5P_LIBRARY_SHORT_NAMES,
            ensure_directory=self.ensure_directory,
            read_json=self.read_json,
            read_json_or_default=self.read_json_or_default,
            write_json=self.write_json,
            fetch_json=self.fetch_json,
            download_file=self.download_file,
        )


    def runtime_cli_service(self) -> RuntimeCliService:
        # Intentionally not cached so tests can monkeypatch module-level dependencies safely.
        library_manager = self.h5p_library_manager()
        return RuntimeCliService(
            workspace_lock=self.WORKSPACE_LOCK,
            runtime_dir=self.H5P_RUNTIME_DIR,
            runtime_content_dir=self.H5P_RUNTIME_CONTENT_DIR,
            backend=library_manager,
        )


    def h5p_file_service(self) -> H5PFileService:
        # Intentionally not cached so tests can monkeypatch module-level dependencies safely.
        return H5PFileService(
            courses_dir=self.COURSES_DIR,
            ensure_directory=self.ensure_directory,
            read_yaml=self.read_yaml,
            read_h5p_content_payload=self.read_h5p_content_payload,
            write_h5p_content_files=self.write_h5p_content_files,
            write_json=self.write_json,
        )


    def moodle_client_resolver(self) -> MoodleClientResolver:
        # Intentionally not cached so tests can monkeypatch module-level dependencies safely.
        return MoodleClientResolver(
            dotenv_file=self.DOTENV_FILE,
            make_stable_identifier=self.make_stable_identifier,
            strip_html=self.strip_html,
            fetch_text=self.fetch_text,
            extract_h5p_package_url_from_activity_html=lambda page_html, base_url: extract_h5p_package_url_from_activity_html(
                page_html,
                base_url=base_url,
            ),
            download_file=self.download_file,
            moodle_backup_extractor_factory=self.moodle_backup_extractor,
            build_imported_question_from_h5p_package=self.build_imported_question_from_h5p_package,
            write_source_package_sidecar=self.write_source_package_sidecar,
            environ=os.environ,
        )


    def text_operations(self) -> TextOperations:
        # Intentionally not cached so tests can monkeypatch module-level dependencies safely.
        return TextOperations(
            html_tag_re=self.HTML_TAG_RE,
            whitespace_re=self.WHITESPACE_RE,
        )


    @application_service
    def h5p_runtime_manager(self) -> H5PRuntimeManager:
        return H5PRuntimeManager(
            runtime_dir=self.H5P_RUNTIME_DIR,
            runtime_port=self.H5P_RUNTIME_PORT,
            runtime_proxy_prefix=self.RUNTIME_PROXY_PREFIX,
            custom_h5p_library_short_names=self.CUSTOM_H5P_LIBRARY_SHORT_NAMES,
            runtime_preparation=self.RUNTIME_PREPARATION,
            get_preview_view_builder=self.preview_view_builder,
            compute_question_hash=self.compute_question_hash,
            write_h5p_package=self.write_h5p_package,
            import_question_into_runtime=self.import_question_into_runtime,
            read_json_or_default=self.read_json_or_default,
        )


    @application_service
    def moodle_syncer(self) -> MoodleSyncer:
        return MoodleSyncer(
            courses_dir=self.COURSES_DIR,
            ensure_directory=self.ensure_directory,
            render_imported_question_mdx=self.render_imported_question_mdx,
            parse_course=self.parse_course,
            compute_question_hash=self.compute_question_hash,
            save_sync_metadata=self.save_sync_metadata,
            escape_mdx_attribute=self.escape_mdx_attribute,
            course_build_dir=self.course_build_dir,
        )


    def h5p_package_builder(self) -> H5PPackageBuilder:
        return H5PPackageBuilder(
            workspace_lock=self.WORKSPACE_LOCK,
            python_question_machine_name=self.PYTHON_QUESTION_MACHINE_NAME,
            ensure_directory=self.ensure_directory,
            source_tree_mtime_ns=self.source_tree_mtime_ns,
            source_tree_fingerprint=self.source_tree_fingerprint,
            download_file=self.download_file,
            populate_imported_h5p_directory=self.populate_imported_h5p_directory,
            collect_required_library_dirs_from_metadata=self.collect_required_library_dirs_from_metadata,
            collect_required_library_dirs=self.collect_required_library_dirs,
            write_h5p_archive_from_directory=self.write_h5p_archive_from_directory,
            write_h5p_content_files=self.write_h5p_content_files,
            ensure_h5p_runtime_libraries=self.ensure_h5p_runtime_libraries,
            build_h5p_content=lambda question: self.component_syncer().build_h5p_content(question),
            read_json=self.read_json,
            find_library_dir=self.find_library_dir,
            runtime_libraries_dir=self.H5P_RUNTIME_LIBRARIES_DIR,
        )


    @application_service
    def course_orchestrator(self) -> CourseOrchestrator:
        return CourseOrchestrator(
            workspace_lock=self.WORKSPACE_LOCK,
            courses_dir=self.COURSES_DIR,
            preview_cache=self.PREVIEW_CACHE,
            parse_course=self.parse_course,
            write_h5p_package=self.write_h5p_package,
            render_course_page=self.render_course_page,
            load_sync_metadata=self.load_sync_metadata,
            compute_question_hash=self.compute_question_hash,
            course_build_dir=self.course_build_dir,
        )


    @application_service
    def runtime_html_rewriter(self) -> RuntimeHtmlRewriter:
        return RuntimeHtmlRewriter(
            runtime_port=self.H5P_RUNTIME_PORT,
            runtime_proxy_prefix=self.RUNTIME_PROXY_PREFIX,
        )


    @application_service
    def mdx_course_parser(self) -> MdxCourseParser:
        return MdxCourseParser(
            tag_re=self.TAG_RE,
            fence_re=self.FENCE_RE,
            placeholder_template=self.PLACEHOLDER_TEMPLATE,
            python_question_machine_name=self.PYTHON_QUESTION_MACHINE_NAME,
            parse_jsx_expression=lambda expression: self.component_syncer().parse_jsx_expression(expression),
            normalize_whitespace=self.normalize_whitespace,
            infer_source_package_sidecar_path=self.infer_source_package_sidecar_path,
            build_imported_question_from_sidecar=self.build_imported_question_from_sidecar,
            load_h5p_sidecar_file=lambda course_dir, relative_path: self.h5p_file_service().load_h5p_sidecar_file(
                course_dir,
                relative_path,
                description="H5P-Sidecar",
            ),
            apply_editable_h5p_payload=lambda question, payload: self.component_syncer().apply_editable_h5p_payload(question, payload),
            course_build_dir=self.course_build_dir,
        )


    @application_service
    def h5p_import_mapper(self) -> H5PImportMapper:
        return H5PImportMapper(
            compact_text=self.compact_text,
            normalize_whitespace=self.normalize_whitespace,
        )


    def imported_question_factory(self) -> ImportedQuestionFactory:
        # Intentionally not cached so tests can monkeypatch module-level dependencies safely.
        return ImportedQuestionFactory(
            courses_dir=self.COURSES_DIR,
            python_question_machine_name=self.PYTHON_QUESTION_MACHINE_NAME,
            normalize_whitespace=self.normalize_whitespace,
            strip_html=self.strip_html,
            import_mapper=self.h5p_import_mapper(),
        )


    def rewrite_runtime_html(self, document: str, runtime_path: str, query: str = "") -> str:
        return self.runtime_html_rewriter().rewrite(document, runtime_path, query)


    def sync_course(self, course_dir: Path) -> list[CourseActivity]:
        return self.course_orchestrator().sync_course(course_dir)


    def list_course_dirs(self) -> list[Path]:
        return sorted(item for item in self.COURSES_DIR.iterdir() if (item / "index.mdx").is_file())


    def load_course_preview_state(self, course_dir: Path) -> tuple[list[CourseActivity], str]:
        return self.course_orchestrator().load_course_preview_state(course_dir)


    def invalidate_course_preview_cache(self, course_slug: str) -> None:
        self.course_orchestrator().invalidate_course_preview_cache(course_slug)


    def find_question_by_runtime_content_id(self, runtime_content_id: str) -> CourseActivity | None:
        return self.course_orchestrator().find_question_by_runtime_content_id(runtime_content_id)


    def ensure_runtime_question_ready(self, question: CourseActivity) -> None:
        self.h5p_runtime_manager().ensure_runtime_question_ready(question)


    def rebuild_runtime_question(self, question: CourseActivity) -> None:
        self.h5p_runtime_manager().rebuild_runtime_question(question)


    def is_runtime_question_ready(self, question: CourseActivity) -> bool:
        return self.h5p_runtime_manager().is_runtime_question_ready(question)


    def start_runtime_question_preparation(self, question: CourseActivity) -> None:
        self.h5p_runtime_manager().start_runtime_question_preparation(question)


    def get_runtime_preparation_state(self, question: CourseActivity) -> dict[str, str]:
        return self.h5p_runtime_manager().get_runtime_preparation_state(question)


    def render_preview_waiting_page(self, question: CourseActivity, *, mode: str = "view", simple: bool = False) -> str:
        return self.h5p_runtime_manager().render_preview_waiting_page(question, mode=mode, simple=simple)


    def resolve_runtime_question_from_path(self, runtime_path: str) -> CourseActivity | None:
        runtime_content_id = self.h5p_runtime_manager().resolve_runtime_content_id_from_path(runtime_path)
        if runtime_content_id is None:
            return None
        return self.find_question_by_runtime_content_id(runtime_content_id)


    def escape_inline(self, value: str) -> str:
        return html.escape(value, quote=True)


    def quote_path_segment(self, value: str) -> str:
        return quote_path_segment_helper(value)


    def render_course_page(self,
        course_dir: Path,
        *,
        questions: list[CourseActivity] | None = None,
        rendered_source: str | None = None,
        package_href_builder: Any | None = None,
        player_href_builder: Any | None = None,
        canonical_url: str = "",
        home_href: str = "/",
    ) -> str:
        if questions is None or rendered_source is None:
            _, questions, rendered_source = self.parse_course(course_dir)

        chapters = {chapter["slug"].split("/")[0]: chapter for chapter in list_course_chapters(course_dir)}
        view_builder = self.preview_view_builder()
        question_html = {}
        for question in questions:
            if package_href_builder is not None:
                package_src = str(package_href_builder(question))
            else:
                try:
                    package_src = question.package_path.relative_to(course_dir).as_posix()
                except ValueError:
                    # Build output no longer lives under course_dir (centralized under
                    # COURSE_BUILD_DIR instead) -- reconstruct the same "build/h5p/..."-shaped
                    # relative href callers of this fallback historically got.
                    relative_package_path = (
                        Path(question.h5p_subdir) / question.package_path.name
                        if question.h5p_subdir
                        else Path(question.package_path.name)
                    )
                    package_src = (Path("build") / "h5p" / relative_package_path).as_posix()
            player_src = str(player_href_builder(question)) if player_href_builder is not None else ""
            question_html[question.identifier] = view_builder.build_static_question_component(
                question,
                package_src=package_src,
                player_src=player_src,
            )
            if question.h5p_subdir:
                chapter = chapters.get(question.h5p_subdir, {"slug": question.h5p_subdir, "title": question.h5p_subdir})
                chapter_slug = self.escape_inline(chapter["slug"])
                chapter_title = self.escape_inline(chapter["title"])
                question_html[question.identifier] = question_html[question.identifier].replace(
                    '<section ',
                    f'<section data-chapter="{chapter_slug}" data-chapter-title="{chapter_title}" ',
                    1,
                )
        content_html = self.markdown_renderer().render(rendered_source, question_html)

        return self.template_renderer().render_course_page(
            title=course_dir.name,
            content_html=content_html,
            canonical_url=canonical_url,
            preview_fallback=player_href_builder is None,
            home_href=home_href,
        )


    def prepare_preview_runtime(self, course_dir: Path | None = None) -> list[CourseActivity]:
        self.ensure_h5p_runtime_libraries()
        target_course_dirs = [course_dir] if course_dir is not None else self.list_course_dirs()
        prepared_questions: list[CourseActivity] = []
        for target_course_dir in target_course_dirs:
            questions, _ = self.load_course_preview_state(target_course_dir)
            for question in questions:
                self.ensure_runtime_question_ready(question)
            prepared_questions.extend(questions)
        return prepared_questions


    def export_chapter(self, course_dir: Path, chapter: str, output_dir: Path | None = None) -> list[Path]:
        self.sync_course(course_dir)
        chapter_slug = chapter.strip().strip("/")
        if not chapter_slug:
            raise ValueError("Kapitel-Slug fehlt.")

        source_dir = self.course_build_dir(course_dir) / "h5p" / chapter_slug
        if not source_dir.is_dir():
            raise FileNotFoundError(f"Build-Ordner für Kapitel '{chapter_slug}' wurde nicht gefunden: {source_dir}")

        package_paths = sorted(source_dir.glob("*.h5p"))
        if not package_paths:
            raise FileNotFoundError(f"Keine H5P-Pakete für Kapitel '{chapter_slug}' gefunden.")

        target_dir = output_dir or (course_dir / "exports" / chapter_slug)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        exported_paths: list[Path] = []
        for package_path in package_paths:
            target_path = target_dir / package_path.name
            shutil.copy2(package_path, target_path)
            exported_paths.append(target_path)
        return exported_paths


_default_application: CourseApplication | None = None
_default_application_lock = threading.Lock()


def get_application() -> CourseApplication:
    global _default_application
    with _default_application_lock:
        if _default_application is None:
            _default_application = CourseApplication()
        return _default_application
