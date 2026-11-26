from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import pymupdf

from .config import ROOT, TEXT_CACHE
from .text import clean_page, fix_ligatures

EMPTY_PAGE_CHARS = 30
OCR_THRESHOLD = 0.5
CHUNK_CHARS = 3000
TEXT_FORMATS = {"pdf", "docx", "pptx", "xlsx", "odf", "epub", "html", "text", "image"}
OCR_FORMATS = {"pdf", "image"}
OCR_TIMEOUT = 240
OCR_DEFAULT_LANGUAGE = "deu"
OCR_LANGUAGES = {"deu", "eng"}
ENGLISH_HINTS = {
    "barton", "craig", "reflect", "expect", "check", "explain", "maths", "mathematics",
    "classroom", "teaching", "learning", "sequences", "behaviour",
}
GERMAN_HINTS = {
    "mathematik", "mathe", "unterricht", "lernen", "lehren", "aufgaben", "förderung",
    "diagnose", "geometrie", "stochastik",
}


class OcrError(Exception):
    """Rendering or recognising one page failed or took too long."""


def cache_path(sha: str) -> Path:
    return TEXT_CACHE / f"{sha}.jsonl"


def load_pages(sha: str) -> list[dict]:
    path = cache_path(sha)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        pages = [json.loads(line) for line in handle]
    for page in pages:
        page["t"] = fix_ligatures(page["t"])
    return pages


def save_pages(sha: str, pages: list[dict]) -> None:
    TEXT_CACHE.mkdir(parents=True, exist_ok=True)
    target = cache_path(sha)
    temporary = target.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for page in pages:
            handle.write(json.dumps(page, ensure_ascii=False) + "\n")
    temporary.replace(target)


def _pdf_pages(path: Path) -> list[str]:
    try:
        with pymupdf.open(path) as document:
            return [page.get_text() for page in document]
    except Exception:
        # Damaged page trees: poppler is usually more forgiving than MuPDF.
        result = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(path), "-"], capture_output=True, check=True
        )
        return result.stdout.decode("utf-8", "replace").split("\f")[:-1] or [""]


def _xml_text(data: bytes, paragraph_tags: set[str]) -> list[str]:
    paragraphs = (
        "".join(element.itertext())
        for element in ElementTree.fromstring(data).iter()
        if element.tag.rpartition("}")[2] in paragraph_tags
    )
    return [text for text in paragraphs if text.strip()]


def _chunk(paragraphs: list[str]) -> list[str]:
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) > CHUNK_CHARS:
            chunks.append(current)
            current = ""
        current += paragraph + "\n"
    if current.strip():
        chunks.append(current)
    return chunks or [""]


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        elif tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _html_paragraphs(raw: bytes) -> list[str]:
    parser = _HtmlText()
    parser.feed(raw.decode("utf-8", "replace"))
    return [line.strip() for line in "".join(parser.parts).split("\n") if line.strip()]


def _read_paragraphs(path: Path, fmt: str) -> list[str]:
    if fmt == "text":
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    if fmt == "html":
        return _html_paragraphs(path.read_bytes())
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if fmt == "docx":
            return _xml_text(archive.read("word/document.xml"), {"p"})
        if fmt == "odf":
            return _xml_text(archive.read("content.xml"), {"p", "h"})
        if fmt == "epub":
            paragraphs: list[str] = []
            for name in names:
                if name.lower().endswith((".xhtml", ".html", ".htm")):
                    paragraphs.extend(_html_paragraphs(archive.read(name)))
            return paragraphs
        if fmt == "xlsx":
            if "xl/sharedStrings.xml" not in names:
                return []
            return _xml_text(archive.read("xl/sharedStrings.xml"), {"si"})
    return []


