"""Lokal erfasster Sync-Stand je Plattform.

`.course-sync.json` merkt sich nur fuer das Standard-Moodle-Ziel, mit welchem Inhalts-Hash
eine Aktivitaet hochgeladen wurde. Benannte Moodle-Ziele (`--target`) und der statische
Site-Export kannten bisher nur "vorhanden / fehlt". Dieses Modul haelt fuer beide fest,
welcher Inhalts-Hash (``compute_question_hash``) zuletzt uebertragen wurde, damit sich
"aktuell" von "seit dem Upload lokal geaendert" unterscheiden laesst.

Die Dateien sind reiner, regenerierbarer Zustand: Fehlen sie oder sind sie unlesbar,
gilt der Stand als nicht erfasst -- nie als Fehler.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from material_core.filesystem import atomic_write_text


def target_sync_state_path(course_dir: Path, target: str) -> Path:
    return course_dir / f".moodle-sync-state-{target}.json"


def load_target_sync_state(course_dir: Path, target: str) -> dict[str, dict[str, str]]:
    """Liefert ``{identifier: {"hash": …, "uploadedAt": …}}`` fuer ein benanntes Moodle-Ziel."""
    payload = _read_json_object(target_sync_state_path(course_dir, target))
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    return {
        str(identifier): {"hash": str(entry.get("hash") or ""), "uploadedAt": str(entry.get("uploadedAt") or "")}
        for identifier, entry in entries.items()
        if isinstance(entry, dict) and entry.get("hash")
    }


def record_target_sync_state(course_dir: Path, target: str, hashes: dict[str, str]) -> None:
    """Merkt sich die Inhalts-Hashes gerade hochgeladener Aktivitaeten (additiv)."""
    hashes = {identifier: value for identifier, value in hashes.items() if value}
    if not hashes:
        return
    entries = load_target_sync_state(course_dir, target)
    uploaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for identifier, value in hashes.items():
        entries[identifier] = {"hash": value, "uploadedAt": uploaded_at}
    payload = {"version": 1, "target": target, "entries": dict(sorted(entries.items()))}
    atomic_write_text(
        target_sync_state_path(course_dir, target),
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def forget_target_sync_state(course_dir: Path, target: str, identifiers: set[str]) -> None:
    """Entfernt Aktivitaeten aus dem Sync-Stand eines Ziels (nach dem Loeschen auf dem Ziel)."""
    entries = load_target_sync_state(course_dir, target)
    remaining = {key: value for key, value in entries.items() if key not in identifiers}
    if remaining == entries:
        return
    payload = {"version": 1, "target": target, "entries": dict(sorted(remaining.items()))}
    atomic_write_text(
        target_sync_state_path(course_dir, target),
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def site_export_state_path(build_root: Path, output_dir: Path) -> Path:
    """Ablage des Exportstands -- bewusst neben, nicht im Export.

    Der Exportordner wird 1:1 oeffentlich ausgeliefert; der Stand ist lokaler Zustand und
    gehoert nicht dorthin. Er liegt je Zielordner getrennt unter dem Kurs-Buildordner.
    """
    key = hashlib.sha256(str(output_dir.resolve()).encode("utf-8")).hexdigest()[:16]
    return build_root / ".site-export-state" / f"{key}.json"


def load_site_export_state(build_root: Path, output_dir: Path) -> dict[str, dict[str, str]]:
    """Liefert ``{kurs-slug: {identifier: hash}}`` des zuletzt geschriebenen Site-Exports."""
    courses = _read_json_object(site_export_state_path(build_root, output_dir)).get("courses")
    if not isinstance(courses, dict):
        return {}
    return {
        str(slug): {str(identifier): str(value) for identifier, value in entries.items() if value}
        for slug, entries in courses.items()
        if isinstance(entries, dict)
    }


def record_site_export_state(build_root: Path, output_dir: Path, courses: dict[str, dict[str, str]]) -> None:
    """Merkt sich den Stand der gerade exportierten Kurse; andere Kurse bleiben unberuehrt.

    Ein Export einzelner Kurse darf den Stand der uebrigen nicht loeschen -- sie liegen
    weiterhin unveraendert im Zielordner.
    """
    merged = load_site_export_state(build_root, output_dir)
    merged.update({slug: dict(sorted(entries.items())) for slug, entries in courses.items()})
    payload = {"version": 1, "courses": dict(sorted(merged.items()))}
    atomic_write_text(
        site_export_state_path(build_root, output_dir),
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}
