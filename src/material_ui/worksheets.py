"""Dauerhafte lokale Besprechungen; Build-Ausgaben bleiben regenerierbar."""
from __future__ import annotations

import json
import shutil
import re
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path

from material_core.state import shared_file
from material_core.filesystem import atomic_write_text
from material_ui.config import AppConfig
from material_ui.errors import InvalidInput
from material_ui.slides import deck_lock


class WorksheetStore:
    def __init__(self, config: AppConfig):
        self.config = config
        self.root = config.root
        self.links_path = shared_file(self.root, 'worksheet-solutions.json')
        self.lock = deck_lock(self.links_path)

    def _safe(self, path):
        if path.resolve() != path.absolute():
            raise InvalidInput('Besprechungspfade mit symbolischen Links sind nicht erlaubt.')
        return self.config.safe_path(str(path))

    def directory(self, source):
        rel = source.relative_to(self.root)
        return self._safe(self.root / 'archiv' / 'besprechungen' / rel.parent / f'{rel.name}.besprechung')

    def links(self):
        with self.lock:
            self._safe(self.links_path)
            return json.loads(self.links_path.read_text()) if self.links_path.exists() else {}

    def set_solution(self, source, solution):
        with self.lock:
            mapping = self.links()
            key = self.config.relative(source)
            if solution == 'auto':
                mapping.pop(key, None)
            else:
                mapping[key] = self.config.relative(solution) if solution is not None else None
            atomic_write_text(self.links_path, json.dumps(mapping, ensure_ascii=False))

    def canvas(self, source, *, new=False):
        with self.lock:
            target = self._safe(self.directory(source) / 'besprechung.excalidraw')
            legacy = self._safe(self.root / 'build' / 'artefakte' / source.relative_to(self.root) / target.name)
            marker = legacy.parent / '.besprechung-migriert'
            if legacy.is_file() and not marker.exists() and not target.exists():
                with deck_lock(legacy), deck_lock(target):
                    if not target.exists():
                        # Copy the entire private directory, including history and annotations.
                        # Leave the original intact until normal build cleanup removes it.
                        destination = target.parent
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        stage = destination.with_name(f'.migration-{uuid.uuid4().hex}')
                        try:
                            if any(p.is_symlink() for p in legacy.parent.rglob('*')):
                                raise InvalidInput('Die alte Besprechung enthält symbolische Links.')
                            shutil.copytree(legacy.parent, stage)
                            stage.rename(destination)
                            atomic_write_text(marker, 'archiv/besprechungen\n')
                        finally:
                            if stage.exists():
                                shutil.rmtree(stage)
            parts = self.parts(source)
            def number(path):
                return int(path.stem.rsplit('-', 1)[1]) if '-' in path.stem else 1
            if parts:
                latest = max(parts, key=number)
                if new:
                    return self._safe(target.with_name(f'besprechung-{number(latest)+1:06d}.excalidraw'))
                return self._safe(latest)
            return target

    def parts(self, source):
        directory = self.directory(source)
        paths = [p for p in directory.glob('besprechung*.excalidraw')
                 if re.fullmatch(r'besprechung(?:-\d{6})?\.excalidraw', p.name)]
        return sorted([self._safe(p) for p in paths if p.is_file()], key=lambda p: int(p.stem.rsplit('-', 1)[1]) if '-' in p.stem else 1)

    def migrate_scope(self, source):
        if source.is_dir():
            base = self._safe(self.root / 'build/artefakte' / source.relative_to(self.root))
            if base.exists():
                for legacy in base.rglob('besprechung.excalidraw'):
                    rel = legacy.parent.relative_to(self.root / 'build/artefakte')
                    if rel.suffix in {'.qmd', '.md'}:
                        self.canvas(self.root / rel)
        elif source.suffix in {'.qmd', '.md'}:
            self.canvas(source)

    def migrate_all(self):
        """Called before cleanup too, including for no-longer-existing sources."""
        base = self._safe(self.root / 'build' / 'artefakte')
        if not base.exists():
            return
        for legacy in base.rglob('besprechung.excalidraw'):
            rel = legacy.parent.relative_to(base)
            if rel.suffix in {'.qmd', '.md'}:
                self.canvas(self.root / rel)

    @contextmanager
    def renaming(self, source, target):
        """Move associations and durable data together; roll back on failure."""
        with self.lock, ExitStack() as locks:
            self.migrate_scope(source)
            old_key, new_key = self.config.relative(source), self.config.relative(target)
            folder = source.is_dir()
            old_dir = (self.root / 'archiv' / 'besprechungen' / source.relative_to(self.root)) if folder else self.directory(source)
            new_dir = (self.root / 'archiv' / 'besprechungen' / target.relative_to(self.root)) if folder else self.directory(target)
            self._safe(old_dir)
            self._safe(new_dir)
            if new_dir.exists() and old_dir != new_dir:
                raise FileExistsError('Am Ziel liegen bereits gespeicherte Besprechungen.')
            for deck in sorted(old_dir.rglob('*.excalidraw')) if old_dir.exists() else []:
                locks.enter_context(deck_lock(deck))
                locks.enter_context(deck_lock(new_dir / deck.relative_to(old_dir)))
            before = self.links()

            def replace(value):
                if value == old_key or (folder and value.startswith(old_key + '/')):
                    return new_key + value[len(old_key):]
                return value

            updated = {replace(key): (replace(value) if isinstance(value, str) else value) for key, value in before.items()}
            if len(updated) != len(before):
                raise FileExistsError('Am Ziel existiert bereits eine Lösungszuordnung.')
            moved = False
            written = False
            try:
                if old_dir.exists():
                    new_dir.parent.mkdir(parents=True, exist_ok=True)
                    old_dir.rename(new_dir)
                    moved = True
                if updated != before:
                    atomic_write_text(self.links_path, json.dumps(updated, ensure_ascii=False))
                    written = True
                yield
            except BaseException:
                if moved:
                    new_dir.rename(old_dir)
                if written:
                    atomic_write_text(self.links_path, json.dumps(before, ensure_ascii=False))
                raise
