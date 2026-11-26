from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Callable, Iterable
from zipfile import ZIP_DEFLATED, ZipFile

from material_core.filesystem import atomic_write_text

from .due_dates import normalize_h5p_due_date
from .models import PythonQuestionBlock


class H5PPackageBuilder:
    """Build and materialize local H5P packages for a question.

    The builder uses three strategies internally:
    - imported/source package merge
    - raw package download
    - scratch package assembly
    """

    _ARCHIVE_FILTER_VERSION = 4

    def __init__(
        self,
        *,
        workspace_lock: RLock,
        python_question_machine_name: str,
        ensure_directory: Callable[[Path], None],
        source_tree_mtime_ns: Callable[[Path | None], int],
        source_tree_fingerprint: Callable[[Path | None], str],
        download_file: Callable[[str, Path], None],
        populate_imported_h5p_directory: Callable[[Path, Path, dict[str, object], dict[str, object]], None],
        collect_required_library_dirs_from_metadata: Callable[[dict[str, object]], list[Path]],
        collect_required_library_dirs: Callable[..., list[Path]],
        write_h5p_archive_from_directory: Callable[..., None],
        write_h5p_content_files: Callable[..., None],
        ensure_h5p_runtime_libraries: Callable[[], None],
        build_h5p_content: Callable[[PythonQuestionBlock], dict],
        read_json: Callable[[Path], dict],
        find_library_dir: Callable[..., Path],
        runtime_libraries_dir: Path,
    ) -> None:
        self._workspace_lock = workspace_lock
        self._python_question_machine_name = python_question_machine_name
        self._ensure_directory = ensure_directory
        self._source_tree_mtime_ns = source_tree_mtime_ns
        self._source_tree_fingerprint = source_tree_fingerprint
        self._download_file = download_file
        self._populate_imported_h5p_directory = populate_imported_h5p_directory
        self._collect_required_library_dirs_from_metadata = collect_required_library_dirs_from_metadata
        self._collect_required_library_dirs = collect_required_library_dirs
        self._write_h5p_archive_from_directory = write_h5p_archive_from_directory
        self._write_h5p_content_files = write_h5p_content_files
        self._ensure_h5p_runtime_libraries = ensure_h5p_runtime_libraries
        self._build_h5p_content = build_h5p_content
        self._read_json = read_json
        self._find_library_dir = find_library_dir
        self._runtime_libraries_dir = runtime_libraries_dir

    def build_h5p_metadata(self, question: PythonQuestionBlock) -> dict:
        library_metadata = self._read_json(self._find_library_dir(question.main_library) / "library.json")
        default_language = "en" if question.course_slug.endswith("-en") else "de"
        preloaded_dependencies = [
            {
                "machineName": library_metadata["machineName"],
                "majorVersion": library_metadata["majorVersion"],
                "minorVersion": library_metadata["minorVersion"],
            }
        ]
        preloaded_dependencies.extend(
            {
                "machineName": dependency["machineName"],
                "majorVersion": dependency["majorVersion"],
                "minorVersion": dependency["minorVersion"],
            }
            for dependency in library_metadata.get("preloadedDependencies", [])
        )
        return {
            "title": question.title,
            "language": default_language,
            "defaultLanguage": default_language,
            "mainLibrary": question.main_library,
            "embedTypes": ["div"],
            "license": "U",
            "preloadedDependencies": preloaded_dependencies,
            "majorVersion": library_metadata["majorVersion"],
            "minorVersion": library_metadata["minorVersion"],
        }

    def build_h5p_content(self, question: PythonQuestionBlock) -> dict:
        content = self._build_h5p_content(question)
        self._apply_due_date(content, question.due_date)
        return content

    @staticmethod
    def _apply_due_date(content: dict[str, object], due_date: str) -> None:
        """Apply a chapter deadline to every assignment-capable H5P payload."""
        if not due_date:
            return
        grading_settings = content.get("gradingSettings")
        if not isinstance(grading_settings, dict):
            return
        grading_settings["dueDateGroup"] = {
            "enableDueDate": True,
            "duedate": normalize_h5p_due_date(due_date),
        }

    def _build_state_path(self, question: PythonQuestionBlock) -> Path:
        if question.course_dir is None:
            return question.exploded_dir / ".build-hash"
        return question.build_hash_path

    def _read_build_state(self, question: PythonQuestionBlock) -> str:
        state_path = self._build_state_path(question)
        if not state_path.exists():
            return ""
        try:
            return state_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _write_build_state(self, question: PythonQuestionBlock, fingerprint: str) -> None:
        state_path = self._build_state_path(question)
        self._ensure_directory(state_path.parent)
        atomic_write_text(state_path, fingerprint + "\n")

    def _fingerprint_payload(self, payload: object) -> str:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _libraries_fingerprint(self, library_dirs: Iterable[Path]) -> list[dict[str, str]]:
        return [
            {
                "name": library_dir.name,
                "fingerprint": self._source_tree_fingerprint(library_dir),
            }
            for library_dir in library_dirs
        ]

    def _write_package_archive(
        self,
        question: PythonQuestionBlock,
        *,
        shared_libraries: Iterable[Path],
        metadata_payload: dict[str, object] | None = None,
        content_payload: dict[str, object] | None = None,
        source_dir: Path | None = None,
    ) -> None:
        self._ensure_directory(question.package_path.parent)
        with tempfile.TemporaryDirectory(dir=question.package_path.parent) as temp_dir:
            temp_package_path = Path(temp_dir) / question.package_path.name
            with ZipFile(temp_package_path, "w", compression=ZIP_DEFLATED) as archive:
                self._write_h5p_archive_from_directory(
                    archive,
                    source_dir if source_dir is not None else question.exploded_dir,
                    shared_libraries=shared_libraries,
                    shared_libraries_root=self._runtime_libraries_dir,
                    metadata_payload=metadata_payload,
                    content_payload=content_payload,
                )
            shutil.move(str(temp_package_path), question.package_path)

    def _can_reuse_package(self, question: PythonQuestionBlock, fingerprint: str) -> bool:
        if not question.package_path.exists():
            return False
        return self._read_build_state(question) == fingerprint

    def write_h5p_package(self, question: PythonQuestionBlock) -> Path:
        with self._workspace_lock:
            self._ensure_directory(question.package_path.parent)

            source_archive_path = (question.course_dir / question.source_package_path) if question.source_package_path else None
            source_fingerprint = self._source_tree_fingerprint(source_archive_path)

            if question.raw_package and source_archive_path is not None and source_archive_path.is_file():
                raw_fingerprint = self._fingerprint_payload({
                    "mode": "raw-sidecar",
                    "mainLibrary": question.main_library,
                    "sourceFingerprint": source_fingerprint,
                })
                if self._can_reuse_package(question, raw_fingerprint):
                    return question.package_path
                self._ensure_directory(question.package_path.parent)
                shutil.copy2(source_archive_path, question.package_path)
                self._write_build_state(question, raw_fingerprint)
                return question.package_path

            if question.h5p_metadata is not None and question.h5p_content is not None:
                self._ensure_h5p_runtime_libraries()
                metadata_payload = deepcopy(question.h5p_metadata)
                content_payload = deepcopy(question.h5p_content)
                metadata_payload["title"] = question.title
                metadata_payload["mainLibrary"] = question.main_library
                if question.main_library == self._python_question_machine_name:
                    metadata_payload = self._normalize_imported_python_question_metadata(question, metadata_payload)
                    content_payload = self._build_h5p_content(question)
                if "pythonRunner" in content_payload or question.main_library == self._python_question_machine_name:
                    content_payload["pythonRunner"] = question.runner

                # The due date is chapter-level state (index.mdx), re-derived on every build, so
                # it's applied only to the payload that goes into the built .h5p archive -- not
                # to what gets written back into the tracked source, which would otherwise churn
                # (or go stale) independently of any real change to the question itself.
                archive_content_payload = deepcopy(content_payload)
                self._apply_due_date(archive_content_payload, question.due_date)
                required_library_dirs = self._collect_required_library_dirs_from_metadata(metadata_payload)

                imported_fingerprint = self._fingerprint_payload(
                    {
                        "mode": "imported",
                        "metadata": metadata_payload,
                        "content": archive_content_payload,
                        "sourceFingerprint": source_fingerprint,
                        "libraryFingerprint": self._libraries_fingerprint(required_library_dirs),
                        "packageUrl": question.package_url,
                        "archiveFilterVersion": self._ARCHIVE_FILTER_VERSION,
                    }
                )
                if self._can_reuse_package(question, imported_fingerprint):
                    return question.package_path

                with tempfile.TemporaryDirectory() as temp_dir:
                    source_path = Path(temp_dir) / "source"
                    if source_archive_path is not None and source_archive_path.exists():
                        if source_archive_path.is_dir():
                            shutil.copytree(source_archive_path, source_path)
                        else:
                            shutil.copyfile(source_archive_path, source_path)
                    elif question.package_url:
                        source_path = Path(temp_dir) / "original.h5p"
                        self._download_file(question.package_url, source_path)
                    else:
                        source_path.mkdir()

                    shared_libraries = list(required_library_dirs)
                    metadata_payload = self._normalize_metadata_dependencies(metadata_payload, shared_libraries)

                    self._populate_imported_h5p_directory(source_path, question.build_exploded_dir, metadata_payload, content_payload)
                    self._write_package_archive(
                        question,
                        shared_libraries=shared_libraries,
                        metadata_payload=metadata_payload,
                        content_payload=archive_content_payload,
                        source_dir=question.build_exploded_dir,
                    )

                self._write_build_state(question, imported_fingerprint)

                return question.package_path

            if question.package_url and (question.raw_package or question.main_library != self._python_question_machine_name):
                raw_fingerprint = self._fingerprint_payload(
                    {
                        "mode": "raw",
                        "packageUrl": question.package_url,
                        "mainLibrary": question.main_library,
                        "sourceFingerprint": source_fingerprint,
                    }
                )
                if self._can_reuse_package(question, raw_fingerprint):
                    return question.package_path
                self._download_file(question.package_url, question.package_path)
                self._write_build_state(question, raw_fingerprint)
                return question.package_path

            self._ensure_h5p_runtime_libraries()
            h5p_json = self.build_h5p_metadata(question)
            content_json = self._build_h5p_content(question)
            self._apply_due_date(content_json, question.due_date)
            required_libraries = self._collect_required_library_dirs(question.main_library)
            scratch_fingerprint = self._fingerprint_payload(
                {
                    "mode": "scratch",
                    "metadata": h5p_json,
                    "content": content_json,
                    "sourceFingerprint": "",
                    "libraryFingerprint": self._libraries_fingerprint(required_libraries),
                    "archiveFilterVersion": self._ARCHIVE_FILTER_VERSION,
                }
            )
            if self._can_reuse_package(question, scratch_fingerprint):
                return question.package_path

            if question.build_exploded_dir.exists():
                shutil.rmtree(question.build_exploded_dir)
            self._ensure_directory(question.build_exploded_dir)

            shared_libraries = list(required_libraries)

            self._ensure_directory(question.build_exploded_dir)
            atomic_write_text(question.build_exploded_dir / "h5p.json", json.dumps(h5p_json, ensure_ascii=False, indent=2) + "\n")
            self._write_h5p_content_files(question.build_exploded_dir, content_json)

            self._write_package_archive(question, shared_libraries=shared_libraries, source_dir=question.build_exploded_dir)

            final_scratch_fingerprint = self._fingerprint_payload(
                {
                    "mode": "scratch",
                    "metadata": h5p_json,
                    "content": content_json,
                    "sourceFingerprint": "",
                    "libraryFingerprint": self._libraries_fingerprint(required_libraries),
                    "archiveFilterVersion": self._ARCHIVE_FILTER_VERSION,
                }
            )
            self._write_build_state(question, final_scratch_fingerprint)

            return question.package_path

    def _normalize_metadata_dependencies(
        self,
        metadata_payload: dict[str, object],
        library_dirs: list[Path],
    ) -> dict[str, object]:
        """Replace preloadedDependencies version numbers with the actual installed versions."""
        installed: dict[str, tuple[int, int]] = {}
        for lib_dir in library_dirs:
            try:
                lib_json = self._read_json(lib_dir / "library.json")
                machine_name = str(lib_json.get("machineName") or "")
                major = lib_json.get("majorVersion")
                minor = lib_json.get("minorVersion")
                if machine_name and isinstance(major, int) and isinstance(minor, int):
                    installed[machine_name] = (major, minor)
            except (OSError, ValueError):
                continue

        dependencies = metadata_payload.get("preloadedDependencies", [])
        if not isinstance(dependencies, list):
            return metadata_payload

        updated: list[object] = []
        for dep in dependencies:
            if not isinstance(dep, dict):
                updated.append(dep)
                continue
            machine_name = str(dep.get("machineName") or "")
            if machine_name in installed:
                major, minor = installed[machine_name]
                updated.append({**dep, "majorVersion": major, "minorVersion": minor})
            else:
                updated.append(dep)

        return {**metadata_payload, "preloadedDependencies": updated}

    def _normalize_imported_python_question_metadata(
        self,
        question: PythonQuestionBlock,
        metadata_payload: dict[str, object],
    ) -> dict[str, object]:
        """Fill required H5P metadata fields when imported sidecar metadata is incomplete."""
        baseline = self.build_h5p_metadata(question)

        metadata_payload["majorVersion"] = baseline["majorVersion"]
        metadata_payload["minorVersion"] = baseline["minorVersion"]

        dependencies = metadata_payload.get("preloadedDependencies")
        if not isinstance(dependencies, list) or not dependencies:
            metadata_payload["preloadedDependencies"] = baseline["preloadedDependencies"]
        else:
            baseline_dependencies = {
                dependency.get("machineName"): dependency
                for dependency in baseline["preloadedDependencies"]
                if isinstance(dependency, dict)
            }
            metadata_payload["preloadedDependencies"] = [
                baseline_dependencies.get(dependency.get("machineName"), dependency)
                if isinstance(dependency, dict)
                else dependency
                for dependency in dependencies
            ]

        metadata_payload["majorVersion"] = baseline["majorVersion"]
        metadata_payload["minorVersion"] = baseline["minorVersion"]
        if not isinstance(metadata_payload.get("embedTypes"), list):
            metadata_payload["embedTypes"] = baseline["embedTypes"]

        metadata_payload.setdefault("language", baseline["language"])
        metadata_payload.setdefault("defaultLanguage", baseline["defaultLanguage"])
        metadata_payload.setdefault("license", baseline["license"])
        return metadata_payload
