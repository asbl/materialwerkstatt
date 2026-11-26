from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import yaml

from material_core.filesystem import atomic_write_text

from .config import ROOT, Fach
from .text import slugify

IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", "_meta.yaml"}
EXTENSION_FORMATS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".odt": "odf",
    ".odp": "odf",
    ".ods": "odf",
    ".epub": "epub",
    ".html": "html",
    ".htm": "html",
    ".txt": "text",
    ".md": "text",
    ".qmd": "text",
    ".tex": "text",
    ".csv": "text",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".tif": "image",
    ".tiff": "image",
}
ZIP_MARKERS = {"word/document.xml": "docx", "ppt/presentation.xml": "pptx", "xl/workbook.xml": "xlsx"}


def sniff_format(path: Path) -> str:
    """Trust the extension when it is known, otherwise look at the file header."""
    suffix = path.suffix.lower()
    if suffix in EXTENSION_FORMATS:
        return EXTENSION_FORMATS[suffix]
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError:
        return suffix.lstrip(".") or "unbekannt"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return suffix.lstrip(".") or "unbekannt"
        for marker, kind in ZIP_MARKERS.items():
            if marker in names:
                return kind
        if "mimetype" in names and "content.xml" in names:
            return "odf"
    return suffix.lstrip(".") or "unbekannt"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_files(root: Path):
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = sorted(name for name in subdirs if not name.startswith("."))
        for name in sorted(files):
            if name in IGNORED_NAMES or name.startswith(("~$", ".")):
                continue
            yield Path(directory) / name


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class MetaResolver:
    """Source metadata from quellenarten.yaml (longest path prefix wins) plus folder-local _meta.yaml files."""

    def __init__(self, fach: Fach) -> None:
        self.fach = fach
        rules = _load_yaml(fach.quellenarten).get("regeln", [])
        self.rules = sorted(rules, key=lambda rule: len(rule["pfad"]), reverse=True)
        self._folder_meta: dict[Path, dict] = {}

    def _folder(self, directory: Path) -> dict:
        if directory not in self._folder_meta:
            self._folder_meta[directory] = _load_yaml(directory / "_meta.yaml")
        return self._folder_meta[directory]

    def resolve(self, path: Path) -> dict:
        relative = path.relative_to(self.fach.quellen).as_posix()
        meta: dict = {}
        for rule in self.rules:
            prefix = rule["pfad"].rstrip("/")
            if relative == prefix or relative.startswith(prefix + "/"):
                meta = {key: value for key, value in rule.items() if key != "pfad"}
                break
        directories = [path.parent]
        while directories[-1] != self.fach.quellen:
            directories.append(directories[-1].parent)
        for directory in reversed(directories):
            meta.update(self._folder(directory))
        meta.setdefault("quellenart", "unklassifiziert")
        return meta


def load_manifest(fach: Fach) -> dict:
    if fach.manifest.exists():
        return json.loads(fach.manifest.read_text(encoding="utf-8"))
    return {"fach": fach.name, "quellenordner": fach.quellen.name, "dokumente": []}


