from __future__ import annotations

import secrets
import base64
import json
import re
from typing import Any

from flask import Flask, jsonify, request
from werkzeug.exceptions import BadRequest, Forbidden, HTTPException

from material_ui.errors import InvalidInput, MarketplaceUnavailable, PluginConflict
from material_ui.jobs import JobBusy
from material_ui.storage import RevisionConflict
from material_ui.protocol import API_VERSION, CAPABILITIES


def configure_http(app: Flask, max_upload_bytes: int) -> None:
    app.config.update(MAX_CONTENT_LENGTH=max_upload_bytes * 2 + 65536, TRUSTED_HOSTS=["127.0.0.1", "localhost", "[::1]"])
    app.config["MATERIAL_CSRF_TOKEN"] = secrets.token_urlsafe(32)

    @app.before_request
    def validate_request():
        if (request.endpoint == "static" and request.view_args.get("filename") == "api-contract.json"
                and request.args.get("v") and request.args["v"] != app.config.get("MATERIAL_ASSET_VERSION")):
            return jsonify({"error": {"code": "incompatible_protocol", "message":
                "Die Oberfläche gehört zu einer anderen Serverversion. Bitte die Seite neu laden."}}), 426
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            version = request.headers.get("X-Material-API-Version")
            if version is not None and request.path != "/api/server/restart":
                required = set(filter(None, request.headers.get("X-Material-Capabilities", "").split(",")))
                if version != str(API_VERSION) or not required.issubset(CAPABILITIES):
                    return jsonify({"error": {"code": "incompatible_protocol", "message":
                        "Material-UI und Server sind nicht kompatibel. Bitte die Seite neu laden."}}), 426
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                raise Forbidden("Unzulässiger Ursprung.")
            if not app.testing and not secrets.compare_digest(
                request.headers.get("X-Material-Token", ""), app.config["MATERIAL_CSRF_TOKEN"]
            ):
                raise Forbidden("Ungültiger Anfrage-Token. Bitte Seite neu laden.")
            if request.is_json and not isinstance(request.get_json(), dict):
                raise BadRequest("Ein JSON-Objekt wird erwartet.")
            if request.is_json:
                for name in (
                    "text", "path", "qmdPath", "revision", "chapter", "target", "slug", "title",
                    "filename", "subject", "grade", "topic", "kind", "template", "language", "engine", "folder", "name",
                    "session", "import",
                ):
                    value = request.get_json().get(name)
                    if value is not None and not isinstance(value, str):
                        raise BadRequest(f"{name} muss eine Zeichenkette sein.")

    @app.errorhandler(Exception)
    def api_error(error):
        if isinstance(error, (RevisionConflict, JobBusy, FileExistsError, PluginConflict)):
            status, code = 409, "conflict"
        elif isinstance(error, MarketplaceUnavailable):
            status, code = 502, "marketplace_unavailable"
        elif isinstance(error, FileNotFoundError):
            status, code = 404, "not_found"
        elif isinstance(error, InvalidInput):
            status, code = 400, "invalid_input"
        elif isinstance(error, HTTPException):
            status, code = error.code, error.name.lower().replace(" ", "_")
        else:
            app.logger.exception("Material-UI-Anfrage fehlgeschlagen")
            status, code = 500, "internal_error"
        message = "Interner Fehler." if status == 500 else str(error.description if isinstance(error, HTTPException) else error)
        return jsonify({"error": {"code": code, "message": message}}), status

    @app.after_request
    def no_store(response):
        if request.endpoint == "static":
            version = app.config.get("MATERIAL_ASSET_VERSION")
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable"
                if version and request.args.get("v") == version
                else "no-cache"
            )
        elif request.endpoint == "pdf" and response.status_code in {200, 206, 304}:
            # The PDF route only permits caching for a matching file version.
            pass
        else:
            response.headers["Cache-Control"] = "no-store"
        return response


def required_arg(name: str) -> str:
    return required_value(request.args.get(name))


def required_value(value: Any) -> str:
    if not value:
        raise InvalidInput("Pflichtwert fehlt.")
    return str(value)


def required_text(data: dict[str, Any]) -> str:
    if not isinstance(data.get("text"), str):
        raise InvalidInput("Text muss als Zeichenkette angegeben werden.")
    return data["text"]


def moodle_target_args(data: dict[str, Any]) -> list[str]:
    target = str(data.get("target") or "").strip()
    return [f"--target={target}"] if target else []


def decode_data_url(data_url: str, max_upload_bytes: int = 24 * 1024 * 1024) -> bytes:
    match = re.match(r"^data:image/png;base64,(.+)$", data_url)
    if not match:
        raise InvalidInput("PNG-Daten fehlen.")
    encoded = match.group(1)
    if len(encoded) > ((max_upload_bytes + 2) // 3) * 4:
        raise InvalidInput("Bild ist zu groß für den Import.")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise InvalidInput("Ungültige PNG-Daten.") from None
    if len(payload) > max_upload_bytes:
        raise InvalidInput("Bild ist zu groß für den Import.")
    return payload


def import_metadata() -> dict[str, Any]:
    if request.files:
        metadata = request.form.get("metadata", "{}")
        try:
            data = json.loads(metadata)
        except json.JSONDecodeError as error:
            raise InvalidInput("Import-Metadaten sind kein gültiges JSON.") from error
        if not isinstance(data, dict):
            raise InvalidInput("Import-Metadaten müssen ein Objekt sein.")
        data["_multipart"] = True
        return data
    return request.get_json(force=True)


def read_import_image(field: str, data: dict[str, Any], max_upload_bytes: int = 24 * 1024 * 1024) -> bytes:
    if data.get("_multipart"):
        storage = request.files.get(field)
        if storage is None:
            raise InvalidInput(f"Bildfeld fehlt: {field}")
        payload = storage.read(max_upload_bytes + 1)
        if len(payload) > max_upload_bytes:
            raise InvalidInput("Bild ist zu groß für den Import.")
        return payload
    return decode_data_url(str(data.get(f"{field}DataUrl", "")), max_upload_bytes)
