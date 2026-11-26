from __future__ import annotations

import re

from flask import jsonify, request
from werkzeug.exceptions import NotFound

from material_ui.folder_notes import is_folder_note, read_notes, save_notes
from material_ui.http import required_arg, required_value
from material_ui.storage import RevisionConflict
from material_ui.units import FILENAME as UNIT_FILENAME
from material_ui.index_payload import qmds_payload


def register_folder_routes(app, runtime):
    config = runtime.config
    document_service = runtime.services.documents

    def folder_settings(path):
        folder = config.safe_visible_path(path)
        if not folder.is_dir():
            raise NotFound("Ordner nicht gefunden.")
        return folder

    @app.get("/api/folder/settings")
    def get_folder_settings():
        folder = folder_settings(required_arg("path"))
        relative = config.relative(folder)
        eligible = relative.startswith('unterricht/') and any(
            re.fullmatch(r'klasse-\d+', part) for part in folder.relative_to(config.root).parts)
        return jsonify(notes=read_notes(folder), unit=runtime.services.units.read(folder) if eligible else None)

    @app.post("/api/folder/settings")
    def save_folder_settings():
        data = request.get_json(force=True)
        folder = folder_settings(required_value(data.get('path')))
        with document_service.repository.lock:
            # Check both revisions before changing either file.
            if read_notes(folder)['revision'] != data.get('notesRevision'):
                raise RevisionConflict('Die Ordnerhinweise wurden geändert. Bitte neu laden.')
            if data.get('unit') is not None:
                runtime.services.units.save(config.relative(folder), data['unit'], data.get('unitRevision'))
            save_notes(folder, data.get('notes'), data.get('notesRevision'))
        document_service.invalidate_qmd_cache()
        return jsonify(ok=True)

    @app.get("/api/folder")
    def folder_entries():
        folder = config.safe_path(request.args.get("path") or ".")
        if not folder.is_dir() or not config.is_visible(folder):
            raise NotFound("Ordner nicht gefunden.")
        is_root = folder == config.root
        entries = []
        for child in folder.iterdir():
            if (child.is_file() and (child.name == UNIT_FILENAME or is_folder_note(child.name))) or child.name.startswith(".") or not child.resolve().is_relative_to(config.root):
                continue
            if is_root and child.name == "wissen":
                continue
            if child.is_dir() or child.is_file():
                entries.append({"path": child.relative_to(config.root).as_posix(), "name": child.name, "directory": child.is_dir()})
        payload = {"entries": entries, "notes": read_notes(folder)}
        if request.args.get("metadata") == "1":
            qmds, warnings = [], []
            for entry in entries:
                path = folder / entry["name"]
                if entry["directory"]:
                    continue
                try:
                    if document_service.is_material_source(path):
                        qmds.append(document_service.qmd_entry(path))
                except (OSError, ValueError) as error:
                    warnings.append({"path": entry["path"], "message": str(error)})
            payload.update(qmds=qmds, warnings=warnings)
        return jsonify(payload)

    @app.post("/api/folder/reorder")
    def reorder_folder():
        data = request.get_json(force=True)
        paths = runtime.services.folders.reorder(required_value(data.get("path")), data.get("position"))
        document_service.invalidate_qmd_cache()
        return jsonify({"ok": True, "paths": paths, **qmds_payload(config, document_service)})

    @app.post("/api/folder/rename")
    def rename_folder():
        data = request.get_json(force=True)
        target = runtime.services.folders.rename(required_value(data.get("path")), required_value(data.get("name")))
        document_service.invalidate_qmd_cache()
        return jsonify({"ok": True, "path": config.relative(target), **qmds_payload(config, document_service)})
