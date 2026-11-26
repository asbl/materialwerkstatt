# Material-UI: Ansichts-Registry, neue Ansichten und Plugin-Architektur

Plan vom 2026-11-04. Ziel: die Seitenleiste um **Kalender** (mit CalDAV-Sync),
**Agenda** und **Kurse** erweitern; eigene Features – zuerst die komplette
Kursfunktionalität – in ein **Pluginsystem** auslagern, damit die Material-UI mit
Grundfunktionen ausgeliefert und weitere Plugins (Schulportal-Sync, Sitzplan,
Klassenlisten, …) nachträglich installiert werden können.

Umsetzungsstand: **M1 (Ansichts-Registry), M2 (Plugin-Host), M3 (Kalender- und
Agenda-Plugin) und M4 (Kurs-Extraktion in das eingebaute Plugin `kurse`) sind
umgesetzt** – siehe die Abschnitte „Ansichten“, „Plugins“, „Kalender und Agenda“
und „Kurs-Plugin“ in `src/material_ui/README.md`. Die getrennte Paketform (M5) ist
inzwischen als Marketplace/Paketmanager umgesetzt (siehe Nichtziele-Hinweis unten).

Zusätzlich eingebaut: das Plugin **`wissen`** (read-only) zeigt das
Kompetenzraster (`wissen/kompetenzraster/<fach>/`) und die Kompetenz-Abdeckung
pro Klasse aus `einheit.yaml`/QMD-Frontmatter als Rail-Ansicht „Wissen“ – siehe
„Wissen-Plugin“ in `src/material_ui/README.md`.

Stand 2026-11-07 (Chat und Importe als Plugins): **Chat** (`plugins/chat/`,
`provides: ["chat"]`) und **Importe** (`plugins/importe/`,
`dependsOn: {"@chat": ">=0.1.0"}`) sind ebenfalls ausgelagert; der Kern kennt weder
Chat- noch Importlogik mehr. Plugin-übergreifende Dienste laufen über die
Host-Registry: `ctx.register_service(name, obj)` / `ctx.service(name)`
(Capability `plugin-services`) – so nutzt `importe` den `ChatService` für den
KI-Umbau. Der MCP-Subprozess des Chats liest Aufgabenbilder per HTTP über
`GET /api/document/import/task-image/<token>/image` (Route des `importe`-Plugins),
statt ein fremdes Plugin zu importieren; der MCP-Server startet als
`python -m chat.mcp_server` mit dem Plugin-Suchverzeichnis auf dem PYTHONPATH.
Frontend-seitig registrieren die Plugins ihre Controller beim Kern über
`deps.registerController(name, ctrl)`; Chat-Dock und Import-Modals bleiben als
HTML-Slots im Kern-Template, die zugehörigen Knöpfe werden ohne geladenes Plugin
ausgeblendet. Alle Routenpfade (`/api/chat/…`, `/api/document/import/…`) bleiben
unverändert stabil.

Stand 2026-11-06 (M4): Backend und Frontend der Kursfunktionalität liegen im Plugin
`src/material_ui/plugins/kurse/`. Der Kern kennt keine Kurslogik mehr:

- `IndexExtras` (`src/material_ui/index_extras.py`) hängt Plugin-Einträge an
  `/api/qmds` an; `ctx.index.register(provider, invalidator)` ist die Plugin-Fassade.
- Kurs-Routen bleiben unter `/api/kurse/…` stabil, registriert vom Plugin-Blueprint.
- H5P-Preview-Prewarm läuft über `ctx.lifecycle.on_start`.
- Frontend: `static/workspace-modes.js` (Modus-Registry mit `enter/leave/actions`,
  Chrome-Umschaltung über `setChrome`) und `static/path-resolvers.js`; das Plugin
  registriert Modus `kurs`, Pfad-Resolver für `unterricht/kurse/**` und die Ansicht
  „Kurse". `state.course.kursMode` bleibt als kompatibles Flag. `loadPlugins` wird
  in `init()` vor `loadQmds()` awaited, damit Modi/Resolver beim ersten Öffnen
  bereitstehen.
- `views.switchTo(id, { skipGuard: true })` überspringt den `onLeaveActive`-Wächter;
  der Plugin-Loader nutzt das beim initialen Nachziehen der gespeicherten
  Plugin-Ansicht, damit ein soeben automatisch geöffneter Kursmodus nicht durch
  `closeDocument()` verlassen wird. Benutzerklicks auf Rail-Knöpfe laufen
  unverändert durch den Wächter.
- Plugin-Manifest: optionales Feld `modules` deklariert zusätzliche JS-Dateien des
  jsEntry (z. B. `assets/courses.js`), die die Asset-Route ausliefert.
- Plugin-Manifest: optionales Feld `hostApis` nennt die Frontend-Schnittstellen des Kerns,
  die das JS-Modul als `ctx.deps` braucht (derzeit `chat`, `task-import`, `course-workspace`;
  die Fabriken stehen in `static/app.js` unter `hostApis`). Der Loader reicht nur Deklariertes
  durch; ein unbekannter Name lässt nur dieses Plugin scheitern. Eine Weiche über Plugin-IDs
  gibt es nicht mehr.
- Ansichten können `aliases` tragen (frühere View-IDs, z. B. `kalender` → `agenda`), damit
  gespeicherte Auswahl nach einer Umbenennung weiter greift; der Loader kennt keine
  konkreten Plugin-Ansichten mehr. Ohne gespeicherte Auswahl bleibt die Startansicht des Kerns.
- `ctx.service` ist ein Zugriffsobjekt: `ctx.service("chat")` liefert Interfaces anderer
  Plugins, `ctx.service = <eigener Dienst>` hinterlegt den eigenen Dienst (Attribute über
  `ctx.service.…`, roh über `ctx.own_service`); beides überdeckt sich nicht mehr.
- Mehrere `create_app`-Aufrufe auf derselben Runtime teilen sich den Plugin-Host
  (Singleton wie die Services), damit gepachte Plugin-Dienste in Tests greifen.

Neue Capabilities im API-Vertrag (additiv, apiVersion bleibt 3):
`plugin-index-providers`, `plugin-search-providers`, `workspace-modes`, `path-resolvers`,
`new-document-kinds`, `shortcut-kinds`.

## 1. Ziele und Nichtziele

Ziele:

- Die linke Rail (`nav.index-rail` in `templates/index.html`) zeigt neben Ordner-,
  Tag-Baum- und Tag-Label-Ansicht beliebig viele weitere Ansichten: Kalender, Agenda,
  Kurse und künftige Plugin-Ansichten.
