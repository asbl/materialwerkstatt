from __future__ import annotations

from flask import request

from material_ui.errors import InvalidInput


def register_unit_routes(app, runtime):
    service = runtime.services.units

    @app.get('/api/units')
    def units():
        return service.overview()

    @app.get('/api/units/folders')
    def unit_folders():
        return service.folder_candidates(request.args.get('klasse', ''), request.args.get('path'))

    @app.post('/api/units/dates')
    def append_unit_dates():
        return service.append_dates(request.get_json(force=True))

    @app.post('/api/units/attach')
    def attach_unit():
        return service.attach(request.get_json(force=True))

    @app.post('/api/units/new')
    def new_unit():
        return service.create(request.get_json(force=True)), 201

    @app.post('/api/units')
    def save_unit():
        data = request.get_json(force=True)
        if not isinstance(data, dict) or not isinstance(data.get('path'), str):
            raise InvalidInput('Einheitenpfad fehlt.')
        return service.save(data['path'], data.get('data'), data.get('revision'))

    @app.post('/api/units/theme-delete')
    def delete_unit_theme():
        return service.delete_theme(request.get_json(force=True))
