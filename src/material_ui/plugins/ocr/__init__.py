"""OCR-Plugin: Texterkennung (Tesseract) und PDF-Verkleinerung (Ghostscript) fuer die Wissensbasis.

Die Befehle `inv wissen-ocr`, `wissen-komprimieren` und `wissen-update --ocr/--komprimieren` verlangen
das aktivierte Plugin. Ab Werk aus, damit beide Programme nur braucht, wer Scans erschliesst.
"""
from __future__ import annotations

from . import engine


def register(ctx) -> None:
    ctx.register_service("ocr-engine", engine)