- Ansichten sind registrierbar – zur Entwicklung im Kern genauso wie zur Laufzeit
  über Plugins.
- Die Kursfunktionalität (Ansicht, Editor-Modus, Audit, Moodle-Aktionen, Vorschau,
  H5P-Runtime) zieht vollständig in das Plugin `kurse`; der Kern behält nur schlanke,
  klar definierte Erweiterungspunkte.
- Kalender und Agenda liefert das Plugin `kalender` mit CalDAV-Sync; beide Ansichten
  lesen dieselben synchronisierten Daten.
- Plugin-Installation ohne Kernänderungen: eingebaut im Lieferumfang, als
  Python-Paket (Entry-Point) oder als Ordner im Benutzerverzeichnis.

Nichtziele (bewusst nicht Teil dieses Plans):

- Schreibender Kalender-Sync (Termine aus der UI heraus anlegen oder ändern).
- Signaturen oder das Nachladen von Plugin-Code aus dem Netz zur Laufzeit. Plugins
  sind lokal installierte, vertrauenswürdige Software wie das CLI selbst; das
  Manifest dokumentiert trotzdem Capability-Kennzeichnungen. **Stand 2026-11:
  M5 ist als Marketplace/Paketmanager umgesetzt** (git-Katalog, Abhängigkeiten via
  `dependsOn`/`provides`, Lockfile, Einstellungen → Marketplace; siehe Abschnitt
  „Marketplace und Paketmanager“ in `src/material_ui/README.md`) — Plugin-Code wird
  weiterhin nur lokal installiert und ausgeführt, nie remote geladen.
- Umbau der Kurs-Logik selbst (`course_sync`, `inv kurse.*`). Die Remote-Moodle-Regel
  für KI-Agenten gilt unverändert.
- Allgemeine Ersetzbarkeit von Kernfunktionen (Editor, Rendering, Tabs) durch
  Plugins.

## 2. Ist-Analyse: wo heute überall eingegriffen wird

Bestehende Architektur (beschrieben in `src/material_ui/README.md`): ein
Flask-Prozess (`create_app()` in `app.py`), Dienste explizit verdrahtet in
`services.py`, Frontend ohne Build-Schritt aus Vanilla-ES-Modulen mit strenger
Dependency-Injection (`static/app.js`) und deklarierten State-/DOM-Sichten
(`static/state-view.js`, `static/app-state.js`).

Die Berührungspunkte im Einzelnen:

**Seitenleiste und Ansichten**

- `templates/index.html`: drei fest verdrahtete Rail-Buttons (`folderViewButton`,
  `tagTreeViewButton`, `tagLabelViewButton`); Ansichtsinhalte in `#folderNavigation`,
  Kursinfos in `#kursPane`, beides innerhalb `#indexContent`.
- `static/navigation.js`: `setNavigationView("folder" | "tagTree" | "tagLabel")`
  kennt die drei Ansichten fest eingebaut; beim Verlassen des Kursmodus fragt sie
  `confirmDiscardOrSave()` (ungespeicherte Kursaktivität bleibt geschützt).
- `static/workspace-layout.js`: Fokus-Modus, Index-Einklappen und Chat-Dock wirken
  auf die ganze Seitenleiste – unabhängig von der aktiven Ansicht, bleibt unverändert.
- Icons: `static/icons.svg` hat kein Kalender-Symbol; `uiIcon()` (in `modals.js`)
  zeigt fest auf `/static/icons.svg#<name>`.

**Kursfunktionalität (Extraktionsinventar)**

| Heute | Ort | Bemerkung |
| --- | --- | --- |
| Kurs-Routen `/api/kurse/*` | `course_routes.py` | Endpunkte inkl. Audit, Moodle, Vorschau |
| Kursservice | `course_service.py` | nutzt `JobRegistry` und exklusive Kanäle |
| Adapter auf `course_sync` | `courses.py` | `CourseAdapter` → `CourseApplication`, `create_new_course`, … |
| Vorschau und H5P-Runtime | `preview.py` | zusätzlich `preview.prewarm()` beim Serverstart in `run()` |
| Vermischung im Index | `documents.py` (`all_entries()`) | Kurs-Einträge hängen direkt an `DocumentService` |
| Services-Wiring | `services.py` | `DocumentService` bekommt `CourseService` übergeben |
| Kursmodus-UI | `static/courses.js` + Kurs-Blöcke in `index.html` | `setKursMode` schaltet rund ein Dutzend Kern-Elemente um (Toolbar, Editor-Shell, Vorschau, erweiterte Optionen) |
| Editor-Modus | `static/editor.js`, `document-session.js`, `render-panel.js` | Kursmodus-Zweige für Speichern (Strg+S), Entwürfe (`localStorage`-Schlüssel `…#kurs…`) und Renderstatus |
| Neue-Dokument-Typ | `newKursFields` in `index.html`, `static/new-document.js` | eigener Zweig im Anlage-Dialog („Kurs (H5P)“) |
| Index-Einträge | `static/picker.js` (`courseEntryForPath`) | Ordnerliste (`navigation.js`), Tabs und Wiederherstellung offener Tabs (`static/tabs.js`, `app.js`) |
| Desktop-Starter | `desktop.py`, `static/windows.js` | öffnet Kurs-MDX (`index.mdx`, `chapters/*.mdx`) als Kursansicht über `?path=` |
| Kurs-Shortcuts | `static/shortcuts.js` | eigener Baustein-Katalog im Kursmodus |
| Tests | `src/tests/test_material_ui*.py` | Kurs-Speichern/-Konflikte, H5P-Startup u. a.; ziehen mit bzw. laufen gegen das Plugin weiter |

**Vorhandene Infrastruktur, an der Plugins andocken (nutzen statt neu bauen)**

- Auftragswesen: `jobs.py` (Auftragsregister, exklusive Kanäle, begrenzte Historie,
  Sicherung in `.material-ui/jobs.json`) und `GET /api/jobs/stream` (SSE) mit
  Browser-Clients (`static/job-client.js`, `static/jobs-panel.js`).
- Prozesse und Worker: `processes.py` (begrenzte, protokollierte Prozesse),
  `runtime.py` (Hintergrund-Worker, geordneter Shutdown).
- Speichern: `storage.py` und `material_core/filesystem.py` (atomare Schreibvorgänge,
  Revisionen).
