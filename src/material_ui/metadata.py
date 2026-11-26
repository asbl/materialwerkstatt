from material_core.metadata import read_metadata, set_fields, set_template, split_frontmatter, template_value
from pathlib import Path
import unicodedata


def solution_filename(path: Path) -> bool:
    name = unicodedata.normalize("NFC", path.stem).casefold().replace("ö", "oe")
    return "loesung" in name


def ensure_solution_metadata(path: Path, text: str) -> str:
    """Persistente, idempotente Kennzeichnung anhand des QMD-Dateinamens."""
    if path.suffix != ".qmd" or not solution_filename(path):
        return text
    from material_ui.assets import parse_tags

    metadata = read_metadata(text)
    tags = parse_tags(metadata.get("tags"))
    fields = {}
    if metadata.get("kind") != "Lösung":
        fields["kind"] = "Lösung"
    if "Lösung" not in tags:
        fields["tags"] = [*tags, "Lösung"]
    return set_fields(text, fields) if fields else text

__all__ = ["read_metadata", "set_fields", "set_template", "split_frontmatter", "template_value"]
