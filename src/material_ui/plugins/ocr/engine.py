"""Aufrufe von Tesseract und Ghostscript. Nur Standardbibliothek."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def recognise(image: Path, language: str, timeout: int) -> str:
    """Text eines Seitenbilds; Fehler kommen als SubprocessError oder OSError."""
    result = subprocess.run(
        ["tesseract", str(image), "stdout", "-l", language, "--psm", "3"],
        capture_output=True, check=True, timeout=timeout, env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )
    return result.stdout.decode("utf-8", "replace")


def shrink_pdf(src: Path, dst: Path, *, dpi: int, qfactor: float) -> None:
    """Rechnet die Bilder eines PDFs auf `dpi` herunter und speichert sie als JPEG."""
    dict_ps = (
        f"<< /ColorImageDict << /QFactor {qfactor} /Blend 1 /HSamples [1 1 1 1] /VSamples [1 1 1 1] >> "
        f"/GrayImageDict << /QFactor {qfactor} /Blend 1 /HSamples [1 1 1 1] /VSamples [1 1 1 1] >> >> setdistillerparams"
    )
    command = [
        "gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5",
        f"-sOutputFile={dst}", "-dColorConversionStrategy=/LeaveColorUnchanged",
        "-dDownsampleColorImages=true", "-dDownsampleGrayImages=true",
        f"-dColorImageResolution={dpi}", f"-dGrayImageResolution={dpi}",
        "-dColorImageDownsampleThreshold=1.0", "-dGrayImageDownsampleThreshold=1.0",
        "-dColorImageDownsampleType=/Bicubic", "-dGrayImageDownsampleType=/Bicubic",
        "-dAutoFilterColorImages=false", "-dAutoFilterGrayImages=false",
        "-dColorImageFilter=/DCTEncode", "-dGrayImageFilter=/DCTEncode",
        "-dDetectDuplicateImages=true", "-dSubsetFonts=true", "-dCompressFonts=true",
        "-c", dict_ps, "-f", str(src),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=1800)
