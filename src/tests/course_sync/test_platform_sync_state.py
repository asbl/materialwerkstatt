from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from course_sync.application import CourseApplication
from course_sync.classes.platform_sync_state import (
    load_site_export_state,
    load_target_sync_state,
    record_site_export_state,
    record_target_sync_state,
    site_export_state_path,
    target_sync_state_path,
)
from course_sync.config import settings


@pytest.fixture()
def application(tmp_path):
    application = CourseApplication(settings.build_app_config().with_root(tmp_path))
    course = application.COURSES_DIR / "demo"
    course.mkdir(parents=True)
    (course / "index.mdx").write_text("# Demo\n", encoding="utf-8")
    application.parse_course = lambda path: ("Demo", [], (path / "index.mdx").read_text())
    application.render_course_page = lambda path, **kwargs: kwargs["rendered_source"]
    return application


def test_target_sync_state_merges_uploads(tmp_path):
    record_target_sync_state(tmp_path, "schule", {"a": "hash-a", "b": "hash-b"})
    record_target_sync_state(tmp_path, "schule", {"b": "hash-b2", "c": ""})

    state = load_target_sync_state(tmp_path, "schule")
    assert {identifier: entry["hash"] for identifier, entry in state.items()} == {"a": "hash-a", "b": "hash-b2"}
    assert all(entry["uploadedAt"] for entry in state.values())
    assert load_target_sync_state(tmp_path, "anderes") == {}


def test_unreadable_state_counts_as_not_recorded(tmp_path):
    target_sync_state_path(tmp_path, "schule").write_text("{kaputt", encoding="utf-8")
    site_export_state_path(tmp_path, tmp_path / "site").parent.mkdir(parents=True)
    site_export_state_path(tmp_path, tmp_path / "site").write_text("[]", encoding="utf-8")

    assert load_target_sync_state(tmp_path, "schule") == {}
    assert load_site_export_state(tmp_path, tmp_path / "site") == {}


def test_target_upload_records_hashes_captured_before_the_upload(application):
    course = application.COURSES_DIR / "demo"
    questions = [SimpleNamespace(identifier="a"), SimpleNamespace(identifier="b")]
    application.parse_course = lambda path: ("Demo", questions, "")
    application.compute_question_hash = lambda question: f"hash-{question.identifier}"

    before_upload = application._current_question_hashes(course, {"a", "b"})
    # Der Nutzer aendert waehrend des Uploads "a": gespeichert wird der hochgeladene Stand.
    application.compute_question_hash = lambda question: f"geaendert-{question.identifier}"
    application._store_target_activity_ids(course, "schule", [
        SimpleNamespace(identifier="a", activity_id=5, title="A"),
        SimpleNamespace(identifier="b", activity_id=0, title="B"),
    ], before_upload)

    assert json.loads((course / ".moodle-activity-ids-schule.json").read_text(encoding="utf-8")) == {"a": 5}
    state = load_target_sync_state(course, "schule")
    assert {identifier: entry["hash"] for identifier, entry in state.items()} == {"a": "hash-a"}


def test_target_upload_survives_unreadable_course(application, capsys):
    course = application.COURSES_DIR / "demo"

    def broken(path):
        raise ValueError("Kurs defekt")

    application.parse_course = broken
    application._store_target_activity_ids(course, "schule", [SimpleNamespace(identifier="a", activity_id=5, title="A")])

    assert json.loads((course / ".moodle-activity-ids-schule.json").read_text(encoding="utf-8")) == {"a": 5}
    assert load_target_sync_state(course, "schule") == {}
    assert "Sync-Stand" in capsys.readouterr().out


def test_default_moodle_metadata_uses_hashes_captured_before_the_upload(application):
    from course_sync.classes.models import SyncMetadata

    course = application.COURSES_DIR / "demo"
    application._SYNC_METADATA_STORE.save(course, SyncMetadata("demo", 3, "https://moodle.example.org"))
    results = [SimpleNamespace(identifier="a", activity_id=5, title="A")]

    application._store_uploaded_activity_ids(course, results, {"a": "hash-vor-upload"})

    assert application.load_sync_metadata(course).entries["a"].local_hash == "hash-vor-upload"


