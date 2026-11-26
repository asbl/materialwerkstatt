"""Gemeinsamer, rein fachlicher Zugriff auf zentrale Teilkompetenzen."""
from __future__ import annotations

import re
from pathlib import Path

from material_core.metadata import read_metadata


def katalog(root: Path, fach: str) -> dict[str, dict]:
    if not isinstance(fach, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', fach):
        raise ValueError('Ungültiges Fach.')
    directory = root / 'wissen/kompetenzraster' / fach / 'teilkompetenzen'
    result = {}
    for path in sorted(directory.glob('*.md')):
        meta = read_metadata(path.read_text(encoding='utf-8'))
        for item in meta.get('kompetenzen', []):
            kid = item.get('id') if isinstance(item, dict) else None
            if not isinstance(kid, str) or not re.fullmatch(r'\w[\w.-]*', kid):
                raise ValueError(f'Ungültige zentrale Kompetenz-ID in {path.name}.')
            if kid in result:
                raise ValueError(f'Doppelte zentrale Kompetenz-ID: {fach}/{kid}.')
            result[kid] = {**item, 'bereich': meta.get('bereich', path.stem),
                           'datei': f'wissen/kompetenzraster/{fach}/teilkompetenzen/{path.name}'}
    return result


def validate_references(refs, root: Path) -> None:
    """Fach + ID bilden die Referenz; keine stillschweigende Namenszuordnung."""
    if not isinstance(refs, list) or not refs:
        raise ValueError('zentrale_kompetenzen muss eine nicht leere Liste sein.')
    seen, catalogs = set(), {}
    for ref in refs:
        if (not isinstance(ref, dict) or set(ref) != {'fach', 'id'}
                or not isinstance(ref['fach'], str) or not isinstance(ref['id'], str)):
            raise ValueError('Kompetenzreferenz benötigt ausschließlich fach und id als Text.')
        key = (ref['fach'], ref['id'])
        if key in seen:
            raise ValueError(f'Doppelte Kompetenzreferenz: {key}.')
        seen.add(key)
        if ref['fach'] not in catalogs:
            catalogs[ref['fach']] = katalog(root, ref['fach'])
        if ref['id'] not in catalogs[ref['fach']]:
            raise ValueError(f'Unbekannte zentrale Kompetenz: {ref["fach"]}/{ref["id"]}.')
