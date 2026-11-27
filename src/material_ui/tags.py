"""Tag vocabulary, hierarchy settings and repository-wide renaming."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from material_core.state import shared_file
from material_ui.assets import normalize_tag_path, parse_tags, tag_path_matches
from material_ui.errors import InvalidInput
from material_ui.metadata import read_metadata, set_fields
from material_ui.storage import atomic_write_text

SUBJECT_FOLDER_PARENTS = ("unterricht", "wissen")


def subject_folder_names(root: Path) -> set[str]:
    """Namen der Fachordner unter unterricht/ und wissen/, fuer die Root-Tag-Vorbelegung."""
    names: set[str] = set()
    for parent in SUBJECT_FOLDER_PARENTS:
        folder = root / parent
        if not folder.is_dir():
            continue
        names.update(child.name.lower() for child in folder.iterdir() if child.is_dir() and not child.name.startswith("."))
    return names


class TagService:
    def __init__(self, documents):
        self.documents = documents
        self.config = documents.config
        self.repository = documents.repository

    def tag_counts(self) -> list[dict[str, Any]]:
        """Tag-Vokabular des Index mit Vorkommenszaehlung, haeufigste Tags zuerst."""
        counts: dict[str, int] = {}
        for entry in self.documents.qmd_entries_cached():
            for tag in entry.get("tags", []):
                counts[tag] = counts.get(tag, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [{"tag": tag, "count": count} for tag, count in ranked]


    def rename_tag(self, old_path: str, new_path: str) -> list[str]:
        """Benennt einen Tag-Pfad und alle seine Nachfahren in allen QMDs um; liefert geaenderte Pfade."""
        old_scope = normalize_tag_path(old_path)
        new_scope = normalize_tag_path(new_path)
        if not old_scope or not new_scope:
            raise InvalidInput("Tag-Pfad darf nicht leer sein.")
        if old_scope == new_scope:
            return []
        changed: list[str] = []
        with self.repository.lock:
            for source in self.documents.qmd_sources():
                text = self.documents.read_source(source)
                if text is None:
                    continue
                try:
                    tags = parse_tags(read_metadata(text).get("tags"))
                except ValueError:
                    continue
                if not tags:
                    continue
                renamed = [
                    new_scope + tag[len(old_scope):] if tag_path_matches(tag, old_scope) else tag
                    for tag in tags
                ]
                if renamed == tags:
                    continue
                self.repository.save(source, set_fields(text, {"tags": renamed}))
                changed.append(self.config.relative(source) or "")
            settings = self._load_tag_settings()
            root_tags = settings.get("rootTags")
            tag_parents = settings.get("tagParents")
            updates: dict[str, Any] = {}
            if root_tags is not None:
                migrated_roots = [
                    new_scope + tag[len(old_scope):] if tag_path_matches(tag, old_scope) else tag
                    for tag in root_tags
                ]
                if migrated_roots != root_tags:
                    updates["rootTags"] = migrated_roots
            if tag_parents:
                migrated_parents = {
                    (new_scope + child[len(old_scope):] if tag_path_matches(child, old_scope) else child):
                        (new_scope + parent[len(old_scope):] if tag_path_matches(parent, old_scope) else parent)
                    for child, parent in tag_parents.items()
                }
                if migrated_parents != tag_parents:
                    updates["tagParents"] = migrated_parents
            if updates:
                self._save_tag_settings({**settings, **updates})
        if changed:
            self.documents.invalidate_qmd_cache()
        return changed


    def _tag_settings_path(self) -> Path:
        return shared_file(self.config.root, "tag-settings.json")


    def _load_tag_settings(self) -> dict[str, Any]:
        try:
            data = json.loads(self._tag_settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}


    def _save_tag_settings(self, data: dict[str, Any]) -> None:
        atomic_write_text(self._tag_settings_path(), json.dumps(data, ensure_ascii=False, indent=2))


    def _tag_prefixes(self) -> set[str]:
        """Alle Tag-Pfade und ihre Praefixe, z. B. {"klasse-10", "klasse-10/klausuren"} fuer den Tag klasse-10/klausuren."""
        prefixes: set[str] = set()
        for entry in self.documents.qmd_entries_cached():
            for tag in entry.get("tags", []):
                prefix = ""
                for segment in tag.split("/"):
                    prefix = f"{prefix}/{segment}" if prefix else segment
                    prefixes.add(prefix)
        return prefixes


    def root_tags(self) -> list[str]:
        """Root-Tags fuer die Baumansicht; Vorbelegung aus den Fachordnern unter unterricht/ und wissen/."""
        available = self._tag_prefixes()
        settings = self._load_tag_settings()
        stored = settings.get("rootTags")
        if stored is None:
            folder_names = subject_folder_names(self.config.root)
            top_segments = {tag.split("/", 1)[0] for entry in self.documents.qmd_entries_cached() for tag in entry.get("tags", [])}
            stored = sorted(segment for segment in top_segments if segment.lower() in folder_names)
            # Eine leere Vorbelegung nicht festhalten: Auf einem noch nicht fertig
            # synchronisierten Rechner wuerde sie die vorhandenen Einstellungen verdraengen.
            if stored:
                self._save_tag_settings({**settings, "rootTags": stored})
            return stored
        return [tag for tag in stored if tag in available]


    def set_tag_root(self, tag: str, root: bool) -> list[str]:
        """Markiert/entmarkiert einen Tag als Root-Tag fuer die Baumansicht."""
        tag = normalize_tag_path(tag)
        if not tag:
            raise InvalidInput("Tag darf nicht leer sein.")
        with self.repository.lock:
            current = self.root_tags()
            if root and tag not in current:
                current = sorted(current + [tag])
            elif not root and tag in current:
                current = [item for item in current if item != tag]
            else:
                return current
            settings = self._load_tag_settings()
            self._save_tag_settings({**settings, "rootTags": current})
        return current


    def tag_parents(self) -> dict[str, str]:
        """Extern verwaltete Eltern-Tag-Zuordnung (Tag -> Eltern-Tag) fuer die Baumansicht; das Frontmatter bleibt flach."""
        available = self._tag_prefixes()
        stored = self._load_tag_settings().get("tagParents") or {}
        return {child: parent for child, parent in stored.items() if child in available and parent in available}


    def set_tag_parent(self, tag: str, parent: str | None) -> dict[str, str]:
        """Setzt oder loescht den externen Eltern-Tag fuer `tag`; verhindert Selbstbezug und Zyklen."""
        tag = normalize_tag_path(tag)
        if not tag:
            raise InvalidInput("Tag darf nicht leer sein.")
        parent = normalize_tag_path(parent) if parent else ""
        with self.repository.lock:
            settings = self._load_tag_settings()
            current = dict(settings.get("tagParents") or {})
            if parent:
                if parent == tag:
                    raise InvalidInput("Ein Tag kann nicht sein eigener Eltern-Tag sein.")
                cursor = parent
                visited: set[str] = set()
                while cursor in current and cursor not in visited:
                    if cursor == tag:
                        raise InvalidInput("Diese Zuordnung wuerde einen Kreis im Tag-Baum erzeugen.")
                    visited.add(cursor)
                    cursor = current[cursor]
                if cursor == tag:
                    raise InvalidInput("Diese Zuordnung wuerde einen Kreis im Tag-Baum erzeugen.")
                current[tag] = parent
            else:
                current.pop(tag, None)
            self._save_tag_settings({**settings, "tagParents": current})
        return current
