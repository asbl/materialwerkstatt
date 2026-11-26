"""Versioniertes Metadatenmodell für allgemeine Förderangebote (ohne Schülerdaten)."""
from __future__ import annotations

import re
from pathlib import Path

from ruamel.yaml import YAML

from material_core.kompetenzen import validate_references


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} muss nicht leerer Text sein.')


def _fields(data, required, optional=()):
    if not isinstance(data, dict) or not set(required) <= set(data):
        raise ValueError(f'Pflichtfelder fehlen: {", ".join(required)}.')
    if set(data) - set(required) - set(optional):
        raise ValueError('Unbekannte Felder im Förderangebot.')


def material_path(folder: Path, value: str, root: Path) -> Path:
    _text(value, 'quelle')
    if Path(value).is_absolute():
        raise ValueError('quelle muss relativ zum Angebot sein.')
    path = (folder / value).resolve()
    base = root.resolve() / 'foerdermaterial'
    if not path.is_relative_to(base) or path.suffix != '.qmd':
        raise ValueError('Quelle muss eine QMD-Datei innerhalb von foerdermaterial sein.')
    return path


def validate(data, folder: Path, root: Path):
    _fields(data, ('schema', 'id', 'titel', 'zentrale_kompetenzen', 'niveau', 'aufgaben'),
            ('hilfen', 'loesungen', 'dauer_minuten'))
    if type(data['schema']) is not int or data['schema'] != 1:
        raise ValueError('Förderangebot benötigt schema: 1.')
    if not isinstance(data['id'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', data['id']):
        raise ValueError('Ungültige Förderangebot-ID.')
    _text(data['titel'], 'titel')
    _text(data['niveau'], 'niveau')
    validate_references(data['zentrale_kompetenzen'], root)
    if 'dauer_minuten' in data and (type(data['dauer_minuten']) is not int or data['dauer_minuten'] <= 0):
        raise ValueError('dauer_minuten muss eine positive ganze Zahl sein.')
    for key in ('aufgaben', 'hilfen', 'loesungen'):
        entries = data.get(key, [])
        if not isinstance(entries, list) or (key == 'aufgaben' and not entries):
            raise ValueError(f'{key} muss eine Liste sein; Aufgaben dürfen nicht fehlen.')
        for entry in entries:
            _fields(entry, ('quelle', 'fundstelle'))
            material_path(folder, entry['quelle'], root)
            _text(entry['fundstelle'], 'fundstelle')
    return data


def load(path: Path, root: Path):
    if not path.resolve().is_relative_to(root.resolve() / 'foerdermaterial'):
        raise ValueError('Förderangebot muss innerhalb von foerdermaterial liegen.')
    return validate(YAML(typ='safe').load(path.read_text(encoding='utf-8')), path.parent, root)


def audit(data, folder: Path, root: Path):
    validate(data, folder, root)
    missing = [f'{key}: Quelle fehlt.' for key in ('aufgaben', 'hilfen', 'loesungen')
               for entry in data.get(key, []) if not material_path(folder, entry['quelle'], root).is_file()]
    return {'fehler': missing, 'hinweise': []}


def catalog(root: Path):
    """IDs sind innerhalb des Fördermaterialbestands eindeutig und pfadunabhängig."""
    result = {}
    for path in sorted((root / 'foerdermaterial').rglob('angebot.yaml')):
        if any(part.startswith('.') for part in path.relative_to(root).parts):
            continue
        data = load(path, root)
        if data['id'] in result:
            raise ValueError(f'Doppelte Förderangebot-ID: {data["id"]}.')
        result[data['id']] = data
    return result
