"""Application use cases for material file mutations and metadata repair."""
from pathlib import Path

from werkzeug.exceptions import NotFound

from material_ui.document_types import ensure_note_rename
from material_ui.errors import InvalidInput
from material_ui.material_changes import MaterialChange
from material_ui.metadata import ensure_solution_metadata, solution_filename


class FileOperations:
    def __init__(self, config, repository, documents, units, worksheets, changes):
        self.config = config
        self.repository = repository
        self.documents = documents
        self.units = units
        self.worksheets = worksheets
        self.changes = changes

    def visible_file(self, value):
        path = self.config.safe_visible_path(value)
        if not path.is_file():
            raise NotFound('Datei nicht gefunden.')
        return path

    def rename(self, value, name):
        source = self.visible_file(value)
        name = name.strip()
        if not name or name != Path(name).name or name.startswith('.') or '/' in name or '\\' in name:
            raise InvalidInput('Bitte einen sichtbaren Dateinamen ohne Pfad angeben.')
        return self._move(source, source.with_name(name), check_resources=False)

    def move(self, value, destination):
        source = self.visible_file(value)
        self.units.folder(self.config.relative(source.parent))
        folder = self.units.folder(destination)
        if source.suffix.lower() not in {'.qmd', '.md'}:
            raise InvalidInput('Nur Markdown- und QMD-Materialien können verschoben werden.')
        return self._move(source, folder / source.name, check_resources=True)

    def _move(self, source, target, *, check_resources):
        target = self.config.safe_visible_path(str(target))
        with self.worksheets.renaming(source, target), self.repository.lock:
            self.visible_file(str(source))
            if target.exists() or target.is_symlink():
                raise FileExistsError('Zieldatei existiert bereits.')
            ensure_note_rename(source, target)
            if check_resources:
                self.units.check_material_move(source)
            self.units.rename_material(source, target)
        self.changes.publish(MaterialChange('moved', (source, target)))
        return target

    def delete(self, value):
        with self.repository.lock:
            source = self.visible_file(value)
            source.unlink()
        self.changes.publish(MaterialChange('deleted', (source,)))

    def repair_solution_metadata(self):
        """Explicit, repeatable migration; listing/search never invoke this."""
        changed, warnings = [], []
        for source in self.documents.qmd_sources():
            if not solution_filename(source):
                continue
            try:
                with self.repository.lock:
                    snapshot = self.repository.read(source)
                    normalized = ensure_solution_metadata(source, snapshot['text'])
                    if normalized != snapshot['text']:
                        self.repository.save(source, normalized, snapshot['revision'])
                        changed.append(self.config.relative(source))
                        self.changes.publish(MaterialChange('saved', (source,)))
            except (OSError, ValueError) as error:
                warnings.append({'path': self.config.relative(source), 'message': str(error)})
        return {'changed': changed, 'warnings': warnings}
