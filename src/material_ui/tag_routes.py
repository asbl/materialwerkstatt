from __future__ import annotations

from flask import jsonify, request

from material_ui.errors import InvalidInput
from material_ui.http import required_value
from material_ui.index_payload import qmds_payload


def register_tag_routes(app, runtime):
    config = runtime.config
    document_service = runtime.services.documents

    @app.get("/api/tags")
    def tags():
        """Tag-Vokabular des QMD-Index mit Vorkommenszaehlung."""
        return jsonify({
            "tags": document_service.tag_counts(),
            "rootTags": document_service.root_tags(),
            "tagParents": document_service.tag_parents(),
        })

    @app.post("/api/tags/rename")
    def rename_tag():
        """Benennt einen Tag-Pfad (und seine Nachfahren) in allen QMDs um, fuer die Baumpflege im Tag-Explorer."""
        data = request.get_json(force=True)
        changed = document_service.rename_tag(required_value(data.get("from")), required_value(data.get("to")))
        return jsonify({"ok": True, "changed": changed, **qmds_payload(config, document_service)})

    @app.post("/api/tags/root")
    def set_tag_root():
        """Markiert/entmarkiert einen Tag als Root-Tag fuer die oberste Ebene des Tag-Baums."""
        data = request.get_json(force=True)
        root = data.get("root")
        if not isinstance(root, bool):
            raise InvalidInput("root muss als boolescher Wert angegeben werden.")
        document_service.set_tag_root(required_value(data.get("tag")), root)
        return jsonify({"ok": True, **qmds_payload(config, document_service)})

    @app.post("/api/tags/parent")
    def set_tag_parent():
        """Setzt oder loescht den extern verwalteten Eltern-Tag eines Tags fuer die Baumansicht (Frontmatter bleibt unveraendert)."""
        data = request.get_json(force=True)
        parent = data.get("parent")
        if parent is not None and not isinstance(parent, str):
            raise InvalidInput("parent muss eine Zeichenkette oder null sein.")
        document_service.set_tag_parent(required_value(data.get("tag")), parent or None)
        return jsonify({"ok": True, **qmds_payload(config, document_service)})
