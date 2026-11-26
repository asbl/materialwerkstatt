"""Kurs-weite „Secrets" und deren Ersetzung auf Sync-Zielen.

Ein Kurs kann in ``course.yml`` ein ``secrets``-Mapping definieren, z. B. echte
Schuelernamen, die nur auf bestimmten Zielen (etwa dem Schulportal) im Klartext
sichtbar sein sollen::

    secrets:
      "Anna": "Person A"
      "Jonas": "Person B"

Auf jedem Moodle-Ziel, das die Secrets nicht explizit behaelt
(``keep_secrets: true`` in ``.moodle-target-<ziel>.yml``), werden die Secrets
beim Upload durch die neutralen Namen ersetzt -- sowohl in den H5P-Paketen als
auch in den Text-Labels. Der Kurs-Quellstand bleibt unveraendert; die Ersetzung
passiert nur fuer die an das Ziel hochgeladenen Inhalte.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

# Dateiendungen, deren Mitglieder eines H5P-Pakets als Text ersetzt werden.
TEXT_MEMBER_SUFFIXES = {
    ".json",
    ".html",
    ".htm",
    ".md",
    ".mdx",
    ".txt",
    ".js",
    ".mjs",
    ".css",
    ".xml",
    ".svg",
    ".csv",
    ".py",
    ".yaml",
    ".yml",
}

SECRETS_CONFIG_KEY = "secrets"
KEEP_SECRETS_CONFIG_KEY = "keep_secrets"
# Version des Sanitizers; landet im Cache-Hash, damit Aenderungen am Sanitizer
# (z. B. JSON-aware Ersetzung) vorhandene Kopien neu schreiben.
SANITIZER_VERSION = "2"


def load_course_secrets(course_dir: Path) -> dict[str, str]:
    """Liest das ``secrets``-Mapping aus ``<kurs>/course.yml`` (leer, wenn nicht definiert).

    Eintraege mit leerem Secret/Ersatz oder Secret == Ersatz werden ignoriert. Eine
    Ersetzung, die selbst Secret eines anderen Eintrags ist oder doppelt vorkommt,
    wird ebenfalls ignoriert, damit keine zwei Namen auf denselben Ersatz abgebildet
    werden.
    """
    config_path = course_dir / "course.yml"
    if not config_path.is_file():
        return {}
    import yaml

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    secrets = raw.get(SECRETS_CONFIG_KEY)
    if not isinstance(secrets, dict):
        return {}
    candidates: dict[str, str] = {}
    for secret, replacement in secrets.items():
        secret_text = str(secret).strip() if secret is not None else ""
        replacement_text = str(replacement).strip() if replacement is not None else ""
        if not secret_text or not replacement_text or secret_text == replacement_text:
            continue
        candidates[secret_text] = replacement_text
    replacements: dict[str, str] = {}
    used_replacements: set[str] = set()
    for secret_text, replacement_text in candidates.items():
        if replacement_text in candidates or replacement_text in used_replacements:
            continue
        replacements[secret_text] = replacement_text
        used_replacements.add(replacement_text)
    return replacements


def target_keeps_secrets(target_config: dict[str, object] | None) -> bool:
    """True, wenn das Ziel die Secrets im Klartext uebernimmt (``keep_secrets: true``)."""
    if not isinstance(target_config, dict):
        return False
    value = target_config.get(KEEP_SECRETS_CONFIG_KEY, target_config.get("keepSecrets", False))
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "on"}
    return bool(value)


def resolve_secret_replacements(
    course_dir: Path,
    target_config: dict[str, object] | None,
) -> dict[str, str]:
    """Ersetzungen fuer ein Ziel: alle Kurs-Secrets, sofern das Ziel sie nicht behaelt."""
    secrets = load_course_secrets(course_dir)
    if not secrets or target_keeps_secrets(target_config):
        return {}
    return secrets


def compile_secret_pattern(replacements: dict[str, str]) -> re.Pattern[str]:
    """Ein Muster, das jedes Secret als ganzes Wort (case-sensitiv) matcht.

    Laengere Secrets zuerst, damit bei ueberlappenden Namen (z. B. „Anna" und
    „Annabell") der laengste Treffer gewinnt. Grenzen ueber Lookarounds, damit
    auch Namen mit Sonderzeichen (z. B. „van der Berg") als Ganzes ersetzt werden.
    Gruppe 1 ist das Secret, Gruppe 2 ein optionaler Genitiv-s („Fenns"), der
    an die Ersetzung angehaengt wird.
    """
    ordered = sorted(replacements, key=len, reverse=True)
    alternatives = "|".join(re.escape(secret) for secret in ordered)
    return re.compile(rf"(?<!\w)({alternatives})(s?)(?!\w)")


def _replacer(replacements: dict[str, str]):
    def replace(match: re.Match[str]) -> str:
        return replacements[match.group(1)] + match.group(2)

    return replace


def apply_secret_replacements(text: str, replacements: dict[str, str]) -> str:
    """Ersetzt alle Secrets in ``text``; ausserhalb von Wortgrenzen und case-sensitiv.

    „Jonas'“ wird zu „<Ersatz>'“ (der Apostroph bleibt erhalten), „Fenns“ zu
    „<Ersatz>s“, „Annabell“ bleibt unveraendert, wenn nur „Anna“ ein Secret ist.
    """
    if not replacements or not text:
        return text
    return compile_secret_pattern(replacements).sub(_replacer(replacements), text)


def _is_text_member(name: str) -> bool:
    return Path(name).suffix.lower() in TEXT_MEMBER_SUFFIXES


def _replace_in_json(payload: object, pattern: re.Pattern[str], replace) -> object:
    """Ersetzt in allen String-Werten (und Keys) eines JSON-Dokuments.

    Die JSON-aware String-Ersetzung ist noetig, weil im rohen JSON-Text ein Name nach
    einem \\n-Escape steht und dort das vorherige Zeichen „n“ ein Wortzeichen ist –
    eine reine Text-Ersetzung wuerde den Namen dort nicht finden.
    """
    if isinstance(payload, dict):
        return {
            _replace_in_json(key, pattern, replace): _replace_in_json(value, pattern, replace)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_replace_in_json(item, pattern, replace) for item in payload]
    if isinstance(payload, str):
        return pattern.sub(replace, payload)
    return payload


def sanitize_h5p_package(source_path: Path, replacements: dict[str, str], dest_path: Path) -> Path:
    """Schreibt eine Kopie des H5P-Pakets, in der alle Text-Mitglieder ersetzt werden.

    Binaere Mitglieder (Bilder, Audio, …) werden 1:1 kopiert. JSON-Mitglieder werden
    geparst und in ihren String-Werten ersetzt (siehe ``_replace_in_json``), uebrige
    Text-Mitglieder per Regex. Das Ziel wird nur neu geschrieben, wenn sich der
    Quell-Hash oder das Ersetzungs-Mapping geaendert hat; der kombinierte Hash liegt
    als Sidecar neben der Zieldatei.
    """
    digest = hashlib.sha256()
    with source_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    digest.update(
        json.dumps(replacements, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    digest.update(SANITIZER_VERSION.encode("ascii"))
    source_hash = digest.hexdigest()
    hash_path = dest_path.with_name(dest_path.name + ".src-sha256")
    if dest_path.is_file() and hash_path.is_file() and hash_path.read_text(encoding="utf-8").strip() == source_hash:
        return dest_path

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_name(dest_path.name + ".tmp")
    pattern = compile_secret_pattern(replacements)
    replace = _replacer(replacements)
    with ZipFile(source_path) as archive, ZipFile(temp_path, "w", ZIP_DEFLATED) as target:
        for member in archive.infolist():
            data = archive.read(member.filename)
            if not member.is_dir() and _is_text_member(member.filename):
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    pass
                else:
                    if member.filename.lower().endswith(".json"):
                        try:
                            payload = json.loads(text)
                        except ValueError:
                            payload = None
                        if payload is not None:
                            data = json.dumps(
                                _replace_in_json(payload, pattern, replace),
                                ensure_ascii=False,
                            ).encode("utf-8")
                        else:
                            data = pattern.sub(replace, text).encode("utf-8")
                    else:
                        data = pattern.sub(replace, text).encode("utf-8")
            target.writestr(member, data)
    temp_path.replace(dest_path)
    hash_path.write_text(source_hash + "\n", encoding="utf-8")
    return dest_path
