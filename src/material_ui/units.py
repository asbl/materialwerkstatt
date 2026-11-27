"""Folder-owned teaching summaries and repeatable dated uses."""
from contextlib import contextmanager
from datetime import date
from io import StringIO
from pathlib import Path
import re
import os
import threading

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from material_ui.errors import InvalidInput
from material_ui.caching import TTLCache
from material_ui.documents import DocumentService
from material_ui.assets import parse_tags, sanitize_stem
from material_ui.metadata import read_metadata, solution_filename
from material_ui.storage import revision, RevisionConflict
from material_core.filesystem import atomic_write_text

FILENAME = 'einheit.yaml'
UNIT_TYPES = ('unterrichtsstunde', 'klausur')
# Ordnernamen, die bei jedem Verzeichnisbaum-Scan unter unterricht/ keine Einheiten
# enthalten koennen (u.a. die vendored H5P-Bibliotheken unter .../ressourcen/libraries/,
# tausende Dateien), aber ohne diesen gemeinsamen Ausschluss in einzelnen os.walk-Aufrufen
# vergessen wurden und so jeden Request unnoetig verlangsamten.
# Wie materialIcon() im Frontend: Kind aus dem Frontmatter oder Dateiname `slide(s).qmd`.
PRESENTATION_KIND = re.compile(r'pr(?:ae|ä)sentation|folie|slide|^deck$', re.IGNORECASE)
PRESENTATION_STEM = re.compile(r'(?:^|[ _-])slides?$', re.IGNORECASE)
IGNORED_DIR_NAMES = {'build', 'node_modules', 'assets', 'images', 'libraries', 'kurse', 'h5p', 'ressourcen'}


def _normalize_thema(value):
    return re.sub(r'\s+', ' ', value.strip().lower())