- HTTP-Grenzen: `http.py` (`configure_http`) prüft Host, Origin und Token global per
  `before_request` – gilt automatisch auch für Plugin-Blueprints. API-Fehlerform
  (`{"error": …}`) und `InvalidInput` (→ 400) stehen bereit.
- Vertrag: `static/api-contract.json` (`apiVersion` und `capabilities`) mit Prüfung bei
  Schreibzugriffen (`static/api.js`) – der versionierte Weg für Inkompatibilitäten
  existiert also bereits.
- Asset-Versionierung: `desktop.py` (`application_version()`) hasht die Quelldateien
  aller Pakete; statische Assets erhalten `?v=<fingerprint>`; die Importmap in
  `app.py` versioniert auch transitive ES-Module. Hierüber bindet sich später auch
  Plugin-Frontend ein, ohne den Browser-Cache veralten zu lassen.
- Lokaler Zustand: `.material-ui/` ist git-ignoriert (heute `jobs.json`,
  `tag-settings.json`) – der natürliche Ort für Plugin-Einstellungen, -Cache und
  -Fehlerprotokolle.
- Kalender: nicht vorhanden. `httpx` ist vorhanden; `caldav`/`icalendar` stehen nicht
  in `pyproject.toml` und kommen als optionale Extras des Kalender-Plugins hinzu.

## 3. Zielbild

### 3.1 Ansichts-Registry im Kern (Voraussetzung für alles)

Neues Modul `static/views.js` mit dem Controller `createViewRegistry(...)`:

```js
registerView({
  id: "kalender",        // eindeutig; Kern-Ids: folder, tagTree, tagLabel
  title: "Kalender",     // Rail-Tooltip und indexTitle
  icon: "calendar",      // Symbolname, gelöst über icons.svg …
  iconHref: "/plugins/kalender/assets/icons.svg#calendar", // … oder Plugin-Symbol
  order: 40,             // Kern: 10/20/30; Plugins ab 40
  async mount(section, viewApi),  // einmalig beim ersten Aktivieren einbauen
  onActivate(), onDeactivate(),    // bei jedem Ansichtswechsel
  onReload(),                      // nur Ansichten mit eigenem Aktualisieren;
                                   // steuert die Sichtbarkeit des reloadIndex-Knopfs
  async mayLeave(),                // false oder abgelehntes Promise hält den
                                   // Wechsel auf (Kursmodus: confirmDiscardOrSave)
})
```

- Der Rail wird aus der Registry gerendert (`static/app.js` ersetzt die drei festen
  Button-Bindings); `state.navigationView` bleibt der Bezeichner der aktiven Ansicht.
- Jede Ansicht erhält ihr eigenes `<section>`-Element unter `#indexContent`, das beim
  ersten Aktivieren gemountet und sonst nur versteckt wird. Die Ordnerliste lebt samt
  Aufklappzustand weiter, während Kalender oder Agenda aktiv sind.
- `switchTo(id)` fragt `mayLeave()` der aktiven Ansicht (ungespeicherte
  Kursaktivität bleibt geschützt), klinkt die alte Ansicht aus und die neue ein. Der
  zuletzt aktive Ansichtsname wird persistiert (`localStorage`, analog den
  bestehenden `material-ui:`-Schlüsseln).
- Die drei Kernansichten registrieren sich selbst über diese API. `navigation.js`
  schrumpft auf Ordner- und Tag-Logik; die Ansichts-Verzweigungen in
  `setNavigationView` fallen weg.
- Der Kursmodus betitelt heute die Rail-Buttons um („Kurs verlassen und … anzeigen“).
  Künftig entfällt das: Der Wächter für ungespeicherte Änderungen hängt am aktiven
  Workspace-Modus beziehungsweise der aktiven Ansicht (einheitliches `mayLeave()`),
  nicht an Titel-Umschreibungen der Rail-Buttons. Das Plugin bietet im Kurs-Werkraum
  einen eigenen Knopf „Kurs verlassen“ (siehe 3.3); Rail-Titel bleiben stabil.
- Abnahme bewusst eng gefasst: keine Verhaltensänderung; alle bestehenden
  Playwright- und pytest-Fälle bleiben grün.

### 3.2 Pluginsystem

**Form eines Plugins** – ein Ordner (oder installiertes Python-Paket) mit:

```
plugin.json         Pflicht: Manifest
__init__.py         optional: Python-API `register(ctx: PluginContext)`
assets/plugin.js    optional: Frontend `export function register(ctx)`
assets/*.css        optional
assets/icons.svg    optional: eigene Symbole für Rail und Ansichten
```

`plugin.json` (Beispiel Kalender):

```json
{
  "id": "kalender",
  "name": "Kalender und Agenda",
  "version": "0.1.0",
  "minAppApi": 3,
  "capabilities": ["network-outbound"],
  "pythonEntry": "register",
  "jsEntry": "assets/plugin.js",
  "styles": ["assets/kalender.css"],
  "icons": "assets/icons.svg"
}
```

- `capabilities` sind **reine Selbstauskunft** (der Host erzwingt sie nicht; `ctx.runtime`/`ctx.config`
  sind offen) für den Plugin-Dialog und Katalog für den Host:
  erlaubt sind `network-outbound`, `repo-read` (lesender Dokumentenindex) und
  `state-write` (eigener Speicher). Der Host schränkt aktiv ein: Die Python-Fassade
  bietet nur konkrete Dienste, nie freie Repository-Pfade.
- `minAppApi` bindet an `static/api-contract.json` (Bump auf Version 3 mit den neuen
  Fähigkeiten `plugins` und `plugin-views`). Plugin-Schreibzugriffe verhandeln
  dieselben Header wie der Kern – der Mechanismus existiert vollständig
  (`static/api.js`).

**Suchorte** (in dieser Reihenfolge; doppelte IDs werden übersprungen):

1. Eingebaut im Paket: `src/material_ui/plugins/<id>/` – mit dem Repository
   mitgeliefert, aktivier- und abschaltbar.
2. Installierte Python-Distributionen: Entry-Point-Gruppe `material_ui.plugins`
   (**noch nicht implementiert**, siehe 3.6).
3. Benutzerverzeichnis: `~/.local/share/material-ui/plugins/<id>/` (XDG-Pfade nutzt
   `desktop.py` bereits über `data_home()`). Symlinks sind für Entwicklungsinstallationen
   erlaubt: Der Fingerprint folgt ihnen, der Marketplace ersetzt sie nie.
