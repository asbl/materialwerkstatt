"""Moodle-Ziele in der Kurs-Sync-Ansicht: URL in YAML, Zugangsdaten in .env."""

from __future__ import annotations

import os

import pytest

from material_core.dotenv import format_dotenv_value, load_dotenv_file, set_dotenv_values
from material_ui.errors import InvalidInput
from material_ui.plugins.kurse.adapter import CourseAdapter
from material_ui.plugins.kurse.targets import MoodleTargets, normalize_course_url, validate_target_name


URL = "https://neu.example.org/course/view.php?id=42"
ENV_KEYS = [
    "MOODLE_PYTHON_2026_NEU_COURSE_URL", "MOODLE_PYTHON_2026_NEU_USERNAME", "MOODLE_PYTHON_2026_NEU_PASSWORD",
    "MOODLE_PYTHON_2026_USERNAME", "MOODLE_PYTHON_2026_PASSWORD", "MOODLE_USERNAME", "MOODLE_PASSWORD",
]


@pytest.fixture
def targets(tmp_path, monkeypatch):
    # Eigene Kopie, damit os.environ.update() der Speicherroutine nicht in andere Tests leckt.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    course_dir = tmp_path / "unterricht" / "kurse" / "python-2026"
    course_dir.mkdir(parents=True)
    (course_dir / "index.mdx").write_text("# Kurs\n", encoding="utf-8")
    return MoodleTargets(tmp_path, CourseAdapter(tmp_path)), course_dir


def read_env(path):
    values: dict[str, str] = {}
    load_dotenv_file(path, values)
    return values


