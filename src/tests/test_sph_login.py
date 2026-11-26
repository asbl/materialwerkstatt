import json
import stat
from unittest.mock import Mock, call, patch
from urllib.parse import parse_qs

import httpx
import pytest

pytest.importorskip("sph_login", reason="optionales Paket sph-login (pip install -e src/sph_login)")

from sph_login import AuthenticationError, Credentials, InteractionRequired, SphSession
from course_sync.classes.moodle_playwright_uploader import MoodlePlaywrightUploader


CREDS = Credentials("1234", "alice", "very-secret")


def handler(request):
    if request.url.host == "login.schulportal.hessen.de":
        assert request.method == "POST"
        assert parse_qs(request.content.decode()) == {
            "user": ["1234.alice"], "user2": ["alice"], "password": ["very-secret"]}
        return httpx.Response(302, headers={
            "set-cookie": "SPH-Session=sso; Domain=.hessen.de; Path=/; Secure; HttpOnly; SameSite=Lax",
            "location": "https://connect.schulportal.hessen.de/"})
    if request.url.host == "connect.schulportal.hessen.de":
        assert "SPH-Session=sso" in request.headers["cookie"]
        return httpx.Response(302, headers={"location": "https://start.schulportal.hessen.de/session"})
    if request.url.path == "/session":
        return httpx.Response(200, headers={
            "set-cookie": "sid=lanis; Path=/; Secure; HttpOnly"})
    if request.url.path == "/ajax_login.php":
        assert parse_qs(request.content.decode()) == {"name": ["lanis"]}
        return httpx.Response(200, json={"ok": True})
    raise AssertionError(str(request.url))


def session(**kwargs):
    return SphSession(CREDS, transport=httpx.MockTransport(handler), **kwargs)


def test_login_and_browser_bridge_preserve_scopes():
    with session() as sph:
        assert sph.login() is sph
        context = Mock()
        sph.install_in_browser(context)
        cookies = context.add_cookies.call_args.args[0]
        sso = next(c for c in cookies if c["name"] == "SPH-Session")
        assert sso == {"name": "SPH-Session", "value": "sso", "domain": ".hessen.de",
                       "path": "/", "secure": True, "httpOnly": True, "sameSite": "Lax"}
        assert sph.client.is_closed is False
    assert sph.client.is_closed
    assert "very-secret" not in repr(CREDS)


def test_saved_session_validated_without_password_post(tmp_path):
    path = tmp_path / "session.json"
    with session(state_path=path) as sph:
        sph.login()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "very-secret" not in path.read_text()
    requests = []
    def restore(request):
        requests.append(request)
        assert request.url.host != "login.schulportal.hessen.de"
        return handler(request)
    with SphSession(CREDS, state_path=path, transport=httpx.MockTransport(restore)) as sph:
        sph.login().connect_lanis()
    assert requests


@pytest.mark.parametrize("contents", ["{", "[]", '{"version":2}', '{"version":1,"school_id":"other","username":"alice"}'])
def test_corrupt_or_wrong_account_cache_gets_fresh_login(tmp_path, contents):
    path = tmp_path / "session.json"
    path.write_text(contents)
    with session(state_path=path) as sph:
        sph.login()
    assert json.loads(path.read_text())["school_id"] == "1234"


def test_expired_cache_reauthenticates_once(tmp_path):
    path = tmp_path / "session.json"
    with session(state_path=path) as sph:
        sph.login()
    data = json.loads(path.read_text())
    for cookie in data["cookies"]:
        cookie["expires"] = 1
    path.write_text(json.dumps(data))
    calls = []
    def expired(request):
        calls.append(request)
        return handler(request)
    with SphSession(CREDS, state_path=path, transport=httpx.MockTransport(expired)) as sph:
        sph.login()
    assert sum(r.method == "POST" for r in calls) == 1


