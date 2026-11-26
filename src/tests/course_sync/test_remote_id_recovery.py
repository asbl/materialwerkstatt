from types import SimpleNamespace

import pytest

from course_sync.moodle_workflows import MoodleWorkflows


def test_recovery_requires_unique_titles_and_unoccupied_ids():
    workflow = MoodleWorkflows(None)
    expected = [
        {"identifier": "known", "title": "Known", "activityId": 1},
        {"identifier": "ok", "title": "Klassen", "activityId": 0},
        {"identifier": "ambiguous", "title": "Methods", "activityId": 0},
        {"identifier": "local-a", "title": "Duplicate", "activityId": 0},
        {"identifier": "local-b", "title": "Duplicate", "activityId": 0},
        {"identifier": "occupied", "title": "Occupied", "activityId": 0},
        {"identifier": "absent", "title": "Absent", "activityId": 0},
    ]
    activities = [
        {"id": 2, "title": "Test: Klassen"},
        {"id": 2, "title": "Test: Klassen"},  # repeated link, same activity
        {"id": 3, "title": "Methods"}, {"id": 4, "title": "Methods"},
        {"id": 5, "title": "Duplicate"}, {"id": 1, "title": "Occupied"},
    ]
    assert workflow._recover_verification_ids(expected, activities) == {"ok": 2}


def test_exact_titles_distinguish_lesson_and_test_with_same_subject():
    workflow = MoodleWorkflows(None)
    expected = [
        {"identifier": "lesson", "title": "Methoden verändern Zustand", "activityId": 0},
        {"identifier": "test", "title": "test: Methoden verändern Zustand", "activityId": 0},
    ]
    activities = [
        {"id": 10, "title": "Methoden verändern Zustand"},
        {"id": 11, "title": "Test: Methoden verändern Zustand"},
    ]
    assert workflow._recover_verification_ids(expected, activities) == {"lesson": 10, "test": 11}


@pytest.mark.parametrize("confirm_heading", [False, True])
@pytest.mark.parametrize("section_urls", [[], ["https://school.example.org/course/section.php?id=8"]])
@pytest.mark.parametrize("frame_text,use_integration,renamed", [
    ("Expected content " + "x" * 600, False, False),
    ("Expected content", False, False),
    ("Short quiz", True, False),
    ("Short quiz", True, True),
    ("Expected content", False, True),
    ("Good Expected content", False, True),
])
def test_verification_only_persists_content_confirmed_ids(tmp_path, monkeypatch, section_urls, frame_text, use_integration, renamed, confirm_heading):
    import json
    import playwright.sync_api
    from zipfile import ZipFile

    content = {"editorSettings": {"startingCode": "print(1)"}}
    package = tmp_path / "good.h5p"
    with ZipFile(package, "w") as archive:
        archive.writestr("content/content.json", json.dumps(content))
    frame = SimpleNamespace(locator=lambda selector: SimpleNamespace(
        inner_text=lambda **kwargs: frame_text),
        evaluate=lambda script: [json.dumps(content)] if use_integration else [])
    visited = []
    page = SimpleNamespace(
        url="https://school.example.org/course/view.php?id=7",
        set_default_timeout=lambda value: None,
        goto=lambda url, **kwargs: visited.append(url),
        wait_for_timeout=lambda value: None,
        frames=[frame], main_frame=object(), evaluate=lambda script: section_urls,
        locator=lambda selector: SimpleNamespace(all_text_contents=lambda: ["Wrong content"] if confirm_heading else ["Another title"]),
    )
    context = SimpleNamespace(new_page=lambda: page, close=lambda: None,
                              storage_state=lambda **kwargs: None)
    browser = SimpleNamespace(new_context=lambda **kwargs: context, close=lambda: None)

    class PlaywrightContext:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", PlaywrightContext)
    ids_path = tmp_path / ".moodle-activity-ids-school.json"
    ids_path.write_text('{"existing": 99}\n')
    uploader = SimpleNamespace(
        _login_if_needed=lambda page: None,
        _wait_for_manual_login_confirmation=lambda page: None,
        _return_to_course_after_login=lambda page: None,
        _collect_section_h5p_activity_order=lambda page, selector: [
            {"id": 1, "title": "Old title" if renamed else "Good"}, {"id": 2, "title": "Wrong content"}],
    )
    app = SimpleNamespace(
        moodle_client_resolver=lambda: SimpleNamespace(load_dotenv_file=lambda: None),
        sync_course=lambda course: None,
        _resolve_moodle_course_url=lambda *args: "https://school.example.org/course/view.php?id=7",
        _resolve_moodle_storage_state=lambda *args: tmp_path / "state.json",
        _load_target_config=lambda *args: {},
        _target_auth_uses_credentials=lambda config: False,
        _remote_verification_expectations=lambda *args: [
            {"identifier": "existing", "title": "Existing", "activityId": 99, "signals": ["Expected content"]},
            {"identifier": "good", "title": "Good", "activityId": 0, "signals": ["Expected content"], "packagePath": str(package)},
            {"identifier": "bad", "title": "Wrong content", "activityId": 0, "signals": ["Missing signal"]},
        ],
        MoodlePlaywrightUploader=lambda **kwargs: uploader,
        _moodle_base_url=lambda url: "https://school.example.org",
        _load_target_activity_ids=lambda *args: json.loads(ids_path.read_text()),
        _target_activity_ids_path=lambda *args: ids_path,
    )
    workflow = MoodleWorkflows(app)
    results = workflow.verify_moodle_course(tmp_path, target="school", headless=True, missing_ids_only=True)
    good_confirmed = not renamed or use_integration or frame_text.startswith("Good ")
    assert [result["ok"] for result in results] == [good_confirmed, False]
    assert results[0]["contentEqual"] == use_integration
    expected_ids = {"existing": 99}
    if good_confirmed:
        expected_ids["good"] = 1
    if confirm_heading:
        expected_ids["bad"] = 2
    assert json.loads(ids_path.read_text()) == expected_ids
    assert not list(tmp_path.glob(".moodle-sync-state*"))

    assert not any("view.php?id=99" in url for url in visited)
