from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf

from .config import ROOT, Fach

MIN_IMAGE_AREA = 32 * 32


def _round_box(box) -> list[float]:
    return [round(float(value), 2) for value in box]


def _extension(image: dict) -> str:
    ext = str(image.get("ext") or "bin").lower()
    return "jpg" if ext == "jpeg" else ext


def _write_json(path: Path, data: list[dict]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def extract_pdf_images(fach: Fach, doc: dict, *, overwrite: bool = False) -> int:
    """Extract embedded PDF images with stable page/image references.

    Files live in wissen/<fach>/bilder/<doc-id>/ and are accompanied by index.json.
    The image reference is the human-facing part: "<doc-id>#p<page>-i<nr>".
    """
    if doc["format"] != "pdf" or doc.get("duplikat_von"):
        return 0
    target = fach.bilder / doc["id"]
    index_file = target / "index.json"
    if index_file.exists() and not overwrite:
        try:
            existing = json.loads(index_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []
        if existing and existing[0].get("quelle_hash") == doc["sha256"]:
            return 0

    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        if child.is_file():
            child.unlink()

    entries: list[dict] = []
    with pymupdf.open(ROOT / doc["pfad"]) as pdf:
        for page_index, page in enumerate(pdf, start=1):
            images = page.get_image_info(xrefs=True)
            seen_on_page: set[int] = set()
            image_number = 0
            for info in images:
                xref = int(info.get("xref") or 0)
                width = int(info.get("width") or 0)
                height = int(info.get("height") or 0)
                if xref <= 0 or xref in seen_on_page or width * height < MIN_IMAGE_AREA:
                    continue
                seen_on_page.add(xref)
                image_number += 1
                image = pdf.extract_image(xref)
                data = image["image"]
                digest = hashlib.sha256(data).hexdigest()
                ext = _extension(image)
                stem = f"p{page_index:03d}-i{image_number:02d}-{digest[:12]}"
                filename = f"{stem}.{ext}"
                (target / filename).write_bytes(data)
                entries.append(
                    {
                        "id": f"{doc['id']}#p{page_index}-i{image_number}",
                        "quelle": doc["id"],
                        "quelle_hash": doc["sha256"],
                        "pfad": (target / filename).relative_to(ROOT).as_posix(),
                        "seite": page_index,
                        "bild": image_number,
                        "xref": xref,
                        "bbox": _round_box(info.get("bbox") or ()),
                        "breite_px": width,
                        "hoehe_px": height,
                        "sha256": digest,
                    }
                )
    _write_json(index_file, entries)
    return len(entries)


def extract_missing(fach: Fach, manifest: dict, match: str | None = None, overwrite: bool = False, log=print) -> dict[str, int]:
    counts = {"bilder": 0, "dokumente": 0}
    for doc in manifest["dokumente"]:
        if match and match.lower() not in doc["pfad"].lower() and match.lower() != doc["id"].lower():
            continue
        count = extract_pdf_images(fach, doc, overwrite=overwrite)
        if count:
            counts["bilder"] += count
            counts["dokumente"] += 1
            log(f"[{fach.name}] Bilder: {count} aus {doc['pfad']}")
    return counts
