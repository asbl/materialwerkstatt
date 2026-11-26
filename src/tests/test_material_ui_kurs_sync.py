from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import material_ui.app as material_app
from course_sync.classes.models import SyncMetadata, SyncMetadataEntry
from course_sync.classes.platform_sync_state import record_site_export_state, record_target_sync_state
from material_ui.plugins.kurse.chapters import group_questions_by_chapter
from material_ui.plugins.kurse.sync_overview import SyncOverview, SyncOverviewCache, _percent


def question(identifier: str, subdir: str) -> SimpleNamespace:
    return SimpleNamespace(identifier=identifier, title=identifier.upper(), h5p_subdir=subdir,
                           package_path=Path(f"{identifier}.h5p"))


class FakeApplication:
    """Minimaler Ersatz fuer CourseApplication: nur was die Uebersicht liest."""

    def __init__(self, questions, metadata=None, target_ids=None, plan=None, build_dir=None):
        self.questions = questions
        self.COURSE_BUILD_DIR = build_dir or Path("/nonexistent-build")
        self.metadata = metadata
        self.target_ids = target_ids or {}
        self.plan = plan or []
        self._SYNC_METADATA_STORE = SimpleNamespace(path=lambda course_dir: course_dir / ".course-sync.json")

    def parse_course(self, course_dir):
        return "Kurs", self.questions, ""

    def compute_question_hash(self, item):
        return f"hash-{item.identifier}"

    def load_sync_metadata(self, course_dir):
        return self.metadata

    def _course_chapter_plan(self, course_dir):
        return self.plan

    def _load_target_activity_ids(self, course_dir, target):
        return self.target_ids.get(target, {})

    def _target_activity_ids_path(self, course_dir, target):
        return course_dir / f".moodle-activity-ids-{target}.json"

    def _resolve_moodle_course_url(self, course_dir, course_url, target):
        return f"https://{target}.example.org/course/view.php?id=7"


class FakeAdapter:
    def __init__(self, application, chapters, chapter_ids=None):
        self._application = application
        self.chapters = chapters
        self.chapter_ids = chapter_ids or {}

    def read_chapter_question_order(self, course_dir, chapter):
        return self.chapter_ids.get(chapter, [])

    def application(self):
        return self._application

    def list_course_summaries(self, kurse_dir):
        return [{"slug": path.name, "title": "Kurs A", "chapters": len(self.chapters)}
                for path in sorted(kurse_dir.iterdir()) if (path / "index.mdx").is_file()]

    def list_course_chapters(self, course_dir):
        return self.chapters


def entry(identifier: str, local_hash: str, activity_id: int = 1) -> SyncMetadataEntry:
    return SyncMetadataEntry(identifier=identifier, remote_activity_id=activity_id, remote_instance_id=None,
                             remote_title=identifier, remote_url="", remote_visible=True,
                             local_hash=local_hash, remote_hash=local_hash)


@pytest.fixture()
def course(tmp_path):
    course_dir = tmp_path / "unterricht" / "kurse" / "kurs-a"
    course_dir.mkdir(parents=True)
    (course_dir / "index.mdx").write_text("# Kurs A\n", encoding="utf-8")
    return course_dir


def platform(overview: dict, identifier: str) -> dict:
    return next(item for item in overview["courses"][0]["platforms"] if item["id"] == identifier)


def test_default_moodle_distinguishes_current_changed_and_missing(tmp_path, course):
    questions = [question("a", "k1"), question("b", "k1"), question("c", "k1"), question("d", "k1")]
    metadata = SyncMetadata("kurs-a", 7, "https://moodle.example.org", {
        "a": entry("a", "hash-a"),
        "b": entry("b", "veraltet"),
        "c": entry("c", ""),
        "weg": entry("weg", "hash-weg"),
    })
    adapter = FakeAdapter(FakeApplication(questions, metadata), [{"slug": "k1", "title": "Kapitel 1"}])

    overview = SyncOverview(tmp_path, adapter).build()

    moodle = platform(overview, "moodle")
    assert moodle["counts"] == {"synced": 1, "changed": 1, "unknown": 1, "missing": 1}
    assert moodle["chapters"] == [{"slug": "k1", "statuses": ["synced", "changed", "unknown", "missing"]}]
    assert moodle["remoteOnly"] == 1
    assert moodle["url"] == "https://moodle.example.org/course/view.php?id=7"
    assert moodle["host"] == "moodle.example.org"
    # Mit nicht erfasstem Stand ist nur "vorhanden" belegbar: 3 von 4.
    assert (moodle["tracked"], moodle["percent"]) == (False, 75)
    assert overview["site"] == {"available": False, "host": ""}


