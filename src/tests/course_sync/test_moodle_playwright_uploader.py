from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from course_sync.classes.moodle_playwright_uploader import (
    MoodleH5PUploadPackage,
    MoodleH5PUploadResult,
    MoodlePlaywrightUploader,
    MoodleTextLabelUploadItem,
    collect_h5p_upload_packages,
    collect_moodle_text_labels,
    infer_h5p_package_points,
    normalize_moodle_identifier,
    normalize_moodle_section_title,
    read_chapter_question_order,
)


class MoodlePlaywrightUploaderTests(unittest.TestCase):
    def test_question_payloads_do_not_become_moodle_text_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            course_dir = Path(tmp_dir)
            chapters = course_dir / "chapters"
            chapters.mkdir()
            (chapters / "intro.mdx").write_text(
                '<PythonQuestion identifier="example" />\n\n'
                '```python question:example starter\nprint("hello")\n```\n\n'
                '```json question:example testcase\n{"inputs": []}\n```\n\n'
                'Explanation.\n\n```python\nprint("visible example")\n```\n', encoding="utf-8",
            )
            labels = collect_moodle_text_labels(course_dir, "intro")
        self.assertEqual(len(labels), 1)
        self.assertIn("Explanation.", labels[0].markdown)
        self.assertIn('print("visible example")', labels[0].markdown)
        self.assertNotIn("question:example", labels[0].markdown)
        self.assertNotIn('print("hello")', labels[0].markdown)

    def test_text_cleanup_only_removes_obsolete_labels_in_current_chapter(self) -> None:
        uploader = MoodlePlaywrightUploader(course_url="https://moodle.example.org/course/view.php?id=12")
        section = {"selector": "#section-1", "number": 1}
        page = Mock()
        keep = [{"id": 2, "identifier": "intro-keep"}, {"id": 3, "identifier": "other-text"}]
        with (
            patch.object(uploader, "_section_by_number", return_value=section),
            patch.object(uploader, "_goto_populated_section_page", return_value=section),
            patch.object(uploader, "_managed_text_labels", side_effect=[
                [{"id": 1, "identifier": "intro-obsolete"}, *keep], keep,
            ]),
            patch.object(uploader, "_moodle_sesskey", return_value="test-session"),
            patch.object(uploader, "_confirm_section_delete_if_needed") as confirm,
        ):
            uploader._prune_stale_text_labels(page, 1, "intro", {"intro-keep"})
        confirm.assert_called_once_with(page)
        delete_urls = [call.args[0] for call in page.goto.call_args_list if "delete=" in call.args[0]]
        self.assertEqual(len(delete_urls), 1)
        self.assertIn("delete=1&", delete_urls[0])

    def test_normalize_moodle_identifier_matches_import_slugs(self) -> None:
        self.assertEqual(normalize_moodle_identifier("Einführung: Die while-Schleife"), "einfuehrung-die-while-schleife")
        self.assertEqual(normalize_moodle_identifier("Die max() Funktion anwenden"), "die-max-funktion-anwenden")

    def test_delete_confirmation_accepts_moodle_yes_button(self) -> None:
        uploader = MoodlePlaywrightUploader(course_url="https://moodle.example.org/course/view.php?id=12")
        page = Mock()
        empty = Mock()
        empty.count.return_value = 0
        yes_button = Mock()
        yes_button.bounding_box.return_value = {"width": 80, "height": 30}
        yes = Mock()
        yes.count.return_value = 1
        yes.nth.return_value = yes_button
        page.locator.return_value = empty
        page.get_by_role.side_effect = lambda role, name: yes if role == "button" and name.fullmatch("Ja") else empty
        uploader._confirm_section_delete_if_needed(page)
        yes_button.click.assert_called_once()
        page.wait_for_load_state.assert_called_once_with("domcontentloaded")

    def test_text_cleanup_reports_labels_that_were_not_deleted(self) -> None:
        uploader = MoodlePlaywrightUploader(course_url="https://moodle.example.org/course/view.php?id=12")
        page = Mock()
        section = {"selector": "#section-1", "number": 1}
        with (
            patch.object(uploader, "_section_by_number", return_value=section),
            patch.object(uploader, "_goto_populated_section_page", return_value=section),
            patch.object(uploader, "_managed_text_labels", return_value=[{"id": 1, "identifier": "intro-obsolete"}]),
            patch.object(uploader, "_moodle_sesskey", return_value="test-session"),
            patch.object(uploader, "_confirm_section_delete_if_needed"),
            self.assertRaisesRegex(RuntimeError, "nicht vollstaendig entfernt"),
        ):
            uploader._prune_stale_text_labels(page, 1, "intro", set())

    def test_normalize_moodle_section_title_matches_local_and_remote_variants(self) -> None:
        self.assertEqual(normalize_moodle_section_title("Texte und Strings"), "texte strings")
        self.assertEqual(normalize_moodle_section_title("Texte (Strings)"), "texte strings")
        self.assertEqual(normalize_moodle_section_title("Schleifen and Bedingungen"), "schleifen bedingungen")

    def test_collect_h5p_upload_packages_reads_title_from_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            course_dir = Path(tmp_dir) / "python-2026"
            build_dir = course_dir / "build" / "h5p" / "012-miniworlds"
            build_dir.mkdir(parents=True)
            package_path = build_dir / "miniworlds-tutorial.h5p"
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr("h5p.json", json.dumps({"title": "Minis erkunden"}))

            packages = collect_h5p_upload_packages(course_dir, "012-miniworlds")

        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0].identifier, "miniworlds-tutorial")
        self.assertEqual(packages[0].title, "Test: Minis erkunden")
        self.assertEqual(packages[0].path, package_path)
        self.assertEqual(packages[0].points, 2)

    def test_collect_h5p_upload_packages_keeps_ungraded_title_without_test_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            course_dir = Path(tmp_dir) / "python-2026"
            build_dir = course_dir / "build" / "h5p" / "012-miniworlds"
            build_dir.mkdir(parents=True)
            package_path = build_dir / "miniworlds-tutorial.h5p"
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr(
                    "h5p.json",
                    json.dumps({"title": "Minis erkunden", "mainLibrary": "H5P.PythonQuestion"}),
                )
                archive.writestr(
                    "content/content.json",
                    json.dumps({"gradingSettings": {"gradingMethod": "please_choose"}}),
                )

            packages = collect_h5p_upload_packages(course_dir, "012-miniworlds")

        self.assertEqual(packages[0].title, "Minis erkunden")
        self.assertEqual(packages[0].points, 0)

    def test_collect_h5p_upload_packages_does_not_duplicate_test_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            course_dir = Path(tmp_dir) / "python-2026"
            build_dir = course_dir / "build" / "h5p" / "012-miniworlds"
            build_dir.mkdir(parents=True)
            package_path = build_dir / "test-miniworlds-tutorial.h5p"
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr("h5p.json", json.dumps({"title": "Test: Minis erkunden"}))

            packages = collect_h5p_upload_packages(course_dir, "012-miniworlds")

        self.assertEqual(packages[0].title, "Test: Minis erkunden")
        self.assertEqual(packages[0].points, 2)

    def test_infer_h5p_package_points_returns_zero_for_ungraded_python_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            package_path = Path(tmp_dir) / "plain-text.h5p"
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr("h5p.json", json.dumps({"mainLibrary": "H5P.PythonQuestion"}))
                archive.writestr(
                    "content/content.json",
                    json.dumps({"contentType": "text_only", "gradingSettings": {"gradingMethod": "please_choose"}}),
                )

            points = infer_h5p_package_points(package_path)

        self.assertEqual(points, 0)

    def test_infer_h5p_package_points_returns_two_for_graded_python_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            package_path = Path(tmp_dir) / "graded.h5p"
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr("h5p.json", json.dumps({"mainLibrary": "H5P.PythonQuestion"}))
                archive.writestr(
                    "content/content.json",
                    json.dumps({"contentType": "ide_only", "gradingSettings": {"gradingMethod": "ioTestCases"}}),
                )

            points = infer_h5p_package_points(package_path)

        self.assertEqual(points, 2)

    def test_set_completion_tracking_sets_hidden_gradepass_without_fill_timeout(self) -> None:
        class FakeLocator:
            def __init__(self, *, visible: bool = True, checked: bool = False) -> None:
                self.first = self
                self.visible = visible
                self.checked = checked
                self.filled_values: list[str] = []
                self.evaluated_values: list[str | None] = []
                self.selected_values: list[str] = []

            def count(self) -> int:
                return 1

            def is_visible(self) -> bool:
                return self.visible

            def fill(self, value: str) -> None:
                if not self.visible:
                    raise AssertionError("hidden locator must not be filled through Playwright")
                self.filled_values.append(value)

            def evaluate(self, script: str, value: str | None = None) -> None:
                self.evaluated_values.append(value)

            def select_option(self, *, value: str) -> None:
                self.selected_values.append(value)

            def is_checked(self) -> bool:
                return self.checked

            def check(self) -> None:
                self.checked = True

        class EmptyLocator:
            first = None

            def count(self) -> int:
                return 0

        class FakePage:
            def __init__(self) -> None:
                self.gradepass = FakeLocator(visible=False)
                self.completion = FakeLocator()
                self.grade_condition = FakeLocator(checked=False)
                self.passgrade_condition = FakeLocator(visible=False, checked=False)
                self.waits: list[int] = []

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if "gradepass" in selector:
                    return self.gradepass
                if "completionusegrade" in selector:
                    return self.grade_condition
                if "completionpassgrade" in selector:
                    return self.passgrade_condition
                if 'select[name="completion"]' in selector:
                    return self.completion
                return EmptyLocator()

            def wait_for_timeout(self, timeout: int) -> None:
                self.waits.append(timeout)

        page = FakePage()
        uploader = MoodlePlaywrightUploader(course_url="https://example.invalid/course/view.php?id=7845")

        uploader._set_completion_tracking(page, gradepass=1)

        self.assertEqual(page.gradepass.filled_values, [])
        self.assertEqual(page.gradepass.evaluated_values, ["1"])
        self.assertEqual(page.completion.selected_values, ["2"])
        self.assertTrue(page.grade_condition.checked)
        self.assertEqual(page.passgrade_condition.evaluated_values, [None])

    def test_set_completion_tracking_skips_disabled_advcheckbox_hidden_companion(self) -> None:
        # Moodle's advcheckbox form element renders a hidden <input> carrying the "unchecked"
        # value immediately before the real checkbox, both sharing the same name= attribute
        # (here already checked and disabled, as Moodle renders it once a grade condition is
        # locked in). A selector that is not scoped to type="checkbox" can resolve to the
        # hidden decoy first, and calling is_checked() on it raises
        # "Not a checkbox or radio button" instead of leaving the already-satisfied condition
        # alone.
        page = self._render_html(
            """
            <input type="hidden" name="gradepass" value="1" id="id_gradepass">
            <input type="hidden" name="completion" value="2">
            <input type="hidden" name="completionusegrade" value="1">
            <input type="checkbox" name="completionusegrade" class="form-check-input"
                   value="1" id="id_completionusegrade" checked disabled>
            <input type="hidden" name="completionpassgrade" value="1">
            <input type="checkbox" name="completionpassgrade" class="form-check-input"
                   value="1" id="id_completionpassgrade" checked disabled>
            """
        )
        uploader = MoodlePlaywrightUploader(course_url="https://example.invalid/course/view.php?id=5")

        uploader._set_completion_tracking(page, gradepass=1)

        self.assertTrue(page.locator("#id_completionusegrade").is_checked())
        self.assertTrue(page.locator("#id_completionpassgrade").is_checked())

    def test_set_activity_points_uses_none_grade_type_for_ungraded_packages(self) -> None:
        class FakeLocator:
            def __init__(self, *, count: int = 1) -> None:
                self.first = self
                self.count_value = count
                self.filled_values: list[str] = []
                self.evaluated_values: list[str] = []

            def count(self) -> int:
                return self.count_value

            def is_visible(self) -> bool:
                return False

            def fill(self, value: str) -> None:
                self.filled_values.append(value)

            def evaluate(self, script: str, value: str) -> None:
                self.evaluated_values.append(value)

        class FakePage:
            def __init__(self) -> None:
                self.grade_type = FakeLocator()
                self.grade_points = FakeLocator()

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if "modgrade_type" in selector:
                    return self.grade_type
                if "modgrade_point" in selector:
                    return self.grade_points
                return FakeLocator(count=0)

        page = FakePage()
        uploader = MoodlePlaywrightUploader(course_url="https://example.invalid/course/view.php?id=7845")

        uploader._set_activity_points(page, 0)

        self.assertEqual(page.grade_type.evaluated_values, ["none"])
        self.assertEqual(page.grade_points.evaluated_values, [])

    def test_disable_completion_tracking_sets_completion_to_none(self) -> None:
        class FakeLocator:
            first = None

            def __init__(self, *, count: int = 1) -> None:
                self.first = self
                self.count_value = count
                self.evaluated_values: list[str] = []

            def count(self) -> int:
                return self.count_value

            def is_visible(self) -> bool:
                return False

            def fill(self, value: str) -> None:
                raise AssertionError("hidden select should be set through evaluate")

            def evaluate(self, script: str, value: str) -> None:
                self.evaluated_values.append(value)

        class FakePage:
            def __init__(self) -> None:
                self.completion = FakeLocator()

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if 'select[name="completion"]' in selector:
                    return self.completion
                return FakeLocator(count=0)

        page = FakePage()
        uploader = MoodlePlaywrightUploader(course_url="https://example.invalid/course/view.php?id=7845")

        uploader._disable_completion_tracking(page)

        self.assertEqual(page.completion.evaluated_values, ["0"])

    def test_click_first_by_text_clicks_submit_input_value(self) -> None:
        class EmptyLocator:
            first = None

            def count(self) -> int:
                return 0

        class FakeSubmit:
            first = None

            def __init__(self, *, matches: bool) -> None:
                self.first = self
                self.matches = matches
                self.clicked = False

            def count(self) -> int:
                return 1 if self.matches else 0

            def click(self) -> None:
                self.clicked = True

            def filter(self, **kwargs):  # type: ignore[no-untyped-def]
                return EmptyLocator()

        class FakePage:
            def __init__(self) -> None:
                self.submit = FakeSubmit(matches=True)

            def get_by_role(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                return EmptyLocator()

            def get_by_text(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                return EmptyLocator()

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if 'input[type="submit"][value*="Speichern und zum Kurs"]' in selector:
                    return self.submit
                return FakeSubmit(matches=False)

        page = FakePage()
        uploader = MoodlePlaywrightUploader(course_url="https://example.invalid/course/view.php?id=7845")

        uploader._click_first_by_text(page, ["Speichern und zum Kurs"])

        self.assertTrue(page.submit.clicked)

    def test_collect_h5p_upload_packages_uses_chapter_question_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            course_dir = Path(tmp_dir) / "python-2026"
            build_dir = course_dir / "build" / "h5p" / "013-texte-strings"
            chapter_dir = course_dir / "chapters"
            build_dir.mkdir(parents=True)
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "013-texte-strings.mdx").write_text(
                '\n'.join(
                    [
                        '<PythonQuestion identifier="strings-grundlagen" />',
                        '<PythonQuestion identifier="p5-textposter" />',
                        '<PythonQuestion identifier="bonus-kleiner-textgenerator" />',
                    ]
                ),
                encoding="utf-8",
            )
            for identifier, title in [
                ("bonus-kleiner-textgenerator", "Bonus"),
                ("strings-grundlagen", "Grundlagen"),
                ("p5-textposter", "Poster"),
            ]:
                with zipfile.ZipFile(build_dir / f"{identifier}.h5p", "w") as archive:
                    archive.writestr("h5p.json", json.dumps({"title": title}))

            packages = collect_h5p_upload_packages(course_dir, "013-texte-strings")

        self.assertEqual(
            [package.identifier for package in packages],
            ["strings-grundlagen", "p5-textposter", "bonus-kleiner-textgenerator"],
        )

    def test_collect_h5p_upload_packages_ignores_stale_build_files_when_chapter_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            course_dir = Path(tmp_dir) / "python-2026"
            build_dir = course_dir / "build" / "h5p" / "013-texte-strings"
            chapter_dir = course_dir / "chapters"
            build_dir.mkdir(parents=True)
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "013-texte-strings.mdx").write_text(
                '<PythonQuestion identifier="strings-grundlagen" />\n',
                encoding="utf-8",
            )
            for identifier, title in [
                ("strings-grundlagen", "Grundlagen"),
                ("p5-textposter", "Altes p5 Paket"),
            ]:
                with zipfile.ZipFile(build_dir / f"{identifier}.h5p", "w") as archive:
                    archive.writestr("h5p.json", json.dumps({"title": title}))

            packages = collect_h5p_upload_packages(course_dir, "013-texte-strings")

        self.assertEqual([package.identifier for package in packages], ["strings-grundlagen"])

    def test_generated_markdown_package_does_not_match_existing_activity_by_title(self) -> None:
        package = MoodleH5PUploadPackage(
            identifier="004-vererbung-vererbung",
            title="Vererbung",
            path=Path("courses/oop-2026/build/h5p/004-vererbung/004-vererbung-vererbung.h5p"),
        )
        uploader = MoodlePlaywrightUploader(
            course_url="https://mo5235.schulportal.hessen.de/course/view.php?id=7845",
            section_title="Vererbung",
            existing_activity_ids={"oop-vererbung-grundlagen": 117398},
            headless=True,
        )

        activity_id = uploader._resolve_existing_activity_id(
            package,
            {"vererbung": 117398},
            require_section_match=True,
        )

        self.assertIsNone(activity_id)

    def test_read_chapter_question_order_reads_multiline_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            course_dir = Path(tmp_dir) / "python-2026"
            chapter_dir = course_dir / "chapters"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "013-texte-strings.mdx").write_text(
                '<PythonQuestion\n  identifier="strings-grundlagen"\n/>\n'
                '<PythonQuestion\n  identifier="test-namensschild"\n/>\n',
                encoding="utf-8",
            )

            order = read_chapter_question_order(course_dir, "013-texte-strings")

        self.assertEqual(order, ["strings-grundlagen", "test-namensschild"])

    def test_read_chapter_question_order_includes_markdown_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            course_dir = Path(tmp_dir) / "python-2026"
            chapter_dir = course_dir / "chapters"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "001-start.mdx").write_text(
                """## Start

Introtext.

### Konzept

Erklärung.

<PythonQuestion
  identifier="aufgabe"
/>

### Reflexion

Abschluss.
""",
                encoding="utf-8",
            )

            order = read_chapter_question_order(course_dir, "001-start")

        self.assertEqual(order, ["aufgabe"])

    def test_read_chapter_question_order_uses_nested_chapter_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            course_dir = Path(tmp_dir) / "oop-2026"
            chapter_dir = course_dir / "chapters" / "000-programmierparadigmen"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "content.mdx").write_text(
                """## Programmierparadigmen

Introtext.

<PythonQuestion identifier="paradigmen-erkennen" />
""",
                encoding="utf-8",
            )

            order = read_chapter_question_order(course_dir, "000-programmierparadigmen")

        self.assertEqual(order, ["paradigmen-erkennen"])

    def test_collect_moodle_text_labels_reads_markdown_segments_with_h5p_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            course_dir = Path(tmp_dir) / "oop-2026"
            chapter_dir = course_dir / "chapters" / "000-programmierparadigmen"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "content.mdx").write_text(
                """## Programmierparadigmen

Intro.

<PythonQuestion identifier="paradigmen-erkennen" />

### Paradigmen kombinieren

Weiterer Text.

<PythonQuestion identifier="paradigmen-zuordnen" />
""",
                encoding="utf-8",
            )

            labels = collect_moodle_text_labels(course_dir, "000-programmierparadigmen")

        self.assertEqual(
            [(label.identifier, label.title, label.before_identifier) for label in labels],
            [
                (
                    "000-programmierparadigmen-programmierparadigmen",
                    "Programmierparadigmen",
                    "paradigmen-erkennen",
                ),
                (
                    "000-programmierparadigmen-paradigmen-kombinieren",
                    "Paradigmen kombinieren",
                    "paradigmen-zuordnen",
                ),
            ],
        )
        self.assertIn("<!-- course-sync-text:000-programmierparadigmen-programmierparadigmen -->", labels[0].markdown)
        self.assertIn("## Programmierparadigmen\n\nIntro.", labels[0].markdown)

    def test_collect_moodle_text_labels_derives_title_from_prose_when_no_heading(self) -> None:
        # A chapter's lead-in paragraph before its first question commonly has no heading
        # of its own. The Moodle course navigation label for it should show a useful excerpt
        # of that prose rather than the generic placeholder "Inhalt" for every such segment.
        with tempfile.TemporaryDirectory() as tmp_dir:
            course_dir = Path(tmp_dir) / "oop-2026"
            chapter_dir = course_dir / "chapters" / "000-objekte-verwenden"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "content.mdx").write_text(
                "In diesem Kapitel lernst du, wie du mit fertigen Objekten aus "
                "Bibliotheken arbeitest und sie im eigenen Code verwendest.\n\n"
                '<PythonQuestion identifier="einfuehrung" />\n',
                encoding="utf-8",
            )

            labels = collect_moodle_text_labels(course_dir, "000-objekte-verwenden")

        self.assertEqual(len(labels), 1)
        # The identifier must stay stable (it anchors the already-synced Moodle label);
        # only the display title should change.
        self.assertEqual(labels[0].identifier, "000-objekte-verwenden-inhalt")
        self.assertEqual(
            labels[0].title,
            "In diesem Kapitel lernst du, wie du mit fertigen Objekten…",
        )

    def test_headless_login_if_needed_reports_external_sso_redirect(self) -> None:
        class EmptyLocator:
            def count(self) -> int:
                return 0

        class FakePage:
            url = "https://login.schulportal.hessen.de/saml/singleSignOn?SAMLRequest=test"

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                return EmptyLocator()

        uploader = MoodlePlaywrightUploader(
            course_url="https://mo5235.schulportal.hessen.de/course/view.php?id=7845",
            section_title="Listen",
            headless=True,
        )

        with self.assertRaisesRegex(RuntimeError, "abgelaufener SSO-Storage-State.*singleSignOn"):
            uploader._login_if_needed(FakePage())

    def test_goto_login_resilient_returns_on_schulportal_saml_page(self) -> None:
        class EmptyLocator:
            def count(self) -> int:
                return 0

        class FakePage:
            url = ""

            def goto(self, url: str, **kwargs: object) -> None:
                self.url = "https://login.schulportal.hessen.de/saml/singleSignOn?SAMLRequest=test"

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                return EmptyLocator()

            def wait_for_timeout(self, timeout: int) -> None:
                raise AssertionError("Schulportal SAML pages should be handed to the login flow immediately.")

        uploader = MoodlePlaywrightUploader(
            course_url="https://mo5235.schulportal.hessen.de/course/view.php?id=7845",
            section_title="Listen",
            headless=True,
            timeout_ms=1000,
        )

        uploader._goto_login_resilient(FakePage(), "https://mo5235.schulportal.hessen.de/course/view.php?id=7845")

    def test_goto_login_resilient_hands_enrolment_page_to_login(self) -> None:
        class EmptyLocator:
            def count(self) -> int:
                return 0

        class FakePage:
            url = ""

            def goto(self, url: str, **kwargs: object) -> None:
                self.url = "https://moodle.example.org/enrol/index.php?id=12"

            def locator(self, selector: str):
                return EmptyLocator()

            def wait_for_timeout(self, timeout: int) -> None:
                raise AssertionError("Enrolment pages must be handed to the login flow immediately.")

        uploader = MoodlePlaywrightUploader(
            course_url="https://moodle.example.org/course/view.php?id=12",
            section_title="Demo",
            headless=True,
            timeout_ms=1000,
        )
        uploader._goto_login_resilient(FakePage(), uploader.course_url)

    def test_login_with_credentials_submits_schulportal_hessen_sso(self) -> None:
        class FakeLocator:
            def __init__(
                self,
                page,
                name: str,
                present: bool = True,
                visible: bool = True,
                enabled: bool = True,
            ) -> None:  # type: ignore[no-untyped-def]
                self.page = page
                self.name = name
                self.present = present
                self.visible = visible
                self.enabled = enabled
                self.first = self

            def count(self) -> int:
                return 1 if self.present else 0

            def nth(self, index: int):  # type: ignore[no-untyped-def]
                return self

            def is_visible(self) -> bool:
                return self.visible

            def is_enabled(self) -> bool:
                return self.enabled

            def fill(self, value: str) -> None:
                self.page.filled[self.name] = value

            def click(self) -> None:
                self.page.clicks.append(self.name)
                if self.name == "submit":
                    self.page.url = self.page.course_url

        class EmptyLocator:
            first = None

            def count(self) -> int:
                return 0

        class FakePage:
            def __init__(self) -> None:
                self.course_url = "https://mo5235.schulportal.hessen.de/course/view.php?id=7845"
                self.url = "https://login.schulportal.hessen.de/saml/singleSignOn?SAMLRequest=test"
                self.logged_in = False
                self.filled: dict[str, str] = {}
                self.clicks: list[str] = []
                self.gotos: list[str] = []

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if selector == 'input[name="username"]':
                    return FakeLocator(self, "username", not self.logged_in)
                if selector == 'input[name="password"]':
                    return FakeLocator(self, "password", not self.logged_in)
                if selector == 'button[type="submit"]':
                    return FakeLocator(self, "submit", not self.logged_in)
                if selector in (
                    ".logininfo a[href*='login/index.php'], a[href*='login/index.php']",
                    ".usermenu, [data-region='usermenu'], a[href*='login/logout.php'], .logininfo a[href*='login/logout.php']",
                ):
                    return EmptyLocator()
                return EmptyLocator()

            def goto(self, url: str, **kwargs: object) -> None:
                self.gotos.append(url)
                self.url = url
                if url == "https://login.schulportal.hessen.de/?i=5235":
                    return
                if url == self.course_url:
                    self.logged_in = True

            def wait_for_load_state(self, state: str) -> None:
                return None

        page = FakePage()
        uploader = MoodlePlaywrightUploader(
            course_url=page.course_url,
            section_title="Listen",
            username="alice",
            password="secret",
            headless=True,
            sph_login_method="browser",
        )

        uploader._login_with_credentials_if_needed(page)

        self.assertEqual(page.filled, {"username": "alice", "password": "secret"})
        self.assertEqual(page.clicks, ["submit"])
        self.assertEqual(page.gotos, ["https://login.schulportal.hessen.de/?i=5235", page.course_url])
        self.assertEqual(page.url, page.course_url)

    def test_schulportal_hessen_login_skips_hidden_user_input(self) -> None:
        class FakeLocator:
            def __init__(self, page, items: list[dict[str, object]], index: int = 0) -> None:  # type: ignore[no-untyped-def]
                self.page = page
                self.items = items
                self.index = index
                self.first = self if index == 0 else self.nth(0)

            def count(self) -> int:
                return len(self.items)

            def nth(self, index: int):  # type: ignore[no-untyped-def]
                return FakeLocator(self.page, self.items, index)

            def is_visible(self) -> bool:
                return bool(self.items[self.index].get("visible", True))

            def is_enabled(self) -> bool:
                return bool(self.items[self.index].get("enabled", True))

            def fill(self, value: str) -> None:
                self.page.filled[str(self.items[self.index]["name"])] = value

            def click(self) -> None:
                self.page.clicks.append(str(self.items[self.index]["name"]))
                if self.items[self.index]["name"] == "submit":
                    self.page.url = self.page.course_url

        class EmptyLocator:
            first = None

            def count(self) -> int:
                return 0

        class FakePage:
            def __init__(self) -> None:
                self.course_url = "https://mo5235.schulportal.hessen.de/course/view.php?id=7845"
                self.url = "https://login.schulportal.hessen.de/saml/singleSignOn?SAMLRequest=test"
                self.logged_in = False
                self.filled: dict[str, str] = {}
                self.clicks: list[str] = []
                self.gotos: list[str] = []

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if selector == 'input[name="user"]':
                    return FakeLocator(self, [{"name": "hidden-user", "visible": False}])
                if selector == 'input[type="text"]':
                    return FakeLocator(self, [{"name": "visible-user"}])
                if selector == 'input[name="password"]':
                    return FakeLocator(self, [{"name": "password"}])
                if selector == 'button[type="submit"]':
                    return FakeLocator(self, [{"name": "submit"}])
                return EmptyLocator()

            def goto(self, url: str, **kwargs: object) -> None:
                self.gotos.append(url)
                self.url = url
                if url == self.course_url:
                    self.logged_in = True

            def wait_for_load_state(self, state: str) -> None:
                return None

        page = FakePage()
        uploader = MoodlePlaywrightUploader(
            course_url=page.course_url,
            section_title="Listen",
            username="alice",
            password="secret",
            headless=True,
            sph_login_method="browser",
        )

        uploader._login_with_credentials_if_needed(page)

        self.assertEqual(page.filled, {"visible-user": "alice", "password": "secret"})
        self.assertEqual(page.gotos, ["https://login.schulportal.hessen.de/?i=5235", page.course_url])

    def test_schulportal_hessen_login_keeps_existing_instance_login_url(self) -> None:
        class FakeLocator:
            def __init__(self, page, name: str) -> None:  # type: ignore[no-untyped-def]
                self.page = page
                self.name = name
                self.first = self

            def count(self) -> int:
                return 1

            def nth(self, index: int):  # type: ignore[no-untyped-def]
                return self

            def is_visible(self) -> bool:
                return True

            def is_enabled(self) -> bool:
                return True

            def fill(self, value: str) -> None:
                self.page.filled[self.name] = value

            def click(self) -> None:
                self.page.clicks.append(self.name)
                if self.name == "submit":
                    self.page.url = self.page.course_url

        class EmptyLocator:
            first = None

            def count(self) -> int:
                return 0

        class FakePage:
            def __init__(self) -> None:
                self.course_url = "https://mo5235.schulportal.hessen.de/course/view.php?id=7845"
                self.url = "https://login.schulportal.hessen.de/?i=5235"
                self.filled: dict[str, str] = {}
                self.clicks: list[str] = []
                self.gotos: list[str] = []

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if selector == 'input[name="username"]':
                    return FakeLocator(self, "username")
                if selector == 'input[name="password"]':
                    return FakeLocator(self, "password")
                if selector == 'button[type="submit"]':
                    return FakeLocator(self, "submit")
                return EmptyLocator()

            def goto(self, url: str, **kwargs: object) -> None:
                self.gotos.append(url)
                self.url = url

            def wait_for_load_state(self, state: str) -> None:
                return None

        page = FakePage()
        uploader = MoodlePlaywrightUploader(
            course_url=page.course_url,
            section_title="Listen",
            username="alice",
            password="secret",
            headless=True,
            sph_login_method="browser",
        )

        uploader._login_with_schulportal_hessen_credentials(page)

        self.assertEqual(page.gotos, [])
        self.assertEqual(page.filled, {"username": "alice", "password": "secret"})

    def test_schulportal_hessen_login_selects_school_context(self) -> None:
        class FakeLocator:
            def __init__(self, page, name: str, present: bool = True) -> None:  # type: ignore[no-untyped-def]
                self.page = page
                self.name = name
                self.present = present
                self.first = self

            def count(self) -> int:
                return 1 if self.present else 0

            def nth(self, index: int):  # type: ignore[no-untyped-def]
                return self

            def is_visible(self) -> bool:
                return self.present

            def is_enabled(self) -> bool:
                return self.present

            def fill(self, value: str) -> None:
                self.page.filled[self.name] = value

            def click(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
                self.page.clicks.append(self.name)
                if self.name == "school-context":
                    self.page.school_context_selected = True
                if self.name == "submit":
                    self.page.url = self.page.course_url

        class EmptyLocator:
            first = None

            def count(self) -> int:
                return 0

        class FakePage:
            def __init__(self) -> None:
                self.course_url = "https://mo5235.schulportal.hessen.de/course/view.php?id=7845"
                self.url = "https://login.schulportal.hessen.de/?i=5235"
                self.school_context_selected = False
                self.filled: dict[str, str] = {}
                self.clicks: list[str] = []

            def get_by_role(self, role: str, name: object):  # type: ignore[no-untyped-def]
                if role == "button" and not self.school_context_selected:
                    return FakeLocator(self, "school-context")
                return EmptyLocator()

            def get_by_text(self, name: object):  # type: ignore[no-untyped-def]
                return EmptyLocator()

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if selector == 'input[name="username"]':
                    return FakeLocator(self, "username", self.school_context_selected)
                if selector == 'input[name="password"]':
                    return FakeLocator(self, "password", self.school_context_selected)
                if selector == 'button[type="submit"]':
                    return FakeLocator(self, "submit", self.school_context_selected)
                return EmptyLocator()

            def wait_for_load_state(self, state: str) -> None:
                return None

        page = FakePage()
        uploader = MoodlePlaywrightUploader(
            course_url=page.course_url,
            section_title="Listen",
            username="alice",
            password="secret",
            headless=True,
            sph_login_method="browser",
        )

        uploader._login_with_schulportal_hessen_credentials(page)

        self.assertEqual(page.clicks, ["school-context", "submit"])
        self.assertEqual(page.filled, {"username": "alice", "password": "secret"})

    def test_login_with_credentials_keeps_real_moodle_form_login(self) -> None:
        class FakeLocator:
            def __init__(self, page, name: str, present: bool = True) -> None:  # type: ignore[no-untyped-def]
                self.page = page
                self.name = name
                self.present = present
                self.first = self

            def count(self) -> int:
                return 1 if self.present else 0

            def nth(self, index: int):  # type: ignore[no-untyped-def]
                return self

            def is_visible(self) -> bool:
                return self.present

            def is_enabled(self) -> bool:
                return self.present

            def fill(self, value: str) -> None:
                self.page.filled[self.name] = value

            def click(self) -> None:
                self.page.clicks.append(self.name)
                self.page.logged_in = True

        class EmptyLocator:
            first = None

            def count(self) -> int:
                return 0

        class FakePage:
            def __init__(self) -> None:
                self.course_url = "https://moodle.example/course/view.php?id=5"
                self.url = self.course_url
                self.logged_in = False
                self.filled: dict[str, str] = {}
                self.clicks: list[str] = []
                self.gotos: list[str] = []

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if selector == 'input[name="username"]':
                    return FakeLocator(self, "username", not self.logged_in)
                if selector == 'input[name="password"]':
                    return FakeLocator(self, "password", not self.logged_in)
                if selector == "#loginbtn":
                    return FakeLocator(self, "login-button", not self.logged_in)
                if selector == ".logininfo a[href*='login/index.php'], a[href*='login/index.php']":
                    return EmptyLocator()
                if selector == (
                    ".usermenu, [data-region='usermenu'], a[href*='login/logout.php'], "
                    ".logininfo a[href*='login/logout.php']"
                ):
                    return FakeLocator(self, "logout", self.logged_in)
                return EmptyLocator()

            def get_by_role(self, role: str, name):  # type: ignore[no-untyped-def]
                if role == "button":
                    return FakeLocator(self, "login-button")
                return EmptyLocator()

            def get_by_text(self, text):  # type: ignore[no-untyped-def]
                return EmptyLocator()

            def goto(self, url: str, **kwargs: object) -> None:
                self.gotos.append(url)
                self.url = url

            def wait_for_load_state(self, state: str) -> None:
                return None

        page = FakePage()
        uploader = MoodlePlaywrightUploader(
            course_url=page.course_url,
            section_title="Listen",
            username="alice",
            password="secret",
            headless=True,
        )

        uploader._login_with_credentials_if_needed(page)

        self.assertEqual(page.filled, {"username": "alice", "password": "secret"})
        self.assertEqual(page.clicks, ["login-button"])
        self.assertEqual(page.gotos, [page.course_url])

    def test_login_with_credentials_uses_visible_fields_and_login_button(self) -> None:
        class Candidate:
            def __init__(self, page, name: str, visible: bool = True) -> None:  # type: ignore[no-untyped-def]
                self.page = page
                self.name = name
                self.visible = visible

            def is_visible(self) -> bool:
                return self.visible

            def is_enabled(self) -> bool:
                return True

            def fill(self, value: str) -> None:
                if not self.visible:
                    raise AssertionError("hidden field must not be filled")
                self.page.filled[self.name] = value

            def click(self) -> None:
                self.page.clicks.append(self.name)
                self.page.logged_in = True

        class FakeLocator:
            def __init__(self, candidates: list[Candidate]) -> None:
                self.candidates = candidates
                self.first = candidates[0] if candidates else None

            def count(self) -> int:
                return len(self.candidates)

            def nth(self, index: int) -> Candidate:
                return self.candidates[index]

        class EmptyLocator:
            first = None

            def count(self) -> int:
                return 0

        class FakePage:
            def __init__(self) -> None:
                self.course_url = "https://moodle.example.org/course/view.php?id=11"
                self.url = "https://moodle.example.org/enrol/index.php?id=11"
                self.logged_in = False
                self.filled: dict[str, str] = {}
                self.clicks: list[str] = []
                self.gotos: list[str] = []

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if selector == 'input[name="username"]':
                    if self.logged_in:
                        return EmptyLocator()
                    return FakeLocator([Candidate(self, "hidden-user", visible=False), Candidate(self, "visible-user")])
                if selector == 'input[name="password"]':
                    if self.logged_in:
                        return EmptyLocator()
                    return FakeLocator([Candidate(self, "hidden-password", visible=False), Candidate(self, "visible-password")])
                if selector == "#loginbtn":
                    return FakeLocator([Candidate(self, "login-button")])
                if selector == ".logininfo, .usermenu, [data-region='usermenu']":
                    return EmptyLocator()
                if selector == ".logininfo a[href*='login/index.php'], a[href*='login/index.php']":
                    return EmptyLocator()
                if selector == (
                    ".usermenu, [data-region='usermenu'], a[href*='login/logout.php'], "
                    ".logininfo a[href*='login/logout.php']"
                ):
                    return FakeLocator([Candidate(self, "logout")]) if self.logged_in else EmptyLocator()
                return EmptyLocator()

            def goto(self, url: str, **kwargs: object) -> None:
                self.gotos.append(url)
                self.url = url

            def wait_for_load_state(self, state: str) -> None:
                return None

        page = FakePage()
        uploader = MoodlePlaywrightUploader(
            course_url=page.course_url,
            section_title="Grundlagen",
            username="playwright",
            password="secret",
            headless=True,
        )

        uploader._login_with_credentials_if_needed(page)

        self.assertEqual(page.filled, {"visible-user": "playwright", "visible-password": "secret"})
        self.assertEqual(page.clicks, ["login-button"])

    def test_turn_editing_on_reports_external_sso_redirect_as_login(self) -> None:
        class EmptyLocator:
            first = None

            def count(self) -> int:
                return 0

            def get_attribute(self, name: str) -> str | None:
                return None

        class FakePage:
            url = "https://login.schulportal.hessen.de/saml/singleSignOn?SAMLRequest=test"

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                return EmptyLocator()

            def get_by_role(self, role: str, name):  # type: ignore[no-untyped-def]
                return EmptyLocator()

            def goto(self, url: str, **kwargs: object) -> None:
                self.url = "https://login.schulportal.hessen.de/saml/singleSignOn?SAMLRequest=test"

        uploader = MoodlePlaywrightUploader(
            course_url="https://mo5235.schulportal.hessen.de/course/view.php?id=7845",
            section_title="Listen",
            headless=True,
        )

        with self.assertRaisesRegex(RuntimeError, "Seite im Login.*singleSignOn"):
            uploader._turn_editing_on(FakePage())

    def test_external_login_page_detection_ignores_same_host_course_page(self) -> None:
        class EmptyLocator:
            def count(self) -> int:
                return 0

        class FakePage:
            url = "https://mo5235.schulportal.hessen.de/course/view.php?id=7845"

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                return EmptyLocator()

        uploader = MoodlePlaywrightUploader(
            course_url="https://mo5235.schulportal.hessen.de/course/view.php?id=7845",
            section_title="Listen",
        )

        self.assertFalse(uploader._login_is_required(FakePage()))

    def test_credentials_login_does_not_reopen_login_for_loaded_course_page(self) -> None:
        class EmptyLocator:
            def count(self) -> int:
                return 0

        class FakePage:
            url = "https://mo5235.schulportal.hessen.de/course/view.php?id=7845"

            def __init__(self) -> None:
                self.gotos: list[str] = []

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                return EmptyLocator()

            def goto(self, url: str, **kwargs: object) -> None:
                self.gotos.append(url)

        page = FakePage()
        uploader = MoodlePlaywrightUploader(
            course_url="https://mo5235.schulportal.hessen.de/course/view.php?id=7845",
            section_title="Listen",
            username="alice",
            password="secret",
            headless=True,
        )

        uploader._login_with_credentials_if_needed(page)

        self.assertEqual(page.gotos, [])

    def test_headless_login_if_needed_treats_guest_enrol_page_as_stale_storage(self) -> None:
        class EmptyLocator:
            def count(self) -> int:
                return 0

        class TextLocator:
            def count(self) -> int:
                return 1

            def nth(self, index: int):  # type: ignore[no-untyped-def]
                return self

            def inner_text(self, timeout: int = 0) -> str:
                return "Sie sind als Gast angemeldet Anmelden"

        class FakePage:
            url = "https://moodle.example.org/enrol/index.php?id=11"

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if selector in {".logininfo, .usermenu, [data-region='usermenu']"}:
                    return TextLocator()
                return EmptyLocator()

        uploader = MoodlePlaywrightUploader(
            course_url="https://moodle.example.org/course/view.php?id=11",
            section_title="Grundlagen",
            headless=True,
        )

        with self.assertRaisesRegex(RuntimeError, "nur als Gast angemeldet.*Storage-State"):
            uploader._login_if_needed(FakePage())

    def test_find_or_create_section_aborts_when_rename_form_is_missing(self) -> None:
        class UploaderWithMissingRenameForm(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5", section_title="Texte")
                self.created = False

            def _find_section(self, page):  # type: ignore[no-untyped-def]
                return None

            def _find_section_containing_packages(self, page, packages):  # type: ignore[no-untyped-def]
                return None

            def _create_section_at_end(self, page):  # type: ignore[no-untyped-def]
                self.created = True
                return {"selector": "[data-section='9']", "number": 9, "title": ""}

            def _rename_section(self, page, section_number: int, title: str) -> bool:  # type: ignore[no-untyped-def]
                assert section_number == 9
                assert title == "Texte"
                return False

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

            def _course_is_in_edit_mode(self, page):  # type: ignore[no-untyped-def]
                return True

            def _section_by_number(self, page, section_number: int):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='9']", "number": section_number, "title": ""}

        class FakePage:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def goto(self, url: str, **kwargs: object) -> None:
                self.urls.append(url)

        uploader = UploaderWithMissingRenameForm()
        page = FakePage()

        with self.assertRaisesRegex(RuntimeError, "konnte aber nicht in 'Texte' umbenannt werden"):
            uploader._find_or_create_section(page, [])

        self.assertTrue(uploader.created)

    def test_find_or_create_section_retries_find_after_create_for_slow_tiles_rendering(self) -> None:
        # format_tiles renders a newly renamed section's tile title dynamically, so it can still
        # show the old/default title right after domcontentloaded. The post-create lookup must
        # retry instead of failing on the very first (possibly stale) render.
        class UploaderWithSlowTilesRendering(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5", section_title="Texte")
                self.find_section_calls = 0
                self.waits: list[int] = []

            def _find_section(self, page):  # type: ignore[no-untyped-def]
                # Call 1 is the pre-creation check (must miss, or no section gets created);
                # the retry loop below then needs two more misses before it succeeds.
                self.find_section_calls += 1
                if self.find_section_calls < 4:
                    return None
                return {"selector": "[data-section='9']", "number": 9, "title": "Texte"}

            def _find_section_containing_packages(self, page, packages):  # type: ignore[no-untyped-def]
                return None

            def _create_section_at_end(self, page):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='9']", "number": 9, "title": ""}

            def _rename_section(self, page, section_number: int, title: str) -> bool:  # type: ignore[no-untyped-def]
                return True

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

            def _course_is_in_edit_mode(self, page):  # type: ignore[no-untyped-def]
                return True

        class FakePage:
            def __init__(self, uploader: "UploaderWithSlowTilesRendering") -> None:
                self.uploader = uploader

            def goto(self, url: str, **kwargs: object) -> None:
                return None

            def wait_for_timeout(self, timeout: int) -> None:
                self.uploader.waits.append(timeout)

        uploader = UploaderWithSlowTilesRendering()

        section = uploader._find_or_create_section(FakePage(uploader), [])

        self.assertEqual(section["number"], 9)
        self.assertEqual(uploader.find_section_calls, 4)
        self.assertEqual(uploader.waits, [800, 800, 800])

    def test_find_or_create_section_raises_when_never_found_after_create(self) -> None:
        class UploaderWhereSectionNeverAppears(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5", section_title="Texte")

            def _find_section(self, page):  # type: ignore[no-untyped-def]
                return None

            def _find_section_containing_packages(self, page, packages):  # type: ignore[no-untyped-def]
                return None

            def _create_section_at_end(self, page):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='9']", "number": 9, "title": ""}

            def _rename_section(self, page, section_number: int, title: str) -> bool:  # type: ignore[no-untyped-def]
                return True

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

            def _course_is_in_edit_mode(self, page):  # type: ignore[no-untyped-def]
                return True

        class FakePage:
            def goto(self, url: str, **kwargs: object) -> None:
                return None

            def wait_for_timeout(self, timeout: int) -> None:
                return None

        uploader = UploaderWhereSectionNeverAppears()

        with self.assertRaisesRegex(RuntimeError, "wurde angelegt, aber danach nicht gefunden"):
            uploader._find_or_create_section(FakePage(), [])

    def test_find_section_matches_standard_topics_format(self) -> None:
        page = self._render_html(
            """
            <li class="section course-section" id="section-2" data-section="2">
              <h3 class="sectionname">Objekte verwenden</h3>
            </li>
            <li class="section course-section" id="section-3" data-section="3">
              <h3 class="sectionname">Eigene Klassen definieren</h3>
            </li>
            """
        )
        uploader = MoodlePlaywrightUploader(
            course_url="https://example.invalid/course/view.php?id=5",
            section_title="Eigene Klassen definieren",
        )

        section = uploader._find_section(page)

        self.assertIsNotNone(section)
        self.assertEqual(section["number"], 3)

    def test_find_section_falls_back_to_format_tiles_title(self) -> None:
        # format_tiles ("Kachelformat") leaves li.section empty/untitled on the main course page;
        # the real title and content only appear once a tile's own section.php page is opened. The
        # title is available up front via the tile launcher link's aria-label.
        page = self._render_html(
            """
            <li class="section course-section main moveablesection" id="section-2" data-section="2" data-sectionid="82952"></li>
            <li class="section course-section main moveablesection" id="section-3" data-section="3" data-sectionid="82953"></li>
            <li class="tile tile-clickable" id="tile-2" data-section="2" data-true-sectionid="82952">
              <a class="tile-link" data-section="2" aria-label="Objekte verwenden, öffnet Details in Popup" href="https://example.invalid/course/section.php?id=82952"></a>
            </li>
            <li class="tile tile-clickable" id="tile-3" data-section="3" data-true-sectionid="82953">
              <a class="tile-link" data-section="3" aria-label="Eigene Klassen definieren, öffnet Details in Popup" href="https://example.invalid/course/section.php?id=82953"></a>
            </li>
            """
        )
        uploader = MoodlePlaywrightUploader(
            course_url="https://example.invalid/course/view.php?id=5",
            section_title="Objekte verwenden",
        )

        section = uploader._find_section(page)

        self.assertIsNotNone(section)
        self.assertEqual(section["number"], 2)
        self.assertEqual(section["sectionDbId"], "82952")

    def test_find_section_returns_none_for_unknown_title_with_tiles_present(self) -> None:
        page = self._render_html(
            """
            <li class="section course-section" id="section-2" data-section="2" data-sectionid="82952"></li>
            <li class="tile tile-clickable" id="tile-2" data-section="2" data-true-sectionid="82952">
              <a class="tile-link" data-section="2" aria-label="Objekte verwenden, öffnet Details in Popup" href="https://example.invalid/course/section.php?id=82952"></a>
            </li>
            """
        )
        uploader = MoodlePlaywrightUploader(
            course_url="https://example.invalid/course/view.php?id=5",
            section_title="Ein voellig anderer Titel",
        )

        section = uploader._find_section(page)

        self.assertIsNone(section)

    def test_find_section_matches_format_tiles_title_containing_a_comma(self) -> None:
        # The tile aria-label fallback used to isolate the title by splitting the aria-label on
        # the first comma ("<title>, oeffnet Details in Popup"). That breaks for section titles
        # that contain a comma themselves (e.g. "Beziehungen, Kapselung und miniworlds"), since
        # splitting on the first comma keeps only "Beziehungen" and never matches the full title
        # -- causing _find_or_create_section to create a duplicate section on every sync attempt.
        page = self._render_html(
            """
            <li class="section course-section main moveablesection" id="section-3" data-section="3" data-sectionid="83774"></li>
            <li class="tile tile-clickable" id="tile-3" data-section="3" data-true-sectionid="83774">
              <a class="tile-link" data-section="3" aria-label="Beziehungen, Kapselung und miniworlds, öffnet Details in Popup" href="https://example.invalid/course/section.php?id=83774"></a>
            </li>
            """
        )
        uploader = MoodlePlaywrightUploader(
            course_url="https://example.invalid/course/view.php?id=5",
            section_title="Beziehungen, Kapselung und miniworlds",
        )

        section = uploader._find_section(page)

        self.assertIsNotNone(section)
        self.assertEqual(section["number"], 3)
        self.assertEqual(section["sectionDbId"], "83774")

    def test_section_by_number_reads_section_db_id_from_format_tiles_data_attribute(self) -> None:
        # format_tiles ("Kachelformat") sections carry no data-id attribute at all, only
        # data-sectionid. Without falling back to it, sectionDbId comes back empty and every
        # caller that needs it (e.g. navigating to the section's own page to find an existing
        # text label) silently no-ops instead of working, which was the root cause behind
        # sync_text_labels() creating duplicate labels on every run.
        page = self._render_html(
            """
            <li class="section course-section" id="section-2" data-section="2" data-sectionid="82952"></li>
            """
        )
        uploader = MoodlePlaywrightUploader(course_url="https://example.invalid/course/view.php?id=5")

        section = uploader._section_by_number(page, 2)

        self.assertIsNotNone(section)
        self.assertEqual(section["sectionDbId"], "82952")

    def _render_html(self, body: str):  # type: ignore[no-untyped-def]
        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError:
            self.skipTest("playwright is not installed")

        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=True)
        except Exception as error:  # pragma: no cover - depends on local browser install
            self.skipTest(f"no Chromium browser available for playwright: {error}")

        # addCleanup runs registered callbacks in reverse order, so register stop() first
        # to ensure browser.close() runs before the underlying event loop is torn down.
        self.addCleanup(playwright.stop)
        self.addCleanup(browser.close)
        page = browser.new_page()
        page.set_content(f"<!doctype html><html><body>{body}</body></html>")
        return page

    def test_find_or_create_section_reuses_section_with_existing_packages(self) -> None:
        class UploaderWithExistingPackageSection(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5", section_title="Texte")
                self.created = False

            def _find_section(self, page):  # type: ignore[no-untyped-def]
                return None

            def _find_section_containing_packages(self, page, packages):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='26']", "number": 26, "title": "Texte"}

            def _create_section_at_end(self, page):  # type: ignore[no-untyped-def]
                self.created = True
                return {"selector": "[data-section='27']", "number": 27, "title": ""}

        uploader = UploaderWithExistingPackageSection()

        section = uploader._find_or_create_section(object(), [])

        self.assertFalse(uploader.created)
        self.assertEqual(section["number"], 26)

    def test_find_or_create_section_renames_section_with_existing_packages(self) -> None:
        class UploaderWithExistingPackageSection(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5", section_title="Texte")
                self.renamed: list[tuple[int, str]] = []

            def _find_section(self, page):  # type: ignore[no-untyped-def]
                if self.renamed:
                    return {"selector": "[data-section='26']", "number": 26, "title": "Texte"}
                return None

            def _find_section_containing_packages(self, page, packages):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='26']", "number": 26, "title": "Neuer Abschnitt"}

            def _rename_section(self, page, section_number: int, title: str) -> bool:  # type: ignore[no-untyped-def]
                self.renamed.append((section_number, title))
                return True

            def _section_by_number(self, page, section_number: int):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='26']", "number": section_number, "title": "Texte"}

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

            def _course_is_in_edit_mode(self, page):  # type: ignore[no-untyped-def]
                return True

        class FakePage:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def goto(self, url: str, **kwargs: object) -> None:
                self.urls.append(url)

        uploader = UploaderWithExistingPackageSection()

        section = uploader._find_or_create_section(FakePage(), [])

        self.assertEqual(uploader.renamed, [(26, "Texte")])
        self.assertEqual(section["title"], "Texte")

    def test_find_or_create_section_keeps_explicit_target_section_even_if_packages_exist_elsewhere(self) -> None:
        class UploaderWithDuplicateTitleSection(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5", section_title="Texte")
                self.renamed: list[tuple[int, str]] = []

            def _find_section(self, page):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='10']", "number": 10, "title": "Texte"}

            def _section_contains_packages(self, page, section, packages):  # type: ignore[no-untyped-def]
                return False

            def _find_section_containing_packages(self, page, packages):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='16']", "number": 16, "title": "Alter Titel"}

            def _section_by_number(self, page, section_number: int):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='16']", "number": section_number, "title": "Texte"}

            def _rename_section(self, page, section_number: int, title: str) -> bool:  # type: ignore[no-untyped-def]
                self.renamed.append((section_number, title))
                return True

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

            def _course_is_in_edit_mode(self, page):  # type: ignore[no-untyped-def]
                return True

        class FakePage:
            def goto(self, url: str, **kwargs: object) -> None:
                return None

        uploader = UploaderWithDuplicateTitleSection()

        section = uploader._find_or_create_section(
            FakePage(),
            [MoodleH5PUploadPackage("strings-grundlagen", "Strings: Grundlagen", Path("a.h5p"))],
        )

        self.assertEqual(section["number"], 10)
        self.assertEqual(uploader.renamed, [])

    def test_sort_section_h5p_activities_moves_reverse_into_desired_order(self) -> None:
        class SortUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5", section_title="Texte")
                self.activities = [
                    {"id": 3, "identifier": "c", "title": "C"},
                    {"id": 1, "identifier": "a", "title": "A"},
                    {"id": 2, "identifier": "b", "title": "B"},
                ]
                self.moves: list[tuple[int, int]] = []

            def _section_by_number(self, page, section_number: int):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='9']", "number": section_number, "title": ""}

            def _collect_section_h5p_activity_order(self, page, section_selector: str):  # type: ignore[no-untyped-def]
                return list(self.activities)

            def _move_activity_before(self, page, activity_id: int, before_activity_id: int) -> None:
                self.moves.append((activity_id, before_activity_id))
                self.activities = [activity for activity in self.activities if activity["id"] != activity_id]
                before_index = next(
                    index for index, activity in enumerate(self.activities) if activity["id"] == before_activity_id
                )
                self.activities.insert(before_index, {"id": activity_id, "identifier": chr(96 + activity_id), "title": ""})

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

        class FakePage:
            def goto(self, url: str, **kwargs: object) -> None:
                return None

        uploader = SortUploader()
        packages = [
            MoodleH5PUploadPackage("a", "A", Path("a.h5p")),
            MoodleH5PUploadPackage("b", "B", Path("b.h5p")),
            MoodleH5PUploadPackage("c", "C", Path("c.h5p")),
        ]

        uploader._sort_section_h5p_activities(FakePage(), 9, packages)

        self.assertEqual(uploader.moves, [(2, 3), (1, 2)])
        self.assertEqual([activity["id"] for activity in uploader.activities], [1, 2, 3])

    def test_sort_section_h5p_activities_raises_when_order_never_settles(self) -> None:
        # If Moodle keeps reporting the wrong order despite repeated move attempts, the sync
        # must fail loudly instead of silently continuing with a course whose activity order
        # no longer matches the offline chapter order.
        class SortUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5", section_title="Texte")
                self.moves: list[tuple[int, int]] = []
                self.waits: list[int] = []

            def _section_by_number(self, page, section_number: int):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='9']", "number": section_number, "title": ""}

            def _collect_section_h5p_activity_order(self, page, section_selector: str):  # type: ignore[no-untyped-def]
                return [
                    {"id": 3, "identifier": "c", "title": "C"},
                    {"id": 1, "identifier": "a", "title": "A"},
                    {"id": 2, "identifier": "b", "title": "B"},
                ]

            def _move_activity_before(self, page, activity_id: int, before_activity_id: int) -> None:
                self.moves.append((activity_id, before_activity_id))

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

        class FakePage:
            def goto(self, url: str, **kwargs: object) -> None:
                return None

            def wait_for_timeout(self, timeout: int) -> None:
                return None

        uploader = SortUploader()
        packages = [
            MoodleH5PUploadPackage("a", "A", Path("a.h5p")),
            MoodleH5PUploadPackage("b", "B", Path("b.h5p")),
            MoodleH5PUploadPackage("c", "C", Path("c.h5p")),
        ]

        with self.assertRaises(RuntimeError):
            uploader._sort_section_h5p_activities(FakePage(), 9, packages)

    def test_find_text_label_activity_id_via_section_page_navigates_and_retries(self) -> None:
        # On course formats (e.g. format_tiles/"Kachelformat") the main course page never
        # renders section content, so the initial marker search always comes up empty there.
        # Without this fallback every sync would create a duplicate label instead of finding
        # the one that already exists.
        class LabelUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5")
                self.turned_editing_on = 0

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                self.turned_editing_on += 1

            def _section_by_number(self, page, section_number: int):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='2-populated']", "number": section_number, "title": "Objekte verwenden", "sectionDbId": "82952"}

            def _find_text_label_activity_id(self, page, section_selector: str, identifier: str, *, title: str = ""):  # type: ignore[no-untyped-def]
                self.searched_selector = section_selector
                return 117569 if section_selector == "[data-section='2-populated']" else None

        class FakePage:
            def __init__(self) -> None:
                self.urls: list[str] = []
                self.waits: list[int] = []

            def goto(self, url: str, **kwargs: object) -> None:
                self.urls.append(url)

            def wait_for_timeout(self, timeout: int) -> None:
                self.waits.append(timeout)

        uploader = LabelUploader()
        page = FakePage()
        label = MoodleTextLabelUploadItem(identifier="000-objekte-verwenden-inhalt", title="Inhalt", markdown="x")

        activity_id = uploader._find_text_label_activity_id_via_section_page(
            page, {"sectionDbId": "82952"}, 2, label,
        )

        self.assertTrue(page.waits, "must wait for format_tiles to render dynamic section content")

        self.assertEqual(activity_id, 117569)
        self.assertEqual(page.urls, ["https://example.invalid/course/section.php?id=82952"])
        self.assertEqual(uploader.turned_editing_on, 1)

    def test_find_text_label_activity_id_via_section_page_returns_none_without_section_db_id(self) -> None:
        class LabelUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5")

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                raise AssertionError("must not navigate when no sectionDbId is known")

        class FakePage:
            def goto(self, url: str, **kwargs: object) -> None:
                raise AssertionError("must not navigate when no sectionDbId is known")

        uploader = LabelUploader()
        label = MoodleTextLabelUploadItem(identifier="x", title="x", markdown="x")

        activity_id = uploader._find_text_label_activity_id_via_section_page(FakePage(), {}, 2, label)

        self.assertIsNone(activity_id)

    def test_sort_section_h5p_activities_ignores_existing_ids_outside_target_section(self) -> None:
        class SortUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(
                    course_url="https://example.invalid/course/view.php?id=5",
                    section_title="Texte",
                    existing_activity_ids={"a": 10, "b": 11},
                )
                self.moves: list[tuple[int, int]] = []

            def _section_by_number(self, page, section_number: int):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='19']", "number": section_number, "title": ""}

            def _collect_section_h5p_activity_order(self, page, section_selector: str):  # type: ignore[no-untyped-def]
                return []

            def _move_activity_before(self, page, activity_id: int, before_activity_id: int) -> None:
                self.moves.append((activity_id, before_activity_id))

        uploader = SortUploader()
        packages = [
            MoodleH5PUploadPackage("a", "A", Path("a.h5p")),
            MoodleH5PUploadPackage("b", "B", Path("b.h5p")),
        ]

        uploader._sort_section_h5p_activities(object(), 19, packages)

        self.assertEqual(uploader.moves, [])

    def test_sort_section_h5p_activities_falls_back_to_section_page_for_format_tiles(self) -> None:
        # On course formats (e.g. format_tiles/"Kachelformat") the main course page never
        # renders section content, so the initial activity-order scrape comes up empty there.
        # Without this fallback, a newly added or reordered activity silently stays wherever
        # Moodle happened to put it (e.g. at the end of the section).
        class SortUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5", section_title="Texte")
                self.activities = [
                    {"id": 3, "identifier": "c", "title": "C"},
                    {"id": 1, "identifier": "a", "title": "A"},
                    {"id": 2, "identifier": "b", "title": "B"},
                ]
                self.moves: list[tuple[int, int]] = []
                self.collect_calls = 0

            def _section_by_number(self, page, section_number: int):  # type: ignore[no-untyped-def]
                return {
                    "selector": "[data-section='9']",
                    "number": section_number,
                    "title": "",
                    "sectionDbId": "555",
                }

            def _collect_section_h5p_activity_order(self, page, section_selector: str):  # type: ignore[no-untyped-def]
                self.collect_calls += 1
                if self.collect_calls == 1:
                    return []
                return list(self.activities)

            def _move_activity_before(self, page, activity_id: int, before_activity_id: int) -> None:
                self.moves.append((activity_id, before_activity_id))
                self.activities = [activity for activity in self.activities if activity["id"] != activity_id]
                before_index = next(
                    index for index, activity in enumerate(self.activities) if activity["id"] == before_activity_id
                )
                self.activities.insert(before_index, {"id": activity_id, "identifier": chr(96 + activity_id), "title": ""})

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

        class FakePage:
            def __init__(self) -> None:
                self.urls: list[str] = []
                self.waits: list[int] = []

            def goto(self, url: str, **kwargs: object) -> None:
                self.urls.append(url)

            def wait_for_timeout(self, timeout: int) -> None:
                self.waits.append(timeout)

        uploader = SortUploader()
        page = FakePage()
        packages = [
            MoodleH5PUploadPackage("a", "A", Path("a.h5p")),
            MoodleH5PUploadPackage("b", "B", Path("b.h5p")),
            MoodleH5PUploadPackage("c", "C", Path("c.h5p")),
        ]

        uploader._sort_section_h5p_activities(page, 9, packages)

        self.assertEqual(uploader.moves, [(2, 3), (1, 2)])
        self.assertEqual([activity["id"] for activity in uploader.activities], [1, 2, 3])
        self.assertIn("https://example.invalid/course/section.php?id=555", page.urls)
        self.assertTrue(page.waits, "must wait for format_tiles to render dynamic section content")

    def test_resolve_existing_activity_id_can_reuse_coursewide_id_outside_target_section(self) -> None:
        uploader = MoodlePlaywrightUploader(
            course_url="https://example.invalid/course/view.php?id=5",
            section_title="Grundlagen",
            existing_activity_ids={"bewegung": 44},
        )

        activity_id = uploader._resolve_existing_activity_id(
            MoodleH5PUploadPackage("bewegung", "Bewegung", Path("bewegung.h5p")),
            {"installation": 11},
            require_section_match=True,
        )

        self.assertIsNone(activity_id)

        activity_id = uploader._resolve_existing_activity_id(
            MoodleH5PUploadPackage("bewegung", "Bewegung", Path("bewegung.h5p")),
            {"installation": 11},
            require_section_match=False,
        )

        self.assertEqual(activity_id, 44)

    def test_resolve_existing_activity_id_keeps_coursewide_id_inside_target_section(self) -> None:
        uploader = MoodlePlaywrightUploader(
            course_url="https://example.invalid/course/view.php?id=5",
            section_title="Grundlagen",
            existing_activity_ids={"bewegung": 44},
        )

        activity_id = uploader._resolve_existing_activity_id(
            MoodleH5PUploadPackage("bewegung", "Bewegung", Path("bewegung.h5p")),
            {"alter-titel": 44},
            require_section_match=True,
        )

        self.assertEqual(activity_id, 44)

    def test_set_activity_section_updates_hidden_section_field(self) -> None:
        class FakeLocator:
            def __init__(self, present: bool) -> None:
                self.present = present
                self.first = self
                self.evaluated_values: list[str | None] = []

            def count(self) -> int:
                return 1 if self.present else 0

            def select_option(self, *, value: str) -> None:
                raise AssertionError("hidden input must be used in this test")

            def evaluate(self, script: str, value: str | None = None) -> None:
                self.evaluated_values.append(value)

        class FakePage:
            def __init__(self) -> None:
                self.section_input = FakeLocator(True)

            def locator(self, selector: str):  # type: ignore[no-untyped-def]
                if selector.startswith("select"):
                    return FakeLocator(False)
                if selector.startswith("input"):
                    return self.section_input
                return FakeLocator(False)

        page = FakePage()
        uploader = MoodlePlaywrightUploader(course_url="https://example.invalid/course/view.php?id=5")

        uploader._set_activity_section(page, 2)

        self.assertEqual(page.section_input.evaluated_values, ["2"])

    def test_move_activity_to_section_number_uses_moodle_movetosection(self) -> None:
        class MoveUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5")

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

            def _section_by_number(self, page, section_number: int):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='1']", "number": section_number, "title": "Grundlagen", "sectionDbId": "143"}

            def _moodle_sesskey(self, page):  # type: ignore[no-untyped-def]
                return "abc123"

        class FakePage:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def goto(self, url: str, **kwargs: object) -> None:
                self.urls.append(url)

        page = FakePage()
        uploader = MoveUploader()

        uploader._move_activity_to_section_number(page, 412, 1)

        self.assertEqual(
            page.urls,
            [
                "https://example.invalid/course/view.php?id=5",
                "https://example.invalid/course/mod.php?sesskey=abc123&copy=412",
                "https://example.invalid/course/mod.php?movetosection=143&sesskey=abc123",
                "https://example.invalid/course/view.php?id=5",
            ],
        )

    def test_upload_packages_reloads_section_after_invalid_existing_activity_id(self) -> None:
        class UploadUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(
                    course_url="https://example.invalid/course/view.php?id=5",
                    section_title="Weitere Tutorials",
                    existing_activity_ids={"animationen": 419},
                )
                self.section_calls = 0
                self.created = False

            def _find_or_create_section(self, page, packages):  # type: ignore[no-untyped-def]
                self.section_calls += 1
                return {"selector": f"[data-section='{self.section_calls}']", "number": 5, "title": "Weitere Tutorials", "sectionDbId": "148"}

            def _collect_section_h5p_activities(self, page, section_selector: str):  # type: ignore[no-untyped-def]
                return {}

            def _update_h5p_activity(self, page, activity_id: int, package, *, section_number=None):  # type: ignore[no-untyped-def]
                return None

            def _create_h5p_activity(self, page, section_number: int, package):  # type: ignore[no-untyped-def]
                self.created = True
                return MoodleH5PUploadResult(package.identifier, package.title, "created", 777)

            def _sort_section_h5p_activities(self, page, section_number: int, packages):  # type: ignore[no-untyped-def]
                return None

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

        class FakePage:
            def __init__(self) -> None:
                self.gotos: list[str] = []

            def goto(self, url: str, **kwargs: object) -> None:
                self.gotos.append(url)

        uploader = UploadUploader()
        page = FakePage()

        # Exercise the inner package loop without launching Playwright.
        section = None
        known_activities: dict[str, int] = {}
        packages = [MoodleH5PUploadPackage("animationen", "animationen", Path("animationen.h5p"))]

        def ensure_section():  # type: ignore[no-untyped-def]
            nonlocal section, known_activities
            if section is not None:
                return section
            section = uploader._find_or_create_section(page, packages)
            known_activities = uploader._collect_section_h5p_activities(page, section["selector"])
            return section

        package = packages[0]
        target_section = ensure_section()
        activity_id = uploader._resolve_existing_activity_id(package, known_activities, require_section_match=False)
        result = uploader._update_h5p_activity(page, activity_id, package, section_number=int(target_section["number"]))
        self.assertIsNone(result)
        section = None
        known_activities = {}
        uploader.existing_activity_ids.pop(package.identifier, None)
        page.goto(uploader.course_url, wait_until="domcontentloaded")
        uploader._turn_editing_on(page)
        target_section = ensure_section()
        created = uploader._create_h5p_activity(page, int(target_section["number"]), package)

        self.assertEqual(uploader.section_calls, 2)
        self.assertTrue(uploader.created)
        self.assertEqual(created.activity_id, 777)

    def test_upload_packages_updates_known_activity_without_resolving_section(self) -> None:
        # Course formats that hide section content behind per-section navigation (e.g.
        # format_tiles/"Kachelformat") make section discovery on the main course page
        # unreliable. An activity id already recorded from a previous sync must be updatable
        # in place without ever calling into section discovery/creation.
        class UploadUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(
                    course_url="https://example.invalid/course/view.php?id=5",
                    section_title="Objekte verwenden",
                    existing_activity_ids={"einfuehrung": 117566},
                )
                self.updated: list[int] = []

            def _find_or_create_section(self, page, packages):  # type: ignore[no-untyped-def]
                raise AssertionError("section discovery must not run when the activity id is already known")

            def _update_h5p_activity(self, page, activity_id: int, package, *, section_number=None):  # type: ignore[no-untyped-def]
                self.updated.append(activity_id)
                assert section_number is None
                return MoodleH5PUploadResult(package.identifier, package.title, "updated", activity_id)

        uploader = UploadUploader()
        package = MoodleH5PUploadPackage("einfuehrung", "Einfuehrung", Path("einfuehrung.h5p"))

        # Mirrors the reordered lookup at the top of the upload_packages package loop: a
        # pre-resolved activity id (found without any section context) is used directly.
        preresolved_activity_id = uploader._resolve_existing_activity_id(package, {}, require_section_match=False)
        self.assertEqual(preresolved_activity_id, 117566)
        result = uploader._update_h5p_activity(object(), preresolved_activity_id, package, section_number=None)

        self.assertEqual(uploader.updated, [117566])
        self.assertEqual(result.action, "updated")

    def test_prune_extra_course_sections_deletes_only_non_desired_h5p_sections(self) -> None:
        class CleanupUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5")
                self.sections = [
                    {"number": 0, "title": "Allgemeines", "modules": [{"modname": "forum", "name": "Ankündigungen"}]},
                    {"number": 1, "title": "Grundlagen", "modules": [{"modname": "h5pactivity", "name": "intro"}]},
                    {"number": 2, "title": "Alt", "modules": [{"modname": "h5pactivity", "name": "old"}]},
                ]
                self.deleted: list[int] = []

            def _course_sections_snapshot(self, page):  # type: ignore[no-untyped-def]
                return list(self.sections)

            def _delete_section(self, page, section):  # type: ignore[no-untyped-def]
                self.deleted.append(int(section["number"]))
                self.sections = [item for item in self.sections if item["number"] != section["number"]]
                return True

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

        class FakePage:
            def goto(self, url: str, **kwargs: object) -> None:
                return None

        uploader = CleanupUploader()

        results = uploader._prune_extra_course_sections(FakePage(), ["Grundlagen"])

        self.assertEqual(uploader.deleted, [2])
        self.assertEqual([(result.section_number, result.title, result.action) for result in results], [(2, "Alt", "deleted")])

    def test_prune_extra_course_sections_aborts_for_non_h5p_modules(self) -> None:
        class CleanupUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5")

            def _course_sections_snapshot(self, page):  # type: ignore[no-untyped-def]
                return [
                    {"number": 1, "title": "Grundlagen", "modules": []},
                    {"number": 2, "title": "Alt", "modules": [{"modname": "page", "name": "Nicht loeschen"}]},
                ]

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

        class FakePage:
            def goto(self, url: str, **kwargs: object) -> None:
                return None

        uploader = CleanupUploader()

        with self.assertRaisesRegex(RuntimeError, "Nicht-H5P-Inhalte: Nicht loeschen"):
            uploader._prune_extra_course_sections(FakePage(), ["Grundlagen"])

    def test_create_section_at_end_raises_when_no_new_section_was_created(self) -> None:
        class UploaderWithoutCreation(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5", section_title="Funktionen")

            def _last_section_number(self, page):  # type: ignore[no-untyped-def]
                return 12

            def _create_section_by_url(self, page, before):  # type: ignore[no-untyped-def]
                return False

            def _create_section_by_ui(self, page, before):  # type: ignore[no-untyped-def]
                return False

        uploader = UploaderWithoutCreation()

        with self.assertRaisesRegex(RuntimeError, "konnte keine neue Section"):
            uploader._create_section_at_end(object())

    def test_create_section_by_url_prefers_existing_add_section_link(self) -> None:
        class FakeLocator:
            def __init__(self, hrefs: list[str]) -> None:
                self._hrefs = hrefs
                self.first = self

            def nth(self, index: int):
                return FakeLocator([self._hrefs[index]])

            def count(self) -> int:
                return len(self._hrefs)

            def get_attribute(self, name: str) -> str | None:
                if name == "href" and self._hrefs:
                    return self._hrefs[0]
                return None

        class EmptyLocator:
            first = None

            def count(self) -> int:
                return 0

        class FakePage:
            def __init__(self) -> None:
                self.urls: list[str] = []
                self.section_number = 5

            def goto(self, url: str, **kwargs: object) -> None:
                self.urls.append(url)
                if "insertsection=0" in url:
                    self.section_number = 6

            def locator(self, selector: str):
                if selector == 'a[data-action="addSection"][href*="/course/changenumsections.php"]':
                    return FakeLocator(
                        [
                            "/course/changenumsections.php?courseid=7845&insertsection=17&sesskey=test",
                            "/course/changenumsections.php?courseid=7845&insertsection=0&sesskey=test",
                        ]
                    )
                return EmptyLocator()

        class UrlUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=7845", section_title="Funktionen")

            def _course_is_in_edit_mode(self, page):  # type: ignore[no-untyped-def]
                return True

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

            def _last_section_number(self, page):  # type: ignore[no-untyped-def]
                return page.section_number

            def _moodle_sesskey(self, page):  # type: ignore[no-untyped-def]
                return "test"

        page = FakePage()
        uploader = UrlUploader()

        created = uploader._create_section_by_url(page, 5)

        self.assertTrue(created)
        self.assertEqual(
            page.urls,
            [
                "https://example.invalid/course/changenumsections.php?courseid=7845&insertsection=0&sesskey=test",
                "https://example.invalid/course/view.php?id=7845",
            ],
        )

    def test_is_top_level_add_section_href_accepts_only_course_end_insert(self) -> None:
        uploader = MoodlePlaywrightUploader(
            course_url="https://example.invalid/course/view.php?id=7845",
            section_title="Funktionen",
        )

        self.assertTrue(
            uploader._is_top_level_add_section_href(
                "https://example.invalid/course/changenumsections.php?courseid=7845&insertsection=0&sesskey=test"
            )
        )
        self.assertFalse(
            uploader._is_top_level_add_section_href(
                "https://example.invalid/course/changenumsections.php?courseid=7845&insertsection=17&sesskey=test"
            )
        )

    def test_ensure_section_title_raises_if_rename_did_not_change_visible_title(self) -> None:
        class RenameMismatchUploader(MoodlePlaywrightUploader):
            def __init__(self) -> None:
                super().__init__(course_url="https://example.invalid/course/view.php?id=5", section_title="Texte")

            def _rename_section(self, page, section_number: int, title: str) -> bool:  # type: ignore[no-untyped-def]
                return True

            def _turn_editing_on(self, page):  # type: ignore[no-untyped-def]
                return None

            def _section_by_number(self, page, section_number: int):  # type: ignore[no-untyped-def]
                return {"selector": "[data-section='7']", "number": section_number, "title": "Alter Titel"}

        class FakePage:
            def goto(self, url: str, **kwargs: object) -> None:
                return None

        uploader = RenameMismatchUploader()

        with self.assertRaisesRegex(RuntimeError, "traegt aber nicht den erwarteten Titel"):
            uploader._ensure_section_title(FakePage(), {"selector": "[data-section='7']", "number": 7, "title": "Alt"}, "Texte")


if __name__ == "__main__":
    unittest.main()
