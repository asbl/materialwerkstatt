"""Immutable template releases; editable settings drafts share frozen layouts."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import uuid
from pathlib import Path

from material_core.filesystem import atomic_write_bytes, atomic_write_text
from material_core.metadata import clamp_fontsize, enforce_min_fontsize, read_metadata, set_fields, split_frontmatter, template_value, yaml_parser

from material_core.template_roots import (
    find_template, is_private, is_template_dir, logical_relative, private_dirname, private_root, sibling,
)

STORE = "src/quarto/template-releases"
# Privater Speicher: Freigaben aller nicht ausdruecklich freigegebenen Vorlagen.


def local_store() -> str:
    """Privater Freigabespeicher; folgt MATERIAL_PRIVATE_DIR zur Laufzeit (wie private_root())."""
    return f"src/quarto/{private_dirname()}/template-releases"


def __getattr__(name: str):   # LOCAL_STORE bleibt als dynamische Modulkonstante lesbar (Tests)
    if name == "LOCAL_STORE":
        return local_store()
    raise AttributeError(name)
LOCK = threading.RLock()


def dump_text(text, metadata):
    out = io.StringIO()
    yaml_parser().dump(metadata, out)
    parts = split_frontmatter(text)
    return f"{parts.prefix if parts else '---' + chr(10)}{out.getvalue()}{parts.closing if parts else '---' + chr(10)}{parts.body if parts else text}"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class TemplateVersions:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.support = self.root / "src/quarto"

    def path(self, value):
        if not isinstance(value, str) or not value:
            raise ValueError("Template-Version fehlt.")
        path = (self.root / value).resolve()
        if not any(path.is_relative_to(self.root / store) for store in (STORE, local_store())):
            raise ValueError("Ungültiger Template-Versionspfad.")
        if not path.exists() and path.is_relative_to(self.root / local_store()):
            # Freigegebene (eingebaute) Vorlagen: private Bezuege duerfen auf den eingebauten Speicher zeigen.
            public = (self.root / STORE / path.relative_to(self.root / local_store())).resolve()
            if public.exists():
                return public
        if not path.exists() and path.is_relative_to(self.root / STORE):
            # Freigaben nicht eingebauter Vorlagen liegen im privaten Speicher; aeltere
            # Frontmatter-Bezuege nennen noch den frueheren Pfad im eingebauten Speicher.
            private = (self.root / local_store() / path.relative_to(self.root / STORE)).resolve()
            if private.exists():
                return private
        return path

    def relative(self, path):
        return path.relative_to(self.root).as_posix()

    def write(self, path, value, *, overwrite=False):
        if re.fullmatch(r"v[1-9][0-9]*\.json", path.name):
            value = {**value, "checksum": sha(canonical(value).encode())}
        atomic_write_text(path, canonical(value), overwrite=overwrite)

    def local_template(self, path):
        """Standardmaessig privat: nur ausdruecklich freigegebene Dateien gelten als eingebaut.

        Eingebaut ist, was im eingebauten Vorlagenordner liegt (dort landet eine Datei nur ueber
        `inv template-freigeben`) und nicht ignoriert wird. Alles andere, auch Dateien im
        privaten Ordner, in `_local`-Pfaden oder lokale Katalogeintraege, bleibt privat.
        """
        path = Path(path).resolve()
        if is_private(path, self.support) or private_dirname() in path.as_posix():
            return True
        import subprocess
        ignored = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=self.root,
                                 capture_output=True).returncode == 0
        if ignored:
            return True
        from material_core.designs import load_designs
        catalog = self.root / "src/material_core/template-designs.json"
        designs = load_designs(catalog, private_root(self.support) / "template-designs.json") if catalog.is_file() else []
        return any(d.get("local_only") and d["id"] in path.stem for d in designs)

    def resolve_template(self, value, source=None):
        candidate = ((source.parent if source else self.root) / value).resolve()
        if candidate.is_file():
            return candidate
        candidate = find_template(value, self.support)
        if candidate is None:
            raise ValueError(f"Vorlage fehlt: {value}")
        return candidate

    def initial(self, value, source=None, *, refresh=False, note=None):
        template = self.resolve_template(value, source)
        if not is_template_dir(template.parent, self.support):
            raise ValueError("Individuelle lokale Vorlagen benötigen eine eigene Freigabe.")
        store = self.root / (local_store() if self.local_template(template) else STORE)
        release = store / template.stem / "v1.json"
        with LOCK:
            settings = {}
            if refresh and release.exists():
                settings = self.load(self.latest(self.relative(release)))["settings"]
                version = max(self.load(ref)["version"] for ref in self.releases(self.relative(release))) + 1
                release = release.with_name(f"v{version}.json")
            else:
                version = 1
            if not release.exists():
                files = {}
                visited = set()

                def collect(path):
                    path = path.resolve()
                    if path in visited:
                        return
                    visited.add(path)
                    if not path.is_relative_to(self.support) or not path.is_file():
                        raise ValueError(f"Template-Abhängigkeit fehlt oder liegt außerhalb von src/quarto: {path}")
                    if store == self.root / STORE and self.local_template(path):
                        raise ValueError("Lokale Abhängigkeiten dürfen nur in lokale Template-Freigaben aufgenommen werden.")
                    data = path.read_bytes()
                    files[logical_relative(path, self.support)] = data
                    if path.suffix not in {".typst", ".tex"}:
                        return
                    content = data.decode("utf-8")
                    if path.suffix == ".typst":
                        # A private release setting leaves the original default and
                        # document-level fontsize behavior intact for v1.
                        content = re.sub(
                            r'(#set text\(font: (?:body-font|hand-font), size: )(.+?)(, lang:)',
                            lambda m: m[1] + '$if(template-fontsize)$$template-fontsize$$else$' + m[2] + '$endif$' + m[3],
                            content,
                        )
                        files[logical_relative(path, self.support)] = content.encode()
                    for name in re.findall(r"\$([\w-]+\.typst)\(\)\$", content):
                        collect(sibling(path, name, self.support))
                    for name in re.findall(r'(?:#(?:import|include)|\bimage)\s*\(?\s*"([^"\n]+)"', content):
                        if not name.startswith("@"):
                            collect(sibling(path, name, self.support) if "/" not in name else path.parent / name)
                    for name in re.findall(r"\\(?:input|include)\{([^}]+)\}", content):
                        dep = path.parent / name
                        collect(dep if dep.suffix else dep.with_suffix(".tex"))

                collect(template)
                header = find_template("exam-header.tex", self.support)
                if template.suffix == ".tex" and header is not None:
                    collect(header)
                # Lua filters load sibling helpers dynamically.
                for path in (self.support / "filters").glob("*.lua"):
                    collect(path)
                checksums = {name: sha(data) for name, data in files.items()}
                layout_id = sha(canonical(checksums).encode())
                layout = store / "layouts" / layout_id
                for name, data in files.items():
                    destination = layout / name
                    if destination.exists():
                        if destination.read_bytes() != data:
                            raise ValueError("Unveränderliches Layout wurde beschädigt.")
                    else:
                        atomic_write_bytes(destination, data, overwrite=False)
                config_path = self.root / "_quarto.yml"
                project = yaml_parser().load(config_path.read_text()) if config_path.is_file() else {}
                defaults = (project or {}).get("format", {})
                from material_core.designs import DESIGNS
                slide_design = next((d for d in DESIGNS if template.name == f"slide-{d['id']}.typst"), None)
                self.write(release, {"template": template.name, "version": version,
                    "layout": self.relative(layout), "files": checksums, "settings": settings,
                    "defaults": json.loads(json.dumps(defaults)),
                    **({"slide-design": slide_design} if slide_design else {}),
                    "note": note if note is not None else (
                        "Aktualisiertes Layout" if refresh else "Ausgangsstand vor Einführung der Versionierung")})
        self.load(self.relative(release))
        return self.relative(release)

    def load(self, reference):
        path = self.path(reference)
        if not path.is_file() or not re.fullmatch(r"v[1-9][0-9]*\.json", path.name):
            raise ValueError(f"Template-Version fehlt: {reference}")
        release = json.loads(path.read_text())
        checksum = release.pop("checksum", None)
        if checksum != sha(canonical(release).encode()):
            raise ValueError("Template-Freigabe wurde nachträglich verändert.")
        layout = self.path(release["layout"])
        if sha(canonical(release["files"]).encode()) != layout.name:
            raise ValueError("Template-Manifest ist beschädigt.")
        for name, expected in release["files"].items():
            dep = (layout / name).resolve()
            if not dep.is_relative_to(layout) or not dep.is_file() or sha(dep.read_bytes()) != expected:
                raise ValueError(f"Template-Version ist beschädigt: {name}")
        return release

    def releases(self, reference):
        path = self.path(reference)
        return [self.relative(p) for p in sorted(path.parent.glob("v*.json"),
                key=lambda p: int(p.stem[1:])) if re.fullmatch(r"v[1-9][0-9]*", p.stem)]

    def latest(self, reference):
        path = self.path(reference).parent / "default.json"
        return json.loads(path.read_text())["release"] if path.exists() else reference

    def update_offer(self, text, *, include_reviewed=False):
        """Offer the newest published version once per document and release."""
        metadata = read_metadata(text)
        reference = metadata.get("template-release")
        if not reference:
            return None
        current = self.load(reference)
        if Path(template_value(text)).name != current["template"]:
            raise ValueError("Template-Version passt nicht zur gewählten Vorlage.")
        newest = self.releases(reference)[-1]
        release = self.load(newest)
        if release["version"] <= current["version"]:
            return None
        if not include_reviewed and metadata.get("template-update-reviewed") == newest:
            return None
        return {"release": newest, "currentVersion": current["version"],
                "version": release["version"], "template": release["template"],
                "note": release.get("note", "")}

    def review_update(self, text, reference, accept):
        offer = self.update_offer(text, include_reviewed=True)
        if not offer or offer["release"] != reference:
            raise ValueError("Die angebotene Template-Version hat sich geändert. Bitte Rendern erneut starten.")
        fields = {"template-update-reviewed": reference}
        if accept:
            fields["template-release"] = reference
        return set_fields(text, fields)

    def describe(self, reference):
        release = self.load(reference)
        return {"release": reference, "version": release["version"],
                "fontsize": release["settings"].get("fontsize", ""), "note": release["note"]}

    def catalog_entry(self, entry):
        entry = dict(entry)
        path = self.root / entry.get("path", "")
        if not path.is_file() and entry.get("path", "").startswith("src/quarto/templates/"):
            path = find_template(entry["path"], self.support) or path
        if path.is_file() and is_template_dir(path.parent, self.support):
            initial = self.initial(entry["path"])
            entry["release"] = self.latest(initial)
            entry["releases"] = [self.describe(ref) for ref in self.releases(initial)]
        return entry

    def draft(self, reference):
        release = self.load(reference)
        for existing in sorted((self.path(reference).parent / "drafts").glob("*.json"), reverse=True):
            candidate = self.read_draft(self.relative(existing))
            if candidate["base"] == reference and not candidate.get("published"):
                return self.relative(existing)
        path = self.path(reference).parent / "drafts" / f"{uuid.uuid4().hex}.json"
        self.write(path, {"base": reference, "settings": release["settings"], "note": ""})
        return self.relative(path)

    def read_draft(self, reference):
        path = self.path(reference)
        if path.parent.name != "drafts" or not re.fullmatch(r"[a-f0-9]{32}\.json", path.name):
            raise ValueError("Ungültiger Entwurf.")
        return json.loads(path.read_text())

    def save_draft(self, reference, fontsize, note):
        draft = self.read_draft(reference)
        if draft.get("published"):
            raise ValueError("Dieser Entwurf wurde bereits freigegeben. Bitte einen neuen Entwurf erstellen.")
        if not isinstance(fontsize, str) or (fontsize and (not re.fullmatch(r"\d+(?:\.\d+)?pt", fontsize) or not 11 <= float(fontsize[:-2]) <= 32)):
            raise ValueError("Schriftgröße muss zwischen 11 und 32 pt liegen (z. B. 12pt).")
        if not isinstance(note, str) or len(note) > 2000:
            raise ValueError("Bitte eine kurze Änderungsnotiz eingeben.")
        if fontsize and self.load(draft["base"])["template"].endswith(".tex") and fontsize not in {"11pt", "12pt"}:
            raise ValueError("Diese LaTeX-Vorlage unterstützt 11pt oder 12pt als Grundschrift.")
        draft.update(settings={"fontsize": fontsize} if fontsize else {}, note=note)
        self.write(self.path(reference), draft, overwrite=True)
        return draft

    def publish(self, reference, make_default=False):
        with LOCK:
            draft = self.read_draft(reference)
            if draft.get("published"):
                return draft["published"]
            release = self.load(draft["base"])
            version = max(self.load(ref)["version"] for ref in self.releases(draft["base"])) + 1
            path = self.path(draft["base"]).parent / f"v{version}.json"
            release.update(version=version, settings=draft["settings"], note=draft["note"])
            self.write(path, release)
            result = self.relative(path)
            draft["published"] = result
            self.write(self.path(reference), draft, overwrite=True)
            if make_default:
                self.write(path.parent / "default.json", {"release": result}, overwrite=True)
            return result

    def bind(self, text, reference):
        release = self.load(reference)
        if Path(template_value(text)).name != release["template"]:
            raise ValueError("Template-Version passt nicht zur gewählten Vorlage.")
        metadata = read_metadata(text)
        metadata["template-release"] = reference
        return dump_text(text, metadata)

    def freeze_context(self, source, text):
        """Freeze inherited format options and local headers without moving sources.

        Header paths in _metadata.yml are relative to that metadata file, rather
        than the QMD. Keep that origin when pinning a nested document.
        """
        metadata = read_metadata(text)
        if metadata.get("template-context"):
            context = self.context(metadata["template-context"])
            if context.get("filter"):
                return text
            store = self.path(metadata["template-context"]).parent.parent
            self.add_context_filter(context, store)
            reference = store / "contexts" / (sha(canonical(context).encode()) + ".json")
            if not reference.exists():
                self.write(reference, context)
            metadata["template-context"] = self.relative(reference)
            return dump_text(text, metadata)
        formats = metadata.get("format", {})
        engine = next((k for k in ("typst", "pdf", "beamer") if isinstance(formats, dict) and k in formats), None)
        if not engine:
            return text
        options = {}
        include_keys = {"include-in-header", "include-before-body", "include-after-body"}

        def ingest(settings, base):
            incoming = settings.get("format", {})
            incoming = incoming.get(engine, {}) if isinstance(incoming, dict) else {}
            if not isinstance(incoming, dict):
                return
            for key, value in incoming.items():
                if key in include_keys:
                    def resolve(item):
                        if isinstance(item, dict) and set(item) == {"text"} and isinstance(item["text"], str):
                            return dict(item)
                        if not isinstance(item, str):
                            raise ValueError("Konfigurierte Include-Objekte benötigen eine manuelle Versionsbindung.")
                        path = (base / item).resolve()
                        if not path.is_file():
                            # Also repair paths flattened by an earlier migration.
                            path = next((parent / item for parent in [source.parent, *source.parent.parents]
                                         if parent.is_relative_to(self.root) and (parent / item).is_file()), path)
                        if not path.is_file():
                            candidate = find_template(item, self.support)
                            path = candidate if candidate is not None else path
                        if not path.is_file() or not path.is_relative_to(self.root):
                            raise ValueError(f"Layout-Include fehlt oder liegt außerhalb des Projekts: {item}")
                        return path
                    options[key] = [resolve(item) for item in (value if isinstance(value, list) else [value])]
                elif key not in {"template", "output-file"}:
                    options[key] = value

        for directory in reversed([source.parent, *source.parent.parents]):
            if not directory.is_relative_to(self.root):
                continue
            for name in ("_quarto.yml", "_metadata.yml"):
                path = directory / name
                if path.is_file():
                    ingest(yaml_parser().load(path.read_text()) or {}, directory)
        ingest(metadata, source.parent)
        files = {}
        all_headers = [p for key, values in options.items() if key in include_keys for p in values if isinstance(p, Path)]
        local = self.relative(self.path(metadata["template-release"])).startswith(local_store()) or any(self.local_template(p) for p in all_headers)
        store = self.root / (local_store() if local else STORE)
        for key in include_keys & options.keys():
            frozen = []
            for path in options[key]:
                if isinstance(path, dict):
                    frozen.append(path)
                    continue
                data = path.read_bytes()
                # Static file imports need a package preserving their relative tree.
                # Do not silently claim to freeze an incomplete dependency graph.
                if re.search(rb"\\(?:input|include)\{", data):
                    raise ValueError(f"Verschachteltes lokales Layout-Include muss separat paketiert werden: {path.name}")
                target = store / "contexts/assets" / (sha(data) + path.suffix)
                if not target.exists():
                    atomic_write_bytes(target, data, overwrite=False)
                files[self.relative(target)] = sha(data)
                frozen.append(self.relative(target))
            options[key] = frozen
        context = {"options": options, "files": files, "original": {
            key: formats[engine][key] for key in include_keys if isinstance(formats[engine], dict) and key in formats[engine]}}
        self.add_context_filter(context, store)
        reference = store / "contexts" / (sha(canonical(context).encode()) + ".json")
        if not reference.exists():
            self.write(reference, context)
        metadata["template-context"] = self.relative(reference)
        return dump_text(text, metadata)

    def add_context_filter(self, context, store):
        data = (Path(__file__).resolve().parents[1] / "quarto/filters/template-context.lua").read_bytes()
        path = store / "contexts/assets" / (sha(data) + ".lua")
        if not path.exists():
            atomic_write_bytes(path, data, overwrite=False)
        context["filter"] = self.relative(path)
        context["files"][self.relative(path)] = sha(data)

    def context(self, reference):
        path = self.path(reference)
        value = json.loads(path.read_text())
        if sha(canonical(value).encode()) != path.stem:
            raise ValueError("Template-Kontext wurde nachträglich verändert.")
        for name, expected in value["files"].items():
            asset = self.path(name)
            if not asset.is_file() or sha(asset.read_bytes()) != expected:
                raise ValueError(f"Eingefrorenes Layout-Include ist beschädigt: {name}")
        return value

    def render(self, source, text):
        metadata = read_metadata(text)
        enforce_min_fontsize(metadata)
        reference = metadata.get("template-release")
        if not reference:
            return None
        release = self.load(reference)
        preview = metadata.pop("template-preview-draft", None)
        if preview:
            draft = self.read_draft(preview)
            if draft["base"] != reference:
                raise ValueError("Entwurf passt nicht zur Vorschau-Version.")
            release["settings"] = draft["settings"]
        if Path(template_value(text)).name != release["template"]:
            raise ValueError("Template-Version passt nicht zur Vorlage. Bitte Version ausdrücklich wechseln.")
        layout = self.path(release["layout"])
        formats = metadata.get("format")
        if not isinstance(formats, dict):
            raise ValueError("Versionierte Vorlagen benötigen ein explizites Ausgabeformat.")
        engine = next((name for name in ("typst", "pdf", "beamer") if name in formats), None)
        if engine is None:
            raise ValueError("PDF-Ausgabeformat fehlt.")
        defaults = release.get("defaults", {})
        options = dict(defaults.get(engine) or {}) if isinstance(defaults, dict) else {}
        context = self.context(metadata["template-context"]) if metadata.get("template-context") else None
        if context:
            options.update(context["options"])
        options.update(dict(formats[engine]) if isinstance(formats[engine], dict) else {})
        if engine == "typst" and isinstance(options.get("font-paths"), list):
            # Project defaults become document metadata in a frozen release.
            # Preserve their root-relative meaning at any document depth.
            options["font-paths"] = [
                os.path.relpath(self.root / path, source.parent)
                if isinstance(path, str) and path.startswith("src/quarto/") else path
                for path in options["font-paths"]
            ]
        if "fontsize" in options:
            options["fontsize"] = clamp_fontsize(options["fontsize"])
        if context:
            for key in ("include-in-header", "include-before-body", "include-after-body"):
                if key in context["options"] and (key not in formats[engine] or formats[engine].get(key) == context["original"].get(key)):
                    options[key] = [os.path.relpath(self.path(p), source.parent) if isinstance(p, str) else p
                                    for p in context["options"][key]]
        options["template"] = os.path.relpath(layout / "templates" / release["template"], source.parent)
        # Settings are defaults; explicit document overrides keep their meaning.
        for key, value in release["settings"].items():
            if key not in options and key not in metadata:
                metadata[key] = value
        metadata.pop("template-fontsize", None)
        if engine == "typst" and release["settings"].get("fontsize"):
            metadata["template-fontsize"] = options.get("fontsize", metadata.get("fontsize", release["settings"]["fontsize"]))
        # Fallback auf 11 pt erst nach den Release-Standards, damit diese Vorrang behalten.
        enforce_min_fontsize(metadata, default="11pt")
        for key in ("include-in-header", "include-before-body", "include-after-body"):
            if isinstance(options.get(key), str):
                frozen = layout / "templates" / Path(options[key]).name
                if frozen.is_file():
                    options[key] = os.path.relpath(frozen, source.parent)
        if engine in {"pdf", "beamer"} and (layout / "templates/exam-header.tex").is_file():
            options.setdefault("include-in-header", os.path.relpath(layout / "templates/exam-header.tex", source.parent))
        formats[engine] = options
        previous = metadata.get("template-partials") or []
        previous = [previous] if isinstance(previous, str) else list(previous)
        overrides = {Path(p).name for p in previous}
        metadata["template-partials"] = previous + [os.path.relpath(layout / name, source.parent)
            for name in release["files"] if name.endswith(".typst")
            and Path(name).name != release["template"] and Path(name).name not in overrides]
        previous = metadata.get("filters") or []
        previous = [previous] if isinstance(previous, str) else list(previous)
        frozen_filters = []
        for item in previous:
            name = Path(item).name if isinstance(item, str) else ""
            frozen = layout / "filters" / name
            frozen_filters.append(os.path.relpath(frozen, source.parent) if name and frozen.is_file() else item)
        names = {Path(p).name for p in frozen_filters if isinstance(p, str)}
        for name in ("exam.lua", "slide-pages.lua"):
            if name == "slide-pages.lua" and not release["template"].startswith("slide"):
                continue
            path = layout / "filters" / name
            if path.is_file() and name not in names:
                frozen_filters.append(os.path.relpath(path, source.parent))
        metadata["filters"] = frozen_filters
        if context:
            includes = {}
            targets = {"include-in-header": "header-includes", "include-before-body": "include-before", "include-after-body": "include-after"}
            for key, target in targets.items():
                chunks = []
                values = options.get(key, [])
                values = [values] if isinstance(values, (str, dict)) else values
                for value in values:
                    if isinstance(value, dict):
                        chunks.append(value["text"])
                    elif isinstance(value, str):
                        chunks.append((source.parent / value).read_text())
                own = metadata.get(target) or []
                own = [own] if isinstance(own, str) else list(own)
                chunks.extend(own)
                includes[target] = [chunk.encode("utf-8").hex() for chunk in chunks]
            metadata["template-frozen-includes"] = includes
            frozen_filters.append({"path": os.path.relpath(self.path(context["filter"]), source.parent), "at": "post-finalize"})
        return dump_text(text, metadata)

    def migrate(self, paths, *, write=False):
        """Pin existing sources to v1, never to the current new-document default."""
        report = {"pinned": [], "unchanged": [], "manual": []}
        for source in paths:
            source = source.resolve()
            text = source.read_text(encoding="utf-8")
            try:
                metadata = read_metadata(text)
                if metadata.get("template-release"):
                    self.load(metadata["template-release"])
                    updated = self.freeze_context(source, text)
                    if write and updated != text:
                        atomic_write_text(source, updated)
                    report["pinned" if updated != text else "unchanged"].append(self.relative(source))
                    continue
                value = template_value(text)
                if not value:
                    # Quarto's nearest explicit format determines the selected engine.
                    effective = {}
                    selected_engine = None

                    def merge(destination, incoming):
                        for key, value in incoming.items():
                            if isinstance(value, dict) and isinstance(destination.get(key), dict):
                                merge(destination[key], value)
                            else:
                                destination[key] = value

                    def ingest(incoming):
                        nonlocal selected_engine
                        formats = incoming.get("format")
                        if isinstance(formats, str):
                            selected_engine = formats
                            incoming = {**incoming, "format": {formats: {}}}
                        elif isinstance(formats, dict):
                            selected_engine = next((k for k in formats if k in {"typst", "pdf", "beamer"}), selected_engine)
                        merge(effective, incoming)
                    for directory in reversed([source.parent, *source.parent.parents]):
                        if not directory.is_relative_to(self.root):
                            continue
                        for name in ("_quarto.yml", "_metadata.yml"):
                            config = directory / name
                            if config.is_file():
                                incoming = yaml_parser().load(config.read_text()) or {}
                                ingest(incoming)
                    ingest(metadata)
                    formats = effective.get("format", {})
                    if selected_engine not in {"typst", "pdf", "beamer"}:
                        report["unchanged"].append(self.relative(source))
                        continue
                    engine = selected_engine
                    options = formats.get(engine) if engine else None
                    value = options.get("template") if isinstance(options, dict) else None
                    if not value:
                        report["unchanged"].append(self.relative(source))
                        continue
                    declared_formats = dict(metadata["format"]) if isinstance(metadata.get("format"), dict) else {}
                    declared_formats[engine] = {**options, "template": Path(value).name}
                    metadata["format"] = declared_formats
                    text = dump_text(text, metadata)
                template = self.resolve_template(value, source)
                if not is_template_dir(template.parent, self.support):
                    raise ValueError("Individuelle Vorlage: separat prüfen")
                reference = self.initial(str(template))
                updated = self.bind(text, reference)
                updated = self.freeze_context(source, updated)
                if write:
                    atomic_write_text(source, updated)
                report["pinned"].append(self.relative(source))
            except (ValueError, OSError) as error:
                report["manual"].append({"path": self.relative(source), "reason": str(error)})
        return report


def main():
    import argparse
    import subprocess
    parser = argparse.ArgumentParser(description="Template-Versionen sichern und Bestands-QMDs binden")
    parser.add_argument("command", choices=["migrate", "check"])
    parser.add_argument("--write", action="store_true", help="Versionsbindungen in QMDs speichern")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    versions = TemplateVersions(args.root)
    # Ein eigener Inhaltsordner ist in der Regel selbst kein Git-Repo.
    versioned = (versions.root / ".git").exists()
    if args.command == "migrate":
        if versioned:
            result = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.qmd"],
                                    cwd=versions.root, check=True, capture_output=True)
            names = result.stdout.decode().split("\0")
        else:
            names = [path.relative_to(versions.root).as_posix() for path in versions.root.rglob("*.qmd")
                     if not any(part == "build" or part.startswith(".")
                                for part in path.relative_to(versions.root).parts)]
        paths = [versions.root / name for name in dict.fromkeys(names)
                 if name and (versions.root / name).is_file()]
        print(canonical(versions.migrate(paths, write=args.write)))
    else:
        for store in (STORE, local_store()):
            for path in (versions.root / store).glob("*/v*.json"):
                versions.load(versions.relative(path))
            for path in (versions.root / store / "contexts").glob("*.json"):
                versions.context(versions.relative(path))
        # Ohne Git (Inhaltsordner) bleiben die Pruefsummen oben; geaenderte Releases erkennt Git nur im Programm-Repo.
        changed = subprocess.run(["git", "diff", "HEAD", "--name-only", "--diff-filter=MD", "--", STORE, local_store()],
                                 cwd=versions.root, check=True, capture_output=True, text=True).stdout if versioned else ""
        def moved_to_private(line):
            # Freigaben nicht eingebauter Vorlagen wanderten in den privaten Speicher: dort vorhanden = nicht veraendert.
            if not line.startswith(STORE + "/"):
                return False
            return (versions.root / local_store() / line[len(STORE) + 1:]).exists()

        immutable_changes = [line for line in changed.splitlines()
                             if ("/layouts/" in line or "/contexts/" in line or re.search(r"/v[1-9][0-9]*\.json$", line))
                             and not moved_to_private(line)]
        if immutable_changes:
            raise SystemExit("Bestehende Freigaben wurden verändert: " + ", ".join(immutable_changes))
        print("Template-Versionen und Prüfsummen sind gültig.")


if __name__ == "__main__":
    main()
