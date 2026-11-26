"""Interactive template updates shared with managed command-line builds."""
from __future__ import annotations

import sys
from pathlib import Path

from material_core.filesystem import atomic_write_text
from material_core.template_versions import TemplateVersions


def review_before_build(root: Path, source: Path, choice="ask", *, interactive=None, ask=None):
    if choice not in {"ask", "keep", "latest"}:
        raise ValueError("Template-Update: ask, keep oder latest wählen.")
    versions = TemplateVersions(root)
    text = source.read_text(encoding="utf-8")
    offer = versions.update_offer(text)
    if not offer:
        return False
    if choice == "ask":
        if not (sys.stdin.isatty() if interactive is None else interactive):
            raise ValueError(
                f"{source.relative_to(root)}: Template v{offer['version']} verfügbar "
                f"(bisher v{offer['currentVersion']}). Entscheidung erforderlich: "
                "interaktiv starten oder --template-update=latest / --template-update=keep angeben."
            )
        prompt = (f"{source.relative_to(root)}: Template v{offer['version']} "
                  f"statt v{offer['currentVersion']} verwenden? [j/N] ")
        answer = (ask or input)(prompt).strip().lower()
        while answer not in {"", "j", "ja", "y", "yes", "n", "nein", "no"}:
            answer = (ask or input)("Bitte j oder n eingeben: ").strip().lower()
        accept = answer in {"j", "ja", "y", "yes"}
    else:
        accept = choice == "latest"
    updated = versions.review_update(text, offer["release"], accept)

    def check_revision():
        if source.read_text(encoding="utf-8") != text:
            raise ValueError("Dokument wurde während der Template-Nachfrage geändert. Bitte erneut bauen.")

    atomic_write_text(source, updated, before_replace=check_revision)
    return True
