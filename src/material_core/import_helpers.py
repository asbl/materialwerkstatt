"""Kleine Helfer der Importwege (PDF, DOCX); brauchen nur Poppler und die Standardbibliothek."""
from __future__ import annotations

import re
import subprocess
import unicodedata
from pathlib import Path

PDFINFO = "pdfinfo"


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_value = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return ascii_value or "onlyoffice-import"


def pdf_pages(path: Path) -> int:
    completed = subprocess.run(
        [PDFINFO, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"^Pages:\s+(\d+)\s*$", completed.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Kann Seitenzahl nicht ermitteln: {path}")
    return int(match.group(1))