4. Projektlokal: `<repo>/plugins/<id>/` (Quelle „project“, **implementiert**): Der Ordner ist
   git-ignoriert und der Weg für **private Plugins**, die nicht öffentlich verteilt werden
   sollen (Beispiel: die Wissensbasis, deren Code im privaten Wissens-Repo unter
   `wissen/plugin/` liegt; `plugins/wissen` ist ein Symlink darauf). Projektlokale Plugins sind
   vorab aktiv, der Marketplace verwaltet sie nie (kein Aktualisieren, kein Entfernen) und
   lehnt Katalogpakete mit gleicher ID ab; der Server-Fingerprint bezieht sie ein. Ein gesetztes
   `MATERIAL_UI_PLUGIN_PATHS` (Tests) blendet auch diesen Ort aus.

**Backend-Host** (neu: `plugins/host.py`, `plugins/context.py`)

- `PluginHost` lädt beim Start Manifeste, validiert sie (ID-Muster `[a-z0-9-]+`,
  Versionen, Eindeutigkeit), überspringt deaktivierte IDs und ruft `register(ctx)`
  auf. Fehler eines Plugins führen zu einem Statuseintrag `error` mit Meldung –
  niemals zum Startabbruch des Kerns.
- `PluginContext` (Fassade, versioniert):

```python
ctx.register_routes(blueprint)               # Flask-Blueprint, url_prefix frei wählbar;
                                            # Kurse behalten ihre Pfade unter /api/kurse/…
ctx.storage   # <repo>/.material-ui/plugins/<id>/, atomar geschrieben
ctx.settings  # JSON-Einstellungen, Dateimodus 0600 (siehe CalDAV-Passwörter)
ctx.index.register(provider)                 # Kurs-Einträge in den Dokumentenindex einspeisen
ctx.index.invalidate()                       # Indexinvalidierung durch das Plugin
ctx.documents.register_path_resolver(fn)     # Klick/Starter auf unbekannten Pfad (Kurs-MDX)
ctx.jobs.channel("kalender-sync")            # eigener, exklusiver Auftragskanal
ctx.processes, ctx.start_worker(...)         # begrenzte Prozesse, shutdown-sichere Worker
ctx.lifecycle.on_start(fn), ctx.lifecycle.on_shutdown(fn)
ctx.render.start(path)                       # Render-Lauf ueber die Kern-Warteschlange -> Job-ID
ctx.search.register(provider, source_id=…)   # Such-Quelle fuer GET /api/search (s. Such-Schnittstellen)
ctx.windows.live_count()                     # lebende App-Fenster (0 = UI geschlossen)
```

- Guards: Host-, Origin- und Token-Prüfungen aus `http.py` greifen automatisch auch
  für Plugin-Routen; es gibt keine separaten Authentifizierungspfade. Plugin-Routen
  nutzen dasselbe Fehlerform (`InvalidInput` → 400). Auftrags- und SSE-Strecke wird
  unverändert weiterverwendet.
- Assets: Der Host veröffentlicht je Plugin eine Route `/plugins/<id>/…`, die nur die
  im Manifest benannten Dateien ausliefert (JS, CSS, Icons), versioniert mit dem
  Server-Fingerprint über dasselbe `?v=`-Verfahren wie `asset_url()`.
- Status-API fürs Frontend: `GET /api/plugins` liefert je Plugin `{id, name, version,
  status, capabilities, jsUrl, cssUrls, iconsHref}`.
- Aktivieren und Deaktivieren erfordern einen Neustart (Python-Module sind zu früh
  geladen): Stand in `.material-ui/plugins.json` (git-ignoriert), UI-Dialog
  „Plugins“ im Zahnrad-Menü sowie `inv plugin-list`, `inv plugin-enable <id>`,
  `inv plugin-disable <id>`. Der Neustartweg existiert bereits: `POST /api/server/restart`,
  ausgelöst in `static/app.js` über `restartServer()` mit anschließendem Neuladen.
- Fingerprint: `application_version()` bezieht die Plugin-Quellordner aus allen
  Suchorten ein – der Desktop-Starter startet bei Plugin-Änderungen selbst neu
  (bestehende Logik, kein neuer Mechanismus).

**Frontend-Lader** (neu: `static/plugins/loader.js`)

1. Nach dem Protokollabgleich lädt `app.js` `GET /api/plugins`.
2. Pro Plugin: erst `<link rel="stylesheet" href="…?v=…">`, dann
   `await import(jsUrl)`.
3. `register(ctx)` des Plugins erhält:

```js
ctx.views.register({...})               // Ansichts-Registry aus 3.1, iconHref erlaubt
ctx.api                                 // api.js-Client mit Token-/Version-Headern, freies URL-Präfix
ctx.ui.openModal/closeModal/setStatus/uiIcon  // bestehende Modalbausteine (modals.js, ui-utils.js)
ctx.state.plugins[id]                    // getrennter State-Bereich je Plugin;
                                        // state-view.js gibt keine Kern-Schlüssel weiter
ctx.events.jobs(subscriber)             // Auftrags-Strom (bestehender SSE-Client)
ctx.documents.isDirty()                 // aktueller Zustand ungespeicherter Änderungen
ctx.documents.registerPreviewResolver(path => null) // optional {url, path} für Markdown-Vorschauen
ctx.workspace.registerMode({...})        // siehe 3.3
ctx.newDocument.registerKind({...})      // siehe 3.3
```

Für eine eigene Markdown-Vorschau liefert ein Resolver `{url, path}` oder `null`.
Der Kern verwendet den ersten passenden Resolver und sendet den aktuellen,
auch ungespeicherten Editorinhalt als JSON `{path, text}` per POST an `url`.
Die Antwort enthält `{html}` und wird im isolierten Vorschaufenster angezeigt.
Ohne Resolver verwendet der Kern die allgemeine Markdown-Vorschau. Dokumente
mit Render-Fähigkeit behalten ihre PDF-Vorschau. Beispielsweise löst das
Blog-Plugin seine Bildpfade über seine eigene Vorschauroute auf.

4. Lade- und Laufzeitfehler eines Plugins sind im Plugin-Status sichtbar, ohne die
   restliche UI zu brechen.

Technische Randbedingung (bewusst so, kein Build-Schritt): Plugin-JS importiert
Kern-Module über die Importmap (`import { api } from "/static/api.js"`), nicht über
relative Pfade – so greifen die bestehende Importmap-Versionierung und der
Asset-Cache unverändert. Die neuen Kernmodule (`views.js`,
`plugins/loader.js`) stehen in derselben Importmap.

### 3.3 Extraktion der Kursfunktionalität (`plugins/kurse`)