def test_set_dotenv_values_keeps_comments_and_replaces_in_place(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# Kommentar\nA=1\n\nB=2\n", encoding="utf-8")
    path.chmod(0o640)
    set_dotenv_values(path, {"B": "neu", "C": "3"})
    assert path.read_text(encoding="utf-8") == "# Kommentar\nA=1\n\nB=neu\nC=3\n"
    assert path.stat().st_mode & 0o777 == 0o640


def test_set_dotenv_values_creates_private_file(tmp_path):
    path = tmp_path / ".env"
    set_dotenv_values(path, {"A": "1"})
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("value", ["einfach", " mit Rand ", "'quoted'x", '"x"', "a #b", "back\\slash", "dollar$x", 'say "hi"'])
def test_dotenv_values_survive_the_project_parser(tmp_path, value):
    if value in {"'quoted'x"}:
        with pytest.raises(ValueError):
            format_dotenv_value(value)
        return
    path = tmp_path / ".env"
    set_dotenv_values(path, {"K": value})
    assert read_env(path)["K"] == value


def test_dotenv_rejects_newlines(tmp_path):
    with pytest.raises(ValueError):
        set_dotenv_values(tmp_path / ".env", {"K": "a\nb"})


@pytest.mark.parametrize("url", ["", "ftp://x/course/view.php?id=1", "https://x/course/view.php", "https://x/course/view.php?id=abc", "https://x/ y?id=1", "moodle.example"])
def test_normalize_course_url_rejects(url):
    with pytest.raises(InvalidInput):
        normalize_course_url(url)


def test_normalize_course_url_accepts():
    assert normalize_course_url(f"  {URL} ") == URL


@pytest.mark.parametrize("name", ["", "-x", "a b", "a/b", "../x", "x" * 41])
def test_validate_target_name_rejects(name):
    with pytest.raises(InvalidInput):
        validate_target_name(name)


def test_create_writes_yaml_and_env_and_never_returns_password(targets):
    service, course_dir = targets
    result = service.save(course_dir, "neu", {"courseUrl": URL, "username": "lehrer", "password": "geheim 1"}, create=True)

    assert "geheim" not in repr(result)
    assert result["courseUrl"] == URL
    assert result["urlSource"] == "yml"
    assert result["auth"] == "credentials"
    assert result["username"] == "lehrer"
    assert result["passwordSet"] is True
    assert (course_dir / ".moodle-target-neu.yml").read_text(encoding="utf-8") == f"course_url: {URL}\nauth: credentials\n"
    env = read_env(service.dotenv_path)
    assert env["MOODLE_PYTHON_2026_NEU_USERNAME"] == "lehrer"
    assert env["MOODLE_PYTHON_2026_NEU_PASSWORD"] == "geheim 1"
    # Die laufende UI und ihre Unterprozesse sehen die Werte sofort.
    assert os.environ["MOODLE_PYTHON_2026_NEU_PASSWORD"] == "geheim 1"
    assert "neu" in service.names(course_dir)


def test_create_twice_and_update_unknown_fail(targets):
    service, course_dir = targets
    service.save(course_dir, "neu", {"courseUrl": URL}, create=True)
    with pytest.raises(InvalidInput):
        service.save(course_dir, "neu", {"courseUrl": URL}, create=True)
    with pytest.raises(InvalidInput):
        service.save(course_dir, "anders", {"courseUrl": URL}, create=False)


def test_update_keeps_comments_other_keys_and_stored_password(targets, monkeypatch):
    service, course_dir = targets
    config = course_dir / ".moodle-target-neu.yml"
    config.write_text("# Nicht geheim\nauth: sso\nnotes: \"Schulportal\"\ncourse_url: https://alt.example/course/view.php?id=1\n", encoding="utf-8")
    set_dotenv_values(service.dotenv_path, {"MOODLE_PYTHON_2026_NEU_PASSWORD": "bleibt"})
    monkeypatch.setenv("MOODLE_PYTHON_2026_NEU_PASSWORD", "bleibt")

    result = service.save(course_dir, "neu", {"courseUrl": URL, "password": ""}, create=False)

    text = config.read_text(encoding="utf-8")
    assert "# Nicht geheim" in text and 'notes: "Schulportal"' in text and "auth: sso" in text
    assert f"course_url: {URL}" in text
    assert result["auth"] == "sso"
    assert read_env(service.dotenv_path)["MOODLE_PYTHON_2026_NEU_PASSWORD"] == "bleibt"


def test_keep_secrets_roundtrip(targets):
    service, course_dir = targets
    config = course_dir / ".moodle-target-schule.yml"
    config.write_text("# Kommentar\ncourse_url: https://schule.example/course/view.php?id=7\n", encoding="utf-8")

    assert service.describe(course_dir, "schule")["keepSecrets"] is False

    result = service.save(course_dir, "schule", {"courseUrl": "https://schule.example/course/view.php?id=7", "keepSecrets": True}, create=False)
    text = config.read_text(encoding="utf-8")
    assert "# Kommentar" in text and "keep_secrets: true" in text
    assert result["keepSecrets"] is True

    # Ohne keepSecrets in der Anfrage bleibt der Wert erhalten.
    service.save(course_dir, "schule", {"courseUrl": "https://schule.example/course/view.php?id=7"}, create=False)
    assert "keep_secrets: true" in config.read_text(encoding="utf-8")

    result = service.save(course_dir, "schule", {"courseUrl": "https://schule.example/course/view.php?id=7", "keepSecrets": False}, create=False)
    assert "keep_secrets: false" in config.read_text(encoding="utf-8")
    assert result["keepSecrets"] is False


def test_save_rejects_non_boolean_keep_secrets(targets):
    service, course_dir = targets
    with pytest.raises(InvalidInput):
        service.save(course_dir, "neu", {"courseUrl": URL, "keepSecrets": "ja"}, create=True)
    assert not (course_dir / ".moodle-target-neu.yml").exists()


def test_update_follows_target_specific_env_url(targets, monkeypatch):
    service, course_dir = targets
    (course_dir / ".moodle-target-neu.yml").write_text("auth: credentials\n", encoding="utf-8")
    set_dotenv_values(service.dotenv_path, {"MOODLE_PYTHON_2026_NEU_COURSE_URL": "https://alt.example/course/view.php?id=1"})
    monkeypatch.setenv("MOODLE_PYTHON_2026_NEU_COURSE_URL", "https://alt.example/course/view.php?id=1")

    result = service.save(course_dir, "neu", {"courseUrl": URL}, create=False)

    assert result["courseUrl"] == URL and result["urlSource"] == "env"
    assert read_env(service.dotenv_path)["MOODLE_PYTHON_2026_NEU_COURSE_URL"] == URL


def test_describe_reports_fallback_credentials_without_values_leaking(targets, monkeypatch):
    service, course_dir = targets
    (course_dir / ".moodle-target-neu.yml").write_text(f"course_url: {URL}\n", encoding="utf-8")
    monkeypatch.setenv("MOODLE_PYTHON_2026_USERNAME", "kursnutzer")
    monkeypatch.setenv("MOODLE_PASSWORD", "global-geheim")

    info = service.describe(course_dir, "neu")

    assert info["usernameSource"] == "course" and info["username"] == "kursnutzer"
    assert info["passwordSet"] is True and info["passwordSource"] == "global"
    assert "global-geheim" not in repr(info)


def test_save_rejects_unknown_auth_and_bad_credentials(targets):
    service, course_dir = targets
    with pytest.raises(InvalidInput):
        service.save(course_dir, "neu", {"courseUrl": URL, "auth": "magie"}, create=True)
    with pytest.raises(InvalidInput):
        service.save(course_dir, "neu", {"courseUrl": URL, "username": "a\nb"}, create=True)
    assert not (course_dir / ".moodle-target-neu.yml").exists()


def test_target_routes_create_list_update(tmp_path, monkeypatch):
    import material_ui.app as material_app

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(material_app, "ROOT", tmp_path)
    course_dir = tmp_path / "unterricht" / "kurse" / "kurs-a"
    (course_dir / "chapters").mkdir(parents=True)
    (course_dir / "index.mdx").write_text('# Kurs A\n\n<Chapter src="./chapters/k1.mdx" title="Kapitel 1" />\n', encoding="utf-8")
    (course_dir / "chapters" / "k1.mdx").write_text("# Kapitel 1\n", encoding="utf-8")
    app = material_app.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    base = "/api/kurse/kurs-a/moodle/targets"
    try:
        created = client.post(base, json={"target": "schule2", "courseUrl": URL, "username": "u", "password": "p"})
        assert created.status_code == 201
        payload = created.get_json()
        assert payload["target"]["passwordSet"] is True and "p" not in payload["target"].get("password", "")
        assert [item["target"] for item in payload["targets"]] == ["schule2"]
        assert read_env(tmp_path / ".env")["MOODLE_KURS_A_SCHULE2_USERNAME"] == "u"

        assert client.post(base, json={"target": "schule2", "courseUrl": URL}).status_code == 400
        assert client.post(base, json={"target": "../x", "courseUrl": URL}).status_code == 400
        assert client.post(base, json={"target": "ok", "courseUrl": "kein-link"}).status_code == 400

        updated = client.put(f"{base}/schule2", json={"target": "schule2", "courseUrl": "https://z.example/course/view.php?id=9"})
        assert updated.status_code == 200
        assert updated.get_json()["target"]["courseUrl"] == "https://z.example/course/view.php?id=9"
        assert client.put(f"{base}/gibtsnicht", json={"courseUrl": URL}).status_code == 400
        assert client.get("/api/kurse/unbekannt/moodle/targets").status_code == 400

        overview = client.get("/api/kurse/sync-overview?refresh=1").get_json()
        platforms = overview["courses"][0]["platforms"]
        assert [item["target"] for item in platforms if item["target"]] == ["schule2"]
        assert platforms[0]["host"] == "z.example"
    finally:
        app.extensions["material_runtime"].close()


def test_browser_adds_and_edits_target_in_sync_view(tmp_path, monkeypatch):
    sync_api = pytest.importorskip("playwright.sync_api")
    import material_ui.app as material_app
    from test_material_ui import LiveServer, free_port

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(material_app, "ROOT", tmp_path)
    course_dir = tmp_path / "unterricht" / "kurse" / "kurs-a"
    (course_dir / "chapters").mkdir(parents=True)
    (course_dir / "index.mdx").write_text('# Kurs A\n\n<Chapter src="./chapters/k1.mdx" title="Kapitel 1" />\n', encoding="utf-8")
    (course_dir / "chapters" / "k1.mdx").write_text("# Kapitel 1\n", encoding="utf-8")
    app = material_app.create_app()
    try:
        with LiveServer(app, free_port()) as url, sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script('localStorage.setItem("material-ui:auto-render", "false")')
            page.goto(url, wait_until="networkidle")
            page.locator("#viewButton-kurse-sync").click()
            page.wait_for_selector("#viewSection-kurse-sync [data-target-add]")

            page.locator("[data-target-add]").click()
            form = page.locator("[data-target-form]")
            form.wait_for()
            form.locator("[name=target]").fill("schule2")
            form.locator("[name=courseUrl]").fill("kein-link")
            form.locator("button[type=submit]").click()
            # Keine gueltige URL: der Browser verhindert das Absenden.
            assert form.locator("[name=courseUrl]").evaluate("element => !element.validity.valid")
            assert not (course_dir / ".moodle-target-schule2.yml").exists()

            # Gueltige URL ohne Kurs-ID: die Ablehnung des Servers erscheint im Formular.
            form.locator("[name=courseUrl]").fill("https://neu.example.org/course/view.php")
            form.locator("button[type=submit]").click()
            page.wait_for_function("document.querySelector('[data-target-error]').textContent.includes('Kurs-ID')")
            assert form.locator("button[type=submit]").is_enabled()
            assert not (course_dir / ".moodle-target-schule2.yml").exists()

            form.locator("[name=courseUrl]").fill(URL)
            form.locator("summary").click()
            assert form.locator("[name=password]").get_attribute("type") == "password"
            form.locator("[name=username]").fill("lehrer")
            form.locator("[name=password]").fill("geheim")
            form.locator("button[type=submit]").click()
            page.wait_for_selector("[data-target-edit=schule2]")
            assert page.locator("[data-target-form]").count() == 0
            assert "neu.example.org" in page.locator("#viewSection-kurse-sync").inner_text()
            assert (course_dir / ".moodle-target-schule2.yml").is_file()
            assert read_env(tmp_path / ".env")["MOODLE_KURS_A_SCHULE2_PASSWORD"] == "geheim"

            page.locator("[data-target-edit=schule2]").click()
            form = page.locator("[data-target-form]")
            form.wait_for()
            assert form.locator("[name=target]").get_attribute("readonly") is not None
            assert form.locator("[name=courseUrl]").input_value() == URL
            assert form.locator("[name=username]").input_value() == "lehrer"
            assert form.locator("[name=password]").input_value() == ""
            assert "geheim" not in page.content()
            form.locator("[name=courseUrl]").fill("https://zwei.example.org/course/view.php?id=3")
            form.locator("button[type=submit]").click()
            page.wait_for_function("document.querySelector('#viewSection-kurse-sync').innerText.includes('zwei.example.org')")
            assert read_env(tmp_path / ".env")["MOODLE_KURS_A_SCHULE2_PASSWORD"] == "geheim"
            browser.close()
    finally:
        app.extensions["material_runtime"].close()
