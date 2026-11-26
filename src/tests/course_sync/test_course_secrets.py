"""Kurs-Secrets (course.yml) und deren Ersetzung auf Sync-Zielen ohne keep_secrets."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from course_sync.application import CourseApplication
from course_sync.classes.course_secrets import (
    apply_secret_replacements,
    load_course_secrets,
    resolve_secret_replacements,
    sanitize_h5p_package,
    target_keeps_secrets,
)
from course_sync.config import settings


def write_course(course_dir: Path, *, secrets_yaml: str = "", index: str | None = None) -> None:
    course_dir.mkdir(parents=True, exist_ok=True)
    if secrets_yaml:
        (course_dir / "course.yml").write_text(secrets_yaml, encoding="utf-8")
    (course_dir / "index.mdx").write_text(
        index if index is not None else '# Demo\n\n<Chapter src="./chapters/001-a/content.mdx" title="A" />\n',
        encoding="utf-8",
    )
    chapter = course_dir / "chapters" / "001-a" / "q1"
    chapter.mkdir(parents=True, exist_ok=True)
    (chapter / "content.mdx").write_text("### Frage\n", encoding="utf-8")


def write_package(path: Path, *, title: str, instructions: str, extra_binary: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("h5p.json", json.dumps({"title": title, "mainLibrary": "H5P.PythonQuestion"}))
        archive.writestr(
            "content/content.json",
            json.dumps({"editorSettings": {"instructions": instructions}, "gradingSettings": {"gradingMethod": "points"}}),
        )
        if extra_binary:
            archive.writestr("content/image.png", b"\x89PNG\r\n\x1a\n" + bytes(range(64)))


@pytest.fixture()
def application(tmp_path):
    return CourseApplication(settings.build_app_config().with_root(tmp_path))


@pytest.fixture()
def course(tmp_path):
    course_dir = tmp_path / "unterricht" / "kurse" / "demo"
    write_course(
        course_dir,
        secrets_yaml='secrets:\n  "Anna": "Person A"\n  "Fenn": "Person B"\n  "leerer": ""\n  "Anna2": "Anna2"\n',
    )
    return course_dir


def test_load_course_secrets_ignores_invalid_entries(course):
    assert load_course_secrets(course) == {"Anna": "Person A", "Fenn": "Person B"}
    assert load_course_secrets(course.parent / "unbekannt") == {}


def test_load_course_secrets_drops_colliding_replacements(tmp_path):
    course_dir = tmp_path / "kurs"
    write_course(
        course_dir,
        secrets_yaml=(
            'secrets:\n  "Anna": "Lea"\n  "Ben": "Anna"\n  "Fenn": "Lea"\n  "Noah": "Noah"\n  "leer": ""\n'
        ),
    )
    # "Ben" -> "Anna" kollidiert mit einem Secret, "Fenn" -> "Lea" ist doppelt.
    assert load_course_secrets(course_dir) == {"Anna": "Lea"}


def test_target_keeps_secrets_flag():
    assert target_keeps_secrets({"keep_secrets": True}) is True
    assert target_keeps_secrets({"keep_secrets": "true"}) is True
    assert target_keeps_secrets({"keepSecrets": True}) is True
    assert target_keeps_secrets({"keep_secrets": False}) is False
    assert target_keeps_secrets({}) is False
    assert target_keeps_secrets(None) is False


def test_resolve_secret_replacements_only_when_target_does_not_keep(course):
    assert resolve_secret_replacements(course, {"keep_secrets": True}) == {}
    assert resolve_secret_replacements(course, None) == {"Anna": "Person A", "Fenn": "Person B"}
    assert resolve_secret_replacements(course, {"auth": "credentials"}) == {"Anna": "Person A", "Fenn": "Person B"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Anna macht Fenns Taktik.", "Person A macht Person Bs Taktik."),
        ("Anna' Buch und Annabell und anna bleiben.", "Person A' Buch und Annabell und anna bleiben."),
        ("Fenns, Fenn, fenn", "Person Bs, Person B, fenn"),
        ("Tim ist kein Secret, Timer auch nicht.", "Tim ist kein Secret, Timer auch nicht."),
        ("", ""),
    ],
)
def test_apply_secret_replacements_word_boundaries(text, expected):
    assert apply_secret_replacements(text, {"Anna": "Person A", "Fenn": "Person B"}) == expected


def test_apply_secret_replacements_prefers_longest_secret():
    replacements = {"Anna": "Person A", "Annabell": "Person Z"}
    assert apply_secret_replacements("Annabell und Anna", replacements) == "Person Z und Person A"


def test_sanitize_h5p_package_rewrites_text_and_keeps_binary(tmp_path):
    source = tmp_path / "q1.h5p"
    write_package(source, title="Anna-Aufgabe", instructions="Anna tippt Fenns Code.")
    dest = tmp_path / "sanitized" / "q1.h5p"

    sanitize_h5p_package(source, {"Anna": "Person A", "Fenn": "Person B"}, dest)

    with zipfile.ZipFile(dest) as archive:
        assert json.loads(archive.read("h5p.json"))["title"] == "Person A-Aufgabe"
        content = json.loads(archive.read("content/content.json"))
        assert content["editorSettings"]["instructions"] == "Person A tippt Person Bs Code."
        assert archive.read("content/image.png") == b"\x89PNG\r\n\x1a\n" + bytes(range(64))

    # Erneuter Lauf mit unveraenderter Quelle und gleichem Mapping schreibt nicht neu.
    before = dest.stat().st_mtime_ns
    sanitize_h5p_package(source, {"Anna": "Person A", "Fenn": "Person B"}, dest)
    assert dest.stat().st_mtime_ns == before

    # Geaendertes Mapping wird neu sanitized (Cache-Hash enthaelt die Ersetzungen).
    sanitize_h5p_package(source, {"Anna": "Lea", "Fenn": "Person B"}, dest)
    with zipfile.ZipFile(dest) as archive:
        content = json.loads(archive.read("content/content.json"))
        assert content["editorSettings"]["instructions"] == "Lea tippt Person Bs Code."

    # Geaenderte Quelle wird neu sanitized.
    write_package(source, title="Fenn-Aufgabe", instructions="Anna")
    sanitize_h5p_package(source, {"Anna": "Person A", "Fenn": "Person B"}, dest)
    with zipfile.ZipFile(dest) as archive:
        assert json.loads(archive.read("h5p.json"))["title"] == "Person B-Aufgabe"


def test_sanitize_h5p_package_replaces_names_after_json_escaped_newlines(tmp_path):
    # Im rohen JSON steht vor „Anna“ das Escape-„n“ von \n – die Ersetzung muss
    # JSON-aware sein, sonst bleibt der Name an Zeilenanfaengen stehen.
    source = tmp_path / "q1.h5p"
    write_package(source, title="Aufgabe", instructions="Team\n\nAnna und Fenn\n\nJonas' Liste")
    dest = tmp_path / "sanitized" / "q1.h5p"

    sanitize_h5p_package(source, {"Anna": "Lea", "Fenn": "Falk", "Jonas": "Elias"}, dest)

    with zipfile.ZipFile(dest) as archive:
        raw = archive.read("content/content.json").decode("utf-8")
        assert "Anna" not in raw and "Fenn" not in raw and "Jonas" not in raw
        content = json.loads(raw)
        assert content["editorSettings"]["instructions"] == "Team\n\nLea und Falk\n\nElias' Liste"


def test_workflow_secret_replacements_per_target(application, course):
    (course / ".moodle-target-public.yml").write_text(
        "course_url: https://public.example/course/view.php?id=1\nauth: credentials\n", encoding="utf-8"
    )
    (course / ".moodle-target-school.yml").write_text(
        "course_url: https://school.example/course/view.php?id=2\nkeep_secrets: true\n", encoding="utf-8"
    )
    assert application._secret_replacements(course, "public") == {"Anna": "Person A", "Fenn": "Person B"}
    assert application._secret_replacements(course, "school") == {}
    assert application._secret_replacements(course, None) == {"Anna": "Person A", "Fenn": "Person B"}


def _build_chapter_package(application, course: Path, chapter: str = "001-a") -> Path:
    package_dir = application.COURSE_BUILD_DIR / course.name / "h5p" / chapter
    package = package_dir / "q1.h5p"
    write_package(package, title="Anna-Aufgabe", instructions="Anna laut Fenn vor.")
    return package


def test_remote_verification_expectations_use_sanitized_packages(application, course):
    original = _build_chapter_package(application, course)
    (course / ".moodle-target-public.yml").write_text(
        "course_url: https://public.example/course/view.php?id=1\nauth: credentials\n", encoding="utf-8"
    )

    expectations = application._remote_verification_expectations(course, "public")

    assert len(expectations) == 1
    package_path = Path(str(expectations[0]["packagePath"]))
    assert package_path != original
    assert "h5p-sanitized" in package_path.parts
    assert expectations[0]["title"] == "Test: Person A-Aufgabe"
    with zipfile.ZipFile(package_path) as archive:
        content = json.loads(archive.read("content/content.json"))
        assert "Anna" not in json.dumps(content)
        assert "Fenn" not in json.dumps(content)
    assert all("Anna" not in signal and "Fenn" not in signal for signal in expectations[0]["signals"])

    # Ziel mit keep_secrets: unveraendertes Paket.
    (course / ".moodle-target-school.yml").write_text(
        "course_url: https://school.example/course/view.php?id=2\nkeep_secrets: true\n", encoding="utf-8"
    )
    school_expectations = application._remote_verification_expectations(course, "school")
    assert Path(str(school_expectations[0]["packagePath"])) == original


def test_sanitize_packages_for_target_keeps_identifier_and_reads_title(application, course):
    original = _build_chapter_package(application, course)
    packages = application.collect_h5p_upload_packages(course, "001-a")

    sanitized = application._sanitize_packages_for_target(
        course, "001-a", packages, {"Anna": "Person A", "Fenn": "Person B"}, "public"
    )

    assert [package.identifier for package in sanitized] == ["q1"]
    assert sanitized[0].path != original
    assert sanitized[0].path.name == "q1.h5p"
    assert sanitized[0].title == "Test: Person A-Aufgabe"
    with zipfile.ZipFile(sanitized[0].path) as archive:
        assert "Anna" not in archive.read("h5p.json").decode("utf-8")


def test_sanitize_text_labels(application):
    from course_sync.classes.moodle_playwright_uploader import MoodleTextLabelUploadItem

    labels = [
        MoodleTextLabelUploadItem(identifier="l1", title="Anna erklärt", markdown="Anna und Fenns Code", before_identifier=None),
    ]
    sanitized = application._sanitize_text_labels(labels, {"Anna": "Person A", "Fenn": "Person B"})
    assert sanitized[0].identifier == "l1"
    assert sanitized[0].title == "Person A erklärt"
    assert sanitized[0].markdown == "Person A und Person Bs Code"