Der Kursmodus ist ein Vollbild-Zustand: eigene Toolbar, eigener Editor-Modus, eigene
erweiterte Optionen, eigene Verwendung der Vorschau. Dafür ein Workspace-Modus-Haken
(`ctx.workspace`), den nur Plugins nutzen, die einen vollständigen Arbeitsmodus
brauchen:

```js
ctx.workspace.registerMode({
  id: "kurs",
  entryFor(path),     // index.mdx / chapters/*.mdx -> {slug, chapter, activity}
  enter(entry),       // eigene Toolbar/Pane/Flächen mounten, Kern-Editor aushängen
  leave(),            // aufräumen, Kern wiederherstellen
  ownsDocument(path),   // steuert Chat-Kontext, Tabs und ?path-Handling
})
```

Abbildung des Inventars auf die Haken (Zustand nach M2/M4):

| Kommt heute aus | Geht künftig über | Wo |
| --- | --- | --- |
| `DocumentService.all_entries()` = QMDs + `courses.entries()` | `ctx.index.register(provider)`: Kurs-Einträge bleiben Teil von `GET /api/qmds`, inkl. Caching und Tag-Vokabular | `documents.py`, `services.py`, `caching.py` |
| `course_routes.py`, `course_service.py`, `courses.py`, `preview.py` | als Pluginmodul verschoben; Blueprint behält die Endpunkte unter `/api/kurse/…` | `plugins/kurse/` |
| Anlage eines Kurses über `POST /api/kurse/new` inkl. Indexinvalidierung | Pluginroute; Invalidierung über `ctx.index.invalidate()` | `services.py` verliert die Kopplung, `plugins/kurse/routes.py` |
| `setKursMode`, `kursPane`, `courseToolbar`, `kursActions`, `moodleConfirmModal`, `courseActivityPane` | `ctx.workspace.registerMode(...)`; das Plugin rendert seine Oberfläche vollständig aus JS; `index.html` verliert die Kurs-Blöcke | `static/courses.js` → `plugins/kurse/assets/plugin.js` |
| Neue-Dokument-Typ „Kurs (H5P)“ mit eigenen Feldern | `ctx.newDocument.registerKind({kind, label, fields(node), create()})` | `static/new-document.js` ohne festen Kurszweig |
| `courseEntryForPath` (Picker, Ordnerliste, Tabs, `restoreTabs`) | `ctx.documents.register_path_resolver(fn)`: Der Kern fragt registrierte Resolver, bevor er einen Pfad als QMD öffnet | `static/picker.js`, `static/navigation.js`, `static/app.js`, `static/tabs.js` |
| Kursmodus-Zweige in `editor.js`, `document-session.js`, `render-panel.js`, `chat-panel.js` | bleiben im Kern, fragen aber den aktiven Workspace-Modus statt `state.course.kursMode` (Schnittstelle `ownedMode(path)`). Draft-`localStorage`-Schlüssel bleiben unverändert – keine Datenverluste | Editor- und Session-Module |
| `preview.prewarm()` beim Serverstart | `ctx.lifecycle.on_start(...)`, nur wenn das Plugin aktiviert ist | `app.py`, `plugins/kurse` |
| Desktop-Starter öffnet Kurs-MDX als Kursansicht | unverändert – der Starter reicht `?path=` weiter; die Auflösung übernimmt der registrierte Path-Resolver im Frontend | `desktop.py` unverändert |
| Kurs-Shortcuts | `ctx.shortcuts.kind("kurs")` – pluginspezifischer Baustein-Katalog im Kursmodus | `static/shortcuts.js` |
| Kurs-Tests | ziehen nach `src/tests/test_plugins_kurse.py` (u. a. Kurs-Speichern/-Konflikte, H5P-Startup) | `src/tests/` |

Was bewusst nicht passiert: Die Remote-Moodle-Grenzregel für KI-Agenten bleibt
unverändert in Kraft – das Plugin ruft weiterhin `course-sync`-Subprozesse mit
`COURSE_SYNC_TASK=1` beziehungsweise über `inv kurse.*` auf. An der Veröffentlichungs-
und Auditlogik von `course_sync` ändert der Plan nichts.

### 3.4 Kalender und Agenda (`plugins/kalender`) mit CalDAV

**Abhängigkeiten** als optionales Extra in `pyproject.toml`
(`pip install -e '.[kalender]'`):

```
caldav>=1.3,<2                 # CalDAV-Client (bringt icalendar, vobject, lxml mit)
recurring-ical-events>=3,<4     # Serientermine inkl. Ausnahmen und Zeitzonen
```

Der Host importiert die Bibliotheken nur, wenn das Plugin aktiviert ist. Fehlt das
Extra, zeigt der Plugin-Status eine klare Meldung mit Installationshinweis anstelle
eines nackten Importfehlers.

**Einstellungen** (`.material-ui/plugins/kalender/settings.json`, Dateimodus 0600,
git-ignoriert)

- Konten: Liste von `{label, url, username, password}` (App-Passwort für den
  CalDAV-Server der Schule oder einer Nextcloud), Zeitzone (Standard
  `Europe/Berlin`), Sync-Intervall (Standard 60 Minuten, abschaltbar), Abgleichfenster
  (Standard: 30 Tage zurück bis 120 Tage voraus), je Konto ausgewählte Kalender.
- Passwörter werden im UI maskiert und nie in Antworten ausgeliefert: `GET` liefert
  nur Platzhalter, `PUT` ersetzt ausschließlich übermittelte Felder.

**Sync (Backend)**

- `plugins/kalender/caldav_client.py`: je Konto `caldav.DAVClient` → `principal` →
  `calendars()` → Abfrage im Zeitfenster (`calendar.search(...)` beziehungsweise
  `date_search`, je nachdem was der Server unterstützt). Normalisierte Datensätze:
  `{uid, recurrenceId, account, calendar, title, start, end, allDay, location,
  description, url, categories, status}` – zeitzonenkonvertiert, Serientermine und
  Ausnahmen über `recurring-ical-events` expandiert.
- Ablage: JSON-Cache je Kalender unter
  `.material-ui/plugins/kalender/cache/<konto>-<kalender>.json` (wenige hundert
  Termine, atomar geschrieben über `storage.py`, lesbar und debug-freundlich –
  bewusst keine SQLite in v1; Wechsel bleibt später möglich).
