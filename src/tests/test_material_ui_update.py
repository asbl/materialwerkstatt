import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from material_core import updates
from material_ui.app import create_app
from material_ui.config import AppConfig
from test_material_ui import LiveServer, free_port, sync_playwright


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.org", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def release(origin, version, filename="neu.txt"):
    (origin / "pyproject.toml").write_text(f'[project]\nname = "demo"\nversion = "{version}"\n', encoding="utf-8")
    (origin / filename).write_text(version, encoding="utf-8")
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", version)
    git(origin, "tag", f"v{version}")


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """Quelle mit zwei Releases und ein Klon, der noch auf dem ersten steht."""
    origin, clone = tmp_path / "origin", tmp_path / "clone"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    release(origin, "0.9.0")
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    release(origin, "0.10.0")
    git(origin, "tag", "v1.0.0-rc1")
    monkeypatch.setenv("MATERIAL_UI_UPDATE_URL", str(origin))
    monkeypatch.setenv("MATERIAL_UI_UPDATE_CHECK", "1")
    # Ohne virtuelle Umgebung: der Test installiert nichts.
    monkeypatch.setattr(updates.sys, "prefix", updates.sys.base_prefix)
    return origin, clone


def test_latest_release_compares_numbers_and_skips_prereleases(repos):
    origin, clone = repos
    assert updates.latest_release(str(origin)) == "0.10.0"
    assert updates.current_version(clone) == "0.9.0"
    assert updates.is_newer("0.10.0", "0.9.0")
    assert not updates.is_newer("0.9.0", "0.9.0")
    assert not updates.is_newer("v1.0.0-rc1", "0.9.0")


def test_default_source_is_the_repository_of_the_project(monkeypatch):
    monkeypatch.delenv("MATERIAL_UI_UPDATE_URL", raising=False)
    assert updates.source_url().startswith("https://")
    monkeypatch.setattr(updates.workspace, "CODE_ROOT", Path("/nicht/vorhanden"))
    assert updates.source_url() == ""
    with pytest.raises(updates.UpdateError, match="Quelle"):
        updates.latest_release("")


def test_cache_limits_requests_and_survives_being_offline(repos, tmp_path, monkeypatch):
    cache = tmp_path / "state/update.json"
    assert updates.latest_cached(cache)["latest"] == "0.10.0"

    def offline(url):
        raise updates.UpdateError("offline")

    monkeypatch.setattr(updates, "latest_release", offline)
    assert updates.latest_cached(cache)["error"] == ""
    refreshed = updates.latest_cached(cache, refresh=True)
    assert (refreshed["latest"], refreshed["error"]) == ("0.10.0", "offline")


def test_apply_fast_forwards_the_clone(repos):
    _, clone = repos
    updates.apply("0.10.0", clone)
    assert updates.current_version(clone) == "0.10.0"
    with pytest.raises(updates.UpdateError, match="bereits"):
        updates.apply("0.10.0", clone)


@pytest.mark.parametrize("change", ["dirty", "commit"])
def test_apply_never_overwrites_local_work(repos, change):
    _, clone = repos
    (clone / "neu.txt").write_text("eigene Arbeit", encoding="utf-8")
    if change == "commit":
        git(clone, "commit", "-qam", "eigen")
    head = git(clone, "rev-parse", "HEAD")
    with pytest.raises(updates.UpdateError):
        updates.apply("0.10.0", clone)
    assert git(clone, "rev-parse", "HEAD") == head
    assert (clone / "neu.txt").read_text(encoding="utf-8") == "eigene Arbeit"


def test_failed_dependency_install_restores_the_previous_state(repos, monkeypatch):
    _, clone = repos
    monkeypatch.setattr(updates.sys, "prefix", "/venv")
    monkeypatch.setattr(updates.sys, "executable", shutil.which("false"))
    with pytest.raises(updates.UpdateError, match="alte Stand"):
        updates.apply("0.10.0", clone)
    assert updates.current_version(clone) == "0.9.0"


def test_api_offers_and_applies_only_the_latest_release(repos, tmp_path, monkeypatch):
    _, clone = repos
    monkeypatch.setattr(updates.workspace, "CODE_ROOT", clone)
    content = tmp_path / "content"
    content.mkdir()
    app = create_app(config=AppConfig(content))
    app.testing = True
    try:
        client = app.test_client()
        status = client.get("/api/update").json
        assert (status["current"], status["latest"], status["kind"]) == ("0.9.0", "0.10.0", "git")
        assert status["updateAvailable"] and not status["restartRequired"]
        assert client.post("/api/update/apply", json={"version": "0.9.5"}).status_code == 400
        identifier = app.extensions["material_runtime"].jobs.create("blatt", "render")
        assert client.post("/api/update/apply", json={"version": "0.10.0"}).status_code == 409
        app.extensions["material_runtime"].jobs.update(identifier, running=False)
        response = client.post("/api/update/apply", json={"version": "0.10.0"})
        assert response.status_code == 200, response.json
        assert response.json["restartRequired"] and not response.json["updateAvailable"]
    finally:
        app.extensions["material_runtime"].close()


def test_interface_offers_updates_by_installation_kind():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js ist nicht installiert")
    module = (Path(__file__).resolve().parents[1] / "material_ui/static/app-update.js").as_uri()
    script = '''
import assert from "node:assert/strict";
import { describeUpdate } from MODULE;
const data = { enabled: true, latest: "0.2.0", updateAvailable: true, restartRequired: false, kind: "git" };
assert.equal(describeUpdate(data).canApply, true);
assert.equal(describeUpdate(data).notify, true);
assert.equal(describeUpdate(data, "0.2.0").notify, false);
assert.equal(describeUpdate(data, "0.2.0").canApply, true);
assert.equal(describeUpdate({ ...data, kind: "package" }).canApply, false);
assert.match(describeUpdate({ ...data, kind: "package" }).hint, /Paketverwaltung/);
assert.equal(describeUpdate({ ...data, updateAvailable: false }).notify, false);
assert.equal(describeUpdate({ ...data, restartRequired: true }).badge, "Neustart nötig");
'''.replace("MODULE", json.dumps(module))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_browser_shows_the_notice_and_opens_the_version_tab(repos, tmp_path, monkeypatch):
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    _, clone = repos
    monkeypatch.setattr(updates.workspace, "CODE_ROOT", clone)
    content = tmp_path / "content"
    content.mkdir()
    app = create_app(config=AppConfig(content))
    app.testing = True
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(url, wait_until="networkidle")
            notice = page.locator("#updateNotice")
            notice.wait_for()
            assert notice.inner_text().strip() == "Update 0.10.0"
            notice.click()
            page.locator("#updateApply").wait_for()
            assert page.locator("#updateCurrent").inner_text() == "0.9.0"
            page.screenshot(path=os.environ.get("UPDATE_SCREENSHOT") or tmp_path / "update.png")
            page.locator("#updateDismiss").click()
            assert notice.is_hidden()
            browser.close()
    finally:
        app.extensions["material_runtime"].close()