def test_named_target_uses_recorded_hashes_and_skips_excluded_chapters(tmp_path, course):
    questions = [question("a", "k1"), question("b", "k1"), question("c", "k2"), question("d", "k2")]
    (course / ".moodle-target-schule.yml").write_text("auth: sso\n", encoding="utf-8")
    record_target_sync_state(course, "schule", {"a": "hash-a", "b": "alt"})
    application = FakeApplication(
        questions,
        target_ids={"schule": {"a": 11, "b": 12, "d": 14}},
        plan=[SimpleNamespace(slug="k1", synced=True), SimpleNamespace(slug="k2", synced=False)],
    )
    chapters = [{"slug": "k1", "title": "Kapitel 1"}, {"slug": "k2/content", "title": "Kapitel 2"}]

    overview = SyncOverview(tmp_path, FakeAdapter(application, chapters)).build()

    assert [item["synced"] for item in overview["courses"][0]["chapters"]] == [True, False]
    target = platform(overview, "moodle:schule")
    # "c" fehlt in einem ausgenommenen Kapitel und zaehlt nicht zum Soll; "d" liegt trotzdem dort.
    assert target["chapters"][1]["statuses"] == ["excluded", "unknown"]
    assert target["counts"] == {"synced": 1, "changed": 1, "unknown": 1, "missing": 0}
    assert (target["total"], target["excluded"], target["target"]) == (3, 1, "schule")
    assert target["host"] == "schule.example.org"


def test_website_compares_export_state(tmp_path, course):
    site = tmp_path / "build" / "site"
    (site / "h5p" / "kurs-a" / "k1").mkdir(parents=True)
    (site / "courses" / "kurs-a").mkdir(parents=True)
    (site / "index.html").write_text("", encoding="utf-8")
    (site / "courses" / "kurs-a" / "index.html").write_text("", encoding="utf-8")
    (site / "CNAME").write_text("kurse.example.org\n", encoding="utf-8")
    for identifier in ("a", "b", "c"):
        (site / "h5p" / "kurs-a" / "k1" / f"{identifier}.h5p").write_bytes(b"h5p")
    build = tmp_path / "build" / "kurse"
    record_site_export_state(build, site, {"kurs-a": {"a": "hash-a", "b": "alt"}})
    questions = [question(identifier, "k1") for identifier in ("a", "b", "c", "d")]
    plan = [SimpleNamespace(slug="k1", synced=False)]
    adapter = FakeAdapter(FakeApplication(questions, plan=plan, build_dir=build), [{"slug": "k1", "title": "Kapitel 1"}])

    overview = SyncOverview(tmp_path, adapter).build()

    website = platform(overview, "website")
    # Der Export kennt keine ausgenommenen Kapitel: alle Aktivitaeten zaehlen.
    assert website["counts"] == {"synced": 1, "changed": 1, "unknown": 1, "missing": 1}
    assert website["url"] == "https://kurse.example.org/courses/kurs-a/"
    assert overview["site"] == {"available": True, "host": "kurse.example.org"}


@pytest.mark.parametrize("broken", ["parse_course", "_course_chapter_plan", "load_sync_metadata"])
def test_broken_course_is_reported_without_breaking_the_overview(tmp_path, course, broken):
    other = tmp_path / "unterricht" / "kurse" / "kurs-b"
    other.mkdir()
    (other / "index.mdx").write_text("# Kurs B\n", encoding="utf-8")
    application = FakeApplication([question("a", "k1")])
    original = getattr(application, broken)

    def explode(course_dir):
        if course_dir.name == "kurs-a":
            raise RuntimeError("Kurs defekt")
        return original(course_dir)

    setattr(application, broken, explode)
    adapter = FakeAdapter(application, [{"slug": "k1", "title": "Kapitel 1"}])
    adapter.list_course_chapters = lambda course_dir: (_ for _ in ()).throw(RuntimeError("Kurs defekt")) \
        if broken == "_course_chapter_plan" and course_dir.name == "kurs-a" else [{"slug": "k1", "title": "Kapitel 1"}]

    overview = SyncOverview(tmp_path, adapter).build()

    by_slug = {item["slug"]: item for item in overview["courses"]}
    assert by_slug["kurs-a"]["error"] == "RuntimeError: Kurs defekt" or broken == "load_sync_metadata"
    assert by_slug["kurs-b"]["error"] is None
    assert by_slug["kurs-b"]["activities"] == 1