- Ausführung: regulärer Auftrag im Kanal `kalender-sync` (Zusammenfassung laufender
  Anforderungen wie im Renderkanal), Status über den bestehenden SSE-Strom und
  `GET /api/plugins/kalender/status`; periodischer Lauf als registrierter
  Runtime-Worker (shutdown-sicher); Knopf „Jetzt synchronisieren“ in der Ansicht. Die
  Darstellung liest ausschließlich den Cache – ohne Konto oder Netz bleibt die
  Ansicht mit Hinweis nutzbar.
- Kein schreibender Sync in v1 (siehe Nichtziele): Termine anlegen und verschieben
  bleibt Aufgabe des Originalkalenders.

**Routen** (Blueprint `/api/plugins/kalender/…`): `GET events?from&to` (aus dem
Cache, Zusammenführung überlappender Cache-Fenster), `POST sync` (202 + Job),
`GET status`, `GET/PUT settings`.

**Ansichten** (beide über `ctx.views.register`, Icons aus `assets/icons.svg`,
neues Kalender-Symbol)

- „Kalender“ (Monatsraster): CSS-Grid 7×5–6, Kopfnavigation (Monat zurück und vor,
  „Heute“), Kalenderwoche im Kopf, ganztägige Termine als Block, Farbmarken je
  Kalender, Tageszellen kürzen mit „+n“, Zellklick öffnet die Tagesliste,
  Terminklick ein Detail-Modal (Ort als Link, Beschreibung, Quelle/URL).
- „Agenda“: einfache Liste mit Tag-Gruppen („Heute“, „Morgen“, Datum), Standard
  30 Tage ab heute (einstellbar), Sprung-zu-Datum, ganztägige Termine oben,
  Farbmarken je Kalender. Ohne konfiguriertes Konto bietet die Ansicht direkt den
  Einstellungsdialog an (Konto anlegen → Sync starten → Termine erscheinen ohne
  Neuladen); bei Verbindungsfehlern bleibt der letzte Cache lesbar, der Sync-Fehler
  wird angezeigt.

Erweiterungen, die sich später anbieten (nicht Teil von v1): Termine mit Materialien
verknüpfen (Tag-/Frontmatter-Bezug), ICS-Abos (einfache HTTP-URLs ohne CalDAV-
Server), Ferienkalender, Stundenplan-Ansicht als weiteres Plugin auf demselben Cache.

### 3.5 Ansicht „Kurse“

Die Ansicht gehört zum `kurse`-Plugin, nicht zum Kern: Sie listet die Kurse aus dem
Dokumentenindex (Typ „Kurs (H5P)“, mit Kapitelzahl und Pfad), öffnet auf Klick direkt
die Kursansicht (dieselbe Aktion wie die Ordnerliste heute) und zeigt je Kurs den
Stand des letzten lokalen Audits. Aufbau wie die Tag-Label-Ansicht (Liste mit
Zählern) direkt aus dem vorhandenen Index – kein eigener Service.

Sollte die Ansicht vor der Extraktion gebraucht werden, kann eine minimale
Kernfassung (Filter `kind === "Kurs (H5P)"` aus `GET /api/qmds`) als Zwischenstand
schon mit M2 entstehen und in M4 vom Plugin übernommen werden. Empfehlung: direkt im
Plugin bauen; das erspart doppelte Pflege.

### 3.6 Auslieferung und Nachinstallation

- Grundfunktionen: Kern = Dokumente, Editor, Rendering, Suche, Tags/Ordner, Tabs,
  Chat, Aufträge. Eingebaute Plugins (`kurse`, `kalender`) sind ab Auslieferung
  standardmäßig aktiv und lassen sich abschalten; extern installierte Plugins sind
  standardmäßig ausgeschaltet, bis sie aktiviert werden.
- Erste Form (dieses Repository): Plugins unter `src/material_ui/plugins/`, je Plugin
  ein optionales Extra in `pyproject.toml`. Ein Start ohne das `[kalender]`-Extra
  meldet dezidiert die fehlende Abhängigkeit.
- Spätere Form (getrennte Verteilung): `material-ui-kalender` und weitere als eigene
  Pakete mit Entry-Point `material_ui.plugins` und den Assets im Paket; der Host lädt
  sie zusätzlich zu den eingebauten. Der Plugin-Ordner trägt die Struktur des
  Manifests schon jetzt – kein Übergangsaufwand.
- Pflege: `inv plugin-list`, `inv plugin-enable <id>`, `inv plugin-disable <id>`
  sowie der UI-Dialog „Plugins“ mit Status, Fehlern, Version und Capabilities samt
  Bestätigung des nötigen Neustarts (bestehender Restart-Fluss).

## 4. Ablaufplan (Meilensteine mit Abnahme)

Reihenfolge und Begründung: Der Kalender ist Neuland ohne Migrationslast – er validiert
Ansichts-Registry und Plugin-Host unter realer Nutzung, bevor die am tiefsten
verwobene Kursfunktionalität über dieselben Haken zieht. Der Kursmodus bleibt bis M4
voll funktionsfähig im Kern; wer die Kurs-Ansicht früher im Rail braucht, nimmt die
minimale Kernfassung aus 3.5 vorab.

| M | Inhalt | Abnahme |
| --- | --- | --- |
| M1 | Ansichts-Registry: `views.js`, Rail aus der Registry, drei Kernansichten registriert, Persistenz, `mayLeave()`-Wächter | Keine Verhaltensänderung; bestehende Playwright- und pytest-Fälle grün; Rail zugänglich (ARIA: `aria-pressed`, Tooltips, Tastatur) |
| M2 | Plugin-Host: Backend-Lader, Manifestvalidierung, Fassade (`PluginContext`), `/api/plugins`, Aktivieren/Deaktivieren, Fingerprint-Erweiterung; Frontend-Lader; Test-Plugin (Ansicht, Route, Settings, Job) | Test-Plugin erscheint im Rail und funktioniert; seine Route durchläuft Host-/Origin-/Token-Guards; ein kaputtes Plugin zeigt Fehlerstatus statt Absturz; Desktop-Starter startet bei Plugin-Änderung neu |
| M3 | Kalender-Plugin: CalDAV-Sync (Konten, Cache, Kanal, Intervall-Worker), Monats- und Agenda-Ansicht, Einstell-UI, Offline-Cache | Beide Ansichten liefern Termine aus gestubbten DAV-Antworten (kein Netz im Test); Serientermine und Zeitzonen korrekt; Sync-Status sichtbar; Passwörter nur 0600 und maskiert |
| M4 | Kurs-Extraktion: Haken aus Tabelle 3.3 im Kern, Plugin `kurse` entsteht (Backend, Frontend, Modus, Anlage-Typ, Ansicht „Kurse“), Testwanderung | Kern ohne Kursbezüge (grep-Abnahme); alle gewanderten Tests grün; Playwright-E2E des Kurs-Workflows (Index laden, Aktivität speichern, Audit-Mock, Vorschau-Mock); Desktop-Starter-Test der Kurs-MDX; die Remote-Moodle-Regeln aus `AGENTS.md` gelten unverändert |
| M5 | Verteilung: Marketplace/Paketmanager — git-Katalog (über `MATERIAL_UI_MARKETPLACE_REPO` konfiguriert), Resolver mit `dependsOn`/`provides`, Lockfile, `inv plugin-install/-uninstall/-update/-refresh`, UI „Einstellungen → Marketplace“, Doku in `material_ui/README.md` | **Umgesetzt** (apiVersion 4, Capability `plugin-marketplace`): Katalog wird geklont/gepullt, Installation kopiert atomar ins Benutzerverzeichnis und aktiviert, Abhängigkeiten werden rekursiv aufgelöst, Zyklen/Konflikte als 409, Deinstallation eingebauter Plugins gesperrt |