def test_failing_hash_capture_does_not_break_the_upload(application, capsys):
    course = application.COURSES_DIR / "demo"
    application.parse_course = lambda path: (_ for _ in ()).throw(ValueError("Kurs defekt"))

    assert application._current_question_hashes(course) == {}
    assert "nicht bestimmbar" in capsys.readouterr().out


def test_site_export_keeps_its_state_out_of_the_published_site(application, tmp_path):
    output = tmp_path / "public"
    application.export_static_site(output, application.COURSES_DIR / "demo")

    assert load_site_export_state(application.COURSE_BUILD_DIR, output) == {"demo": {}}
    assert not [path for path in output.rglob("*") if "state" in path.name]
    manifest = json.loads((output / ".course-sync-export-manifest.json").read_text(encoding="utf-8"))
    assert not [name for name in manifest["files"] if "state" in name]


def test_exporting_one_course_keeps_the_state_of_the_others(tmp_path):
    build, output = tmp_path / "build", tmp_path / "public"
    record_site_export_state(build, output, {"a": {"x": "1"}, "b": {"y": "2"}})
    record_site_export_state(build, output, {"a": {"x": "neu", "z": "3"}})

    assert load_site_export_state(build, output) == {"a": {"x": "neu", "z": "3"}, "b": {"y": "2"}}
    assert load_site_export_state(build, tmp_path / "anderer-ordner") == {}


def test_failed_export_does_not_touch_the_recorded_state(application, tmp_path):
    output = tmp_path / "public"
    course = application.COURSES_DIR / "demo"
    application.export_static_site(output, course)
    before = site_export_state_path(application.COURSE_BUILD_DIR, output).read_text(encoding="utf-8")

    def broken_renderer(*args, **kwargs):
        raise ValueError("Renderer defekt")

    application.render_course_page = broken_renderer
    with pytest.raises(ValueError, match="Renderer defekt"):
        application.export_static_site(output, course)
    assert site_export_state_path(application.COURSE_BUILD_DIR, output).read_text(encoding="utf-8") == before


def test_forget_target_sync_state_removes_only_named_entries(tmp_path):
    from course_sync.classes.platform_sync_state import forget_target_sync_state

    record_target_sync_state(tmp_path, "schule", {"a": "hash-a", "b": "hash-b"})
    forget_target_sync_state(tmp_path, "schule", {"a", "unbekannt"})

    assert set(load_target_sync_state(tmp_path, "schule")) == {"b"}


def test_delete_stale_target_activities_only_removes_known_missing_ids(tmp_path):
    from types import SimpleNamespace

    from course_sync.classes.platform_sync_state import load_target_sync_state
    from course_sync.moodle_workflows import MoodleWorkflows

    (tmp_path / ".moodle-activity-ids-schule.json").write_text(
        json.dumps({"alt": 11, "bleibt": 12, "weg": 13}), encoding="utf-8"
    )
    record_target_sync_state(tmp_path, "schule", {"alt": "h1", "bleibt": "h2", "weg": "h3"})
    deleted_calls: list[list[int]] = []

    class FakeUploader:
        def __init__(self, **kwargs):
            pass

        def delete_h5p_activities(self, ids):
            deleted_calls.append(list(ids))
            return [11]  # 13 bleibt auf dem Ziel erhalten (Loeschen fehlgeschlagen)

    workflow = MoodleWorkflows(None)
    application = SimpleNamespace(MoodlePlaywrightUploader=FakeUploader)
    application._load_target_activity_ids = lambda course, target: workflow._load_target_activity_ids.__func__(
        SimpleNamespace(application=application), course, target
    )
    application._target_activity_ids_path = lambda course, target: course / f".moodle-activity-ids-{target}.json"
    workflow.application = application

    result = workflow._delete_stale_target_activities(
        tmp_path,
        "schule",
        current_identifiers={"bleibt"},
        course_url="https://example.org/course/view.php?id=1",
        username=None,
        password=None,
        storage_state=None,
        headless=True,
        timeout_ms=1000,
    )

    assert deleted_calls == [[11, 13]]
    assert result == [11]
    remaining = json.loads((tmp_path / ".moodle-activity-ids-schule.json").read_text(encoding="utf-8"))
    assert remaining == {"bleibt": 12, "weg": 13}
    assert set(load_target_sync_state(tmp_path, "schule")) == {"bleibt", "weg"}
