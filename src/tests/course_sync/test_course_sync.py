import json
import os
import tarfile
import tempfile
import threading
import unittest
from hashlib import sha1
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import yaml

from course_sync.main import (
    MoodleApiClient,
    MoodleH5PActivity,
    SyncMetadata,
    SyncMetadataEntry,
    _course_chapter_plan,
    build_moodle_ping_report,
    build_h5p_content,
    build_course_status,
    build_imported_question_from_h5p_package,
    compute_question_hash,
    export_static_site,
    extract_h5p_package_url_from_activity_html,
    import_moodle_course,
    load_course_preview_state,
    load_sync_metadata,
    make_stable_identifier,
    parse_course,
    prepare_preview_runtime,
    render_imported_question_mdx,
    render_course_page,
    resolve_moodle_client,
    rewrite_runtime_html,
    save_sync_metadata,
    sync_course,
    write_h5p_package,
    write_source_package_sidecar,
)
from course_sync.classes.h5p_runtime_manager import build_runtime_content_id
from requirements import needs_h5p_libraries


class CourseSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        from course_sync import main as module

        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self._original_course_build_dir = module.COURSE_BUILD_DIR
        module.COURSE_BUILD_DIR = self.root / "build" / "kurse"
        self.course_dir = self.root / "kurse" / "python-2026"
        (self.course_dir / "h5p").mkdir(parents=True)
        (self.course_dir / "assets").mkdir()
        (self.course_dir / "index.mdx").write_text(
            """# Python Kurs

<PythonQuestion
  identifier="12eck"
  title="Zwölfeck zeichnen"
  instructions="Schreibe ein Programm, das ein Zwölfeck zeichnet."
  runner="pyodide"
  packages="miniworlds"
  gradingMethod="ioTestCases"
/>

```python question:12eck starter
import miniworlds

world = miniworlds.World(400, 400)
world.run()
```

```python question:12eck solution
print("fertig")
```

```json question:12eck testcase
{"hidden": false, "inputs": [], "outputs": ["fertig"]}
```

<PythonQuestion
    identifier="quadrat"
    title="Quadrat zeichnen"
    instructions="Schreibe ein Programm, das ein Quadrat zeichnet."
    runner="pyodide"
    packages="miniworlds"
    gradingMethod="ioTestCases"
/>

```python question:quadrat starter
import miniworlds

world = miniworlds.World(300, 300)
pen = miniworlds.Turtle()
world.run()
```

```python question:quadrat solution
print("quadrat")
```

```json question:quadrat testcase
{"hidden": true, "inputs": [], "outputs": ["quadrat"]}
```
""",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        from course_sync import main as module

        module.COURSE_BUILD_DIR = self._original_course_build_dir
        self.tmp_dir.cleanup()

    def test_parse_course_reads_python_questions(self) -> None:
        _, questions, rendered_source = parse_course(self.course_dir)

        self.assertEqual(len(questions), 2)
        first_question = questions[0]
        second_question = questions[1]
        self.assertEqual(first_question.identifier, "12eck")
        self.assertEqual(first_question.packages, ["miniworlds"])
        self.assertEqual(second_question.identifier, "quadrat")
        self.assertIn("[[[PYTHON_QUESTION:12eck]]]", rendered_source)
        self.assertIn("[[[PYTHON_QUESTION:quadrat]]]", rendered_source)

    def test_parse_course_defaults_plain_python_questions_to_skulpt(self) -> None:
        (self.course_dir / "index.mdx").write_text(
            """# Python Kurs

<PythonQuestion
  identifier="text-test"
  title="Text"
/>

```python question:text-test starter
print("bereit")
```
""",
            encoding="utf-8",
        )

        _, questions, _ = parse_course(self.course_dir)

        self.assertEqual(questions[0].runner, "skulpt")

    def test_parse_course_defaults_miniworlds_questions_to_pyodide(self) -> None:
        (self.course_dir / "index.mdx").write_text(
            """# Python Kurs

<PythonQuestion
  identifier="welt"
  title="Welt"
  packages="miniworlds"
/>

```python question:welt starter
import miniworlds
```
""",
            encoding="utf-8",
        )

        _, questions, _ = parse_course(self.course_dir)

        self.assertEqual(questions[0].runner, "pyodide")

    def test_parse_course_allows_turtle_question_with_pyodide(self) -> None:
        (self.course_dir / "index.mdx").write_text(
            """# Python Kurs

<PythonQuestion
  identifier="turtle-test"
  title="Turtle"
  runner="pyodide"
/>

```python question:turtle-test starter
import turtle
turtle.forward(50)
```
""",
            encoding="utf-8",
        )

        questions = parse_course(self.course_dir)[1]

        self.assertEqual(questions[0].runner, "pyodide")

    def test_parse_course_rejects_p5_question_with_pyodide(self) -> None:
        (self.course_dir / "index.mdx").write_text(
            """# Python Kurs

<PythonQuestion
  identifier="p5-test"
  title="p5"
  runner="pyodide"
/>

```python question:p5-test starter
import p5
```
""",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "pythonRunner: skulpt"):
            parse_course(self.course_dir)

    def test_parse_course_expands_chapter_files_and_sets_h5p_subdir(self) -> None:
        chapters_dir = self.course_dir / "chapters"
        chapters_dir.mkdir()
        (self.course_dir / "index.mdx").write_text(
            '# Python Kurs\n\n<Chapter src="./chapters/010-einfuehrung.mdx" title="Einführung" />\n',
            encoding="utf-8",
        )
        (chapters_dir / "010-einfuehrung.mdx").write_text(
            """## Einführung

<PythonQuestion
  identifier="intro"
  title="Intro"
  instructions="Los gehts."
/>
""",
            encoding="utf-8",
        )

        from course_sync import main as module

        _, questions, rendered_source = parse_course(self.course_dir)

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].identifier, "intro")
        self.assertEqual(questions[0].h5p_subdir, "010-einfuehrung")
        self.assertEqual(
            questions[0].package_path,
            module.course_build_dir(self.course_dir) / "h5p" / "010-einfuehrung" / "intro.h5p",
        )
        self.assertIn("## Einführung", rendered_source)
        self.assertIn("[[[PYTHON_QUESTION:intro]]]", rendered_source)

    def test_course_chapter_plan_defaults_synced_to_true(self) -> None:
        (self.course_dir / "index.mdx").write_text(
            """# Python Kurs

<Chapter src="./chapters/001-start.mdx" title="Start" />
<Chapter src="./chapters/002-weiter.mdx" title="Weiter" synced={false} />
""",
            encoding="utf-8",
        )

        plan = _course_chapter_plan(self.course_dir)

        self.assertEqual([(item.slug, item.title, item.synced) for item in plan], [
            ("001-start", "Start", True),
            ("002-weiter", "Weiter", False),
        ])

    def test_course_chapter_plan_can_return_only_synced_chapters(self) -> None:
        (self.course_dir / "index.mdx").write_text(
            """# Python Kurs

<Chapter src="./chapters/001-start.mdx" title="Start" />
<Chapter src="./chapters/002-weiter.mdx" title="Weiter" synced="false" />
<Chapter src="./chapters/003-ende.mdx" title="Ende" synced />
""",
            encoding="utf-8",
        )

        plan = _course_chapter_plan(self.course_dir, synced_only=True)

        self.assertEqual([(item.slug, item.title) for item in plan], [
            ("001-start", "Start"),
            ("003-ende", "Ende"),
        ])

    def test_parse_course_turns_chapter_markdown_sections_into_python_questions(self) -> None:
        chapters_dir = self.course_dir / "chapters"
        chapters_dir.mkdir()
        (self.course_dir / "index.mdx").write_text(
            '# Python Kurs\n\n<Chapter src="./chapters/001-start.mdx" title="Start" />\n',
            encoding="utf-8",
        )
        (chapters_dir / "001-start.mdx").write_text(
            """## Start

Introtext.

### Konzept

Erklärung mit Code:

```python
print("demo")
```

<PythonQuestion identifier="aufgabe" title="Aufgabe" instructions="Mach." />

### Reflexion

Was hast du gelernt?
""",
            encoding="utf-8",
        )

        _, questions, rendered_source = parse_course(self.course_dir)

        self.assertEqual([question.identifier for question in questions], ["aufgabe"])
        self.assertIn('print("demo")', rendered_source)
        self.assertIn("[[[PYTHON_QUESTION:aufgabe]]]", rendered_source)

    def test_parse_course_reads_chapter_local_content_mdx_with_frontmatter_and_course_defaults(self) -> None:
        chapters_dir = self.course_dir / "chapters"
        activity_dir = chapters_dir / "001-start" / "hello"
        activity_dir.mkdir(parents=True)
        (self.course_dir / "course.yml").write_text(
            """h5pDefaults:
  language: de
  defaultLanguage: de
  mainLibrary: H5P.PythonQuestion
  embedTypes:
    - div
  license: U
  majorVersion: 6
  minorVersion: 90
""",
            encoding="utf-8",
        )
        (self.course_dir / "index.mdx").write_text(
            '# Python Kurs\n\n<Chapter src="./chapters/001-start.mdx" title="Start" />\n',
            encoding="utf-8",
        )
        (chapters_dir / "001-start.mdx").write_text(
            '<PythonQuestion identifier="hello" title="Hallo" />\n',
            encoding="utf-8",
        )
        (activity_dir / "content.mdx").write_text(
            """---
contentType: ide_only
pythonRunner: pyodide
pyodideOptions:
  packages:
    - numpy
---
<Instructions>
Gib den Text aus.
</Instructions>

```python editor:startingCode
print("Hallo")
```

```yaml grading
gradingMethod: please_choose
testCases: []
```
""",
            encoding="utf-8",
        )

        _, questions, _ = parse_course(self.course_dir)

        self.assertEqual(len(questions), 1)
        question = questions[0]
        self.assertEqual(question.identifier, "hello")
        self.assertEqual(question.title, "Hallo")
        self.assertEqual(question.h5p_subdir, "001-start")
        self.assertEqual(question.source_package_path, "chapters/001-start/hello")
        self.assertEqual(question.runner, "pyodide")
        self.assertEqual(question.packages, ["numpy"])
        self.assertEqual(question.starter_code, 'print("Hallo")')
        self.assertEqual(question.h5p_metadata["mainLibrary"], "H5P.PythonQuestion")
        self.assertEqual(question.h5p_content["contentType"], "ide_only")

    def test_parse_course_builds_multiple_choice_grading_settings(self) -> None:
        chapters_dir = self.course_dir / "chapters"
        activity_dir = chapters_dir / "001-start" / "uml-quiz"
        activity_dir.mkdir(parents=True)
        (self.course_dir / "course.yml").write_text(
            "h5pDefaults:\n  mainLibrary: H5P.PythonQuestion\n",
            encoding="utf-8",
        )
        (self.course_dir / "index.mdx").write_text(
            '# Python Kurs\n\n<Chapter src="./chapters/001-start.mdx" title="Start" />\n',
            encoding="utf-8",
        )
        (chapters_dir / "001-start.mdx").write_text(
            '<PythonQuestion identifier="uml-quiz" title="UML-Quiz" />\n',
            encoding="utf-8",
        )
        (activity_dir / "content.mdx").write_text(
            """---
contentType: text_only
pythonRunner: skulpt
pyodideOptions:
  packages: []
---
### Frage

<Instructions>
Welche Aussagen sind richtig?
</Instructions>

```yaml grading
gradingMethod: multipleChoice
multipleChoice:
  allowMultiple: true
  choices:
    - text: Aussage eins
      correct: true
    - text: Aussage zwei
      correct: false
```
""",
            encoding="utf-8",
        )

        _, questions, _ = parse_course(self.course_dir)
        payload = build_h5p_content(questions[0])

        self.assertEqual(payload["gradingSettings"]["gradingMethod"], "multipleChoice")
        self.assertEqual(
            payload["gradingSettings"]["multipleChoice"],
            {
                "allowMultiple": True,
                "choices": [
                    {"text": "Aussage eins", "correct": True},
                    {"text": "Aussage zwei", "correct": False},
                ],
            },
        )

    def test_parse_course_passes_through_enable_python_tutor_option(self) -> None:
        chapters_dir = self.course_dir / "chapters"
        activity_dir = chapters_dir / "001-start" / "tutor-demo"
        activity_dir.mkdir(parents=True)
        (self.course_dir / "course.yml").write_text(
            "h5pDefaults:\n  mainLibrary: H5P.PythonQuestion\n",
            encoding="utf-8",
        )
        (self.course_dir / "index.mdx").write_text(
            '# Python Kurs\n\n<Chapter src="./chapters/001-start.mdx" title="Start" />\n',
            encoding="utf-8",
        )
        (chapters_dir / "001-start.mdx").write_text(
            '<PythonQuestion identifier="tutor-demo" title="Tutor-Demo" />\n',
            encoding="utf-8",
        )
        (activity_dir / "content.mdx").write_text(
            """---
contentType: ide_only
pythonRunner: skulpt
pyodideOptions:
  packages: []
advancedOptions:
  enablePythonTutor: true
---
<Instructions>
Starte den Code und visualisiere ihn.
</Instructions>

```python editor:startingCode
a = 1
```

```yaml grading
gradingMethod: please_choose
```
""",
            encoding="utf-8",
        )

        _, questions, _ = parse_course(self.course_dir)
        payload = build_h5p_content(questions[0])

        self.assertEqual(payload["advancedOptions"]["enablePythonTutor"], True)

    def test_build_h5p_content_infers_missing_content_type_for_imported_text_and_ide(self) -> None:
        chapters_dir = self.course_dir / "chapters" / "001-start"
        activity_dir = chapters_dir / "test-methode"
        activity_dir.mkdir(parents=True)
        (self.course_dir / "course.yml").write_text(
            "h5pDefaults:\n  mainLibrary: H5P.PythonQuestion\n",
            encoding="utf-8",
        )
        (self.course_dir / "index.mdx").write_text(
            '# Python Kurs\n\n<Chapter src="./chapters/001-start/content.mdx" title="Start" />\n',
            encoding="utf-8",
        )
        (chapters_dir / "content.mdx").write_text(
            '<PythonQuestion identifier="test-methode" title="test: Methode" />\n',
            encoding="utf-8",
        )
        (activity_dir / "content.yml").write_text(
            """contents:
- type: text
  text: Aufgabe
editorSettings:
  instructions: Schreibe Code.
  startingCode: |-
    pass
gradingSettings:
  gradingMethod: please_choose
pyodideOptions:
  packages: []
pythonRunner: skulpt
""",
            encoding="utf-8",
        )

        _, questions, _ = parse_course(self.course_dir)
        payload = build_h5p_content(questions[0])

        self.assertEqual(payload["contentType"], "text_and_ide")

    def test_parse_course_rejects_duplicate_identifiers(self) -> None:
        (self.course_dir / "index.mdx").write_text(
            """# Python Kurs

<PythonQuestion identifier="dup" title="Eins" instructions="A" />
<PythonQuestion identifier="dup" title="Zwei" instructions="B" />
""",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "mehrfach vergeben"):
            parse_course(self.course_dir)

    def test_chapter_due_date_is_inherited_by_its_h5p_activities(self) -> None:
        chapters = self.course_dir / "chapters"
        chapters.mkdir()
        (chapters / "000-start.mdx").write_text(
            '<PythonQuestion identifier="start-test" title="Test" instructions="Los" />\n',
            encoding="utf-8",
        )
        (self.course_dir / "index.mdx").write_text(
            '# Kurs\n\n<Chapter src="./chapters/000-start.mdx" dueDate="23.08.2026 23:59" />\n',
            encoding="utf-8",
        )

        _, questions, _ = parse_course(self.course_dir)
        payload = build_h5p_content(questions[0])

        self.assertEqual(questions[0].due_date, "23.08.2026 23:59")
        self.assertEqual(
            payload["gradingSettings"]["dueDateGroup"],
            {"enableDueDate": True, "duedate": "2026-08-23T23:59:00"},
        )

    def test_build_h5p_content_contains_editor_and_tests(self) -> None:
        _, questions, _ = parse_course(self.course_dir)
        question = questions[0]
        payload = build_h5p_content(question)

        self.assertEqual(payload["editorSettings"]["startingCode"].splitlines()[0], "import miniworlds")
        self.assertEqual(payload["gradingSettings"]["gradingMethod"], "ioTestCases")
        self.assertEqual(payload["gradingSettings"]["testCases"][0]["outputs"][0], "fertig")
        self.assertEqual(payload["editorSettings"]["options"]["enableImageUploads"], True)
        self.assertEqual(payload["editorSettings"]["options"]["allowAddingFiles"], True)

    def test_render_course_page_embeds_preview_link(self) -> None:
        html = render_course_page(self.course_dir)
        self.assertEqual(html.count("<iframe"), 1)
        self.assertIn('href="build/h5p/12eck.h5p"', html)
        self.assertIn('href="build/h5p/quadrat.h5p"', html)
        self.assertIn('class="course-section course-section-h1"', html)
        self.assertIn('class="course-section-body"', html)
        self.assertIn('chapterButton.className = "course-chapter-button"', html)
        self.assertIn('id="course-h5p-frame"', html)
        self.assertIn('id="course-prev-button"', html)
        self.assertIn('id="course-next-button"', html)
        self.assertIn('course-sync:navigate-course-overview', html)
        self.assertIn('href="/" aria-label="Zur Startseite"', html)
        self.assertIn('Bitte Aktivität wählen', html)
        self.assertIn('>Zurück<', html)
        self.assertIn('/preview/${encodeURIComponent(courseSlug)}/${encodeURIComponent(questionId)}?mode=view&simple=1', html)
        self.assertNotIn('PythonQuestion', html)
        self.assertNotIn('Waehle links eine Aktivitaet', html)
        self.assertNotIn('zusaetzlich verfuegbar', html)
        self.assertNotIn('Vorschau und Bearbeitung nur auf Klick', html)
        self.assertNotIn('data-open-modal="true"', html)
        self.assertIn('class="question-toolbar"', html)
        self.assertNotIn('/preview-status/python-2026/12eck', html)
        self.assertNotIn('id="preview-modal"', html)
        self.assertIn('>Download<', html)
        self.assertNotIn('>Öffnen<', html)
        self.assertNotIn('>Edit<', html)
        self.assertNotIn('>Split View<', html)
        self.assertNotIn('>Löschen<', html)
        self.assertNotIn('delete-runtime', html)
        self.assertNotIn('<details', html)

    @needs_h5p_libraries
    def test_export_static_site_writes_index_and_h5p_packages(self) -> None:
        output_dir = self.root / "public"

        written_paths = export_static_site(output_dir, self.course_dir)

        self.assertIn(output_dir / ".nojekyll", written_paths)
        self.assertTrue((output_dir / "index.html").is_file())
        course_index = output_dir / "courses" / "python-2026" / "index.html"
        self.assertTrue(course_index.is_file())
        self.assertTrue((output_dir / "h5p" / "python-2026" / "12eck.h5p").is_file())
        self.assertTrue((output_dir / "h5p" / "python-2026" / "quadrat.h5p").is_file())
        self.assertTrue((output_dir / "h5p-content" / "python-2026" / "12eck" / "h5p.json").is_file())
        self.assertTrue((output_dir / "h5p-content" / "python-2026" / "12eck" / "content" / "content.json").is_file())
        self.assertTrue((output_dir / "h5p-player" / "python-2026" / "12eck" / "index.html").is_file())
        course_html = course_index.read_text(encoding="utf-8")
        self.assertIn('href="../../index.html" aria-label="Zur Startseite"', course_html)
        self.assertIn('href="../../h5p/python-2026/12eck.h5p"', course_html)
        self.assertIn('href="../../h5p-player/python-2026/12eck/index.html"', course_html)
        self.assertNotIn('class="h5p-player-frame"', course_html)
        player_html = (output_dir / "h5p-player" / "python-2026" / "12eck" / "index.html").read_text(encoding="utf-8")
        self.assertIn("h5p-standalone@3.8.2", player_html)
        self.assertIn('"h5pJsonPath": "../../../h5p-content/python-2026/12eck"', player_html)
        self.assertNotIn('id="activity-back-link"', player_html)
        self.assertNotIn('course-sync:navigate-course-overview', player_html)
        self.assertNotIn('Zur Übersicht', player_html)
        self.assertNotIn("/preview/", course_html)

    @needs_h5p_libraries
    def test_export_static_site_rebuilds_existing_stale_h5p_package(self) -> None:
        output_dir = self.root / "public"
        export_static_site(output_dir, self.course_dir)

        index_path = self.course_dir / "index.mdx"
        index_path.write_text(
            index_path.read_text(encoding="utf-8").replace(
                "Schreibe ein Programm, das ein Zwölfeck zeichnet.",
                "Zeichne ein aktualisiertes Zwölfeck.",
            ),
            encoding="utf-8",
        )

        export_static_site(output_dir, self.course_dir)

        content_payload = json.loads(
            (output_dir / "h5p-content" / "python-2026" / "12eck" / "content" / "content.json").read_text(
                encoding="utf-8",
            )
        )
        self.assertEqual(
            content_payload["editorSettings"]["instructions"],
            "Zeichne ein aktualisiertes Zwölfeck.",
        )

    @needs_h5p_libraries
    def test_export_static_site_reuses_unchanged_packages_and_extracted_content(self) -> None:
        from course_sync import main as module

        output_dir = self.root / "public"
        export_static_site(output_dir, self.course_dir)

        build_package = module.course_build_dir(self.course_dir) / "h5p" / "12eck.h5p"
        exported_package = output_dir / "h5p" / "python-2026" / "12eck.h5p"
        extracted_content = output_dir / "h5p-content" / "python-2026" / "12eck" / "content" / "content.json"
        player = output_dir / "h5p-player" / "python-2026" / "12eck" / "index.html"
        mtimes_before = {
            path: path.stat().st_mtime_ns
            for path in (build_package, exported_package, extracted_content, player)
        }

        os.utime(self.course_dir / "index.mdx", None)
        export_static_site(output_dir, self.course_dir)

        self.assertEqual(
            mtimes_before,
            {
                path: path.stat().st_mtime_ns
                for path in (build_package, exported_package, extracted_content, player)
            },
        )

    def test_export_static_site_writes_custom_domain_metadata(self) -> None:
        output_dir = self.root / "public"

        written_paths = export_static_site(output_dir, self.course_dir, "https://courses.example.org/")

        self.assertIn(output_dir / "CNAME", written_paths)
        self.assertEqual((output_dir / "CNAME").read_text(encoding="utf-8"), "courses.example.org\n")
        index_html = (output_dir / "index.html").read_text(encoding="utf-8")
        course_html = (output_dir / "courses" / "python-2026" / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="canonical" href="https://courses.example.org/"', index_html)
        self.assertIn('rel="canonical" href="https://courses.example.org/courses/python-2026/"', course_html)

    @needs_h5p_libraries
    def test_export_static_site_accepts_relative_output_dir_with_extracted_content_manifest(self) -> None:
        original_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            written_paths = export_static_site(Path("public"), self.course_dir, "https://courses.example.org/")
        finally:
            os.chdir(original_cwd)

        output_dir = self.root / "public"
        self.assertIn(Path("public") / "index.html", written_paths)
        manifest = json.loads((output_dir / ".course-sync-export-manifest.json").read_text(encoding="utf-8"))
        self.assertIn("h5p-content/python-2026/12eck/content/content.json", manifest["files"])
        self.assertIn("h5p-player/python-2026/12eck/index.html", manifest["files"])

    def test_export_static_site_index_groups_courses_demos_and_preview(self) -> None:
        output_dir = self.root / "public"
        java_course = self.root / "kurse" / "java-course"
        algorithmen_course = self.root / "kurse" / "algorithmen-2026"
        oop_course = self.root / "kurse" / "oop-2026"
        demo_course = self.root / "kurse" / "h5p-demo"
        java_course.mkdir()
        algorithmen_course.mkdir()
        oop_course.mkdir()
        demo_course.mkdir()
        java_course.joinpath("index.mdx").write_text("# Java Kurs\n", encoding="utf-8")
        algorithmen_course.joinpath("index.mdx").write_text("# Algorithmen\n", encoding="utf-8")
        oop_course.joinpath("index.mdx").write_text("# OOP Kurs\n", encoding="utf-8")
        demo_course.joinpath("index.mdx").write_text("# H5P Demo\n", encoding="utf-8")

        export_static_site(output_dir, [java_course, self.course_dir, algorithmen_course, demo_course, oop_course])

        index_html = (output_dir / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("Statisch veröffentlichte Kursseiten", index_html)
        self.assertNotIn("Unfertige Preview-Kurse sind sichtbar", index_html)
        self.assertIn("Kurs öffnen", index_html)
        self.assertNotIn("fallback-links", index_html)
        self.assertNotIn("Direktlinks", index_html)
        self.assertLess(index_html.index('id="course-group-courses"'), index_html.index('id="course-group-demos"'))
        self.assertLess(index_html.index('id="course-group-demos"'), index_html.index('id="course-group-preview"'))
        self.assertLess(index_html.index("Python Kurs"), index_html.index("Java Kurs"))
        self.assertLess(index_html.index("Python Kurs"), index_html.index("Algorithmen"))
        self.assertLess(index_html.index("Python Kurs"), index_html.index("OOP Kurs"))
        self.assertLess(index_html.index("H5P Demo"), index_html.index("Java Kurs"))
        self.assertLess(index_html.index("H5P Demo"), index_html.index("OOP Kurs"))
        self.assertLess(index_html.index("Java Kurs"), index_html.index("OOP Kurs"))
        self.assertIn("Unfertige Preview", index_html)
        self.assertIn("Dieser Kurs ist noch unfertig", index_html)
        self.assertIn('href="#impressum-title">Impressum</a>', index_html)
        self.assertIn("<h2 id=\"impressum-title\">Impressum</h2>", index_html)

    def test_render_index_reads_imprint_from_dotenv_values(self) -> None:
        from course_sync.classes import template_renderer as template_renderer_module
        from course_sync.main import escape_inline

        original_read_dotenv_values = template_renderer_module._read_dotenv_values
        try:
            template_renderer_module._read_dotenv_values = lambda: {
                "IMPRESSUM_NAME": "Ada Lovelace",
                "IMPRESSUM_ADDRESS": "Rechenweg 1\\n12345 Zahlenstadt",
                "IMPRESSUM_EMAIL": "ada@example.test",
            }
            html = template_renderer_module.TemplateRenderer(escape_inline=escape_inline).render_index([self.course_dir])
        finally:
            template_renderer_module._read_dotenv_values = original_read_dotenv_values

        self.assertIn("<strong>Ada Lovelace</strong>", html)
        self.assertIn("Rechenweg 1<br>12345 Zahlenstadt", html)
        self.assertIn('href="mailto:ada@example.test"', html)

    def test_render_index_reads_site_description_from_dotenv_values(self) -> None:
        from course_sync.classes import template_renderer as template_renderer_module
        from course_sync.main import escape_inline

        original_read_dotenv_values = template_renderer_module._read_dotenv_values
        try:
            template_renderer_module._read_dotenv_values = lambda: {
                "SITE_DESCRIPTION": "Eigener Startseitentext\\nmit zweiter Zeile.",
            }
            html = template_renderer_module.TemplateRenderer(escape_inline=escape_inline).render_index([self.course_dir])
        finally:
            template_renderer_module._read_dotenv_values = original_read_dotenv_values

        self.assertIn("<p>Eigener Startseitentext<br>mit zweiter Zeile.</p>", html)
        self.assertNotIn("Statisch veröffentlichte Kursseiten", html)

    def test_export_static_site_preserves_existing_output_directory(self) -> None:
        output_dir = self.root / "public"
        export_static_site(output_dir, self.course_dir)
        (output_dir / "stale.txt").write_text("old", encoding="utf-8")
        original_inode = output_dir.stat().st_ino

        export_static_site(output_dir, self.course_dir)

        self.assertEqual(output_dir.stat().st_ino, original_inode)
        self.assertEqual((output_dir / "stale.txt").read_text(encoding="utf-8"), "old")
        self.assertTrue((output_dir / "index.html").is_file())

    def test_export_static_site_rejects_project_root_as_output(self) -> None:
        from course_sync import main as module

        original_root_dir = module.ROOT_DIR
        original_courses_dir = module.COURSES_DIR
        try:
            module.ROOT_DIR = self.root
            module.COURSES_DIR = self.root / "kurse"
            with self.assertRaisesRegex(ValueError, "Export-Zielordner"):
                export_static_site(self.root, self.course_dir)
            with self.assertRaisesRegex(ValueError, "Export-Zielordner"):
                export_static_site(self.root / "kurse", self.course_dir)
        finally:
            module.ROOT_DIR = original_root_dir
            module.COURSES_DIR = original_courses_dir

    def test_rewrite_runtime_html_rewrites_paths_and_hides_view_chrome(self) -> None:
        source = (
            '<head></head><body>'
            '<a href="/edit/x/y">Edit</a>'
            '<script>'
            'fetch("/remove/y"); '
            'const baseUrl = "http://localhost:8766"; '
            'const ajaxPath = "http://localhost:8766/edit/x/y/";'
            '</script>'
            '<div id="status"></div>'
            '</body>'
        )

        rewritten = rewrite_runtime_html(source, '/view/x/y', 'simple=1')

        self.assertIn('href="/runtime/edit/x/y"', rewritten)
        self.assertIn('fetch("/runtime/remove/y")', rewritten)
        self.assertIn('"/runtime"', rewritten)
        self.assertIn('"/runtime/edit/x/y/"', rewritten)
        self.assertNotIn('"/runtime/runtime"', rewritten)
        self.assertIn('#status', rewritten)
        self.assertIn('.menu-holder', rewritten)
        self.assertIn('#sessions', rewritten)
        self.assertIn('.submenu', rewritten)
        self.assertIn('a[href*="/split/"]', rewritten)
        self.assertIn('a[href*="/remove/"]', rewritten)
        self.assertIn("getElementById('sessions')", rewritten)

    def test_rewrite_runtime_html_hides_edit_and_split_chrome(self) -> None:
        source = '<head></head><body><div id="menu"></div><div class="h5p-cli-view"><div class="col50"></div></div></body>'

        rewritten_edit = rewrite_runtime_html(source, '/edit/x/y')
        rewritten_split = rewrite_runtime_html(source, '/split/x/y')

        self.assertIn('#menu', rewritten_edit)
        self.assertIn('.h5p-cli-view > .col50', rewritten_split)

    def test_runtime_content_id_namespaces_identifier_by_course(self) -> None:
        self.assertEqual(build_runtime_content_id("python-2026", "12eck"), "python-2026-12eck")
        self.assertEqual(build_runtime_content_id("python basics", "frage/1"), "python%20basics-frage%2F1")

    def test_make_stable_identifier_suffixes_duplicates(self) -> None:
        existing: set[str] = set()

        first = make_stable_identifier("Quadrat H5P", existing)
        second = make_stable_identifier("Quadrat H5P", existing)

        self.assertEqual(first, "quadrat-h5p")
        self.assertEqual(second, "quadrat-h5p-2")

    def test_make_stable_identifier_transliterates_umlauts(self) -> None:
        identifier = make_stable_identifier("Einführung: Größen & Maße", set())

        self.assertEqual(identifier, "einfuehrung-groessen-masse")

    def test_extract_h5p_package_url_from_activity_html_reads_embed_iframe(self) -> None:
        page_html = (
            '<iframe src="https://moodle.example.org/h5p/embed.php?url=https%3A%2F%2Fmoodle.example.org%2Fpluginfile.php%2F157%2Fmod_h5pactivity%2Fpackage%2F0%2Fhello-world.h5p&amp;preventredirect=1"></iframe>'
        )

        package_url = extract_h5p_package_url_from_activity_html(page_html)

        self.assertEqual(
            package_url,
            "https://moodle.example.org/pluginfile.php/157/mod_h5pactivity/package/0/hello-world.h5p",
        )

    def test_build_imported_question_from_h5p_package_maps_python_question_fields(self) -> None:
        activity = MoodleH5PActivity(
            identifier="test-erste-aufgabe",
            title="Test: Erste Aufgabe",
            course_id=5,
            activity_id=135,
            instance_id=96,
            section_title="Einführung",
            url="https://example.invalid/mod/h5pactivity/view.php?id=135",
        )
        metadata_payload = {
            "title": "PythonQuestion",
            "mainLibrary": "H5P.PythonQuestion",
        }
        content_payload = {
            "pythonRunner": "skulpt",
            "pyodideOptions": {
                "packages": [{"package": "miniworlds"}],
            },
            "editorSettings": {
                "instructions": "**Aufgabe:** Gebe Informatik aus.",
                "preCode": "import math",
                "startingCode": 'print("Informatik")\n',
                "postCode": "print('fertig')",
                "options": {
                    "allowAddingFiles": True,
                    "sourceFiles": [
                        {
                            "fileName": "helper.py",
                            "code": "VALUE = 1\n",
                            "visibleToLearner": False,
                            "learnerEditable": False,
                        }
                    ],
                },
            },
            "gradingSettings": {
                "gradingMethod": "ioTestCases",
                "targetCode": 'print("Informatik")',
                "testCases": [
                    {
                        "hidden": False,
                        "inputs": [],
                        "outputs": ["Informatik"],
                    }
                ],
            },
            "advancedOptions": {
                "showConsole": False,
            },
        }

        question = build_imported_question_from_h5p_package(
            "python-2026",
            activity,
            metadata_payload,
            content_payload,
        )

        assert question is not None
        self.assertEqual(question.title, "Test: Erste Aufgabe")
        self.assertEqual(question.runner, "skulpt")
        self.assertEqual(question.packages, ["miniworlds"])
        self.assertEqual(question.instructions, "**Aufgabe:** Gebe Informatik aus.")
        self.assertEqual(question.pre_code, "import math")
        self.assertEqual(question.starter_code, 'print("Informatik")')
        self.assertEqual(question.solution_code, 'print("Informatik")')
        self.assertEqual(question.post_code, "print('fertig')")
        self.assertEqual(question.grading_method, "ioTestCases")
        self.assertFalse(question.show_console)
        self.assertTrue(question.allow_adding_files)
        self.assertEqual(question.source_files[0].file_name, "helper.py")
        self.assertFalse(question.source_files[0].visible_to_learner)
        self.assertFalse(question.source_files[0].learner_editable)
        self.assertEqual(question.test_cases[0].outputs, ["Informatik"])
        self.assertEqual(question.h5p_metadata, metadata_payload)
        self.assertEqual(question.h5p_content, content_payload)

    def test_build_imported_question_from_h5p_package_keeps_questionset_as_raw_h5p(self) -> None:
        activity = MoodleH5PActivity(
            identifier="quiz-division",
            title="Quiz Division",
            course_id=5,
            activity_id=165,
            instance_id=120,
            section_title="Quiz",
            intro="",
            url="https://example.invalid/mod/h5pactivity/view.php?id=165",
            package_url="https://example.invalid/pluginfile.php/165/mod_h5pactivity/package/0/quiz-division.h5p",
        )
        metadata_payload = {
            "title": "Quiz Division",
            "mainLibrary": "H5P.QuestionSet",
        }
        content_payload = {
            "questions": [
                {"params": {"question": "Was ist 12 / 3?"}},
                {"params": {"question": "Was ist 9 / 3?"}},
            ]
        }

        question = build_imported_question_from_h5p_package(
            "python-2026",
            activity,
            metadata_payload,
            content_payload,
        )

        assert question is not None
        self.assertEqual(question.main_library, "H5P.QuestionSet")
        self.assertEqual(question.package_url, activity.package_url)
        self.assertIn("2 Teilfragen", question.instructions)
        self.assertIn("12 / 3", question.instructions)
        self.assertEqual(question.h5p_metadata, metadata_payload)
        self.assertEqual(question.h5p_content, content_payload)

    def test_build_imported_question_from_h5p_package_keeps_text_only_python_question_as_raw_h5p(self) -> None:
        activity = MoodleH5PActivity(
            identifier="einfuehrung-farben",
            title="Einführung: Farben",
            course_id=5,
            activity_id=145,
            instance_id=105,
            section_title="Farben",
            intro="",
            url="https://example.invalid/mod/h5pactivity/view.php?id=145",
            package_url="https://example.invalid/pluginfile.php/168/mod_h5pactivity/package/0/einfuhrung-farben-891.h5p",
        )
        metadata_payload = {
            "title": "Einführung: Farben",
            "mainLibrary": "H5P.PythonQuestion",
        }
        content_payload = {
            "contentType": "text_only",
            "pythonRunner": "skulpt",
            "contents": [
                {"type": "text", "text": "Schau dir den folgenden Code an."},
                {"type": "code", "code": "import turtle\nturtle.forward(10)\n"},
            ],
            "editorSettings": {
                "instructions": "Schau dir den folgenden Code an.",
                "options": {},
            },
            "gradingSettings": {},
        }

        question = build_imported_question_from_h5p_package(
            "python-2026",
            activity,
            metadata_payload,
            content_payload,
        )

        assert question is not None
        self.assertEqual(question.main_library, "H5P.PythonQuestion")
        self.assertEqual(question.package_url, activity.package_url)
        self.assertEqual(question.runner, "skulpt")
        self.assertIn("Schau dir den folgenden Code an.", question.instructions)
        self.assertEqual(question.h5p_metadata, metadata_payload)
        self.assertEqual(question.h5p_content, content_payload)

    @needs_h5p_libraries
    def test_render_and_parse_imported_question_roundtrips_exact_h5p_json_blocks(self) -> None:
        question = build_imported_question_from_h5p_package(
            "python-2026",
            MoodleH5PActivity(
                identifier="einfuehrung-farben",
                title="Einführung: Farben",
                course_id=5,
                activity_id=145,
                instance_id=105,
                section_title="Farben",
                intro="",
                url="https://example.invalid/mod/h5pactivity/view.php?id=145",
                package_url="https://example.invalid/pluginfile.php/168/mod_h5pactivity/package/0/einfuhrung-farben-891.h5p",
            ),
            {"title": "Einführung: Farben", "mainLibrary": "H5P.PythonQuestion"},
            {
                "contentType": "text_only",
                "pythonRunner": "skulpt",
                "contents": [
                    {"type": "text", "text": "Schau dir den folgenden Code an."},
                    {"type": "code", "code": "import turtle\nturtle.forward(10)\n"},
                ],
                "editorSettings": {"instructions": "Schau dir den folgenden Code an.", "options": {}},
                "gradingSettings": {},
            },
        )

        assert question is not None
        question.course_dir = self.course_dir
        source_archive = self.course_dir / "einfuehrung-farben.h5p"
        source_archive.write_bytes(
            self._build_h5p_archive_bytes(
                {"title": "Einführung: Farben", "mainLibrary": "H5P.PythonQuestion"},
                question.h5p_content or {},
            )
        )
        question.source_package_path = write_source_package_sidecar(question, source_archive)
        mdx = "# Python Kurs\n\n" + "\n".join(render_imported_question_mdx(question)) + "\n"
        (self.course_dir / "index.mdx").write_text(mdx, encoding="utf-8")

        _, questions, _ = parse_course(self.course_dir)

        self.assertEqual(len(questions), 1)
        parsed = questions[0]
        from course_sync import main as module

        self.assertEqual(parsed.h5p_metadata["title"], question.h5p_metadata["title"])
        self.assertEqual(parsed.h5p_metadata["mainLibrary"], question.h5p_metadata["mainLibrary"])
        self.assertEqual(
            module.component_syncer().build_editable_h5p_payload(parsed),
            module.component_syncer().build_editable_h5p_payload(question),
        )
        self.assertEqual(parsed.source_package_path, "h5p/einfuehrung-farben")
        self.assertNotIn("h5p={{", mdx)
        self.assertNotIn("title=", mdx)
        self.assertNotIn("instructions=", mdx)
        self.assertNotIn("runner=", mdx)

    def test_prepare_preview_runtime_prepares_all_questions_for_selected_course(self) -> None:
        from course_sync import main as module

        original_ensure_h5p_runtime_libraries = module.ensure_h5p_runtime_libraries
        original_load_course_preview_state = module.load_course_preview_state
        original_ensure_runtime_question_ready = module.ensure_runtime_question_ready
        try:
            course_dir = self.course_dir
            other_course_dir = self.root / "kurse" / "python-2027"
            other_course_dir.mkdir(parents=True)

            first = build_imported_question_from_h5p_package(
                "python-2026",
                MoodleH5PActivity(
                    identifier="eins",
                    title="Eins",
                    course_id=5,
                    activity_id=1,
                    instance_id=1,
                    section_title="Intro",
                    intro="",
                    url="https://example.invalid/mod/h5pactivity/view.php?id=1",
                ),
                {"title": "Eins", "mainLibrary": "H5P.QuestionSet"},
                {"questions": []},
            )
            second = build_imported_question_from_h5p_package(
                "python-2026",
                MoodleH5PActivity(
                    identifier="zwei",
                    title="Zwei",
                    course_id=5,
                    activity_id=2,
                    instance_id=2,
                    section_title="Intro",
                    intro="",
                    url="https://example.invalid/mod/h5pactivity/view.php?id=2",
                ),
                {"title": "Zwei", "mainLibrary": "H5P.QuestionSet"},
                {"questions": []},
            )
            other = build_imported_question_from_h5p_package(
                "python-2027",
                MoodleH5PActivity(
                    identifier="drei",
                    title="Drei",
                    course_id=6,
                    activity_id=3,
                    instance_id=3,
                    section_title="Intro",
                    intro="",
                    url="https://example.invalid/mod/h5pactivity/view.php?id=3",
                ),
                {"title": "Drei", "mainLibrary": "H5P.QuestionSet"},
                {"questions": []},
            )

            assert first is not None
            assert second is not None
            assert other is not None

            library_calls: list[str] = []
            prepared_ids: list[str] = []

            module.ensure_h5p_runtime_libraries = lambda: library_calls.append("libraries")
            module.load_course_preview_state = (
                lambda current_course_dir: ([first, second], "") if current_course_dir == course_dir else ([other], "")
            )
            module.ensure_runtime_question_ready = lambda question: prepared_ids.append(question.identifier)

            prepared = prepare_preview_runtime(course_dir)
        finally:
            module.ensure_h5p_runtime_libraries = original_ensure_h5p_runtime_libraries
            module.load_course_preview_state = original_load_course_preview_state
            module.ensure_runtime_question_ready = original_ensure_runtime_question_ready

        self.assertEqual(library_calls, ["libraries"])
        self.assertEqual(prepared_ids, ["eins", "zwei"])
        self.assertEqual([question.identifier for question in prepared], ["eins", "zwei"])

    @needs_h5p_libraries
    def test_build_editable_h5p_payload_omits_python_question_defaults(self) -> None:
        question = build_imported_question_from_h5p_package(
            "python-2026",
            MoodleH5PActivity(
                identifier="einfuehrung-farben",
                title="Einführung: Farben",
                course_id=5,
                activity_id=145,
                instance_id=105,
                section_title="Farben",
                intro="",
                url="https://example.invalid/mod/h5pactivity/view.php?id=145",
            ),
            {"title": "Einführung: Farben", "mainLibrary": "H5P.PythonQuestion"},
            {
                "contentType": "text_only",
                "pythonRunner": "skulpt",
                "advancedOptions": {"showConsole": True},
                "contents": [
                    {"type": "text", "text": "Schau dir den folgenden Code an."},
                    {"type": "code", "code": "import turtle\nturtle.forward(10)\n", "options": {"showEditor": True}},
                ],
                "editorSettings": {"instructions": "Schau dir den folgenden Code an.", "options": {"allowAddingFiles": False}},
                "gradingSettings": {"gradingMethod": "please_choose"},
            },
        )

        assert question is not None
        from course_sync import main as module
        payload = module.component_syncer().build_editable_h5p_payload(question)

        self.assertEqual(
            payload,
            {
                "contentType": "text_only",
                "contents": [
                    {"text": "Schau dir den folgenden Code an."},
                    {"type": "code", "code": "import turtle\nturtle.forward(10)\n"},
                ],
            },
        )

    @needs_h5p_libraries
    def test_build_editable_h5p_payload_omits_duplicate_ide_instructions(self) -> None:
        question = build_imported_question_from_h5p_package(
            "python-2026",
            MoodleH5PActivity(
                identifier="test-timestamps",
                title="Python Question",
                course_id=5,
                activity_id=170,
                instance_id=130,
                section_title="While",
                intro="",
                url="https://example.invalid/mod/h5pactivity/view.php?id=170",
            ),
            {"title": "Python Question", "mainLibrary": "H5P.PythonQuestion"},
            {
                "contentType": "ide_only",
                "pythonRunner": "skulpt",
                "editorSettings": {
                    "instructions": "Lese zwei timestamps ein und berechne die Anzahl an Sekunden zwischen zwei Timestamps\n",
                    "startingCode": "\n",
                },
                "gradingSettings": {
                    "gradingMethod": "ioTestCases",
                    "testCases": [{"inputs": [{"input": "1"}], "outputs": [{"output": "1"}]}],
                },
            },
        )

        assert question is not None
        self.assertEqual(question.instructions, "Lese zwei timestamps ein und berechne die Anzahl an Sekunden zwischen zwei Timestamps")
        from course_sync import main as module
        self.assertNotIn("instructions", json.dumps(module.component_syncer().build_editable_h5p_payload(question), ensure_ascii=False))

    def test_non_python_imported_payload_uses_source_package_as_baseline(self) -> None:
        question = build_imported_question_from_h5p_package(
            "python-2026",
            MoodleH5PActivity(
                identifier="quiz-division",
                title="Quiz Division",
                course_id=5,
                activity_id=165,
                instance_id=120,
                section_title="Quiz",
                intro="",
                url="https://example.invalid/mod/h5pactivity/view.php?id=165",
            ),
            {"title": "Quiz Division", "mainLibrary": "H5P.QuestionSet", "language": "de"},
            {"questions": [{"params": {"question": "Alt?"}}]},
        )

        assert question is not None
        question.course_dir = self.course_dir
        source_archive = self.course_dir / "quiz-division.h5p"
        source_archive.write_bytes(
            self._build_h5p_archive_bytes(
                {"title": "Quiz Division", "mainLibrary": "H5P.QuestionSet", "language": "de"},
                {"questions": [{"params": {"question": "Alt?"}}]},
            )
        )
        question.source_package_path = write_source_package_sidecar(question, source_archive)

        from course_sync import main as module
        self.assertEqual(module.component_syncer().build_editable_h5p_payload(question), {})

        mdx = "# Python Kurs\n\n" + "\n".join(render_imported_question_mdx(question)) + "\n"
        self.assertIn('identifier="quiz-division"', mdx)
        self.assertNotIn("h5p={{", mdx)

        (self.course_dir / "index.mdx").write_text(mdx, encoding="utf-8")
        _, questions, _ = parse_course(self.course_dir)

        self.assertEqual(len(questions), 1)
        parsed = questions[0]
        self.assertEqual(parsed.h5p_metadata, question.h5p_metadata)
        self.assertEqual(parsed.h5p_content, question.h5p_content)

    @needs_h5p_libraries
    def test_sync_course_preserves_imported_h5p_assets_in_sidecar_and_output(self) -> None:
        from course_sync import main as module

        question = build_imported_question_from_h5p_package(
            "python-2026",
            MoodleH5PActivity(
                identifier="test-zahlen-addieren",
                title="Test: Zahlen addieren",
                course_id=5,
                activity_id=1,
                instance_id=1,
                section_title="Variablen",
                intro="",
                url="https://example.invalid/mod/h5pactivity/view.php?id=1",
            ),
            {"title": "Test: Zahlen addieren", "mainLibrary": "H5P.PythonQuestion"},
            {
                "contentType": "ide_only",
                "pythonRunner": "skulpt",
                "editorSettings": {
                    "instructionsImage": {
                        "path": "images/instructions.png",
                        "mime": "image/png",
                    },
                    "startingCode": "print(12)\n",
                },
                "gradingSettings": {
                    "gradingMethod": "ioTestCases",
                    "testCases": [{"outputs": [{"output": "12"}]}],
                },
            },
        )

        assert question is not None
        question.course_dir = self.course_dir
        source_archive = self.course_dir / "test-zahlen-addieren.h5p"
        source_archive.write_bytes(
            self._build_h5p_archive_bytes(
                {"title": "Test: Zahlen addieren", "mainLibrary": "H5P.PythonQuestion"},
                question.h5p_content or {},
                extra_files={"content/images/instructions.png": b"png-bytes"},
            )
        )
        question.source_package_path = write_source_package_sidecar(question, source_archive)

        mdx = "# Python Kurs\n\n" + "\n".join(render_imported_question_mdx(question)) + "\n"
        (self.course_dir / "index.mdx").write_text(mdx, encoding="utf-8")

        sync_course(self.course_dir)

        self.assertTrue((self.course_dir / "h5p" / "test-zahlen-addieren" / "images" / "instructions.png").exists())
        self.assertTrue((self.course_dir / "h5p" / "test-zahlen-addieren" / "content.mdx").exists())
        self.assertTrue((self.course_dir / "h5p" / "test-zahlen-addieren" / "settings.yml").exists())
        self.assertFalse((self.course_dir / "h5p" / "test-zahlen-addieren" / "content.json").exists())
        with ZipFile(module.course_build_dir(self.course_dir) / "h5p" / "test-zahlen-addieren.h5p") as archive:
            self.assertIn("content/images/instructions.png", archive.namelist())

    @needs_h5p_libraries
    def test_render_imported_question_mdx_uses_readable_strings(self) -> None:
        question = build_imported_question_from_h5p_package(
            "python-2026",
            MoodleH5PActivity(
                identifier="variablen-das-gehirn-des-computers",
                title="Python Question",
                course_id=5,
                activity_id=1,
                instance_id=1,
                section_title="Variablen",
                intro="",
                url="https://example.invalid/mod/h5pactivity/view.php?id=1",
            ),
            {"title": "Python Question", "mainLibrary": "H5P.PythonQuestion"},
            {
                "contentType": "text_only",
                "pythonRunner": "skulpt",
                "contents": [
                    {"type": "text", "text": "Variablen sind das **&quot;Gehirn des Computers&quot;**.\n\n"},
                    {"type": "code", "code": "print(&quot;Hallo&quot;)\n"},
                ],
                "editorSettings": {"instructions": "Variablen sind das **&quot;Gehirn des Computers&quot;**.\n\n", "options": {}},
                "gradingSettings": {},
            },
        )

        assert question is not None
        mdx = "\n".join(render_imported_question_mdx(question))

        self.assertIn('instructions={`Variablen sind das **"Gehirn des Computers"**.', mdx)
        self.assertIn('"text": `', mdx)
        self.assertIn('Variablen sind das **"Gehirn des Computers"**.', mdx)
        self.assertIn('"code": `', mdx)
        self.assertIn('print("Hallo")', mdx)
        self.assertNotIn("&quot;", mdx)

    def test_parse_tag_attributes_supports_template_literals(self) -> None:
        from course_sync import main as module

        attrs = module.mdx_course_parser().parse_tag_attributes(
            ' instructions={`Zeile 1\nZeile 2 mit "Zitat"`} h5p={{"contents": [{"text": `A "B"\n\nC`} ]}} '
        )

        self.assertEqual(attrs["instructions"], 'Zeile 1\nZeile 2 mit "Zitat"')
        assert isinstance(attrs["h5p"], dict)
        self.assertEqual(attrs["h5p"]["contents"][0]["text"], 'A "B"\n\nC')

    @needs_h5p_libraries
    def test_write_h5p_package_patches_original_imported_package(self) -> None:
        from course_sync import main as module

        original_download_file = module.download_file
        original_courses_dir = module.COURSES_DIR
        try:
            module.COURSES_DIR = self.root / "kurse"

            downloaded: list[tuple[str, Path]] = []

            def fake_download(url: str, destination: Path) -> None:
                downloaded.append((url, destination))
                with ZipFile(destination, "w") as archive:
                    archive.writestr("h5p.json", json.dumps({"title": "Original", "mainLibrary": "H5P.QuestionSet"}))
                    archive.writestr("content/content.json", json.dumps({"questions": [{"params": {"question": "Alt?"}}]}))
                    archive.writestr("content/extra.txt", "behalten")

            module.download_file = fake_download
            question = build_imported_question_from_h5p_package(
                "python-2026",
                MoodleH5PActivity(
                    identifier="quiz-division",
                    title="Quiz Division",
                    course_id=5,
                    activity_id=165,
                    instance_id=120,
                    section_title="Quiz",
                    intro="",
                    url="https://example.invalid/mod/h5pactivity/view.php?id=165",
                    package_url="https://example.invalid/pluginfile.php/165/mod_h5pactivity/package/0/quiz-division.h5p",
                ),
                {"title": "Quiz Division", "mainLibrary": "H5P.QuestionSet"},
                {"questions": [{"params": {"question": "Original aus MDX"}}]},
            )

            assert question is not None
            assert question.h5p_content is not None
            question.h5p_content["questions"][0]["params"]["question"] = "Neu?"
            package_path = write_h5p_package(question)
        finally:
            module.download_file = original_download_file
            module.COURSES_DIR = original_courses_dir

        self.assertEqual(len(downloaded), 1)
        self.assertEqual(
            downloaded[0][0],
            "https://example.invalid/pluginfile.php/165/mod_h5pactivity/package/0/quiz-division.h5p",
        )
        self.assertEqual(package_path, self.course_dir / "build" / "h5p" / "quiz-division.h5p")
        self.assertTrue(package_path.exists())
        with ZipFile(package_path) as archive:
            self.assertEqual(json.loads(archive.read("h5p.json").decode("utf-8"))["title"], "Quiz Division")
            self.assertEqual(
                json.loads(archive.read("content/content.json").decode("utf-8"))["questions"][0]["params"]["question"],
                "Neu?",
            )
            self.assertEqual(archive.read("content/extra.txt").decode("utf-8"), "behalten")

    @needs_h5p_libraries
    def test_write_h5p_package_patches_original_python_question_package(self) -> None:
        from course_sync import main as module

        original_download_file = module.download_file
        original_courses_dir = module.COURSES_DIR
        try:
            module.COURSES_DIR = self.root / "kurse"

            downloaded: list[tuple[str, Path]] = []

            def fake_download(url: str, destination: Path) -> None:
                downloaded.append((url, destination))
                with ZipFile(destination, "w") as archive:
                    archive.writestr(
                        "h5p.json",
                        json.dumps({"title": "Original", "mainLibrary": "H5P.PythonQuestion"}),
                    )
                    archive.writestr(
                        "content/content.json",
                        json.dumps({"contentType": "text_only", "pythonRunner": "pyodide", "contents": [], "editorSettings": {}, "gradingSettings": {}}),
                    )
                    archive.writestr("content/extra.txt", "behalten")

            module.download_file = fake_download
            question = build_imported_question_from_h5p_package(
                "python-2026",
                MoodleH5PActivity(
                    identifier="einfuehrung-farben",
                    title="Einführung: Farben",
                    course_id=5,
                    activity_id=145,
                    instance_id=105,
                    section_title="Farben",
                    intro="",
                    url="https://example.invalid/mod/h5pactivity/view.php?id=145",
                    package_url="https://example.invalid/pluginfile.php/168/mod_h5pactivity/package/0/einfuhrung-farben-891.h5p",
                ),
                {"title": "Einführung: Farben", "mainLibrary": "H5P.PythonQuestion"},
                {
                    "contentType": "text_only",
                    "pythonRunner": "skulpt",
                    "contents": [{"type": "text", "text": "A"}],
                    "editorSettings": {"instructions": "A", "options": {}},
                    "gradingSettings": {},
                },
            )

            assert question is not None
            question.title = "Geänderte Farben"
            package_path = write_h5p_package(question)
        finally:
            module.download_file = original_download_file
            module.COURSES_DIR = original_courses_dir

        self.assertEqual(len(downloaded), 1)
        self.assertEqual(
            downloaded[0][0],
            "https://example.invalid/pluginfile.php/168/mod_h5pactivity/package/0/einfuhrung-farben-891.h5p",
        )
        self.assertEqual(package_path, self.course_dir / "build" / "h5p" / "einfuehrung-farben.h5p")
        self.assertTrue(package_path.exists())
        with ZipFile(package_path) as archive:
            self.assertEqual(json.loads(archive.read("h5p.json").decode("utf-8"))["title"], "Geänderte Farben")
            self.assertEqual(json.loads(archive.read("content/content.json").decode("utf-8"))["pythonRunner"], "skulpt")
            self.assertEqual(archive.read("content/extra.txt").decode("utf-8"), "behalten")

    def test_write_h5p_package_recovers_missing_python_question_preloaded_dependencies(self) -> None:
        from course_sync import main as module

        original_download_file = module.download_file
        original_courses_dir = module.COURSES_DIR
        original_runtime_libraries_dir = module.H5P_RUNTIME_LIBRARIES_DIR
        original_ensure_runtime = module.ensure_h5p_runtime_libraries
        try:
            (self.course_dir / "h5p" / "12eck.h5p").write_text("legacy-package", encoding="utf-8")
            (self.course_dir / "h5p" / ".12eck.build-hash").write_text("legacy-hash", encoding="utf-8")
            (self.course_dir / "h5p" / "orphaned-old-package.h5p").write_text("legacy-package", encoding="utf-8")
            (self.course_dir / "h5p" / ".orphaned-old-package.build-hash").write_text("legacy-hash", encoding="utf-8")
            module.COURSES_DIR = self.root / "kurse"
            module.H5P_RUNTIME_LIBRARIES_DIR = self.root / ".h5p-runtime" / "libraries"
            module.ensure_h5p_runtime_libraries = lambda: None

            self._create_fake_library(module.H5P_RUNTIME_LIBRARIES_DIR, "H5P.Question", 1, 5, [])
            self._create_fake_library(module.H5P_RUNTIME_LIBRARIES_DIR, "H5P.LibCodeTools", 6, 73, [])
            self._create_fake_library(
                module.H5P_RUNTIME_LIBRARIES_DIR,
                "H5P.CodeQuestion",
                6,
                73,
                [("H5P.Question", 1, 5), ("H5P.LibCodeTools", 6, 73)],
            )
            self._create_fake_library(
                module.H5P_RUNTIME_LIBRARIES_DIR,
                "H5P.PythonQuestion",
                6,
                73,
                [("H5P.CodeQuestion", 6, 73), ("H5P.LibCodeTools", 6, 73)],
            )

            def fake_download(url: str, destination: Path) -> None:
                with ZipFile(destination, "w") as archive:
                    archive.writestr(
                        "h5p.json",
                        json.dumps({"title": "Original", "mainLibrary": "H5P.PythonQuestion"}),
                    )
                    archive.writestr(
                        "content/content.json",
                        json.dumps(
                            {
                                "contentType": "text_only",
                                "pythonRunner": "skulpt",
                                "contents": [{"type": "text", "text": "A"}],
                                "editorSettings": {"instructions": "A", "options": {}},
                                "gradingSettings": {},
                            }
                        ),
                    )

            module.download_file = fake_download
            question = build_imported_question_from_h5p_package(
                "python-2026",
                MoodleH5PActivity(
                    identifier="einfuehrung-farben",
                    title="Einführung: Farben",
                    course_id=5,
                    activity_id=145,
                    instance_id=105,
                    section_title="Farben",
                    intro="",
                    url="https://example.invalid/mod/h5pactivity/view.php?id=145",
                    package_url="https://example.invalid/pluginfile.php/168/mod_h5pactivity/package/0/einfuhrung-farben-891.h5p",
                ),
                {
                    "title": "Einführung: Farben",
                    "mainLibrary": "H5P.PythonQuestion",
                },
                {
                    "contentType": "text_only",
                    "pythonRunner": "skulpt",
                    "contents": [{"type": "text", "text": "A"}],
                    "editorSettings": {"instructions": "A", "options": {}},
                    "gradingSettings": {},
                },
            )

            assert question is not None
            package_path = write_h5p_package(question)
        finally:
            module.download_file = original_download_file
            module.COURSES_DIR = original_courses_dir
            module.H5P_RUNTIME_LIBRARIES_DIR = original_runtime_libraries_dir
            module.ensure_h5p_runtime_libraries = original_ensure_runtime

        with ZipFile(package_path) as archive:
            metadata = json.loads(archive.read("h5p.json").decode("utf-8"))

        self.assertEqual(metadata["mainLibrary"], "H5P.PythonQuestion")
        self.assertIn("preloadedDependencies", metadata)
        self.assertIsInstance(metadata["preloadedDependencies"], list)
        self.assertGreater(len(metadata["preloadedDependencies"]), 0)

    def test_write_h5p_package_keeps_chapters_source_as_frontmatter_without_due_date(self) -> None:
        from course_sync import main as module

        original_courses_dir = module.COURSES_DIR
        original_runtime_libraries_dir = module.H5P_RUNTIME_LIBRARIES_DIR
        original_ensure_runtime = module.ensure_h5p_runtime_libraries
        try:
            module.COURSES_DIR = self.root / "kurse"
            module.H5P_RUNTIME_LIBRARIES_DIR = self.root / ".h5p-runtime" / "libraries"
            module.ensure_h5p_runtime_libraries = lambda: None

            self._create_fake_library(module.H5P_RUNTIME_LIBRARIES_DIR, "H5P.Question", 1, 5, [])
            self._create_fake_library(module.H5P_RUNTIME_LIBRARIES_DIR, "H5P.LibCodeTools", 6, 73, [])
            self._create_fake_library(
                module.H5P_RUNTIME_LIBRARIES_DIR,
                "H5P.CodeQuestion",
                6,
                73,
                [("H5P.Question", 1, 5), ("H5P.LibCodeTools", 6, 73)],
            )
            self._create_fake_library(
                module.H5P_RUNTIME_LIBRARIES_DIR,
                "H5P.PythonQuestion",
                6,
                73,
                [("H5P.CodeQuestion", 6, 73), ("H5P.LibCodeTools", 6, 73)],
            )

            chapters_course_dir = self.root / "kurse" / "chapters-2026"
            question_dir = chapters_course_dir / "chapters" / "000-intro" / "hello"
            question_dir.mkdir(parents=True)
            (chapters_course_dir / "index.mdx").write_text("# Kurs\n", encoding="utf-8")
            (chapters_course_dir / "course.yml").write_text(
                "h5pDefaults:\n"
                "  mainLibrary: H5P.PythonQuestion\n"
                "  language: de\n"
                "  defaultLanguage: de\n"
                "  license: U\n",
                encoding="utf-8",
            )
            original_mdx = (
                "---\n"
                "contentType: ide_only\n"
                "pythonRunner: pyodide\n"
                "pyodideOptions:\n"
                "  packages: []\n"
                "---\n"
                "<Instructions>\n"
                "Sag Hallo.\n"
                "</Instructions>\n\n"
                "```python editor:startingCode\n"
                "print('Hallo')\n"
                "```\n\n"
                "```python grading:targetCode\n"
                "print('Hallo')\n"
                "```\n\n"
                "```yaml grading\n"
                "gradingMethod: ioTestCases\n"
                "```\n"
            )
            (question_dir / "content.mdx").write_text(original_mdx, encoding="utf-8")

            question = module.build_imported_question_from_sidecar(
                chapters_course_dir, "hello", "chapters/000-intro/hello"
            )
            assert question is not None
            question.due_date = "24.08.2026 23:59"

            package_path = write_h5p_package(question)
        finally:
            module.COURSES_DIR = original_courses_dir
            module.H5P_RUNTIME_LIBRARIES_DIR = original_runtime_libraries_dir
            module.ensure_h5p_runtime_libraries = original_ensure_runtime

        # The tracked source must come back out exactly as it went in: still a single
        # frontmatter-only content.mdx, no sidecar h5p.json/settings.yml, and -- critically --
        # no due date baked in (that's chapter-level state, re-derived on every build).
        self.assertEqual(sorted(p.name for p in question_dir.iterdir()), ["content.mdx"])
        rewritten_mdx = (question_dir / "content.mdx").read_text(encoding="utf-8")
        self.assertEqual(rewritten_mdx, original_mdx)
        self.assertNotIn("dueDateGroup", rewritten_mdx)

        # The built archive still needs a real h5p.json (synthesized from course.yml's
        # h5pDefaults, since none is tracked in the source) and the due date applied to
        # gradingSettings so grading in the browser actually enforces the deadline.
        with ZipFile(package_path) as archive:
            metadata = json.loads(archive.read("h5p.json").decode("utf-8"))
            content = json.loads(archive.read("content/content.json").decode("utf-8"))

        self.assertEqual(metadata["mainLibrary"], "H5P.PythonQuestion")
        self.assertEqual(
            content["gradingSettings"]["dueDateGroup"],
            {"enableDueDate": True, "duedate": "2026-08-24T23:59:00"},
        )

    def test_extract_h5p_package_from_course_backup_recovers_hidden_activity(self) -> None:
        backup_path = self.root / "course.mbz"
        destination = self.root / "timestamps2.h5p"
        package_bytes = self._build_h5p_archive_bytes(
            {"title": "Bonus: Timestamps II", "mainLibrary": "H5P.PythonQuestion"},
            {"contentType": "ide_only", "pythonRunner": "skulpt", "contents": []},
        )
        content_hash = sha1(package_bytes).hexdigest()
        file_member = f"files/{content_hash[:2]}/{content_hash[2:4]}/{content_hash}"
        with tarfile.open(backup_path, "w:gz") as archive:
            self._add_tar_text(
                archive,
                "moodle_backup.xml",
                """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<moodle_backup>
  <information>
    <contents>
      <activities>
        <activity>
          <moduleid>110020</moduleid>
          <modulename>h5pactivity</modulename>
          <title>Bonus: Timestamps II</title>
          <directory>activities/h5pactivity_110020</directory>
        </activity>
      </activities>
    </contents>
  </information>
</moodle_backup>
""",
            )
            self._add_tar_text(
                archive,
                "activities/h5pactivity_110020/inforef.xml",
                """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<inforef><fileref><file><id>4448317</id></file></fileref></inforef>
""",
            )
            self._add_tar_text(
                archive,
                "files.xml",
                f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<files>
  <file id=\"4448317\">
    <contenthash>{content_hash}</contenthash>
    <contextid>197210</contextid>
    <component>mod_h5pactivity</component>
    <filearea>package</filearea>
    <itemid>0</itemid>
    <filepath>/</filepath>
    <filename>timestamps2.h5p</filename>
  </file>
</files>
""",
            )
            self._add_tar_bytes(archive, file_member, package_bytes)

        activity = MoodleH5PActivity(
            identifier="bonus-timestamps-ii",
            title="Bonus: Timestamps II",
            course_id=5,
            activity_id=171,
            instance_id=131,
            section_title="While",
            intro="",
            url="https://example.invalid/mod/h5pactivity/view.php?id=171",
        )

        from course_sync import main as module

        extracted = module.moodle_backup_extractor().extract_h5p_package_from_backup_activity(
            backup_path,
            "activities/h5pactivity_110020",
            destination,
        )

        self.assertTrue(extracted)
        with ZipFile(destination) as archive:
            self.assertEqual(json.loads(archive.read("h5p.json").decode("utf-8"))["title"], "Bonus: Timestamps II")

    def test_download_activity_question_falls_back_to_course_backup(self) -> None:
        backup_path = self.root / "course.mbz"
        package_bytes = self._build_h5p_archive_bytes(
            {"title": "Bonus: Timestamps II", "mainLibrary": "H5P.PythonQuestion"},
            {
                "contentType": "ide_only",
                "pythonRunner": "skulpt",
                "editorSettings": {"instructions": "Aus Backup", "options": {}},
                "gradingSettings": {},
            },
        )
        content_hash = sha1(package_bytes).hexdigest()
        with tarfile.open(backup_path, "w:gz") as archive:
            self._add_tar_text(
                archive,
                "moodle_backup.xml",
                """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<moodle_backup><information><contents><activities><activity><moduleid>110020</moduleid><modulename>h5pactivity</modulename><title>Bonus: Timestamps II</title><directory>activities/h5pactivity_110020</directory></activity></activities></contents></information></moodle_backup>
""",
            )
            self._add_tar_text(
                archive,
                "activities/h5pactivity_110020/inforef.xml",
                """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<inforef><fileref><file><id>4448317</id></file></fileref></inforef>
""",
            )
            self._add_tar_text(
                archive,
                "files.xml",
                f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<files><file id=\"4448317\"><contenthash>{content_hash}</contenthash><component>mod_h5pactivity</component><filearea>package</filearea><filename>timestamps2.h5p</filename></file></files>
""",
            )
            self._add_tar_bytes(archive, f"files/{content_hash[:2]}/{content_hash[2:4]}/{content_hash}", package_bytes)

        from course_sync import main as module

        original_fetch_text = module.fetch_text
        original_download_file = module.download_file
        original_courses_dir = module.COURSES_DIR
        try:
            module.COURSES_DIR = self.root / "kurse"
            def fake_fetch_text(url: str) -> str:
                if "view.php?id=171" in url:
                    return "<html><body>Kein iframe</body></html>"
                if "course/view.php?id=5" in url:
                    return '<a href="https://example.invalid/backup/course.mbz">Backup</a>'
                raise AssertionError(url)

            def fake_download_file(url: str, destination: Path) -> None:
                if url == "https://example.invalid/backup/course.mbz":
                    destination.write_bytes(backup_path.read_bytes())
                    return
                raise AssertionError(url)

            module.fetch_text = fake_fetch_text
            module.download_file = fake_download_file
            backup_extractor = module.moodle_backup_extractor()
            client = MoodleApiClient(
                "https://example.invalid",
                "token",
                make_stable_identifier=module.make_stable_identifier,
                strip_html=module.strip_html,
                fetch_text=module.fetch_text,
                extract_h5p_package_url_from_activity_html=lambda page_html: module.extract_h5p_package_url_from_activity_html(
                    page_html,
                    base_url="https://example.invalid",
                ),
                download_file=module.download_file,
                extract_h5p_package_from_course_backup=backup_extractor.extract_h5p_package_from_course_backup,
                build_imported_question_from_h5p_package=module.build_imported_question_from_h5p_package,
                write_source_package_sidecar=module.write_source_package_sidecar,
            )
            question = client.download_activity_question(
                "python-2026",
                MoodleH5PActivity(
                    identifier="bonus-timestamps-ii",
                    title="Bonus: Timestamps II",
                    course_id=5,
                    activity_id=171,
                    instance_id=131,
                    section_title="While",
                    intro="",
                    url="https://example.invalid/mod/h5pactivity/view.php?id=171",
                ),
            )
        finally:
            module.fetch_text = original_fetch_text
            module.download_file = original_download_file
            module.COURSES_DIR = original_courses_dir

        assert question is not None
        self.assertEqual(question.title, "Bonus: Timestamps II")
        self.assertEqual(question.instructions, "Aus Backup")
        self.assertEqual(question.source_package_path, "h5p/bonus-timestamps-ii")
        self.assertTrue((self.root / "kurse" / "python-2026" / question.source_package_path).exists())

    def test_load_course_preview_state_uses_cache_until_mdx_changes(self) -> None:
        from course_sync import main as module

        original_courses_dir = module.COURSES_DIR
        original_preview_cache = dict(module.PREVIEW_CACHE)
        try:
            module.COURSES_DIR = self.root / "kurse"
            module.PREVIEW_CACHE.clear()

            questions_one, html_one = load_course_preview_state(self.course_dir)
            questions_two, html_two = load_course_preview_state(self.course_dir)

            self.assertIs(questions_one, questions_two)
            self.assertEqual(html_one, html_two)

            updated = (self.course_dir / "index.mdx").read_text(encoding="utf-8") + "\n\n## Neu\n"
            (self.course_dir / "index.mdx").write_text(updated, encoding="utf-8")

            questions_three, html_three = load_course_preview_state(self.course_dir)
        finally:
            module.COURSES_DIR = original_courses_dir
            module.PREVIEW_CACHE.clear()
            module.PREVIEW_CACHE.update(original_preview_cache)

        self.assertIsNot(questions_one, questions_three)
        self.assertEqual(html_three, render_course_page(self.course_dir, questions=questions_three, rendered_source=parse_course(self.course_dir)[2]))

    def test_sync_metadata_roundtrip(self) -> None:
        metadata = SyncMetadata(
            course_slug="python-2026",
            remote_course_id=5,
            moodle_base_url="https://example.invalid",
            entries={
                "12eck": SyncMetadataEntry(
                    identifier="12eck",
                    remote_activity_id=134,
                    remote_instance_id=77,
                    remote_title="Zwölfeck zeichnen",
                    remote_url="https://example.invalid/mod/h5pactivity/view.php?id=134",
                    remote_visible=True,
                    local_hash="abc",
                )
            },
        )

        save_sync_metadata(self.course_dir, metadata)
        reloaded = load_sync_metadata(self.course_dir)

        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded.remote_course_id, 5)
        self.assertEqual(reloaded.entries["12eck"].remote_activity_id, 134)
        self.assertEqual(reloaded.entries["12eck"].local_hash, "abc")

    def test_load_dotenv_file_sets_missing_values_only(self) -> None:
        from course_sync import main as module

        dotenv_path = self.root / ".env"
        dotenv_path.write_text(
            'MOODLE_BASE_URL="https://example.invalid"\nMOODLE_TOKEN=test-token\n',
            encoding="utf-8",
        )

        original_base = os.environ.pop("MOODLE_BASE_URL", None)
        original_token = os.environ.pop("MOODLE_TOKEN", None)
        try:
            module.moodle_client_resolver().load_dotenv_file(dotenv_path)
            self.assertEqual(os.environ["MOODLE_BASE_URL"], "https://example.invalid")
            self.assertEqual(os.environ["MOODLE_TOKEN"], "test-token")

            os.environ["MOODLE_TOKEN"] = "override-token"
            module.moodle_client_resolver().load_dotenv_file(dotenv_path)
            self.assertEqual(os.environ["MOODLE_TOKEN"], "override-token")
        finally:
            if original_base is None:
                os.environ.pop("MOODLE_BASE_URL", None)
            else:
                os.environ["MOODLE_BASE_URL"] = original_base
            if original_token is None:
                os.environ.pop("MOODLE_TOKEN", None)
            else:
                os.environ["MOODLE_TOKEN"] = original_token

    def test_resolve_moodle_client_reads_from_dotenv(self) -> None:
        from course_sync import main as module

        dotenv_path = self.root / ".env"
        dotenv_path.write_text(
            "MOODLE_BASE_URL=https://example.invalid\nMOODLE_TOKEN=token-from-env\n",
            encoding="utf-8",
        )

        original_dotenv_file = module.DOTENV_FILE
        original_base = os.environ.pop("MOODLE_BASE_URL", None)
        original_token = os.environ.pop("MOODLE_TOKEN", None)
        try:
            module.DOTENV_FILE = dotenv_path
            client = resolve_moodle_client()
            self.assertEqual(client.base_url, "https://example.invalid")
            self.assertEqual(client.token, "token-from-env")
        finally:
            module.DOTENV_FILE = original_dotenv_file
            if original_base is None:
                os.environ.pop("MOODLE_BASE_URL", None)
            else:
                os.environ["MOODLE_BASE_URL"] = original_base
            if original_token is None:
                os.environ.pop("MOODLE_TOKEN", None)
            else:
                os.environ["MOODLE_TOKEN"] = original_token

    def test_upload_moodle_chapter_prefers_course_specific_dotenv_values(self) -> None:
        from course_sync import main as module

        dotenv_path = self.root / ".env"
        dotenv_path.write_text(
            "\n".join(
                [
                    "MOODLE_COURSE_URL=https://global.example/course/view.php?id=1",
                    "MOODLE_USERNAME=global-user",
                    "MOODLE_PASSWORD=global-pass",
                    "MOODLE_PYTHON_2026_COURSE_URL=https://course.example/course/view.php?id=5",
                    "MOODLE_PYTHON_2026_USERNAME=course-user",
                    "MOODLE_PYTHON_2026_PASSWORD=course-pass",
                ]
            ),
            encoding="utf-8",
        )

        captured: dict[str, object] = {}

        class FakeUploader:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            def ensure_section_visible(self) -> None:
                pass

            def upload_packages(self, packages: object) -> list[object]:
                captured["packages"] = packages
                return []

        original_dotenv_file = module.DOTENV_FILE
        original_sync_course = module.sync_course
        original_collect = module.collect_h5p_upload_packages
        original_uploader = module.MoodlePlaywrightUploader
        original_keys = {
            key: os.environ.pop(key, None)
            for key in [
                "MOODLE_COURSE_URL",
                "MOODLE_USERNAME",
                "MOODLE_PASSWORD",
                "MOODLE_PYTHON_2026_COURSE_URL",
                "MOODLE_PYTHON_2026_USERNAME",
                "MOODLE_PYTHON_2026_PASSWORD",
            ]
        }
        try:
            module.DOTENV_FILE = dotenv_path
            module.sync_course = lambda _course_dir: []
            module.collect_h5p_upload_packages = lambda _course_dir, _chapter: []
            module.MoodlePlaywrightUploader = FakeUploader

            module.upload_moodle_chapter(self.course_dir, "013-texte-strings")

            self.assertEqual(captured["course_url"], "https://course.example/course/view.php?id=5")
            self.assertEqual(captured["username"], "course-user")
            self.assertEqual(captured["password"], "course-pass")
        finally:
            module.DOTENV_FILE = original_dotenv_file
            module.sync_course = original_sync_course
            module.collect_h5p_upload_packages = original_collect
            module.MoodlePlaywrightUploader = original_uploader
            for key, value in original_keys.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_upload_moodle_chapter_prefers_named_target_dotenv_values(self) -> None:
        from course_sync import main as module

        dotenv_path = self.root / ".env"
        dotenv_path.write_text(
            "\n".join(
                [
                    "MOODLE_PYTHON_2026_COURSE_URL=https://primary.example/course/view.php?id=5",
                    "MOODLE_PYTHON_2026_USERNAME=primary-user",
                    "MOODLE_PYTHON_2026_PASSWORD=primary-pass",
                    "MOODLE_PYTHON_2026_SECOND_COURSE_URL=https://second.example/course/view.php?id=9",
                    "MOODLE_PYTHON_2026_SECOND_USERNAME=second-user",
                    "MOODLE_PYTHON_2026_SECOND_PASSWORD=second-pass",
                ]
            ),
            encoding="utf-8",
        )

        captured: dict[str, object] = {}

        class FakeUploader:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            def ensure_section_visible(self) -> None:
                pass

            def upload_packages(self, packages: object) -> list[object]:
                captured["packages"] = packages
                return []

        original_dotenv_file = module.DOTENV_FILE
        original_sync_course = module.sync_course
        original_collect = module.collect_h5p_upload_packages
        original_uploader = module.MoodlePlaywrightUploader
        original_store = module._store_uploaded_activity_ids
        store_calls: list[object] = []
        original_keys = {
            key: os.environ.pop(key, None)
            for key in [
                "MOODLE_PYTHON_2026_COURSE_URL",
                "MOODLE_PYTHON_2026_USERNAME",
                "MOODLE_PYTHON_2026_PASSWORD",
                "MOODLE_PYTHON_2026_SECOND_COURSE_URL",
                "MOODLE_PYTHON_2026_SECOND_USERNAME",
                "MOODLE_PYTHON_2026_SECOND_PASSWORD",
            ]
        }
        try:
            module.DOTENV_FILE = dotenv_path
            module.sync_course = lambda _course_dir: []
            module.collect_h5p_upload_packages = lambda _course_dir, _chapter: []
            module.MoodlePlaywrightUploader = FakeUploader
            module._store_uploaded_activity_ids = lambda *args: store_calls.append(args)

            module.upload_moodle_chapter(self.course_dir, "013-texte-strings", target="second")

            self.assertEqual(captured["course_url"], "https://second.example/course/view.php?id=9")
            self.assertEqual(captured["username"], "second-user")
            self.assertEqual(captured["password"], "second-pass")
            self.assertEqual(captured["storage_state"], self.course_dir / ".moodle-storage-state-second.json")
            self.assertEqual(store_calls, [])
        finally:
            module.DOTENV_FILE = original_dotenv_file
            module.sync_course = original_sync_course
            module.collect_h5p_upload_packages = original_collect
            module.MoodlePlaywrightUploader = original_uploader
            module._store_uploaded_activity_ids = original_store
            for key, value in original_keys.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_resolve_moodle_course_url_reads_named_target_config(self) -> None:
        from course_sync import main as module

        target_path = self.course_dir / ".moodle-target-schulportal.yml"
        target_path.write_text(
            "auth: schulportal-hessen\n"
            "course_url: https://mo5235.schulportal.hessen.de/course/view.php?id=8128\n",
            encoding="utf-8",
        )
        keys = [
            "MOODLE_PYTHON_2026_SCHULPORTAL_COURSE_URL",
            "MOODLE_PYTHON_2026_COURSE_URL",
            "MOODLE_COURSE_URL",
        ]
        original_values = {key: os.environ.pop(key, None) for key in keys}
        try:
            self.assertEqual(
                module._resolve_moodle_course_url(self.course_dir, None, "schulportal"),
                "https://mo5235.schulportal.hessen.de/course/view.php?id=8128",
            )
        finally:
            for key, value in original_values.items():
                if value is not None:
                    os.environ[key] = value

    def test_resolve_moodle_course_url_prefers_target_yaml_over_course_and_global_env(self) -> None:
        from course_sync import main as module

        (self.course_dir / ".moodle-target-neu.yml").write_text(
            "course_url: https://neu.example/course/view.php?id=42\n", encoding="utf-8"
        )
        env = {
            "MOODLE_PYTHON_2026_COURSE_URL": "https://alt.example/course/view.php?id=5",
            "MOODLE_COURSE_URL": "https://global.example/course/view.php?id=1",
        }
        original = {key: os.environ.get(key) for key in [*env, "MOODLE_PYTHON_2026_NEU_COURSE_URL"]}
        os.environ.pop("MOODLE_PYTHON_2026_NEU_COURSE_URL", None)
        os.environ.update(env)
        try:
            self.assertEqual(
                module._resolve_moodle_course_url(self.course_dir, None, "neu"),
                "https://neu.example/course/view.php?id=42",
            )
            os.environ["MOODLE_PYTHON_2026_NEU_COURSE_URL"] = "https://env.example/course/view.php?id=7"
            self.assertEqual(
                module._resolve_moodle_course_url(self.course_dir, None, "neu"),
                "https://env.example/course/view.php?id=7",
            )
            # Ohne Ziel bleibt die Kurs-Variable massgeblich.
            self.assertEqual(
                module._resolve_moodle_course_url(self.course_dir, None, None),
                "https://alt.example/course/view.php?id=5",
            )
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_upload_moodle_chapter_reads_credentials_for_sso_target(self) -> None:
        from course_sync import main as module

        (self.course_dir / ".moodle-target-2.yml").write_text("auth: sso\n", encoding="utf-8")
        dotenv_path = self.root / ".env"
        dotenv_path.write_text(
            "\n".join(
                [
                    "MOODLE_PYTHON_2026_2_COURSE_URL=https://mo5235.schulportal.hessen.de/course/view.php?id=7845",
                    "MOODLE_PYTHON_2026_2_USERNAME=sso-user",
                    "MOODLE_PYTHON_2026_2_PASSWORD=sso-pass",
                ]
            ),
            encoding="utf-8",
        )

        captured: dict[str, object] = {}

        class FakeUploader:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            def ensure_section_visible(self) -> None:
                pass

            def upload_packages(self, packages: object) -> list[object]:
                return []

        original_dotenv_file = module.DOTENV_FILE
        original_sync_course = module.sync_course
        original_collect = module.collect_h5p_upload_packages
        original_uploader = module.MoodlePlaywrightUploader
        original_keys = {
            key: os.environ.pop(key, None)
            for key in [
                "MOODLE_PYTHON_2026_2_COURSE_URL",
                "MOODLE_PYTHON_2026_2_USERNAME",
                "MOODLE_PYTHON_2026_2_PASSWORD",
            ]
        }
        try:
            module.DOTENV_FILE = dotenv_path
            module.sync_course = lambda _course_dir: []
            module.collect_h5p_upload_packages = lambda _course_dir, _chapter: []
            module.MoodlePlaywrightUploader = FakeUploader

            module.upload_moodle_chapter(self.course_dir, "013-texte-strings", target="2")

            self.assertEqual(captured["course_url"], "https://mo5235.schulportal.hessen.de/course/view.php?id=7845")
            self.assertEqual(captured["username"], "sso-user")
            self.assertEqual(captured["password"], "sso-pass")
        finally:
            module.DOTENV_FILE = original_dotenv_file
            module.sync_course = original_sync_course
            module.collect_h5p_upload_packages = original_collect
            module.MoodlePlaywrightUploader = original_uploader
            for key, value in original_keys.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_upload_moodle_chapter_infers_sso_target_from_course_url(self) -> None:
        from course_sync import main as module

        course_url = "https://mo5235.schulportal.hessen.de/course/view.php?id=8128"
        (self.course_dir / ".moodle-target-schulportal.yml").write_text(
            f"auth: schulportal-hessen\ncourse_url: {course_url}\n",
            encoding="utf-8",
        )
        dotenv_path = self.root / ".env"
        dotenv_path.write_text(
            "\n".join(
                [
                    "MOODLE_PYTHON_2026_SCHULPORTAL_USERNAME=sso-user",
                    "MOODLE_PYTHON_2026_SCHULPORTAL_PASSWORD=sso-pass",
                ]
            ),
            encoding="utf-8",
        )

        captured: dict[str, object] = {}

        class FakeUploader:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            def ensure_section_visible(self) -> None:
                pass

            def upload_packages(self, packages: object) -> list[object]:
                return []

        original_dotenv_file = module.DOTENV_FILE
        original_sync_course = module.sync_course
        original_collect = module.collect_h5p_upload_packages
        original_existing_ids = module._load_existing_h5p_activity_ids_from_moodle
        original_uploader = module.MoodlePlaywrightUploader
        original_keys = {
            key: os.environ.pop(key, None)
            for key in [
                "MOODLE_PYTHON_2026_SCHULPORTAL_USERNAME",
                "MOODLE_PYTHON_2026_SCHULPORTAL_PASSWORD",
            ]
        }
        try:
            module.DOTENV_FILE = dotenv_path
            module.sync_course = lambda _course_dir: []
            module.collect_h5p_upload_packages = lambda _course_dir, _chapter: []
            module._load_existing_h5p_activity_ids_from_moodle = lambda *_args, **_kwargs: {}
            module.MoodlePlaywrightUploader = FakeUploader

            module.upload_moodle_chapter(self.course_dir, "013-texte-strings", course_url=course_url)

            self.assertEqual(captured["course_url"], course_url)
            self.assertEqual(captured["username"], "sso-user")
            self.assertEqual(captured["password"], "sso-pass")
            self.assertEqual(captured["storage_state"], self.course_dir / ".moodle-storage-state-schulportal.json")
        finally:
            module.DOTENV_FILE = original_dotenv_file
            module.sync_course = original_sync_course
            module.collect_h5p_upload_packages = original_collect
            module._load_existing_h5p_activity_ids_from_moodle = original_existing_ids
            module.MoodlePlaywrightUploader = original_uploader
            for key, value in original_keys.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_upload_moodle_chapter_prefers_index_title_for_section_title(self) -> None:
        from course_sync import main as module

        (self.course_dir / "chapters").mkdir()
        (self.course_dir / "chapters" / "013-texte-strings.mdx").write_text(
            "## Texte (Strings)\n\n<PythonQuestion identifier=\"strings-grundlagen\" />\n",
            encoding="utf-8",
        )
        (self.course_dir / "index.mdx").write_text(
            '# Python Kurs\n\n<Chapter src="./chapters/013-texte-strings.mdx" title="Schleifen und Texte" />\n',
            encoding="utf-8",
        )

        captured: dict[str, object] = {}

        class FakeUploader:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            def ensure_section_visible(self) -> None:
                pass

            def upload_packages(self, packages: object) -> list[object]:
                return []

        original_sync_course = module.sync_course
        original_collect = module.collect_h5p_upload_packages
        original_uploader = module.MoodlePlaywrightUploader
        try:
            module.sync_course = lambda _course_dir: []
            module.collect_h5p_upload_packages = lambda _course_dir, _chapter: []
            module.MoodlePlaywrightUploader = FakeUploader

            module.upload_moodle_chapter(
                self.course_dir,
                "013-texte-strings",
                course_url="https://example.invalid/course/view.php?id=5",
            )

            self.assertEqual(captured["section_title"], "Schleifen und Texte")
        finally:
            module.sync_course = original_sync_course
            module.collect_h5p_upload_packages = original_collect
            module.MoodlePlaywrightUploader = original_uploader

    def test_upload_moodle_chapter_matches_section_visibility_to_hidden_flag(self) -> None:
        from course_sync import main as module

        (self.course_dir / "chapters").mkdir()
        (self.course_dir / "index.mdx").write_text(
            "# Kurs\n\n"
            '<Chapter src="./chapters/001-sichtbar.mdx" title="Sichtbar" />\n'
            '<Chapter src="./chapters/002-verborgen.mdx" title="Verborgen" hidden synced={false} />\n'
            '<Chapter src="./chapters/003-explizit-sichtbar.mdx" title="Explizit" hidden={false} />\n',
            encoding="utf-8",
        )
        self.assertFalse(module._chapter_hidden_from_index(self.course_dir, "001-sichtbar"))
        self.assertTrue(module._chapter_hidden_from_index(self.course_dir, "002-verborgen"))
        self.assertFalse(module._chapter_hidden_from_index(self.course_dir, "003-explizit-sichtbar"))
        self.assertFalse(module._chapter_hidden_from_index(self.course_dir, "unbekannt"))

        calls: list[str] = []

        class FakeUploader:
            def __init__(self, **kwargs: object) -> None:
                pass

            def ensure_section_hidden(self) -> None:
                calls.append("hide")

            def ensure_section_visible(self) -> None:
                calls.append("show")

            def upload_packages(self, packages: object) -> list[object]:
                calls.append("upload")
                return []

        original_sync_course = module.sync_course
        original_collect = module.collect_h5p_upload_packages
        original_uploader = module.MoodlePlaywrightUploader
        try:
            module.sync_course = lambda _course_dir: []
            module.collect_h5p_upload_packages = lambda _course_dir, _chapter: []
            module.MoodlePlaywrightUploader = FakeUploader
            course_url = "https://example.invalid/course/view.php?id=5"

            module.upload_moodle_chapter(self.course_dir, "002-verborgen", course_url=course_url)
            self.assertEqual(calls, ["hide", "upload"])

            calls.clear()
            module.upload_moodle_chapter(self.course_dir, "001-sichtbar", course_url=course_url)
            self.assertEqual(calls, ["show", "upload"])
        finally:
            module.sync_course = original_sync_course
            module.collect_h5p_upload_packages = original_collect
            module.MoodlePlaywrightUploader = original_uploader

    def test_load_existing_h5p_activity_ids_skips_ambiguous_titles(self) -> None:
        from course_sync import main as module

        class FakeClient:
            def list_course_h5p_activities(self, course_id: int):
                self.course_id = course_id
                return [
                    type("Activity", (), {"activity_id": 197, "title": "Python Question"})(),
                    type("Activity", (), {"activity_id": 198, "title": "Python Question"})(),
                ]

        original_resolve = module.resolve_moodle_client
        try:
            module.resolve_moodle_client = lambda: FakeClient()
            packages = [
                type("Pkg", (), {"identifier": "a", "title": "Python Question"})(),
                type("Pkg", (), {"identifier": "b", "title": "Python Question"})(),
            ]

            result = module._load_existing_h5p_activity_ids_from_moodle(
                self.course_dir,
                "https://example.invalid/course/view.php?id=5",
                packages,
            )

            self.assertEqual(result, {})
        finally:
            module.resolve_moodle_client = original_resolve

    def test_load_existing_h5p_activity_ids_maps_unique_title(self) -> None:
        from course_sync import main as module

        class FakeClient:
            def list_course_h5p_activities(self, course_id: int):
                self.course_id = course_id
                return [
                    type("Activity", (), {"activity_id": 241, "title": "Funktionen definieren"})(),
                ]

        original_resolve = module.resolve_moodle_client
        try:
            module.resolve_moodle_client = lambda: FakeClient()
            packages = [
                type("Pkg", (), {"identifier": "funktionen-definieren", "title": "Funktionen definieren"})(),
            ]

            result = module._load_existing_h5p_activity_ids_from_moodle(
                self.course_dir,
                "https://example.invalid/course/view.php?id=5",
                packages,
            )

            self.assertEqual(result, {"funktionen-definieren": 241})
        finally:
            module.resolve_moodle_client = original_resolve

    def test_build_moodle_ping_report_detects_import_capability(self) -> None:
        class FakeMoodleClient:
            base_url = "https://example.invalid"

            def get_site_info(self) -> dict[str, object]:
                return {
                    "sitename": "OpenCode",
                    "siteurl": "https://example.invalid",
                    "userid": 42,
                    "username": "service-user",
                    "fullname": "Service User",
                    "functions": [
                        {"name": "core_course_get_contents"},
                        {"name": "core_webservice_get_site_info"},
                    ],
                }

        report = build_moodle_ping_report(FakeMoodleClient())

        self.assertEqual(report["baseUrl"], "https://example.invalid")
        self.assertEqual(report["siteName"], "OpenCode")
        self.assertEqual(report["userName"], "service-user")
        self.assertTrue(report["supportsCourseImport"])
        self.assertFalse(report["supportsCoursePush"])
        self.assertIn("core_course_get_contents", report["functions"])
        self.assertTrue(report["pushBlockers"])

    def test_moodle_api_client_push_support_report_marks_missing_write_apis(self) -> None:
        class StubMoodleApiClient(MoodleApiClient):
            def get_available_function_names(self) -> list[str]:
                return ["core_course_get_contents", "core_webservice_get_site_info"]

        client = StubMoodleApiClient(
            "https://example.invalid",
            "token",
            make_stable_identifier=lambda title, used: make_stable_identifier(title, used),
            strip_html=lambda text: text,
            fetch_text=lambda url: "",
            extract_h5p_package_url_from_activity_html=lambda page_html: "",
            download_file=lambda url, destination: None,
            extract_h5p_package_from_course_backup=lambda base, activity, archive_path: False,
            build_imported_question_from_h5p_package=lambda course_slug, activity, metadata, content: None,
            write_source_package_sidecar=lambda question, archive_path: "",
        )

        report = client.build_course_push_support_report()

        self.assertFalse(report["supportsCoursePush"])
        self.assertFalse(report["supportsDraftUpload"])
        self.assertFalse(report["supportsModuleCreation"])
        self.assertTrue(report["blockers"])

    def test_find_library_dir_seeds_runtime_from_local_archive(self) -> None:
        from course_sync.classes import H5PLibraryManager

        runtime_dir = self.root / ".h5p-runtime"
        runtime_libraries_dir = runtime_dir / "libraries"
        runtime_downloads_dir = runtime_dir / "downloads"
        shared_libraries_dir = self.root / "ressourcen" / "libraries"
        shared_libraries_dir.mkdir(parents=True, exist_ok=True)

        archive_path = self.course_dir / "build" / "h5p" / "quiz-division.h5p"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(
            self._build_h5p_archive_bytes(
                {"title": "Quiz", "mainLibrary": "H5P.MultiChoice"},
                {"question": "2+2?"},
                libraries={
                    "H5P.MultiChoice-1.16": {
                        "machineName": "H5P.MultiChoice",
                        "majorVersion": 1,
                        "minorVersion": 16,
                    }
                },
            )
        )

        manager = H5PLibraryManager(
            workspace_lock=threading.RLock(),
            runtime_dir=runtime_dir,
            runtime_content_dir=runtime_dir / "content",
            runtime_libraries_dir=runtime_libraries_dir,
            runtime_downloads_dir=runtime_downloads_dir,
            shared_libraries_dir=shared_libraries_dir,
            courses_dir=self.root / "kurse",
            release_repo="repo",
            release_tag="tag",
            asset_prefixes={},
            custom_short_names={},
            ensure_directory=lambda path: path.mkdir(parents=True, exist_ok=True),
            read_json=lambda path: json.loads(path.read_text(encoding="utf-8")),
            read_json_or_default=lambda path, default: default if not path.exists() else json.loads(path.read_text(encoding="utf-8")),
            write_json=lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"),
            fetch_json=lambda url: {},
            download_file=lambda url, destination: None,
        )

        library_dir = manager.find_library_dir("H5P.MultiChoice", 1, 16)

        self.assertEqual(library_dir.name, "H5P.MultiChoice-1.16")
        self.assertTrue((runtime_libraries_dir / "H5P.MultiChoice-1.16" / "library.json").exists())

    def test_find_library_dir_without_version_uses_highest_numeric_version(self) -> None:
        from course_sync.classes import H5PLibraryManager

        runtime_dir = self.root / ".h5p-runtime"
        runtime_libraries_dir = runtime_dir / "libraries"
        shared_libraries_dir = self.root / "ressourcen" / "libraries"
        for minor_version in (99, 110):
            library_dir = runtime_libraries_dir / f"H5P.CodeQuestion-6.{minor_version}"
            library_dir.mkdir(parents=True)
            (library_dir / "library.json").write_text(
                json.dumps(
                    {
                        "machineName": "H5P.CodeQuestion",
                        "majorVersion": 6,
                        "minorVersion": minor_version,
                    }
                ),
                encoding="utf-8",
            )

        manager = H5PLibraryManager(
            workspace_lock=threading.RLock(),
            runtime_dir=runtime_dir,
            runtime_content_dir=runtime_dir / "content",
            runtime_libraries_dir=runtime_libraries_dir,
            runtime_downloads_dir=runtime_dir / "downloads",
            shared_libraries_dir=shared_libraries_dir,
            courses_dir=self.root / "kurse",
            release_repo="repo",
            release_tag="tag",
            asset_prefixes={},
            custom_short_names={},
            ensure_directory=lambda path: path.mkdir(parents=True, exist_ok=True),
            read_json=lambda path: json.loads(path.read_text(encoding="utf-8")),
            read_json_or_default=lambda path, default: default if not path.exists() else json.loads(path.read_text(encoding="utf-8")),
            write_json=lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"),
            fetch_json=lambda url: {},
            download_file=lambda url, destination: None,
        )

        self.assertEqual(manager.find_library_dir("H5P.CodeQuestion").name, "H5P.CodeQuestion-6.110")

    def test_python_question_multiple_choice_runtime_fix_creates_versioned_copies(self) -> None:
        from course_sync.classes import H5PLibraryManager

        runtime_dir = self.root / ".h5p-runtime"
        runtime_libraries_dir = runtime_dir / "libraries"
        shared_libraries_dir = self.root / "ressourcen" / "libraries"
        code_dir = runtime_libraries_dir / "H5P.CodeQuestion-6.109"
        python_dir = runtime_libraries_dir / "H5P.PythonQuestion-6.115"
        code_dir.mkdir(parents=True)
        python_dir.mkdir(parents=True)
        (code_dir / "library.json").write_text(
            json.dumps(
                {
                    "machineName": "H5P.CodeQuestion",
                    "majorVersion": 6,
                    "minorVersion": 109,
                }
            ),
            encoding="utf-8",
        )
        (python_dir / "library.json").write_text(
            json.dumps(
                {
                    "machineName": "H5P.PythonQuestion",
                    "majorVersion": 6,
                    "minorVersion": 115,
                    "preloadedDependencies": [
                        {
                            "machineName": "H5P.CodeQuestion",
                            "majorVersion": 6,
                            "minorVersion": 109,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        manager = H5PLibraryManager(
            workspace_lock=threading.RLock(),
            runtime_dir=runtime_dir,
            runtime_content_dir=runtime_dir / "content",
            runtime_libraries_dir=runtime_libraries_dir,
            runtime_downloads_dir=runtime_dir / "downloads",
            shared_libraries_dir=shared_libraries_dir,
            courses_dir=self.root / "kurse",
            release_repo="repo",
            release_tag="tag",
            asset_prefixes={},
            custom_short_names={},
            ensure_directory=lambda path: path.mkdir(parents=True, exist_ok=True),
            read_json=lambda path: json.loads(path.read_text(encoding="utf-8")),
            read_json_or_default=lambda path, default: default if not path.exists() else json.loads(path.read_text(encoding="utf-8")),
            write_json=lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"),
            fetch_json=lambda url: {},
            download_file=lambda url, destination: None,
        )

        manager.ensure_python_question_multiple_choice_runtime_fix()

        fixed_code = json.loads((runtime_libraries_dir / "H5P.CodeQuestion-6.110" / "library.json").read_text(encoding="utf-8"))
        fixed_python = json.loads((runtime_libraries_dir / "H5P.PythonQuestion-6.116" / "library.json").read_text(encoding="utf-8"))
        self.assertEqual(fixed_code["minorVersion"], 110)
        self.assertEqual(fixed_python["minorVersion"], 116)
        self.assertEqual(fixed_python["preloadedDependencies"][0]["minorVersion"], 110)

    def test_update_custom_libraries_from_github_downloads_latest_release_to_shared_and_runtime(self) -> None:
        from course_sync.classes import H5PLibraryManager

        runtime_dir = self.root / ".h5p-runtime"
        runtime_libraries_dir = runtime_dir / "libraries"
        runtime_downloads_dir = runtime_dir / "downloads"
        shared_libraries_dir = self.root / "ressourcen" / "libraries"
        (shared_libraries_dir / "H5P.PythonQuestion-6.73").mkdir(parents=True)
        (runtime_libraries_dir / "H5P.PythonQuestion-6.73").mkdir(parents=True)

        archive_payload = self._build_h5p_archive_bytes(
            {"title": "Question", "mainLibrary": "H5P.PythonQuestion"},
            {},
            libraries={
                "H5P.PythonQuestion-6.74": {
                    "machineName": "H5P.PythonQuestion",
                    "majorVersion": 6,
                    "minorVersion": 74,
                    "title": "Python Question",
                }
            },
        )
        downloads = {"https://example.invalid/H5P.PythonQuestion-6.74.h5p": archive_payload}
        fetched_urls: list[str] = []

        manager = H5PLibraryManager(
            workspace_lock=threading.RLock(),
            runtime_dir=runtime_dir,
            runtime_content_dir=runtime_dir / "content",
            runtime_libraries_dir=runtime_libraries_dir,
            runtime_downloads_dir=runtime_downloads_dir,
            shared_libraries_dir=shared_libraries_dir,
            courses_dir=self.root / "kurse",
            release_repo="owner/repo",
            release_tag="old-tag",
            asset_prefixes={"H5P.PythonQuestion": "H5P.PythonQuestion-6.73_"},
            custom_short_names={"H5P.PythonQuestion": "h5p-python-question"},
            ensure_directory=lambda path: path.mkdir(parents=True, exist_ok=True),
            read_json=lambda path: json.loads(path.read_text(encoding="utf-8")),
            read_json_or_default=lambda path, default: default if not path.exists() else json.loads(path.read_text(encoding="utf-8")),
            write_json=lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"),
            fetch_json=lambda url: fetched_urls.append(url)
            or {
                "tag_name": "v6.74.0",
                "assets": [
                    {
                        "name": "H5P.PythonQuestion-6.74_20260511.h5p",
                        "browser_download_url": "https://example.invalid/H5P.PythonQuestion-6.74.h5p",
                    }
                ],
            },
            download_file=lambda url, destination: destination.write_bytes(downloads[url]),
        )

        updated = manager.update_custom_libraries_from_github()

        self.assertEqual(fetched_urls, ["https://api.github.com/repos/owner/repo/releases/latest"])
        self.assertEqual(updated[0]["asset"], "H5P.PythonQuestion-6.74_20260511.h5p")
        self.assertFalse((shared_libraries_dir / "H5P.PythonQuestion-6.73").exists())
        self.assertFalse((runtime_libraries_dir / "H5P.PythonQuestion-6.73").exists())
        self.assertTrue((shared_libraries_dir / "H5P.PythonQuestion-6.74" / "library.json").exists())
        self.assertTrue((runtime_libraries_dir / "H5P.PythonQuestion-6.74" / "library.json").exists())
        registry = json.loads((runtime_dir / "libraryRegistry.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["H5P.PythonQuestion"]["shortName"], "h5p-python-question")

    def test_update_custom_libraries_from_local_export_installs_newest_version(self) -> None:
        from course_sync.classes import H5PLibraryManager

        runtime_dir = self.root / ".h5p-runtime"
        runtime_libraries_dir = runtime_dir / "libraries"
        runtime_downloads_dir = runtime_dir / "downloads"
        shared_libraries_dir = self.root / "ressourcen" / "libraries"
        export_dir = self.root / "h5p-dev" / "export"
        export_dir.mkdir(parents=True)
        (shared_libraries_dir / "H5P.PythonQuestion-6.73").mkdir(parents=True)
        (runtime_libraries_dir / "H5P.PythonQuestion-6.73").mkdir(parents=True)

        for minor_version in (151, 152):
            archive_payload = self._build_h5p_archive_bytes(
                {"title": "Question", "mainLibrary": "H5P.PythonQuestion"},
                {},
                libraries={
                    f"H5P.PythonQuestion-6.{minor_version}": {
                        "machineName": "H5P.PythonQuestion",
                        "majorVersion": 6,
                        "minorVersion": minor_version,
                        "title": "Python Question",
                    }
                },
            )
            (export_dir / f"H5P.PythonQuestion-6.{minor_version}_20261022.h5p").write_bytes(archive_payload)

        manager = H5PLibraryManager(
            workspace_lock=threading.RLock(),
            runtime_dir=runtime_dir,
            runtime_content_dir=runtime_dir / "content",
            runtime_libraries_dir=runtime_libraries_dir,
            runtime_downloads_dir=runtime_downloads_dir,
            shared_libraries_dir=shared_libraries_dir,
            courses_dir=self.root / "kurse",
            release_repo="owner/repo",
            release_tag="old-tag",
            asset_prefixes={
                "H5P.PythonQuestion": "H5P.PythonQuestion-6.73_",
                "H5P.CodeQuestion": "H5P.CodeQuestion-6.104_",
            },
            custom_short_names={"H5P.PythonQuestion": "h5p-python-question"},
            ensure_directory=lambda path: path.mkdir(parents=True, exist_ok=True),
            read_json=lambda path: json.loads(path.read_text(encoding="utf-8")),
            read_json_or_default=lambda path, default: default if not path.exists() else json.loads(path.read_text(encoding="utf-8")),
            write_json=lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"),
            fetch_json=lambda url: {},
            download_file=lambda url, destination: None,
        )

        updated = manager.update_custom_libraries_from_local_export(export_dir)

        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["machineName"], "H5P.PythonQuestion")
        self.assertEqual(updated[0]["asset"], "H5P.PythonQuestion-6.152_20261022.h5p")
        self.assertFalse((shared_libraries_dir / "H5P.PythonQuestion-6.73").exists())
        self.assertFalse((runtime_libraries_dir / "H5P.PythonQuestion-6.73").exists())
        self.assertFalse((shared_libraries_dir / "H5P.PythonQuestion-6.151").exists())
        self.assertTrue((shared_libraries_dir / "H5P.PythonQuestion-6.152" / "library.json").exists())
        self.assertTrue((runtime_libraries_dir / "H5P.PythonQuestion-6.152" / "library.json").exists())
        registry = json.loads((runtime_dir / "libraryRegistry.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["H5P.PythonQuestion"]["shortName"], "h5p-python-question")

    def test_update_custom_libraries_from_local_export_installs_dependency_only_libraries(self) -> None:
        from course_sync.classes import H5PLibraryManager

        runtime_dir = self.root / ".h5p-runtime"
        runtime_libraries_dir = runtime_dir / "libraries"
        shared_libraries_dir = self.root / "ressourcen" / "libraries"
        export_dir = self.root / "h5p-dev" / "export"
        export_dir.mkdir(parents=True)

        packages = {
            "H5P.SQLQuestion-6.95": {
                "machineName": "H5P.SQLQuestion",
                "majorVersion": 6,
                "minorVersion": 95,
                "title": "SQL Question",
                "preloadedDependencies": [
                    {"machineName": "H5P.LibMathTools", "majorVersion": 1, "minorVersion": 0},
                    {"machineName": "H5P.Question", "majorVersion": 1, "minorVersion": 5},
                ],
            },
            "H5P.LibMathTools-1.0": {
                "machineName": "H5P.LibMathTools",
                "majorVersion": 1,
                "minorVersion": 0,
                "title": "Math Tools",
            },
        }
        for dirname, library_json in packages.items():
            archive_payload = self._build_h5p_archive_bytes(
                {"title": dirname, "mainLibrary": library_json["machineName"]},
                {},
                libraries={dirname: library_json},
            )
            (export_dir / f"{dirname}_20261118.h5p").write_bytes(archive_payload)

        manager = H5PLibraryManager(
            workspace_lock=threading.RLock(),
            runtime_dir=runtime_dir,
            runtime_content_dir=runtime_dir / "content",
            runtime_libraries_dir=runtime_libraries_dir,
            runtime_downloads_dir=runtime_dir / "downloads",
            shared_libraries_dir=shared_libraries_dir,
            courses_dir=self.root / "kurse",
            release_repo="owner/repo",
            release_tag="old-tag",
            asset_prefixes={"H5P.SQLQuestion": "H5P.SQLQuestion-6.90_"},
            custom_short_names={"H5P.SQLQuestion": "h5p-sql-question"},
            ensure_directory=lambda path: path.mkdir(parents=True, exist_ok=True),
            read_json=lambda path: json.loads(path.read_text(encoding="utf-8")),
            read_json_or_default=lambda path, default: default if not path.exists() else json.loads(path.read_text(encoding="utf-8")),
            write_json=lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"),
            fetch_json=lambda url: {},
            download_file=lambda url, destination: None,
        )

        updated = manager.update_custom_libraries_from_local_export(export_dir)

        self.assertEqual({entry["machineName"] for entry in updated}, {"H5P.SQLQuestion", "H5P.LibMathTools"})
        self.assertTrue((runtime_libraries_dir / "H5P.LibMathTools-1.0" / "library.json").exists())
        self.assertTrue((shared_libraries_dir / "H5P.LibMathTools-1.0" / "library.json").exists())

    def test_update_custom_libraries_from_local_export_rejects_missing_export_dir(self) -> None:
        from course_sync.classes import H5PLibraryManager

        runtime_dir = self.root / ".h5p-runtime"
        manager = H5PLibraryManager(
            workspace_lock=threading.RLock(),
            runtime_dir=runtime_dir,
            runtime_content_dir=runtime_dir / "content",
            runtime_libraries_dir=runtime_dir / "libraries",
            runtime_downloads_dir=runtime_dir / "downloads",
            shared_libraries_dir=self.root / "ressourcen" / "libraries",
            courses_dir=self.root / "kurse",
            release_repo="owner/repo",
            release_tag="old-tag",
            asset_prefixes={},
            custom_short_names={},
            ensure_directory=lambda path: path.mkdir(parents=True, exist_ok=True),
            read_json=lambda path: json.loads(path.read_text(encoding="utf-8")),
            read_json_or_default=lambda path, default: default if not path.exists() else json.loads(path.read_text(encoding="utf-8")),
            write_json=lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"),
            fetch_json=lambda url: {},
            download_file=lambda url, destination: None,
        )

        with self.assertRaisesRegex(RuntimeError, "Export-Ordner"):
            manager.update_custom_libraries_from_local_export(self.root / "fehlt")

    def test_ensure_h5p_editor_dependencies_seeds_github_archives(self) -> None:
        from course_sync.classes import H5PLibraryManager

        runtime_dir = self.root / ".h5p-runtime"
        runtime_libraries_dir = runtime_dir / "libraries"
        runtime_downloads_dir = runtime_dir / "downloads"
        shared_libraries_dir = self.root / "ressourcen" / "libraries"

        def archive_bytes(root: str, machine_name: str) -> bytes:
            payload = BytesIO()
            with ZipFile(payload, "w") as archive:
                archive.writestr(f"{root}/library.json", json.dumps({
                    "title": machine_name,
                    "machineName": machine_name,
                    "majorVersion": 1,
                    "minorVersion": 0,
                    "runnable": 0,
                }))
                archive.writestr(f"{root}/language/en.json", "{}")
            return payload.getvalue()

        downloads = {
            "https://github.com/h5p/h5p-editor-show-when/archive/refs/tags/1.0.9.zip": archive_bytes(
                "h5p-editor-show-when-1.0.9",
                "H5PEditor.ShowWhen",
            ),
            "https://github.com/otacke/h5p-editor-datetime/archive/refs/tags/1.0.10.zip": archive_bytes(
                "h5p-editor-datetime-1.0.10",
                "H5PEditor.DateTime",
            ),
        }
        downloaded_urls: list[str] = []

        manager = H5PLibraryManager(
            workspace_lock=threading.RLock(),
            runtime_dir=runtime_dir,
            runtime_content_dir=runtime_dir / "content",
            runtime_libraries_dir=runtime_libraries_dir,
            runtime_downloads_dir=runtime_downloads_dir,
            shared_libraries_dir=shared_libraries_dir,
            courses_dir=self.root / "kurse",
            release_repo="owner/repo",
            release_tag="tag",
            asset_prefixes={},
            custom_short_names={},
            ensure_directory=lambda path: path.mkdir(parents=True, exist_ok=True),
            read_json=lambda path: json.loads(path.read_text(encoding="utf-8")),
            read_json_or_default=lambda path, default: default if not path.exists() else json.loads(path.read_text(encoding="utf-8")),
            write_json=lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"),
            fetch_json=lambda url: {},
            download_file=lambda url, destination: downloaded_urls.append(url) or destination.write_bytes(downloads[url]),
        )

        manager.ensure_h5p_editor_dependencies()

        self.assertEqual(
            downloaded_urls,
            [
                "https://github.com/h5p/h5p-editor-show-when/archive/refs/tags/1.0.9.zip",
                "https://github.com/otacke/h5p-editor-datetime/archive/refs/tags/1.0.10.zip",
            ],
        )
        self.assertTrue((shared_libraries_dir / "H5PEditor.ShowWhen-1.0" / "language" / "en.json").exists())
        self.assertTrue((shared_libraries_dir / "H5PEditor.DateTime-1.0" / "language" / "en.json").exists())
        self.assertTrue((runtime_libraries_dir / "H5PEditor.ShowWhen-1.0" / "library.json").exists())
        self.assertTrue((runtime_libraries_dir / "H5PEditor.DateTime-1.0" / "library.json").exists())
        registry = json.loads((runtime_dir / "libraryRegistry.json").read_text(encoding="utf-8"))
        self.assertIn("H5PEditor.ShowWhen", registry)
        self.assertIn("H5PEditor.DateTime", registry)

    def test_moodle_api_client_list_course_h5p_activities_filters_and_maps_fields(self) -> None:
        class StubMoodleApiClient(MoodleApiClient):
            def call(self, function_name: str, **params: object) -> object:
                self.last_call = (function_name, params)
                return [
                    {
                        "name": "Kapitel 1",
                        "modules": [
                            {
                                "modname": "h5pactivity",
                                "id": 10,
                                "instance": 20,
                                "name": "Einfuehrung Farben",
                                "description": "<p>Intro</p>",
                                "url": "https://example.invalid/mod/h5pactivity/view.php?id=10",
                                "visible": 1,
                            },
                            {
                                "modname": "assign",
                                "id": 11,
                                "name": "Abgabe",
                            },
                        ],
                    }
                ]

        client = StubMoodleApiClient(
            "https://example.invalid",
            "token",
            make_stable_identifier=lambda title, used: make_stable_identifier(title, used),
            strip_html=lambda text: "Intro" if "Intro" in text else text,
            fetch_text=lambda url: "",
            extract_h5p_package_url_from_activity_html=lambda page_html: "",
            download_file=lambda url, destination: None,
            extract_h5p_package_from_course_backup=lambda base, activity, archive_path: False,
            build_imported_question_from_h5p_package=lambda course_slug, activity, metadata, content: None,
            write_source_package_sidecar=lambda question, archive_path: "",
        )

        activities = client.list_course_h5p_activities(5)

        self.assertEqual(client.last_call[0], "core_course_get_contents")
        self.assertEqual(client.last_call[1]["courseid"], 5)
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities[0].identifier, "einfuehrung-farben")
        self.assertEqual(activities[0].activity_id, 10)
        self.assertEqual(activities[0].instance_id, 20)
        self.assertEqual(activities[0].intro, "Intro")

    def test_moodle_api_client_places_subsection_activities_at_parent_module_position(self) -> None:
        class StubMoodleApiClient(MoodleApiClient):
            def call(self, function_name: str, **params: object) -> object:
                return [
                    {
                        "name": "Grundlagen",
                        "section": 1,
                        "modules": [
                            {"modname": "h5pactivity", "id": 10, "instance": 20, "name": "Vorher"},
                            {"modname": "subsection", "id": 11, "instance": 30, "name": "Erste Aufgaben"},
                            {"modname": "h5pactivity", "id": 12, "instance": 22, "name": "Nachher"},
                        ],
                    },
                    {
                        "name": "Erste Aufgaben",
                        "section": 8,
                        "component": "mod_subsection",
                        "itemid": 30,
                        "modules": [
                            {"modname": "h5pactivity", "id": 13, "instance": 23, "name": "Aufgabe 1"},
                            {"modname": "h5pactivity", "id": 14, "instance": 24, "name": "Aufgabe 2"},
                        ],
                    },
                ]

        client = StubMoodleApiClient(
            "https://example.invalid",
            "token",
            make_stable_identifier=lambda title, used: make_stable_identifier(title, used),
            strip_html=lambda text: text,
            fetch_text=lambda url: "",
            extract_h5p_package_url_from_activity_html=lambda page_html: "",
            download_file=lambda url, destination: None,
            extract_h5p_package_from_course_backup=lambda base, activity, archive_path: False,
            build_imported_question_from_h5p_package=lambda course_slug, activity, metadata, content: None,
            write_source_package_sidecar=lambda question, archive_path: "",
        )

        activities = client.list_course_h5p_activities(5)

        self.assertEqual([activity.title for activity in activities], ["Vorher", "Aufgabe 1", "Aufgabe 2", "Nachher"])
        self.assertEqual(activities[1].section_title, "Grundlagen")
        self.assertEqual(activities[1].subsection_title, "Erste Aufgaben")
        self.assertEqual(activities[1].module_index, 1)
        self.assertEqual(activities[1].submodule_index, 0)

    def test_moodle_api_client_get_site_info_rejects_non_object_payload(self) -> None:
        class StubMoodleApiClient(MoodleApiClient):
            def call(self, function_name: str, **params: object) -> object:
                return ["not-a-dict"]

        client = StubMoodleApiClient(
            "https://example.invalid",
            "token",
            make_stable_identifier=lambda title, used: make_stable_identifier(title, used),
            strip_html=lambda text: text,
            fetch_text=lambda url: "",
            extract_h5p_package_url_from_activity_html=lambda page_html: "",
            download_file=lambda url, destination: None,
            extract_h5p_package_from_course_backup=lambda base, activity, archive_path: False,
            build_imported_question_from_h5p_package=lambda course_slug, activity, metadata, content: None,
            write_source_package_sidecar=lambda question, archive_path: "",
        )

        with self.assertRaises(RuntimeError):
            client.get_site_info()

    @needs_h5p_libraries
    def test_import_moodle_course_creates_local_scaffold_and_metadata(self) -> None:
        class FakeMoodleClient:
            base_url = "https://example.invalid"

            def list_course_h5p_activities(self, course_id: int):
                self.last_course_id = course_id
                return [
                    type(
                        "RemoteActivity",
                        (),
                        {
                            "identifier": "test-quadrat",
                            "title": "Test Quadrat",
                            "activity_id": 134,
                            "instance_id": 55,
                            "section_title": "Grundlagen",
                            "intro": "Beschreibe ein Quadrat.",
                            "url": "https://example.invalid/mod/h5pactivity/view.php?id=134",
                            "visible": True,
                        },
                    )(),
                    type(
                        "RemoteActivity",
                        (),
                        {
                            "identifier": "test-dreieck",
                            "title": "Test Dreieck",
                            "activity_id": 135,
                            "instance_id": 56,
                            "section_title": "Grundlagen",
                            "intro": "Beschreibe ein Dreieck.",
                            "url": "https://example.invalid/mod/h5pactivity/view.php?id=135",
                            "visible": False,
                        },
                    )(),
                ]

            def download_activity_question(self, course_slug: str, activity: object):
                return None

        from course_sync import main as module

        original_courses_dir = module.COURSES_DIR
        try:
            module.COURSES_DIR = self.root / "kurse"
            target_course_dir = import_moodle_course("imported-course", 5, FakeMoodleClient())
        finally:
            module.COURSES_DIR = original_courses_dir

        mdx = (target_course_dir / "index.mdx").read_text(encoding="utf-8")
        chapter_mdx = (target_course_dir / "chapters" / "001-grundlagen.mdx").read_text(encoding="utf-8")
        metadata = load_sync_metadata(target_course_dir)

        self.assertIn('<Chapter src="./chapters/001-grundlagen.mdx" title="Grundlagen" />', mdx)
        self.assertIn('identifier="test-quadrat"', chapter_mdx)
        self.assertIn('title="Test Quadrat"', chapter_mdx)
        self.assertNotIn("previewUrl", chapter_mdx)
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.remote_course_id, 5)
        self.assertEqual(metadata.entries["test-quadrat"].remote_activity_id, 134)
        self.assertFalse(metadata.entries["test-dreieck"].remote_visible)

    @needs_h5p_libraries
    def test_import_moodle_course_preserves_remote_section_and_activity_order(self) -> None:
        class FakeMoodleClient:
            base_url = "https://example.invalid"

            def list_course_h5p_activities(self, course_id: int):
                self.last_course_id = course_id
                return [
                    type(
                        "RemoteActivity",
                        (),
                        {
                            "identifier": "s2-b",
                            "title": "S2-B",
                            "activity_id": 203,
                            "instance_id": 63,
                            "section_title": "Sektion 2",
                            "section_index": 2,
                            "module_index": 1,
                            "intro": "Zweite Sektion, zweites H5P.",
                            "url": "https://example.invalid/mod/h5pactivity/view.php?id=203",
                            "visible": True,
                        },
                    )(),
                    type(
                        "RemoteActivity",
                        (),
                        {
                            "identifier": "s1-a",
                            "title": "S1-A",
                            "activity_id": 101,
                            "instance_id": 61,
                            "section_title": "Sektion 1",
                            "section_index": 1,
                            "module_index": 0,
                            "intro": "Erste Sektion, erstes H5P.",
                            "url": "https://example.invalid/mod/h5pactivity/view.php?id=101",
                            "visible": True,
                        },
                    )(),
                    type(
                        "RemoteActivity",
                        (),
                        {
                            "identifier": "s2-a",
                            "title": "S2-A",
                            "activity_id": 202,
                            "instance_id": 62,
                            "section_title": "Sektion 2",
                            "section_index": 2,
                            "module_index": 0,
                            "intro": "Zweite Sektion, erstes H5P.",
                            "url": "https://example.invalid/mod/h5pactivity/view.php?id=202",
                            "visible": True,
                        },
                    )(),
                ]

            def download_activity_question(self, course_slug: str, activity: object):
                return None

        from course_sync import main as module

        original_courses_dir = module.COURSES_DIR
        try:
            module.COURSES_DIR = self.root / "kurse"
            target_course_dir = import_moodle_course("imported-order", 5, FakeMoodleClient())
        finally:
            module.COURSES_DIR = original_courses_dir

        index_mdx = (target_course_dir / "index.mdx").read_text(encoding="utf-8")
        first_chapter_mdx = (target_course_dir / "chapters" / "001-sektion-1.mdx").read_text(encoding="utf-8")
        second_chapter_mdx = (target_course_dir / "chapters" / "002-sektion-2.mdx").read_text(encoding="utf-8")

        self.assertLess(index_mdx.index("001-sektion-1"), index_mdx.index("002-sektion-2"))
        self.assertIn('identifier="s1-a"', first_chapter_mdx)
        self.assertLess(second_chapter_mdx.index('identifier="s2-a"'), second_chapter_mdx.index('identifier="s2-b"'))

    @needs_h5p_libraries
    def test_import_moodle_course_renders_subsection_headings_in_remote_position(self) -> None:
        class FakeMoodleClient:
            base_url = "https://example.invalid"

            def list_course_h5p_activities(self, course_id: int):
                return [
                    MoodleH5PActivity(
                        identifier="after",
                        title="Nachher",
                        course_id=course_id,
                        activity_id=12,
                        instance_id=22,
                        section_title="Grundlagen",
                        section_index=1,
                        module_index=2,
                        intro="",
                        url="https://example.invalid/mod/h5pactivity/view.php?id=12",
                    ),
                    MoodleH5PActivity(
                        identifier="task-one",
                        title="Aufgabe 1",
                        course_id=course_id,
                        activity_id=13,
                        instance_id=23,
                        section_title="Grundlagen",
                        subsection_title="Erste Aufgaben",
                        section_index=1,
                        module_index=1,
                        subsection_index=8,
                        submodule_index=0,
                        intro="",
                        url="https://example.invalid/mod/h5pactivity/view.php?id=13",
                    ),
                    MoodleH5PActivity(
                        identifier="before",
                        title="Vorher",
                        course_id=course_id,
                        activity_id=10,
                        instance_id=20,
                        section_title="Grundlagen",
                        section_index=1,
                        module_index=0,
                        intro="",
                        url="https://example.invalid/mod/h5pactivity/view.php?id=10",
                    ),
                ]

            def download_activity_question(self, course_slug: str, activity: object):
                return None

        from course_sync import main as module

        original_courses_dir = module.COURSES_DIR
        try:
            module.COURSES_DIR = self.root / "kurse"
            target_course_dir = import_moodle_course("imported-subsection-order", 5, FakeMoodleClient())
        finally:
            module.COURSES_DIR = original_courses_dir

        mdx = (target_course_dir / "chapters" / "001-grundlagen.mdx").read_text(encoding="utf-8")

        self.assertLess(mdx.index('identifier="before"'), mdx.index("### Erste Aufgaben"))
        self.assertLess(mdx.index("### Erste Aufgaben"), mdx.index('identifier="task-one"'))
        self.assertLess(mdx.index('identifier="task-one"'), mdx.index('identifier="after"'))

    def test_download_activity_question_persists_source_archive_for_public_packages(self) -> None:
        package_path = self.root / "public-package.h5p"
        package_path.write_bytes(
            self._build_h5p_archive_bytes(
                {"title": "Einführung: Farben", "mainLibrary": "H5P.PythonQuestion"},
                {
                    "contentType": "text_only",
                    "pythonRunner": "skulpt",
                    "contents": [{"type": "text", "text": "Aus Paket"}],
                    "editorSettings": {"instructions": "Aus Paket", "options": {}},
                    "gradingSettings": {},
                },
            )
        )

        from course_sync import main as module

        original_fetch_text = module.fetch_text
        original_download_file = module.download_file
        original_courses_dir = module.COURSES_DIR
        try:
            module.COURSES_DIR = self.root / "kurse"

            def fake_fetch_text(url: str) -> str:
                self.assertIn("view.php?id=145", url)
                return '<iframe src="https://example.invalid/h5p/embed.php?url=https%3A%2F%2Fexample.invalid%2Ffiles%2Feinfuhrung-farben.h5p"></iframe>'

            def fake_download_file(url: str, destination: Path) -> None:
                self.assertEqual(url, "https://example.invalid/files/einfuhrung-farben.h5p")
                destination.write_bytes(package_path.read_bytes())

            module.fetch_text = fake_fetch_text
            module.download_file = fake_download_file
            backup_extractor = module.moodle_backup_extractor()
            client = MoodleApiClient(
                "https://example.invalid",
                "token",
                make_stable_identifier=module.make_stable_identifier,
                strip_html=module.strip_html,
                fetch_text=module.fetch_text,
                extract_h5p_package_url_from_activity_html=lambda page_html: module.extract_h5p_package_url_from_activity_html(
                    page_html,
                    base_url="https://example.invalid",
                ),
                download_file=module.download_file,
                extract_h5p_package_from_course_backup=backup_extractor.extract_h5p_package_from_course_backup,
                build_imported_question_from_h5p_package=module.build_imported_question_from_h5p_package,
                write_source_package_sidecar=module.write_source_package_sidecar,
            )
            question = client.download_activity_question(
                "python-2026",
                MoodleH5PActivity(
                    identifier="einfuehrung-farben",
                    title="Einführung: Farben",
                    course_id=5,
                    activity_id=145,
                    instance_id=105,
                    section_title="Farben",
                    intro="",
                    url="https://example.invalid/mod/h5pactivity/view.php?id=145",
                ),
            )
        finally:
            module.fetch_text = original_fetch_text
            module.download_file = original_download_file
            module.COURSES_DIR = original_courses_dir

        assert question is not None
        self.assertEqual(question.source_package_path, "h5p/einfuehrung-farben")
        self.assertTrue((self.root / "kurse" / "python-2026" / question.source_package_path).exists())

    def test_build_course_status_reports_modified_and_remote_only(self) -> None:
        metadata = SyncMetadata(
            course_slug="python-2026",
            remote_course_id=5,
            moodle_base_url="https://example.invalid",
        )
        _, questions, _ = parse_course(self.course_dir)
        metadata.entries["12eck"] = SyncMetadataEntry(
            identifier="12eck",
            remote_activity_id=134,
            remote_instance_id=77,
            remote_title="Zwölfeck zeichnen",
            remote_url="https://example.invalid/mod/h5pactivity/view.php?id=134",
            remote_visible=True,
            local_hash="stale",
        )
        metadata.entries["online-only"] = SyncMetadataEntry(
            identifier="online-only",
            remote_activity_id=999,
            remote_instance_id=88,
            remote_title="Nur Online",
            remote_url="https://example.invalid/mod/h5pactivity/view.php?id=999",
            remote_visible=True,
            local_hash="",
        )
        save_sync_metadata(self.course_dir, metadata)

        status = build_course_status(self.course_dir)

        self.assertEqual(status["counts"]["modified-local"], 1)
        self.assertEqual(status["counts"]["local-only"], 1)
        self.assertEqual(status["counts"]["remote-only"], 1)
        self.assertIn(
            {"identifier": "12eck", "title": "Zwölfeck zeichnen", "status": "modified-local", "remoteActivityId": 134},
            status["items"],
        )

    def test_store_uploaded_activity_ids_refreshes_metadata_hash_and_title(self) -> None:
        from course_sync import main as module
        from course_sync.classes.moodle_playwright_uploader import MoodleH5PUploadResult

        metadata = SyncMetadata(
            course_slug="python-2026",
            remote_course_id=5,
            moodle_base_url="https://example.invalid",
        )
        metadata.entries["12eck"] = SyncMetadataEntry(
            identifier="12eck",
            remote_activity_id=134,
            remote_instance_id=77,
            remote_title="Alter Titel",
            remote_url="",
            remote_visible=False,
            local_hash="stale",
            remote_hash="stale",
            status="modified-local",
        )
        save_sync_metadata(self.course_dir, metadata)

        module._store_uploaded_activity_ids(
            self.course_dir,
            [MoodleH5PUploadResult("12eck", "Zwölfeck zeichnen", "updated", 134)],
        )

        reloaded = load_sync_metadata(self.course_dir)
        assert reloaded is not None
        entry = reloaded.entries["12eck"]
        _, questions, _ = parse_course(self.course_dir)
        question = next(question for question in questions if question.identifier == "12eck")
        expected_hash = compute_question_hash(question)
        self.assertEqual(entry.remote_title, "Zwölfeck zeichnen")
        self.assertEqual(entry.remote_url, "https://example.invalid/mod/h5pactivity/view.php?id=134")
        self.assertEqual(entry.local_hash, expected_hash)
        self.assertEqual(entry.remote_hash, expected_hash)
        self.assertEqual(entry.status, "tracked")
        self.assertTrue(entry.remote_visible)

    def test_sync_course_writes_h5p_files(self) -> None:
        from course_sync import main as module

        original_courses_dir = module.COURSES_DIR
        original_runtime_libraries_dir = module.H5P_RUNTIME_LIBRARIES_DIR
        original_ensure_runtime = module.ensure_h5p_runtime_libraries
        try:
            module.COURSES_DIR = self.root / "kurse"
            module.H5P_RUNTIME_LIBRARIES_DIR = self.root / ".h5p-runtime" / "libraries"
            module.ensure_h5p_runtime_libraries = lambda: None
            self._create_fake_library(module.H5P_RUNTIME_LIBRARIES_DIR, "H5P.Question", 1, 5, [])
            self._create_fake_library(
                module.H5P_RUNTIME_LIBRARIES_DIR,
                "H5P.LibCodeTools",
                6,
                73,
                [],
            )
            self._create_fake_library(
                module.H5P_RUNTIME_LIBRARIES_DIR,
                "H5P.CodeQuestion",
                6,
                73,
                [("H5P.Question", 1, 5), ("H5P.LibCodeTools", 6, 73)],
            )
            self._create_fake_library(
                module.H5P_RUNTIME_LIBRARIES_DIR,
                "H5P.PythonQuestion",
                6,
                73,
                [("H5P.CodeQuestion", 6, 73), ("H5P.LibCodeTools", 6, 73)],
            )
            course_build_dir = module.course_build_dir(self.course_dir)
            stale_hash = course_build_dir / "hashes" / "old-section" / "old-question.build-hash"
            stale_hash.parent.mkdir(parents=True)
            stale_hash.write_text("stale", encoding="utf-8")
            questions = sync_course(self.course_dir)
        finally:
            module.COURSES_DIR = original_courses_dir
            module.H5P_RUNTIME_LIBRARIES_DIR = original_runtime_libraries_dir
            module.ensure_h5p_runtime_libraries = original_ensure_runtime

        self.assertEqual([question.identifier for question in questions], ["12eck", "quadrat"])
        archive = course_build_dir / "h5p" / "12eck.h5p"
        content_mdx = course_build_dir / "content" / "12eck" / "content.mdx"
        build_hash = course_build_dir / "hashes" / "12eck.build-hash"
        second_archive = course_build_dir / "h5p" / "quadrat.h5p"
        self.assertTrue(archive.exists())
        self.assertTrue(content_mdx.exists())
        self.assertTrue(build_hash.exists())
        self.assertFalse(stale_hash.exists())
        self.assertFalse((self.course_dir / "h5p" / "12eck.h5p").exists())
        self.assertFalse((self.course_dir / "h5p" / ".12eck.build-hash").exists())
        self.assertFalse((self.course_dir / "h5p" / "orphaned-old-package.h5p").exists())
        self.assertFalse((self.course_dir / "h5p" / ".orphaned-old-package.build-hash").exists())
        self.assertFalse((self.course_dir / "h5p" / "12eck" / "12eck.h5p").exists())
        self.assertFalse((self.course_dir / "h5p" / "12eck" / ".build-hash").exists())
        self.assertFalse((self.course_dir / "h5p" / "12eck" / "content.json").exists())
        self.assertTrue(second_archive.exists())
        # Shared libraries are embedded straight from the runtime libraries dir now -- no
        # intermediate "ressourcen/libraries" cache is created next to the course tree anymore.
        for built_archive in (archive, second_archive):
            with ZipFile(built_archive) as package:
                names = package.namelist()
            self.assertIn("H5P.PythonQuestion-6.73/library.json", names)
            self.assertIn("H5P.CodeQuestion-6.73/library.json", names)
            self.assertIn("H5P.LibCodeTools-6.73/library.json", names)
            self.assertIn("H5P.Question-1.5/library.json", names)
        self.assertFalse((self.root / "ressourcen" / "libraries").exists())
        self.assertFalse((self.course_dir / "h5p" / "libraries").exists())
        self.assertFalse((self.course_dir / "h5p" / "12eck" / "H5P.PythonQuestion-6.73").exists())

        settings_yaml = course_build_dir / "content" / "12eck" / "settings.yml"
        payload = yaml.safe_load(settings_yaml.read_text(encoding="utf-8"))
        self.assertEqual(payload["pythonRunner"], "pyodide")

        metadata = json.loads((course_build_dir / "content" / "12eck" / "h5p.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["preloadedDependencies"][0]["machineName"], "H5P.PythonQuestion")

        with ZipFile(archive) as package:
            package_names = set(package.namelist())
        self.assertNotIn("12eck.h5p", package_names)
        self.assertIn("H5P.PythonQuestion-6.73/library.json", package_names)
        self.assertIn("H5P.CodeQuestion-6.73/library.json", package_names)
        self.assertIn("H5P.LibCodeTools-6.73/library.json", package_names)
        self.assertIn("H5P.Question-1.5/library.json", package_names)

    def test_sync_course_package_skips_hidden_library_files_and_duplicate_entries(self) -> None:
        from course_sync import main as module

        original_courses_dir = module.COURSES_DIR
        original_runtime_libraries_dir = module.H5P_RUNTIME_LIBRARIES_DIR
        original_ensure_runtime = module.ensure_h5p_runtime_libraries
        try:
            module.COURSES_DIR = self.root / "kurse"
            module.H5P_RUNTIME_LIBRARIES_DIR = self.root / ".h5p-runtime" / "libraries"
            module.ensure_h5p_runtime_libraries = lambda: None
            self._create_fake_library(module.H5P_RUNTIME_LIBRARIES_DIR, "H5P.Question", 1, 5, [])
            self._create_fake_library(module.H5P_RUNTIME_LIBRARIES_DIR, "H5P.LibCodeTools", 6, 73, [])
            self._create_fake_library(
                module.H5P_RUNTIME_LIBRARIES_DIR,
                "H5P.CodeQuestion",
                6,
                73,
                [("H5P.Question", 1, 5), ("H5P.LibCodeTools", 6, 73)],
            )
            self._create_fake_library(
                module.H5P_RUNTIME_LIBRARIES_DIR,
                "H5P.PythonQuestion",
                6,
                73,
                [("H5P.CodeQuestion", 6, 73), ("H5P.LibCodeTools", 6, 73)],
            )

            python_library_dir = self.root / "ressourcen" / "libraries" / "H5P.PythonQuestion-6.73"
            (python_library_dir / ".git").mkdir(parents=True)
            (python_library_dir / ".git" / "config").write_text("ignored", encoding="utf-8")
            (python_library_dir / ".gitignore").write_text("ignored", encoding="utf-8")

            sync_course(self.course_dir)
        finally:
            module.COURSES_DIR = original_courses_dir
            module.H5P_RUNTIME_LIBRARIES_DIR = original_runtime_libraries_dir
            module.ensure_h5p_runtime_libraries = original_ensure_runtime

        archive = module.course_build_dir(self.course_dir) / "h5p" / "12eck.h5p"
        with ZipFile(archive) as package:
            package_names = package.namelist()

        self.assertEqual(len(package_names), len(set(package_names)))
        self.assertNotIn("H5P.PythonQuestion-6.73/.git/config", package_names)
        self.assertNotIn("H5P.PythonQuestion-6.73/.gitignore", package_names)

    def test_ensure_custom_h5p_libraries_skips_release_lookup_when_libraries_exist(self) -> None:
        from course_sync import main as module

        original_libraries_dir = module.H5P_RUNTIME_LIBRARIES_DIR
        original_downloads_dir = module.H5P_RUNTIME_DOWNLOADS_DIR
        original_fetch_json = module.fetch_json
        try:
            module.H5P_RUNTIME_LIBRARIES_DIR = self.root / ".h5p-runtime" / "libraries"
            module.H5P_RUNTIME_DOWNLOADS_DIR = self.root / ".h5p-runtime" / "downloads"
            for machine_name in module.H5P_LIBRARY_ASSET_PREFIXES:
                self._create_fake_library(module.H5P_RUNTIME_LIBRARIES_DIR, machine_name, 6, 73, [])
            for asset in module.H5P_LIBRARY_EXTRA_ASSETS:
                self._create_fake_library(module.H5P_RUNTIME_LIBRARIES_DIR, asset["machineName"], 6, 73, [])

            def fail_fetch(url: str) -> dict:
                raise AssertionError(f"fetch_json should not be called: {url}")

            module.fetch_json = fail_fetch
            module.h5p_library_manager().ensure_custom_h5p_libraries()
        finally:
            module.H5P_RUNTIME_LIBRARIES_DIR = original_libraries_dir
            module.H5P_RUNTIME_DOWNLOADS_DIR = original_downloads_dir
            module.fetch_json = original_fetch_json

    def test_ensure_custom_h5p_libraries_uses_cached_release_metadata(self) -> None:
        from course_sync import main as module
        from course_sync.classes import H5PLibraryManager

        original_libraries_dir = module.H5P_RUNTIME_LIBRARIES_DIR
        original_downloads_dir = module.H5P_RUNTIME_DOWNLOADS_DIR
        original_fetch_json = module.fetch_json
        original_download_file = module.download_file
        original_extract_library_asset = H5PLibraryManager.extract_library_asset
        original_register_local_library = H5PLibraryManager.register_local_library
        try:
            module.H5P_RUNTIME_LIBRARIES_DIR = self.root / ".h5p-runtime" / "libraries"
            module.H5P_RUNTIME_DOWNLOADS_DIR = self.root / ".h5p-runtime" / "downloads"
            module.H5P_RUNTIME_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

            manager = module.h5p_library_manager()
            default_assets = [
                {
                    "name": f"{asset_prefix}cached.h5p",
                    "browser_download_url": f"https://example.invalid/{machine_name}.h5p",
                }
                for machine_name, asset_prefix in module.H5P_LIBRARY_ASSET_PREFIXES.items()
            ]
            manager.release_metadata_cache_path().write_text(json.dumps({"assets": default_assets}), encoding="utf-8")

            extra_assets_by_release: dict[tuple[str, str], list[dict[str, str]]] = {}
            for asset in module.H5P_LIBRARY_EXTRA_ASSETS:
                key = (asset["releaseRepo"], asset["releaseTag"])
                extra_assets_by_release.setdefault(key, []).append(
                    {
                        "name": f"{asset['assetPrefix']}cached.h5p",
                        "browser_download_url": f"https://example.invalid/{asset['machineName']}.h5p",
                    }
                )
            for (release_repo, release_tag), assets in extra_assets_by_release.items():
                manager._release_metadata_cache_path_for(release_repo, release_tag).write_text(
                    json.dumps({"assets": assets}),
                    encoding="utf-8",
                )

            downloaded: list[tuple[str, Path]] = []
            extracted: list[tuple[Path, str]] = []
            registered: list[Path] = []

            def fail_fetch(url: str) -> dict:
                raise AssertionError(f"fetch_json should not be called: {url}")

            def fake_download(url: str, destination: Path) -> None:
                downloaded.append((url, destination))
                destination.write_bytes(b"fake")

            def fake_extract(self: H5PLibraryManager, archive_path: Path, machine_name: str) -> Path:
                extracted.append((archive_path, machine_name))
                library_dir = module.H5P_RUNTIME_LIBRARIES_DIR / f"{machine_name}-6.73"
                library_dir.mkdir(parents=True, exist_ok=True)
                (library_dir / "library.json").write_text(
                    json.dumps({"machineName": machine_name, "majorVersion": 6, "minorVersion": 73}),
                    encoding="utf-8",
                )
                return library_dir

            def fake_register(self: H5PLibraryManager, library_dir: Path) -> None:
                registered.append(library_dir)

            module.fetch_json = fail_fetch
            module.download_file = fake_download
            H5PLibraryManager.extract_library_asset = fake_extract
            H5PLibraryManager.register_local_library = fake_register

            module.h5p_library_manager().ensure_custom_h5p_libraries()
        finally:
            module.H5P_RUNTIME_LIBRARIES_DIR = original_libraries_dir
            module.H5P_RUNTIME_DOWNLOADS_DIR = original_downloads_dir
            module.fetch_json = original_fetch_json
            module.download_file = original_download_file
            H5PLibraryManager.extract_library_asset = original_extract_library_asset
            H5PLibraryManager.register_local_library = original_register_local_library

        expected_downloads = len(module.H5P_LIBRARY_ASSET_PREFIXES) + len(module.H5P_LIBRARY_EXTRA_ASSETS)
        self.assertEqual(len(downloaded), expected_downloads)
        self.assertEqual(downloaded[0][0], "https://example.invalid/H5P.PythonQuestion.h5p")
        self.assertEqual(extracted[0][1], "H5P.PythonQuestion")
        self.assertEqual(len(registered), expected_downloads)

    def _create_fake_library(
        self,
        libraries_dir: Path,
        machine_name: str,
        major_version: int,
        minor_version: int,
        dependencies: list[tuple[str, int, int]],
    ) -> None:
        library_dir = libraries_dir / f"{machine_name}-{major_version}.{minor_version}"
        library_dir.mkdir(parents=True, exist_ok=True)
        (library_dir / "library.json").write_text(
            json.dumps(
                {
                    "machineName": machine_name,
                    "majorVersion": major_version,
                    "minorVersion": minor_version,
                    "preloadedDependencies": [
                        {
                            "machineName": dependency_name,
                            "majorVersion": dependency_major,
                            "minorVersion": dependency_minor,
                        }
                        for dependency_name, dependency_major, dependency_minor in dependencies
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _build_h5p_archive_bytes(
        self,
        metadata: dict[str, object],
        content: dict[str, object],
        extra_files: dict[str, bytes | str] | None = None,
        libraries: dict[str, dict[str, object]] | None = None,
    ) -> bytes:
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("h5p.json", json.dumps(metadata))
            archive.writestr("content/content.json", json.dumps(content))
            for library_root, library_metadata in (libraries or {}).items():
                archive.writestr(f"{library_root}/library.json", json.dumps(library_metadata))
                archive.writestr(f"{library_root}/scripts/example.js", "console.log('ok');")
            for path, payload in (extra_files or {}).items():
                archive.writestr(path, payload)
        return buffer.getvalue()

    def _add_tar_text(self, archive: tarfile.TarFile, name: str, content: str) -> None:
        self._add_tar_bytes(archive, name, content.encode("utf-8"))

    def _add_tar_bytes(self, archive: tarfile.TarFile, name: str, content: bytes) -> None:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        archive.addfile(info, BytesIO(content))


if __name__ == "__main__":
    unittest.main()
