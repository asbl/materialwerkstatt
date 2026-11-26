from __future__ import annotations

from pathlib import Path

from flask import jsonify, request, send_file
from werkzeug.exceptions import NotFound

from material_ui.assets import AssetService
from material_ui.document_types import capabilities, ensure_renderable
from material_ui.documents import ensure_editable, ensure_qmd
from material_core.designs import template_slide_design
from material_core.template_roots import find_template
from material_core.render_inputs import render_content
from material_ui.index_payload import qmds_payload
from material_ui.errors import InvalidInput
from material_ui.http import required_arg, required_value, required_text, import_metadata, read_import_image
from material_ui.metadata import read_metadata, set_fields, set_template, template_value
from material_ui.worksheet_notes import ensure_worksheet_note

def pdf_version(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns}-{stat.st_ctime_ns}-{stat.st_size}"

def register_document_routes(app, runtime, max_upload_bytes: int):
    config = runtime.config
    document_service = runtime.services.documents
    builds = runtime.services.builds
    renderer = runtime.services.render

    def version_call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except ValueError as error:
            raise InvalidInput(str(error)) from error

    def has_slides(text):
        try:
            return template_slide_design(text)[0]
        except ValueError:
            return False

    def is_presentation(text):
        try:
            template = Path(template_value(text).replace("\\", "/")).name
            return template.startswith("slide-") or template == "slides-template.tex"
        except ValueError:
            return False

    @app.get("/api/search")
    def search():
        results, source_errors = runtime.services.search.search_with_sources(
            request.args.get("q") or "",
            subject=request.args.get("subject") or "",
            grade=request.args.get("grade") or "",
            kind=request.args.get("kind") or "",
            tags=request.args.get("tags") or "",
            pdf=request.args.get("pdf") or "",
            area=request.args.get("area") or "",
            solution=request.args.get("solution") == "true",
            sort=request.args.get("sort") or "relevance",
        )
        return jsonify({
            "results": results,
            "sources": [{"id": source_id, "name": name} for source_id, name in runtime.services.search.provider_sources()],
            "sourceErrors": source_errors,
        })

    @app.get("/api/document/git")
    def document_git():
        source = config.safe_path(required_arg("path"))
        ensure_editable(source)
        return jsonify(runtime.services.git.document_info(source))

    @app.get("/api/qmds")
    def qmds():
        return jsonify(qmds_payload(config, document_service))

    @app.post("/api/qmds/reload")
    def qmds_reload():
        """Nach Dateiaenderungen von aussen den Index sofort neu einlesen statt den TTL-Cache abzuwarten."""
        document_service.invalidate_qmd_cache()
        return jsonify(qmds_payload(config, document_service))

    @app.get("/api/file")
    def download_file():
        source = config.safe_path(required_arg("path"))
        if not source.is_file() or not config.is_visible(source):
            raise NotFound("Datei nicht gefunden.")
        return send_file(source, as_attachment=True)

    @app.post("/api/file/rename")
    def rename_file():
        data = request.get_json(force=True)
        target = runtime.services.files.rename(required_value(data.get("path")), required_value(data.get("name")))
        return jsonify({"ok": True, "path": config.relative(target), **qmds_payload(config, document_service)})

    @app.post("/api/file/move")
    def move_file():
        data = request.get_json(force=True)
        target = runtime.services.files.move(required_value(data.get("path")), required_value(data.get("destination")))
        return jsonify({"ok": True, "path": config.relative(target), **qmds_payload(config, document_service)})

    @app.delete("/api/file")
    def delete_file():
        runtime.services.files.delete(required_arg("path"))
        return jsonify({"ok": True, **qmds_payload(config, document_service)})

    @app.post("/api/materials/repair-solution-metadata")
    def repair_solution_metadata():
        return jsonify(runtime.services.files.repair_solution_metadata())

    @app.get("/api/templates")
    def templates():
        from material_core.designs import slide_templates
        from material_core.template_versions import TemplateVersions

        versions = TemplateVersions(config.root)
        return jsonify({"templates": document_service.template_entries(),
                        "slideTemplates": [versions.catalog_entry(entry) for entry in slide_templates()]})

    @app.post("/api/template-drafts")
    def template_draft():
        from material_core.template_versions import TemplateVersions
        versions = TemplateVersions(config.root)
        data = request.get_json(force=True)
        reference = required_value(data.get("release"))
        draft = version_call(versions.draft, reference)
        return jsonify({"draft": draft, **versions.read_draft(draft)})

    @app.post("/api/template-drafts/save")
    def save_template_draft():
        from material_core.template_versions import TemplateVersions
        versions = TemplateVersions(config.root)
        data = request.get_json(force=True)
        draft = required_value(data.get("draft"))
        return jsonify(version_call(versions.save_draft, draft, data.get("fontsize", ""), data.get("note", "")))

    @app.post("/api/template-drafts/publish")
    def publish_template_draft():
        from material_core.template_versions import TemplateVersions
        versions = TemplateVersions(config.root)
        data = request.get_json(force=True)
        default = data.get("makeDefault", False)
        if not isinstance(default, bool):
            raise InvalidInput("makeDefault muss ein Wahrheitswert sein.")
        release = version_call(versions.publish, required_value(data.get("draft")), default)
        return jsonify(versions.describe(release))

    @app.post("/api/template-drafts/preview")
    def preview_template_draft():
        import uuid
        from material_core.template_versions import TemplateVersions
        versions = TemplateVersions(config.root)
        data = request.get_json(force=True)
        source = config.safe_path(required_value(data.get("path")))
        ensure_editable(source)
        ensure_renderable(source)
        draft_ref = required_value(data.get("draft"))
        draft = version_call(versions.read_draft, draft_ref)
        release = versions.load(draft["base"])
        template = release["template"]
        engine = "typst" if template.endswith(".typst") else "beamer" if template == "slides-template.tex" else "pdf"
        text = set_template(required_text(data), template, engine)
        text = versions.bind(text, draft["base"])
        text = set_fields(text, {"template-preview-draft": draft_ref})
        preview_source = source.with_name(f"template-preview-{uuid.uuid4().hex}.qmd")
        try:
            preview_source.write_text(text, encoding="utf-8")
            result = builds.build_document(preview_source)
            return jsonify({"pdf": config.relative(result.pdf_path)})
        finally:
            preview_source.unlink(missing_ok=True)

    @app.get("/api/document")
    def document():
        source = config.safe_path(required_arg("path"))
        ensure_editable(source)
        klasse, thema = document_service.klasse_thema_for(source)
        current = runtime.documents.read(source)
        caps = capabilities(source, current["text"])
        try:
            pdf_path = builds.find_pdf(source, text=current["text"]) if caps["render"] else None
        except ValueError:
            # A broken header must remain editable; diagnostics explain the error.
            pdf_path = None
        try:
            output = read_metadata(current["text"]).get("material-output", "pdf")
        except ValueError:
            output = "pdf"
        return jsonify(
            {
                "path": config.relative(source),
                "absolutePath": str(source),
                **current,
                "output": output,
                "capabilities": caps,
                "hasSlides": caps["present"] and has_slides(current["text"]),
                "isPresentation": caps["present"] and is_presentation(current["text"]),
                "pdfCurrent": builds.pdf_is_current(source, current["text"]) if caps["render"] else None,
                "slidesCurrent": runtime.services.slides.is_current(source) if caps["present"] and has_slides(current["text"]) else None,
                "deck": document_service.deck_link(source, current["text"]) if caps["present"] else "",
                "pdf": config.relative(pdf_path),
                "sourceMtime": source.stat().st_mtime,
                "pdfMtime": pdf_path.stat().st_mtime if pdf_path else None,
                "pdfVersion": pdf_version(pdf_path) if pdf_path else None,
                "klasse": klasse,
                "thema": thema,
            }
        )

    @app.post("/api/document/language-check")
    def language_check():
        from material_ui.language_check import check_language
        data = request.get_json(force=True)
        source = config.safe_visible_path(required_value(data.get("path")))
        ensure_editable(source)
        text = required_text(data)
        if len(text) > 100_000:
            raise InvalidInput("Sprachprüfung unterstützt höchstens 100.000 Zeichen.")
        return jsonify(check_language(text))

    @app.post("/api/document/preview")
    def markdown_preview():
        from urllib.parse import quote
        from material_ui.markdown_preview import markdown_html
        data = request.get_json(force=True)
        source = config.safe_visible_path(required_value(data.get("path")))
        ensure_editable(source)
        text = required_text(data)
        if source.suffix != ".md":
            raise InvalidInput("Markdown-Vorschau benötigt eine .md-Datei.")
        folder = config.relative(source.parent)
        html = markdown_html(text, base="/api/document/assets/" + quote(folder, safe="/") + "/")
        return jsonify({"html": html})

    @app.get("/api/document/assets/<path:name>")
    def markdown_asset(name):
        source = config.safe_visible_path(name)
        if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}:
            raise InvalidInput("Nur Bilddateien sind in der Vorschau erlaubt.")
        response = send_file(source)
        response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
        return response

    @app.get("/api/document/history")
    def document_history():
        source = config.safe_path(required_arg("path"))
        ensure_editable(source)
        return jsonify({"versions": runtime.documents.history(source)})

    @app.get("/api/document/history/<identifier>")
    def document_version(identifier):
        source = config.safe_path(required_arg("path"))
        ensure_editable(source)
        return jsonify(runtime.documents.history_snapshot(source, identifier))

    @app.post("/api/document/metadata")
    def document_metadata():
        data = request.get_json(force=True)
        text = required_text(data)
        if "template" in data:
            if not isinstance(data["template"], str):
                raise InvalidInput("template muss eine Zeichenkette sein.")
            engine = data.get("engine")
            text = set_template(text, data["template"], engine)
            if data["template"]:
                from material_core.template_versions import TemplateVersions
                versions = TemplateVersions(config.root)
                reference = data.get("release")
                if reference:
                    text = version_call(versions.bind, text, reference)
                else:
                    builtin = find_template(data["template"], config.root / "src/quarto")
                    if builtin is not None:
                        text = versions.bind(text, versions.latest(versions.initial(str(builtin))))
                if data.get("path") and read_metadata(text).get("template-release"):
                    text = version_call(versions.freeze_context, config.safe_path(data["path"]), text)
        if data.get("fields") is not None:
            fields = data["fields"]
            if not isinstance(fields, dict) or not all(isinstance(key, str) for key in fields):
                raise InvalidInput("fields muss ein Objekt mit Zeichenkettenschluesseln sein.")
            try:
                if "deck-design" in fields:
                    from material_core.designs import design_by_id

                    design_by_id(fields["deck-design"])
                text = set_fields(text, fields)
            except ValueError as error:
                raise InvalidInput(str(error)) from error
        try:
            template = template_value(text)
            metadata = read_metadata(text)
        except ValueError as error:
            raise InvalidInput(str(error)) from error
        return jsonify({"text": text, "template": template, "metadata": metadata, "isPresentation": is_presentation(text), "hasSlides": template_slide_design(text)[0]})

    @app.get("/api/document/new-preview")
    def new_document_preview():
        data = {key: request.args.get(key) for key in ("subject", "grade", "topic", "title", "kind", "filename", "template", "folder")}
        data["mini"] = request.args.get("mini") == "1"
        return jsonify(document_service.preview_target(data))

    @app.post("/api/document/new")
    def new_document():
        data = request.get_json(force=True)
        source = document_service.create_document(data)
        document_service.invalidate_qmd_cache()
        pdf_path = builds.find_pdf(source) if capabilities(source)["render"] else None
        klasse, thema = document_service.klasse_thema_for(source)
        return jsonify(
            {
                "ok": True,
                "path": config.relative(source),
                "absolutePath": str(source),
                **runtime.documents.read(source),
                "pdf": config.relative(pdf_path),
                "sourceMtime": source.stat().st_mtime,
                "pdfMtime": pdf_path.stat().st_mtime if pdf_path else None,
                "klasse": klasse,
                "thema": thema,
                "qmds": document_service.all_entries(),
            }
        )

    @app.post("/api/document/note")
    def document_note():
        """Notiz zu einem QMD anlegen (falls fehlend) und ihren Pfad liefern."""
        data = request.get_json(force=True)
        source = config.safe_visible_path(required_value(data.get("path")))
        ensure_qmd(source)
        try:
            title = document_service.source_meta(source)["title"]
        except (OSError, ValueError):
            title = source.stem.replace("_", " ").replace("-", " ")
        target, created = ensure_worksheet_note(source, title)
        if created:
            document_service.invalidate_qmd_cache()
        return jsonify({"ok": True, "path": config.relative(target), "created": created,
                        **qmds_payload(config, document_service)})

    @app.post("/api/document")
    def save_document():
        data = request.get_json(force=True)
        source = config.safe_path(str(data.get("path", "")))
        ensure_editable(source)
        text = required_text(data)
        with runtime.documents.lock:
            before = runtime.documents.read(source)["text"]
            result = runtime.documents.save(source, text, data.get("revision"))
            text = result.get("text", text)
        caps = capabilities(source, text)
        changed, needs_render = False, False
        if caps["render"]:
            try:
                changed = render_content(before, source) != render_content(text, source)
                pdf_current = builds.pdf_is_current(source, text)
                needs_render = changed or pdf_current is not True or (has_slides(text) and not runtime.services.slides.is_current(source))
            except (ValueError, OSError):
                changed, needs_render = True, True
        document_service.invalidate_qmd_cache(source)
        return jsonify({"ok": True, **result, "capabilities": caps, "hasSlides": caps["present"] and has_slides(text), "isPresentation": caps["present"] and is_presentation(text),
                        "renderChanged": changed, "renderNeeded": needs_render})

    @app.post("/api/import")
    def import_asset():
        data = import_metadata()
        source = config.safe_path(str(data.get("qmdPath", "")))
        ensure_qmd(source)
        payloads = {field: read_import_image(field, data, max_upload_bytes) for field in ("original", "clean")}
        service = AssetService(config.root, runtime.documents)
        result = service.import_images(source, data, payloads)
        document_service.invalidate_qmd_cache()
        return jsonify({"ok": True, **result, "pdf": config.relative(builds.find_pdf(source))})

    @app.get("/api/document/template-update")
    def template_update_offer():
        from material_core.template_versions import TemplateVersions
        source = config.safe_visible_path(required_arg("path"))
        ensure_editable(source)
        snapshot = runtime.documents.read(source)
        offer = version_call(TemplateVersions(config.root).update_offer, snapshot["text"])
        return jsonify({"offer": offer})

    @app.post("/api/document/template-update")
    def review_template_update():
        from material_core.template_versions import TemplateVersions
        data = request.get_json(force=True)
        if not isinstance(data.get("accept"), bool):
            raise InvalidInput("Bitte Template-Update bestätigen oder ablehnen.")
        text = version_call(TemplateVersions(config.root).review_update,
                            required_text(data), required_value(data.get("release")), data["accept"])
        return jsonify({"text": text})

    @app.post("/api/render")
    def render():
        from material_ui.diagnostics import PreflightFailure
        source = config.safe_path(required_value(request.values.get("path") or (request.get_json(silent=True) or {}).get("path")))
        ensure_editable(source)
        ensure_renderable(source)
        from material_core.template_versions import TemplateVersions
        text = runtime.documents.read(source)["text"]
        try:
            read_metadata(text)
        except ValueError:
            # Einen ungültigen YAML-Header meldet die Vorprüfung mit Zeilenangabe (422).
            offer = None
        else:
            offer = version_call(TemplateVersions(config.root).update_offer, text)
        if offer:
            return jsonify({"error": {"code": "template_update_required", "message":
                "Eine neuere Template-Version ist verfügbar. Bitte Rendern erneut starten und die Version wählen."},
                "templateUpdate": offer}), 409
        try:
            identifier = renderer.start(source)
        except PreflightFailure as error:
            return jsonify({"error": {"code": "preflight_failed", "message": str(error)}, "issues": error.issues}), 422
        return jsonify(runtime.jobs.get(identifier)), 202

    @app.get("/api/render/status")
    def render_status():
        return jsonify(renderer.state_payload())

    @app.get("/api/pdf-for")
    def pdf_for():
        source = config.safe_path(required_arg("path"))
        ensure_qmd(source)
        pdf_path = builds.find_pdf(source)
        return jsonify({"pdf": config.relative(pdf_path)})

    @app.post("/api/check")
    def check_document():
        data = request.get_json(force=True)
        source = config.safe_path(str(data.get("path", "")))
        ensure_editable(source)
        text = required_text(data) if "text" in data else None
        return jsonify({"issues": document_service.document_issues(source, text)})

    @app.get("/api/pdf")
    def pdf():
        path_value = request.args.get("path")
        if not path_value:
            if not renderer.state_payload().get("pdf"):
                raise NotFound("Noch kein PDF gerendert.")
            pdf_path = config.safe_path(renderer.state_payload().get("pdf"))
        else:
            pdf_path = config.safe_path(path_value)
        if pdf_path.suffix.lower() != ".pdf" or not pdf_path.exists():
            raise NotFound("PDF nicht gefunden.")
        response = send_file(pdf_path, mimetype="application/pdf")
        version = pdf_version(pdf_path)
        response.headers["Cache-Control"] = (
            "private, max-age=31536000, immutable"
            if request.args.get("v") == version else "no-store"
        )
        return response

    @app.get("/api/source")
    def source_file():
        source = config.safe_path(required_arg("path"))
        ensure_editable(source)
        response = send_file(source, mimetype="text/plain; charset=utf-8", as_attachment=False)
        response.headers["Cache-Control"] = "no-store"
        return response
