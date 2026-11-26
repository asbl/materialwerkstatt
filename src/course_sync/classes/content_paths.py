from __future__ import annotations

from pathlib import Path
from material_core import workspace


DEFAULT_COURSES_DIR = workspace.root() / "unterricht" / "kurse"


class H5PContentsMixin:
    __slots__ = ()
    identifier: str
    course_dir: Path | None
    course_slug: str
    h5p_subdir: str = ""
    source_package_path: str = ""
    raw_package: bool = False
    build_dir: Path | None = None

    @property
    def build_root(self) -> Path:
        """Root of this question's build output.

        Normally set explicitly (see application.course_build_dir) so it lives
        centrally under <repo-root>/build/kurse/<course-slug>/, outside the
        unterricht/ source tree. Falls back to course_dir/build for call sites
        that construct a question directly without going through that wiring.
        """
        if self.build_dir is not None:
            return self.build_dir
        course_dir = self.course_dir or (DEFAULT_COURSES_DIR / self.course_slug)
        return course_dir / "build"

    @property
    def package_path(self) -> Path:
        build_dir = self.build_root / "h5p"
        return build_dir / self.h5p_subdir / f"{self.identifier}.h5p" if self.h5p_subdir else build_dir / f"{self.identifier}.h5p"

    @property
    def build_exploded_dir(self) -> Path:
        return self.build_root / "content" / self.h5p_subdir / self.identifier

    @property
    def build_hash_path(self) -> Path:
        hash_dir = self.build_root / "hashes"
        return hash_dir / self.h5p_subdir / f"{self.identifier}.build-hash" if self.h5p_subdir else hash_dir / f"{self.identifier}.build-hash"

    @property
    def h5p_dir(self) -> Path:
        course_dir = self.course_dir or (DEFAULT_COURSES_DIR / self.course_slug)
        return course_dir / "h5p" / self.h5p_subdir if self.h5p_subdir else course_dir / "h5p"

    @property
    def exploded_dir(self) -> Path:
        if self.source_package_path and not self.raw_package:
            candidate = (self.course_dir or (DEFAULT_COURSES_DIR / self.course_slug)) / self.source_package_path
            if candidate.suffix != ".h5p":
                return candidate
        return self.h5p_dir / self.identifier
