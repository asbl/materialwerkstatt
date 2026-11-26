from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from wissensbasis import pipeline
from wissensbasis.config import Fach


def test_pdf_images_are_extracted_with_page_references(project):
    fach = Fach("testfach")
    source = project / "quellen-testfach" / "bilderbuch.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    image = project / "bild.png"

    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 60), False)
    pixmap.clear_with(180)
    pixmap.save(image)

    pdf = pymupdf.open()
    page = pdf.new_page(width=200, height=200)
    page.insert_text((30, 30), "Aufgabe mit Bild")
    page.insert_image(pymupdf.Rect(40, 60, 120, 120), filename=image)
    pdf.save(source)

    pipeline.update("testfach", reindex=False, extract_images=True)

    index = fach.bilder / "bilderbuch" / "index.json"
    data = json.loads(index.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == "bilderbuch#p1-i1"
    assert data[0]["seite"] == 1
    assert Path(project / data[0]["pfad"]).exists()
