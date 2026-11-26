from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from invoke import task
from material_core.dotenv import read_dotenv_values
from material_core.filesystem import atomic_write_text
from material_core import content_tests, workspace


ROOT_DIR = workspace.root()
SRC_DIR = workspace.CODE_SRC
PYTHON = sys.executable
COURSE_SYNC = SRC_DIR / "course_sync" / "main.py"

# Wird von _run_python bei jedem ueber diese Tasks gestarteten Subprozess gesetzt. Kommandos, die mit
# dem Remote-Moodle-Kurs kommunizieren (siehe REMOTE_SYNC_COMMANDS in
# src/course_sync/classes/cli/runner.py), pruefen diese Variable und brechen ohne sie ab. So sind
# Remote-Sync-Operationen technisch auf die hier definierten Tasks beschraenkt; ein direkter Aufruf
# von `python -m course_sync.main upload-...` ausserhalb von `inv` schlaegt bewusst fehl. Siehe auch
# AGENTS.md, Abschnitt "Remote-Sync-Regel".
REMOTE_SYNC_ENV = {"COURSE_SYNC_TASK": "1"}


def _subprocess_env() -> dict[str, str]:
    env = {**os.environ, **REMOTE_SYNC_ENV}
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC_DIR) + (os.pathsep + existing_path if existing_path else "")
    return env


def _run_python(ctx, *args: str, pty: bool = False) -> None:
    del ctx, pty
    command_args = list(args)
    if command_args and command_args[0] == str(COURSE_SYNC):
        command_args = ["-m", "course_sync.main", *command_args[1:]]
    env = _subprocess_env()
    cwd = ROOT_DIR
    if command_args[:2] == ["-m", "pytest"]:
        # Die Werkzeugtests liegen beim Programm, nicht im Inhaltsordner.
        cwd = workspace.CODE_ROOT
        env[workspace.ENV] = str(cwd)
    subprocess.run([PYTHON, *command_args], check=True, cwd=cwd, env=env)


def _run_content_tests() -> None:
    """Tests der Kurse (`unterricht/kurse/<kurs>/tests`), sofern vorhanden."""
    if content_tests.directories(ROOT_DIR) and content_tests.run(ROOT_DIR, python=PYTHON):
        raise SystemExit("Inhaltstests fehlgeschlagen.")


def _print_status_best_effort(course: str) -> None:
    """After-sync-Absicherung: zeigt den lokalen Sync-Status, ohne eine erfolgreiche Sync als
    fehlgeschlagen zu melden, falls fuer den Kurs (noch) keine Sync-Metadaten existieren."""
    result = subprocess.run(
        [PYTHON, "-m", "course_sync.main", "status", course],
        cwd=ROOT_DIR,
        env=_subprocess_env(),
    )
    if result.returncode != 0:
        print(f"(Hinweis: Kein lokaler Sync-Status fuer '{course}' verfuegbar.)")


def _invoke_binary(project_dir: Path) -> str:
    local_invoke = project_dir / ".venv" / "bin" / "invoke"
    if local_invoke.exists():
        return str(local_invoke)
    return shutil.which("invoke") or shutil.which("inv") or "invoke"


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _course_chapters(course: str) -> list[str]:
    index_path = ROOT_DIR / "unterricht" / "kurse" / course / "index.mdx"
    if not index_path.exists():
        raise FileNotFoundError(f"Course index not found: {index_path}")

    source = index_path.read_text(encoding="utf-8")
    chapters = [
        Path(match).stem
        for match in re.findall(r"<Chapter\b[^>]*\bsrc=[\"']\.\/chapters\/([^\"']+\.mdx)[\"']", source)
    ]
    if not chapters:
        raise RuntimeError(f"No chapters found in {index_path}")
    return chapters


