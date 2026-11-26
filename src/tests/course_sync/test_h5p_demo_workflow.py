from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from course_sync.classes.h5p_file_service import H5PFileService


ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent


def load_tasks_module():
    spec = importlib.util.spec_from_file_location("course_sync_tasks", ROOT_DIR / "src" / "course_sync_tasks.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load course_sync_tasks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class H5PDemoWorkflowTests(unittest.TestCase):
    def test_h5p_archive_filter_skips_library_development_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library_dir = Path(temp_dir) / "H5P.Components-1.0"
            library_dir.mkdir()
            (library_dir / ".h5pignore").write_text("src\neslint.config.mjs\n", encoding="utf-8")
            service = H5PFileService(
                courses_dir=ROOT_DIR / "unterricht" / "kurse",
                ensure_directory=lambda path: path.mkdir(parents=True, exist_ok=True),
                read_yaml=lambda _path: {},
                read_h5p_content_payload=lambda _path: {},
                write_h5p_content_files=lambda _path, _payload: None,
                write_json=lambda _path, _payload: None,
            )

            self.assertTrue(service._should_skip_archive_path("H5P.Components-1.0/LICENSE", archive_root=Path(temp_dir)))
            self.assertTrue(service._should_skip_archive_path("H5P.Components-1.0/eslint.config.mjs", archive_root=Path(temp_dir)))
            self.assertTrue(service._should_skip_archive_path("H5P.Components-1.0/vitest.config.mjs", archive_root=Path(temp_dir)))
            self.assertTrue(service._should_skip_archive_path("H5P.Components-1.0/src/components/button.js", archive_root=Path(temp_dir)))
            self.assertFalse(service._should_skip_archive_path("H5P.Components-1.0/dist/h5p-components.js", archive_root=Path(temp_dir)))

    def test_release_questions_workflow_orders_release_update_tests_and_demo_build(self) -> None:
        tasks = load_tasks_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            h5p_dev_dir = Path(temp_dir) / "h5p-dev"
            h5p_dev_dir.mkdir()

            calls: list[tuple[tuple[str, ...], Path]] = []

            def fake_run(args, *, check, cwd):
                self.assertTrue(check)
                calls.append((tuple(str(item) for item in args), Path(cwd)))
                return subprocess.CompletedProcess(args=args, returncode=0)

            with patch.object(tasks.subprocess, "run", side_effect=fake_run):
                tasks.release_questions_workflow.body(
                    None,
                    h5p_dev_dir=str(h5p_dev_dir),
                    course="h5p-demo",
                    english_course="h5p-demo-en",
                    tag="v6.90.0",
                    dry_run=True,
                )

        self.assertEqual(
            calls,
            [
                ((tasks._invoke_binary(h5p_dev_dir), "pack-all"), h5p_dev_dir.resolve()),
                ((tasks._invoke_binary(h5p_dev_dir), "deploy.release", "--all", "--dry-run"), h5p_dev_dir.resolve()),
                ((tasks.PYTHON, "-m", "course_sync.main", "update-h5p-libraries", "--tag", "v6.90.0"), ROOT_DIR),
                ((tasks.PYTHON, "-m", "pytest", "src/tests/course_sync", "-q"), ROOT_DIR),
                ((tasks.PYTHON, "-m", "course_sync.main", "build", "h5p-demo"), ROOT_DIR),
                ((tasks.PYTHON, "-m", "course_sync.main", "build", "h5p-demo-en"), ROOT_DIR),
            ],
        )


if __name__ == "__main__":
    unittest.main()