Größenordnung: M1 mittel, M2 groß (größte Schnittstelle), M3 mittel, M4 groß
(risikoreichste Migration), M5 klein bis mittel.

## 5. Sicherheit und Betrieb

- Host-, Origin- und Token-Prüfungen aus `http.py` gelten automatisch für
  Plugin-Routen; es gibt keine eigenen Authentifizierungspfade. Das API-Fehlerform
  bleibt `{"error": {...}}`.
- Schreibzugriffe von Plugins: nur der eigene Storage unter
  `.material-ui/plugins/<id>/` und die Host-APIs; keine freien Repository-Pfade,
  keine Shell. Die Fassade verweigert Überschreitungen aktiv statt per Konvention.
- Passwörter (CalDAV): 0600-JSON, im UI maskiert, nie in Git (`.material-ui/` ist
  bereits ignoriert); Sync-Fehler protokollieren keine Passwortinhalte.
- Netzwerk: nur die direkt konfigurierten CalDAV-Konten des Plugins; der Host stellt
  keine generelle Web- oder Proxy-Freigabe bereit.
- Plugin-Installation ist bewusst ein lokaler Vertrauensakt (pip oder Ordner) analog
  zum CLI selbst; die Manifest-Capabilities dokumentieren die Wirkung vor dem
  Aktivieren.
- Degradation: kaputte oder wegen fehlender Extras nicht ladbare Plugins laufen als
  `error`-Status weiter; Kern und andere Plugins bleiben voll nutzbar.
- Die Verhaltensdokumentation in `material_ui/README.md` wird je Meilenstein
  mitgeführt – dort steht heute das Verhalten vollständig beschrieben; dieser Plan
  ergänzt nur Neuansätze und referenziert Bestehendes.

## 6. Teststrategie

- M1: bestehende Frontend- und Playwright-Tests; neue Fälle: Rail-Reihenfolge,
  wiederhergestellte Ansicht nach Neuladen, Wechselwächter mit ungespeicherter
  Editorfassung.
- M2: pytest für Manifestvalidierung, Suchreihenfolge, Fehlerisolation,
  Storage-Abgrenzung (kein Pfad-Traversal über die Plugin-ID), Versions-Gate
  (`minAppApi`), Guard-Anwendung auf Plugin-Routen; Playwright: Test-Plugin-Ansicht
  und Fehlerstatus.
- M3: CalDAV-Client gegen aufgezeichnete beziehungsweise gestubbte DAV-Antworten
  (kein Netz); Serien- und Zeitzonenfälle mit `recurring-ical-events` auf
  Beispieldaten; Cache-Schreibvorgänge (atomar, Absturz-Szenarien); Playwright:
  Monatsraster, Agenda, Einstell-UI, Passwortmaskierung.
- M4: Wanderung der bestehenden Kurs-Fälle (u. a. aus
  `src/tests/test_material_ui_architecture.py`, `src/tests/test_material_ui.py`);
  Haken-Tests (Index-Provider, Path-Resolver, Modusregistrierung); End-to-End-
  Playwright des Kurs-Workflows mit Mocks – kein Remote-Moodle, keine Remote-H5P-
  Aktionen.

## 7. Risiken und Gegenmaßnahmen

- **M4 ist die riskanteste Migration** (Tabs, Drafts, Desktop-Starter).
  Gegenmittel: Haken zuerst bauen und mit Tests absichern, dann Schritt für Schritt
  mit den mitwandernden Tests umziehen; keine parallelen Verhaltensänderungen;
  grep-Abnahme auf kernbezogene Kursbezüge – eine Suche nach `kursMode`,
  `courseEntryForPath` und `setKursMode` unterhalb `src/material_ui` darf danach nur
  noch die Haken-Definitionen finden.
- **Plugin-API-Fläche** wächst schnell ohne Versionsdisziplin. Gegenmittel: schmale,
  versionierte Fassade (`api-contract.json`), Erweiterungen nur über neue
  Capability-Namen; keine Kernmodule als interne Reste an Plugins weitergeben.
- **Frontend ohne Build-Schritt**: Plugins bleiben Vanilla-ES-Module, keine
  npm-Kette je Plugin; Konvention im Authoring-Guide (M5).
- **Kalenderdatenqualität** (Zeitzonen, Ausnahmen, Ganztägigkeit) ist
  erfahrungsgemäß der eigentliche Aufwand. Gegenmittel: Zeitfenster-Abgleich und
  Serien-Expansion in v1; ein Wechsel zu CalDAV-Sync-Tokens (serverabhängig) bleibt
  als Ergänzung offen.
- **Rail-Überlauf** bei vielen Plugins: Das Rail wird scrollbar; Behandlung
  (CSS, Fokuszustände, ARIA) ist Teil von M1.

## 8. Offene Entscheidungen (Empfehlungen jeweils markiert)

1. **Reihenfolge M3 (Kalender) vor M4 (Kurse)** – Empfehlung: ja, wie in Abschnitt 4
   begründet; alternativ M4 zuerst, wenn die Kurs-Ansicht im Rail dringender ist als
   die Kalenderfunktionen.
2. **Kurs-Routenpfade** unter `/api/kurse/…` behalten statt unter
   `/api/plugins/kurse/…` – Empfehlung: behalten (Starter, Tabs und dokumentierte API
   bleiben stabil; Blueprint-Präfixe erlauben es).
3. **Plugin-UI aus JS rendern** statt feste Anker-Blöcke in `index.html` –
   Empfehlung: JS-Rendering; im Kern bleiben nur die Slots der Workspace-Modi.
