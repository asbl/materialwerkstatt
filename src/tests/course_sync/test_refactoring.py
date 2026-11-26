from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from course_sync.application import CourseApplication
from course_sync.classes.content_types import activity_to_content_type
from course_sync.classes.models import CourseActivity, PythonQuestionBlock, SyncMetadata
from course_sync.config import settings
from material_core import filesystem, publication


@pytest.fixture()
def application(tmp_path):
    application = CourseApplication(settings.build_app_config().with_root(tmp_path))
    course = application.COURSES_DIR / "demo"
    course.mkdir(parents=True)
    (course / "index.mdx").write_text("# Demo\n", encoding="utf-8")
    application.parse_course = lambda path: ("Demo", [], (path / "index.mdx").read_text())
    application.render_course_page = lambda path, **kwargs: kwargs["rendered_source"]
    return application


def snapshot(directory):
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in directory.rglob("*") if path.is_file()}


def test_export_rejects_unknown_nonempty_output(application, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    original = output / "important.txt"
    original.write_text("Original")
    with pytest.raises(ValueError, match="kein Exportmanifest"):
        application.export_static_site(output, application.COURSES_DIR / "demo")
    assert snapshot(output) == {"important.txt": b"Original"}


def test_failed_export_preserves_all_published_files(application, tmp_path):
    output = tmp_path / "public"
    course = application.COURSES_DIR / "demo"
    application.export_static_site(output, course)
    before = snapshot(output)

    def broken_renderer(*args, **kwargs):
        raise ValueError("Renderer defekt")

    application.render_course_page = broken_renderer
    with pytest.raises(ValueError, match="Renderer defekt"):
        application.export_static_site(output, course)
    assert snapshot(output) == before
    assert not list(tmp_path.glob(".course-export-*"))


@pytest.mark.parametrize("files", [["../important.txt"], ["/tmp/important.txt"], ["."], [12], [".course-sync-export-manifest.json"]])
def test_export_rejects_invalid_manifest_paths(application, tmp_path, files):
    output = tmp_path / "public"
    output.mkdir()
    (output / ".course-sync-export-manifest.json").write_text(json.dumps({"version": 1, "files": files}))
    before = snapshot(output)
    with pytest.raises(ValueError):
        application.export_static_site(output, application.COURSES_DIR / "demo")
    assert snapshot(output) == before


def test_export_prunes_only_owned_files(application, tmp_path):
    output = tmp_path / "public"
    course = application.COURSES_DIR / "demo"
    application.export_static_site(output, course, "https://example.org")
    inode = output.stat().st_ino
    assert (output / "index.html").stat().st_mode & 0o777 == 0o644
    (output / "private.txt").write_text("Keep")
    application.export_static_site(output, course)
    assert not (output / "CNAME").exists()
    assert (output / "private.txt").read_text() == "Keep"
    assert output.stat().st_ino == inode


def test_export_does_not_overwrite_unowned_file(application, tmp_path):
    output = tmp_path / "public"
    course = application.COURSES_DIR / "demo"
    application.export_static_site(output, course)
    (output / "CNAME").write_text("Private")
    before = snapshot(output)
    with pytest.raises(ValueError, match="fremde Datei"):
        application.export_static_site(output, course, "https://example.org")
    assert snapshot(output) == before


def test_publication_rolls_back_after_copy_error(tmp_path, monkeypatch):
    staging = tmp_path / "work" / "site"
    destination = tmp_path / "public"
    staging.mkdir(parents=True)
    destination.mkdir()
    for name in ("a.txt", "b.txt", "manifest.json"):
        (staging / name).write_text("New")
        (destination / name).write_text("Old")
    original_copy = publication.atomic_copy_file
    failed = False

    def fail_once(source, target):
        nonlocal failed
        if source == staging / "b.txt" and not failed:
            failed = True
            raise OSError("Datenträgerfehler")
        original_copy(source, target)

    monkeypatch.setattr(publication, "atomic_copy_file", fail_once)
    with pytest.raises(OSError, match="Datenträgerfehler"):
        publication.publish_files(staging, destination, {"a.txt", "b.txt"}, {"a.txt", "b.txt"}, "manifest.json")
    assert all(path.read_text() == "Old" for path in destination.iterdir())


def test_staged_copy_does_not_modify_hardlinked_published_file(application, tmp_path):
    published = tmp_path / "published.h5p"
    staged = tmp_path / "staged.h5p"
    source = tmp_path / "source.h5p"
    published.write_bytes(b"Previous package")
    os.link(published, staged)
    source.write_bytes(b"New package")
    application.site_exporter._copy_file_if_changed(source, staged)
    assert published.read_bytes() == b"Previous package"
    assert staged.read_bytes() == b"New package"


def test_export_rejects_symlink_in_owned_path(application, tmp_path):
    output = tmp_path / "public"
    course = application.COURSES_DIR / "demo"
    application.export_static_site(output, course)
    external = tmp_path / "external.txt"
    external.write_text("Keep")
    (output / "index.html").unlink()
    (output / "index.html").symlink_to(external)
    with pytest.raises(ValueError):
        application.export_static_site(output, course)
    assert external.read_text() == "Keep"


def test_preview_detects_same_size_sidecar_changes_and_deletion(application):
    course = application.COURSES_DIR / "demo"
    sidecar = course / "h5p" / "quiz" / "content.yml"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("Old")
    parses = []

    def parse(path):
        parses.append(path)
        return "Demo", [], sidecar.read_text() if sidecar.exists() else "Missing"

    application.parse_course = parse
    assert application.load_course_preview_state(course)[1] == "Old"
    assert application.load_course_preview_state(course)[1] == "Old"
    timestamp = sidecar.stat().st_mtime_ns
    sidecar.write_text("New")
    os.utime(sidecar, ns=(timestamp, timestamp))
    assert application.load_course_preview_state(course)[1] == "New"
    sidecar.unlink()
    assert application.load_course_preview_state(course)[1] == "Missing"
    assert len(parses) == 3


def test_preview_ignores_generated_files_but_tracks_config(application):
    course = application.COURSES_DIR / "demo"
    parser = application.mdx_course_parser()
    fingerprint = parser.source_fingerprint(course)
    (course / "build").mkdir()
    (course / "build" / "result.h5p").write_bytes(b"Generated")
    assert parser.source_fingerprint(course) == fingerprint
    (course / "course.yml").write_text("language: en")
    assert parser.source_fingerprint(course) != fingerprint


def test_applications_have_independent_configuration_and_state(application, tmp_path):
    other = CourseApplication(settings.build_app_config().with_root(tmp_path / "other"))
    application.PREVIEW_CACHE["demo"] = ("hash", [], "Cached")
    assert other.PREVIEW_CACHE == {}
    assert other.WORKSPACE_LOCK is not application.WORKSPACE_LOCK
    assert other.mdx_course_parser() is not application.mdx_course_parser()
    assert other.APP_CONFIG.root_dir == tmp_path / "other"
    assert other._SYNC_METADATA_STORE is not application._SYNC_METADATA_STORE
    application.H5P_LIBRARY_ASSET_PREFIXES["Private.Library"] = "private"
    assert "Private.Library" not in other.H5P_LIBRARY_ASSET_PREFIXES


def test_application_templates_use_the_configured_dotenv(application):
    application.DOTENV_FILE.write_text("SITE_DESCRIPTION=Local project description\n")
    html = application.template_renderer().render_index([application.COURSES_DIR / "demo"])
    assert "Local project description" in html


@pytest.mark.parametrize("layout", ["h5p/unit/quiz", "chapters/unit/quiz"])
def test_activity_adapters_share_source_and_build_paths(application, layout):
    from course_sync import main

    activity = CourseActivity(identifier="quiz", title="Quiz", instructions="", course_dir=application.COURSES_DIR / "demo", course_slug="demo", h5p_subdir="unit", source_package_path=layout)
    adapter = activity_to_content_type(activity)
    assert PythonQuestionBlock is CourseActivity
    assert main.PythonQuestionBlock is CourseActivity
    assert adapter.package_path == activity.package_path
    assert adapter.exploded_dir == activity.exploded_dir == activity.course_dir / layout
    assert adapter.build_exploded_dir == activity.build_exploded_dir
    assert activity.build_exploded_dir.is_relative_to(activity.course_dir / "build")


def test_atomic_metadata_failure_preserves_previous_json(application, monkeypatch):
    course = application.COURSES_DIR / "demo"
    previous = SyncMetadata("demo", 1, "https://example.invalid")
    target = application.save_sync_metadata(course, previous)
    before = target.read_bytes()

    def no_space(*args):
        raise OSError("Kein Speicherplatz")

    monkeypatch.setattr(filesystem.os, "fsync", no_space)
    with pytest.raises(OSError):
        application.save_sync_metadata(course, SyncMetadata("demo", 2, "https://example.invalid"))
    assert target.read_bytes() == before
    assert not list(course.glob(f".{target.name}.*"))


def test_release_test_task_runs_pytest(monkeypatch):
    import course_sync_tasks

    calls = []
    monkeypatch.setattr(course_sync_tasks, "_run_python", lambda context, *args: calls.append(args))
    course_sync_tasks.test.body(SimpleNamespace())
    assert calls == [("-m", "pytest", "src/tests/course_sync", "-q")]


def test_raw_h5p_sources_survive_build_and_sync(application):
    course = application.COURSES_DIR / "demo"
    source = course / "h5p" / "quiz.h5p"
    source.parent.mkdir()
    with ZipFile(source, "w") as archive:
        archive.writestr("h5p.json", '{"mainLibrary": "H5P.MultiChoice"}')
        archive.writestr("content/content.json", "{}")
    unrelated = source.parent / "unreferenced.h5p"
    unrelated.write_bytes(b"Authored archive")
    before = source.read_bytes()
    activity = CourseActivity(identifier="quiz", title="Quiz", instructions="", course_dir=course, course_slug="demo", raw_package=True, source_package_path="h5p/quiz.h5p")
    application.parse_course = lambda path: ("Demo", [activity], "")
    application.sync_course(course)
    assert source.read_bytes() == before
    assert activity.package_path.read_bytes() == before
    assert unrelated.read_bytes() == b"Authored archive"


def test_imported_h5p_build_preserves_authored_sidecars(application):
    course = application.COURSES_DIR / "demo"
    source = course / "chapters" / "unit" / "quiz"
    (source / "content").mkdir(parents=True)
    metadata = {"mainLibrary": "H5P.MultiChoice", "title": "Authored", "preloadedDependencies": []}
    (source / "h5p.json").write_text(json.dumps(metadata))
    (source / "content" / "content.json").write_text('{"question": "Original?"}')
    before = snapshot(source)
    activity = CourseActivity(identifier="quiz", title="Built title", instructions="", main_library="H5P.MultiChoice", course_dir=course, course_slug="demo", h5p_subdir="unit", source_package_path="chapters/unit/quiz", h5p_metadata=metadata, h5p_content={"question": "New?"})
    application.ensure_h5p_runtime_libraries = lambda: None
    application.collect_required_library_dirs_from_metadata = lambda payload: []
    package = application.write_h5p_package(activity)
    timestamp = package.stat().st_mtime_ns
    application.write_h5p_package(activity)
    assert package.stat().st_mtime_ns == timestamp
    assert snapshot(source) == before
    assert (activity.build_exploded_dir / "h5p.json").is_file()
    with ZipFile(package) as archive:
        assert json.loads(archive.read("content/content.json"))["question"] == "New?"
