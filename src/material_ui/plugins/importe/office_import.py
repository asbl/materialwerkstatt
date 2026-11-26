from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdf_erschliessung
from material_core.filesystem import atomic_write_bytes, atomic_write_text
from material_core.import_helpers import pdf_pages, slugify
from material_ui.assets import yaml_string
from material_ui.documents import DocumentService
from material_ui.tags import subject_folder_names
from material_ui.errors import InvalidInput
from material_ui.metadata import read_metadata, set_fields, split_frontmatter


MAX_OFFICE_BYTES = 32 * 1024 * 1024
OFFICE_IMPORT_TTL = 24 * 60 * 60
ALLOWED_SUFFIXES = {".pdf", ".docx"}
STAGING_DIRNAME = "office-imports"
PDFTOTEXT = "pdftotext"

_GRADE_PATTERN = re.compile(r"[Kk]lasse\s*0?(\d{1,2})|[Jj]ahrgang(?:sstufe)?\s*0?(\d{1,2})")


@dataclass(frozen=True)
class OfficeStagingRecord:
    token: str
    name: str
    origin_kind: str
    slug: str
    staged_pdf: Path
    media_dir: Path
    pages: int
    text: str
    duplicate_of: str | None
    suggested: dict[str, Any] = field(default_factory=dict)
    created: float = 0.0


def _staging_root(root: Path) -> Path:
    directory = root / ".material-ui" / STAGING_DIRNAME
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def _staging_dir(token: str, root: Path) -> Path:
    if not re.fullmatch(r"[a-f0-9]{48}", token):
        raise InvalidInput("Ungültiger Importauftrag.")
    return _staging_root(root) / token


def _state_path(token: str, root: Path) -> Path:
    return _staging_dir(token, root) / "state.json"


def _prune_expired(root: Path) -> None:
    """Raeumt nur Verzeichnisse auf, die seit OFFICE_IMPORT_TTL nicht mehr angefasst wurden.

    Nutzt bewusst die mtime des Staging-Verzeichnisses selbst (wird bei jedem
    Schreiben darin aktualisiert), nicht die von state.json: Ein gerade erst
    gestarteter, noch laufender Upload hat noch keine state.json, waere mit deren
    mtime also faelschlich sofort "abgelaufen" und wuerde von einem parallel
    gestarteten zweiten Upload geloescht werden, obwohl er gerade aktiv ist.
    """
    now = time.time()
    for candidate in _staging_root(root).iterdir():
        try:
            if now - candidate.stat().st_mtime > OFFICE_IMPORT_TTL:
                shutil.rmtree(candidate, ignore_errors=True)
        except FileNotFoundError:
            continue


def guess_subject(text: str, filename: str, *, root: Path) -> str:
    haystack = f"{filename}\n{text[:4000]}".lower()
    for name in sorted(subject_folder_names(root)):
        if name in haystack:
            return name
    return ""


def guess_grade(text: str, filename: str) -> str:
    match = _GRADE_PATTERN.search(filename) or _GRADE_PATTERN.search(text[:4000])
    if not match:
        return ""
    return next(group for group in match.groups() if group)


def guess_title(text: str, filename: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:120]
    return Path(filename).stem


def _media_rel(slug: str) -> Path:
    """Medienordner-Pfad relativ zum jeweiligen qmd -- im Staging *und* am endgueltigen
    Zielort identisch, damit die von Pandoc erzeugten Bildverweise nach dem Kopieren
    weiter stimmen (siehe extract_markdown im Plugin office)."""
    return Path("assets") / slug / "media"


def _staged_paths(staging_dir: Path, slug: str) -> tuple[Path, Path]:
    """Einzige Quelle fuer die Staging-Pfade von PDF und Medien, von stage_office_upload
    und office_staging_record gleichermassen genutzt, damit sie nicht auseinanderlaufen."""
    return staging_dir / f"{slug}-original.pdf", staging_dir / _media_rel(slug)


