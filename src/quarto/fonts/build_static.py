"""Build renamed static OFL faces for Typst (requires fonttools).

Originals and their licenses are pinned in manifest.json. Run from any directory:
python src/quarto/fonts/build_static.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent


def build(families=None):
    manifest = json.loads((ROOT / "manifest.json").read_text())
    previous = ROOT / "static-manifest.json"
    outputs = ([entry for entry in json.loads(previous.read_text())["files"]
                if Path(entry["source"]).parent.name not in families]
               if families and previous.exists() else [])
    for entry in manifest["files"]:
        source = ROOT / entry["path"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Font source checksum mismatch: {entry['path']}")
        if source.suffix != ".ttf":
            continue
        if families and source.parent.name not in families:
            continue
        original = TTFont(source, recalcTimestamp=False)
        family = original["name"].getBestFamilyName()
        destination = ROOT / "static" / source.parent.name
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source.parent / "OFL.txt", destination / "OFL.txt")
        weights = [600, 700] if "fvar" in original else [original["OS/2"].usWeightClass]
        for weight in weights:
            face = TTFont(source, recalcTimestamp=False)
            coordinates = {}
            if "fvar" in face:
                coordinates = {a.axisTag: a.defaultValue for a in face["fvar"].axes}
                coordinates["wght"] = weight
                # Header optical size; never use a display master for small text.
                if "opsz" in coordinates:
                    coordinates["opsz"] = 20
                face = instantiateVariableFont(face, coordinates, inplace=True)
            renamed = {"Acme": "Material Cartoon", "Barlow Semi Condensed": "Material Sport",
                       "Lilita One": "Material Insel"}.get(
                family, "Material " + family)
            style = {400: "Regular", 600: "SemiBold", 700: "Bold"}[weight]
            postscript = renamed.replace(" ", "") + "-" + style
            # Separate family names prevent installed variable originals from winning
            # font selection. This also avoids every original Reserved Font Name.
            names = face["name"]
            for record in list(names.names):
                if record.nameID in {1, 2, 3, 4, 6, 16, 17, 21, 22}:
                    names.names.remove(record)
            values = {1: renamed, 2: style, 3: postscript + ";" + manifest["commit"],
                      4: renamed + " " + style, 6: postscript, 16: renamed, 17: style}
            for name_id, value in values.items():
                names.setName(value, name_id, 3, 1, 0x409)
            face["OS/2"].usWeightClass = weight
            face["OS/2"].fsSelection &= ~((1 << 5) | (1 << 6))
            face["OS/2"].fsSelection |= (1 << 5) if weight >= 700 else (1 << 6)
            face["head"].macStyle = (face["head"].macStyle & ~1) | (1 if weight >= 700 else 0)
            target = destination / (postscript + ".ttf")
            face.save(target)
            outputs.append({"path": target.relative_to(ROOT).as_posix(),
                            "source": entry["path"], "axes": coordinates,
                            "family": renamed, "weight": weight,
                            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    (ROOT / "static-manifest.json").write_text(json.dumps({
        "source_commit": manifest["commit"],
        "modification": "Static instances, optical size 20 where available, renamed families and style metadata.",
        "files": outputs,
    }, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    build(sys.argv[1:] or None)