class UnitService:
    def __init__(self, config, documents):
        self.config = config
        self.documents = documents
        self._overview_cache = TTLCache(config.qmd_cache_ttl)
        self._overview_stamp = None
        self._stamp_lock = threading.Lock()
        self._stamp_cache = {}

    def invalidate_overview_cache(self):
        self._overview_cache.invalidate()
        self._overview_stamp = None
        with self._stamp_lock:
            self._stamp_cache.clear()

    def _stamped(self, key, build):
        """Ergebnis pro (key, Manifest-Fingerprint, Katalog-Generation) cachen; externe
        Aenderungen an einheit.yaml oder am Ordnerbaum werden ohne TTL-Verzoegerung erkannt."""
        stamp = self._manifest_stamp()
        generation = None
        if self.documents is not None and hasattr(self.documents, 'catalog'):
            # qmd_sources() stoesst den Verzeichnis-Fingerprint-Check des Katalogs an.
            self.documents.qmd_sources()
            generation = self.documents.catalog.generation
        full_key = (key, stamp, generation)
        with self._stamp_lock:
            cached = self._stamp_cache.get(full_key)
            if cached is not None:
                return cached
        value = build()
        with self._stamp_lock:
            for stale in [k for k in self._stamp_cache if k[0] == key]:
                del self._stamp_cache[stale]
            self._stamp_cache[full_key] = value
        return value

    def _manifest_stamp(self):
        """Fingerprint aller einheit.yaml-Dateien (mtime/size), damit externe Aenderungen
        (git pull, externer Editor) ohne TTL-Verzoegerung erkannt werden."""
        entries = []
        base = self.config.root / 'unterricht'
        for directory, children, files in os.walk(base):
            children[:] = [p for p in children if not p.startswith('.') and p not in IGNORED_DIR_NAMES]
            if FILENAME in files:
                path = Path(directory) / FILENAME
                try:
                    info = path.stat()
                    entries.append((str(path), info.st_mtime_ns, info.st_size))
                except OSError:
                    entries.append((str(path), None, None))
        return tuple(sorted(entries))

    def folder(self, value):
        folder = self.config.safe_visible_path(value)
        relative = folder.relative_to(self.config.root)
        if not relative.parts or relative.parts[0] != 'unterricht' or not any(re.fullmatch(r'klasse-\d+', p) for p in relative.parts):
            raise InvalidInput('Eine Einheit muss in einem Klassenordner unter unterricht liegen.')
        if not folder.is_dir():
            raise InvalidInput('Einheitenordner fehlt.')
        self.config.safe_visible_path(str(relative / FILENAME))
        return folder

    def linked_material_path(self, folder, name):
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise InvalidInput('Bitte einen relativen Arbeitsblattpfad angeben.')
        path = self.config.safe_visible_path(str(folder / name))
        if (not path.is_relative_to(self.config.root / 'unterricht')
                or path.is_relative_to(folder) or path.suffix != '.qmd'
                or path.name.endswith('-old.qmd') or os.path.relpath(path, folder) != name):
            raise InvalidInput('Verknüpfte Arbeitsblätter müssen in einem anderen Unterrichtsordner liegen.')
        return path

    def validate(self, data, folder):
        if not isinstance(data, dict):
            raise InvalidInput('Die Einheit muss eine YAML-Zuordnung sein.')
        for key in ('titel', 'thema', 'kurzbeschreibung'):
            if not isinstance(data.get(key), str) or (key != 'kurzbeschreibung' and not data[key].strip()):
                raise InvalidInput(f'{key} fehlt oder ist kein Text.')
        if data.get('typ', 'unterrichtsstunde') not in UNIT_TYPES:
            raise InvalidInput('Unbekannter Einheitentyp.')
        if 'tags' in data:
            if not isinstance(data['tags'], list) or any(not isinstance(tag, str) or not tag.strip() for tag in data['tags']):
                raise InvalidInput('tags muss eine Liste nicht leerer Texte sein.')
            data['tags'] = list(dict.fromkeys(tag.strip() for tag in data['tags']))
        if 'datumsneutral' in data and type(data['datumsneutral']) is not bool:
            raise InvalidInput('datumsneutral muss wahr oder falsch sein.')
        if 'kompetenzen' in data:
            raw = data['kompetenzen']
            if not isinstance(raw, list):
                raise InvalidInput('kompetenzen muss eine Liste sein.')
            norm, seen = [], set()
            for item in raw:
                if isinstance(item, str):
                    kid, stufe = item.strip(), 'geübt'
                elif isinstance(item, dict) and isinstance(item.get('id'), str):
                    kid, stufe = item['id'].strip(), item.get('stufe', 'geübt')
                else:
                    raise InvalidInput('Jeder kompetenzen-Eintrag braucht eine id (Text oder {id, stufe}).')
                if not kid:
                    raise InvalidInput('kompetenzen-Eintrag ohne id.')
                if stufe not in ('eingeführt', 'geübt', 'geprüft'):
                    raise InvalidInput(f'Unbekannte Kompetenzstufe: {stufe!r}')
                if kid in seen:
                    continue
                seen.add(kid)
                norm.append({'id': kid, 'stufe': stufe})
            data['kompetenzen'] = norm
        if 'fertig' in data and type(data['fertig']) is not bool:
            raise InvalidInput('fertig muss wahr oder falsch sein.')
        if 'arbeitsblaetter_fertig' in data:
            states = data['arbeitsblaetter_fertig']
            if not isinstance(states, dict) or any(not isinstance(name, str) or type(done) is not bool for name, done in states.items()):
                raise InvalidInput('arbeitsblaetter_fertig muss Dateipfade auf wahr oder falsch abbilden.')
        if 'lernstand' in data:
            from material_core.lernstand import validate, LernstandError
            try:
                validate(data['lernstand'], folder, self.config.root)
            except LernstandError as error:
                raise InvalidInput(str(error)) from error
        linked = data.get('verlinkte_materialien', [])
        if not isinstance(linked, list):
            raise InvalidInput('verlinkte_materialien muss eine Liste von Arbeitsblattpfaden sein.')
        for name in linked:
            self.linked_material_path(folder, name)
        if 'verlinkte_materialien' in data:
            data['verlinkte_materialien'] = list(dict.fromkeys(linked))
        uses = data.get('einsatz', [])
        if not isinstance(uses, list):
            raise InvalidInput('einsatz muss eine Liste sein.')
        for use in uses:
            if not isinstance(use, dict):
                raise InvalidInput('Jeder Einsatz braucht ein Datum.')
            try:
                value = str(use['datum'])
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                    raise ValueError()
                date.fromisoformat(value)
            except (KeyError, ValueError):
                raise InvalidInput('Datum bitte als JJJJ-MM-TT angeben.') from None
            use['datum'] = value
            for key in ('lerngruppe', 'notiz', 'material'):
                if key in use and not isinstance(use[key], str):
                    raise InvalidInput(f'{key} muss Text sein.')
            if use.get('material') and use['material'] not in linked:
                target = self.config.safe_visible_path(str(folder.relative_to(self.config.root) / use['material']))
                if Path(use['material']).is_absolute() or not target.is_relative_to(folder):
                    raise InvalidInput('Material muss innerhalb der Einheit liegen.')
        return data

    def read(self, folder, sources=None):
        return self._read(folder, sources)[0]

    def _read(self, folder, sources=None):
        """Einheit plus Materialien mit Fertig-Schalter: {pfad: {kind, fertig}}."""
        path = folder / FILENAME
        parts = folder.relative_to(self.config.root).parts
        index = next(i for i, part in enumerate(parts) if re.fullmatch(r'klasse-\d+', part))
        text = path.read_text(encoding='utf-8') if path.exists() else ''
        default_title = re.sub(r'^\d+[ _-]+', '', folder.name).replace('_', ' ').replace('-', ' ')
        default_title = default_title[:1].upper() + default_title[1:]
        try:
            data = YAML(typ='safe').load(text) if text else {
                'titel': default_title,
                'thema': ' / '.join(parts[index + 1:-1]) or folder.name,
                'kurzbeschreibung': '', 'einsatz': [],
            }
            data = self.validate(data, folder)
        except YAMLError as error:
            raise InvalidInput(f'Ungültige {FILENAME}: {error}') from error
        materials = self.completion_materials(folder, sources)
        stored = data.get('fertig', False)
        states = data.get('arbeitsblaetter_fertig')
        for name, material in materials.items():
            if states is None:
                material['fertig'] = stored
            else:
                # Decks ohne eigenen Eintrag (Einheiten von vor dem Deck-Schalter) erben den
                # gespeicherten Einheitenstatus; ein neues AB oeffnet die Einheit dagegen wieder.
                material['fertig'] = states.get(name, stored if material['kind'] == 'presentation' else False)
        if materials and states is not None:
            data['fertig'] = all(material['fertig'] for material in materials.values())
        referenced = set(data.get('verlinkte_materialien', []))
        referenced.update(use['material'] for use in data.get('einsatz', []) if use.get('material'))
        unit = {'path': folder.relative_to(self.config.root).as_posix(),
                'klasse': parts[index], 'fach': parts[1], 'data': data,
                'revision': revision(text), 'gespeichert': path.exists(),
                'missingMaterials': sorted(name for name in referenced if not (folder / name).is_file())}
        return unit, materials

    def material_entry(self, folder, path):
        """Small navigation metadata; invalid frontmatter keeps a file reachable."""
        source_meta = getattr(self.documents, 'source_meta', None)
        if source_meta is not None:
            try:
                meta = source_meta(path)
            except OSError:
                # Datei zwischen Scan und Zugriff verschwunden: still ueberspringen.
                return None
        else:
            # Fallback ohne Metadaten-Cache (z. B. reduziertes DocumentService in Tests).
            try:
                catalog = getattr(self.documents, 'catalog', None)
                text = catalog.read_text(path) if catalog else path.read_text(encoding='utf-8')
                metadata = read_metadata(text)
            except OSError:
                return None
            except (ValueError, YAMLError, UnicodeError):
                metadata = {}
            kind = DocumentService.header_text(metadata, 'kind') or DocumentService.infer_kind(list(path.parts), path.name)
            meta = {
                'title': DocumentService.title_from_metadata(metadata) or path.stem.replace('_', ' ').replace('-', ' '),
                'kind': kind,
                'solution': solution_filename(path) or kind == 'Lösung' or 'Lösung' in parse_tags(metadata.get('tags')),
                'loesung': DocumentService.header_text(metadata, 'loesung'),
            }
        return {
            'path': os.path.relpath(path, folder),
            'title': meta['title'],
            'kind': meta['kind'],
            'solution': meta['solution'],
            'loesung': meta.get('loesung', ''),
        }

    def completion_materials(self, folder, sources=None):
        """Arbeitsblaetter und Praesentationen der Einheit; Loesungen zaehlen nicht mit."""
        if sources is None:
            candidates = []
            for path in self.documents.qmd_sources():
                if not path.is_relative_to(folder) or not path.is_file() or not self.config.is_visible(path):
                    continue
                if not self.config.safe_visible_path(str(path)).is_relative_to(folder):
                    continue
                candidates.append(path)
        else:
            # Bereits sichtbare/gepruefte Pfade (z. B. aus dem Uebersichts-Index).
            candidates = [path for path in sources if path.is_relative_to(folder)]
        result = {}
        for path in candidates:
            entry = self.material_entry(folder, path)
            if not entry or entry['solution']:
                continue
            if entry['kind'] == 'Arbeitsblatt' or path.stem == 'ab' or path.stem.startswith(('ab_', 'ab-')):
                result[entry['path']] = {'kind': 'worksheet'}
            elif PRESENTATION_KIND.search(entry['kind'] or '') or PRESENTATION_STEM.search(path.stem):
                result[entry['path']] = {'kind': 'presentation'}
        return result

    def scheduled_units(self):
        """Read dated summaries without indexing every material for calendar requests."""
        return self._stamped('scheduled', self._build_scheduled_units)

    def _build_scheduled_units(self):
        units = []
        # Eine Quellenliste teilen statt pro Einheit erneut alle QMDs/Notizen zu pruefen.
        sources = self.documents.qmd_sources() if self.documents is not None else None
        for directory, children, files in os.walk(self.config.root / 'unterricht'):
            children[:] = [name for name in children if not name.startswith('.')
                           and name not in IGNORED_DIR_NAMES
                           and not (Path(directory) / name).is_symlink()]
            if FILENAME not in files:
                continue
            try:
                unit = self.read(self.folder(Path(directory).relative_to(self.config.root).as_posix()), sources)
                if unit['data'].get('einsatz'):
                    units.append(unit)
            except (InvalidInput, OSError):
                continue
        return units

    def overview(self):
        """Gecachte Uebersicht; Invalidierung bei Einheiten-Saves, Index-Aenderungen
        und externen Aenderungen an einheit.yaml (Fingerprint-Vergleich pro Aufruf)."""
        stamp = self._manifest_stamp()
        if stamp != self._overview_stamp:
            self._overview_stamp = stamp
            self._overview_cache.invalidate()
        return self._overview_cache.get(self._build_overview)

    def _build_overview(self):
        sources = self.documents.qmd_sources()
        # Einmalig nach Ordnern gruppieren statt pro Einheit alle Quellen zu pruefen
        # (je Datei fielen is_file/resolve-Syscalls an).
        by_folder = {}
        folders = set()
        for path in sources:
            parts = path.relative_to(self.config.root).parts
            if parts[0] != 'unterricht' or not any(re.fullmatch(r'klasse-\d+', p) for p in parts):
                continue
            try:
                safe = self.config.safe_visible_path(str(path))
            except InvalidInput:
                continue
            folders.add(path.parent)
            for ancestor in (path.parent, *path.parent.parents):
                if not ancestor.is_relative_to(self.config.root):
                    break
                by_folder.setdefault(ancestor, []).append(safe)
        # Also include summaries in folders without their own QMD (e.g. a whole sequence).
        base = self.config.root / 'unterricht'
        for directory, children, files in os.walk(base):
            children[:] = [p for p in children if not p.startswith('.') and p not in IGNORED_DIR_NAMES]
            if FILENAME in files:
                folders.add(Path(directory))
        # Class folders contain planning metadata, but are not teaching units.
        folders = {folder for folder in folders if not re.fullmatch(r'klasse-\d+', folder.name)}
        # A diagnostic package is one unit even when its materials live in subfolders.
        from ruamel.yaml.error import YAMLError
        owners = set()
        for folder in folders:
            manifest = folder / FILENAME
            if manifest.is_file():
                try:
                    raw = YAML(typ='safe').load(manifest.read_text(encoding='utf-8'))
                    if isinstance(raw, dict) and 'lernstand' in raw:
                        owners.add(folder)
                except (YAMLError, OSError):
                    pass
        folders = {folder for folder in folders if not any(folder != owner and folder.is_relative_to(owner) for owner in owners)}
        units, errors = [], []
        for folder in sorted(folders):
            try:
                candidates = by_folder.get(folder, [])
                unit, tracked = self._read(self.folder(folder.relative_to(self.config.root).as_posix()), candidates)
                # A parent sequence includes child units too. Each child keeps its own summary.
                entries = [entry for entry in (self.material_entry(folder, path) for path in sorted(candidates)) if entry]
                for name in unit['data'].get('verlinkte_materialien', []):
                    path = self.linked_material_path(folder, name)
                    entry = self.material_entry(folder, path) if path.is_file() else None
                    entries.append({
                        **(entry or {'path': name, 'title': path.stem, 'kind': 'Arbeitsblatt', 'missing': True}),
                        'sourcePath': self.config.relative(path),
                    })
                unit['materials'] = [entry['path'] for entry in entries]
                unit['materialEntries'] = entries
                for entry in unit['materialEntries']:
                    material = tracked.get(entry['path'], {})
                    entry['worksheet'] = material.get('kind') == 'worksheet'
                    entry['presentation'] = material.get('kind') == 'presentation'
                    entry['fertig'] = material.get('fertig', unit['data'].get('fertig', False))
                if 'lernstand' in unit['data']:
                    from material_core.lernstand import audit
                    unit['lernstandStatus'] = audit(unit['data']['lernstand'], folder, self.config.root)
                units.append(unit)
            except (InvalidInput, OSError) as error:
                errors.append(f'{folder.relative_to(self.config.root)}: {error}')
        return {'units': units, 'errors': errors, 'project': str(self.config.root)}

    @contextmanager
    def reference_updates(self, source, target):
        """Update ancestor references after a file/folder move; restore on failure.

        The caller holds the repository lock and rolls back its filesystem move
        if metadata cannot be written. Internal references of a moved folder stay
        relative and require no rewriting.
        """
        changes = []
        base = self.config.root / 'unterricht'
        is_folder = source.is_dir()

        def moved_path(path):
            if path.is_relative_to(source):
                return target / path.relative_to(source) if is_folder else target
            return path

        if source.is_relative_to(base):
            candidates = {parent for parent in [source.parent, *source.parent.parents] if parent.is_relative_to(base)}
            # Linked worksheets and diagnostics can refer to other unit folders.
            from material_core.lernstand import manifests
            for manifest in manifests(self.config.root):
                if is_folder and manifest.parent.is_relative_to(source):
                    candidates.add(manifest.parent)
                if manifest.parent in candidates or manifest.is_symlink():
                    continue
                try:
                    raw = YAML(typ='safe').load(manifest.read_text(encoding='utf-8'))
                except (YAMLError, OSError):
                    continue
                if not isinstance(raw, dict):
                    continue
                references = raw.get('verlinkte_materialien')
                references = list(references) if isinstance(references, list) else []
                learning = raw.get('lernstand')
                if isinstance(learning, dict) and isinstance(learning.get('materialien'), list):
                    references.extend(item[key] for item in learning['materialien'] if isinstance(item, dict)
                                      for key in ('quelle', 'loesung') if key in item)
                if any(isinstance(name, str) and (manifest.parent / name).resolve().is_relative_to(source)
                       for name in references):
                    candidates.add(manifest.parent)
            for folder in sorted(candidates):
                path = folder / FILENAME
                if not path.is_file():
                    continue
                self.config.safe_visible_path(str(path))
                before = path.read_text(encoding='utf-8')
                try:
                    data = YAML(typ='safe').load(before)
                    self.validate(data, folder)
                except (YAMLError, InvalidInput) as error:
                    name = path.relative_to(self.config.root).as_posix()
                    raise InvalidInput(
                        f'Zusammenfassung {name} ist ungültig. Bitte zuerst korrigieren. {error}'
                    ) from error
                new_folder = target / folder.relative_to(source) if is_folder and folder.is_relative_to(source) else folder
                new_path = new_folder / FILENAME
                changed = False
                linked = data.get('verlinkte_materialien', [])
                if linked:
                    destinations = [moved_path((folder / name).resolve()) for name in linked]
                    if any(path.suffix != '.qmd' or path.name.endswith('-old.qmd') for path in destinations):
                        raise InvalidInput('Verknüpfte Arbeitsblätter müssen sichtbare QMD-Dateien bleiben.')
                    updated = list(dict.fromkeys(os.path.relpath(path, new_folder) for path in destinations
                                                 if not path.is_relative_to(new_folder)))
                    if updated != linked:
                        changed = True
                        if updated:
                            data['verlinkte_materialien'] = updated
                        else:
                            del data['verlinkte_materialien']
                if 'arbeitsblaetter_fertig' in data:
                    states = {}
                    for name, done in data['arbeitsblaetter_fertig'].items():
                        material = (folder / name).resolve()
                        destination = moved_path(material)
                        if destination.is_relative_to(new_folder):
                            states[destination.relative_to(new_folder).as_posix()] = done
                    if states != data['arbeitsblaetter_fertig']:
                        data['arbeitsblaetter_fertig'] = states
                        changed = True
                for use in data.get('einsatz', []):
                    if not use.get('material'):
                        continue
                    material = (folder / use['material']).resolve()
                    destination = moved_path(material)
                    if destination == material and new_folder == folder:
                        continue
                    updated = os.path.relpath(destination, new_folder)
                    if use['material'] in linked or destination.is_relative_to(new_folder):
                        if updated != use['material']:
                            use['material'] = updated
                            changed = True
                    else:
                        # Keep the unit's dates/notes when its local material leaves.
                        del use['material']
                        changed = True
                for item in data.get('lernstand', {}).get('materialien', []):
                    for key in ('quelle', 'loesung'):
                        if key not in item:
                            continue
                        material = (folder / item[key]).resolve()
                        destination = moved_path(material)
                        updated = os.path.relpath(destination, new_folder)
                        if updated != item[key]:
                            item[key] = updated
                            changed = True
                if changed:
                    stream = StringIO()
                    YAML().dump(data, stream)
                    changes.append((new_path, before, stream.getvalue()))
        written = []
        try:
            yield
            for path, before, after in changes:
                def check(path=path, before=before):
                    if path.read_text(encoding='utf-8') != before:
                        raise RevisionConflict(f'Die Zusammenfassung {path.relative_to(self.config.root)} wurde zwischenzeitlich geändert.')
                check()
                atomic_write_text(path, after, before_replace=check)
                written.append((path, before))
        except BaseException:
            for path, before in reversed(written):
                atomic_write_text(path, before)
            raise

    def check_material_move(self, source):
        """Refuse moves whose document-local resources would change meaning."""
        from urllib.parse import urlsplit
        text = source.read_text(encoding='utf-8')
        references = []
        patterns = (
            r'!?\[[^\]]*\]\(\s*(<[^>]+>|[^\s)]+)',
            r'(?m)^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)',
            r'\{\{<\s*include\s+([^>]+?)\s*>}}',
            r'\\(?:includegraphics|input|include)(?:\[[^\]]*\])?\{([^}]+)\}',
            r'(?:\b(?:image|read|csv|json|yaml|bibliography)\s*\(|#(?:include|import)\s+)[\s]*["\']([^"\']+)',
            r'\b(?:src|href)\s*=\s*["\']([^"\']+)',
        )
        for pattern in patterns:
            references.extend(re.findall(pattern, text))
        # Catch local files in named Typst arguments and less common metadata keys.
        for value in re.findall(r'["\']([^"\'\n]+)["\']', text):
            candidate = source.parent / value
            if not urlsplit(value).scheme and (candidate.is_file() or ('/' in value and candidate.is_dir())):
                references.append(value)
        def metadata_paths(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {'resources', 'bibliography', 'csl', 'css', 'include-in-header', 'include-before-body', 'include-after-body'}:
                        references.extend(item if isinstance(item, list) else [item])
                    elif key in {'template', 'template-partials', 'filters'}:
                        for path in item if isinstance(item, list) else [item]:
                            if isinstance(path, str) and (source.parent / path).exists():
                                references.append(path)
                    else:
                        metadata_paths(item)
        metadata_paths(read_metadata(text))
        for value in references:
            if not isinstance(value, str):
                continue
            value = value.strip().strip('<>"\'')
            if value and not value.startswith(('/', '#')) and not urlsplit(value).scheme:
                raise InvalidInput(
                    f'Dieses Material verwendet relative Ressourcen oder Links ({value}). '
                    'Verschieben wurde abgebrochen, damit diese Verweise gültig bleiben. '
                    'Bitte zuerst die Ressourcen und Verweise für den Zielordner anpassen.'
                )

    def rename_material(self, source, target):
        """Move a file and keep its references in sync, including rollback."""
        with self.documents.repository.lock:
            moved = False
            try:
                with self.reference_updates(source, target):
                    source.rename(target)
                    moved = True
            except BaseException:
                if moved:
                    target.rename(source)
                raise
        self.invalidate_overview_cache()

    def folder_candidates(self, grade='', path=None):
        if path is not None:
            return {'folders': [self.read(self.folder(path))], 'errors': []}
        return self._stamped(('folders', grade), lambda: self._build_folder_candidates(grade))

    def _build_folder_candidates(self, grade):
        folders, errors = [], []
        if grade and not re.fullmatch(r'klasse-\d{2}', grade):
            raise InvalidInput('Ungültige Klasse.')
        base = self.config.root / 'unterricht'
        # Eine Quellenliste teilen statt pro Ordner erneut alle QMDs/Notizen zu pruefen.
        sources = self.documents.qmd_sources() if self.documents is not None else None
        for directory, children, _files in os.walk(base):
            parent = Path(directory)
            children[:] = [name for name in children
                           if not name.startswith('.') and name not in IGNORED_DIR_NAMES
                           and not (parent / name).is_symlink()]
            parts = parent.relative_to(self.config.root).parts
            classes = [part for part in parts if re.fullmatch(r'klasse-\d+', part)]
            if not classes or (grade and classes[0] != grade):
                continue
            try:
                unit = self.read(self.folder(parent.relative_to(self.config.root).as_posix()), sources)
                folders.append(unit)
            except (InvalidInput, OSError) as error:
                errors.append(f'{parent.relative_to(self.config.root)}: {error}')
        return {'folders': sorted(folders, key=lambda item: item['path']), 'errors': errors}

    def attach(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get('path'), str):
            raise InvalidInput('Bitte einen vorhandenen Ordner auswählen.')
        if not isinstance(payload.get('datum'), str) or not payload['datum']:
            raise InvalidInput('Bitte ein Einsatzdatum angeben.')
        for key in ('titel', 'thema'):
            if not isinstance(payload.get(key), str) or not payload[key].strip():
                raise InvalidInput(f'{key} fehlt.')
        if 'lerngruppe' in payload and not isinstance(payload['lerngruppe'], str):
            raise InvalidInput('Lerngruppe muss Text sein.')
        with self.documents.repository.lock:
            folder = self.folder(payload['path'])
            current = self.read(folder)
            data = current['data']
            data.update(titel=payload['titel'].strip(), thema=payload['thema'].strip())
            use = {'datum': payload['datum']}
            group = payload.get('lerngruppe', '').strip()
            if group:
                use['lerngruppe'] = group
            uses = data.setdefault('einsatz', [])
            if not any(item['datum'] == use['datum'] and item.get('lerngruppe', '') == group and not item.get('material') for item in uses):
                uses.append(use)
            return self.save(payload['path'], data, payload.get('revision'))

    def append_dates(self, payload):
        """Edit selected existing dates and append new ones in one revision check."""
        if not isinstance(payload, dict) or not isinstance(payload.get('path'), str):
            raise InvalidInput('Lerneinheit fehlt.')
        dates = payload.get('dates', [])
        updates = payload.get('updates', [])
        removals = payload.get('remove', [])
        if (not isinstance(dates, list) or not isinstance(updates, list) or not isinstance(removals, list)
                or not 1 <= len(dates) + len(updates) + len(removals) <= 100):
            raise InvalidInput('Bitte mindestens ein Datum angeben (höchstens 100).')
        if any(not isinstance(value, str) or not value for value in dates):
            raise InvalidInput('Bitte gültige Datumsangaben angeben.')
        if not isinstance(payload.get('lerngruppe', ''), str):
            raise InvalidInput('Lerngruppe muss Text sein.')
        if not isinstance(payload.get('material', ''), str):
            raise InvalidInput('Material muss Text sein.')
        group = payload.get('lerngruppe', '').strip()
        material = payload.get('material', '').strip()
        for removal in removals:
            if (not isinstance(removal, dict) or not isinstance(removal.get('datum'), str) or not removal['datum']
                    or any(not isinstance(removal.get(key, ''), str) for key in ('lerngruppe', 'material'))):
                raise InvalidInput('Ungültiger Einsatz zum Entfernen.')
        with self.documents.repository.lock:
            folder = self.folder(payload['path'])
            current = self.read(folder)
            if not isinstance(payload.get('revision'), str):
                raise InvalidInput('Revision fehlt. Bitte die Einheit neu laden.')
            if current['revision'] != payload['revision']:
                raise RevisionConflict('Die Einheit wurde geändert. Bitte neu laden.')
            data = current['data']
            uses = data.setdefault('einsatz', [])
            indices = set()
            for update in updates:
                if not isinstance(update, dict) or type(update.get('index')) is not int or not 0 <= update['index'] < len(uses) or update['index'] in indices:
                    raise InvalidInput('Ungültiger bestehender Einsatz.')
                if not isinstance(update.get('datum'), str) or not update['datum']:
                    raise InvalidInput('Bitte ein Datum für den bestehenden Einsatz angeben.')
                indices.add(update['index'])
                uses[update['index']]['datum'] = update['datum']
            # Ein verschobener Einsatz darf keinen gleichen Einsatz (Datum, Lerngruppe, Material) doppeln.
            keys = [(use['datum'], use.get('lerngruppe', ''), use.get('material', '')) for use in uses]
            for index in indices:
                if keys.count(keys[index]) > 1:
                    raise InvalidInput('Die Einheit ist an diesem Tag bereits eingetragen.')
            # Entfernen (z. B. Rückgängig nach dem Zuweisen) ist idempotent: Fehlt der Einsatz
            # bereits, bleibt die Liste unverändert.
            for removal in removals:
                for position, use in enumerate(uses):
                    if (use['datum'] == removal['datum'] and use.get('lerngruppe', '') == removal.get('lerngruppe', '').strip()
                            and use.get('material', '') == removal.get('material', '').strip()):
                        del uses[position]
                        break
            for value in dates:
                if not any(use['datum'] == value and use.get('lerngruppe', '') == group
                           and use.get('material', '') == material for use in uses):
                    uses.append({'datum': value, **({'lerngruppe': group} if group else {}),
                                 **({'material': material} if material else {})})
            return self.save(payload['path'], data, payload['revision'])

    def link_material(self, payload, *, remove=False):
        if not isinstance(payload, dict) or any(
            not isinstance(payload.get(key), str) or not payload[key].strip()
            for key in ('path', 'material', 'revision')
        ):
            raise InvalidInput('Einheit, Arbeitsblatt und Revision müssen angegeben werden.')
        with self.documents.repository.lock:
            folder = self.folder(payload['path'])
            path = self.config.safe_visible_path(payload['material'])
            if (not path.is_relative_to(self.config.root / 'unterricht')
                    or path.suffix != '.qmd' or path.name.endswith('-old.qmd')):
                raise InvalidInput('Bitte ein Arbeitsblatt aus dem Unterrichtsordner auswählen.')
            name = os.path.relpath(path, folder)
            current = self.read(folder)
            if current['revision'] != payload['revision']:
                raise RevisionConflict('Die Einheit wurde geändert. Bitte neu laden.')
            linked = current['data'].get('verlinkte_materialien', [])
            if remove:
                if name not in linked:
                    return current
                if any(use.get('material') == name for use in current['data'].get('einsatz', [])):
                    raise InvalidInput('Bitte zuerst die Einsätze dieses Arbeitsblatts in der Einheit entfernen.')
                linked = [item for item in linked if item != name]
            else:
                entry = self.material_entry(folder, path) if path.is_file() else None
                if (not entry or entry['solution']
                        or not (re.search(r'arbeitsblatt|aufgabenblatt|^mini[ _-]?ab$', entry['kind'], re.I)
                                or re.match(r'^ab(?:$|[_-])', path.stem, re.I))):
                    raise InvalidInput('Bitte ein vorhandenes Arbeitsblatt auswählen.')
                if path.is_relative_to(folder) or name in linked:
                    return current
                self.linked_material_path(folder, name)
                linked = [*linked, name]
            data = current['data']
            if linked:
                data['verlinkte_materialien'] = linked
            else:
                data.pop('verlinkte_materialien', None)
            return self.save(payload['path'], data, current['revision'])

    def delete_theme(self, payload):
        """Thema der Fach/Klasse-Teilmenge loeschen.

        Das thema-Feld jeder betroffenen Zusammenfassung wird auf das Ersatzthema
        gesetzt; Ordner und Materialdateien bleiben unveraendert und andere
        Klassen oder Faecher unberuehrt. Zusaetzlich zu einem neuen Namen ist
        auch ein bereits vorhandenes Thema als Ziel moeglich. Ordner ohne eigene
        einheit.yaml leiten ihr Thema aus dem Pfad ab und blockieren die
        Loeschung mit einer behebbaren Meldung statt stillschweigend uebrig zu
        bleiben.
        """
        if not isinstance(payload, dict):
            raise InvalidInput('Angaben zum Thema fehlen.')
        for key in ('fach', 'klasse', 'thema', 'ersatz'):
            if not isinstance(payload.get(key), str) or not payload[key].strip():
                raise InvalidInput(f'{key} fehlt.')
        grade = re.fullmatch(r'(?:klasse-)?(\d{1,2})', payload['klasse'].strip())
        if not grade or not 1 <= int(grade[1]) <= 13:
            raise InvalidInput('Klasse bitte als Zahl von 1 bis 13 angeben.')
        thema, ersatz = payload['thema'].strip(), payload['ersatz'].strip()
        if _normalize_thema(thema) == _normalize_thema(ersatz):
            raise InvalidInput('Das Ersatzthema muss sich vom zu löschenden Thema unterscheiden.')
        base = self.config.root / 'unterricht' / sanitize_stem(payload['fach']) / f'klasse-{int(grade[1]):02d}'
        if not base.is_dir():
            raise InvalidInput('Der Klassenordner fehlt. Bitte Fach und Klasse prüfen.')
        manifests, blockers = self._theme_status(base)
        if blockers:
            raise InvalidInput(
                'Diese Ordner leiten ihr Thema aus dem Pfad ab (keine eigene '
                + FILENAME + '): ' + ', '.join(path for path, _ in blockers)
                + '. Bitte sie zuerst als Lerneinheit einbinden oder umbenennen.')
        changes = []
        for folder in sorted(manifests):
            before, data = manifests[folder]
            if not isinstance(data, dict) or _normalize_thema(str(data.get('thema') or '')) != _normalize_thema(thema):
                continue
            try:
                unit_folder = self.folder(folder.relative_to(self.config.root).as_posix())
                data = self.validate(data, unit_folder)
            except (InvalidInput, OSError) as error:
                raise InvalidInput(f'{folder.relative_to(self.config.root)}: {error}') from error
            data['thema'] = ersatz
            stream = StringIO()
            YAML().dump(data, stream)
            changes.append((unit_folder, stream.getvalue()))
        if not changes:
            raise InvalidInput('Keine Einheiten mit diesem Thema gefunden.')
        with self.documents.repository.lock:
            written = []
            try:
                for folder, after in changes:
                    path = folder / FILENAME
                    before = path.read_text(encoding='utf-8')
                    def check(path=path, before=before):
                        if path.read_text(encoding='utf-8') != before:
                            raise RevisionConflict(
                                f'Die Zusammenfassung {path.relative_to(self.config.root)} wurde zwischenzeitlich geändert.')
                    atomic_write_text(path, after, before_replace=check)
                    written.append((path, before))
            except BaseException:
                for path, previous in reversed(written):
                    atomic_write_text(path, previous)
                raise
        self.invalidate_overview_cache()
        return {'removed': thema, 'ersatz': ersatz,
                'updated': [folder.relative_to(self.config.root).as_posix() for folder, _ in changes]}

    def _theme_status(self, base):
        """Zusammenfassungen unterhalb des Klassenordners sowie Ordner sammeln,
        die ihr Thema aus dem Pfad ableiten (Material ohne eigene Datei)."""
        sources = self.documents.qmd_sources() if self.documents is not None else []
        qmd_folders = {source.parent for source in sources
                        if source.parent.is_relative_to(base) and source.parent != base}
        manifests, owners = {}, set()
        for directory, children, files in os.walk(base):
            children[:] = [name for name in children
                           if not name.startswith('.') and name not in IGNORED_DIR_NAMES
                           and not (Path(directory) / name).is_symlink()]
            folder = Path(directory)
            if folder == base or FILENAME not in files:
                continue
            path = folder / FILENAME
            try:
                before = path.read_text(encoding='utf-8')
                data = YAML(typ='safe').load(before)
            except (OSError, YAMLError) as error:
                raise InvalidInput(
                    f'Zusammenfassung {path.relative_to(self.config.root)} ist unlesbar: {error}') from error
            manifests[folder] = (before, data)
            if isinstance(data, dict) and 'lernstand' in data:
                owners.add(folder)
        blockers = []
        for folder in sorted(qmd_folders):
            if folder in manifests or any(folder != owner and folder.is_relative_to(owner) for owner in owners):
                continue
            parts = folder.relative_to(self.config.root).parts
            index = next((i for i, part in enumerate(parts) if re.fullmatch(r'klasse-\d+', part)), None)
            if index is None:
                continue
            derived = ' / '.join(parts[index + 1:-1]) or folder.name
            blockers.append((folder, derived))
        return manifests, [(folder.relative_to(self.config.root).as_posix(), derived)
                            for folder, derived in blockers]

    def _sibling_themes(self, klasse_folder):
        """Nur die Thema-Werte innerhalb einer Fach/Klasse-Teilmenge lesen,
        ohne qmd_sources() oder den vollen Verzeichnisbaum zu scannen."""
        if not klasse_folder.is_dir():
            return []
        found = []
        for yaml_path in klasse_folder.rglob(FILENAME):
            if any(parent.is_symlink() for parent in (yaml_path, *yaml_path.parents) if parent != self.config.root):
                continue
            try:
                data = YAML(typ='safe').load(yaml_path.read_text(encoding='utf-8'))
            except (YAMLError, OSError):
                continue
            thema = data.get('thema') if isinstance(data, dict) else None
            if isinstance(thema, str) and thema:
                found.append((yaml_path.as_posix(), thema))
        found.sort(key=lambda item: item[0])
        return [thema for _, thema in found]

    def create(self, payload):
        if not isinstance(payload, dict):
            raise InvalidInput('Angaben zur Lerneinheit fehlen.')
        for key in ('fach', 'klasse', 'titel', 'thema'):
            if not isinstance(payload.get(key), str) or not payload[key].strip():
                raise InvalidInput(f'{key} fehlt.')
        grade = re.fullmatch(r'(?:klasse-)?(\d{1,2})', payload['klasse'].strip())
        if not grade or not 1 <= int(grade[1]) <= 13:
            raise InvalidInput('Klasse bitte als Zahl von 1 bis 13 angeben.')
        topics = [part.strip() for part in payload['thema'].split('/')]
        if any(not part or part.startswith('.') for part in [payload['fach'], payload['titel'], *topics]):
            raise InvalidInput('Bitte sichtbare Namen für Fach, Thema und Titel angeben.')
        relative = Path('unterricht') / sanitize_stem(payload['fach']) / f'klasse-{int(grade[1]):02d}'
        for part in topics:
            relative /= sanitize_stem(part)
        relative /= sanitize_stem(payload['titel'])
        lexical = self.config.root / relative
        if any(parent.is_symlink() for parent in (lexical, *lexical.parents) if parent != self.config.root):
            raise InvalidInput('Lerneinheiten können nicht in verlinkten Ordnern angelegt werden.')
        folder = self.config.safe_visible_path(relative.as_posix())
        submitted_thema = ' / '.join(topics)
        normalized_submitted = _normalize_thema(submitted_thema)
        klasse_folder = self.config.root / 'unterricht' / sanitize_stem(payload['fach']) / f'klasse-{int(grade[1]):02d}'
        thema = next((existing for existing in self._sibling_themes(klasse_folder)
                      if _normalize_thema(existing) == normalized_submitted), submitted_thema)
        data = {'titel': payload['titel'].strip(), 'thema': thema,
                'typ': payload.get('typ', 'unterrichtsstunde'),
                'kurzbeschreibung': '', 'datumsneutral': payload.get('datumsneutral', False),
                'einsatz': [{'datum': payload['datum'], **({'lerngruppe': payload['lerngruppe']} if payload.get('lerngruppe') else {})}] if payload.get('datum') else []}
        self.validate(data, folder)
        stream = StringIO()
        YAML().dump(data, stream)
        with self.documents.repository.lock:
            folder.mkdir(parents=True, exist_ok=False)
            try:
                atomic_write_text(folder / FILENAME, stream.getvalue(), overwrite=False)
            except BaseException:
                try:
                    folder.rmdir()
                except OSError:
                    pass
                raise
        self.invalidate_overview_cache()
        # The folder was just created and contains no materials. Avoid scanning
        # the entire source index to determine its (empty) worksheet list.
        unit = self.read(folder, [])
        unit.update(materials=[], materialEntries=[])
        return unit

    def save(self, value, data, expected):
        folder = self.folder(value)
        self.validate(data, folder)
        if not isinstance(expected, str):
            raise InvalidInput('Revision fehlt. Bitte die Ansicht neu laden.')
        path = folder / FILENAME
        with self.documents.repository.lock:
            def check():
                text = path.read_text(encoding='utf-8') if path.exists() else ''
                if revision(text) != expected:
                    raise RevisionConflict('Die Einheit wurde geändert. Bitte neu laden.')
            check()
            previous, materials = self._read(folder)
            states = data.get('arbeitsblaetter_fertig', {})
            if data.get('fertig', False) != previous['data'].get('fertig', False):
                states = {name: data.get('fertig', False) for name in materials}
            if materials and (states or 'arbeitsblaetter_fertig' in data):
                # Ein nicht mitgeschicktes Deck behaelt seinen bisherigen (ggf. geerbten) Status.
                data['arbeitsblaetter_fertig'] = {
                    name: states.get(name, material['fertig'] if material['kind'] == 'presentation' else False)
                    for name, material in materials.items()}
                data['fertig'] = all(data['arbeitsblaetter_fertig'].values())
            stream = StringIO()
            YAML().dump(data, stream)
            atomic_write_text(path, stream.getvalue(), before_replace=check)
        self.invalidate_overview_cache()
        return self.read(folder)
