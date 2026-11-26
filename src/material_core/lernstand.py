"""Learning diagnostic metadata, validation and material references."""
from __future__ import annotations

from pathlib import Path
import os
import re

from ruamel.yaml import YAML
from material_core.metadata import read_metadata, output_filename
from material_core.kompetenzen import validate_references


class LernstandError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise LernstandError(message)


def source_path(folder, value, root):
    _require(isinstance(value, str) and value and not Path(value).is_absolute(), 'Materialpfad muss relativ sein.')
    path = (folder / value).resolve()
    _require(path.is_relative_to((root / 'unterricht').resolve()), 'Material muss innerhalb von unterricht liegen.')
    _require(path.suffix == '.qmd', 'Material muss eine QMD-Quelle sein.')
    return path


def validate(data, folder, root):
    """Validate structure separately from missing files (reported by audit)."""
    _require(isinstance(data, dict) and type(data.get('schema')) is int and data['schema'] == 1, 'lernstand.schema muss 1 sein.')
    for key in ('id', 'version'):
        _require(isinstance(data.get(key), str) and re.fullmatch(r'[a-z0-9][a-z0-9._-]*', data[key]), f'lernstand.{key}: ungültige Kennung.')
    competencies = data.get('kompetenzen')
    _require(isinstance(competencies, list) and competencies, 'Kompetenzen fehlen.')
    known, stages = set(), {}
    for item in competencies:
        _require(isinstance(item, dict) and isinstance(item.get('id'), str) and item['id'] not in known, 'Kompetenz-ID fehlt oder ist doppelt.')
        _require(re.fullmatch(r'[a-z0-9][a-z0-9._-]*', item['id']), 'Ungültige Kompetenz-ID.')
        known.add(item['id'])
        if 'zentrale_kompetenzen' in item:
            try:
                validate_references(item['zentrale_kompetenzen'], root)
            except ValueError as error:
                raise LernstandError(str(error)) from error
        _require(isinstance(item.get('titel'), str) and item['titel'].strip(), 'Kompetenztitel fehlt.')
        levels = item.get('stufen')
        _require(isinstance(levels, list) and levels, 'Kompetenzstufen fehlen.')
        stages[item['id']] = set()
        for level in levels:
            _require(isinstance(level, dict) and isinstance(level.get('id'), str) and level['id'] not in stages[item['id']], 'Stufen-ID fehlt oder ist doppelt.')
            _require(isinstance(level.get('beschreibung'), str) and level['beschreibung'].strip(), 'Stufenbeschreibung fehlt.')
            _require(re.fullmatch(r'[a-z0-9][a-z0-9._-]*', level['id']), 'Ungültige Stufen-ID.')
            stages[item['id']].add(level['id'])
    materials = data.get('materialien')
    _require(isinstance(materials, list) and materials, 'Materialien fehlen.')
    ids, destinations = set(), set()
    for item in materials:
        _require(isinstance(item, dict) and isinstance(item.get('id'), str) and item['id'] not in ids, 'Material-ID fehlt oder ist doppelt.')
        _require(re.fullmatch(r'[a-z0-9][a-z0-9._-]*', item['id']), 'Ungültige Material-ID.')
        ids.add(item['id'])
        _require(item.get('rolle') in ('diagnose', 'nachtest', 'foerdermaterial', 'wegweiser'), 'Ungültige Materialrolle.')
        if 'titel' in item:
            _require(isinstance(item['titel'], str), 'Materialtitel muss Text sein.')
        source_path(folder, item.get('quelle'), root)
        if 'loesung' in item:
            source_path(folder, item['loesung'], root)
        for flag in ('online', 'loesung_online'):
            _require(type(item.get(flag, False)) is bool, f'{flag} muss wahr oder falsch sein.')
        for key in ('kompetenz', 'stufe'):
            if key in item:
                _require(isinstance(item[key], str), f'{key} muss Text sein.')
        if item['rolle'] == 'foerdermaterial':
            _require(isinstance(item.get('kompetenz'), str) and isinstance(item.get('stufe'), str), 'Kompetenz und Stufe müssen Text sein.')
            _require(item.get('kompetenz') in known and item.get('stufe') in stages.get(item.get('kompetenz'), set()), 'Unbekannte Kompetenz oder Stufe.')
        if 'online_pfad' in item:
            _require(isinstance(item['online_pfad'], str), 'Online-Pfad muss Text sein.')
            p = Path(item['online_pfad'])
            _require(not p.is_absolute() and '..' not in p.parts and p.suffix == '.pdf', 'Ungültiger Online-Pfad.')
            _require(p.as_posix() not in destinations, 'Doppelter Online-Pfad.')
            destinations.add(p.as_posix())
    by_id = {item['id']: item for item in materials}
    tasks = data.get('aufgaben', [])
    _require(isinstance(tasks, list), 'aufgaben muss eine Liste sein.')
    task_ids = set()
    for task in tasks:
        _require(isinstance(task, dict) and isinstance(task.get('id'), str) and task['id'] not in task_ids, 'Aufgaben-ID fehlt oder ist doppelt.')
        task_ids.add(task['id'])
        _require(isinstance(task.get('nummer', ''), str), 'Aufgabennummer bitte als Text angeben.')
        _require(isinstance(task.get('diagnose'), str) and isinstance(task.get('kompetenz'), str), 'Diagnose und Kompetenz müssen Text sein.')
        _require(task.get('diagnose') in by_id and by_id[task['diagnose']]['rolle'] in ('diagnose', 'nachtest', 'wegweiser'), 'Diagnose fehlt.')
        _require(task.get('kompetenz') in known, 'Aufgabenkompetenz fehlt.')
        _require(isinstance(task.get('empfehlung'), list), 'Förderempfehlung muss eine Liste sein.')
        for mid in task['empfehlung']:
            _require(isinstance(mid, str) and mid in by_id and by_id[mid]['rolle'] == 'foerdermaterial' and by_id[mid]['kompetenz'] == task['kompetenz'], 'Ungültige Förderempfehlung.')
    return data