def _extract_pdf_text(source: Path) -> str:
    completed = subprocess.run(
        [PDFTOTEXT, "-layout", str(source), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _frontmatter_title(raw_docx_markdown: str) -> str:
    parts = split_frontmatter(raw_docx_markdown)
    if not parts:
        return ""
    try:
        value = read_metadata(raw_docx_markdown).get("title")
    except ValueError:
        return ""
    return str(value).strip() if value else ""


def stage_office_upload(payload: bytes, filename: str, *, root: Path, docx_converter=None) -> OfficeStagingRecord:
    """Laedt ein PDF/DOCX hoch, extrahiert Text und schlaegt Metadaten vor.

    Die Originaldatei und der Extraktions-Zwischenstand liegen unter
    ``.material-ui/office-imports/<token>/`` (im Repo, aber ignoriert) --
    nicht unter ``_eingang/``, damit ein paralleler ``inv pdf-erschliessen``
    laufende Importe nicht versehentlich mit erfasst.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise InvalidInput("Nur PDF- oder DOCX-Dateien koennen importiert werden.")
    if len(payload) > MAX_OFFICE_BYTES:
        raise InvalidInput(f"Die Datei darf höchstens {MAX_OFFICE_BYTES // (1024 * 1024)} MiB groß sein.")
    if not payload:
        raise InvalidInput("Die hochgeladene Datei ist leer.")

    if suffix == ".docx" and docx_converter is None:
        raise InvalidInput(
            "DOCX-Import braucht das Plugin „office“ (inv plugin-enable office, danach den Server neu starten). "
            "PDF-Dateien lassen sich auch ohne importieren."
        )
    root = root.resolve()
    _prune_expired(root)
    token = secrets.token_hex(24)
    staging_dir = _staging_dir(token, root)
    staging_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    slug = slugify(Path(filename).stem)
    staged_pdf, media_dir = _staged_paths(staging_dir, slug)

    try:
        if suffix == ".docx":
            upload_path = staging_dir / "upload.docx"
            atomic_write_bytes(upload_path, payload)
            converted = docx_converter.to_pdf(upload_path, staging_dir)
            shutil.move(str(converted), staged_pdf)
            raw_markdown = docx_converter.to_markdown(upload_path, staging_dir, _media_rel(slug))
            upload_path.unlink(missing_ok=True)
            title_hint = _frontmatter_title(raw_markdown)
            parts = split_frontmatter(raw_markdown)
            text = parts.body.strip() if parts else raw_markdown
        else:
            atomic_write_bytes(staged_pdf, payload)
            text = _extract_pdf_text(staged_pdf)
            title_hint = ""
            if not text or len(text.strip()) < 20:
                raise InvalidInput(
                    "Diese PDF hat keine erkennbare Textebene. Bitte zuerst `inv wissen-ocr` (Plugin „ocr“) auf die Datei anwenden "
                    "und das OCR-Ergebnis erneut importieren."
                )
    except subprocess.CalledProcessError as error:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise InvalidInput(f"Konvertierung fehlgeschlagen: {error.stderr or error}") from error
    except FileNotFoundError as error:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise InvalidInput(f"Konvertierung fehlgeschlagen, Programm oder Datei fehlt: {error.filename or error}") from error
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    pages = pdf_pages(staged_pdf)
    checksum = pdf_erschliessung.pruefsumme(staged_pdf)
    manifest = pdf_erschliessung.manifest_laden(root)
    existing = manifest["eintraege"].get(checksum)
    duplicate_of = existing["pfad"] if existing else None

    title = title_hint or guess_title(text, filename)
    suggested = {
        "title": title,
        "subject": guess_subject(text, filename, root=root),
        "grade": guess_grade(text, filename),
        "thema": "",
        "kind": "Arbeitsblatt",
        "tags": [],
    }

    created = time.time()
    state = {
        "token": token,
        "name": filename,
        "origin_kind": "docx" if suffix == ".docx" else "pdf",
        "slug": slug,
        "pages": pages,
        "text": text,
        "duplicate_of": duplicate_of,
        "suggested": suggested,
        "created": created,
    }
    atomic_write_text(_state_path(token, root), json.dumps(state, ensure_ascii=False))

    return OfficeStagingRecord(
        token=token,
        name=filename,
        origin_kind=state["origin_kind"],
        slug=slug,
        staged_pdf=staged_pdf,
        media_dir=media_dir,
        pages=pages,
        text=text,
        duplicate_of=duplicate_of,
        suggested=suggested,
        created=created,
    )


def office_staging_record(token: str, *, root: Path) -> OfficeStagingRecord:
    state_path = _state_path(token, root.resolve())
    if not state_path.is_file():
        raise FileNotFoundError("Der Importauftrag ist abgelaufen oder wurde bereits abgeschlossen.")
    data = json.loads(state_path.read_text(encoding="utf-8"))
    staging_dir = state_path.parent
    staged_pdf, media_dir = _staged_paths(staging_dir, data["slug"])
    return OfficeStagingRecord(
        token=data["token"],
        name=data["name"],
        origin_kind=data["origin_kind"],
        slug=data["slug"],
        staged_pdf=staged_pdf,
        media_dir=media_dir,
        pages=data["pages"],
        text=data["text"],
        duplicate_of=data["duplicate_of"],
        suggested=data["suggested"],
        created=data["created"],
    )


def discard_office_import(token: str, *, root: Path) -> None:
    shutil.rmtree(_staging_dir(token, root.resolve()), ignore_errors=True)


def update_staged_text(token: str, text: str, *, root: Path) -> None:
    """Ersetzt den Entwurfstext eines Staging-Auftrags (z. B. nach KI-Umbau oder Handbearbeitung)."""
    state_path = _state_path(token, root.resolve())
    if not state_path.is_file():
        raise FileNotFoundError("Der Importauftrag ist abgelaufen oder wurde bereits abgeschlossen.")
    data = json.loads(state_path.read_text(encoding="utf-8"))
    data["text"] = text
    atomic_write_text(state_path, json.dumps(data, ensure_ascii=False))


def conversion_prompt(record: OfficeStagingRecord, *, title: str, subject: str, grade: str, thema: str, kind: str) -> str:
    """Anweisung fuer den ersten KI-Umbau-Schritt: roher Extraktionstext -> AB im Projekt-Markdown-Stil."""
    return (
        "Wandle den folgenden automatisch extrahierten Entwurf eines Unterrichtsmaterials in den "
        "Markdown-Koerper eines Quarto-Arbeitsblatts um (ohne YAML-Frontmatter, das wird separat ergaenzt).\n"
        f"Fach: {subject or 'unbekannt'}, Klasse: {grade or 'unbekannt'}, Thema: {thema or 'unbekannt'}, "
        f"Typ: {kind or 'Arbeitsblatt'}, Titel: {title or record.name}.\n"
        "Konventionen: Aufgaben in Bloecken der Form '::: aufgabe\\n...\\n:::', Ueberschriften mit "
        "'##', deutsche Sprache, knapp und ohne Konvertierungsartefakte (Seitenzahlen, Kopf-/Fusszeilen-"
        "Reste, doppelte Leerzeilen). Nummerierung und fachlicher Inhalt der Originalaufgaben bleiben "
        "erhalten. Gib ausschliesslich den fertigen Markdown-Koerper zurueck, keine Erklaerung drumherum.\n\n"
        "--- Entwurf ---\n"
        f"{record.text.strip()}\n"
        "--- Ende Entwurf ---\n"
    )


def default_targets(*, subject: str, grade: str, thema: str, kind: str, stem: str) -> tuple[str, str]:
    """Projektpfad (unterricht/...) und Wissensbasis-Zielordner (wissen/...) aus denselben Feldern."""
    subject_slug = subject or "material"
    grade_code = DocumentService.sanitize_grade(grade or "05")
    thema_slug = thema or "material"
    kind_label = kind or "Arbeitsblatt"
    normalized_kind = DocumentService.normalize_label(kind_label)
    folder = DocumentService.kind_folder(kind_label)
    filename_stem = DocumentService.worksheet_stem(stem) if DocumentService.is_worksheet_kind(kind_label) else stem
    project_target = f"unterricht/{subject_slug}/klasse-{grade_code}/{thema_slug}/{folder}/{filename_stem}/{filename_stem}.qmd"
    if "curriculum" in normalized_kind:
        wissen_ziel = f"{subject_slug}/curriculum"
    else:
        wissen_ziel = f"arbeitsblatt/{subject_slug}/klasse-{grade_code}/{thema_slug}"
    return project_target, wissen_ziel


def _skeleton(record: OfficeStagingRecord, *, title: str, wissen_pfad: str, body: str | None = None) -> str:
    body = (body if body is not None else record.text).strip() or "Automatisch importierter Entwurf. Bitte Inhalt pruefen."
    return (
        "---\n"
        f"title: {yaml_string(title)}\n"
        "format: pdf\n"
        "material:\n"
        "  import:\n"
        f"    kind: {record.origin_kind}\n"
        f"    source-pdf: {yaml_string(wissen_pfad)}\n"
        "---\n\n"
        f"{body}\n\n"
        "<!-- material-ui -->\n"
    )


def finalize_office_import(
    token: str,
    *,
    root: Path,
    target: Path,
    wissen_ziel: str,
    fields: dict[str, Any],
    body: str | None = None,
) -> dict[str, Any]:
    """Erschliesst die Originaldatei nach wissen/ und schreibt den Entwurf atomar an `target`.

    Reihenfolge bewusst: zuerst erschliessen() (liefert den endgueltigen
    wissen/-Pfad bzw. den Pfad eines Duplikats), danach einmalig die komplette
    Frontmatter schreiben -- dadurch entfaellt der nachtraegliche Regex-Rewrite,
    den der bestehende CLI-Zweischritt (`inv import-onlyoffice` + `inv
    pdf-erschliessen --verlinken`) braucht.
    """
    root = root.resolve()
    record = office_staging_record(token, root=root)
    if target.exists():
        raise FileExistsError(f"Datei existiert bereits: {target}")
    if target.suffix != ".qmd":
        raise InvalidInput("Zielpfad muss auf eine .qmd-Datei zeigen.")

    try:
        ergebnis = pdf_erschliessung.erschliessen(record.staged_pdf, wissen_ziel, root=root)
    except ValueError as error:
        raise InvalidInput(str(error)) from error
    if ergebnis.status == pdf_erschliessung.STATUS_DUPLIKAT:
        wissen_pfad = ergebnis.duplikat_von.relative_to(root).as_posix()
    else:
        wissen_pfad = ergebnis.ziel.relative_to(root).as_posix()

    title = str(fields.get("title") or record.suggested.get("title") or record.name).strip()
    text = _skeleton(record, title=title, wissen_pfad=wissen_pfad, body=body)
    text = set_fields(text, {
        "subject": str(fields.get("subject") or ""),
        "grade": str(fields.get("grade") or ""),
        "thema": str(fields.get("thema") or ""),
        "kind": str(fields.get("kind") or ""),
        "tags": [str(tag) for tag in fields.get("tags") or []],
    })

    if record.media_dir.is_dir() and any(record.media_dir.iterdir()):
        target_media = target.parent / _media_rel(record.slug)
        target_media.parent.mkdir(parents=True, exist_ok=True)
        if target_media.exists():
            shutil.rmtree(target_media)
        shutil.copytree(record.media_dir, target_media)

    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, text, overwrite=False)
    discard_office_import(token, root=root)
    return {
        "path": target,
        "wissen_path": wissen_pfad,
        "duplicate": ergebnis.status == pdf_erschliessung.STATUS_DUPLIKAT,
    }
