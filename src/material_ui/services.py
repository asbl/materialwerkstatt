from __future__ import annotations

from material_ui.builds import BuildService
from material_ui.config import AppConfig
from material_ui.documents import DocumentService
from material_ui.gitinfo import GitService
from material_ui.folders import FolderService
from material_ui.index_extras import IndexExtras
from material_ui.rendering import RenderService
from material_ui.search import SearchService
from material_ui.slides import SlidesService
from material_ui.windows import WindowRegistry
from material_ui.worksheets import WorksheetStore
from material_ui.units import UnitService
from material_ui.file_operations import FileOperations
from material_ui.material_changes import MaterialChanges


class ApplicationServices:
    def __init__(self, runtime, config: AppConfig) -> None:
        self.windows = WindowRegistry()
        self.builds = BuildService(config.root, runtime.processes.run)
        # Plugin-Index-Provider (z. B. Kurse) hängen zusätzliche Einträge an /api/qmds an.
        self.index_extras = IndexExtras()
        self.changes = MaterialChanges()
        self.documents = DocumentService(config, runtime.documents, self.builds, self.index_extras, self.changes)
        self.units = UnitService(config, self.documents)
        self.changes.subscribe(self._material_changed)
        self.slides = SlidesService(config, repository=runtime.documents, runner=runtime.processes.run,
                                    jobs=runtime.jobs, submit=runtime.start_worker)
        self.worksheets = WorksheetStore(config)
        self.folders = FolderService(config, runtime.documents, self.slides, worksheets=self.worksheets, units=self.units)
        self.render = RenderService(config, runtime.documents, self.builds, runtime.jobs, runtime.start_worker,
                                    slides=self.slides)
        self.search = SearchService(config, self.documents)
        self.git = GitService(config, runtime.processes)

        self.files = FileOperations(config, runtime.documents, self.documents, self.units,
                                    self.worksheets, self.changes)

    def _material_changed(self, change):
        if change.kind == 'invalidated':
            self.units.invalidate_overview_cache()
            if not change.paths:
                self.index_extras.invalidate()
            return
        if change.kind == 'saved' and len(change.paths) == 1:
            self.documents.invalidate_qmd_cache(change.paths[0])
        else:
            self.documents.invalidate_qmd_cache()