4. **Kalender-Cache als JSON** statt SQLite – Empfehlung: JSON in v1.
5. **Eingebaute Plugins standardmäßig aktiv** – Empfehlung: ja (Nutzererwartung an
   das Auslieferungs-Repository); Abschaltung über UI und CLI.
6. **CalDAV-Passwörter in `settings.json` (0600)** statt `.env` – Empfehlung:
   `settings.json`; `.env` bleibt für Betreiber- und Umgebungswerte wie heute.

### Implementierte Einheitenaktionen und Lernstand-Export

Frontend-Plugins können über `ctx.units.registerAction({ id, matches, mount })`
Aktionen zu Einheiten beitragen. `matches(unit)` grenzt die Aktion auf passende
Einheiten ein; `mount({ unit, container })` erzeugt die Bedienelemente. IDs werden
vom Host mit der Plugin-ID versehen. Der Rückgabewert ist eine Funktion zum
Entfernen der Aktion. Einheiten mit Lernstand zeigen die Aktionen in der breiten
Diagnoseansicht, andere Einheiten in ihrer normalen Aktionsleiste. Später geladene
Aktionen werden in bestehende Ansichten eingefügt, ohne offene Dialoge oder
Editoren neu aufzubauen. Fehler einer Aktion bleiben auf deren Bereich begrenzt.

Das eingebaute Plugin `lernstand` nutzt diesen Haken für den Paketdownload und
registriert seine eigene Exportroute. Modell und Bearbeitung bleiben im Kern;
Veröffentlichungsformat, Vorschauseite und rsync-Upload liegen beim Plugin.
Details und Bedienung: [Lernstand und Förderung](lernstand-und-foerderung.md#plugin-grenze).

### Kalender-Schnittstellen (November 2026)

Für neue Integrationen gelten folgende öffentliche Haken:

- Backend: Das Kalender-Plugin stellt das Interface `@calendar` bereit
  (`provides: ["calendar"]`, Plugin-Version 0.3.0). Ein Plugin deklariert
  `"dependsOn": {"@calendar": ">=0.3.0"}`, holt `ctx.service("calendar")` und ruft
  `register_source(provider, source_id=…, name=…)` mit dem bestehenden Terminvertrag auf.
  Die Rückgabe ist eine idempotente Abmeldefunktion (am besten über
  `ctx.lifecycle.on_shutdown`); `sources()` liefert einen Snapshot als
  `(source_id, name, provider)`. Der Kalender validiert Antworten vollständig und isoliert
  Quellfehler je Quelle. Der Kern kennt keine Kalenderquellen mehr; `ctx.calendar` und
  `register_calendar_source` im Backend sind entfernt. Seit 0.3.0 liest das Interface auch
  den Kalenderbestand: `events(from_iso, to_iso)` (gecachte Termine im Fenster inkl.
  lokaler Einträge), `tasks()` (offene TODOs) und `timezone()` – etwa für das eingebaute
  Plugin `erinnerungen` (Desktop-Benachrichtigungen bei geschlossener UI).
- Frontend `ctx.calendar.registerAction({ id, mount })` registriert eine Aktion in
  Kalender und Agenda. `mount({ container, refresh })` erhält einen eigenen Container
  und die gemeinsame Aktualisierungsfunktion; optional liefert es eine Cleanup-Funktion.
  IDs werden mit der Plugin-ID versehen. Die Registrierung liefert eine Abmeldefunktion.
  Bereits gemountete Toolbars werden nachgezogen, sodass die Ladereihenfolge egal ist.
  Das bisherige DOM-Ereignis bleibt für ältere Plugins erhalten.
- Backend `ctx.units.scheduled()` liest die Einheiten mit Einsätzen; `ctx.workers`
  bietet `closing` und `start_worker(fn, args)` für verwaltete Hintergrundarbeit.
  Der Kalender benötigt damit keinen direkten Zugriff auf die gesamte Runtime.

- Einheit und Material am Termin: `event.units[]` enthält neben `path` und `title` die Liste
  `materials` (Pfade relativ zum Einheitenordner, leer bei Einsätzen für die ganze Einheit; mehrere
  Einsätze derselben Einheit am Tag werden gesammelt). Heute, Monatsliste und Agenda zeigen dafür
  je einen Knopf, der das Ereignis `material-ui:open-material` mit dem Dokumentpfad
  (`<Einheitenpfad>/<Material>`) auslöst; die Einheitenansicht öffnet das Dokument im Editor.
  Das Feld ist additiv, ältere Oberflächen ignorieren es.

Die additiven Fähigkeiten `plugin-calendar-sources` und `plugin-calendar-actions`
stehen im API-Vertrag. Auch JS-Module in Unterordnern werden über die Importmap
versioniert, damit Plugin und Host dieselbe Registry-Instanz verwenden.
`runtime` und `config` bleiben zur Kompatibilität verfügbar: Das ist keine Sandbox
für fremden Python-Code.

### Such-Schnittstellen (November 2026)

- Backend: `ctx.search.register(provider, source_id=…, name=…)` registriert eine
  Such-Quelle für `GET /api/search` (Fähigkeit `plugin-search-providers`). Der Provider
  erhält `(query, filters)` und liefert Treffer-Dicts mit mindestens `path` und `title`;
  der Kern normalisiert sie, versieht sie mit `source: <source_id>` und mischt sie vor
  Sortierung und Limit in die Kerntreffer. Fehler einer Quelle landen als
  `sourceErrors: [{source, name, message}]` in der Antwort, ohne die Kernsuche zu
  beeinträchtigen; `sources` listet die registrierten Quellen. Die Registrierung
  liefert eine idempotente Abmeldefunktion. `source_id` ist ein Slug
  (`[a-z0-9-]{1,32}`), max. 16 Quellen.
- Frontend: `ctx.search.registerProvider(provider, sourceId, name)` (Loader-Fassade
  über `static/search-providers.js`) registriert lokale Trefferquellen für den Picker
  (Strg+K); die IDs werden mit der Plugin-ID versehen. Lokale Treffer werden nach den
  API-Ergebnissen eingemischt und tragen ebenfalls `source`; im Picker erscheint der
  Quellenname als Badge am Treffer.
- Indexanbieter (`ctx.index.register`, Fähigkeit `plugin-index-providers`) und
  Workspace-Modi (`ctx.workspace.registerMode`, Fähigkeit `workspace-modes`) sind
  bereits umgesetzt und oben beschrieben.
