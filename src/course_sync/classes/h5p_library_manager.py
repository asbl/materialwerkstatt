from __future__ import annotations

import json
import shutil
import subprocess
import threading
from http import HTTPStatus
from pathlib import Path
from typing import Callable, TypedDict
from urllib.parse import quote
from urllib.error import HTTPError
from zipfile import BadZipFile, ZipFile


class H5PLibraryAssetSpec(TypedDict):
    machineName: str
    assetPrefix: str
    releaseRepo: str
    releaseTag: str


class H5PLibraryManager:
    """Manages local H5P runtime libraries and their dependencies."""

    def __init__(
        self,
        *,
        workspace_lock: threading.RLock,
        runtime_dir: Path,
        runtime_content_dir: Path,
        runtime_libraries_dir: Path,
        runtime_downloads_dir: Path,
        shared_libraries_dir: Path,
        courses_dir: Path,
        release_repo: str,
        release_tag: str,
        asset_prefixes: dict[str, str],
        custom_short_names: dict[str, str],
        ensure_directory: Callable[[Path], None],
        read_json: Callable[[Path], dict],
        read_json_or_default: Callable[[Path, dict], dict],
        write_json: Callable[[Path, dict], None],
        fetch_json: Callable[[str], dict],
        download_file: Callable[[str, Path], None],
        run_cli_command: Callable[[list[str], Path], subprocess.CompletedProcess[str]] | None = None,
        resolve_cli_command: Callable[[], list[str]] | None = None,
        extra_assets: list[dict[str, str]] | None = None,
    ) -> None:
        self._workspace_lock = workspace_lock
        self._runtime_dir = runtime_dir
        self._runtime_content_dir = runtime_content_dir
        self._runtime_libraries_dir = runtime_libraries_dir
        self._runtime_downloads_dir = runtime_downloads_dir
        self._shared_libraries_dir = shared_libraries_dir
        self._courses_dir = courses_dir
        self._release_repo = release_repo
        self._release_tag = release_tag
        self._asset_prefixes = asset_prefixes
        self._custom_short_names = custom_short_names
        self._ensure_directory = ensure_directory
        self._read_json = read_json
        self._read_json_or_default = read_json_or_default
        self._write_json = write_json
        self._fetch_json = fetch_json
        self._download_file = download_file
        self._run_cli_command = run_cli_command
        self._resolve_cli_command = resolve_cli_command
        self._extra_assets = extra_assets or []
        self._runtime_libraries_ready = False

    def find_downloaded_asset(self, asset_prefix: str) -> Path | None:
        matches = sorted(self._runtime_downloads_dir.glob(f"{asset_prefix}*.h5p"))
        if not matches:
            return None
        return matches[-1]

    def release_metadata_cache_path(self) -> Path:
        return self._release_metadata_cache_path_for(self._release_repo, self._release_tag)

    def _release_metadata_cache_path_for(self, release_repo: str, release_tag: str) -> Path:
        safe_repo = release_repo.replace("/", "-")
        if release_repo == self._release_repo and release_tag == self._release_tag:
            return self._runtime_downloads_dir / f"release-{release_tag}.json"
        return self._runtime_downloads_dir / f"release-{safe_repo}-{release_tag}.json"

    def load_release_assets(self) -> dict[str, str]:
        return self.load_release_assets_for(self._release_repo, self._release_tag)

    def load_release_assets_for(self, release_repo: str, release_tag: str) -> dict[str, str]:
        cache_path = self._release_metadata_cache_path_for(release_repo, release_tag)
        cached_release = self._read_json_or_default(cache_path, {})
        if cached_release:
            return {asset["name"]: asset["browser_download_url"] for asset in cached_release.get("assets", [])}

        try:
            release = self._fetch_json(
                f"https://api.github.com/repos/{release_repo}/releases/tags/{release_tag}"
            )
        except HTTPError as error:
            if error.code == HTTPStatus.FORBIDDEN:
                raise RuntimeError(
                    "GitHub API Rate-Limit erreicht und keine lokale Release-Metadatenkopie gefunden. "
                    "Falls die Libraries schon einmal geladen wurden, reicht ein vorhandener Inhalt in .h5p-runtime/downloads/."
                ) from error
            raise

        self._write_json(cache_path, release)
        return {asset["name"]: asset["browser_download_url"] for asset in release.get("assets", [])}

    def load_github_release(self, tag: str | None = None) -> dict:
        return self.load_github_release_for(self._release_repo, tag)

    def load_github_release_for(self, release_repo: str, tag: str | None = None) -> dict:
        endpoint = f"releases/tags/{tag}" if tag else "releases/latest"
        try:
            return self._fetch_json(f"https://api.github.com/repos/{release_repo}/{endpoint}")
        except HTTPError as error:
            if error.code == HTTPStatus.FORBIDDEN:
                raise RuntimeError("GitHub API Rate-Limit erreicht. Bitte spaeter erneut versuchen.") from error
            raise

    def _library_asset_specs(self) -> list[H5PLibraryAssetSpec]:
        specs: list[H5PLibraryAssetSpec] = [
            {
                "machineName": machine_name,
                "assetPrefix": asset_prefix,
                "releaseRepo": self._release_repo,
                "releaseTag": self._release_tag,
            }
            for machine_name, asset_prefix in self._asset_prefixes.items()
        ]
        for extra_asset in self._extra_assets:
            machine_name = str(extra_asset.get("machineName") or "").strip()
            asset_prefix = str(extra_asset.get("assetPrefix") or "").strip()
            if not machine_name or not asset_prefix:
                continue
            specs.append(
                {
                    "machineName": machine_name,
                    "assetPrefix": asset_prefix,
                    "releaseRepo": str(extra_asset.get("releaseRepo") or self._release_repo),
                    "releaseTag": str(extra_asset.get("releaseTag") or self._release_tag),
                }
            )
        return specs

    def _library_dir_prefix_for_asset_prefix(self, asset_prefix: str) -> str:
        return asset_prefix.split("_", 1)[0]

    def _has_runtime_library_for_asset_prefix(self, asset_prefix: str) -> bool:
        machine_name = self._library_dir_prefix_for_asset_prefix(asset_prefix).rsplit("-", 1)[0]
        for library_json_path in self._runtime_libraries_dir.glob(f"{machine_name}-*/library.json"):
            try:
                if self._read_json(library_json_path).get("machineName") == machine_name:
                    return True
            except Exception:
                continue
        return False

    def _asset_prefix_for_latest_release(self, machine_name: str) -> str:
        configured_prefix = self._asset_prefixes.get(machine_name, "")
        if configured_prefix:
            return configured_prefix.split("_", 1)[0].rsplit("-", 1)[0] + "-"
        return f"{machine_name}-"

    def _find_release_asset_name(
        self,
        assets: dict[str, str],
        machine_name: str,
        asset_prefix: str | None = None,
    ) -> str:
        prefix = asset_prefix or self._asset_prefix_for_latest_release(machine_name)
        candidates = sorted(name for name in assets if name.startswith(prefix) and name.endswith(".h5p"))
        if not candidates:
            raise RuntimeError(f"Release-Asset fuer {machine_name} mit Praefix '{prefix}' wurde nicht gefunden.")
        return candidates[-1]

    def _remove_library_dirs_for_machine_name(self, root: Path, machine_name: str) -> None:
        for library_dir in sorted(root.glob(f"{machine_name}-*")):
            if library_dir.is_dir():
                shutil.rmtree(library_dir)

    def _ensure_versioned_copy(
        self,
        *,
        source_name: str,
        target_name: str,
        minor_version: int,
        dependency_updates: dict[str, int] | None = None,
    ) -> None:
        source_dir = self._runtime_libraries_dir / source_name
        target_dir = self._runtime_libraries_dir / target_name
        if target_dir.exists() or not source_dir.is_dir():
            return

        shutil.copytree(source_dir, target_dir)
        library_json_path = target_dir / "library.json"
        library_json = self._read_json(library_json_path)
        library_json["minorVersion"] = minor_version
        dependency_updates = dependency_updates or {}
        dependencies = library_json.get("preloadedDependencies")
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if not isinstance(dependency, dict):
                    continue
                machine_name = str(dependency.get("machineName") or "")
                if machine_name in dependency_updates:
                    dependency["minorVersion"] = dependency_updates[machine_name]
        self._write_json(library_json_path, library_json)

    def ensure_python_question_multiple_choice_runtime_fix(self) -> None:
        """Create cache-busting runtime copies for the fixed MC scorer.

        Moodle keeps already-installed H5P libraries by machine/version. The
        multiple-choice scorer was fixed in the bundled JS while the local
        package still used the previous H5P minor versions, so Moodle could keep
        serving the stale scorer. These local versioned copies force packages to
        request fresh library versions without requiring the ignored runtime
        directories to be committed.
        """
        self._ensure_versioned_copy(
            source_name="H5P.CodeQuestion-6.109",
            target_name="H5P.CodeQuestion-6.110",
            minor_version=110,
        )
        self._ensure_versioned_copy(
            source_name="H5P.PythonQuestion-6.115",
            target_name="H5P.PythonQuestion-6.116",
            minor_version=116,
            dependency_updates={"H5P.CodeQuestion": 110},
        )

    def _extract_library_root_from_archive_to(self, archive: ZipFile, library_root: str, destination_root: Path) -> Path:
        destination = destination_root / Path(library_root).name
        if destination.exists():
            shutil.rmtree(destination)

        extracted_root = False
        for member in archive.namelist():
            normalized = member.strip("/")
            if not normalized or not normalized.startswith(f"{library_root}/"):
                continue

            relative_path = Path(normalized).relative_to(library_root)
            if not relative_path.parts or relative_path.parts[0] == "content":
                continue

            target_path = destination / relative_path
            if normalized.endswith("/"):
                self._ensure_directory(target_path)
                continue

            self._ensure_directory(target_path.parent)
            with archive.open(member) as source, target_path.open("wb") as target:
                shutil.copyfileobj(source, target)
            extracted_root = True

        if not extracted_root:
            raise RuntimeError(f"Die Library '{Path(library_root).name}' konnte nicht aus dem Archiv extrahiert werden.")

        return destination

    def extract_library_asset_to(self, archive_path: Path, machine_name: str, destination_root: Path) -> Path:
        with ZipFile(archive_path) as archive:
            library_root = None
            for member in archive.namelist():
                normalized = member.strip("/")
                if not normalized.endswith("/library.json"):
                    continue
                metadata = json.loads(archive.read(member).decode("utf-8"))
                if metadata.get("machineName") == machine_name:
                    library_root = normalized.rsplit("/", 1)[0]
                    break

            if library_root is None:
                raise RuntimeError(f"Kein library.json fuer {machine_name} in {archive_path.name} gefunden.")
            return self._extract_library_root_from_archive_to(archive, library_root, destination_root)

    def update_custom_libraries_from_github(self, tag: str | None = None) -> list[dict[str, str]]:
        with self._workspace_lock:
            self._ensure_directory(self._runtime_downloads_dir)
            self._ensure_directory(self._runtime_libraries_dir)
            self._ensure_directory(self._shared_libraries_dir)

            default_tag = tag
            release_cache: dict[tuple[str, str], dict] = {}
            assets_cache: dict[tuple[str, str], dict[str, str]] = {}

            updated: list[dict[str, str]] = []
            for spec in self._library_asset_specs():
                machine_name = spec["machineName"]
                release_repo = spec["releaseRepo"]
                is_default_spec = (
                    release_repo == self._release_repo
                    and self._asset_prefixes.get(machine_name) == spec["assetPrefix"]
                )
                requested_tag = default_tag if is_default_spec else spec["releaseTag"]
                release_key = (release_repo, requested_tag)
                if release_key not in release_cache:
                    release_cache[release_key] = self.load_github_release_for(release_repo, requested_tag)
                    assets_cache[release_key] = {
                        asset["name"]: asset["browser_download_url"]
                        for asset in release_cache[release_key].get("assets", [])
                        if isinstance(asset, dict) and asset.get("name") and asset.get("browser_download_url")
                    }
                    if not assets_cache[release_key]:
                        actual_tag = str(release_cache[release_key].get("tag_name") or requested_tag or "latest")
                        raise RuntimeError(f"GitHub-Release {actual_tag} enthaelt keine downloadbaren Assets.")

                release = release_cache[release_key]
                release_tag = str(release.get("tag_name") or requested_tag or "latest")
                assets = assets_cache[release_key]
                asset_prefix = None
                if not is_default_spec:
                    asset_prefix = spec["assetPrefix"]
                asset_name = self._find_release_asset_name(assets, machine_name, asset_prefix)
                archive_path = self._runtime_downloads_dir / asset_name
                if not archive_path.exists():
                    self._download_file(assets[asset_name], archive_path)

                self._remove_library_dirs_for_machine_name(self._shared_libraries_dir, machine_name)
                self._remove_library_dirs_for_machine_name(self._runtime_libraries_dir, machine_name)
                shared_library_dir = self.extract_library_asset_to(archive_path, machine_name, self._shared_libraries_dir)
                runtime_library_dir = self._copy_library_dir_to_runtime(shared_library_dir)
                self.register_local_library(runtime_library_dir)
                updated.append(
                    {
                        "machineName": machine_name,
                        "asset": asset_name,
                        "release": release_tag,
                        "path": str(shared_library_dir),
                    }
                )

            self.ensure_registered_local_libraries()
            return updated

    def _find_local_export_asset(self, export_dir: Path, machine_name: str) -> Path | None:
        """Findet die neueste .h5p-Datei einer Library im lokalen h5p-dev-Export-Ordner.

        Export-Dateinamen haben die Form ``<MachineName>-<major>.<minor>_<Zeitstempel>.h5p``.
        Gewaehlt wird die hoechste Version; bei Gleichstand die juengste Datei.
        """
        candidates: list[tuple[tuple[int, int], float, Path]] = []
        for archive_path in export_dir.glob(f"{machine_name}-*.h5p"):
            version_part = archive_path.name[len(machine_name) + 1 :].split("_", 1)[0]
            try:
                major, minor = (int(part) for part in version_part.split(".", 1))
            except ValueError:
                continue
            candidates.append(((major, minor), archive_path.stat().st_mtime, archive_path))
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], item[1]))[2]

    def update_custom_libraries_from_local_export(self, export_dir: Path) -> list[dict[str, str]]:
        """Installiert die neuesten Library-Versionen aus einem lokalen h5p-dev-Export.

        Anders als ``update_custom_libraries_from_github`` wird kein GitHub-Release
        benoetigt: pro konfigurierter Custom-Library wird die neueste
        ``.h5p``-Datei aus dem Export-Ordner installiert. Libraries, fuer die der
        Ordner keine Datei enthaelt, werden uebersprungen.
        """
        export_dir = Path(export_dir).expanduser()
        if not export_dir.is_dir():
            raise RuntimeError(f"Export-Ordner '{export_dir}' wurde nicht gefunden.")

        with self._workspace_lock:
            self._ensure_directory(self._runtime_libraries_dir)
            self._ensure_directory(self._shared_libraries_dir)

            updated: list[dict[str, str]] = []
            for spec in self._library_asset_specs():
                machine_name = spec["machineName"]
                archive_path = self._find_local_export_asset(export_dir, machine_name)
                if archive_path is None:
                    continue

                self._remove_library_dirs_for_machine_name(self._shared_libraries_dir, machine_name)
                self._remove_library_dirs_for_machine_name(self._runtime_libraries_dir, machine_name)
                shared_library_dir = self.extract_library_asset_to(archive_path, machine_name, self._shared_libraries_dir)
                runtime_library_dir = self._copy_library_dir_to_runtime(shared_library_dir)
                self.register_local_library(runtime_library_dir)
                updated.append(
                    {
                        "machineName": machine_name,
                        "asset": archive_path.name,
                        "release": archive_path.stem,
                        "path": str(shared_library_dir),
                    }
                )

            if not updated:
                raise RuntimeError(f"Im Export-Ordner '{export_dir}' wurden keine passenden H5P-Libraries gefunden.")

            updated.extend(self._install_missing_dependencies_from_local_export(export_dir, updated))
            self.ensure_registered_local_libraries()
            return updated

    def _install_missing_dependencies_from_local_export(
        self,
        export_dir: Path,
        installed: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Installiert Abhaengigkeiten der frisch installierten Libraries, die nur im Export liegen.

        Ein h5p-dev-Paket enthaelt genau eine Library; Hilfsbibliotheken wie
        ``H5P.LibMathTools`` stehen in keiner Release-Konfiguration und fehlten sonst im
        Runtime-Ordner, sodass der Paketbau mit "Library nicht gefunden" abbrach.
        """
        extra: list[dict[str, str]] = []
        known = {entry["machineName"] for entry in installed}
        pending = [Path(entry["path"]) for entry in installed]
        while pending:
            library_json_path = pending.pop() / "library.json"
            if not library_json_path.is_file():
                continue
            library_data = self._read_json(library_json_path)
            for key in ("preloadedDependencies", "dynamicDependencies", "editorDependencies"):
                for dependency in library_data.get(key, []):
                    machine_name = str(dependency.get("machineName") or "").strip()
                    if not machine_name or machine_name in known:
                        continue
                    known.add(machine_name)
                    if self._has_runtime_library_for_asset_prefix(f"{machine_name}-0_"):
                        continue
                    archive_path = self._find_local_export_asset(export_dir, machine_name)
                    if archive_path is None:
                        continue
                    shared_library_dir = self.extract_library_asset_to(
                        archive_path, machine_name, self._shared_libraries_dir
                    )
                    runtime_library_dir = self._copy_library_dir_to_runtime(shared_library_dir)
                    self.register_local_library(runtime_library_dir)
                    extra.append(
                        {
                            "machineName": machine_name,
                            "asset": archive_path.name,
                            "release": archive_path.stem,
                            "path": str(shared_library_dir),
                        }
                    )
                    pending.append(shared_library_dir)
        return extra

    def get_h5p_cli_command(self) -> list[str]:
        if self._resolve_cli_command is not None:
            return self._resolve_cli_command()

        h5p_binary = shutil.which("h5p")
        if h5p_binary:
            return [h5p_binary]

        npx_binary = shutil.which("npx")
        if npx_binary:
            return [npx_binary, "--yes", "h5p-cli"]

        raise RuntimeError(
            "Für vollständige H5P-Pakete benötigt course_sync entweder 'h5p' oder 'npx' im PATH."
        )

    def run_h5p_cli(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if self._run_cli_command is not None:
            return self._run_cli_command(args, cwd)
        return subprocess.run(
            [*self.get_h5p_cli_command(), *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )

    def _find_installed_library_dir(
        self,
        machine_name: str,
        major_version: int | None = None,
        minor_version: int | None = None,
    ) -> Path:
        if major_version is not None and minor_version is not None:
            candidate = self._runtime_libraries_dir / f"{machine_name}-{major_version}.{minor_version}"
            if candidate.exists():
                return candidate

        matches = sorted(self._runtime_libraries_dir.glob(f"{machine_name}-*"))
        if not matches:
            raise FileNotFoundError(
                f"H5P-Library '{machine_name}' wurde in {self._runtime_libraries_dir} nicht gefunden."
            )

        if major_version is None or minor_version is None:
            versioned_matches: list[tuple[int, int, Path]] = []
            for candidate in matches:
                metadata = self._read_json(candidate / "library.json")
                major = metadata.get("majorVersion")
                minor = metadata.get("minorVersion")
                if metadata.get("machineName") == machine_name and isinstance(major, int) and isinstance(minor, int):
                    versioned_matches.append((major, minor, candidate))
            if versioned_matches:
                return max(versioned_matches, key=lambda item: (item[0], item[1]))[2]
            return matches[-1]

        for candidate in matches:
            metadata = self._read_json(candidate / "library.json")
            if metadata.get("majorVersion") == major_version and metadata.get("minorVersion") == minor_version:
                return candidate

        return matches[-1]

    def _library_matches_requested_version(
        self,
        library_dir: Path,
        major_version: int | None = None,
        minor_version: int | None = None,
    ) -> bool:
        if major_version is None or minor_version is None:
            return True

        library_json = library_dir / "library.json"
        if not library_json.exists():
            return False

        metadata = self._read_json(library_json)
        return metadata.get("majorVersion") == major_version and metadata.get("minorVersion") == minor_version

    def _copy_library_dir_to_runtime(self, library_dir: Path) -> Path:
        destination = self._runtime_libraries_dir / library_dir.name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(library_dir, destination)
        return destination

    def _install_library_from_github_archive(self, *, org: str, repo: str, tag: str, destination: str) -> Path:
        self._ensure_directory(self._runtime_downloads_dir)
        self._ensure_directory(self._shared_libraries_dir)
        self._ensure_directory(self._runtime_libraries_dir)
        archive_path = self._runtime_downloads_dir / f"{repo}-{tag}.zip"
        if not archive_path.exists():
            encoded_tag = quote(tag, safe="")
            self._download_file(
                f"https://github.com/{org}/{repo}/archive/refs/tags/{encoded_tag}.zip",
                archive_path,
            )

        shared_destination = self._shared_libraries_dir / destination
        if shared_destination.exists():
            shutil.rmtree(shared_destination)

        with ZipFile(archive_path) as archive:
            names = [name.strip("/") for name in archive.namelist() if name.strip("/")]
            roots = {Path(name).parts[0] for name in names if Path(name).parts}
            if len(roots) != 1:
                raise RuntimeError(f"GitHub-Archiv {archive_path.name} enthaelt keine eindeutige Library-Wurzel.")
            archive_root = roots.pop()
            for member in archive.namelist():
                normalized = member.strip("/")
                if not normalized or not normalized.startswith(f"{archive_root}/"):
                    continue
                relative_path = Path(normalized).relative_to(archive_root)
                if not relative_path.parts:
                    continue
                target_path = shared_destination / relative_path
                if member.endswith("/"):
                    self._ensure_directory(target_path)
                    continue
                self._ensure_directory(target_path.parent)
                with archive.open(member) as source, target_path.open("wb") as target:
                    shutil.copyfileobj(source, target)

        runtime_destination = self._copy_library_dir_to_runtime(shared_destination)
        self.register_local_library(runtime_destination)
        return runtime_destination

    def _extract_library_root_from_archive(self, archive: ZipFile, library_root: str) -> Path:
        destination = self._runtime_libraries_dir / Path(library_root).name
        if destination.exists():
            shutil.rmtree(destination)

        extracted_root = False
        for member in archive.namelist():
            normalized = member.strip("/")
            if not normalized or not normalized.startswith(f"{library_root}/"):
                continue

            relative_path = Path(normalized).relative_to(library_root)
            if not relative_path.parts or relative_path.parts[0] == "content":
                continue

            target_path = destination / relative_path
            if normalized.endswith("/"):
                self._ensure_directory(target_path)
                continue

            self._ensure_directory(target_path.parent)
            with archive.open(member) as source, target_path.open("wb") as target:
                shutil.copyfileobj(source, target)
            extracted_root = True

        if not extracted_root:
            raise RuntimeError(f"Die Library '{Path(library_root).name}' konnte nicht aus dem Archiv extrahiert werden.")

        return destination

    def _seed_library_from_shared_libraries(
        self,
        machine_name: str,
        major_version: int | None = None,
        minor_version: int | None = None,
    ) -> Path | None:
        if not self._shared_libraries_dir.exists():
            return None

        if major_version is not None and minor_version is not None:
            exact_match = self._shared_libraries_dir / f"{machine_name}-{major_version}.{minor_version}"
            if exact_match.exists() and self._library_matches_requested_version(exact_match, major_version, minor_version):
                return self._copy_library_dir_to_runtime(exact_match)

        matches = sorted(self._shared_libraries_dir.glob(f"{machine_name}-*"))
        for candidate in matches:
            if self._library_matches_requested_version(candidate, major_version, minor_version):
                return self._copy_library_dir_to_runtime(candidate)

        if matches and (major_version is None or minor_version is None):
            return self._copy_library_dir_to_runtime(matches[-1])

        if matches and major_version is not None:
            for candidate in reversed(matches):
                try:
                    lib_meta = self._read_json(candidate / "library.json")
                    if lib_meta.get("majorVersion") == major_version:
                        return self._copy_library_dir_to_runtime(candidate)
                except (OSError, ValueError):
                    continue

        return None

    def _seed_library_from_local_archives(
        self,
        machine_name: str,
        major_version: int | None = None,
        minor_version: int | None = None,
    ) -> Path | None:
        if not self._courses_dir.exists():
            return None

        archive_paths = sorted(self._courses_dir.glob("*/build/h5p/**/*.h5p"))
        fallback_root: str | None = None
        fallback_archive: Path | None = None

        for archive_path in archive_paths:
            try:
                with ZipFile(archive_path) as archive:
                    for member in archive.namelist():
                        normalized = member.strip("/")
                        if not normalized.endswith("/library.json"):
                            continue

                        library_root = normalized.rsplit("/", 1)[0]
                        metadata = json.loads(archive.read(member).decode("utf-8"))
                        if metadata.get("machineName") != machine_name:
                            continue

                        if major_version is not None and minor_version is not None:
                            if (
                                metadata.get("majorVersion") == major_version
                                and metadata.get("minorVersion") == minor_version
                            ):
                                return self._extract_library_root_from_archive(archive, library_root)
                        elif fallback_root is None:
                            fallback_root = library_root
                            fallback_archive = archive_path
            except (BadZipFile, OSError, KeyError, json.JSONDecodeError):
                continue

        if fallback_root is None or fallback_archive is None:
            return None

        with ZipFile(fallback_archive) as archive:
            return self._extract_library_root_from_archive(archive, fallback_root)

    def _seed_runtime_library(
        self,
        machine_name: str,
        major_version: int | None = None,
        minor_version: int | None = None,
    ) -> None:
        seeded_library = self._seed_library_from_shared_libraries(machine_name, major_version, minor_version)
        if seeded_library is None:
            seeded_library = self._seed_library_from_local_archives(machine_name, major_version, minor_version)

        if seeded_library is not None:
            self.register_local_library(seeded_library)

    def find_library_dir(
        self,
        machine_name: str,
        major_version: int | None = None,
        minor_version: int | None = None,
    ) -> Path:
        try:
            return self._find_installed_library_dir(machine_name, major_version, minor_version)
        except FileNotFoundError:
            self._seed_runtime_library(machine_name, major_version, minor_version)
            return self._find_installed_library_dir(machine_name, major_version, minor_version)

    def extract_library_asset(self, archive_path: Path, machine_name: str) -> Path:
        with ZipFile(archive_path) as archive:
            library_root = None
            for member in archive.namelist():
                normalized = member.strip("/")
                if normalized.endswith("/library.json"):
                    library_root = normalized.rsplit("/", 1)[0]
                    break

            if library_root is None:
                raise RuntimeError(f"Kein library.json in {archive_path.name} gefunden.")
            return self._extract_library_root_from_archive(archive, library_root)

    def _update_registry_entry(self, library_json: dict, registry: dict) -> None:
        machine_name = library_json["machineName"]
        existing_entry = registry.get(machine_name, {})
        short_name = (
            self._custom_short_names.get(machine_name)
            or existing_entry.get("shortName")
            or machine_name.lower().replace(".", "-")
        )
        registry[machine_name] = {
            **existing_entry,
            "id": machine_name,
            "title": library_json.get("title", machine_name),
            "author": library_json.get("author", ""),
            "runnable": library_json.get("runnable", 0),
            "shortName": short_name,
        }

    def register_local_library(self, library_dir: Path) -> None:
        with self._workspace_lock:
            library_json = self._read_json(library_dir / "library.json")
            registry_path = self._runtime_dir / "libraryRegistry.json"
            registry = self._read_json_or_default(registry_path, {})
            self._update_registry_entry(library_json, registry)
            self._write_json(registry_path, registry)

    def ensure_custom_h5p_libraries(self) -> None:
        self._ensure_directory(self._runtime_downloads_dir)
        self._ensure_directory(self._runtime_libraries_dir)

        missing_specs = [
            spec
            for spec in self._library_asset_specs()
            if not self._has_runtime_library_for_asset_prefix(spec["assetPrefix"])
        ]
        if not missing_specs:
            return

        assets_by_release: dict[tuple[str, str], dict[str, str]] = {}

        for spec in missing_specs:
            machine_name = spec["machineName"]
            asset_prefix = spec["assetPrefix"]

            archive_path = self.find_downloaded_asset(asset_prefix)
            if archive_path is None:
                release_key = (spec["releaseRepo"], spec["releaseTag"])
                if release_key not in assets_by_release:
                    assets_by_release[release_key] = self.load_release_assets_for(*release_key)
                assets = assets_by_release[release_key]

                asset_name = next((name for name in assets if name.startswith(asset_prefix) and name.endswith(".h5p")), None)
                if asset_name is None:
                    raise RuntimeError(
                        f"Release-Asset für {machine_name} mit Präfix '{asset_prefix}' wurde nicht gefunden."
                    )

                archive_path = self._runtime_downloads_dir / asset_name
                if not archive_path.exists():
                    self._download_file(assets[asset_name], archive_path)

            library_dir = self.extract_library_asset(archive_path, machine_name)
            self.register_local_library(library_dir)

    def ensure_registered_local_libraries(self) -> None:
        with self._workspace_lock:
            registry_path = self._runtime_dir / "libraryRegistry.json"
            registry = self._read_json_or_default(registry_path, {})
            for library_dir in sorted(self._runtime_libraries_dir.glob("*")):
                library_json_path = library_dir / "library.json"
                if library_json_path.exists():
                    self._update_registry_entry(self._read_json(library_json_path), registry)
            self._write_json(registry_path, registry)

    def ensure_h5p_editor_dependencies(self) -> None:
        if not list(self._runtime_libraries_dir.glob("H5PEditor.ShowWhen-*")):
            self._install_library_from_github_archive(
                org="h5p",
                repo="h5p-editor-show-when",
                tag="1.0.9",
                destination="H5PEditor.ShowWhen-1.0",
            )
        if not list(self._runtime_libraries_dir.glob("H5PEditor.DateTime-*")):
            self._install_library_from_github_archive(
                org="otacke",
                repo="h5p-editor-datetime",
                tag="1.0.10",
                destination="H5PEditor.DateTime-1.0",
            )

    def ensure_h5p_math_display_registered(self) -> None:
        math_display_dirs = sorted(self._runtime_libraries_dir.glob("H5P.MathDisplay-*"))
        if not math_display_dirs:
            return
        self.register_local_library(math_display_dirs[-1])

    def ensure_h5p_runtime_libraries(self) -> None:
        with self._workspace_lock:
            if self._runtime_libraries_ready:
                return
            self._ensure_directory(self._runtime_dir)
            self._ensure_directory(self._runtime_content_dir)
            self._ensure_directory(self._runtime_libraries_dir)

            core_marker = self._runtime_dir / ".core-ready"
            if not core_marker.exists():
                self.run_h5p_cli(["core"], cwd=self._runtime_dir)
                core_marker.write_text("ok\n", encoding="utf-8")

            self.ensure_custom_h5p_libraries()
            self.ensure_python_question_multiple_choice_runtime_fix()
            self.ensure_registered_local_libraries()
            self.ensure_h5p_math_display_registered()

            if not list(self._runtime_libraries_dir.glob("H5P.Question-*")):
                self.run_h5p_cli(["setup", "h5p-question"], cwd=self._runtime_dir)

            self.ensure_h5p_editor_dependencies()
            self._runtime_libraries_ready = True

    def collect_required_library_dirs(
        self,
        machine_name: str,
        major_version: int | None = None,
        minor_version: int | None = None,
        seen: set[str] | None = None,
    ) -> list[Path]:
        seen = seen or set()
        library_dir = self.find_library_dir(machine_name, major_version, minor_version)
        library_name = library_dir.name
        if library_name in seen:
            return []

        seen.add(library_name)
        metadata = self._read_json(library_dir / "library.json")
        required = [library_dir]
        for dependency in metadata.get("preloadedDependencies", []):
            required.extend(
                self.collect_required_library_dirs(
                    dependency["machineName"],
                    dependency.get("majorVersion"),
                    dependency.get("minorVersion"),
                    seen,
                )
            )
        return required

    def collect_required_library_dirs_from_metadata(self, metadata_payload: dict[str, object]) -> list[Path]:
        dependencies = metadata_payload.get("preloadedDependencies", [])
        if not isinstance(dependencies, list):
            return []

        required: list[Path] = []
        seen: set[str] = set()
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue
            machine_name = str(dependency.get("machineName") or "").strip()
            if not machine_name:
                continue
            required.extend(
                self.collect_required_library_dirs(
                    machine_name,
                    int(dependency["majorVersion"]) if dependency.get("majorVersion") is not None else None,
                    int(dependency["minorVersion"]) if dependency.get("minorVersion") is not None else None,
                    seen,
                )
            )
        return required