def extract_text(path_str: str, fmt: str) -> dict:
    """Return {'einheit': 'seite'|'abschnitt'|'folie'|'bild', 'seiten': [...]} or {'fehler': msg}."""
    path = ROOT / path_str
    try:
        if fmt == "pdf":
            return {"einheit": "seite", "seiten": [clean_page(text) for text in _pdf_pages(path)]}
        if fmt == "image":
            return {"einheit": "bild", "seiten": [""]}
        if fmt == "pptx":
            with zipfile.ZipFile(path) as archive:
                slides = sorted(
                    (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                    key=lambda name: int(re.search(r"(\d+)", name.rsplit("/", 1)[1]).group(1)),
                )
                return {
                    "einheit": "folie",
                    "seiten": [clean_page("\n".join(_xml_text(archive.read(name), {"p"}))) for name in slides] or [""],
                }
        return {"einheit": "abschnitt", "seiten": [clean_page(chunk) for chunk in _chunk(_read_paragraphs(path, fmt))]}
    except Exception as error:  # noqa: BLE001 - a single broken file must not stop the whole run
        return {"fehler": f"{type(error).__name__}: {error}"}


def text_status(fmt: str, pages: list[dict], einheit: str) -> dict:
    count = len(pages)
    threshold = EMPTY_PAGE_CHARS if fmt in OCR_FORMATS else 1
    empty = sum(1 for page in pages if len(page["t"].strip()) < threshold)
    pending = sum(
        1 for page in pages if len(page["t"].strip()) < EMPTY_PAGE_CHARS and not page.get("ocr")
    )
    if fmt in OCR_FORMATS and count and pending / count > OCR_THRESHOLD:
        status = "needs_ocr"
    elif count == 0 or empty == count:
        status = "leer"
    else:
        status = "ok"
    return {
        "status": status,
        "einheit": einheit,
        "einheiten": count,
        "zeichen": sum(len(page["t"]) for page in pages),
        "ocr_seiten": sum(1 for page in pages if page.get("ocr") and len(page["t"].strip()) >= EMPTY_PAGE_CHARS),
    }


def ocr_language(doc: dict) -> str:
    """Choose a Tesseract language for OCR.

    Folder-local `_meta.yaml` may set `ocr_sprache`, `sprache`, `language` or `lang`.
    Without explicit metadata, a conservative path/title heuristic decides, defaulting to German.
    """
    meta = doc.get("meta") or {}
    explicit = str(
        meta.get("ocr_sprache") or meta.get("sprache") or meta.get("language") or meta.get("lang") or ""
    ).lower()
    if explicit.startswith(("en", "eng")):
        return "eng"
    if explicit.startswith(("de", "deu", "ger")):
        return "deu"

    haystack = " ".join(str(value) for value in (doc.get("pfad"), doc.get("id")) if value).lower()
    tokens = set(re.findall(r"[a-zäöüß]+", haystack))
    if tokens & ENGLISH_HINTS and not tokens & GERMAN_HINTS:
        return "eng"
    return OCR_DEFAULT_LANGUAGE


def needs_ocr_language_refresh(doc: dict) -> bool:
    text = doc.get("text") or {}
    current = text.get("ocr_sprache") or text.get("ocr_lang") or OCR_DEFAULT_LANGUAGE
    return bool(text.get("ocr_seiten")) and current != ocr_language(doc)


def extract_missing(documents: list[dict], workers: int = 6) -> dict[str, int]:
    """Fill the text cache for every document that has none yet and set its 'text' status."""
    counts = {"extrahiert": 0, "fehler": 0, "nicht_textuell": 0}
    todo: list[dict] = []
    for doc in documents:
        if doc.get("duplikat_von"):
            continue
        if doc["format"] not in TEXT_FORMATS:
            doc["text"] = {"status": "nicht_textuell"}
            counts["nicht_textuell"] += 1
        elif doc.get("text") and cache_path(doc["sha256"]).exists():
            continue
        else:
            todo.append(doc)
    if not todo:
        return counts
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = pool.map(extract_text, [doc["pfad"] for doc in todo], [doc["format"] for doc in todo], chunksize=1)
        for number, (doc, result) in enumerate(zip(todo, results), start=1):
            if "fehler" in result:
                doc["text"] = {"status": "fehler", "meldung": result["fehler"]}
                counts["fehler"] += 1
                continue
            pages = [{"p": index, "t": text} for index, text in enumerate(result["seiten"], start=1)]
            save_pages(doc["sha256"], pages)
            doc["text"] = text_status(doc["format"], pages, result["einheit"])
            counts["extrahiert"] += 1
            if number % 25 == 0:
                print(f"  Text extrahiert: {number}/{len(todo)}", flush=True)
    return counts


def _ocr_page(pdf: Path, number: int | None, image: Path | None = None, language: str = OCR_DEFAULT_LANGUAGE) -> str:
    """Recognise one page. Raises OcrError instead of letting a damaged page abort a multi-hour run."""
    try:
        with tempfile.TemporaryDirectory() as directory:
            if image is None:
                target = Path(directory) / "page"
                subprocess.run(
                    ["pdftoppm", "-r", "200", "-gray", "-png", "-singlefile", "-f", str(number), "-l", str(number), str(pdf), str(target)],
                    check=True, capture_output=True, timeout=OCR_TIMEOUT,
                )
                image = target.with_suffix(".png")
            if language not in OCR_LANGUAGES:
                language = OCR_DEFAULT_LANGUAGE
            result = subprocess.run(
                ["tesseract", str(image), "stdout", "-l", language, "--psm", "3"],
                capture_output=True, check=True, timeout=OCR_TIMEOUT, env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            )
    except (subprocess.SubprocessError, OSError) as error:
        raise OcrError(f"Seite {number}: {type(error).__name__}") from error
    return clean_page(result.stdout.decode("utf-8", "replace"))


def ocr_document(doc: dict, workers: int = 6, log=print) -> int:
    """OCR the pages that have no text; progress is saved so an interrupted run resumes."""
    pages = load_pages(doc["sha256"])
    language = ocr_language(doc)
    refresh_language = needs_ocr_language_refresh(doc)
    pending = [
        page for page in pages
        if (len(page["t"].strip()) < EMPTY_PAGE_CHARS and not page.get("ocr")) or (refresh_language and page.get("ocr"))
    ]
    if not pending:
        return 0
    path = ROOT / doc["pfad"]
    done = 0

    def work(page: dict) -> tuple[dict, str | None]:
        try:
            if doc["format"] == "image":
                return page, _ocr_page(path, None, image=path, language=language)
            return page, _ocr_page(path, page["p"], language=language)
        except OcrError as error:
            log(f"    OCR-Fehler, Seite wird übersprungen: {error}")
            return page, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for page, text in pool.map(work, pending):
            page["t"], page["ocr"] = text or "", True
            if text is None:
                page["fehler"] = True
            done += 1
            if done % 25 == 0:
                save_pages(doc["sha256"], pages)
                log(f"    {done}/{len(pending)} Seiten")
    save_pages(doc["sha256"], pages)
    doc["text"] = text_status(doc["format"], pages, doc["text"]["einheit"])
    doc["text"]["ocr_sprache"] = language
    doc["text"]["ocr_lang"] = language
    failed = sum(1 for page in pages if page.get("fehler"))
    if failed:
        doc["text"]["ocr_fehlerseiten"] = failed
    return done
