"""One folder note, with lossless consolidation of older topic-specific notes."""
import json
import re

from material_core.filesystem import atomic_write_text
from material_ui.errors import InvalidInput
from material_ui.storage import revision, RevisionConflict

FILENAME = 'hinweise.md'


def is_folder_note(name):
    if name.lower().startswith("notiz_"):
        return False
    return bool(re.fullmatch(r'(?:.*[-_])?hinweise\.md', name, re.IGNORECASE))


def read_notes(folder):
    files = sorted(p for p in folder.iterdir() if p.is_file() and is_folder_note(p.name))
    if any(p.is_symlink() for p in files):
        raise InvalidInput('Verlinkte Hinweisdateien können nicht als Ordnerhinweise bearbeitet werden.')
    contents = [(p.name, p.read_text(encoding='utf-8')) for p in files]
    text = '\n\n'.join(text if name.lower() == FILENAME else f'## {name[:-3]}\n\n{text}'
                         for name, text in contents)
    return {'text': text, 'revision': revision(json.dumps(contents, ensure_ascii=False))}


def save_notes(folder, text, expected):
    if not isinstance(text, str):
        raise InvalidInput('Hinweise müssen Text sein.')
    if read_notes(folder)['revision'] != expected:
        raise RevisionConflict('Die Ordnerhinweise wurden geändert. Bitte neu laden.')
    old = [p for p in folder.iterdir() if p.is_file() and is_folder_note(p.name) and p.name != FILENAME]
    # Write the full merged text before removing any legacy file.
    if text or old or (folder / FILENAME).exists():
        atomic_write_text(folder / FILENAME, text)
    for path in old:
        path.unlink()
