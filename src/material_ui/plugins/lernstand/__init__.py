"""Optional publication UI and routes. Metadata remains in material_core."""


def register(ctx):
    from flask import Blueprint, request, send_file
    from io import BytesIO
    from material_ui.errors import InvalidInput
    # Use the canonical import so CLI and host share the same implementation.
    from material_ui.plugins.lernstand import export as publication

    service = ctx.unit_service
    bp = Blueprint('lernstand_publication', __name__)

    @bp.post('/api/units/lernstand/export')  # Compatibility alias, owned by the plugin.
    @bp.post('/api/plugins/lernstand/export')
    def export_package():
        payload = request.get_json(force=True)
        if not isinstance(payload, dict) or not isinstance(payload.get('path'), str):
            raise InvalidInput('Einheitenpfad fehlt.')
        folder = service.folder(payload['path'])
        try:
            with publication.snapshot(folder, ctx.config.root,
                build=lambda source: publication.ensure_pdf(source, ctx.builds),
                solutions=payload.get('loesungen') is True) as target:
                package = BytesIO((target / 'paket.zip').read_bytes())
                import json
                unit_id = json.loads((target / 'katalog.json').read_text())['id']
            return send_file(package, mimetype='application/zip', as_attachment=True, download_name=unit_id + '.zip')
        except publication.LernstandError as error:
            raise InvalidInput(str(error)) from error

    ctx.register_routes(bp)
