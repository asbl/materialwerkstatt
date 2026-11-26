import tempfile
import unittest
from pathlib import Path

from course_sync.main import audit_course
from requirements import needs_h5p_libraries


class AuditMultipleChoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        from course_sync import main as module

        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self._original_course_build_dir = module.COURSE_BUILD_DIR
        module.COURSE_BUILD_DIR = self.root / "build" / "kurse"
        self.course_dir = self.root / "courses" / "audit-course"
        (self.course_dir / "chapters" / "001-start" / "quiz").mkdir(parents=True)
        (self.course_dir / "assets").mkdir()
        (self.course_dir / "course.yml").write_text(
            "h5pDefaults:\n  mainLibrary: H5P.PythonQuestion\n",
            encoding="utf-8",
        )
        (self.course_dir / "index.mdx").write_text(
            '# Audit Kurs\n\n<Chapter src="./chapters/001-start.mdx" title="Start" />\n',
            encoding="utf-8",
        )
        (self.course_dir / "chapters" / "001-start.mdx").write_text(
            '<PythonQuestion identifier="quiz" title="Quiz" />\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        from course_sync import main as module

        module.COURSE_BUILD_DIR = self._original_course_build_dir
        self.tmp_dir.cleanup()

    def _write_quiz(self, grading_yaml: str) -> None:
        (self.course_dir / "chapters" / "001-start" / "quiz" / "content.mdx").write_text(
            f"""---
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
{grading_yaml}
```
""",
            encoding="utf-8",
        )

    @needs_h5p_libraries
    def test_audit_flags_multiple_choice_without_correct_answer(self) -> None:
        self._write_quiz(
            "gradingMethod: multipleChoice\n"
            "multipleChoice:\n"
            "  allowMultiple: false\n"
            "  choices:\n"
            "    - text: Aussage eins\n"
            "      correct: false\n"
            "    - text: Aussage zwei\n"
            "      correct: false\n"
        )

        report = audit_course(self.course_dir)

        messages = [issue["message"] for issue in report["issues"]]
        self.assertIn("Multiple-Choice-Aufgabe hat keine richtige Antwortoption.", messages)
        self.assertGreaterEqual(report["errors"], 1)

    @needs_h5p_libraries
    def test_audit_flags_multiple_choice_with_conflicting_single_answer_setting(self) -> None:
        self._write_quiz(
            "gradingMethod: multipleChoice\n"
            "multipleChoice:\n"
            "  allowMultiple: false\n"
            "  choices:\n"
            "    - text: Aussage eins\n"
            "      correct: true\n"
            "    - text: Aussage zwei\n"
            "      correct: true\n"
        )

        report = audit_course(self.course_dir)

        messages = [issue["message"] for issue in report["issues"]]
        self.assertIn(
            "Multiple-Choice-Aufgabe erlaubt nur eine Antwort, hat aber mehrere korrekte Optionen.",
            messages,
        )

    @needs_h5p_libraries
    def test_audit_flags_multiple_choice_with_empty_answer_text(self) -> None:
        self._write_quiz(
            "gradingMethod: multipleChoice\n"
            "multipleChoice:\n"
            "  allowMultiple: true\n"
            "  choices:\n"
            "    - text: ''\n"
            "      correct: true\n"
            "    - text: Aussage zwei\n"
            "      correct: false\n"
        )

        report = audit_course(self.course_dir)

        messages = [issue["message"] for issue in report["issues"]]
        self.assertIn("Multiple-Choice-Aufgabe enthält eine Antwortoption ohne Text.", messages)

    @needs_h5p_libraries
    def test_audit_accepts_valid_multiple_choice_question(self) -> None:
        self._write_quiz(
            "gradingMethod: multipleChoice\n"
            "multipleChoice:\n"
            "  allowMultiple: true\n"
            "  choices:\n"
            "    - text: Aussage eins\n"
            "      correct: true\n"
            "    - text: Aussage zwei\n"
            "      correct: false\n"
        )

        report = audit_course(self.course_dir)

        self.assertEqual(report["errors"], 0)
        self.assertEqual(report["warnings"], 0)


if __name__ == "__main__":
    unittest.main()