def _ensure_course_sync_metadata(course: str, remote_course_id: int | None, moodle_base_url: str = "") -> None:
    """Legt `.course-sync.json` an, falls sie fehlt; Kurs-ID und Moodle-URL kommen vom Aufrufer.

    Die Moodle-URL faellt auf `MOODLE_BASE_URL` (.env) zurueck. Fehlen Angaben, bricht der Task mit
    einer Anleitung ab, statt Werte zu raten.
    """
    metadata_path = ROOT_DIR / "unterricht" / "kurse" / course / ".course-sync.json"
    if metadata_path.exists():
        return
    moodle_base_url = moodle_base_url or os.environ.get("MOODLE_BASE_URL") or read_dotenv_values(ROOT_DIR / ".env").get("MOODLE_BASE_URL", "")
    if not remote_course_id or not moodle_base_url:
        raise SystemExit(
            f"{metadata_path} fehlt. Remote-Kurs-ID (--remote-course-id) und Moodle-URL (MOODLE_BASE_URL in .env) "
            "angeben, oder den Kurs zuerst mit `inv kurse.import-moodle` einrichten."
        )

    atomic_write_text(
        metadata_path,
        json.dumps(
            {
                "version": 1,
                "course": course,
                "remoteCourseId": remote_course_id,
                "moodleBaseUrl": moodle_base_url.rstrip("/"),
                "entries": [],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        overwrite=False,
    )


@task
def test(ctx) -> None:
    """Run the test suite: tool tests, then the tests of the courses."""
    _run_python(ctx, "-m", "pytest", "src/tests/course_sync", "-q")
    _run_content_tests()


@task(name="list-courses", optional=["verbose"])
def list_courses(ctx, verbose: bool = False) -> None:
    """List local courses."""
    args = [str(COURSE_SYNC), "list-courses"]
    if verbose:
        args.append("--verbose")
    _run_python(ctx, *args)


@task(name="new-course", optional=["title", "language", "force"])
def new_course(ctx, course: str, title: str = "", language: str = "de", force: bool = False) -> None:
    """Create a minimal new course scaffold."""
    args = [str(COURSE_SYNC), "new-course", course]
    if title:
        args.extend(["--title", title])
    if language != "de":
        args.extend(["--language", language])
    if force:
        args.append("--force")
    _run_python(ctx, *args)


@task(optional=["course"])
def sync(ctx, course: str = "python-2026") -> None:
    """Generate H5P output for a course."""
    _run_python(ctx, str(COURSE_SYNC), "sync", course)


@task(optional=["course"])
def build(ctx, course: str = "") -> None:
    """Batch-prepare H5P output and preview runtime."""
    args = [str(COURSE_SYNC), "build"]
    if course:
        args.append(course)
    _run_python(ctx, *args)


@task(name="export-site", optional=["course", "courses", "output", "site_url"])
def export_site(ctx, course: str = "", courses: str = "", output: str = "build/site", site_url: str = "") -> None:
    """Generate a static course website for local use or GitHub Pages."""
    args = [str(COURSE_SYNC), "export-site"]
    selected_courses = courses.split() if courses else ([course] if course else [])
    args.extend(selected_courses)
    if output != "build/site":
        args.extend(["--output", output])
    if site_url:
        args.extend(["--site-url", site_url])
    _run_python(ctx, *args)


@task(name="update-h5p-libraries", optional=["tag"])
def update_h5p_libraries(ctx, tag: str = "") -> None:
    """Download the latest custom H5P libraries from GitHub into libraries/."""
    args = [str(COURSE_SYNC), "update-h5p-libraries"]
    if tag:
        args.extend(["--tag", tag])
    _run_python(ctx, *args)


@task(name="sync-h5p-dev", optional=["h5p_dev_dir"])
def sync_h5p_dev(ctx, h5p_dev_dir: str = "") -> None:
    """Installiert die neuesten H5P-Libraries aus dem lokalen h5p-dev-Export.

    Packt die Libraries aus <h5p-dev>/export/ (z.B. H5P.PythonQuestion-6.152_*.h5p)
    nach ressourcen/libraries/ und .h5p-runtime/libraries/ und invalidiert die
    Runtime-Build-Marker, damit der naechste `inv kurse.build` alle Inhalte mit
    den neuen Library-Pins neu packt. h5p_dev_dir muss explizit angegeben
    werden, da h5p-dev kein Unterordner von material-datenbank ist.
    """
    if not h5p_dev_dir:
        raise ValueError(
            "--h5p-dev-dir muss angegeben werden, z.B. --h5p-dev-dir=<Pfad>/h5p-dev"
        )
    export_dir = Path(h5p_dev_dir).expanduser().resolve() / "export"
    _run_python(ctx, str(COURSE_SYNC), "update-h5p-libraries-local", "--export-dir", str(export_dir))


@task(optional=["course", "output"])
def export_chapter(ctx, chapter: str, course: str = "python-2026", output: str = "") -> None:
    """Copy one chapter's built H5P packages into an upload folder."""
    args = [str(COURSE_SYNC), "export-chapter", course, chapter]
    if output:
        args.extend(["--output", output])
    _run_python(ctx, *args)


@task(
    name="sync-miniworlds-examples-moodle",
    optional=["course_url", "username", "password", "headless", "timeout", "verify_mbz_sync", "verify_remote", "skip_tests"],
)
def sync_miniworlds_examples_moodle(
    ctx,
    course_url: str = "",
    username: str = "",
    password: str = "",
    headless: bool = False,
    timeout: int = 30000,
    verify_mbz_sync: bool = False,
    verify_remote: bool = False,
    skip_tests: bool = False,
    remote_course_id: int = 0,
) -> None:
    """Build and upload all miniworlds_examples chapters to Moodle.

    `--remote-course-id` wird nur gebraucht, wenn `.course-sync.json` des Kurses noch fehlt.

    Requires:
    - Playwright-Nutzer: Moodle-Zugang mit Trainer-Rolle (oder hoeher) im Kurs
    - Webservice-Nutzer: Eingeschrieben im Kurs (fuer API-Zugriffe)

    Beide Nutzer muessen Zugriff auf den Kurs haben!

    Before-sync: laeuft die Testsuite (ausser mit --skip-tests). After-sync: zeigt den
    lokalen Sync-Status des Kurses.
    """
    course = "miniworlds_examples"
    _ensure_course_sync_metadata(course, remote_course_id)

    if not skip_tests:
        test(ctx)
    _run_python(ctx, str(COURSE_SYNC), "build", course)

    for chapter in _course_chapters(course):
        args = [str(COURSE_SYNC), "upload-chapter-moodle", course, chapter]
        if course_url:
            args.extend(["--course-url", course_url])
        if username:
            args.extend(["--username", username])
        if password:
            args.extend(["--password", password])
        if headless:
            args.append("--headless")
        if timeout != 30000:
            args.extend(["--timeout", str(timeout)])
        if verify_mbz_sync:
            args.append("--verify-mbz-sync")
        if verify_remote:
            args.append("--verify-remote")
        _run_python(ctx, *args, pty=not headless)

    _print_status_best_effort(course)


@task(
    optional=[
        "course_url",
        "target",
        "section",
        "username",
        "password",
        "storage_state",
        "headless",
        "timeout",
        "verify_mbz_sync",
        "verify_remote",
        "skip_tests",
    ]
)
def upload_chapter_moodle(
    ctx,
    course: str = "python-2026",
    chapter: str = "",
    course_url: str = "",
    target: str = "",
    section: str = "",
    username: str = "",
    password: str = "",
    storage_state: str = "",
    headless: bool = False,
    timeout: int = 30000,
    verify_mbz_sync: bool = False,
    verify_remote: bool = False,
    skip_tests: bool = False,
) -> None:
    """Upload or update one chapter's H5P packages in Moodle via Playwright.

    Usage:
        inv kurse.upload-chapter-moodle --course=COURSE --chapter=CHAPTER [--course-url URL] [--username USER] [--password PASS] [--headless]

    Requires:
    - Playwright-Nutzer: Moodle-Zugang mit Trainer-Rolle (oder hoeher) im Kurs
    - Webservice-Nutzer: Eingeschrieben im Kurs (fuer API-Zugriffe)

    Before-sync: laeuft die Testsuite (ausser mit --skip-tests), damit keine kaputte lokale
    Synchronisierung in Moodle landet. After-sync: zeigt den lokalen Sync-Status des Kurses.
    Fuer die vollstaendig abgesicherte Variante mit MBZ-Backup-Diff und Remote-Verifikation
    als Standard siehe `inv kurse.publish`.
    """
    if not chapter:
        raise ValueError("CHAPTER must be provided, e.g.: inv kurse.upload-chapter-moodle --course=python-2026 --chapter=001-einstieg")
    if not skip_tests:
        test(ctx)
    args = [str(COURSE_SYNC), "upload-chapter-moodle", course, chapter]
    if course_url:
        args.extend(["--course-url", course_url])
    if target:
        args.extend(["--target", target])
    if section:
        args.extend(["--section", section])
    if username:
        args.extend(["--username", username])
    if password:
        args.extend(["--password", password])
    if storage_state:
        args.extend(["--storage-state", storage_state])
    if headless:
        args.append("--headless")
    if timeout != 30000:
        args.extend(["--timeout", str(timeout)])
    if verify_mbz_sync:
        args.append("--verify-mbz-sync")
    if verify_remote:
        args.append("--verify-remote")
    _run_python(ctx, *args, pty=not headless)
    _print_status_best_effort(course)


@task(
    name="sync-h5p-demo-courses-moodle",
    optional=[
        "german_course",
        "english_course",
        "german_course_url",
        "english_course_url",
        "timeout",
        "verify_mbz_sync",
        "verify_remote",
    ],
)
def sync_h5p_demo_courses_moodle(
    ctx,
    german_course: str = "h5p-demo",
    english_course: str = "h5p-demo-en",
    german_course_url: str = "",
    english_course_url: str = "",
    headless: bool = False,
    timeout: int = 30000,
    verify_mbz_sync: bool = False,
    verify_remote: bool = False,
    german_course_id: int = 0,
    english_course_id: int = 0,
) -> None:
    """Build and upload both H5P demo courses to their configured Moodle courses.

    Die Remote-Kurs-IDs (`--german-course-id`, `--english-course-id`) werden nur gebraucht, wenn
    `.course-sync.json` des jeweiligen Kurses noch fehlt.

    Before-sync: laeuft immer die Testsuite. After-sync: zeigt den lokalen Sync-Status
    beider Kurse.
    """
    _ensure_course_sync_metadata(german_course, german_course_id)
    _ensure_course_sync_metadata(english_course, english_course_id)

    _run_python(ctx, "-m", "pytest", "src/tests/course_sync", "-q")
    _run_content_tests()
    for course in [german_course, english_course]:
        _run_python(ctx, str(COURSE_SYNC), "build", course)

    for course, course_url in [(german_course, german_course_url), (english_course, english_course_url)]:
        for chapter in _course_chapters(course):
            args = [str(COURSE_SYNC), "upload-chapter-moodle", course, chapter]
            if course_url:
                args.extend(["--course-url", course_url])
            if headless:
                args.append("--headless")
            if timeout != 30000:
                args.extend(["--timeout", str(timeout)])
            if verify_mbz_sync:
                args.append("--verify-mbz-sync")
            if verify_remote:
                args.append("--verify-remote")
            _run_python(ctx, *args, pty=not headless)
        _print_status_best_effort(course)


@task(optional=["course"])
def audit(ctx, course: str = "python-2026") -> None:
    """Audit local course content and built H5P packages for common sync/content issues.

    Rein lokal, keine Remote-Verbindung. Nuetzlicher before-sync-Check vor jedem Upload.
    """
    _run_python(ctx, str(COURSE_SYNC), "audit", course)


@task(name="push-moodle", optional=["base_url", "token"])
def push_moodle(ctx, course: str, remote_course_id: int, base_url: str = "", token: str = "") -> None:
    """Attempt to push a local course as Moodle H5P activities via the REST API.

    Fuer die meisten Moodle-Installationen (noch) nicht unterstuetzt; siehe
    MoodleSyncer.push_moodle_course fuer die konkreten API-Einschraenkungen.
    """
    args = [str(COURSE_SYNC), "push-moodle", course, str(remote_course_id)]
    if base_url:
        args.extend(["--base-url", base_url])
    if token:
        args.extend(["--token", token])
    _run_python(ctx, *args)


@task(
    name="upload-course-moodle",
    optional=[
        "course_url",
        "target",
        "username",
        "password",
        "storage_state",
        "headless",
        "timeout",
        "verify_mbz_sync",
        "verify_remote",
        "prune_extra_sections",
        "skip_tests",
        "skip_audit",
    ],
)
def upload_course_moodle(
    ctx,
    course: str = "python-2026",
    course_url: str = "",
    target: str = "",
    username: str = "",
    password: str = "",
    storage_state: str = "",
    headless: bool = False,
    timeout: int = 30000,
    verify_mbz_sync: bool = True,
    verify_remote: bool = True,
    prune_extra_sections: bool = False,
    skip_tests: bool = False,
    skip_audit: bool = False,
) -> None:
    """Upload every synced chapter of a course to Moodle and reconcile sections with index.mdx.

    Before-sync: Testsuite und `course-sync audit` laufen zuerst und brechen bei Fehlern ab,
    bevor irgendetwas remote geschrieben wird (abschaltbar mit --skip-tests/--skip-audit).
    After-sync: MBZ-Backup-Diff und Remote-Frame-Verifikation laufen standardmaessig
    (abschaltbar mit --no-verify-mbz-sync/--no-verify-remote), danach ein lokaler
    Statusbericht.

    --prune-extra-sections loescht Moodle-Sections, die nicht mehr in index.mdx vorkommen,
    inklusive ihrer Aktivitaeten. Bewusst kein Default, da destruktiv.
    """
    if not skip_tests:
        test(ctx)
    if not skip_audit:
        _run_python(ctx, str(COURSE_SYNC), "audit", course)
    args = [str(COURSE_SYNC), "upload-course-moodle", course]
    if course_url:
        args.extend(["--course-url", course_url])
    if target:
        args.extend(["--target", target])
    if username:
        args.extend(["--username", username])
    if password:
        args.extend(["--password", password])
    if storage_state:
        args.extend(["--storage-state", storage_state])
    if headless:
        args.append("--headless")
    if timeout != 30000:
        args.extend(["--timeout", str(timeout)])
    if verify_mbz_sync:
        args.append("--verify-mbz-sync")
    if verify_remote:
        args.append("--verify-remote")
    if prune_extra_sections:
        args.append("--prune-extra-sections")
    _run_python(ctx, *args, pty=not headless)
    _print_status_best_effort(course)


@task(
    name="verify-moodle",
    optional=["course_url", "target", "username", "password", "storage_state", "headless", "timeout"],
)
def verify_moodle(
    ctx,
    course: str = "python-2026",
    course_url: str = "",
    target: str = "",
    username: str = "",
    password: str = "",
    storage_state: str = "",
    headless: bool = False,
    timeout: int = 30000,
    missing_ids_only: bool = False,
) -> None:
    """Verify remote H5P activities in Moodle against local expectations.

    Rein lesend (keine Uploads), aber greift live auf den Remote-Kurs zu und ist deshalb
    ebenfalls ein dedizierter Sync-Task. --missing-ids-only beschraenkt die Pruefung
    auf fehlende lokale Ziel-IDs; bestaetigte Zuordnungen werden lokal ergaenzt.
    """
    args = [str(COURSE_SYNC), "verify-moodle", course]
    if course_url:
        args.extend(["--course-url", course_url])
    if target:
        args.extend(["--target", target])
    if username:
        args.extend(["--username", username])
    if password:
        args.extend(["--password", password])
    if storage_state:
        args.extend(["--storage-state", storage_state])
    if headless:
        args.append("--headless")
    if timeout != 30000:
        args.extend(["--timeout", str(timeout)])
    if missing_ids_only:
        args.append("--missing-ids-only")
    _run_python(ctx, *args, pty=not headless)


@task(
    optional=[
        "course_url",
        "target",
        "username",
        "password",
        "storage_state",
        "timeout",
    ]
)
def publish(
    ctx,
    course: str = "python-2026",
    course_url: str = "",
    target: str = "",
    username: str = "",
    password: str = "",
    storage_state: str = "",
    headless: bool = False,
    timeout: int = 30000,
    prune_extra_sections: bool = False,
    verify_mbz_sync: bool = True,
    skip_tests: bool = False,
) -> None:
    """Run the fully-guarded release path: audit -> upload -> remote verify -> status.

    Dies ist der sicherste Weg, einen Kurs final nach Moodle zu veroeffentlichen: Testsuite
    und Audit laufen vorher und brechen bei Fehlern ab; Remote-Verifikation laeuft danach
    immer und bricht bei Abweichungen ab; ein MBZ-Backup-Diff laeuft standardmaessig mit
    (abschaltbar mit --no-verify-mbz-sync); ein Statusbericht schliesst ab.

    Fuer schnelle Iteration waehrend der Content-Erstellung stattdessen
    `inv kurse.upload-chapter-moodle` verwenden, das ist bewusst leichtgewichtiger.
    """
    if not skip_tests:
        test(ctx)
    args = [str(COURSE_SYNC), "publish", course]
    if course_url:
        args.extend(["--course-url", course_url])
    if target:
        args.extend(["--target", target])
    if username:
        args.extend(["--username", username])
    if password:
        args.extend(["--password", password])
    if storage_state:
        args.extend(["--storage-state", storage_state])
    if headless:
        args.append("--headless")
    if timeout != 30000:
        args.extend(["--timeout", str(timeout)])
    if prune_extra_sections:
        args.append("--prune-extra-sections")
    if verify_mbz_sync:
        args.append("--verify-mbz-sync")
    _run_python(ctx, *args, pty=not headless)


@task(optional=["base_url", "token"])
def import_moodle(ctx, course: str, remote_course_id: int, base_url: str = "", token: str = "") -> None:
    """Import a Moodle course into the local MDX structure."""
    args = [str(COURSE_SYNC), "import-moodle", course, str(remote_course_id)]
    if base_url:
        args.extend(["--base-url", base_url])
    if token:
        args.extend(["--token", token])
    _run_python(ctx, *args)


@task(name="import-mbz", optional=["remote_course_id", "base_url"])
def import_mbz(ctx, course: str, mbz_path: str, remote_course_id: int = 0, base_url: str = "") -> None:
    """Import a Moodle course from a local .mbz backup file (no API credentials needed)."""
    args = [str(COURSE_SYNC), "import-mbz", course, mbz_path]
    if remote_course_id:
        args.extend(["--remote-course-id", str(remote_course_id)])
    if base_url:
        args.extend(["--base-url", base_url])
    _run_python(ctx, *args)


@task(name="moodle-ping", optional=["base_url", "token"])
def moodle_ping(ctx, base_url: str = "", token: str = "") -> None:
    """Verify that the configured Moodle webservice connection works."""
    args = [str(COURSE_SYNC), "moodle-ping"]
    if base_url:
        args.extend(["--base-url", base_url])
    if token:
        args.extend(["--token", token])
    _run_python(ctx, *args)


@task(optional=["course"])
def status(ctx, course: str = "python-2026") -> None:
    """Show the local Moodle sync status for a course."""
    _run_python(ctx, str(COURSE_SYNC), "status", course)


@task(optional=["port"])
def serve(ctx, port: int = 8765) -> None:
    """Start the local preview server."""
    print(f"Lokale Vorschau: http://127.0.0.1:{port}")
    _run_python(ctx, str(COURSE_SYNC), "serve", "--port", str(port))


@task
def clean(ctx) -> None:
    """Remove generated course output and temporary local folders."""
    for target in [ROOT_DIR / "content", ROOT_DIR / "build" / "scratch" / "temp", ROOT_DIR / "uploads"]:
        _remove_path(target)

    for cache_dir in (ROOT_DIR / "unterricht" / "kurse").glob("**/__pycache__"):
        _remove_path(cache_dir)

    courses_dir = ROOT_DIR / "unterricht" / "kurse"
    for build_dir in courses_dir.glob("*/build"):
        _remove_path(build_dir)


@task(name="clean-runtime")
def clean_runtime(ctx) -> None:
    """Remove the bootstrapped local H5P runtime."""
    _remove_path(ROOT_DIR / ".h5p-runtime")


@task
def smoke(ctx, course: str = "python-2026") -> None:
    """Run a quick local verification of tests and sync."""
    test(ctx)
    sync(ctx, course=course)


@task(
    name="release-questions-workflow",
    optional=["h5p_dev_dir", "course", "english_course", "tag", "release_target"],
)
def release_questions_workflow(
    ctx,
    h5p_dev_dir: str = "",
    course: str = "h5p-demo",
    english_course: str = "h5p-demo-en",
    tag: str = "",
    release_target: str = "all",
    dry_run: bool = False,
    skip_release: bool = False,
) -> None:
    """Run the Questions release/update/demo verification workflow.

    h5p_dev_dir muss explizit angegeben werden (z.B. --h5p-dev-dir=/pfad/zu/h5p-dev), da
    h5p-dev kein Unterordner von material-datenbank ist und daher kein sinnvoller
    repo-relativer Default existiert.
    """
    del ctx
    if not h5p_dev_dir:
        raise ValueError("--h5p-dev-dir muss angegeben werden, z.B. --h5p-dev-dir=<Pfad>/h5p-dev")
    h5p_dev_path = Path(h5p_dev_dir).expanduser().resolve()
    if not h5p_dev_path.exists():
        raise FileNotFoundError(f"h5p-dev directory not found: {h5p_dev_path}")

    h5p_invoke = _invoke_binary(h5p_dev_path)

    subprocess.run([h5p_invoke, "pack-all"], check=True, cwd=h5p_dev_path)

    if not skip_release:
        release_args = [h5p_invoke, "deploy.release"]
        if release_target == "all":
            release_args.append("--all")
        elif release_target:
            release_args.extend(["--target", release_target])
        if dry_run:
            release_args.append("--dry-run")
        subprocess.run(release_args, check=True, cwd=h5p_dev_path)

    update_args = [PYTHON, "-m", "course_sync.main", "update-h5p-libraries"]
    if tag:
        update_args.extend(["--tag", tag])
    subprocess.run(update_args, check=True, cwd=ROOT_DIR)

    subprocess.run(
        [PYTHON, "-m", "pytest", "src/tests/course_sync", "-q"],
        check=True,
        cwd=workspace.CODE_ROOT,
    )
    _run_content_tests()
    for demo_course in dict.fromkeys([course, english_course]):
        if demo_course:
            subprocess.run(
                [PYTHON, "-m", "course_sync.main", "build", demo_course],
                check=True,
                cwd=ROOT_DIR,
            )
