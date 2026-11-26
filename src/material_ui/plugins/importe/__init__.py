"""Importe-Plugin: Office-Dokumente (PDF/DOCX) und Aufgabenbilder (Zwischenablage).

Nutzt das Interface `chat` des chat-Plugins für den KI-Umbau gestagter Inhalte
(dependsOn @chat). Die HTTP-Pfade bleiben stabil unter /api/document/import/...,
 damit Desktop-Starter, Frontend und MCP-Client des chat-Plugins unverändert bleiben.
"""
from __future__ import annotations

from . import office_import, task_image_import
from .office_routes import build_blueprint as build_office_blueprint
from .task_image_routes import build_blueprint as build_task_image_blueprint


def register(ctx) -> None:
    ctx.register_routes(build_office_blueprint(ctx, office_import.MAX_OFFICE_BYTES))
    ctx.register_routes(build_task_image_blueprint(ctx, task_image_import.MAX_TASK_IMAGE_BYTES))
