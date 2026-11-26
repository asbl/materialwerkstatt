"""Tests run against a throw-away project tree; the real quellen-*/ and wissen/ folders are never touched."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pymupdf
import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="wissensbasis-test-"))
os.environ["WISSENSBASIS_ROOT"] = str(TEST_ROOT)  # must be set before wissensbasis is imported
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SENTENCES = [
    "Grundvorstellungen zu Bruchzahlen entstehen durch handelndes Tun und durch den Wechsel der Darstellungen.",
    "Ein Rechteckmodell macht die Multiplikation von Anteilen sichtbar und ist tragfähiger als ein Kreismodell.",
    "Fehler sind ein natürlicher Teil des Lernprozesses und geben Hinweise auf noch nicht tragfähige Vorstellungen.",
    "Offene Aufgaben ermöglichen mehrere richtige Lösungen und verlangen Begründungen von den Lernenden.",
    "Die Zahlengerade zeigt den Unterschied zwischen einem Bruch und einer Bruchzahl besonders deutlich.",
    "Übungsaufgaben sollen sinnstiftend, entdeckungsoffen, selbstdifferenzierend und reflexiv gestaltet sein.",
    "Prozentrechnung wird verständlich, wenn Anteile mit Bildern und mit der Zahlengeraden verknüpft werden.",
    "Gleichungen lassen sich als Waage deuten, auf beiden Seiten wird immer dasselbe getan.",
]


def make_scan_pdf(path: Path, pages: int = 3, seed: int = 0, sentences: int = 5) -> list[str]:
    """Write a PDF that only contains 300 dpi page images (no text layer), like a scan. Returns the page texts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    texts = []
    output = pymupdf.open()
    for number in range(pages):
        text = "\n\n".join(SENTENCES[(seed + number + shift) % len(SENTENCES)] for shift in range(sentences))
        texts.append(text)
        with pymupdf.open() as source:
            page = source.new_page(width=595, height=842)
            page.insert_textbox(pymupdf.Rect(50, 60, 545, 780), text, fontsize=14, fontname="helv")
            jpeg = page.get_pixmap(dpi=300).tobytes("jpeg", jpg_quality=90)
        target = output.new_page(width=595, height=842)
        target.insert_image(target.rect, stream=jpeg)
    output.save(path)
    output.close()
    return texts


CONFIG = """regeln:
  - pfad: buecher
    quellenart: theorie
  - pfad: uebungen
    quellenart: unterrichtsmaterial
komprimierung:
  mindestgroesse_mb: 0.05
  mindest_ersparnis: 0.10
"""


@pytest.fixture()
def project():
    """A fresh project with one subject `testfach`; returns the project root."""
    for child in TEST_ROOT.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    (TEST_ROOT / "quellen-testfach").mkdir()
    config = TEST_ROOT / "wissen" / "testfach" / "_config"
    config.mkdir(parents=True)
    (config / "quellenarten.yaml").write_text(CONFIG, encoding="utf-8")
    return TEST_ROOT


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


needs_tools = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("gs", "tesseract", "pdftoppm", "pdfimages")),
    reason="Ghostscript, Tesseract und Poppler werden benötigt",
)
