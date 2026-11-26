"""Chat-Plugin: KI-Assistent (Claude/Codex/Vibe-CLI) mit Wissensbasis-Werkzeugen.

Stellt das Interface `chat` bereit (provides), das andere Plugins (z. B. `importe`
fuer den KI-Umbau gestagter Dokumente) ueber `ctx.service("chat")` nutzen.
"""
from __future__ import annotations

from .routes import build_blueprint
from .service import ChatService


def register(ctx) -> None:
    service = ChatService(ctx.config)
    ctx.chat_service = service
    ctx.register_service("chat", service)
    ctx.lifecycle.on_shutdown(service.close)
    ctx.register_routes(build_blueprint(ctx))
