from __future__ import annotations

from course_sync.classes.course_sources import course_source_files
from material_core import content_tests


def test_findet_kurs_und_vorlagentests(tmp_path):
    for name in ("unterricht/kurse/a/tests", "unterricht/kurse/b/tests", "src/quarto/_local/tests", "unterricht/kurse/c"):
        (tmp_path / name).mkdir(parents=True)
    found = [path.relative_to(tmp_path).as_posix() for path in content_tests.directories(tmp_path)]
    assert found == ["unterricht/kurse/a/tests", "unterricht/kurse/b/tests", "src/quarto/_local/tests"]
    assert content_tests.directories(tmp_path, "b") == [tmp_path / "unterricht/kurse/b/tests"]


def test_laeuft_mit_dem_programmcode_und_gleichen_dateinamen(tmp_path):
    for course in ("a", "b"):
        folder = tmp_path / "unterricht/kurse" / course / "tests"
        folder.mkdir(parents=True)
        (folder / "test_inhalt.py").write_text("import course_sync\n\n\ndef test_ok():\n    pass\n")
    assert content_tests.run(tmp_path) == 0


def test_kurstests_zaehlen_nicht_als_kursquelle(tmp_path):
    for name in ("index.mdx", "tests/test_x.py", "chapters/tests/aufgabe.mdx"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x")
    names = [path.relative_to(tmp_path).as_posix() for path in course_source_files(tmp_path)]
    assert names == ["chapters/tests/aufgabe.mdx", "index.mdx"]
