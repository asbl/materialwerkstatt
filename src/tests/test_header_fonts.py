"""Verify distributable fonts and the actual title/exercise faces in rendered PDFs."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

import pymupdf
import pytest

from material_core.builds import BuildService

ROOT = Path(__file__).resolve().parents[2]
FONTS = ROOT / "src/quarto/fonts"


def test_bundled_faces_have_licenses_checksums_and_german_glyphs():
    TTFont = pytest.importorskip("fontTools.ttLib").TTFont
    original = json.loads((FONTS / "manifest.json").read_text())
    static = json.loads((FONTS / "static-manifest.json").read_text())
    for entry in [*original["files"], *static["files"]]:
        path = FONTS / entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert b"SIL OPEN FONT LICENSE Version 1.1" in (path.parent / "OFL.txt").read_bytes()
    for entry in static["files"]:
        with TTFont(FONTS / entry["path"]) as font:
            assert "fvar" not in font, "Typst needs genuinely static faces"
            assert font["name"].getBestFamilyName() == entry["family"]
            assert font["OS/2"].usWeightClass == entry["weight"]
            assert all(ord(c) in font.getBestCmap() for c in "ÄÖÜäöüß")
    # Acme reserves its name; its modified face has an unrelated primary name.
    cartoon = next(e for e in static["files"] if e["source"].startswith("acme/"))
    assert cartoon["family"] == "Material Cartoon"


@pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")
@pytest.mark.parametrize("template,title_face,exercise_face", [
    ("worksheet-retro.typst", "MaterialPixelifySans-Bold", "MaterialOutfit-SemiBold"),
    ("worksheet-informatik.typst", "MaterialSpaceGrotesk-Bold", "MaterialSpaceGrotesk-SemiBold"),
    ("worksheet-fussball.typst", "MaterialSport-Bold", "MaterialSport-SemiBold"),
    ("worksheet-anime.typst", "Bangers", "MaterialCartoon-Regular"),
])
def test_title_and_exercise_use_distinct_actual_faces(tmp_path, template, title_face, exercise_face):
    # worksheet-anime verlangt "Bangers", das nicht mitgeliefert wird.
    if title_face == "Bangers" and "Bangers" not in subprocess.run(
            ["typst", "fonts"], capture_output=True, text=True).stdout.splitlines():
        pytest.skip("Schrift Bangers ist nicht installiert (nicht mitgeliefert)")
    source = tmp_path / "ab_probe.qmd"
    source.write_text(
        f"---\ntitle: Größen und Maßstäbe\nformat:\n  typst:\n    template: {template}\n---\n\n"
        "# 1 Größen ändern\n\nÄpfel, Öl und süße Grüße.\n",
    )
    result = BuildService(tmp_path, subprocess.run).build_document(source, error_summary=lambda s: s)
    assert result.returncode == 0, result.stdout
    assert "variable fonts are not currently supported" not in result.stdout
    assert "unknown font family: material" not in result.stdout
    with pymupdf.open(result.pdf_path) as pdf:
        spans = [span for page in pdf for block in page.get_text("dict")["blocks"]
                 for line in block.get("lines", []) for span in line["spans"]]
        # Typst truncates some embedded PostScript names in its PDF font table.
        def matches(actual, expected):
            return actual == expected[:len(actual)] or actual.startswith(expected + "-")
        assert any(s["text"] == "Größen und Maßstäbe" and matches(s["font"], title_face) for s in spans)
        assert any("Größen ändern" in s["text"] and matches(s["font"], exercise_face) for s in spans)
