from __future__ import annotations

import json
import hashlib
import os
import tempfile
import threading
import time
from pathlib import Path
from contextlib import nullcontext

from excalideck.generator import generate_deck
from excalideck.processes import process_scope
from excalideck.outline import ImageBlock, ModelBlock, parse_outline
from material_core.designs import template_slide_design, resolved_slide_design
from material_core.render_inputs import render_content
from material_core.builds import OUTPUT_ARTIFACT_DIR, OUTPUT_ROOT
from material_core.filesystem import atomic_copy_file, atomic_write_text
from material_ui.jobs import ResourceJobQueue

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}


def deck_lock(deck: Path):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(deck.resolve(), threading.RLock())


def annotations_path(deck: Path) -> Path:
    return deck.parent / '.material-annotations' / deck.name


def annotation_targets(element) -> set:
    """Folienbezuege einer Anmerkung: frameId und customData.annotationSlide."""
    if not isinstance(element, dict):
        return set()
    targets = set()
    if isinstance(element.get('frameId'), str):
        targets.add(element['frameId'])
    custom = element.get('customData')
    if isinstance(custom, dict) and isinstance(custom.get('annotationSlide'), str):
        targets.add(custom['annotationSlide'])
    return targets


def _reading_frames(scene) -> list:
    if not isinstance(scene, dict):
        return []
    elements = scene.get('elements')
    frames = [element for element in (elements or []) if isinstance(element, dict)
              and element.get('type') == 'frame' and not element.get('isDeleted')
              and isinstance(element.get('id'), str)]
    return sorted(frames, key=lambda element: (element.get('y') or 0, element.get('x') or 0))


def frame_mapping(old_scene, new_scene) -> dict:
    """Frame-IDs der alten auf die neue Deck-Fassung abbilden.

    Der Folienbau vergibt bei jedem Durchlauf neue Element-IDs; Anmerkungen
    haengen an Folien, nicht an IDs. Frames gelten als gleiche Folie, wenn
    Rechteck und Titel uebereinstimmen: Umbenannte, verschobene, entfernte
    oder neu eingefuegte Folien bleiben bewusst ohne Abbildung, damit nie
    still eine Anmerkung auf die falsche Folie wandert.
    """
    def rect_key(frame):
        return (round(frame.get('x') or 0, 1), round(frame.get('y') or 0, 1),
                round(frame.get('width') or 0, 1), round(frame.get('height') or 0, 1))

    mapping = {}
    old_by_rect = {rect_key(frame): frame for frame in _reading_frames(old_scene)}
    for frame in _reading_frames(new_scene):
        old = old_by_rect.get(rect_key(frame))
        if old is not None and old.get('name') == frame.get('name'):
            mapping[old['id']] = frame['id']
    return mapping


def remap_annotation(element, mapping):
    """Eine Anmerkung auf neue Frame-IDs umschreiben; None, wenn unbildbar.

    Kehrt das Element unveraendert zurueck, wenn alle Bezuege schon zur
    neuen Fassung passen; None bedeutet, dass die Ziel-Folie im neuen
    Deck fehlt.
    """
    if not isinstance(element, dict):
        return element
    targets = annotation_targets(element)
    if not targets <= set(mapping):
        return None
    frame_id = element.get('frameId')
    custom = element.get('customData')
    slide = custom.get('annotationSlide') if isinstance(custom, dict) else None
    if (not isinstance(frame_id, str) or mapping.get(frame_id) == frame_id) \
            and (not isinstance(slide, str) or mapping.get(slide) == slide):
        return element
    updated = {**element}
    if isinstance(frame_id, str):
        updated['frameId'] = mapping[frame_id]
    if isinstance(custom, dict) and isinstance(slide, str):
        updated['customData'] = {**custom, 'annotationSlide': mapping[slide]}
    return updated


def mapped_annotations(elements, mapping):
    """Alle Anmerkungen umschreiben; None, wenn eine nicht abgebildet werden kann."""
    if not isinstance(elements, list):
        return None
    result = []
    for element in elements:
        mapped = remap_annotation(element, mapping)
        if mapped is None:
            return None
        result.append(mapped)
    return result


