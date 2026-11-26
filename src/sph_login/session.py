from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

LOGIN = "https://login.schulportal.hessen.de/"
CONNECT = "https://connect.schulportal.hessen.de/"


class AuthenticationError(RuntimeError):
    """Login failed, expired, or returned an unsupported response."""


class InteractionRequired(AuthenticationError):
    """Continue interactively using the pending cookies and optional URL.

    The URL may contain transient tokens; do not log it.
    """

    def __init__(self, message: str, *, continuation_url: str | None = None) -> None:
        super().__init__(message)
        self.continuation_url = continuation_url


@dataclass(frozen=True)
class Credentials:
    school_id: str
    username: str
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        if not str(self.school_id).isdigit() or not self.username or not self.password:
            raise ValueError("Schul-ID, Benutzername und Passwort sind erforderlich.")
        object.__setattr__(self, "school_id", str(self.school_id))


def _portal_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.port not in (None, 443)
            or parsed.username or parsed.password
            or not (host == "schulportal.hessen.de" or host.endswith(".schulportal.hessen.de"))):
        raise AuthenticationError("Unerwartetes Weiterleitungsziel bei der SPH-Anmeldung.")
    return url


class SphSession:
    """Owns one account's HTTP cookie jar. No threads or automatic task retries.

    ``login`` prepares SSO cookies; the target must verify authentication.
    LANiS is optional via ``connect_lanis``. Call ``login(force=True)`` to refresh
    a rejected cached SSO session, before starting any tasks.
    """

    def __init__(self, credentials: Credentials, *, state_path: Path | None = None,
                 timeout: float = 30, transport: httpx.BaseTransport | None = None) -> None:
        self.credentials = credentials
        self.state_path = Path(state_path) if state_path else None
        self.client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=False,
                                   headers={"User-Agent": "sph-login/0.1"})
        self._last_keepalive = float("-inf")

    def connect_lanis(self) -> SphSession:
        """Open and validate a LANiS session, independently of SSO preparation."""
        try:
            self._connect()
            self.save()
            return self
        except httpx.HTTPError:
            raise AuthenticationError("LANiS-Verbindung wegen eines HTTP-Fehlers fehlgeschlagen.") from None

    def _connect(self) -> None:
        # Clear LANiS sid first: an old cookie must not prove a new login succeeded.
        for cookie in list(self.client.cookies.jar):
            if cookie.name == "sid":
                self.client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
        url = CONNECT
        for _ in range(10):
            response = self.client.get(_portal_url(url))
            if response.status_code in (401, 403):
                raise AuthenticationError("SPH-Sitzung ist abgelaufen oder nicht berechtigt.")
            if not response.is_redirect:
                response.raise_for_status()
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise AuthenticationError("SPH-Weiterleitung ohne Ziel.")
                url = urljoin(str(response.url), location)
                _portal_url(url)
                if urlparse(url).hostname == "login.schulportal.hessen.de":
                    raise InteractionRequired("SPH verlangt einen weiteren Anmeldeschritt.",
                                              continuation_url=url)
                continue
            if any(c.name == "sid" and c.value and not c.is_expired()
                   for c in self.client.cookies.jar):
                self.client.cookies.set("i", self.credentials.school_id,
                                        domain="start.schulportal.hessen.de", path="/")
                for cookie in self.client.cookies.jar:
                    if cookie.name == "i":
                        cookie.secure = True
                return
            raise AuthenticationError("LANiS lieferte keine Sitzung. SSO-Cookies bleiben erhalten.")
        raise AuthenticationError("Zu viele SPH-Weiterleitungen.")

    def _has_sso_cookie(self) -> bool:
        return any(c.name == "SPH-Session" and c.value and not c.is_expired()
                   for c in self.client.cookies.jar)

    def login(self, *, force: bool = False) -> SphSession:
        """Prepare SSO cookies, without requiring LANiS access.

        A cookie is not proof of completed authentication. Consumers must check
        their target, refreshing a rejected cache once before executing tasks.
        InteractionRequired preserves pending cookies for browser continuation.
        """
        try:
            if not force and self._load() and self._has_sso_cookie():
                return self
            self.client.cookies.clear()
            response = self.client.post(LOGIN, params={"i": self.credentials.school_id}, data={
                "user2": self.credentials.username,
                "user": f"{self.credentials.school_id}.{self.credentials.username}",
                "password": self.credentials.password,
            })
            if response.status_code in (401, 403):
                raise AuthenticationError("SPH hat die Zugangsdaten abgelehnt.")
            if not response.is_redirect:
                response.raise_for_status()
            location = response.headers.get("location")
            continuation = _portal_url(urljoin(str(response.url), location)) if location else None
            if not self._has_sso_cookie() or not response.is_redirect:
                raise InteractionRequired("SPH verlangt eine interaktive Anmeldung.",
                                          continuation_url=continuation)
            if urlparse(continuation or "").hostname == "login.schulportal.hessen.de":
                raise InteractionRequired("SPH verlangt einen weiteren Anmeldeschritt.",
                                          continuation_url=continuation)
            self.save()
            return self
        except InteractionRequired:
            raise
        except httpx.HTTPError:
            self.client.cookies.clear()
            raise AuthenticationError("SPH-Anmeldung wegen eines Netzwerk- oder HTTP-Fehlers fehlgeschlagen.") from None
        except AuthenticationError:
            self.client.cookies.clear()
            raise

    def keepalive(self, *, interval: float = 60) -> bool:
        """Send a LANiS keepalive (True), or skip due to rate limiting (False).

        True means the request was sent without a recognized error, not proof
        that the server renewed the session. Unknown response bodies are allowed
        because the endpoint's full protocol has not been verified live.
        """
        if interval < 10:
            raise ValueError("Keepalive-Intervall muss mindestens 10 Sekunden betragen.")
        now = time.monotonic()
        if now - self._last_keepalive < interval:
            return False
        token = next((c.value for c in self.client.cookies.jar
                      if c.name == "sid" and not c.is_expired()), None)
        if not token:
            raise AuthenticationError("Keine aktive LANiS-Sitzung.")
        try:
            response = self.client.post("https://start.schulportal.hessen.de/ajax_login.php",
                                        data={"name": token},
                                        headers={"X-Requested-With": "XMLHttpRequest"})
            response.raise_for_status()
        except httpx.HTTPError:
            raise AuthenticationError("SPH-Keepalive fehlgeschlagen.") from None
        if response.is_redirect or "text/html" in response.headers.get("content-type", ""):
            raise AuthenticationError("SPH-Keepalive verlangt erneute Anmeldung.")
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and (
            payload.get("success") is False or payload.get("ok") is False or payload.get("error")
        ):
            raise AuthenticationError("LANiS-Keepalive meldet einen Fehler.")
        self._last_keepalive = now
        return True

    def browser_cookies(self) -> list[dict[str, Any]]:
        """Cookies for Playwright BrowserContext.add_cookies; preserves scope/flags."""
        result = []
        for cookie in self.client.cookies.jar:
            if cookie.is_expired():
                continue
            item: dict[str, Any] = {
                "name": cookie.name, "value": cookie.value, "domain": cookie.domain,
                "path": cookie.path or "/", "secure": cookie.secure,
                "httpOnly": cookie.has_nonstandard_attr("HttpOnly"),
            }
            if cookie.expires is not None:
                item["expires"] = cookie.expires
            same_site = cookie.get_nonstandard_attr("SameSite")
            if same_site and same_site.lower() in ("lax", "strict", "none"):
                item["sameSite"] = same_site.capitalize()
            result.append(item)
        return result

    def install_in_browser(self, context: Any) -> None:
        """Seed a browser; the consumer then opens its own SSO-protected target."""
        context.add_cookies(self.browser_cookies())

    def save(self) -> None:
        if self.state_path is None:
            return
        data = {"version": 1, "school_id": self.credentials.school_id,
                "username": self.credentials.username,
                "cookies": [vars(c) for c in self.client.cookies.jar]}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.state_path.parent, prefix=".sph-state-")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream)
            os.replace(temporary, self.state_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load(self) -> bool:
        if not self.state_path or not self.state_path.exists():
            return False
        try:
            data = json.loads(self.state_path.read_text())
            if (data["version"] != 1 or data["school_id"] != self.credentials.school_id
                    or data["username"] != self.credentials.username):
                return False
            jar = httpx.Cookies()
            for raw in data["cookies"]:
                raw = dict(raw)
                raw["rest"] = raw.pop("_rest", {})
                cookie = Cookie(**raw)
                host = cookie.domain.lstrip(".")
                if not (host == "hessen.de" or host.endswith(".hessen.de")):
                    return False
                if not cookie.is_expired():
                    jar.jar.set_cookie(cookie)
            self.client.cookies = jar
            return bool(list(jar.jar))
        except (ValueError, KeyError, TypeError, AttributeError):
            return False

    def close(self) -> None:
        """Close local connections without invalidating other SPH/Moodle sessions."""
        self.client.close()

    def __enter__(self) -> SphSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