@pytest.mark.parametrize("target", ["http://start.schulportal.hessen.de/", "https://evil.test/", "https://schulportal.hessen.de.evil.test/", "https://login.schulportal.hessen.de/"])
def test_unexpected_redirects_rejected(target):
    visited = []
    def redirect(request):
        visited.append(request.url.host)
        if request.url.host == "connect.schulportal.hessen.de":
            return httpx.Response(302, headers={"location": target})
        return handler(request)
    with SphSession(CREDS, transport=httpx.MockTransport(redirect)) as sph:
        sph.login()
        with pytest.raises(AuthenticationError):
            sph.connect_lanis()
        assert any(c.name == "SPH-Session" for c in sph.client.cookies.jar)
    assert visited == ["login.schulportal.hessen.de", "connect.schulportal.hessen.de"]


def test_interaction_required_no_false_success():
    with SphSession(CREDS, transport=httpx.MockTransport(lambda r: httpx.Response(200, text="MFA"))) as sph:
        with pytest.raises(InteractionRequired):
            sph.login()


def test_network_error_redacted():
    def fail(request):
        raise httpx.ConnectError("secret redirect token", request=request)
    with SphSession(CREDS, transport=httpx.MockTransport(fail)) as sph:
        with pytest.raises(AuthenticationError) as exc:
            sph.login()
        assert "secret" not in str(exc.value)
        assert exc.value.__suppress_context__


def test_keepalive_explicit_rate_limited():
    with session() as sph:
        sph.login().connect_lanis()
        assert sph.keepalive()
        assert not sph.keepalive()
        with pytest.raises(ValueError):
            sph.keepalive(interval=1)


def test_moodle_uses_bridge_then_own_sso():
    page = Mock()
    page.url = "https://login.schulportal.hessen.de/"
    uploader = MoodlePlaywrightUploader(course_url="https://mo1234.schulportal.hessen.de/course/view.php?id=1",
                                       username="alice", password="very-secret", headless=True)
    with patch("sph_login.SphSession") as cls, \
         patch.object(uploader, "_goto_login_resilient") as navigate, \
         patch.object(uploader, "_login_is_required", return_value=False):
        uploader._login_with_schulportal_hessen_credentials(page)
        assert cls.call_args.args[0] == CREDS
        active = cls.return_value.__enter__.return_value
        active.login.assert_called_once_with()
        active.install_in_browser.assert_called_once_with(page.context)
        navigate.assert_called_once_with(page, uploader.course_url)


def test_moodle_headless_interaction_stops_before_tasks():
    uploader = MoodlePlaywrightUploader(course_url="https://mo1234.schulportal.hessen.de/course/view.php?id=1",
                                       username="alice", password="very-secret", headless=True)
    with patch("sph_login.SphSession") as cls:
        cls.return_value.__enter__.return_value.login.side_effect = InteractionRequired("MFA")
        with pytest.raises(InteractionRequired):
            uploader._login_with_schulportal_hessen_credentials(Mock())


def test_sso_login_does_not_require_or_contact_lanis():
    calls = []
    def only_sso(request):
        calls.append(request)
        assert request.url.host == "login.schulportal.hessen.de"
        return handler(request)
    with SphSession(CREDS, transport=httpx.MockTransport(only_sso)) as sph:
        sph.login()
        assert len(calls) == 1
        assert not any(c.name == "sid" for c in sph.client.cookies.jar)
        browser = Mock()
        sph.install_in_browser(browser)
        assert any(c["name"] == "SPH-Session" for c in browser.add_cookies.call_args.args[0])


def test_lanis_failure_does_not_discard_sso():
    def no_lanis(request):
        if request.url.host == "login.schulportal.hessen.de":
            return handler(request)
        return httpx.Response(200, text="LANiS unavailable")
    with SphSession(CREDS, transport=httpx.MockTransport(no_lanis)) as sph:
        sph.login()
        with pytest.raises(AuthenticationError, match="LANiS lieferte keine Sitzung"):
            sph.connect_lanis()
        assert any(c["name"] == "SPH-Session" for c in sph.browser_cookies())


def test_cached_sso_is_only_a_candidate_target_must_validate(tmp_path):
    path = tmp_path / "state.json"
    with session(state_path=path) as sph:
        sph.login()
    def no_http(request):
        pytest.fail("Loading SSO candidates must not contact LANiS")
    with SphSession(CREDS, state_path=path, transport=httpx.MockTransport(no_http)) as sph:
        sph.login()
        assert sph.browser_cookies()


