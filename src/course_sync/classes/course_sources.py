from __future__ import annotations

import hashlib
from pathlib import Path


GENERATED_DIRECTORIES = {"build", "pdf", "node_modules", "__pycache__"}


def course_source_files(course_dir: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in course_dir.rglob("*")
            if path.is_file()
            and path.relative_to(course_dir).parts[0] != "tests"
            and not any(
                part.startswith(".") or part in GENERATED_DIRECTORIES
                for part in path.relative_to(course_dir).parts
            )
        )
    )


def course_source_fingerprint(course_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in course_source_files(course_dir):
        name = path.relative_to(course_dir).as_posix().encode("utf-8")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        with path.open("rb") as source:
            content = hashlib.file_digest(source, "sha256").digest()
        digest.update(content)
    return digest.hexdigest()
