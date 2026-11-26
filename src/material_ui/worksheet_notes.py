"""Eine Notiz pro Material, wie Loesungen neben dem AB abgelegt."""
from pathlib import Path
import re
import unicodedata

from material_ui.document_types import is_note

from material_core.filesystem import atomic_write_text

SUFFIX = '-notizen'


def note_target(source: Path) -> Path:
    """Notizpfad zum Material: gleicher Ordner, gleicher Stamm, Endung -notizen.md."""
    return source.with_name(f'{source.stem}{SUFFIX}.md')


def note_skeleton(title: str) -> str:
    from material_ui.assets import yaml_string

    return (
        '---\n'
        f'title: {yaml_string(f"Notizen zu {title}")}\n'
        'kind: Notiz\n'
        'tags: []\n'
        '---\n'
        '\n'
        '## Gut gelaufen\n'
        '\n'
        '- \n'
        '\n'
        '## Für den nächsten Durchlauf\n'
        '\n'
        '- \n'
    )


def ensure_worksheet_note(source: Path, title: str) -> tuple[Path, bool]:
    """Notiz anlegen, wenn sie fehlt; bestehende Notizen werden nie ueberschrieben."""
    target = note_target(source)
    if target.is_file():
        return target, False
    # The navigation also recognizes renamed -notiz / _notizen / _notiz files.
    # Reuse these instead of creating a second note under the canonical name.
    def normalize(value):
        return ''.join(char for char in unicodedata.normalize('NFD', value)
                       if not unicodedata.combining(char)).lower()

    for candidate in sorted(source.parent.iterdir()):
        stem = re.sub(r'[-_](?:notizen|notiz)\.md$', '', candidate.name, flags=re.I)
        if (stem != candidate.name and normalize(stem) == normalize(source.stem)
                and candidate.is_file() and is_note(candidate)):
            return candidate, False
    try:
        atomic_write_text(target, note_skeleton(title), overwrite=False)
    except FileExistsError:
        return target, False
    return target, True