@pytest.mark.parametrize("headless", [True, False])
def test_real_http_interactive_redirect_reaches_browser_or_stops(headless):
    def second_factor(request):
        return httpx.Response(302, headers={
            "set-cookie": "SPH-Session=pending; Domain=.hessen.de; Secure; Path=/",
            "location": "https://login.schulportal.hessen.de/second-factor"})
    uploader = MoodlePlaywrightUploader(course_url="https://mo1234.schulportal.hessen.de/course/view.php?id=1",
                                       username="alice", password="very-secret", headless=headless)
    page = Mock()
    with SphSession(CREDS, transport=httpx.MockTransport(second_factor)) as sph:
        with patch("sph_login.SphSession", return_value=sph), \
             patch.object(uploader, "_wait_for_sph_browser_login") as manual:
            if headless:
                with pytest.raises(InteractionRequired):
                    uploader._login_with_schulportal_hessen_credentials(page)
                manual.assert_not_called()
            else:
                uploader._login_with_schulportal_hessen_credentials(page)
                manual.assert_called_once_with(page, "https://login.schulportal.hessen.de/second-factor")
                assert any(c["value"] == "pending" for c in page.context.add_cookies.call_args.args[0])


def test_connect_login_redirect_is_interaction_required():
    def redirect(request):
        if request.url.host == "login.schulportal.hessen.de":
            return handler(request)
        return httpx.Response(302, headers={"location": "https://login.schulportal.hessen.de/second-factor"})
    with SphSession(CREDS, transport=httpx.MockTransport(redirect)) as sph:
        sph.login()
        with pytest.raises(InteractionRequired) as exc:
            sph.connect_lanis()
        assert exc.value.continuation_url.endswith("/second-factor")
        assert "SPH-Session" in {c["name"] for c in sph.browser_cookies()}


def test_moodle_rejects_cached_sso_and_refreshes_before_tasks():
    uploader = MoodlePlaywrightUploader(course_url="https://mo1234.schulportal.hessen.de/course/view.php?id=1",
                                       username="alice", password="very-secret", headless=True)
    with patch("sph_login.SphSession") as cls, \
         patch.object(uploader, "_goto_login_resilient"), \
         patch.object(uploader, "_login_is_required", side_effect=[True, False]):
        uploader._login_with_schulportal_hessen_credentials(Mock())
        active = cls.return_value.__enter__.return_value
        assert active.login.call_args_list == [call(), call(force=True)]
        assert active.install_in_browser.call_count == 2


def test_manual_continuation_waits_until_target_authenticated():
    uploader = MoodlePlaywrightUploader(course_url="https://mo1234.schulportal.hessen.de/course/view.php?id=1")
    page = Mock()
    page.url = "https://login.schulportal.hessen.de/second-factor"
    def finish(_):
        page.url = uploader.course_url
    page.wait_for_timeout.side_effect = finish
    with patch.object(uploader, "_goto_login_resilient") as navigate, \
         patch.object(uploader, "_login_is_required", return_value=False), \
         patch.object(uploader, "_looks_logged_in", return_value=False):
        uploader._wait_for_sph_browser_login(page, page.url)
        navigate.assert_called_once()
        page.wait_for_timeout.assert_called_once()


@pytest.mark.parametrize("payload", [{"success": False}, {"ok": False}, {"error": "session expired"}])
def test_keepalive_json_error_is_not_success(payload):
    replies = iter([payload, {"ok": True}])
    with SphSession(CREDS, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=next(replies)))) as sph:
        sph.client.cookies.set("sid", "lanis", domain="start.schulportal.hessen.de")
        with pytest.raises(AuthenticationError, match="meldet einen Fehler"):
            sph.keepalive()
        assert sph.keepalive() is True  # a failed attempt must not rate-limit recovery


def test_keepalive_unknown_body_means_only_request_sent():
    with SphSession(CREDS, transport=httpx.MockTransport(lambda r: httpx.Response(200, text=""))) as sph:
        sph.client.cookies.set("sid", "lanis", domain="start.schulportal.hessen.de")
        assert sph.keepalive() is True
