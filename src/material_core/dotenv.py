"""Minimaler .env-Parser, gemeinsam genutzt von course_sync und material_ui."""

from __future__ import annotations

from pathlib import Path
from typing import MutableMapping


def load_dotenv_file(dotenv_path: Path, environ: MutableMapping[str, str]) -> None:
    """Setzt Variablen aus dotenv_path in environ, die dort noch nicht gesetzt sind."""
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        environ[key] = value


def read_dotenv_values(dotenv_path: Path) -> dict[str, str]:
    """Liest die Variablen einer .env-Datei (ohne os.environ zu beruehren)."""
    values: dict[str, str] = {}
    load_dotenv_file(dotenv_path, values)
    return values


def format_dotenv_value(value: str) -> str:
    """Formatiert einen Wert so, dass `load_dotenv_file` ihn unveraendert zuruecklesen kann."""
    if "\n" in value or "\r" in value or "\0" in value:
        raise ValueError("Wert darf keine Zeilenumbrueche enthalten.")
    needs_quotes = (
        value != value.strip()
        or value[:1] in {'"', "'"}
        or value[-1:] in {'"', "'"}
        or " #" in value
        or "\\" in value
        or "$" in value
    )
    if not needs_quotes:
        return value
    if "'" in value:
        raise ValueError("Wert mit Sonderzeichen und Apostroph kann nicht sicher in .env gespeichert werden.")
    return f"'{value}'"


def set_dotenv_values(dotenv_path: Path, updates: dict[str, str]) -> None:
    """Setzt Variablen in einer .env-Datei, ohne Kommentare und Reihenfolge zu veraendern.

    Vorhandene Zeilen werden an Ort und Stelle ersetzt, neue am Ende angehaengt. Die
    Datei wird atomar ersetzt; Zugriffsrechte einer bestehenden Datei bleiben erhalten,
    eine neue Datei ist nur fuer den Besitzer lesbar.
    """
    import os
    import tempfile

    for key in updates:
        if not key or "=" in key or any(char.isspace() for char in key):
            raise ValueError(f"Ungueltiger Variablenname: {key!r}")
    formatted = {key: format_dotenv_value(value) for key, value in updates.items()}
    try:
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    pending = dict(formatted)
    result: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        key = stripped.split("=", 1)[0].strip() if stripped and not stripped.startswith("#") and "=" in stripped else ""
        if key in pending:
            result.append(f"{key}={pending.pop(key)}")
        else:
            result.append(raw_line)
    for key, value in pending.items():
        result.append(f"{key}={value}")
    mode = dotenv_path.stat().st_mode & 0o777 if dotenv_path.exists() else 0o600
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{dotenv_path.name}.", dir=dotenv_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(result) + "\n")
        os.chmod(temp_name, mode)
        os.replace(temp_name, dotenv_path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
