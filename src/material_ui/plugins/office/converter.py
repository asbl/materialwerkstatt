"""DOCX-Konvertierung mit LibreOffice (PDF) und Pandoc (Markdown)."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from quarto_render_guard import managed_render_environment
from material_core import workspace
from material_core.import_helpers import pdf_pages, slugify


ROOT_DIR = workspace.root()
LIBREOFFICE = "libreoffice"
PANDOC = "pandoc"
QUARTO = "quarto"


@dataclass(frozen=True)
class ImportResult:
    source: Path
    qmd: Path
    draft_qmd: Path | None
    source_pdf: Path
    source_pages: int
    rendered_pdf: Path | None
    rendered_pages: int | None


def _relative_to_root(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _run(command: list[str], *, cwd: Path = ROOT_DIR, quiet: bool = False) -> None:
    stdout = subprocess.DEVNULL if quiet else None
    options = {}
    if command[:2] == [QUARTO, "render"]:
        options["env"] = managed_render_environment()
    subprocess.run(command, cwd=cwd, check=True, stdout=stdout, **options)


def _convert_docx_to_pdf(source: Path, output_dir: Path) -> Path:
    _run(
        [
            LIBREOFFICE,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(source),
        ],
        quiet=True,
    )
    pdf_path = output_dir / f"{source.stem}.pdf"
    if not pdf_path.exists():
        candidates = sorted(output_dir.glob("*.pdf"))
        if len(candidates) == 1:
            return candidates[0]
        raise FileNotFoundError(pdf_path)
    return pdf_path


def extract_markdown(source: Path, cwd: Path, media_rel: Path) -> str:
    """Rohe Pandoc-Ausgabe (inkl. moeglichem YAML-Block aus den DOCX-Kerneigenschaften).

    `--extract-media` bekommt bewusst einen relativen Pfad und laeuft mit `cwd=cwd`:
    Mit einem absoluten Pfad schreibt Pandoc auch absolute Bildverweise in den
    Markdown-Body (empirisch verifiziert), die nach dem Verschieben des Medienordners
    an den endgueltigen Ablageort (assets/<slug>/media neben dem Ziel-qmd) ins Leere
    zeigen wuerden. Mit einem relativen Pfad bleibt der Verweis auch nach dem Kopieren
    gueltig, weil Quelle und Ziel dieselbe relative Struktur haben.
    """
    completed = subprocess.run(
        [
            PANDOC,
            str(source),
            "-t",
            "markdown+yaml_metadata_block",
            "--wrap=none",
            f"--extract-media={media_rel.as_posix()}",
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write_page_stable_qmd(
    qmd_path: Path,
    *,
    title: str,
    slug: str,
    source: Path,
    source_pdf: Path,
    source_pages: int,
    draft_qmd: Path | None,
) -> None:
    pdf_reference = source_pdf.relative_to(qmd_path.parent).as_posix()
    draft_reference = draft_qmd.name if draft_qmd else ""
    draft_line = f"    editable-draft: {draft_reference}\n" if draft_reference else ""
    qmd_path.write_text(
        "---\n"
        'title: ""\n'
        "lang: de\n"
        "format:\n"
        "  pdf:\n"
        f"    output-file: {slug}.pdf\n"
        "    keep-tex: true\n"
        "header-includes:\n"
        "  - \\usepackage{pdfpages}\n"
        "material:\n"
        f'  title: "{title}"\n'
        "  import:\n"
        "    kind: onlyoffice\n"
        "    mode: pdfpages\n"
        f"    source: {_relative_to_root(source)}\n"
        f"    source-pages: {source_pages}\n"
        f"{draft_line}"
        "---\n\n"
        f"\\includepdf[pages=-,fitpaper=true]{{{pdf_reference}}}\n",
        encoding="utf-8",
    )


def _write_editable_draft(source: Path, output_dir: Path, slug: str, title: str) -> Path:
    draft_path = output_dir / f"{slug}-entwurf.qmd"
    media_dir = Path("assets") / slug / "media"
    tmp_body = output_dir / f".{slug}-pandoc-body.md"
    _run(
        [
            PANDOC,
            str(source.resolve()),
            "-t",
            "markdown+yaml_metadata_block",
            "--wrap=none",
            f"--extract-media={media_dir.as_posix()}",
            "-o",
            tmp_body.name,
        ],
        cwd=output_dir,
        quiet=True,
    )
    body = tmp_body.read_text(encoding="utf-8").strip()
    tmp_body.unlink()
    draft_path.write_text(
        "---\n"
        f'title: "{title}"\n'
        "lang: de\n"
        "format:\n"
        "  pdf:\n"
        f"    output-file: {slug}-entwurf.pdf\n"
        "    keep-tex: true\n"
        "material:\n"
        "  import:\n"
        "    kind: onlyoffice\n"
        "    mode: pandoc-draft\n"
        f"    source: {_relative_to_root(source)}\n"
        "---\n\n"
        "<!-- Automatisch erzeugter Pandoc-Entwurf. Layout und Seitenzahl sind hier nicht garantiert. -->\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return draft_path


def _relocate_render_artifacts(qmd_path: Path, slug: str) -> Path | None:
    rendered_pdf = qmd_path.parent / f"{slug}.pdf"
    final_pdf: Path | None = None
    output_relpath = qmd_path.parent.relative_to(ROOT_DIR)
    if rendered_pdf.exists():
        pdf_dir = ROOT_DIR / "build" / "pdf" / output_relpath
        pdf_dir.mkdir(parents=True, exist_ok=True)
        final_pdf = pdf_dir / rendered_pdf.name
        if final_pdf.exists():
            final_pdf.unlink()
        shutil.move(str(rendered_pdf), str(final_pdf))
    build_dir = ROOT_DIR / "build" / "artefakte" / output_relpath
    for suffix in (".aux", ".log", ".out", ".tex", ".toc"):
        artifact = qmd_path.parent / f"{slug}{suffix}"
        if artifact.exists():
            build_dir.mkdir(parents=True, exist_ok=True)
            target = build_dir / artifact.name
            if target.exists():
                target.unlink()
            shutil.move(str(artifact), str(target))
    return final_pdf


def _validate_pages(qmd_path: Path, slug: str, source_pages: int) -> tuple[Path, int]:
    _run([QUARTO, "render", str(qmd_path.relative_to(ROOT_DIR))])
    rendered_pdf = _relocate_render_artifacts(qmd_path, slug)
    if rendered_pdf is None:
        raise FileNotFoundError(qmd_path.parent / f"{slug}.pdf")
    rendered_pages = pdf_pages(rendered_pdf)
    if rendered_pages != source_pages:
        raise RuntimeError(
            f"Seitenzahl stimmt nicht: {qmd_path} erzeugt {rendered_pages}, "
            f"Quelle hat {source_pages}"
        )
    return rendered_pdf, rendered_pages


def import_docx(
    source: Path,
    output_dir: Path,
    *,
    overwrite: bool = False,
    draft: bool = True,
    validate: bool = True,
) -> ImportResult:
    source = source.resolve()
    output_dir = output_dir.resolve()
    if source.suffix.lower() != ".docx":
        raise ValueError(f"Nur .docx wird unterstuetzt: {source}")
    if not source.exists():
        raise FileNotFoundError(source)

    slug = slugify(source.stem)
    title = source.stem
    qmd_path = output_dir / f"{slug}.qmd"
    if qmd_path.exists() and not overwrite:
        raise FileExistsError(f"{qmd_path} existiert bereits. Nutze --overwrite.")

    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        converted_pdf = _convert_docx_to_pdf(source, tmp_dir)
        source_pages = pdf_pages(converted_pdf)
        # Das konvertierte PDF liegt neben der DOCX-Quelle (ueblicherweise im
        # _eingang) und wird von dort per `inv pdf-erschliessen` in die
        # Wissensbasis unter wissen/ verschoben.
        source_pdf = source.parent / f"{slug}-original.pdf"
        shutil.copy2(converted_pdf, source_pdf)

    draft_qmd = _write_editable_draft(source, output_dir, slug, title) if draft else None
    _write_page_stable_qmd(
        qmd_path,
        title=title,
        slug=slug,
        source=source,
        source_pdf=source_pdf,
        source_pages=source_pages,
        draft_qmd=draft_qmd,
    )

    rendered_pdf: Path | None = None
    rendered_pages: int | None = None
    if validate:
        rendered_pdf, rendered_pages = _validate_pages(qmd_path, slug, source_pages)

    return ImportResult(
        source=source,
        qmd=qmd_path,
        draft_qmd=draft_qmd,
        source_pdf=source_pdf,
        source_pages=source_pages,
        rendered_pdf=rendered_pdf,
        rendered_pages=rendered_pages,
    )


def _docx_sources(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.docx"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Onlyoffice-DOCX seitenstabil nach QMD importieren.")
    parser.add_argument("source", help="DOCX-Datei oder Ordner mit DOCX-Dateien")
    parser.add_argument("output_dir", help="Zielordner fuer die QMD-Dateien")
    parser.add_argument("--overwrite", action="store_true", help="Vorhandene QMDs ueberschreiben")
    parser.add_argument("--no-draft", action="store_true", help="Keinen editierbaren Pandoc-Entwurf erzeugen")
    parser.add_argument("--no-validate", action="store_true", help="Nicht rendern und Seitenzahl nicht pruefen")
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.is_absolute():
        source = ROOT_DIR / source
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT_DIR / output_dir

    sources = _docx_sources(source)
    if not sources:
        raise SystemExit(f"Keine DOCX-Dateien gefunden: {source}")

    for docx in sources:
        result = import_docx(
            docx,
            output_dir,
            overwrite=args.overwrite,
            draft=not args.no_draft,
            validate=not args.no_validate,
        )
        status = f"{result.source_pages} Seite(n)"
        if result.rendered_pages is not None:
            status += f", validiert: {result.rendered_pages}"
        print(f"+ {result.qmd.relative_to(ROOT_DIR)} ({status})")
        if result.draft_qmd:
            print(f"  Entwurf: {result.draft_qmd.relative_to(ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
