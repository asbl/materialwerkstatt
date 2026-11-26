"""Document capabilities shared by discovery and API actions."""
from material_ui.metadata import read_metadata
from material_ui.errors import InvalidInput
from material_ui.folder_notes import is_folder_note


def is_note(source, text=None):
    if source.suffix.lower() != ".md" or is_folder_note(source.name):
        return False
    if source.stem.startswith("notiz_"):
        return True
    try:
        return read_metadata(source.read_text(encoding="utf-8") if text is None else text).get("kind") == "Notiz"
    except (ValueError, OSError, UnicodeError):
        return False


def capabilities(source, text=None):
    note = is_note(source, text)
    if source.suffix.lower() == ".md":
        try:
            meta = read_metadata(source.read_text(encoding="utf-8") if text is None else text)
            note = note or not any(meta.get(key) for key in ("template", "template-release", "format"))
        except (ValueError, OSError):
            note = True
    return {"edit": True, "render": not note, "present": not note}


def ensure_renderable(source):
    if not capabilities(source)["render"]:
        raise InvalidInput("Notizen können weder gerendert noch präsentiert werden.")


def ensure_note_rename(source, target):
    if not is_note(source):
        return
    if target.suffix != ".md" or is_folder_note(target.name):
        raise InvalidInput("Notizen benötigen die Endung .md und dürfen keinen reservierten Hinweisnamen tragen.")
    if target.stem.startswith("notiz_"):
        return
    try:
        remains_note = is_note(target, source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        remains_note = False
    if not remains_note:
        raise InvalidInput("Bitte das Präfix notiz_ beibehalten oder im Frontmatter kind: Notiz setzen.")
