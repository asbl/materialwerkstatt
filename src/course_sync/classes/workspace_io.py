from __future__ import annotations

import json
from pathlib import Path

from material_core.filesystem import atomic_write_text

from .content_store import ContentStore


class WorkspaceIO:
    """Generic filesystem and content helpers used by composition root wiring."""

    def __init__(self, *, content_store: ContentStore) -> None:
        self._content_store = content_store

    def ensure_directory(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def read_yaml(self, path: Path) -> object:
        return self._content_store.read_yaml(path)

    def read_json_or_default(self, path: Path, default: dict) -> dict:
        if not path.exists():
            return default

        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return default

        return json.loads(content)

    def write_json(self, path: Path, payload: dict) -> None:
        atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    def read_h5p_content_payload(self, source_dir: Path) -> dict[str, object]:
        return self._content_store.read_h5p_content_payload(source_dir)

    def write_h5p_content_files(
        self, target_dir: Path, payload: dict[str, object], *, use_frontmatter: bool = False
    ) -> None:
        self._content_store.write_h5p_content_files(target_dir, payload, use_frontmatter=use_frontmatter)
