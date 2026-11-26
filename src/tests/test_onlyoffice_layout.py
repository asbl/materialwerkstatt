from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onlyoffice_layout import ImageCatalog, layout_draft


@pytest.fixture()
def imported_draft(tmp_path):
    directory = tmp_path / "assets" / "beispiel"
    media = directory / "media"
    media.mkdir(parents=True)
    for shade, filename in [(255, "weiss.png"), (50, "dunkel.png")]:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
        pixmap.clear_with(shade)
        pixmap.save(media / filename)
    original = directory / "beispiel-original.pdf"
    with pymupdf.open() as document:
        first = document.new_page(width=300, height=200)
        first.insert_text((20, 30), "Aufgabe 1: 50% & 100_2", fontsize=11)
        first.insert_image(pymupdf.Rect(20, 40, 100, 100), filename=str(media / "dunkel.png"), keep_proportion=False)
        image_stream = first.get_contents()[-1]
        document.update_stream(image_stream, b"q\n20 110 80 30 re W n\n" + document.xref_stream(image_stream) + b"\nQ\n")
        first.draw_rect(pymupdf.Rect(15, 15, 280, 180), color=(0.1, 0.3, 0.5), width=0.5)
        second = document.new_page(width=300, height=200)
        second.insert_text((20, 30), "Loesung 1", fontsize=11)
        second.insert_image(pymupdf.Rect(20, 40, 100, 100), filename=str(media / "weiss.png"), keep_proportion=False)
        document.save(original)
    source = tmp_path / "beispiel-entwurf.qmd"
    source.write_text(
        "---\ntitle: Beispiel\nformat:\n  pdf:\n    output-file: beispiel-entwurf.pdf\n"
        "    keep-tex: true\nmaterial:\n  import:\n    kind: onlyoffice\n"
        "    mode: pandoc-draft\n---\n\nAlter Import\n",
        encoding="utf-8",
    )
    return source, original


def test_layout_keeps_native_elements_and_image_clipping(imported_draft):
    source, _ = imported_draft
    text = layout_draft(source)
    assert text.count(r"\begin{importseite}") == 2
    assert "paperwidth=300bp" in text
    assert "paperheight=200bp" in text
    assert "source-pages: 2" in text
    assert "mode: positioned-draft" in text
    assert r"50\%\ \&\ 100\_2" in text
    assert "assets/beispiel/media/dunkel.png" in text
    assert "assets/beispiel/media/weiss.png" in text
    assert r"\clip (20,90) -- (100,90) -- (100,60) -- (20,60) -- cycle;" in text
    assert r"\path[" in text
    assert "original.pdf" not in text
    assert r"\includepdf" not in text


def test_layout_resolves_original_via_source_pdf_reference(imported_draft, monkeypatch):
    import onlyoffice_layout

    source, original = imported_draft
    erschlossen = source.parent / "wissen" / "arbeitsblatt" / "beispiel" / "beispiel.pdf"
    erschlossen.parent.mkdir(parents=True)
    original.replace(erschlossen)
    monkeypatch.setattr(onlyoffice_layout, "ROOT", source.parent)
    source.write_text(
        "---\ntitle: Beispiel\nformat:\n  pdf:\n    output-file: beispiel-entwurf.pdf\n"
        "    keep-tex: true\nmaterial:\n  import:\n    kind: onlyoffice\n"
        "    mode: positioned-draft\n"
        "    source-pdf: wissen/arbeitsblatt/beispiel/beispiel.pdf\n"
        "    source-pages: 2\n---\n\nAlter Import\n",
        encoding="utf-8",
    )

    text = onlyoffice_layout.layout_draft(source)

    assert text.count(r"\begin{importseite}") == 2
    assert "source-pages: 2" in text
    # Bildverweise bleiben relativ zur QMD und zeigen auf die Medien neben dem Entwurf.
    assert "assets/beispiel/media/dunkel.png" in text
    assert "assets/beispiel/media/weiss.png" in text


@pytest.mark.skipif(not shutil.which("quarto") or not shutil.which("lualatex"), reason="Quarto/LuaLaTeX fehlt")
def test_render_preserves_pages_native_text_and_visible_layout(imported_draft):
    source, original_path = imported_draft
    source.write_text(layout_draft(source), encoding="utf-8")
    result = subprocess.run(["quarto", "render", str(source)], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    with pymupdf.open(original_path) as original, pymupdf.open(source.with_suffix(".pdf")) as rendered:
        assert len(rendered) == len(original) == 2
        for before, after in zip(original, rendered, strict=True):
            assert tuple(after.rect) == pytest.approx(tuple(before.rect), abs=0.01)
            assert after.get_text().split() == before.get_text().split()
            original_pixels = np.frombuffer(before.get_pixmap().samples, dtype=np.uint8).astype(float)
            rendered_pixels = np.frombuffer(after.get_pixmap().samples, dtype=np.uint8).astype(float)
            assert np.abs(original_pixels - rendered_pixels).mean() < 1


def test_mixed_page_sizes_require_explicit_layout_handling(imported_draft):
    source, original_path = imported_draft
    with pymupdf.open(original_path) as document:
        document.new_page(width=200, height=300)
        document.saveIncr()
    with pytest.raises(ValueError, match="Unterschiedliche Seitengrößen"):
        layout_draft(source)


def test_extracted_image_keeps_transparency_mask(tmp_path):
    image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), True)
    image.clear_with()
    image.set_rect(pymupdf.IRect(2, 2, 6, 6), (200, 0, 0, 255))
    with pymupdf.open() as document:
        page = document.new_page()
        xref = page.insert_image(pymupdf.Rect(20, 20, 100, 100), stream=image.tobytes("png"))
        target = ImageCatalog(tmp_path).match(document, xref)
    extracted = pymupdf.Pixmap(target)
    assert extracted.alpha == 1
    assert extracted.pixel(0, 0)[3] == 0
    assert extracted.pixel(3, 3)[3] == 255