def manifests(root):
    """Visit teaching units without traversing course exports or local history."""
    for directory, children, files in os.walk(root / 'unterricht'):
        parent = Path(directory)
        children[:] = [name for name in children if not name.startswith('.')
                       and name not in {'build', 'kurse', 'libraries', 'node_modules', 'assets'}
                       and not (parent / name).is_symlink()]
        if 'einheit.yaml' in files:
            yield parent / 'einheit.yaml'


def unique_id(folder, root, unit_id):
    from ruamel.yaml.error import YAMLError
    for path in manifests(root):
        if path.parent.resolve() == folder.resolve():
            continue
        try:
            unit = YAML(typ='safe').load(path.read_text(encoding='utf-8'))
        except (OSError, YAMLError):
            continue
        other = unit.get('lernstand') if isinstance(unit, dict) else None
        _require(not isinstance(other, dict) or other.get('id') != unit_id,
                 f'Lernstand-ID {unit_id} wird bereits verwendet: {path}')


def load(folder, root):
    unit = YAML(typ='safe').load((folder / 'einheit.yaml').read_text(encoding='utf-8'))
    _require(isinstance(unit, dict), 'einheit.yaml muss eine Zuordnung sein.')
    data = validate(unit.get('lernstand'), folder, root)
    return unit, data


def audit(data, folder, root):
    validate(data, folder, root)
    errors, warnings = [], []
    for item in data['materialien']:
        for key in ('quelle', 'loesung'):
            if key in item and not source_path(folder, item[key], root).is_file():
                errors.append(f"{item['id']}: {key} fehlt: {item[key]}")
    for task in data.get('aufgaben', []):
        if not task['empfehlung']:
            warnings.append(f"{task['id']}: Fördermaterial fehlt ({task.get('hinweis', 'noch nicht zugeordnet')}).")
    for comp in data['kompetenzen']:
        if 'zentrale_kompetenzen' not in comp:
            warnings.append(f"{comp['id']}: Zuordnung zu zentralen Kompetenzen fehlt.")
        for stage in comp['stufen']:
            if not any(item.get('kompetenz') == comp['id'] and item.get('stufe') == stage['id'] for item in data['materialien']):
                warnings.append(f"{comp['id']}/{stage['id']}: Noch kein Fördermaterial vorhanden.")
    if not data.get('aufgaben'):
        warnings.append('Noch keine Diagnoseaufgaben zugeordnet.')
    return {'fehler': errors, 'hinweise': warnings}


def pdf_path(source, root):
    metadata = read_metadata(source.read_text(encoding='utf-8'))
    name = output_filename('', source.stem + '.pdf', metadata=metadata)
    return root / 'build/pdf' / source.parent.relative_to(root) / Path(name).name

