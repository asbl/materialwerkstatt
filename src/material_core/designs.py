from __future__ import annotations

import json
from pathlib import Path

from material_core.private_hooks import hook
from material_core.slide_designs import slide_background
from material_core.template_roots import private_root


def load_designs(path: Path, local_path: Path | None = None) -> list[dict]:
    """Eingebauter Katalog plus der private, nicht versionierte Katalog.

    Eintraege des privaten Katalogs (`<privater Ordner>/template-designs.json`) sind als
    `local_only` markiert; ihre Vorlagen, Freigaben und Hintergruende bleiben privat.
    """
    public = json.loads(path.read_text(encoding="utf-8"))
    if local_path is None:
        local_path = private_root() / "template-designs.json"
    local = json.loads(local_path.read_text(encoding="utf-8")) if local_path.is_file() else []
    merged = {design["id"]: design for design in public}
    for design in local:
        merged[design["id"]] = {**design, "local_only": True}
    return list(merged.values())


DESIGNS = load_designs(Path(__file__).with_name("template-designs.json"))
for design in DESIGNS:
    design["slide_background"] = slide_background(design)
    design.update(hook("design_extras", design, default={}))


def design_by_id(value: str | None) -> dict | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("deck-design muss ein Designname als Text sein.")
    design = next((item for item in DESIGNS if item["id"] == value), None)
    if design is None:
        raise ValueError(f"Unbekanntes Folien-Design: {value}")
    return design


def slide_templates() -> list[dict]:
    return [
        {
            "path": "src/quarto/templates/slide-template.typst", "label": "Standard", "kind": "Excalidraw-Folien",
            "tags": ["Excalidraw-Folien"],
            "engine": "Typst", "target": "slides", "design": None,
            "description": "Weiße Folien mit handschriftlichen Überschriften und viel Zeichenfläche.",
            "preview": "16:9 · editierbare Texte und Modelle · freie Zeichenfläche",
        },
        *[
            {
                "path": f"src/quarto/templates/slide-{design['id']}.typst", "label": design["label"],
                "kind": "Excalidraw-Folien", "engine": "Typst", "target": "slides",
                "tags": ["Excalidraw-Folien"],
                "design": design, "description": design["description"],
                "preview": "16:9 · eigene Rahmen und Randmotive · freie Zeichenfläche · Foliennummer",
            }
            for design in DESIGNS
        ],
    ]


def template_slide_design(text: str) -> tuple[bool, dict | None]:
    """The PDF template is authoritative, including when deck-design is stale."""
    from material_core.metadata import template_value

    name = Path(template_value(text).replace("\\", "/")).name
    if name in {"slide-template.typst", "slides-template.tex"}:
        return True, None
    for design in DESIGNS:
        if name == f"slide-{design['id']}.typst" or (
            not design.get("slides_only") and name == f"worksheet-{design['id']}.typst"
        ):
            return True, design
    return False, None


def sync_template_design(text: str) -> str:
    from material_core.metadata import set_fields

    enabled, design = template_slide_design(text)
    return set_fields(text, {"deck-design": design["id"] if enabled and design else "", "material-output": ""})


def resolved_slide_design(text: str, source: Path, root: Path | None = None) -> dict | None:
    """Resolve a release's frozen design for both generation and cache checks."""
    import re
    from material_core.metadata import read_metadata, template_value
    from material_core.template_versions import TemplateVersions

    enabled, design = template_slide_design(text)
    reference = read_metadata(text).get("template-release")
    if not enabled:
        return design_by_id(read_metadata(text).get("deck-design"))
    if not reference:
        return design
    if root is None:
        root = next((p for p in source.resolve().parents if (p / "_quarto.yml").is_file()), None)
    if root is None:
        raise ValueError("Projektwurzel für Template-Version fehlt.")
    versions = TemplateVersions(root)
    release = versions.load(reference)
    if Path(template_value(text)).name != release["template"]:
        raise ValueError("Template-Version passt nicht zur gewählten Vorlage.")
    if "slide-design" in release:
        return json.loads(json.dumps(release["slide-design"]))
    if not design:
        return None
    # Legacy releases have no design snapshot. Recover the literal background
    # and colors from the frozen template instead of rewriting their manifests.
    template = (versions.path(release["layout"]) / "templates" / release["template"]).read_text()
    encoded = re.search(r'image\(bytes\((".*")\), width:', template)
    frozen = dict(design)
    if encoded:
        frozen["slide_background"] = json.loads(encoded[1])
    for name in ("primary", "ink", "paper", "slide-heading-ink"):
        value = re.search(rf'#let {name} = (rgb\("#[0-9a-fA-F]+"\)|white|black|primary)\s*\n', template)
        if value:
            raw = value[1]
            frozen["heading_ink" if name == "slide-heading-ink" else name] = (
                frozen["primary"] if raw == "primary" else
                {"white": "#ffffff", "black": "#000000"}.get(raw, raw[5:-2])
            )
    if "$slide-writing-layout.typst()$" in template:
        # This legacy layout contains no theme-specific box decorations.
        return {k: frozen[k] for k in ("id", "primary", "ink", "paper", "heading_ink", "slide_background")} | {"writing_grid": True}
    return frozen
