from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    courses_dir: Path
    course_build_dir: Path
    default_port: int
    dotenv_file: Path
    h5p_runtime_dir: Path
    h5p_runtime_content_dir: Path
    h5p_runtime_libraries_dir: Path
    h5p_runtime_downloads_dir: Path
    h5p_runtime_port: int
    runtime_proxy_prefix: str
    h5p_library_release_repo: str
    h5p_library_release_tag: str
    h5p_library_asset_prefixes: dict[str, str]
    h5p_library_extra_assets: list[dict[str, str]]
    custom_h5p_library_short_names: dict[str, str]
    python_question_machine_name: str
    placeholder_template: str
    sync_metadata_file: str
    h5p_sidecar_dirname: str
    tag_re: re.Pattern[str]
    fence_re: re.Pattern[str]
    html_tag_re: re.Pattern[str]
    whitespace_re: re.Pattern[str]
    h5p_embed_iframe_re: re.Pattern[str]
    mbz_link_re: re.Pattern[str]

    def with_root(self, root: Path) -> AppConfig:
        root = root.resolve()
        runtime = root / ".h5p-runtime"
        return replace(
            self,
            root_dir=root,
            courses_dir=root / "unterricht" / "kurse",
            course_build_dir=root / "build" / "kurse",
            dotenv_file=root / ".env",
            h5p_runtime_dir=runtime,
            h5p_runtime_content_dir=runtime / "content",
            h5p_runtime_libraries_dir=runtime / "libraries",
            h5p_runtime_downloads_dir=runtime / "downloads",
        )