class SlidesService:
    """PDF-Template und Quelle bestimmen das Deck im zentralen Build-Ordner."""

    def __init__(self, config, *, repository=None, runner=None, jobs=None, submit=None):
        self.config = config
        self.repository = repository
        self.runner = runner
        self.build_lock = threading.RLock()
        self.closed = threading.Event()
        self.queue = ResourceJobQueue(jobs, submit) if jobs is not None else None

    def start(self, source: Path, *, force=False) -> str:
        from material_ui.document_types import ensure_renderable
        ensure_renderable(source)
        if self.queue is None:
            raise RuntimeError('Folien-Auftragsverwaltung fehlt.')
        if not template_slide_design(source.read_text(encoding='utf-8'))[0]:
            raise ValueError('Bitte zuerst ein Template mit Foliendesign wählen.')

        def work():
            if force:
                deck, backup = self.rebuild(source)
                generated = True
            else:
                deck, generated = self.ensure(source)
                backup = None
            return {'ok': True, 'deck': self.config.relative(deck), 'generated': generated,
                    'backup': self.config.relative(backup), 'message': 'Präsentation bereit.'}

        return self.queue.start(self.config.relative(source), 'slides-rebuild' if force else 'slides-ensure', work)

    def close(self):
        self.closed.set()
        if self.queue is not None:
            self.queue.close()

    def deck_path(self, source: Path) -> Path:
        rel = source.relative_to(self.config.root)
        return self.config.root / OUTPUT_ROOT / OUTPUT_ARTIFACT_DIR / rel.parent / f'{source.stem}.excalidraw'

    def source_stamp(self, deck: Path) -> Path:
        return deck.parent / '.material-source' / f'{deck.name}.json'

    def signature(self, source: Path) -> str:
        text = source.read_text(encoding='utf-8')
        enabled, design = template_slide_design(text)
        if not enabled:
            raise ValueError('Bitte zuerst ein Template mit Foliendesign wählen.')
        design = resolved_slide_design(text, source, self.config.root)
        digest = hashlib.sha256((render_content(text, source) + json.dumps(design, sort_keys=True, ensure_ascii=False)).encode('utf-8'))
        dependencies = set()

        def visit(blocks):
            for block in blocks:
                if isinstance(block, ImageBlock):
                    dependencies.add((source.parent / block.path).resolve())
                elif isinstance(block, ModelBlock):
                    from excalideck.generator import MODEL_FILTER
                    dependencies.add(MODEL_FILTER.resolve())
                    sketches = MODEL_FILTER.with_name('algorithm_sketches.lua')
                    if sketches.is_file():
                        dependencies.add(sketches.resolve())
                visit(getattr(block, 'blocks', ()))
                for column in getattr(block, 'columns', ()):
                    visit(column.blocks)

        for slide in parse_outline(source).slides:
            visit(slide.blocks)
        for asset in sorted(dependencies):
            digest.update(str(asset).encode('utf-8'))
            with asset.open('rb') as handle:
                digest.update(hashlib.file_digest(handle, 'sha256').digest())
        return digest.hexdigest()

    def is_current(self, source: Path) -> bool:
        deck = self.deck_path(source)
        try:
            signature = self.signature(source)
            with deck_lock(deck):
                stamp = json.loads(self.source_stamp(deck).read_text(encoding='utf-8'))
                return deck.is_file() and isinstance(stamp, dict) and stamp.get('signature') == signature
        except (OSError, ValueError):
            return False

    def ensure(self, source: Path) -> tuple[Path, bool]:
        deck = self.deck_path(source)
        with self.build_lock:
            if self.is_current(source):
                return deck, False
            self.rebuild(source)
            return deck, True

    def rebuild(self, source: Path) -> tuple[Path, Path | None]:
        """Erst fertig generieren, dann Deck und Anmerkungen gemeinsam sichern.

        Alte Anmerkungen werden der Sicherung zugeordnet, nicht dem neuen Deck.
        Bei fehlgeschlagener Generierung bleibt die bisherige Fassung verfügbar.
        """
        deck = self.deck_path(source)
        with self.build_lock:
            if self.closed.is_set():
                raise RuntimeError('Folienverwaltung ist beendet.')
            source_text = source.read_text(encoding='utf-8')
            signature = self.signature(source)
            deck.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=deck.parent, prefix='.deck-render-') as directory:
                staged = Path(directory) / deck.name
                with process_scope(self.runner):
                    generate_deck(source, output_path=staged)
                if self.signature(source) != signature:
                    raise ValueError('Die Quelle wurde während des Folienbaus geändert. Bitte erneut rendern.')
                # Always take the deck lock before the repository lock. Waiting for
                # a presenter or copying its scene must not block other documents.
                with deck_lock(deck):
                    return self._publish(source, source_text, deck, staged, signature)

    def _publish(self, source, source_text, deck, staged, signature):
        backup = None
        sidecar = annotations_path(deck)
        # Der gemeinsame Lock wird auch beim Speichern in der Present-App benutzt.
        old_deck = deck.read_text(encoding='utf-8') if deck.is_file() else None
        if deck.is_file() or sidecar.is_file():
            backup = deck.with_name(f'{deck.name}.bak-{time.strftime("%Y%m%d-%H%M%S")}-{time.time_ns()}')
            if deck.is_file():
                atomic_copy_file(deck, backup)
            if sidecar.is_file():
                atomic_copy_file(sidecar, annotations_path(backup))
        old_stamp = self.source_stamp(deck).read_text() if self.source_stamp(deck).is_file() else None
        # Sources or embedded resources may have changed during a slow backup.
        # Hashing resources stays outside the global document lock as well.
        if self.signature(source) != signature:
            raise ValueError('Die Quelle wurde während des Folienbaus geändert. Bitte erneut rendern.')
        published = False
        try:
            with self.repository.lock if self.repository is not None else nullcontext():
                if self.closed.is_set():
                    raise RuntimeError('Folienverwaltung ist beendet.')
                if source.read_text(encoding='utf-8') != source_text:
                    raise ValueError('Die Quelle wurde während des Folienbaus geändert. Bitte erneut rendern.')
                os.replace(staged, deck)
                published = True
                atomic_write_text(self.source_stamp(deck), json.dumps({'signature': signature}))
            # Folien neu gebaut: Anmerkungen aus dem Unterricht gehoeren zur
            # Folienstruktur, nicht zu den Zufalls-IDs des Builds. Sie werden
            # auf die neue Fassung umgeschrieben (Reihenfolge und Folientitel
            # muessen passen); ohne Bezuege ueberleben sie unangetastet. Nur
            # nicht mehr abildbare Anmerkungen entfallen (Backup und
            # Versionshistorie bewahren weiterhin alles auf).
            self._reconcile_annotations(deck, sidecar, old_deck)
        except BaseException:
            # Keep the deck lock while restoring, but release the repository lock
            # before copying the (potentially large) saved scene and annotations.
            if published:
                if backup is not None and backup.is_file():
                    atomic_copy_file(backup, deck)
                else:
                    deck.unlink(missing_ok=True)
                if backup is not None and annotations_path(backup).is_file():
                    atomic_copy_file(annotations_path(backup), sidecar)
                if old_stamp is None:
                    self.source_stamp(deck).unlink(missing_ok=True)
                else:
                    atomic_write_text(self.source_stamp(deck), old_stamp)
            raise
        return deck, backup

    def _reconcile_annotations(self, deck: Path, sidecar: Path, old_deck: str | None) -> None:
        """Sidecar-Anmerkungen nach dem Folienbau auf die neue Fassung umschreiben."""
        try:
            if old_deck is None or not sidecar.is_file():
                return
            mapping = frame_mapping(json.loads(old_deck), json.loads(deck.read_text(encoding='utf-8')))
            payload = json.loads(sidecar.read_text(encoding='utf-8'))
            if not isinstance(payload, dict):
                sidecar.unlink(missing_ok=True)
                return
            elements = payload.get('elements')
            if not isinstance(elements, list):
                sidecar.unlink(missing_ok=True)
                return
            kept = [remap_annotation(element, mapping) for element in elements]
            rebuilt = []
            for original, mapped in zip(elements, kept):
                if mapped is None:
                    continue
                rebuilt.append(mapped if mapped is not original else original)
            if not rebuilt:
                sidecar.unlink(missing_ok=True)
                return
            if len(rebuilt) == len(elements) and all(a is b for a, b in zip(rebuilt, elements)):
                return
            payload['elements'] = rebuilt
            file_ids = {element.get('fileId') for element in rebuilt if isinstance(element, dict)}
            files = payload.get('files')
            if isinstance(files, dict):
                payload['files'] = {key: value for key, value in files.items() if key in file_ids}
            atomic_write_text(sidecar, json.dumps(payload, ensure_ascii=False))
        except (OSError, ValueError, TypeError):
            # Der Folienbau ist bereits erfolgt; Anmerkungen duerfen ihn nicht
            # anfechten. Ohne belastbare Zuordnung greift die alte Bereinigung.
            sidecar.unlink(missing_ok=True)
