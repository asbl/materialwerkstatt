from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

import pdf_erschliessung
from material_core.builds import BuildFailure, BuildService
from material_core.filesystem import atomic_write_bytes, atomic_write_text
from material_ui.errors import InvalidInput

MAX_TASK_IMAGE_BYTES = 8 * 1024 * 1024
TASK_IMAGE_TTL = 24 * 60 * 60
STAGING_DIRNAME = "task-images"
ALLOWED_CONTENT_TYPES = {"image/png": ".png", "image/jpeg": ".jpg"}
TOKEN_PATTERN = re.compile(r"[a-f0-9]{48}")


@dataclass(frozen=True)
class TaskImageStagingRecord:
    token: str
    image_path: Path
    extension: str
    code: str
    created: float


def _staging_root(root: Path) -> Path:
    directory = root / ".material-ui" / STAGING_DIRNAME
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def staging_dir(token: str, root: Path) -> Path:
    if not TOKEN_PATTERN.fullmatch(token):
        raise InvalidInput("Ungültiger Importauftrag.")
    return _staging_root(root) / token


def _state_path(token: str, root: Path) -> Path:
    return staging_dir(token, root) / "state.json"


def _prune_expired(root: Path) -> None:
    """Wie office_import._prune_expired: nutzt die mtime des Staging-Ordners selbst,
    damit ein gerade erst gestarteter, noch laufender Upload nicht faelschlich als
    abgelaufen geloescht wird."""
    now = time.time()
    for candidate in _staging_root(root).iterdir():
        try:
            if now - candidate.stat().st_mtime > TASK_IMAGE_TTL:
                shutil.rmtree(candidate, ignore_errors=True)
        except FileNotFoundError:
            continue


def stage_task_image(payload: bytes, content_type: str, *, root: Path) -> TaskImageStagingRecord:
    """Staged ein aus der Zwischenablage eingefuegtes Aufgabenbild unter
    ``.material-ui/task-images/<token>/`` (nicht unter wissen/ oder _eingang/,
    solange der Import noch nicht bestaetigt ist)."""
    extension = ALLOWED_CONTENT_TYPES.get(content_type.split(";")[0].strip().lower())
    if extension is None:
        raise InvalidInput("Nur PNG- oder JPEG-Bilder koennen als Aufgabe importiert werden.")
    if not payload:
        raise InvalidInput("Das eingefuegte Bild ist leer.")
    if len(payload) > MAX_TASK_IMAGE_BYTES:
        raise InvalidInput(f"Das Bild darf höchstens {MAX_TASK_IMAGE_BYTES // (1024 * 1024)} MiB groß sein.")

    root = root.resolve()
    _prune_expired(root)
    token = secrets.token_hex(24)
    directory = staging_dir(token, root)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    image_path = directory / f"original{extension}"
    atomic_write_bytes(image_path, payload)
    created = time.time()
    atomic_write_text(
        _state_path(token, root),
        json.dumps({"token": token, "extension": extension, "code": "", "created": created}, ensure_ascii=False),
    )
    return TaskImageStagingRecord(token=token, image_path=image_path, extension=extension, code="", created=created)


def task_image_record(token: str, *, root: Path) -> TaskImageStagingRecord:
    state_path = _state_path(token, root.resolve())
    if not state_path.is_file():
        raise FileNotFoundError("Der Importauftrag ist abgelaufen oder wurde bereits abgeschlossen.")
    data = json.loads(state_path.read_text(encoding="utf-8"))
    directory = state_path.parent
    return TaskImageStagingRecord(
        token=data["token"],
        image_path=directory / f"original{data['extension']}",
        extension=data["extension"],
        code=data["code"],
        created=data["created"],
    )


def discard_task_image(token: str, *, root: Path) -> None:
    shutil.rmtree(staging_dir(token, root.resolve()), ignore_errors=True)


