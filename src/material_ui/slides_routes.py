from __future__ import annotations

from flask import jsonify, request

from excalideck.generator import DeckDependencyError, DeckExistsError, ModelRenderError
from material_ui.documents import ensure_editable
from material_ui.document_types import ensure_renderable
from material_ui.errors import InvalidInput
from material_ui.http import required_value


def register_slides_routes(app, runtime):
    config = runtime.config
    slides = runtime.services.slides

    def source_from_request():
        data = request.get_json(force=True)
        source = config.safe_path(required_value(data.get("path")))
        ensure_editable(source)
        ensure_renderable(source)
        return source

    @app.post("/api/slides/ensure")
    def slides_ensure():
        source = source_from_request()
        try:
            identifier = slides.start(source)
        except (DeckDependencyError, DeckExistsError, ModelRenderError, ValueError) as error:
            raise InvalidInput(str(error)) from error
        return jsonify({"ok": True, "job_id": identifier}), 202

    @app.post("/api/slides/rebuild")
    def slides_rebuild():
        source = source_from_request()
        try:
            identifier = slides.start(source, force=True)
        except (DeckDependencyError, DeckExistsError, ModelRenderError, ValueError) as error:
            raise InvalidInput(str(error)) from error
        return jsonify({"ok": True, "job_id": identifier}), 202
