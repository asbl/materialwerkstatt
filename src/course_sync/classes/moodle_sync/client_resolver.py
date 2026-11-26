from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, MutableMapping

from material_core.dotenv import load_dotenv_file as _load_dotenv_file

from .api_client import MoodleApiClient
from .backup_extractor import MoodleBackupExtractor


class MoodleClientResolver:
    """Builds Moodle API clients and loads .env configuration values."""

    def __init__(
        self,
        *,
        dotenv_file: Path,
        make_stable_identifier: Callable[[str, set[str]], str],
        strip_html: Callable[[str], str],
        fetch_text: Callable[[str], str],
        extract_h5p_package_url_from_activity_html: Callable[[str, str], str],
        download_file: Callable[[str, Path], None],
        moodle_backup_extractor_factory: Callable[[], MoodleBackupExtractor],
        build_imported_question_from_h5p_package: Callable[[str, object, dict[str, object], dict[str, object]], object],
        write_source_package_sidecar: Callable[[object, Path], str],
        environ: MutableMapping[str, str] | None = None,
    ) -> None:
        self._dotenv_file = dotenv_file
        self._make_stable_identifier = make_stable_identifier
        self._strip_html = strip_html
        self._fetch_text = fetch_text
        self._extract_h5p_package_url_from_activity_html = extract_h5p_package_url_from_activity_html
        self._download_file = download_file
        self._moodle_backup_extractor_factory = moodle_backup_extractor_factory
        self._build_imported_question_from_h5p_package = build_imported_question_from_h5p_package
        self._write_source_package_sidecar = write_source_package_sidecar
        self._environ = environ if environ is not None else os.environ

    def load_dotenv_file(self, dotenv_path: Path | None = None) -> None:
        _load_dotenv_file(dotenv_path or self._dotenv_file, self._environ)

    def resolve_moodle_client(self, base_url: str | None = None, token: str | None = None) -> MoodleApiClient:
        self.load_dotenv_file()
        resolved_base_url = (base_url or self._environ.get("MOODLE_BASE_URL", "")).strip()
        resolved_token = (token or self._environ.get("MOODLE_TOKEN", "")).strip()
        if not resolved_base_url:
            raise RuntimeError(
                "MOODLE_BASE_URL ist nicht gesetzt. Kopiere .env.example nach .env und trage deine "
                "Moodle-Daten ein (oder gib --base-url an)."
            )
        if not resolved_token:
            raise RuntimeError(
                "MOODLE_TOKEN ist nicht gesetzt. Kopiere .env.example nach .env und trage deinen "
                "Webservice-Token ein (oder gib --token an)."
            )

        backup_extractor = self._moodle_backup_extractor_factory()
        return MoodleApiClient(
            resolved_base_url,
            resolved_token,
            make_stable_identifier=self._make_stable_identifier,
            strip_html=self._strip_html,
            fetch_text=self._fetch_text,
            extract_h5p_package_url_from_activity_html=lambda page_html: self._extract_h5p_package_url_from_activity_html(
                page_html,
                resolved_base_url,
            ),
            download_file=self._download_file,
            extract_h5p_package_from_course_backup=lambda base_url, activity, destination: backup_extractor.extract_h5p_package_from_course_backup(
                base_url,
                activity,
                destination,
            ),
            build_imported_question_from_h5p_package=self._build_imported_question_from_h5p_package,
            write_source_package_sidecar=self._write_source_package_sidecar,
        )
