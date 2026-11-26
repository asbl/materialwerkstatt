from __future__ import annotations

from contextlib import ExitStack, nullcontext
import json
import re
import uuid
from pathlib import Path

from werkzeug.exceptions import NotFound

from material_core.builds import OUTPUT_ARTIFACT_DIR, OUTPUT_ROOT
from material_core.filesystem import atomic_write_bytes, atomic_write_text
from material_ui.errors import InvalidInput
from material_ui.slides import deck_lock
from material_ui.units import UnitService


class FolderService:
    def __init__(self, config, repository, slides, *, worksheets=None, units=None):
        self.config = config
        self.repository = repository
        self.slides = slides
        self.worksheets = worksheets
        self.units = units if units is not None else UnitService(config, None)

    def source_folder(self, value: str) -> Path:
        # Check the lexical path before safe_path resolves symlinks, including
        # symlinks in parent components. Never rename the target of a UI link.
        path = self.config.root / value
        if any(part.is_symlink() for part in (path, *path.parents) if part != self.config.root):
            raise InvalidInput('Ordnerpfade mit symbolischen Links können nicht umbenannt werden.')
        source = self.config.safe_visible_path(value)
        if source == self.config.root:
            raise InvalidInput('Der Projektordner kann nicht umbenannt werden.')
        return source

    def reorder(self, value: str, position: int) -> dict[str, str]:
        """Reorder numbered siblings using reversible intermediate renames."""
        if type(position) is not int:
            raise InvalidInput('Bitte eine ganze Zahl als Position angeben.')
        # Preserve lexical paths until source_folder has checked for symlinks.
        # config.relative() resolves links and would hide them from that check.
        def relative(path: Path) -> str:
            return path.relative_to(self.config.root).as_posix()

        with (self.worksheets.lock if self.worksheets else nullcontext()), self.slides.build_lock, self.repository.lock:
            source = self.source_folder(value)
            if not source.is_dir():
                raise NotFound('Ordner nicht gefunden.')
            pattern = re.compile(r'^(\d+)_(.+)$')
            if not pattern.match(source.name):
                raise InvalidInput('Nur Ordner mit Nummer und Unterstrich können umsortiert werden.')
            siblings = sorted(
                [p for p in source.parent.iterdir() if p.is_dir() and pattern.match(p.name)],
                key=lambda p: (int(pattern.match(p.name)[1]), p.name),
            )
            if not 1 <= position <= len(siblings):
                raise InvalidInput(f'Die Position muss zwischen 1 und {len(siblings)} liegen.')
            for sibling in siblings:
                self.source_folder(relative(sibling))
            siblings.remove(source)
            siblings.insert(position - 1, source)
            width = max(len(pattern.match(p.name)[1]) for p in siblings)
            moves = [(p, p.with_name(f'{i:0{width}d}_{pattern.match(p.name)[2]}'))
                     for i, p in enumerate(siblings, 1)]
            moves = [(a, b) for a, b in moves if a != b]
            sources = {a for a, _ in moves}
            for _, target in moves:
                if (target.exists() or target.is_symlink()) and target not in sources:
                    raise FileExistsError(f'Pfad existiert bereits: {relative(target)}')
            completed = []
            try:
                staged = []
                for before, after in moves:
                    temporary = before.with_name(f'reorder-{uuid.uuid4().hex}')
                    self.rename(relative(before), temporary.name)
                    completed.append((before, temporary))
                    staged.append((temporary, after))
                for before, after in staged:
                    self.rename(relative(before), after.name)
                    completed.append((before, after))
            except BaseException:
                for before, after in reversed(completed):
                    self.rename(relative(after), before.name)
                raise
            return {relative(a): relative(b) for a, b in moves}

    def rename(self, value: str, name: str) -> Path:
        source = self.source_folder(value)
        name = name.strip()
        if not name or name != Path(name).name or name.startswith('.') or '/' in name or '\\' in name:
            raise InvalidInput('Bitte einen sichtbaren Ordnernamen ohne Pfad angeben.')
        target = source.with_name(name)
        build_root = self.config.root / OUTPUT_ROOT
        artifacts = build_root / OUTPUT_ARTIFACT_DIR
        old_artifacts = artifacts / source.relative_to(self.config.root)
        new_artifacts = artifacts / target.relative_to(self.config.root)
        # build/ itself can be browsed too; it must never be moved into itself.
        migrate = not source.is_relative_to(build_root)
        with (self.worksheets.renaming(source, target) if self.worksheets else nullcontext()), self.slides.build_lock, ExitStack() as locks:
            self.source_folder(value)
            if not source.is_dir():
                raise NotFound('Ordner nicht gefunden.')
            if target.exists() or target.is_symlink():
                raise FileExistsError(f'Pfad existiert bereits: {self.config.relative(target)}')
            if migrate:
                for path in (old_artifacts, new_artifacts):
                    if path.resolve() != path:
                        raise InvalidInput('Build-Pfade mit symbolischen Links können nicht verschoben werden.')
                if new_artifacts.exists():
                    raise FileExistsError('Am neuen Ordnerpfad liegen bereits Build-Artefakte.')
            artifact_tree = old_artifacts if migrate and old_artifacts.is_dir() else None
            decks = list(source.rglob('*.excalidraw'))
            if artifact_tree is not None:
                decks.extend(artifact_tree.rglob('*.excalidraw'))
            for deck in sorted(decks):
                destination = (target / deck.relative_to(source)) if deck.is_relative_to(source) else new_artifacts / deck.relative_to(old_artifacts)
                locks.enter_context(deck_lock(deck))
                locks.enter_context(deck_lock(destination))
            with self.repository.lock:
                self.source_folder(value)
                if not source.is_dir():
                    raise NotFound('Ordner nicht gefunden.')
                if target.exists() or target.is_symlink():
                    raise FileExistsError(f'Pfad existiert bereits: {self.config.relative(target)}')
                if migrate and (new_artifacts.exists() or new_artifacts.is_symlink()):
                    raise FileExistsError('Am neuen Ordnerpfad liegen bereits Build-Artefakte.')
                current = []
                if artifact_tree is not None:
                    for document in source.rglob('*'):
                        if document.suffix not in {'.qmd', '.md'} or not document.is_file():
                            continue
                        deck = self.slides.deck_path(document)
                        if deck.is_file() and self.slides.is_current(document):
                            stamp = self.slides.source_stamp(deck)
                            current.append((document.relative_to(source), stamp.relative_to(old_artifacts), stamp.read_bytes()))
                moved = []
                updated_stamps = []
                try:
                    with self.units.reference_updates(source, target):
                        source.rename(target)
                        moved.append((source, target))
                        if artifact_tree is not None:
                            new_artifacts.parent.mkdir(parents=True, exist_ok=True)
                            old_artifacts.rename(new_artifacts)
                            moved.append((old_artifacts, new_artifacts))
                        # Signatures include absolute resource paths. Refresh only
                        # decks that were current before the move, preserving edits
                        # and annotations instead of triggering a destructive rebuild.
                        for relative_source, relative_stamp, original in current:
                            signature = self.slides.signature(target / relative_source)
                            stamp = new_artifacts / relative_stamp
                            atomic_write_text(stamp, json.dumps({'signature': signature}))
                            updated_stamps.append((stamp, original))
                except BaseException:
                    try:
                        for stamp, original in reversed(updated_stamps):
                            atomic_write_bytes(stamp, original)
                    finally:
                        for before, after in reversed(moved):
                            after.rename(before)
                    raise
        return target