def save_manifest(fach: Fach, manifest: dict) -> None:
    manifest["dokumente"].sort(key=lambda doc: doc["pfad"])
    fach.manifest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(fach.manifest, json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")


def _compressed_from(doc: dict) -> str | None:
    """Hash of the original a compressed document was made from."""
    info = doc.get("komprimierung") or {}
    return info.get("vorher_sha256") if info.get("status") == "komprimiert" else None


def scan(fach: Fach, old: dict) -> tuple[dict, dict[str, list[str]]]:
    """Walk the whole folder and compare with the previous manifest.

    Documents are matched by path first (unchanged when size and mtime agree, otherwise re-hashed).
    Files without a known path are matched by hash against documents that vanished (moved or renamed), and by the
    hash of the original a compressed document came from (original restored). Everything else is new.
    Identical files, and originals lying next to their compressed version, are flagged as `duplikat_von`.
    An entry with `_relink` tells the caller that its text cache and notes still point to the old (compressed) hash.
    """
    resolver = MetaResolver(fach)
    files = list(iter_files(fach.quellen))
    on_disk = {path.relative_to(ROOT).as_posix() for path in files}
    previous = {doc["pfad"]: doc for doc in old["dokumente"]}
    missing = {doc["id"]: doc for doc in old["dokumente"] if doc["pfad"] not in on_disk}

    changes: dict[str, list[str]] = {"neu": [], "geaendert": [], "verschoben": [], "wiederhergestellt": [], "entfernt": []}
    used_ids: set[str] = set()
    documents: list[dict] = []
    pending: list[tuple[Path, str, os.stat_result]] = []

    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        stat = path.stat()
        known = previous.get(relative)
        orphaned_duplicate = known is not None and known.get("duplikat_von") in missing
        if known and known["groesse"] == stat.st_size and known["mtime_ns"] == stat.st_mtime_ns and not orphaned_duplicate:
            entry = {key: value for key, value in known.items() if key not in {"meta", "duplikat_von"}}
            if (entry.get("text") or {}).get("status") == "duplikat":
                entry.pop("text")
            documents.append({**entry, **_meta_fields(resolver, path)})
            used_ids.add(known["id"])
        else:
            pending.append((path, relative, stat))

    claimed: set[str] = set()
    for path, relative, stat in pending:
        sha = file_hash(path)
        entry = {
            "pfad": relative,
            "sha256": sha,
            "groesse": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "format": sniff_format(path),
            **_meta_fields(resolver, path),
        }
        known = previous.get(relative)
        adopted, kind = None, None
        if known and known["sha256"] == sha and known["id"] not in claimed and known.get("duplikat_von") not in missing:
            adopted, kind = known, "gleich"
        elif known and _compressed_from(known) == sha:
            adopted, kind = known, "wiederhergestellt"
        else:
            pool = list(missing.values())
            if known and known.get("duplikat_von") in missing:
                pool = [missing[known["duplikat_von"]]]
            for candidate in pool:
                if candidate["id"] in claimed:
                    continue
                if candidate["sha256"] == sha:
                    adopted, kind = candidate, "verschoben"
                    break
                if _compressed_from(candidate) == sha:
                    adopted, kind = candidate, "wiederhergestellt"
                    break
        if adopted is None and known:
            adopted, kind = known, "geaendert"

        if adopted is None:
            changes["neu"].append(relative)
        else:
            claimed.add(adopted["id"])
            entry["id"] = adopted["id"]
            if kind == "geaendert":
                changes["geaendert"].append(relative)
            else:
                entry["text"] = adopted.get("text")
                if kind in {"gleich", "verschoben"} and adopted.get("komprimierung"):
                    entry["komprimierung"] = adopted["komprimierung"]
                if kind == "verschoben":
                    if adopted["pfad"] != relative:
                        changes["verschoben"].append(f"{adopted['pfad']} -> {relative}")
                elif kind == "wiederhergestellt":
                    entry["komprimierung"] = {"status": "wiederhergestellt", "frueher_sha256": adopted["sha256"]}
                    entry["_relink"] = {"alt_sha256": adopted["sha256"]}
                    changes["wiederhergestellt"].append(relative)
            used_ids.add(adopted["id"])
        documents.append(entry)

    for entry in documents:
        if "id" not in entry:
            entry["id"] = _new_id(Path(entry["pfad"]).stem, entry["sha256"], used_ids)
            used_ids.add(entry["id"])

    changes["entfernt"] = sorted(
        doc["pfad"] for doc in old["dokumente"] if doc["pfad"] not in on_disk and doc["id"] not in used_ids
    )
    _flag_duplicates(documents)
    manifest = {"fach": fach.name, "quellenordner": fach.quellen.name, "dokumente": documents}
    return manifest, changes


def _flag_duplicates(documents: list[dict]) -> None:
    """Identical files and originals next to their compressed copy are not processed twice."""
    for doc in documents:
        doc.pop("duplikat_von", None)
        if (doc.get("text") or {}).get("status") == "duplikat":
            doc.pop("text")
    by_sha: dict[str, list[dict]] = {}
    for doc in documents:
        by_sha.setdefault(doc["sha256"], []).append(doc)
    for group in by_sha.values():
        if len(group) > 1:
            primary = min(group, key=lambda doc: (0 if doc.get("text") else 1, doc["pfad"]))
            for doc in group:
                if doc is not primary:
                    _mark_duplicate(doc, primary)
    for doc in documents:
        original = _compressed_from(doc)
        if original and not doc.get("duplikat_von"):
            for other in by_sha.get(original, []):
                if other is not doc:
                    _mark_duplicate(other, doc)


def _mark_duplicate(doc: dict, primary: dict) -> None:
    doc["duplikat_von"] = primary["id"]
    doc["text"] = {"status": "duplikat"}
    doc.pop("komprimierung", None)


def _meta_fields(resolver: MetaResolver, path: Path) -> dict:
    meta = resolver.resolve(path)
    return {"quellenart": meta.pop("quellenart"), **({"meta": meta} if meta else {})}


def _new_id(stem: str, sha: str, used: set[str]) -> str:
    slug = slugify(stem)
    return slug if slug not in used else f"{slug}-{sha[:6]}"
