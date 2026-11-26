"""Moodle-Ziele eines Kurses verwalten (Kurs-Sync-Ansicht).

Ein Ziel ist ein benannter Moodle-Kurs, gegen den derselbe lokale Kurs synchronisiert
wird. Die nicht geheimen Angaben (Kurs-URL, Anmeldeart, ``keep_secrets``) stehen in
``<kurs>/.moodle-target-<ziel>.yml`` und werden mit dem Kurs im privaten Inhalts-Repo
versioniert. Zugangsdaten bleiben in der lokalen, ignorierten ``.env``
(``MOODLE_<KURS>_<ZIEL>_USERNAME`` / ``_PASSWORD``); die Oberflaeche liefert Passwoerter
nie zurueck, sie zeigt nur, ob eines gesetzt ist.

``keep_secrets: true`` haelt die in ``course.yml`` definierten Secrets (z. B. echte
Namen) auf diesem Ziel im Klartext; ohne die Angabe werden sie durch neutrale Namen
ersetzt (siehe course_sync.classes.course_secrets).
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from material_core.dotenv import read_dotenv_values, set_dotenv_values
from material_ui.errors import InvalidInput


TARGET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}")
TARGET_FILE_PREFIX = ".moodle-target-"
TARGET_FILE_SUFFIX = ".yml"

# Anmeldearten; die ersten drei lesen Benutzername und Passwort aus der .env.
AUTH_MODES = {
    "credentials": "Moodle-Login mit Benutzername und Passwort",
    "sso": "Einmalanmeldung (SSO) mit Benutzername und Passwort",
    "schulportal-hessen": "Schulportal Hessen",
    "manual": "Ohne gespeicherte Zugangsdaten (Anmeldung im Browser)",
}
DEFAULT_AUTH = "credentials"
CREDENTIAL_AUTH_MODES = {"credentials", "sso", "schulportal", "schulportal-hessen"}


def normalize_course_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        raise InvalidInput("Die Kurs-URL fehlt.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or any(char.isspace() for char in url):
        raise InvalidInput("Die Kurs-URL muss mit https:// beginnen, z. B. https://moodle.example/course/view.php?id=12.")
    course_id = parse_qs(parsed.query).get("id", [""])[0]
    if not course_id.isdigit():
        raise InvalidInput("In der Kurs-URL fehlt die Kurs-ID (…/course/view.php?id=12).")
    return url


def validate_target_name(value: Any) -> str:
    name = str(value or "").strip()
    if not TARGET_NAME.fullmatch(name):
        raise InvalidInput("Der Zielname darf nur Buchstaben, Ziffern, „-“ und „_“ enthalten (höchstens 40 Zeichen).")
    return name


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "on"}
    return bool(value)


class MoodleTargets:
    """Liest und schreibt Ziel-Konfiguration eines Kurses und die zugehoerigen .env-Eintraege."""

    def __init__(self, root: Path, adapter) -> None:
        self.root = root
        self.adapter = adapter
        self._lock = threading.Lock()

    @property
    def dotenv_path(self) -> Path:
        return self.root / ".env"

    def target_path(self, course_dir: Path, target: str) -> Path:
        return course_dir / f"{TARGET_FILE_PREFIX}{target}{TARGET_FILE_SUFFIX}"

    # -- Lesen ------------------------------------------------------------------

    def names(self, course_dir: Path) -> list[str]:
        found = {
            path.name.removeprefix(TARGET_FILE_PREFIX).removesuffix(TARGET_FILE_SUFFIX)
            for path in course_dir.glob(f"{TARGET_FILE_PREFIX}*{TARGET_FILE_SUFFIX}")
        }
        return sorted(name for name in found if TARGET_NAME.fullmatch(name))

    def list(self, course_dir: Path) -> dict[str, Any]:
        return {
            "targets": [self.describe(course_dir, name) for name in self.names(course_dir)],
            "authModes": [{"id": key, "label": label} for key, label in AUTH_MODES.items()],
            "envFile": self.dotenv_path.name,
        }

    def describe(self, course_dir: Path, target: str) -> dict[str, Any]:
        application = self.adapter.application()
        config = application._load_target_config(course_dir, target)
        file_values = read_dotenv_values(self.dotenv_path)

        def lookup(key: str) -> str:
            return (os.environ.get(key) or file_values.get(key) or "").strip()

        course_url_key = application._target_env_key(course_dir, target, "COURSE_URL")
        configured_url = str(config.get("course_url", config.get("courseUrl", "")) or "").strip()
        env_url = lookup(course_url_key)
        auth = str(config.get("auth") or DEFAULT_AUTH).strip().lower()

        def credential(suffix: str, fallback: str) -> dict[str, Any]:
            own_key = application._target_env_key(course_dir, target, suffix)
            sources = (
                ("target", own_key),
                ("course", application._course_env_key(course_dir, suffix)),
                ("global", fallback),
            )
            for source, key in sources:
                value = lookup(key)
                if value:
                    return {"key": own_key, "value": value, "source": source, "sourceKey": key}
            return {"key": own_key, "value": "", "source": "", "sourceKey": own_key}

        username = credential("USERNAME", "MOODLE_USERNAME")
        password = credential("PASSWORD", "MOODLE_PASSWORD")
        return {
            "target": target,
            "courseUrl": env_url or configured_url,
            "urlSource": "env" if env_url else ("yml" if configured_url else ""),
            "urlEnvKey": course_url_key,
            "auth": auth,
            "usesCredentials": auth in CREDENTIAL_AUTH_MODES,
            "keepSecrets": _as_bool(config.get("keep_secrets", config.get("keepSecrets", False))),
            "username": username["value"],
            "usernameSource": username["source"],
            "usernameKey": username["key"],
            "passwordSet": bool(password["value"]),
            "passwordSource": password["source"],
            "passwordKey": password["key"],
            "configFile": self.target_path(course_dir, target).name,
        }

    # -- Schreiben --------------------------------------------------------------

    def save(self, course_dir: Path, target: Any, data: dict[str, Any], *, create: bool) -> dict[str, Any]:
        target = validate_target_name(target)
        course_url = normalize_course_url(data.get("courseUrl"))
        auth = str(data.get("auth") or "").strip().lower()
        config_path = self.target_path(course_dir, target)
        existing = config_path.is_file()
        if not existing and not create:
            raise InvalidInput(f"Unbekanntes Ziel: {target}")
        if create and existing:
            raise InvalidInput(f"Das Ziel „{target}“ gibt es für diesen Kurs bereits.")
        if auth and auth not in AUTH_MODES:
            raise InvalidInput("Unbekannte Anmeldeart.")
        keep_secrets = data.get("keepSecrets")
        if keep_secrets is not None and not isinstance(keep_secrets, bool):
            raise InvalidInput("keepSecrets muss true oder false sein.")
        username = self._optional_text(data.get("username"), "Benutzername")
        password = self._optional_text(data.get("password"), "Passwort", strip=False)

        application = self.adapter.application()
        env_updates: dict[str, str] = {}
        if username:
            env_updates[application._target_env_key(course_dir, target, "USERNAME")] = username
        if password:
            env_updates[application._target_env_key(course_dir, target, "PASSWORD")] = password
        # Eine zielspezifische COURSE_URL-Variable ueberstimmt die YAML-Datei; sie muss
        # dann mitgefuehrt werden, sonst bliebe die Eingabe wirkungslos.
        url_key = application._target_env_key(course_dir, target, "COURSE_URL")
        with self._lock:
            if url_key in read_dotenv_values(self.dotenv_path) or os.environ.get(url_key):
                env_updates[url_key] = course_url
            self._write_config(config_path, course_url, auth or (None if existing else DEFAULT_AUTH), keep_secrets)
            if env_updates:
                try:
                    set_dotenv_values(self.dotenv_path, env_updates)
                except (OSError, ValueError) as error:
                    raise InvalidInput(f"Zugangsdaten konnten nicht in .env gespeichert werden: {error}") from error
                # Die laufende Material-UI hat .env beim Start gelesen; ihre Unterprozesse
                # erben os.environ und braeuchten sonst einen Neustart.
                os.environ.update(env_updates)
        return self.describe(course_dir, target)

    @staticmethod
    def _optional_text(value: Any, label: str, *, strip: bool = True) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise InvalidInput(f"{label} muss als Text angegeben werden.")
        text = value.strip() if strip else value
        if len(text) > 512:
            raise InvalidInput(f"{label} ist zu lang.")
        if "\n" in text or "\r" in text or "\0" in text:
            raise InvalidInput(f"{label} darf keine Zeilenumbrüche enthalten.")
        return text

    @staticmethod
    def _write_config(path: Path, course_url: str, auth: str | None, keep_secrets: bool | None = None) -> None:
        """Schreibt course_url (und auth/keep_secrets) und erhaelt Kommentare und uebrige Schluessel."""
        from ruamel.yaml import YAML

        yaml = YAML()
        yaml.preserve_quotes = True
        document = None
        if path.is_file():
            document = yaml.load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            document = yaml.map()
        url_key = "courseUrl" if "courseUrl" in document and "course_url" not in document else "course_url"
        document[url_key] = course_url
        if auth:
            document["auth"] = auth
        if keep_secrets is not None:
            document["keep_secrets"] = bool(keep_secrets)
        temp = path.with_name(path.name + ".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            yaml.dump(document, handle)
        os.replace(temp, path)
