"""Version 1 host ports. Builtins depend on these, never the full runtime."""


class PluginDocuments:
    def __init__(self, config, repository, documents):
        self._config, self._repository, self._documents = config, repository, documents
        self.lock = repository.lock

    def read(self, path):
        return self._repository.read(self._config.safe_visible_path(str(path)))

    def save(self, path, text, expected=None):
        path = self._config.safe_visible_path(str(path))
        result = self._repository.save(path, text, expected)
        self._documents.invalidate_qmd_cache(path)
        return result

    def all_entries(self):
        return self._documents.all_entries()

    def klasse_thema_for(self, path):
        return self._documents.klasse_thema_for(path)

    def invalidate_qmd_cache(self, path=None):
        self._documents.invalidate_qmd_cache(path)


class PluginProcesses:
    def __init__(self, processes):
        self.run = processes.run
        self.start = processes.start
        self.stop = processes.stop


class PluginBuilds:
    def __init__(self, builds):
        self.build_document = getattr(builds, "build_document", None)


class PluginRender:
    """Render-Port: startet einen Render-Lauf ueber die zentrale Render-Warteschlange des Kerns.

    Liefert die Auftrags-ID; der Stand laeuft ueber die ueblichen Job-Routen (/api/jobs/<id>).
    """

    def __init__(self, config, render):
        self._config, self._render = config, render

    @property
    def available(self) -> bool:
        return self._render is not None

    def start(self, path: str) -> str:
        if self._render is None:
            raise RuntimeError("Render-Dienst ist nicht verfügbar.")
        return self._render.start(self._config.safe_visible_path(str(path)))

    def job(self, identifier: str) -> dict:
        if self._render is None:
            raise RuntimeError("Render-Dienst ist nicht verfügbar.")
        return self._render.jobs.get(identifier)


class PluginWindows:
    """Fenster-Port: Zahl der lebenden App-Fenster (Herzschlag-Registry des Kerns).

    0 bedeutet „UI geschlossen“ – z. B. fuer Desktop-Erinnerungen des Kalender-Plugins.
    """

    def __init__(self, windows):
        self._windows = windows

    @property
    def available(self) -> bool:
        return self._windows is not None

    def live_count(self) -> int:
        if self._windows is None:
            return 0
        return self._windows.count()


class PluginSearch:
    """Such-Provider-Port: Plugins ergaenzen /api/search um eigene Trefferquellen.

    Entspricht dem Muster der Kalender-Quellen (@calendar): registrieren, idempotente
    Abmeldefunktion zurueck, Quellenliste als Snapshot, Fehler pro Quelle isoliert.
    """

    def __init__(self, search):
        self._search = search

    @property
    def available(self) -> bool:
        return self._search is not None

    def register(self, provider, source_id: str, name: str = ""):
        if self._search is None:
            raise RuntimeError("Such-Dienst ist nicht verfügbar.")
        return self._search.register_provider(provider, source_id=source_id, name=name or source_id)

    def sources(self) -> list[tuple[str, str]]:
        if self._search is None:
            return []
        return self._search.provider_sources()
