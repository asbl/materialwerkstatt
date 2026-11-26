"""Install the standard H5P libraries required by the static exporter.

Custom course libraries are downloaded by ``course-sync update-h5p-libraries``.
The upstream H5P libraries below do not provide compatible release archives, so
CI and Codespaces seed them from their pinned Git tags.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from material_core import workspace


ROOT = workspace.root()
TARGET_ROOT = ROOT / ".h5p-runtime" / "libraries"

LIBRARIES = (
    ("h5p", "h5p-question", "1.5.47", "H5P.Question-1.5"),
    ("h5p", "h5p-image", "1.1.23", "H5P.Image-1.1"),
    ("h5p", "h5p-multi-choice", "1.16.14", "H5P.MultiChoice-1.16"),
    ("h5p", "h5p-question-set", "1.20.31", "H5P.QuestionSet-1.20"),
    ("h5p", "h5p-video", "1.6.71", "H5P.Video-1.6"),
    ("h5p", "h5p-joubel-ui", "1.3.32", "H5P.JoubelUI-1.3"),
    ("h5p", "h5p-transition", "1.0.4", "H5P.Transition-1.0"),
    ("h5p", "h5p-font-icons", "1.0.6", "H5P.FontIcons-1.0"),
    ("h5p", "font-awesome", "4.5.6", "FontAwesome-4.5"),
    ("h5p", "jquery-ui", "1.10.22", "jQuery.ui-1.10"),
    ("h5p", "h5p-components", "1.0.89", "H5P.Components-1.0"),
)


def main() -> None:
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        for organisation, repository, tag, destination in LIBRARIES:
            clone_path = temporary_root / repository
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    tag,
                    f"https://github.com/{organisation}/{repository}.git",
                    str(clone_path),
                ],
                check=True,
            )
            target_path = TARGET_ROOT / destination
            if target_path.exists():
                shutil.rmtree(target_path)
            shutil.copytree(
                clone_path,
                target_path,
                ignore=shutil.ignore_patterns(".git", "node_modules"),
            )


if __name__ == "__main__":
    main()