def update_code(token: str, code: str, *, root: Path) -> None:
    """Haelt den zuletzt vom Chat gelieferten Code-Stand im Staging-Auftrag fest."""
    state_path = _state_path(token, root.resolve())
    if not state_path.is_file():
        raise FileNotFoundError("Der Importauftrag ist abgelaufen oder wurde bereits abgeschlossen.")
    data = json.loads(state_path.read_text(encoding="utf-8"))
    data["code"] = code
    atomic_write_text(state_path, json.dumps(data, ensure_ascii=False))


def conversion_prompt(token: str) -> str:
    return (
        f'Rufe zuerst das Werkzeug show_task_image mit token="{token}" auf, um das Bild einer einzelnen '
        "Aufgabe zu sehen (z. B. ein Schulbuch-Screenshot).\n"
        "Wandle die Aufgabe danach in Quarto-Markdown-Code um: Aufgabentext und Teilaufgaben wie im Original "
        "nummeriert, Formeln als LaTeX-Mathe ($...$ bzw. $$...$$). Gib ausschliesslich den fertigen "
        "Markdown-Code zurueck -- kein YAML-Frontmatter, keinen ::: aufgabe :::-Block (der wird separat "
        "ergaenzt), keine Erklaerung drumherum."
    )


def render_preview(builds: BuildService, token: str, code: str, *, root: Path) -> Path:
    """Rendert den aktuellen Code-Entwurf einmalig; liefert den Pfad zum PNG der ersten Seite.

    Nutzt dieselbe BuildService-Pipeline (Render-Lock, Managed-Render-Umgebung,
    Artefakt-Umsortierung) wie jeder andere Render in der App, damit diese
    Vorschau sich nicht an einer eigenen, parallelen Quarto-Invokation vorbeischmuggelt.
    """
    directory = staging_dir(token, root.resolve())
    preview_qmd = directory / "preview.qmd"
    text = "---\n" 'title: "Vorschau"\n' "format: pdf\n" "---\n\n" f"{code.strip() or 'Kein Code.'}\n"
    atomic_write_text(preview_qmd, text)
    try:
        result = builds.build_document(preview_qmd, snapshot={"text": text}, allow_source_changes=True)
    except BuildFailure as error:
        raise InvalidInput(f"Vorschau-Render fehlgeschlagen: {error}") from error
    preview_png = directory / "preview.png"
    with pymupdf.open(result.pdf_path) as document:
        pixmap = document.load_page(0).get_pixmap(dpi=150)
        pixmap.save(preview_png)
    return preview_png


def commit_task_image(token: str, *, root: Path, wissen_ziel: str, code: str) -> dict[str, Any]:
    """Erschliesst das Originalbild nach wissen/aufgaben/... und liefert den fertigen Markdown-Block.

    Fuegt den Block bewusst NICHT selbst ins Dokument ein (anders als
    office_import.finalize_office_import, das eine neue Datei erzeugt): hier wird
    in ein bereits offenes, moeglicherweise ungespeichert bearbeitetes Dokument
    eingefuegt. Wie AssetService.import_images bei insert=false macht das der
    Client selbst im aktuellen Editor-Puffer und speichert danach ganz normal --
    das vermeidet eine serverseitige Revisionspruefung gegen einen Stand, den der
    Client zu diesem Zeitpunkt moeglicherweise schon ueberholt hat.
    """
    root = root.resolve()
    record = task_image_record(token, root=root)
    if not code.strip():
        raise InvalidInput("Kein Code zum Importieren vorhanden.")
    try:
        ergebnis = pdf_erschliessung.erschliessen(record.image_path, wissen_ziel, root=root)
    except ValueError as error:
        raise InvalidInput(str(error)) from error
    if ergebnis.status == pdf_erschliessung.STATUS_DUPLIKAT:
        wissen_pfad = ergebnis.duplikat_von.relative_to(root).as_posix()
    else:
        wissen_pfad = ergebnis.ziel.relative_to(root).as_posix()
    markdown = "\n::: aufgabe\n" f"{code.strip()}\n" f"<!-- quelle: {wissen_pfad} -->\n" ":::\n"
    discard_task_image(token, root=root)
    return {"wissen_path": wissen_pfad, "markdown": markdown}