def test_chapters_sharing_a_subdirectory_keep_their_own_activities():
    chapters = [{"slug": "k2/a", "title": "A"}, {"slug": "k2/b", "title": "B"}, {"slug": "k1", "title": "Eins"}]
    questions = [question("a1", "k2"), question("b1", "k2"), question("a2", "k2"), question("e1", "k1"),
                 question("lose", "zusatz"), question("unklar", "k2")]
    ids = {"k2/a": ["a1", "a2"], "k2/b": ["b1"]}

    grouped = group_questions_by_chapter(chapters, questions, lambda chapter: ids.get(chapter, []))

    assert {item["slug"]: [q.identifier for q in item["questions"]] for item in grouped} == {
        "k2/a": ["a1", "a2", "unklar"],   # ohne Treffer gewinnt das erste Kapitel
        "k2/b": ["b1"],
        "k1": ["e1"],
        "zusatz": ["lose"],
    }
    assert grouped[-1]["title"] == "Weitere Aktivitäten"
    assert "questions" not in chapters[0]  # Eingabe bleibt unveraendert


def test_cache_serves_within_ttl_and_refreshes_on_demand():
    calls = []
    cache = SyncOverviewCache(60, lambda: calls.append(1) or {"n": len(calls)})

    assert cache.get() == {"n": 1} and cache.get() == {"n": 1}
    assert cache.get(refresh=True) == {"n": 2}
    cache.invalidate()
    assert cache.get() == {"n": 3}


def test_invalidate_never_waits_for_a_running_build_and_discards_its_result():
    started, release = threading.Event(), threading.Event()
    results = iter([{"n": 1}, {"n": 2}])

    def slow_build():
        value = next(results)
        started.set()
        release.wait(timeout=5)
        return value

    cache = SyncOverviewCache(60, slow_build)
    runner = threading.Thread(target=lambda: cache.get())
    runner.start()
    assert started.wait(timeout=5)

    invalidator = threading.Thread(target=cache.invalidate)
    invalidator.start()
    invalidator.join(timeout=1)
    assert not invalidator.is_alive(), "invalidate blockiert auf der laufenden Auswertung"

    release.set()
    runner.join(timeout=5)
    # Das waehrend der Invalidierung entstandene Ergebnis ist ueberholt und wird nicht gemerkt.
    assert cache.get() == {"n": 2}


@pytest.mark.parametrize(("part", "total", "expected"), [(0, 0, 0), (0, 5, 0), (5, 5, 100), (199, 200, 99), (1, 400, 1), (1, 2, 50)])
def test_percent_reports_zero_and_full_only_when_exact(part, total, expected):
    assert _percent(part, total) == expected


def test_sync_overview_route_reads_real_course(tmp_path, monkeypatch):
    monkeypatch.setattr(material_app, "ROOT", tmp_path)
    course_dir = tmp_path / "unterricht" / "kurse" / "kurs-a"
    (course_dir / "chapters").mkdir(parents=True)
    (course_dir / "index.mdx").write_text('# Kurs A\n\n<Chapter src="./chapters/k1.mdx" title="Kapitel 1" />\n', encoding="utf-8")
    (course_dir / "chapters" / "k1.mdx").write_text("# Kapitel 1\n", encoding="utf-8")
    (course_dir / ".course-sync.json").write_text(json.dumps({
        "version": 1, "course": "kurs-a", "remoteCourseId": 3, "moodleBaseUrl": "https://moodle.example.org", "entries": [],
    }), encoding="utf-8")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        try:
            response = app.test_client().get("/api/kurse/sync-overview?refresh=1")
        finally:
            app.extensions["material_runtime"].close()

    assert response.status_code == 200
    payload = response.get_json()
    assert [item["slug"] for item in payload["courses"]] == ["kurs-a"]
    assert payload["courses"][0]["error"] is None
    assert [item["id"] for item in payload["courses"][0]["platforms"]] == ["moodle"]
