from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from zipfile import ZipFile

from material_core.filesystem import atomic_copy_file, atomic_write_text
from material_core.publication import publish_files, safe_member

from course_sync.classes.platform_sync_state import record_site_export_state
from course_sync.classes.course_secrets import apply_secret_replacements, load_course_secrets, sanitize_h5p_package


class StaticSiteExporter:
    def __init__(self, application) -> None:
        self.application = application

    def _normalize_site_url(self, site_url: str) -> str:
        normalized = site_url.strip().rstrip("/")
        if not normalized:
            return ""
        parsed = urlparse(normalized)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("--site-url muss eine absolute URL sein, z.B. https://courses.example.org")
        return normalized


    def _site_cname(self, site_url: str) -> str:
        parsed = urlparse(site_url)
        return parsed.netloc if parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.path.strip("/") else ""


    def _site_absolute_url(self, site_url: str, path: str = "") -> str:
        if not site_url:
            return ""
        return f"{site_url}/{path.lstrip('/')}" if path else f"{site_url}/"


    def _relative_url(self, from_dir: Path, target: Path) -> str:
        return Path(os.path.relpath(target, from_dir)).as_posix()


    def _file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


    def _write_text_if_changed(self, path: Path, content: str) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text(encoding="utf-8") == content and path.stat().st_mode & 0o777 == 0o644:
            return False
        atomic_write_text(path, content, mode=0o644)
        return True


    def _copy_file_if_changed(self, source_path: Path, target_path: Path) -> bool:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.is_file():
            source_stat = source_path.stat()
            target_stat = target_path.stat()
            if source_stat.st_size == target_stat.st_size and source_stat.st_mtime_ns == target_stat.st_mtime_ns and target_stat.st_mode & 0o777 == 0o644:
                return False
            if source_stat.st_size == target_stat.st_size and self._file_sha256(source_path) == self._file_sha256(target_path) and target_stat.st_mode & 0o777 == 0o644:
                return False
        atomic_copy_file(source_path, target_path)
        target_path.chmod(0o644)
        return True


    def _question_hash(self, question) -> str:
        """Inhalts-Hash fuer den Exportstand; leer, wenn er sich nicht bestimmen laesst."""
        try:
            return str(self.application.compute_question_hash(question) or "")
        except Exception:  # noqa: BLE001 - der Stand ist optional, der Export nicht
            return ""


    def _export_manifest_path(self, output_dir: Path) -> Path:
        return output_dir / ".course-sync-export-manifest.json"


    def _load_export_manifest(self, output_dir: Path) -> set[str]:
        manifest_path = self._export_manifest_path(output_dir)
        if not manifest_path.exists():
            return set()
        safe_member(output_dir, manifest_path.name)
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Ungültiges Exportmanifest: {manifest_path}") from error
        if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("files"), list):
            raise ValueError(f"Ungültiges Exportmanifest: {manifest_path}")
        files = payload["files"]
        if not all(isinstance(relative, str) for relative in files):
            raise ValueError(f"Ungültiges Exportmanifest: {manifest_path}")
        for relative in files:
            if relative == manifest_path.name:
                raise ValueError(f"Exportmanifest darf sich nicht selbst auflisten: {manifest_path}")
            safe_member(output_dir, relative)
        return set(files)

    def _write_export_manifest(self, output_dir: Path, written_paths: Iterable[Path]) -> Path:
        manifest_path = self._export_manifest_path(output_dir)
        resolved_output_dir = output_dir.resolve()
        resolved_manifest_path = manifest_path.resolve()
        files = sorted(
            path.resolve().relative_to(resolved_output_dir).as_posix()
            for path in written_paths
            if path.exists() and path.is_file() and path.resolve() != resolved_manifest_path
        )
        self._write_text_if_changed(manifest_path, json.dumps({"version": 1, "files": files}, ensure_ascii=False, indent=2) + "\n")
        return manifest_path


    def _remove_stale_export_files(self, output_dir: Path, previous_files: set[str], current_paths: Iterable[Path]) -> None:
        resolved_output_dir = output_dir.resolve()
        current_files = {
            path.resolve().relative_to(resolved_output_dir).as_posix()
            for path in current_paths
            if path.exists() and path.is_file()
        }
        for relative_path in sorted(previous_files - current_files, reverse=True):
            stale_path = safe_member(output_dir, relative_path)
            if stale_path.is_file():
                stale_path.unlink()

        for directory in sorted((path for path in output_dir.glob("**/*") if path.is_dir()), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass


    def _safe_extract_h5p(self, package_path: Path, target_dir: Path) -> list[Path]:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        extracted_paths: list[Path] = []
        with ZipFile(package_path) as archive:
            for member in archive.infolist():
                target_path = (target_dir / member.filename).resolve()
                if not target_path.is_relative_to(target_dir.resolve()):
                    raise ValueError(f"Unsicherer Pfad im H5P-Paket {package_path}: {member.filename}")
                if member.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target_path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                extracted_paths.append(target_path)
        return extracted_paths


    def _extract_h5p_if_changed(self, package_path: Path, target_dir: Path) -> list[Path]:
        package_stat = package_path.stat()
        digest_path = target_dir / ".package-sha256"
        metadata_path = target_dir / ".package-meta.json"
        expected_metadata = {"size": package_stat.st_size, "mtimeNs": package_stat.st_mtime_ns}
        if target_dir.is_dir() and metadata_path.is_file():
            try:
                current_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                current_metadata = {}
            if current_metadata == expected_metadata:
                return [path for path in target_dir.rglob("*") if path.is_file()]

        package_digest = self._file_sha256(package_path)
        if target_dir.is_dir() and digest_path.is_file() and digest_path.read_text(encoding="utf-8").strip() == package_digest:
            self._write_text_if_changed(metadata_path, json.dumps(expected_metadata, ensure_ascii=False, sort_keys=True) + "\n")
            return [path for path in target_dir.rglob("*") if path.is_file()]

        extracted_paths = self._safe_extract_h5p(package_path, target_dir)
        self._write_text_if_changed(digest_path, package_digest + "\n")
        self._write_text_if_changed(metadata_path, json.dumps(expected_metadata, ensure_ascii=False, sort_keys=True) + "\n")
        extracted_paths.append(digest_path)
        extracted_paths.append(metadata_path)
        return extracted_paths


    def _read_h5p_title(self, package_path: Path, fallback: str) -> str:
        try:
            with ZipFile(package_path) as archive:
                payload = json.loads(archive.read("h5p.json").decode("utf-8"))
            return str(payload.get("title") or fallback)
        except Exception:
            return fallback


    def _installed_h5p_library_machine_names(self) -> set[str]:
        names: set[str] = set()
        for library_dir in (self.application.ROOT_DIR / ".h5p-runtime" / "libraries").glob("*-*"):
            library_json = library_dir / "library.json"
            if not library_json.is_file():
                continue
            try:
                payload = json.loads(library_json.read_text(encoding="utf-8"))
            except Exception:
                continue
            machine_name = str(payload.get("machineName") or "").strip()
            if machine_name:
                names.add(machine_name)
        return names


    def _write_static_h5p_player(self, player_path: Path, *, title: str, content_dir: Path, package_href: str) -> None:
        player_dir = player_path.parent
        h5p_json_path = self._relative_url(player_dir, content_dir)
        escaped_title = html.escape(title)
        escaped_package_href = html.escape(package_href, quote=True)
        options = json.dumps(
            {
                "h5pJsonPath": h5p_json_path,
                "frameJs": "https://cdn.jsdelivr.net/npm/h5p-standalone@3.8.2/dist/frame.bundle.js",
                "frameCss": "https://cdn.jsdelivr.net/npm/h5p-standalone@3.8.2/dist/styles/h5p.css",
                "frame": True,
                "export": True,
                "downloadUrl": package_href,
                "fullScreen": True,
            },
            ensure_ascii=False,
        )
        self._write_text_if_changed(
            player_path,
            f"""<!doctype html>
    <html lang=\"de\">
      <head>
        <meta charset=\"utf-8\">
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
        <title>{escaped_title}</title>
        <link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/h5p-standalone@3.8.2/dist/styles/h5p.css\">
        <style>
          :root {{ color-scheme: light; --page: #f6f8fb; --surface: #fff; --ink: #172033; --muted: #64748b; --accent: #2563eb; --border: #d8dee8; }}
          html, body {{ margin: 0; min-height: 100%; background: var(--page); color: var(--ink); }}
          body {{ font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif; }}
          .activity-header {{ border-bottom: 1px solid var(--border); background: rgba(255,255,255,0.96); }}
          .activity-header-inner {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 14px 0; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 14px; }}
          .activity-download {{ display: inline-flex; align-items: center; justify-content: center; min-height: 34px; padding: 6px 11px; border-radius: 7px; border: 1px solid var(--border); background: #fff; color: var(--muted); text-decoration: none; font-size: 0.9rem; font-weight: 620; }}
          .activity-download {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
          .activity-title {{ min-width: 0; margin: 0; font-size: 1rem; line-height: 1.25; font-weight: 720; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
          .activity-frame {{ width: min(1180px, calc(100% - 32px)); margin: 18px auto 42px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); overflow: hidden; }}
          #h5p-container {{ width: 100%; min-height: 760px; }}
          .h5p-iframe-wrapper iframe {{ min-height: 680px; }}
          @media (max-width: 720px) {{ .activity-header-inner {{ grid-template-columns: 1fr; align-items: start; }} .activity-title {{ white-space: normal; }} .activity-frame {{ width: calc(100% - 20px); margin-top: 10px; }} #h5p-container {{ min-height: 680px; }} }}
        </style>
      </head>
      <body>
        <header class=\"activity-header\">
          <div class=\"activity-header-inner\">
            <h1 class=\"activity-title\">{escaped_title}</h1>
            <a class=\"activity-download\" href=\"{escaped_package_href}\" download>Download</a>
          </div>
        </header>
        <main class=\"activity-frame\">
          <div id=\"h5p-container\"></div>
        </main>
        <script src=\"https://cdn.jsdelivr.net/npm/h5p-standalone@3.8.2/dist/main.bundle.js\" charset=\"UTF-8\"></script>
        <script>
          new H5PStandalone.H5P(document.getElementById(\"h5p-container\"), {options});
        </script>
      </body>
    </html>
    """,
        )


    def export_static_site(self, output_dir: Path, course_dir: Path | list[Path] | None = None, site_url: str = "") -> list[Path]:
        output = output_dir.resolve()
        courses = course_dir if isinstance(course_dir, list) else [course_dir] if course_dir is not None else self.application.list_course_dirs()
        root = self.application.ROOT_DIR.resolve()
        courses_dir = self.application.COURSES_DIR.resolve()
        build_dir = courses_dir / "build"
        protected = [
            *courses,
            *(root / name for name in ("src", "wissen", "ressourcen", "wheels")),
            *(root / "unterricht" / name for name in ("informatik", "mathematik", "organisation", "sachkunde")),
        ]
        if (
            root.is_relative_to(output)
            or output == courses_dir
            or (output.is_relative_to(courses_dir) and not output.is_relative_to(build_dir))
            or any(output.is_relative_to(path.resolve()) or path.resolve().is_relative_to(output) for path in protected)
        ):
            raise ValueError(f"Export-Zielordner darf kein Projekt- oder Kurs-Quellordner sein: {output_dir}")
        if output_dir.is_symlink():
            raise ValueError("Export-Zielordner darf kein Symlink sein.")
        if output.exists() and not output.is_dir():
            raise ValueError("Export-Zielordner ist kein Verzeichnis.")
        manifest = self._export_manifest_path(output).name
        if output.is_dir() and any(output.iterdir()) and not (output / manifest).is_file():
            raise ValueError(f"Export-Zielordner ist nicht leer und besitzt kein Exportmanifest: {output_dir}")
        previous = self._load_export_manifest(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with self.application.WORKSPACE_LOCK, tempfile.TemporaryDirectory(dir=output.parent, prefix=".course-export-") as temporary:
            for stale in sorted(output.parent.glob(".course-export-*")):
                if stale.is_dir() and stale != Path(temporary):
                    shutil.rmtree(stale, ignore_errors=True)
            staging = Path(temporary) / "site"
            staging.mkdir()
            for relative in previous | ({manifest} if (output / manifest).is_file() else set()):
                existing = safe_member(output, relative)
                if existing.is_file():
                    target = safe_member(staging, relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        os.link(existing, target)
                    except OSError:
                        shutil.copy2(existing, target)
            export_state: dict[str, dict[str, str]] = {}
            written = self._render_site(staging, course_dir, site_url, export_state)
            current = self._load_export_manifest(staging)
            if "index.html" not in current:
                raise ValueError("Export enthält keine Startseite.")
            output.mkdir(exist_ok=True)
            publish_files(staging, output, previous, current, manifest)
            try:
                record_site_export_state(self.application.COURSE_BUILD_DIR, output, export_state)
            except OSError:
                pass  # Der Stand ist nur Anzeige; ein voller Datentraeger darf den Export nicht kippen.
            return [output_dir / path.relative_to(staging) for path in written]

    def _render_site(
        self,
        output_dir: Path,
        course_dir: Path | list[Path] | None = None,
        site_url: str = "",
        export_state: dict[str, dict[str, str]] | None = None,
    ) -> list[Path]:
        normalized_site_url = self._normalize_site_url(site_url)
        if isinstance(course_dir, list):
            target_course_dirs = course_dir
        elif course_dir is not None:
            target_course_dirs = [course_dir]
        else:
            target_course_dirs = [item for item in self.application.list_course_dirs() if (item / "index.mdx").exists()]
        if not target_course_dirs:
            raise FileNotFoundError("Keine Kurse für den statischen Export gefunden.")

        previous_manifest_files = self._load_export_manifest(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_text_if_changed(output_dir / ".nojekyll", "")

        written_paths: list[Path] = [output_dir / ".nojekyll"]
        manifest_paths: list[Path] = [output_dir / ".nojekyll"]
        cname = self._site_cname(normalized_site_url)
        if cname:
            cname_path = output_dir / "CNAME"
            self._write_text_if_changed(cname_path, cname + "\n")
            written_paths.append(cname_path)
            manifest_paths.append(cname_path)

        # Inhalts-Hash je exportierter Aktivitaet: Grundlage der Sync-Uebersicht. Der Aufrufer
        # speichert ihn erst, wenn der Export veroeffentlicht ist.
        if export_state is None:
            export_state = {}
        for target_course_dir in target_course_dirs:
            _, ordered_questions, rendered_source = self.application.parse_course(target_course_dir)
            # Die statische Website ist oeffentlich: Kurs-Secrets (z. B. Namen) werden
            # immer durch die neutralen Ersetzungen aus course.yml ersetzt.
            course_secrets = load_course_secrets(target_course_dir)
            unavailable_questions: dict[str, str] = {}
            installed_libraries = self._installed_h5p_library_machine_names()
            for question in ordered_questions:
                if question.main_library and question.main_library not in installed_libraries:
                    unavailable_questions[question.identifier] = (
                        f"H5P-Library '{question.main_library}' wurde lokal nicht gefunden."
                    )
                    continue
                try:
                    self.application.write_h5p_package(question)
                except FileNotFoundError as error:
                    if "H5P-Library" not in str(error):
                        raise
                    unavailable_questions[question.identifier] = str(error)

            course_site_dir = output_dir / "courses" / target_course_dir.name
            h5p_site_dir = output_dir / "h5p" / target_course_dir.name
            h5p_content_site_dir = output_dir / "h5p-content" / target_course_dir.name
            h5p_player_site_dir = output_dir / "h5p-player" / target_course_dir.name
            course_site_dir.mkdir(parents=True, exist_ok=True)
            h5p_site_dir.mkdir(parents=True, exist_ok=True)
            h5p_content_site_dir.mkdir(parents=True, exist_ok=True)
            h5p_player_site_dir.mkdir(parents=True, exist_ok=True)

            copied_packages: dict[str, str] = {}
            copied_players: dict[str, str] = {}
            exported_hashes = export_state.setdefault(target_course_dir.name, {})
            for question in ordered_questions:
                if question.identifier in unavailable_questions:
                    continue
                if not question.package_path.is_file():
                    raise FileNotFoundError(f"H5P-Paket für '{question.identifier}' wurde nicht gebaut: {question.package_path}")
                package_source = question.package_path
                if course_secrets:
                    package_source = sanitize_h5p_package(
                        question.package_path,
                        course_secrets,
                        self.application.course_build_dir(target_course_dir) / "h5p-sanitized" / "site" / question.package_path.name,
                    )
                relative_package_path = (
                    Path(question.h5p_subdir) / package_source.name
                    if question.h5p_subdir
                    else Path(package_source.name)
                )
                target_package_path = h5p_site_dir / relative_package_path
                self._copy_file_if_changed(package_source, target_package_path)
                copied_packages[question.identifier] = f"../../h5p/{target_course_dir.name}/{relative_package_path.as_posix()}"
                written_paths.append(target_package_path)
                manifest_paths.append(target_package_path)

                relative_content_path = relative_package_path.with_suffix("")
                target_content_dir = h5p_content_site_dir / relative_content_path
                manifest_paths.extend(self._extract_h5p_if_changed(package_source, target_content_dir))

                target_player_path = h5p_player_site_dir / relative_content_path / "index.html"
                self._write_static_h5p_player(
                    target_player_path,
                    title=self._read_h5p_title(package_source, question.title),
                    content_dir=target_content_dir,
                    package_href=self._relative_url(target_player_path.parent, target_package_path),
                )
                copied_players[question.identifier] = self._relative_url(course_site_dir, target_player_path)
                written_paths.append(target_player_path)
                manifest_paths.append(target_player_path)
                exported_hashes[question.identifier] = self._question_hash(question)

            html_content = self.application.render_course_page(
                target_course_dir,
                questions=ordered_questions,
                rendered_source=rendered_source,
                package_href_builder=lambda question: copied_packages.get(question.identifier, ""),
                player_href_builder=lambda question: copied_players.get(question.identifier, ""),
                canonical_url=self._site_absolute_url(normalized_site_url, f"courses/{target_course_dir.name}/"),
                home_href="../../index.html",
            )
            if course_secrets:
                html_content = apply_secret_replacements(html_content, course_secrets)
            course_index_path = course_site_dir / "index.html"
            self._write_text_if_changed(course_index_path, html_content + "\n")
            written_paths.append(course_index_path)
            manifest_paths.append(course_index_path)

        index_path = output_dir / "index.html"
        self._write_text_if_changed(
            index_path,
            self.application.template_renderer().render_index(
                target_course_dirs,
                static=True,
                canonical_url=self._site_absolute_url(normalized_site_url),
            )
            + "\n"
        )
        written_paths.append(index_path)
        manifest_paths.append(index_path)

        wheels_dir = self.application.ROOT_DIR / "wheels"
        if wheels_dir.is_dir():
            for source_path in sorted(wheels_dir.glob("*.whl")):
                target_path = output_dir / "wheels" / source_path.name
                self._copy_file_if_changed(source_path, target_path)
                written_paths.append(target_path)
                manifest_paths.append(target_path)

        manifest_path = self._write_export_manifest(output_dir, manifest_paths)
        manifest_paths.append(manifest_path)
        self._remove_stale_export_files(output_dir, previous_manifest_files, manifest_paths)
        return written_paths
