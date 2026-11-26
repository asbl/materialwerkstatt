# Material-UI: Architektur und API

Die Anwendung läuft lokal als einzelner Flask-Prozess über `inv material-ui`.
`create_app()` erzeugt einen eigenen `RuntimeState`. `create_app(config=AppConfig(root))`
bindet eine Instanz an ein bestimmtes Repository; mehrere Instanzen dürfen unterschiedliche
Repositorys verwenden. Tests können Dokumentablage, Prozessverwaltung und Auftragsregister
über `RuntimeState` injizieren und diesen über `create_app(runtime=...)` übergeben.
Ein injizierter Zustand gehört dem Aufrufer und wird mit `runtime.close()` beendet.
Ohne Flask-Kontext oder expliziten `runtime_scope` gibt es keinen impliziten Standardzustand.
Die Dienste selbst benötigen weder Flask noch einen Request-Kontext.

## Desktop-App

`inv material-ui-install` installiert den Starter, die QMD-Dateizuordnung und
das Icon samt Cache-Aktualisierung. MDX-Dateien aus `kurse/` sind ebenfalls
zugeordnet: Der Starter übergibt sie als `?path=`-Parameter, und die UI öffnet
für jede Kurs-MDX (`index.mdx` wie `chapters/*.mdx`) die Kursansicht des
zugehörigen Kurses. MDX-Dateien außerhalb von `kurse/` und externe MDX-Pfade
lehnt der Starter ab. `desktop.py` öffnet Chromium im App-Modus,
protokolliert Browserfehler und prüft den Serverstand anhand eines Fingerprints
der Python-, JavaScript-, CSS-, HTML- und SVG-Dateien im Paket. Die API liefert
den beim Serverstart ermittelten Fingerprint. Beim Öffnen startet der Starter
einen fehlenden Server automatisch und startet einen veralteten Server neu.
Ein aktueller Server wird weiterverwendet. Mit `inv material-ui-server
--action status|start|stop|restart` lässt sich der Server verwalten. Stop/Neustart
prüfen Repository und Prozessidentität vor dem Beenden.

Beim Serverstart wird der Materialindex in einem verwalteten Hintergrund-Worker
aufgebaut. Die Oberfläche zeigt währenddessen „Index wird aufgebaut …“; für
`/api/qmds` gelten 120 Sekunden Zeitlimit, bei einem wiederholbaren Fehler folgt
ein zweiter Versuch. Metadaten für Index und Navigation verwenden einen schnellen
YAML-Leseparser; Änderungen am Frontmatter behalten den Round-Trip-Parser für
Kommentare und Zitierstil. Der Quellkatalog hält Dateiköpfe und Metadaten mit
Datei-Fingerprints im Cache und schließt `foerderempfehlungen/` samt verlinkten
Verzeichnissen bereits beim Scan aus.

Material-UI öffnet sich möglichst nur einmal: Jedes App-Fenster meldet sich
alle zwei Sekunden per Herzschlag beim Server (`POST /api/window/heartbeat`,
Registry in `windows.py`, Routen in `window_routes.py`); beim Schließen meldet
es sich ab, und ohne Herzschlag gilt ein Fenster nach zwölf Sekunden als beendet.
`GET /api/desktop-status` meldet die Zahl lebender Fenster. Öffnet der Starter
eine Datei, während ein Fenster lebt, stellt er die Anforderung an den Server
(`POST /api/window/open`, Pfad oder Import-Token) und wartet kurz, bis ein
Fenster sie beim nächsten Herzschlag übernimmt und die Datei als Tab öffnet;
erst wenn kein Fenster übernimmt, startet der Starter ein neues App-Fenster.
Ein Starter ohne Datei holt bei lebendem Fenster nur das bestehende nach vorn.
Die gesamte Fensterphase läuft unter dem Startup-Lock, und nach dem Start
wartet der Starter die Registrierung des neuen Fensters ab: Zeitgleich
gestartete Starter (Mehrfachauswahl im Dateimanager) entscheiden so
nacheinander, und alle Dateien öffnen als Tabs im selben Fenster. Ein über
`xdotool` erreichbares bestehendes Fenster holt der Starter zusätzlich nach
vorn. Die Weiterleitung ist bewusst best effort: Schlägt sie fehl, greift wie
bisher das neue Fenster.

Per Rechtsklick auf einen Tab lassen sich über „Andere Tabs schließen“ alle anderen
Tabs schließen. Bei ungespeicherten Änderungen und deaktiviertem Auto-Speichern
erscheint eine Rückfrage zum Speichern; Abbrechen oder ein Speicherfehler hält die
Tabs offen.

Mehrere Dateien sind in Tabs geöffnet: Die Tab-Leiste über dem Editor zeigt
alle geöffneten Dokumente und Kurse (maximal 12), ein Klick wechselt, die
X-Knopf oder Mittelklick schließt einen Tab; beim Schließen des aktiven Tabs
wechselt die UI zum Nachbartab, sonst in die leere Ansicht. Ungespeicherte
Änderungen werden beim Wechsel wie beim Dokumentwechsel gesichert. Die offenen
Tabs bleiben in `localStorage` (`material-ui:open-tabs`) erhalten und werden
beim Start wiederhergestellt; Umbenennen und Löschen in der Ordnerliste
aktualisieren oder entfernen betroffene Tabs. `static/tabs.js` enthält die
Tab-Logik, `static/windows.js` Herzschlag und Übernahme der Öffnen-Anforderungen.

Beim Dokumentwechsel hält der Editor bis zu zwölf zuletzt verwendete Zustände
mit insgesamt höchstens zwei Millionen Quelltextzeichen im Speicher. Bei
unverändertem Text bleiben Undo, Auswahl und Faltungen erhalten; externe
Textänderungen erzeugen einen neuen Zustand. Die Dateiabfrage bleibt bei jedem
Wechsel aktiv. PDF-URLs verwenden die Dateiversion statt eines Zeitstempels pro
Aufruf. Nur zur aktuellen Version passende URLs dürfen privat im Browsercache
bleiben; unversionierte Abrufe und andere API-Antworten bleiben `no-store`.
Die Aktualitätsprüfung verwendet einen begrenzten Cache für Abhängigkeits-Hashes,
der Änderungszeit, ctime, Größe und Dateiidentität vor jeder Wiederverwendung prüft.

Externe QMDs werden zunächst mit zufälligem Token, Dateirechten 0600 und einer
Gültigkeit von 24 Stunden im lokalen Zustandsverzeichnis vorgemerkt. Die URL
enthält nur dieses Token. Die API akzeptiert keine beliebigen externen Quellpfade.
`qmd_imports.py` übernimmt nach Bestätigung die UTF-8-Datei (maximal 24 MiB) an
einen geprüften Repository-Zielpfad. Veröffentlichung über einen atomaren Hardlink
verhindert das Überschreiben existierender Dateien. Original und verknüpfte
Ressourcen bleiben unverändert. Import, Abbruch und Dokumentwechsel aktualisieren
die URL, damit Neuladen das aktuelle Dokument beibehält.

Unter Wayland wird bei gesetztem `DISPLAY` XWayland für das App-Fenster verwendet,
damit `StartupWMClass` den Launcher zuverlässig zuordnet. Ohne XWayland verwendet
Chromium seine native Plattform; deren Dockzuordnung ist separat zu überprüfen.

## Zuständigkeiten

„Neu“ neben der Materialauswahl öffnet die Anlage mit der üblichen Ordnerstruktur.
„Neu in diesem Ordner“ unter der Ordnerliste legt die QMD-Datei direkt im aktuell
ausgewählten Ordner an; der Dialog zeigt den Zielpfad vor dem Anlegen.
Jede Datei in der Ordnerliste trägt zusätzlich Knöpfe zum Umbenennen und Löschen.
Ordner haben neben dem Plus-Knopf einen Knopf „Ordner umbenennen“. Der Dialog
ist mit dem bisherigen Namen vorbelegt. Geöffnete Tabs und das aktive Dokument
erhalten den neuen Pfad auch für Dateien in Unterordnern.
`POST /api/folder/rename` benennt einen sichtbaren Ordner innerhalb seines
Elternordners um; belegte Namen und das Umbenennen des Projektordners werden abgewiesen.
Symbolische Links im Ordnerpfad werden abgewiesen. Zugehörige Build-Artefakte
einschließlich gespeicherter Decks, Anmerkungen und Sicherungen ziehen mit um.
Bereits aktuelle Decks bleiben aktuell; bei vorhandenen Artefakten am Ziel wird
abgebrochen. Fehler beim Verschieben oder Aktualisieren der Deck-Stempel führen
zum Zurücksetzen der Verschiebung.
Nummerierte Ordner (`01_thema`, `02_thema`, …) lassen sich per Drag & Drop
auf einen nummerierten Geschwisterordner ziehen. Der Dialog fragt die neue Position
ab und schlägt die Position des Zielordners vor. Nach Bestätigung werden alle
nummerierten Geschwister ab 1 lückenlos nummeriert; führende Nullen bleiben erhalten.
Nicht nummerierte Ordner bleiben unverändert. `POST /api/folder/reorder` erwartet
`path` und die ganzzahlige `position` (1 bis Anzahl der nummerierten Ordner).
Build-Artefakte ziehen mit um; bei Fehlern werden die Umbenennungen zurückgesetzt.
Offene Tabs und das aktive Dokument erhalten die neuen Pfade.

`POST /api/file/rename` verschiebt eine sichtbare Datei innerhalb ihres Ordners
(409 bei vorhandenem Ziel), `DELETE /api/file` entfernt sie; beide prüfen den Pfad
gegen die Repository-Grenze, lehnen versteckte Pfade ab, invalidieren den
QMD-Cache und liefern den aktualisierten Index zurück. Wird die gerade geöffnete
Datei umbenannt, lädt der Editor sie anschließend unter dem neuen Pfad; wird sie
gelöscht, schließt der Editor das Dokument. Vorher ausstehende Speicherungen
werden abgeschlossen, damit kein Timer die Datei neu anlegt.
Speichern, Bild hinzufügen, Template und Shortcuts stehen oberhalb des Editors.
In der Shortcut-Auswahl öffnen Bausteine mit Einstellungen einen Dialog mit
beschrifteten Feldern, Hinweisen und einer laufend aktualisierten Textvorschau.
Beispielwerte sind vorbelegt; nach dem Einfügen merkt sich der Browser die Werte
pro Baustein. „Beispielwerte verwenden“ setzt die Felder zurück. „Abbrechen“
kehrt zur Auswahl zurück, ohne den Editor oder die gespeicherten Werte zu ändern.
Bausteine ohne Einstellungen werden direkt eingefügt.
Die Baustein-Autovervollständigung im Editor öffnet denselben Dialog; Abbrechen
lässt den eingegebenen Suchtext erhalten. Nach dem Einfügen liegt der Fokus
wieder im Editor. Ungültige Zahlen, Maße und unpassende Anzahlen von Knoten und
Sprüngen werden vor dem Einfügen mit Meldungen direkt am Feld abgefangen.
Codefelder unterstützen mehrere Zeilen; zusätzliche Dateien werden mit korrekt
eingerücktem Code und sicher maskiertem Dateinamen in YAML eingefügt. Sichtbarkeit,
Bearbeitbarkeit und das Aktivieren einer Bewertungsfrist sind im Dialog wählbar.
Die Vorlagen sind über Typ-Tags gruppiert: Zuerst den Typ (etwa Arbeitsblatt,
Klausur, Förderplan oder Fördermaterial) wählen, anschließend eine passende
Vorlage. Der Typ erscheint als Tag in der Vorschau. Beim Anlegen neuer Materialien
filtert die Typauswahl ebenfalls die Vorlagen; für Typen ohne eigene Vorlage
steht die Standardausgabe bereit. Eine bereits gesetzte Vorlage wählt ihren
Typ beim erneuten Öffnen automatisch vor.
Die Template-Auswahl zeigt für jede Vorlage ein schematisches Layoutbeispiel mit
typischen Inhalten, auch beim Anlegen eines Dokuments. Die Vorschau dient der
Layoutauswahl; die tatsächliche PDF-Ausgabe hängt vom Dokumentinhalt ab.
Die Namen kommen ohne Engine-Präfixe aus. Neben den bisherigen Vorlagen gibt es
das Klasse-5-Fördermaterial im Retro-Stil sowie die Designs Retro, Fußball, Reiten und
Anime. Weitere Vorlagen sind **standardmäßig privat** (ignorierter Ordner `src/quarto/_local/`)
und erscheinen in der Auswahl, sobald sie dort liegen; sie werden nie versioniert. Eingebaut
wird eine Vorlage nur ausdrücklich über `inv template-freigeben` (siehe
`src/quarto/templates/README.md`). Beim Wechsel passt
die UI auch das Ausgabeformat an; bestehende Template-Pfade bleiben gültig.
Für Excalidraw stehen die Arbeitsblatt-Designs und ein Standardlayout bereit. Designs
können Kastenmotive mitbringen (`box_icons`, `box_mascot` im Designdatensatz): Dann
erscheinen Symbole oder ein Maskottchen in Info-, Tipp- und Warnboxen, auch in Spalten.
Die QMD-Werte sind `deck-design: <Design-ID>`.
PDF und Slides verwenden dieselbe Template-Auswahl. Vorlagen mit einem
Foliendesign (gestaltete Arbeitsblätter und Folienvorlagen) bestimmen automatisch
auch das passende Excalidraw-Design. Nur für diese Dokumente erscheint „Slides“.
Ein separat gesetztes `deck-design` überschreibt das Template nicht.
„Rendern“ und Auto-Render bauen das PDF und bei passenden Vorlagen auch das
Deck neu. Manuelles Rendern (Button, Strg+Enter) lädt die Datei wie „Neu laden“ zuerst
frisch von der Platte, damit Editor und PDF auch nach Änderungen von außen
denselben Stand zeigen. Bei ungespeicherten Änderungen entfällt das Neuladen:
sie werden wie bisher erst geprüft und dann gespeichert, ein abweichender
Dateistand erscheint als Konflikt. Auto-Render nach dem Speichern lädt nicht
neu. Vorhandene Decks werden einschließlich ihrer Anmerkungen unter einem
eindeutigen Sicherungsnamen aufbewahrt. Separate Anmerkungen werden in
`.material-annotations/<Sicherungsname>` mitgesichert und vom neuen Deck entfernt.
„Slides“ prüft Quelle, Design und die Inhalte eingebundener Bilder: Ein aktuelles Deck bleibt einschließlich seiner
Anmerkungen erhalten; ein fehlendes oder veraltetes Deck wird neu erzeugt.
Die Prüfung verwendet einen Stempel unter `.material-source/` im Build-Ordner.
Ein führender `#`-Titel wird für PDF und Deck als gemeinsame Titelfolie verwendet;
ohne Titel entsteht keine zusätzliche Standardtitelseite.
Folien-PDFs halten jede `##`-Sektion auf einer Seite; bei Bedarf wird der gesamte
Inhalt proportional verkleinert. Die benötigten Filter und Template-Teile werden
auch außerhalb der Quarto-Render-Verzeichnisse mitgegeben. Auto-Speichern und Auto-Render werden im
Einstellungsmenü (Zahnrad) ein- und ausgeschaltet.

Unter „Neues Material“ kann der Typ „Excalidraw-Folien“ samt gemeinsamer
PDF-/Folienvorlage gewählt werden. Dabei entstehen `slide.qmd` im Materialordner,
das PDF unter `build/pdf/` und das Deck zentral unter
`build/artefakte/<Quellordner>/slide.excalidraw`. Neue Quellen verwenden eine
reguläre PDF-Vorlage statt `material-output: excalidraw`. Bei älteren Outlines
wird über „Template ändern“ eine gemeinsame Vorlage zugewiesen.
Die native Excalidraw-Ausgabe enthält editierbare Texte, Rahmen und
Zeichenflächen; die Vektormotive sind direkt in der Datei eingebettet.
Weitere Dokumentaktionen sowie Kurs- und Moodle-Aktionen befinden sich dort unter
„Erweiterte Optionen“.

`.excalidraw`-Dateien in der Ordnerliste erhalten zusätzlich zum Dateilink eine
Play-Schaltfläche: Sie öffnet die Present-App (`/present/?path=…`) in einem Modal
innerhalb der Material-UI, lädt das Deck automatisch und blättert die Frames mit
PageUp/PageDown als Folien durch; „In neuem Tab öffnen“ im Modal-Header erlaubt
weiterhin das separate Fenster. Gezeichnet wird direkt auf der Folie;
„Speichern“ schreibt die bearbeitete Szene über `POST /api/deck/save` atomar in
die `.excalidraw`-Datei zurück; der Server überspringt No-op-Speicherungen,
archiviert die vorherige Fassung in `.material-history/` und bietet sie über
„Versionen“ in der App wieder an. Anmerkungen lassen sich optional getrennt vom
Deck im Sidecar `.material-annotations/` ablegen, damit die Folieninhalte
unberührt bleiben. Beim separaten Speichern prüft der Server sowohl die
Anmerkungsrevision (`revision`) als auch die Deck-Revision (`deckRevision`).
Anmerkungen aus einer alten Deck-Fassung werden mit 409 (`deck_changed`)
abgewiesen. Die App bietet dann einen Download der lokalen Fassung an,
bevor das aktuelle Deck geladen wird. Die App gleicht den Dateistand regelmäßig über
`GET /api/deck/revision` ab und reagiert auf externe Änderungen mit einem
Hinweis beziehungsweise einem Konfliktdialog beim Speichern (409).
QMD-Dokumente verweisen über das Metadatenfeld „Deck“ (Frontmatter `deck:`) auf
eine `.excalidraw`-Datei; verknüpfte Dokumente zeigen in der Ordnerliste einen
eigenen Play-Knopf, und die Volltextsuche durchsucht auch die Textelemente
aller Decks. Ohne Material-UI-Kontext (etwa beim Start über `inv deck-present`)
bleibt die App nutzbar und speichert per Download. Die App selbst liegt als
Vite-Build in `src/excalideck/present/` und wird einmalig mit `inv deck-present`
gebaut; fehlt der Build, liefern die Present-Routen einen klaren Hinweis statt
der App.

Der Trenner zwischen Editor und PDF-Vorschau lässt sich ziehen; mit Fokus auf dem
Trenner ändern auch die Pfeiltasten die Breite. Das Vollbild-Icon über dem PDF
blendet die übrige Oberfläche aus. Ein erneuter Klick oder Escape führt zurück.

Die Schaltfläche „Render-Ausgabe“ und ein Klick auf den Status oben öffnen das
Protokoll des letzten Renderns für das aktuelle Dokument. Bei Fehlern öffnet es
sich automatisch und lässt sich auch über den Hinweis in der PDF-Vorschau erneut
aufrufen. Die Ausgabe enthält die letzten 64 KiB des Prozessprotokolls ohne
Terminal-Farbcodes, den Befehl, die Quelldatei und den Exitcode. Nach einem
Dokumentwechsel wird das bisherige Protokoll verworfen.

- `app.py`: App-Factory, Dienstkomposition und Serverstart.
- `config.py`: unveränderliche Repository- und Ausführungskonfiguration mit Pfadprüfung
  (`safe_path`, `safe_visible_path`, `is_visible`).
- `caching.py`: zeitbegrenzter Cache mit Invalidate für Dokument- und Kursindex.
- `errors.py`: `InvalidInput` als Markierung ungültiger Client-Eingaben; nur diese
  werden als HTTP 400 gemeldet, andere Wertefehler gelten als interne Fehler.
- `services.py`: explizite Verdrahtung der Dienste und ihrer Abhängigkeiten.
- `document_routes.py`, `deck_routes.py`, `window_routes.py`: HTTP-Adapter für Dokumente, Excalidraw-Decks und App-Fenster. Kurs-Routen liefert das Plugin `kurse` (`plugins/kurse/routes.py`, stabile Pfade `/api/kurse/…`).
- `server_routes.py`, `job_routes.py`: Startseite, Desktop-/Protokollstatus und Auftrags-API.
- `folder_routes.py`, `tag_routes.py`, `unit_routes.py`, `qmd_import_routes.py`: HTTP-Adapter für Ordner, Tags, Einheiten und QMD-Import.
- `index_payload.py`: gemeinsame Indexantwort für Dokument- und Navigationsaktionen.
- `tags.py`: Tag-Vokabular, Hierarchieeinstellungen und Umbenennung; `DocumentService` delegiert seine bisherigen Tag-Methoden an diesen Dienst.
- `static/unit-editor.js`, `static/unit-data.js`: Einheitenbearbeitung mit Konfliktvergleich sowie reine Zusammenführungs-/Filterfunktionen. `static/units.js` bleibt der Einstieg der Ansicht.
- `static/unit-dates.js`, `static/unit-new-form.js`, `static/unit-filters.js`: Termineformular der Einheitenkarte, Formular „Neue Lerneinheit“ und Filterleiste. Sie erhalten Zustand und Hilfen als Argumente (`createUnitDates`, `createUnitNewForm`) bzw. sind reine Funktionen und lesen keinen Closure-Zustand von `units.js`.
- `static/unit-assign.js`, `static/pointer-drag.js`: Einheit einer Stunde zuweisen und Einsätze auf freie Stunden verschieben, jeweils per Auswahl (Tastatur, Touch) und als Ziehen am Griff. Heute (Plugin „kalender“) bittet den Kern über `material-ui:assign-unit` (`detail`: `event`, `row`, `trigger`, `notify`, `reload`) um die Auswahl unter der Stunde.
- `static/image-import.js`: Bildimport mit Sitzungsprüfung und Einfügen ins Dokument.
- `static/app.css` bis `static/app-modes.css`: Host-Stylesheet in neun geordneten Teilen (Tokens und Kopfzeile, Navigation, Arbeitsbereich, Bedienelemente,
  Editor, Dialoge, schmale Fenster, Zusatzpanels, Workspace-Modi). Die Reihenfolge in `templates/index.html` ist die Kaskadenreihenfolge; neue Regeln
  gehören in den passenden Teil, Abstände, Radien, Schatten und Fokusring kommen aus den Tokens (`--space-*`, `--radius-*`, `--shadow-*`, `--focus-ring`).
- `static/units.css`: Styles der Einheiten und zugehörigen Materialnavigation; wird nach den `app*.css`-Teilen geladen.
- `documents.py`: Dokumentanlage, Indexierung, Templates und Dokumentprüfung.
- `windows.py`: Fenster-Registry mit Herzschlag und Warteschlange der Öffnen-Anforderungen.
- `rendering.py`: Renderdienst mit begrenzter, dokumentbezogener Warteschlange.
- `search.py`: Volltextsuche über alle QMD-Quellen inklusive Frontmatter und Deck-Texte.
- `gitinfo.py`: Status, Diff und letzter Commit einer Datei aus dem Repository-Git.
- `http.py`: Anfragevalidierung, Host-/Origin-/Token-Prüfung und JSON-Fehler.
- `storage.py`: atomare Dateischreibzugriffe und Dokumentrevisionen.
- `assets.py`: vorbereitete Bildimporte mit Rücknahme bei Fehlern.
- `material_core/builds.py`: gemeinsame Buildlogik, Artefakte und Manifeste.
- `material_core/metadata.py`: strukturierte, formatbewahrende Frontmatter-Verarbeitung.
- `jobs.py`: maßgebliche Auftragszustände, begrenzte Historie und exklusive Ausführungskanäle.
- `processes.py`: gemeinsame Prozessverwaltung für kurze Aufträge und dauerhafte Vorschauen,
  begrenzte Protokolle und Abbruch von Prozessgruppen.
- `runtime.py`: Eigentümer der Dienste, registrierten Hintergrundthreads und des Shutdowns.
- Chat-Panel (Provider, Sitzungen, SSE-Stream, MCP-Werkzeuge) und die Import-Workflows
  (Office, Aufgabenbilder) liegen in den eingebauten Plugins `chat` bzw. `importe`
  (`plugins/chat/`, `plugins/importe/`); siehe Abschnitte „Plugins“ sowie
  „Chat-Plugin (`chat`)“ und „Importe-Plugin (`importe`)“.
- `plugins/manifest.py`, `plugins/storage.py`, `plugins/context.py`, `plugins/host.py`:
  Plugin-Manifeste, Aktivierungszustand, Plugin-Speicher/Einstellungen und der ladende Plugin-Host.
- `plugin_routes.py`: Plugin-Liste, Aktivieren/Deaktivieren und versionierte Plugin-Assets.
- `static/api.js`: HTTP-Client, Anfrage-Token und Fehlerauswertung.
- `catalog.py`: gemeinsame Quelldateiliste und begrenzter Textcache für Navigation und Suche;
  unveränderte Verzeichnisse werden zwischen periodischen Abgleichen nicht erneut durchlaufen.
- `static/document-session.js`: Speichern, Revisionen und lokale Entwürfe.
- `static/document-workspace.js`: Dokumentwechsel und PDF-Anzeige.
- `static/recovery.js`: Wiederherstellungsdialog und Versionsauswahl mit eigenem Dialogzustand.
- `static/state-view.js`: explizit begrenzte Zustands- und DOM-Schnittstellen der Controller.
- `static/slides-panel.js`, `static/job-client.js`: Präsentationsaufträge starten und ihr Ergebnis abwarten.
- `static/editor.js`: Adapter zum CodeMirror-6-Editor-Bundle; Bedienoberfläche
  (Status, Speichern/Rendern auslösen) bleibt hier, Editor-Kern liegt gebündelt vor.
- `../editor-app/`: CodeMirror-6-Editor-Kern (QMD-Hervorhebung, Faltung, Suche,
  Autovervollständigung, Undo). Wird per `inv editor-bundle` (bzw. `npm run build`
  in `src/editor-app/`) zu `static/editor.bundle.js` gebaut; nach Änderungen an
  `src/editor-app/src/main.js` neu bauen, sonst bleibt die Oberfläche auf dem
  alten Stand.
- `static/workspace-modes.js`, `static/path-resolvers.js`: Kern-Registries für Plugin-Arbeitsmodi und Pfad-Resolver; die Kurs-UI liegt im Plugin (`plugins/kurse/assets/`).
- `static/images.js`: Bildbearbeitung und Canvas-Ressourcen.
- `static/templates.js`: Template-Auswahl über die serverseitige Metadaten-API.
- `static/modals.js`, `static/theme.js`: Dialogverwaltung mit Fokusfalle sowie
  Hell-/Dunkel-/System-Umschaltung mit `localStorage`-Voreinstellung.
- `static/shortcuts.js`: Shortcut-Liste und Baustein-Autocomplete im Editor.
- `static/picker.js`: Materialauswahl mit Facets, Scoring und Volltexttreffern.
- `static/tabs.js`: Tab-Leiste der geöffneten Dokumente mit Persistenz.
- `static/windows.js`: Fenster-Herzschlag und Übernahme weitergeleiteter Öffnen-Anforderungen.
- `static/render-panel.js`: Renderstatus, Protokollansicht und PDF-Vorschau.
- `static/jobs-panel.js`: Job-Historie als Dialog; aktualisiert beim Öffnen und
  per Aktualisieren-Knopf (der Auftrags-Eventstrom speist die Renderstatusanzeige).
- `static/diff.js`: Zeilenvergleich (Diff) für Wiederherstellungs- und Versionsdialoge.
- `static/file-actions.js`, `static/qmd-import.js`, `static/new-document.js`,
  `static/metadata-panel.js`, `static/git-panel.js`: Dateiaktionen, QMD-Import,
  Dokumentanlage, Metadaten- und Git-Dialog.
- `diagnostics.py`: positionierte Prüfhinweise für gespeicherte und ungespeicherte QMDs.
- `search.py`: inkrementeller Textindex, Filter und globale Trefferbewertung.
- `static/diagnostics.js`: automatische Prüfungen, Markierungen und Hinweisliste.
- `../editor-app/src/diagnostics.js`: CodeMirror-Markierungen und Randindikatoren.
- `static/app-state.js`: initialer Anwendungszustand und DOM-Referenzen.
- `static/navigation.js`: Ordner-, Tag-Baum- und Tag-Label-Navigation sowie Tag-Pflege.
- `static/views.js`: Ansichts-Registry: Rail-Knöpfe, Ansichtswechsel, Wächter und persistierte Ansicht.
- `static/plugins/loader.js`: laedt das Frontend aktivierter Plugins dynamisch und stellt den Plugin-Kontext bereit.
- `static/workspace-layout.js`: Seitenleistenbreite, Fokusmodus, Chat-Dock und PDF-Vollbild.
- `static/template-catalog.js`: Vorlagenkatalog und Layoutvorschauen.
- `static/update-scheduler.js`: automatische Speicherungen, Renderplanung und Timer.
- `static/ui-utils.js`: Formatierung, Suchnormalisierung und Browserpräferenzen.
- `static/app.js`: Verdrahtung, Ereignisbindungen und Dokumentwechsel.

Die Frontend-Controller erhalten ihre Abhängigkeiten bei der Erzeugung und importieren
`app.js` nicht zurück. Kurs- und Bildzustand sind getrennt gruppiert. Vor einem Kursaudit
oder einer Moodle-Aktion wird die aktuelle Editorfassung vollständig gespeichert.
Speicherfehler oder ein Dokumentwechsel währenddessen verhindern den Start der Aktion.

`POST /api/document/metadata` verarbeitet den übergebenen, auch ungespeicherten `text`.
Ohne `template` liest die Route die Metadaten; mit `template` setzt oder entfernt sie
den Eintrag und liefert den veränderten Text zurück. Mit `fields` (Objekt mit
Zeichenkettenschlüsseln und -werten) setzt die Route mehrere Frontmatter-Einträge
auf einmal; leere Werte entfernen den Eintrag. Werte dürfen zusätzlich Listen von
Zeichenketten sein (leere Liste entfernt den Eintrag) — der Metadaten-Dialog nutzt
das für den `tags`-Eintrag, der kommagetrennt eingegeben und mit Vorschlägen aus
`GET /api/tags` ergänzt wird. Sie schreibt keine Quelldatei.
YAML-Kommentare, Anführungszeichen und der Dokumentkörper bleiben erhalten.
`output-file` wird ausschließlich aus dem Frontmatter und dem PDF-Format gelesen;
Beispielcode im Dokumenttext beeinflusst den Ausgabepfad nicht.

## Tags

QMD-Dateinamen mit „Lösung“/„Lösungen“ (auch `loesung`, Großschreibung und
Musterlösungen) erhalten automatisch `kind: Lösung` und den Tag `Lösung`.
Die Kennzeichnung wird beim Erstellen, Speichern und beim Indexieren bestehender
oder umbenannter Dateien im Frontmatter ergänzt. Vorhandene Tags bleiben erhalten;
unvollständiges YAML bleibt speicherbar und wird nach der Korrektur ergänzt.
Lösungen lassen sich über den Typ, den Tag oder den Filterchip auswählen.
Navigation und Suche zeigen eigene Icons: Lösungsblatt mit Haken, Aufgabenblatt
mit Aufgabenzeilen und Präsentationstafel für Slides.

Jede QMD kann im Frontmatter einen `tags`-Eintrag (Liste von Zeichenketten)
tragen. Der Index nimmt die Tags als `tags` in jeden QMD-Entry auf;
`GET /api/tags` liefert das über alle QMDs aggregierte Vokabular mit
Vorkommenszählung, häufigste Tags zuerst. Über der Ordnerliste schaltet die
Materialauswahl zwischen Ordner- und Tag-Ansicht um: Die Tag-Ansicht zeigt alle
Tags mit Zählung als auswählbare Chips, mehrere ausgewählte Tags filtern die
Dokumentliste per UND-Verknüpfung, und die Treffer öffnen direkt im Editor.
Zusätzlich filtert das Tag-Feld der Suchmaske die Treffer der Materialauswahl
und wird an die Volltextsuche (`tags`-Parameter) weitergereicht.
Die Ordneransicht bleibt unverändert verfügbar; langfristig kann die Struktur
so tag-gesteuert statt ordnergetrieben werden.

`subject`, `grade`, `thema` und `kind` im Index-Entry bevorzugen nicht leere
Zeichenketten-Einträge aus dem Frontmatter; die Pfadableitung
(`klasse-XX`-Ordner, `infer_kind`) greift nur noch als Fallback für Dateien
ohne entsprechende Einträge. `inv tags-backfill` schreibt die pfadabgeleiteten
Attribute (Fach, Klasse, Thema, Typ) einmalig als `tags`-Eintrag in alle QMDs
ohne Tags; der `wissen`-Submodule bleibt ausgespart, und mit `--trocken` zeigt
der Task nur an, was passieren würde. Der tags-Block wird textuell eingefügt,
sodass die Formatierung des bestehenden YAML-Headers unverändert bleibt.

## Ansichten

Die Ordneransicht zeigt QMD-Materialien mit Materialart und mehrzeiligen Titeln.
Passende Lösungsdateien stehen direkt unter der Quelle; die Zuordnung erfolgt
über denselben Dateinamen mit dem Suffix `-loesung` oder `_loesung` (auch plural).
Mit `loesung: ab_loesungen.qmd` im Frontmatter lässt sich auch ein gemeinsames
Lösungsblatt im selben Ordner mehreren Aufgabenblättern zuordnen. Diese Zuordnung
gilt in der Ordneransicht, in Lerneinheiten und in der Lösungsansicht; eine manuelle
Auswahl in der Lösungsansicht hat Vorrang.
Eigenständige Lösungen und alle übrigen Dateien bleiben separat erreichbar.
Dateiaktionen erscheinen bei Hover oder Tastaturfokus, ohne die Zeilenhöhe zu ändern.


Die linke Rail hält alle Ansichten der Seitenleiste: Ordner und „Tags: Baum“
registrieren sich im Kern selbst über die Ansichts-Registry (`static/views.js`), Plugins
ergänzen eigene Knöpfe und eigene Abschnitte unter `#indexContent`. Jede Ansicht darf
sich laut Registry-Vertrag als eigenes `<section>`-Element mounten (lazy beim ersten
Aktivieren) und erhält `onActivate`/`onDeactivate`; die beiden Kernansichten teilen sich
dagegen die vorhandene Ordnernavigation, die bei Plugin-Ansichten ganz ausgeblendet wird.
Beim Ansichtswechsel laeuft zuerst ein Wächter: Eine offene, ungespeicherte
Kursaktivität wird wie bisher ueber `confirmDiscardOrSave()` abgesichert, bevor die
Ansicht wechselt. Die zuletzt gewaehlte Ansicht steht unter
`localStorage["material-ui:active-view"]` und wird beim Neuladen wiederhergestellt;
Plugin-Ansichten werden erst nach dem Laden des Plugins zurueckgeholt, unbekannte IDs
fallen auf die Ordneransicht zurueck. Der Rail laesst sich bei vielen Ansichten scrollen.

Die Materialnavigation führt fest durch Fach → Klasse → Thema, jeweils mit Pfad und
Zurück-Funktion. Fach- und Klassen-Tags erscheinen nicht als Themen. Schuljahr,
Materialart und Suche filtern unabhängig davon und bleiben beim Navigieren erhalten.
Aktive Filter lassen sich einzeln entfernen; Zurücksetzen betrifft nur diese Filter. Die Suche
bleibt sichtbar, weitere Filter stehen unter „Filter …“. Themen und Materialien
teilen den Scrollbereich der Seitenleiste; die Trefferliste zeigt 20 Materialien
pro Seite. Im gewählten Thema erscheinen Tag-Badges aus allen passenden Dateien
mit Trefferzahl. Mehrere Badges filtern gemeinsam (UND); gewählte Pfad-Tags werden
ausgeblendet. Badges lassen sich einzeln abwählen oder über „Filter zurücksetzen“
entfernen. Rechtsklick auf ein Thema (auch im Pfad) öffnet die Tag-Verwaltung.

## Plugins

Ein Plugin ist ein Ordner mit `plugin.json` (ID `[a-z0-9-]+`, identisch zum Ordnernamen,
`name`, `version`, `minAppApi`, `capabilities` aus `network-outbound`/`repo-read`/`state-write`,
optional `pythonEntry` als Funktionsname in `__init__.py`, `jsEntry`, `styles`, `icons`,
`defaultEnabled`, `systemRequirements`) plus Python- und Frontenddateien.
`"defaultEnabled": false` laesst auch ein eingebautes Plugin erst nach `inv plugin-enable` laufen.
`systemRequirements` ist eine Liste `{key, binaries, purpose, packages?, hint?}` mit den
Systemprogrammen, die nur dieses Plugin braucht (`packages`: Paketnamen je `pacman`, `apt`, `dnf`,
`zypper`); der System-Check (`inv doctor`, `install.sh`) prueft sie nur bei aktiviertem Plugin. Suchorte in dieser Reihenfolge (doppelte IDs entfallen):
eingebaut unter `src/material_ui/plugins/<id>/`, installierte Distributionen ueber die
Entry-Point-Gruppe `material_ui.plugins`, Benutzerverzeichnis
`~/.local/share/material-ui/plugins/<id>/` sowie projektbegleitend — test- und
umgebungsweise ersetzt `MATERIAL_UI_PLUGIN_PATHS` (os.pathsep-Liste) alle Suchorte.

Der Host laedt aktivierende Plugins beim Start: Registerfehler eines Plugins landen als
Statuseintrag `error` mit Meldung in `GET /api/plugins`, ohne den Start des Kerns zu
stoppen. Eingebaute Plugins sind standardmaessig aktiv (ausser mit `defaultEnabled: false`),
extern installierte erst nach Bestaetigung; der Zustand liegt dauerhaft unter `.material-ui/plugins.json` und wirkt erst
nach einem Serverneustart (`inv plugin-list`, `inv plugin-enable <id>`, `inv
plugin-disable <id>` oder `POST /api/plugins/<id>/enabled`, Antwort `restartRequired`).
Plugins erhalten einen versionierten Plugin-Kontext: `register_routes(blueprint)` ohne
Prefix-Erzwingung (Routenpfade waehlt das Plugin selbst, z. B. `/api/kurse/…` oder
`/api/plugins/<id>/…`), eigenen Speicher und Einstellungen unter
`.material-ui/plugins/<id>/` (0600-JSON; `password`-Felder werden mit der Maske
`••••` ausgeliefert, und eine Rueckgabe der Maske behaelt den gespeicherten Wert),
`jobs.channel(name)` als exklusiven Ausführungskanal auf der zentralen Auftragsregistrierung
mit SSE-Strom, `lifecycle.on_start/on_shutdown`, eine `runtime`-Referenz fuer
Hintergrund-Worker und die Host-Config. Alle Guards aus `http.py` (Token, Origin,
API-Version) greifen unverändert fuer Plugin-Routen; Assets liefert der Host nur aus
manifestbenannten Dateien unter `/plugins/<id>/…` und nur fuer geladene Plugins,
versioniert mit dem Server-Fingerprint. Der Desktop-Starter bezieht externe
Plugin-Ordner in `application_version()` ein und startet bei Plugin-Aenderungen neu.

Abhängigkeiten deklariert ein Plugin im Manifest: `dependsOn` ist ein Objekt
`{ziel: bedingung}` — Ziel ist eine Plugin-ID oder ein `@interface`, das ein anderes
Plugin per `provides` anbietet (z. B. `"dependsOn": {"@timetable-events": "^1.0"}`);
die Bedingung ist ein Semver-Constraint (`>=`, `^`, `~`, `==`, `*`, kommagetrennt).
Der Host laedt Plugins topologisch (Abhängigkeiten zuerst) und meldet Verstöße als
Zustand `missing-dependency` (nicht installiert) bzw. `blocked` (deaktiviert oder
Version verletzt die Bedingung); Zyklen werden als `error` markiert. Das Deaktivieren
eines Plugins, von dem andere aktivierte Plugins abhängen, wird mit 409 abgelehnt.

Über `provides`/`@interface` hinaus können Plugins einander Dienste überlassen:
`ctx.register_service(name, obj)` registriert ein in `provides` deklariertes Interface
in der Host-Registry, `ctx.service(name)` liefert es einem abhängigen Plugin
(Laufzeit-Lookup, daher ist die Ladereihenfolge egal; ein fehlendes Interface wirft
`LookupError`). Das ist die Schnittstelle, über die z. B. das Plugin `importe` den
KI-Chat des Plugins `chat` für den Umbau gestagter Dokumente nutzt. Die Capability
`plugin-services` gehört zum API-Vertrag (apiVersion 3).

## Private Projekt-Plugins

Neben eingebauten Plugins und dem Benutzerordner (`~/.local/share/material-ui/plugins/`) lädt
der Host Plugins aus `<repo>/plugins/<id>/` (Quelle „project“). Der Ordner ist git-ignoriert;
die Plugins sind vorab aktiv und gehören nicht in den Marketplace: Installieren, Aktualisieren und
Entfernen betreffen nur den Benutzerordner, und ein Katalogpaket mit gleicher ID wird abgelehnt.
So lässt sich privater Code (z. B. die Wissensbasis als Plugin im privaten Wissens-Repo, per
Symlink `plugins/wissen -> ../wissen/plugin` eingehängt) lokal betreiben, ohne das Werkzeugrepo
zu berühren. Fehlt ein solches Plugin, läuft die Anwendung ohne die zugehörige Ansicht.

## Marketplace und Paketmanager

Der Marketplace ist ein **git-Katalog** (kein Standardkatalog: `MATERIAL_UI_MARKETPLACE_REPO`
setzt die URL eines git-Repositorys, z. B. in `.env`; auch lokale `file://`-Pfade sind möglich) mit dem Layout
`plugins/<id>/<version>/plugin.json` (+ optionale `index.json`-Metadaten). Er wird nach
`~/.local/share/material-ui/marketplace/catalog/` geklont bzw. per `git pull --ff-only`
aktualisiert (Offline-Fallback auf den Cache). Installation kopiert die gewählte Version
atomar in das Benutzerverzeichnis `~/.local/share/material-ui/plugins/<id>/`, validiert
das Manifest und aktiviert das Plugin (Installation gilt als Bestätigung); die gewählten
Versionen samt Katalog-Commit landen im Lockfile `.material-ui/plugins.lock.json`.
Weicht die global installierte Version vom Projekt-Lockfile ab (etwa nach einem
Update in einem anderen Projekt), zeigt der Marketplace eine Warnung.
Die Übersicht zeigt die installierte Version und bei ausstehendem Update zusätzlich
die noch geladene Version. Der laufende Plugin-Code wird erst beim Neustart ersetzt.

Installation und Updates lösen die Abhängigkeiten des gesamten verbleibenden
Bestands mit Backtracking auf. Interface-Anbieter werden einschließlich ihrer
konkreten Version geprüft. Unbeteiligte Pakete bleiben nach Möglichkeit unverändert.
Bereits global vorhandene Pakete werden bei einer expliziten Installation ebenfalls
im aktuellen Projekt aktiviert und gelockt; Updates erhalten bestehende Deaktivierungen.
Der Host lädt Konsumenten erst, wenn ein passender Anbieter erfolgreich geladen ist.
Katalog-Versionen mit höherem `minAppApi` als der Server bietet, werden nicht gewählt.
Ein ungültiger Katalog-Eintrag wird übersprungen und als Warnung gemeldet, statt den
gesamten Marketplace zu blockieren. `update all` betrifft nur Pakete aus dem Lockfile;
per Symlink eingebundene Entwicklungsinstallationen und von Hand kopierte Plugins
bleiben unangetastet (explizites Update einer Symlink-Installation wird abgelehnt).
Die Marketplace-Übersicht aktualisiert den Katalog nur, wenn er fehlt oder älter als
10 Minuten ist (`POST /api/marketplace/refresh` und Installation/Update erzwingen es).
Ändert sich die Katalog-URL (`MATERIAL_UI_MARKETPLACE_REPO`), wird neu geklont; schlägt das
fehl, bleibt der bisherige Cache unverändert.
`ctx.require_service(name)` ersetzt `ctx.service(name)`, wenn ein Plugin `ctx.service`
selbst belegt hat.

Paketoperationen teilen prozessübergreifende Sperren für Code, Katalog und
Projektmetadaten. Alle neuen Pakete werden vor der Änderung vorbereitet und validiert.
Bei einem abgefangenen Fehler werden Code, Lockfile und Aktivierung zurückgesetzt;
das gilt auch für Deinstallation und die optional gelöschten Plugin-Daten.
Diese Rückabwicklung ist keine Wiederherstellung nach Stromausfall oder SIGKILL.

- UI: Header-Menü → „Einstellungen" → Abschnitt „Marketplace" (installiert/verfügbar,
  Suche, Abhängigkeiten, Capability-Chips, Installieren/Deinstallieren/Aktivieren/Aktualisieren,
  Neustart-Hinweis mit „Server neu starten").
- API: `GET /api/marketplace`, `POST /api/marketplace/refresh`, `POST /api/marketplace/install`
  `{id, version?}` (Antwort listet alle installierten Pakete inkl. Abhängigkeiten),
  `POST /api/marketplace/uninstall` `{id, purge?, force?}`, `POST /api/marketplace/update`
  `{id | "all"}` — alle Antworten mit `restartRequired: true`.
- CLI: `inv plugin-refresh`, `inv plugin-install <id> [--version …]`,
  `inv plugin-uninstall <id> [--purge] [--force]`, `inv plugin-update [<id>|--all]`.
- Resolver (`plugins/marketplace.py`): wählt je Plugin die neueste Katalog-Version, die
  alle Constraints erfüllt (Auto-Upgrade von Abhängigkeiten); Konflikte (keine passende
  Version) und Zyklen werden als 409 gemeldet. Eingebaute Plugins werden nie überschrieben
  — verletzt die eingebaute Version eine Bedingung, ist das ein Konflikt.
- Deinstallieren ist nur für Benutzer-Plugins (`source=user`) möglich; hängt noch ein
  installiertes Plugin davon ab, wird mit 409 abgelehnt (Dependenten-Liste in der Meldung,
  `force` umgeht). Ohne `purge` bleiben die Daten unter `.material-ui/plugins/<id>/` erhalten.
- API-Fähigkeit `plugin-marketplace` (Vertrag apiVersion 4).

Das Frontend laedt `static/plugins/loader.js` nach dem Protokollabgleich: Er ruft
`GET /api/plugins` ab, verknuepft die CSS-Dateien, importiert das Plugin-JS dynamisch
und uebergibt `register(ctx)` mit `views.register(...)` (Symbol-Verweise auf die
Plugin-Icons), dem `api`-Client, `ui` (Modal- und Statusfunktionen), `events.waitForJob`,
`documents.open(path)` zum Öffnen eines Dokuments im Arbeitsbereich
und einem abgetrennten State-Bereich je Plugin. Ein fehlgeschlagenes Plugin beschraenkt
sich auf seine Statusmeldung. Der Plugin-Frontend-Import von Kernmodulen laeuft ueber die
Importmap (`import … from "/static/ui-utils.js"`), nicht ueber relative Pfade; die
API-Faehigkeiten `plugins`, `plugin-views` und `plugin-marketplace` sind Teil des Vertrags (apiVersion 4).

## Kurs-Plugin (`kurse`)

Das eingebaute Plugin `kurse` liefert die gesamte H5P-Kursfunktionalität; der Kern
kennt keine Kurslogik mehr. Backend: `plugins/kurse/service.py` (Kursquellen, Index,
Audit-/Moodle-Aufträge), `adapter.py` (Adapter zur `CourseApplication`),
`preview.py` (Vorschau-Lebenszyklus und H5P-Runtime, Prewarm über
`ctx.lifecycle.on_start`), `routes.py` (alle Endpunkte unter `/api/kurse/…`,
unverändert stabil). Kurs-Einträge speist das Plugin über `ctx.index.register`
in `/api/qmds` ein; Ordneraktionen invalidieren über `ctx.index.invalidate`.

### Ansicht „Kurs-Sync“

Die Seitenleisten-Ansicht „Kurs-Sync“ (`plugins/kurse/assets/sync-view.js`, Backend
`plugins/kurse/sync_overview.py`, Endpunkt `GET /api/kurse/sync-overview`, `?refresh=1`
umgeht den Kurzzeit-Cache) zeigt je Kurs und Plattform einen gestapelten Balken: welcher
Anteil der Aktivitäten dort liegt und ob er dem lokalen Stand entspricht. Plattformen
sind das Standard-Moodle-Ziel (`.course-sync.json`), jedes benannte Moodle-Ziel
(`.moodle-target-<name>.yml` bzw. `.moodle-activity-ids-<name>.json`) und der
Website-Export unter `build/site`. „Kapitel im Einzelnen“ schlüsselt bis zur einzelnen
Aktivität auf.

Die Auswertung ist rein lokal und lesend: Sie vergleicht den aktuellen Inhalts-Hash
jeder Aktivität mit dem beim letzten Upload bzw. Export festgehaltenen. Statuswerte:
`synced` (aktuell), `changed` (seither lokal geändert), `unknown` (liegt dort, Stand
nicht erfasst), `missing` (fehlt), `excluded` (Kapitel mit `synced={false}`, zählt bei
Moodle nicht zum Soll). Für benannte Ziele und den Website-Export hält course-sync den
Stand erst seit dieser Ansicht fest (`.moodle-sync-state-<name>.json` im Kursordner,
`build/kurse/.site-export-state/<Zielordner-Hash>.json`, bewusst außerhalb des ausgelieferten Exports); ältere Uploads und Exporte erscheinen
deshalb bis zur nächsten Übertragung als „Stand nicht erfasst“, und der Grad heißt dann
„vorhanden“ statt „aktuell“. Änderungen direkt auf der Plattform erkennt nur
`inv kurse.verify-moodle` („Remote-Status prüfen“ im Kurs).

**Moodle-Ziele anlegen und bearbeiten.** Unter jedem Kurs legt „+ Moodle-Ziel hinzufügen“
ein neues Ziel an (Name und URL des Moodle-Kurses, z. B. `…/course/view.php?id=12`);
„Ziel bearbeiten“ ändert URL, Anmeldeart und Zugangsdaten eines vorhandenen Ziels
(Backend `plugins/kurse/targets.py`, Endpunkte `GET|POST /api/kurse/<slug>/moodle/targets`
und `PUT …/targets/<ziel>`). Die URL und die Anmeldeart stehen nicht geheim in
`unterricht/kurse/<slug>/.moodle-target-<ziel>.yml` (Kommentare und weitere Schlüssel
bleiben erhalten). Zugangsdaten bleiben in der lokalen, ignorierten `.env`
(`MOODLE_<KURS>_<ZIEL>_USERNAME` und `…_PASSWORD`); sie sind unter „Erweiterte
Einstellungen“ editierbar, das Passwort wird nie an den Browser zurückgegeben (leeres
Feld lässt das gespeicherte unverändert). Ohne eigene Angaben gelten die Zugangsdaten des
Kurses bzw. die Standard-Zugangsdaten aus der `.env`. Beim Speichern werden die Werte auch
in `os.environ` der laufenden Material-UI übernommen, damit Upload-Jobs sie ohne Neustart
sehen. Steht für das Ziel zusätzlich `MOODLE_<KURS>_<ZIEL>_COURSE_URL` in der `.env`,
gewinnt diese Variable über die YAML-Datei und wird deshalb mitgeändert. Bei der Auflösung
(`_resolve_moodle_course_url`) gilt für benannte Ziele: zielspezifische Variable, dann
YAML, erst danach Kurs- und Globalvariablen; sonst würde `MOODLE_<KURS>_COURSE_URL` ein
neues Ziel auf den alten Kurs lenken. Hochgeladen wird weiterhin im Kurs unter „Moodle“
mit dem Zielnamen (das Zielfeld schlägt die vorhandenen Ziele vor).

Frontend: `plugins/kurse/assets/plugin.js` registriert den Workspace-Modus `kurs`
(`ctx.workspace.registerMode` mit `entryFor`/`enter`/`leave`/`actions`), den
Pfad-Resolver für `unterricht/kurse/**` (`ctx.documents.registerPathResolver`) und
die Seitenleisten-Ansicht „Kurse“. Die Kurs-Steuerung liegt in
`plugins/kurse/assets/courses.js` (im Manifest unter `modules` deklariert). Der Kern
schaltet über `setChrome` nur die Slots um (Toolbar, Editor-Shell, Kurs-Pane);
`state.course.kursMode` bleibt als Flag für bestehende Zweige (Editor-Save,
Entwürfe, Shortcuts, Chat-Kontext). `loadPlugins` wird in `init()` vor `loadQmds()`
awaited, damit Modi und Resolver beim ersten Öffnen bereitstehen. Der Desktop-Starter
reicht Kurs-MDX unverändert als `?path=` durch; die Auflösung übernimmt der
registrierte Resolver. Abschaltbar über `inv plugin-disable kurse` (nach Neustart
entfallen Kurs-Routen, Kurs-Einträge im Index und die Kurs-Ansicht).

## Wissen-Plugin (`wissen`)

Das eingebaute Plugin `wissen` zeigt das Kompetenzraster und die Abdeckung pro
Fach/Klasse (read-only). Datenquellen: `wissen/kompetenzraster/<fach>/`
(Curriculum `klasse-XX.md`, Teilkompetenzen `teilkompetenzen/*.md`) sowie die
Verknüpfungen aus `einheit.yaml` (`kompetenzen: [{id, stufe}]`) und QMD-Frontmatter
(`kompetenzen: [id, …]`) unter `unterricht/<fach>/klasse-XX/`. Backend:
`plugins/wissen/service.py` (lädt und joined Raster + Einheiten, Cache über
mtime-Signatur), `routes.py` (Endpunkte unter `/api/wissen/…`: `overview`,
`raster/<fach>/<klasse>`, `abdeckung/<fach>/<klasse>`, `validate/<fach>/<klasse>`).
Frontend: `plugins/wissen/assets/plugin.js` registriert die Seitenleisten-Ansicht
„Wissen“ (`ctx.views.register`, Icon `book`) mit den Tabs Abdeckung, Kompetenzen
und Curriculum. Tests: `src/tests/test_material_ui_wissen.py`.

Abdeckung und Kompetenzliste folgen den Themen und Unterthemen des Curriculums.
Pro Unterthema werden behandelte und geprüfte Kompetenzen sowie Leerstellen
ausgewiesen. Kompetenzen anderer Klassen erscheinen nur bei ausdrücklicher
Curriculum-Zuordnung; ohne Klassenangabe bleiben sie klassenübergreifend sichtbar.
Die Auswahl im Einheiteneditor bietet weiterhin alle IDs des Fachs an. Zugeordnete
Kompetenzen anderer Klassen erscheinen mit einem Hinweis außerhalb des Klassenrasters.
`halbjahreswechsel_nach` verweist auf die Themen-ID nach dem ersten Halbjahr;
die Grenze erscheint in allen drei Ansichten zusammen mit `halbjahresziel` und
`hj_grenze`. Ohne explizite Zuordnung wird keine Grenze geschätzt.
Die Abdeckung fasst alle Schuljahre zusammen und ist kein individueller
Kompetenznachweis. Im Einheiteneditor können Zuordnungen und Unterrichtsstufen
mit Revisionsprüfung gespeichert werden. Die Ansicht aktualisiert sich bei Aktivierung
und Einheitenänderungen; verspätete Antworten früherer Auswahlen werden verworfen.
QMDs in Unterordnern gehören zur nächsten übergeordneten Einheit. Fehlende Einheiten
und unlesbare Quellen werden unter `quellfehler` gemeldet, verhindern `validate.ok`
und erscheinen als Warnung in der Ansicht.

## Druck-Plugin (`druck`)

Das Plugin `druck` (Ansicht „Druck“: gedruckte Arbeitsblätter, Stückzahlen, hängende Aufträge
aus CUPS) ist kein eingebautes Plugin, sondern liegt in einem Plugin-Katalog
und wird im Marketplace-Dialog installiert. Es setzt Material-UI-API 4 voraus (u. a.
`ctx.documents.open`) und braucht `pycups` (Systempaket `python-pycups`). Beschreibung,
Zuordnungsregeln und Tests stehen im README des Katalogs.

## Chat-Plugin (`chat`)

Das eingebaute Plugin `chat` liefert das komplette Chat-Panel; der Kern kennt keine
Chat-Logik mehr. Backend: `plugins/chat/service.py` (Sitzungen, `ChatService`),
`providers.py` (Claude/Codex/Vibe-CLI als Subprozesse), `tools.py` +
`mcp_server.py` (MCP-Stdio-Server mit den Werkzeugen `search_wissen`,
`search_unterricht`, `read_file`, `propose_document_edit`, `show_task_image`),
`routes.py` (alle Endpunkte unter `/api/chat/…`, unverändert stabil). Der MCP-Server
läuft als eigener Subprozess (`python -m chat.mcp_server`, PYTHONPATH auf das
Plugin-Suchverzeichnis) und liest das Aufgabenbild für `show_task_image` per HTTP
von der Route `GET /api/document/import/task-image/<token>/image` des
`importe`-Plugins — so importiert der Subprozess kein fremdes Plugin.

Das Plugin stellt das Interface `chat` bereit (`provides: ["chat"]`,
`ctx.register_service("chat", service)`); andere Plugins (z. B. `importe`) holen
sich den Dienst per `ctx.service("chat")`. Frontend: `plugins/chat/assets/plugin.js`
verdrahtet das Chat-Dock (HTML-Slot im Kern-Template) mit
`assets/chat-panel.js` (im Manifest unter `modules`) und meldet den Controller
beim Kern an (`deps.registerController("chat", …)`); der Kern blendet den
Chat-Knopf aus, wenn das Plugin nicht geladen ist. Abschaltbar über
`inv plugin-disable chat`.

### Chat-Verhalten und Bedienung

- **Antworten** werden als Markdown dargestellt (`assets/markdown.js`: Absaetze, Ueberschriften,
  Listen, Zitate, Codebloecke, `code`, fett, kursiv, `http(s)`-Links). Der Renderer baut nur DOM-Knoten
  und interpretiert nie HTML aus dem Modelltext; unsichere Links (`javascript:` u. a.) bleiben Text.
- **Werkzeugaufrufe** erscheinen als einklappbare Zeilen („Wissensbasis durchsuchen“ …). Fehlgeschlagene
  Werkzeuge sind rot und aufgeklappt, eingebaute CLI-Werkzeuge (Shell, Dateizugriff in der Sandbox) tragen
  den Zusatz „CLI-Werkzeug“, internes Rauschen (`search_tool_functions`) wird ausgeblendet. Treffer von
  `search_wissen`, `search_unterricht` und `read_file` stehen als Liste darunter; Unterrichtsmaterial
  (`unterricht/…qmd|md|tex`) laesst sich per Klick im Editor oeffnen.
- **Aenderungsvorschlaege** (`propose_document_edit`) zeigen einen Zeilenvergleich (`assets/diff.js`,
  lange unveraenderte Strecken eingefaltet). Bei mehreren Vorschlaegen einer Antwort uebernimmt
  „Alle n Aenderungen uebernehmen“ sie nacheinander; jede Aenderung bleibt mit Strg+Z rueckgaengig.
- **Abbrechen** beendet nur die laufende Antwort (`POST /api/chat/sessions/<id>/cancel`); Sitzung,
  Kontext und Verlauf bleiben erhalten (mit der echten Claude-CLI geprueft: Die Sitzung laeuft nach dem
  Abbruch fehlerfrei weiter und kennt die gestellte Frage; der abgebrochene Teil der Antwort ist dem Modell
  aber nicht bekannt). „Neuer Chat“ schliesst die Sitzung und loescht den Verlauf.
- **Verlauf nach Neuladen:** Nutzer- und Antworttexte sowie Sitzungs-ID, Provider und Modell liegen
  unter `material-ui:chat-state` im `localStorage` des Browsers (max. 60 Nachrichten bzw. 120 000
  Zeichen; keine Dokumentinhalte, Werkzeugdaten oder Aenderungsvorschlaege). Ist die Sitzung auf dem
  Server abgelaufen, startet die naechste Nachricht automatisch eine neue (einmaliger Hinweis). Der
  Verlauf kann Unterrichtsinhalte enthalten; er verschwindet mit „Neuer Chat“ oder durch Loeschen der
  Browserdaten.
- **Sitzungen** laufen nach 60 Minuten ohne Aktivitaet ab (`IDLE_SESSION_SECONDS`); eine laufende Antwort
  wird nie abgeraeumt.
- **Zeitlimits:** Eine Runde endet nach 120 s ohne jede Ausgabe der CLI (`timeout_seconds`, Inaktivitaet)
  oder spaetestens nach 900 s (`max_seconds`); eine streamende Antwort wird also nicht mehr nach
  einer festen Zeit abgeschnitten. Meldet eine CLI Fehler im Klartext (z. B. abgelaufene Anmeldung,
  Rate-Limit) oder beendet sich mit Exit-Code ≠ 0, steht die Meldung im Chat statt einer leeren Antwort.
- **Modellwahl:** `GET /api/chat/providers` liefert je Provider `models`; `POST /api/chat/sessions`
  nimmt `model` an (nur Eintraege aus der Liste, sonst 400). Claude: Aliase aus `CLAUDE_MODELS`
  (Standard `sonnet,opus,haiku`; das erste ist der Standard) mit Denkaufwand: im Chat unter „Einstellungen“ wählbar (niedrig/mittel/hoch, ohne Neustart; `POST /api/chat/sessions` nimmt `effort`),
  Standard aus `CLAUDE_EFFORT` (`low|medium|high|xhigh|max`, vorgabe `medium`), Codex: `CODEX_MODEL` plus `CODEX_MODELS` (kommagetrennt); Vibe
  kennt keine Modelloption auf der Kommandozeile (Modell steht in der Vibe-Konfiguration). Ohne
  Auswahlliste blendet das Panel die Modellauswahl aus; ein Wechsel startet eine neue Sitzung.
- **Dokumentkontext:** Mit Markierung gehen nur der Abschnitt und je 1500 Zeichen Umgebung an die CLI;
  ohne Markierung wird das ganze Dokument nur gesendet, wenn es sich seit der letzten Nachricht der
  Sitzung geaendert hat (sonst ein Hinweis „unveraendert“). Nach einer fehlgeschlagenen Runde wird
  wieder der volle Text gesendet. Die Eingabe wird in jedem Fall vollstaendig geprueft.
- **Mistral-Nutzung** wird 60 s (Fehler 30 s) zwischengespeichert, Abfrage-Timeout 3 s.
- **Regeln und Pruefung:** Mit Dokumentkontext gibt der Chat dem Modell einmal pro Sitzung und Dokumentart
  die Projektregeln mit (`plugins/chat/rules.py`: Arbeitsblatt, Mini-AB, Loesung, Folien, Material; Kurzfassung
  der CLAUDE.md). Das MCP-Werkzeug `check_document(path, text)` prueft Text mit `material_core.conventions`
  (nur mechanisch erkennbare Regeln; Kopf-Regeln wie Untertitel nur bei vollstaendigem Text). Jede
  Vorschlagskarte zeigt ausserdem die durch die Aenderung **neu** entstehenden Regelhinweise
  (`POST /api/chat/check` mit `old_text` als Vergleichsbasis) und faerbt sich bei Verstoessen.
- **Weitere Werkzeuge:** `read_unit` (einheit.yaml und Dateiliste der Einheit), `list_templates`
  (Vorlagenkatalog) und `propose_new_document(path, text)`. Neue Dateien entstehen nur auf Klick
  („Datei anlegen“ -> `POST /api/chat/documents`): nur unter `unterricht/`, nur `.qmd/.md/.tex`, keine
  versteckten Pfade, nie ueberschreibend (409), Ordner werden bei Bedarf angelegt. Die Antwort nennt
  unter `render.job_id` den gestarteten Render-Lauf (ueber `ctx.render`, Notizen ausgenommen); die
  Vorschlagskarte pollt `/api/jobs/<id>` und zeigt „Render läuft …“, bei Erfolg einen „PDF öffnen“-Link
  bzw. bei Fehlern Meldung und Protokoll-Ausschnitt. Geprueft werden zunaechst die Regeln
  (`/api/chat/check`), das Rendering läuft direkt im Anschluss ueber die zentrale Warteschlange.
- **Schnellaktionen:** Chips ueber dem Eingabefeld je Dokumentart (Konventionen pruefen, Loesung erstellen,
  AFB kennzeichnen, Parallelversion, Mini-AB, Folien kuerzen ...) senden sofort; `/` oeffnet dieselben
  Aktionen als Menue und fuellt nur das Eingabefeld. Eigene Prompts stehen unter „Eigene Prompts“
  (`Titel [Art,Art] | Prompt`, `GET/PUT /api/chat/prompts`, gespeichert im Plugin-Zustand).
  Mit ↑/↓ blaettert man durch fruehere Nachrichten des Chats.
- **Kontext waehlen:** `@Suchbegriff` im Eingabefeld sucht Dateien (Unterricht/Wissen) und haengt bis zu
  5 an die naechste Nachricht an (das Modell liest sie bei Bedarf mit `read_file`). Gehoert die offene
  Datei zu einer Einheit, nennt der Prompt sie einmal und `read_unit` liefert die Details.
- **Mehrere Chats:** „Neuer Chat“ legt einen weiteren Chat an (Auswahlliste, je Chat eigene Sitzung,
  Provider und Modell; bis 20 Chats), „Chat loeschen“ schliesst Sitzung und Verlauf. Das aeltere
  Einzelformat (`material-ui:chat-state`) wird uebernommen.
- **Antwortaktionen:** Kopieren (Rohtext), „Neu erzeugen“, „Frage bearbeiten“. Ist ein Vorschlag veraltet,
  bietet die Fehlermeldung „Auf aktuellem Stand neu anfordern“ an.
- **Quellen:** Treffer aus Wissens-PDFs oeffnen das PDF an der gefundenen Seite in einem neuen Tab
  (`GET /api/chat/source?path=wissen/….pdf#page=N`, nur PDFs unter `wissen/`).
- **Darstellung:** Tabellen und Formeln (`$…$`, `$$…$$`, `\(…\)`; Hoch-/Tiefstellung, Bruch, Wurzel,
  Griechisch, gaengige Zeichen; kein vollstaendiges TeX, unbekannte Befehle bleiben sichtbar). Die Breite
  des Docks laesst sich am linken Rand ziehen (Pfeiltasten, Doppelklick = 340 px; 280 bis 720 px).
- **Datenschutz:** Die Kontextzeile nennt den Empfaenger der Daten (Anthropic, OpenAI, Mistral AI). Bei Dateien
  in Klausurordnern (`klausur*`) fragt der Chat je Chat und Datei einmal nach, bevor Inhalt gesendet wird.
- Der Aufgabenbild-Chat (`importe`) bleibt eigenstaendig: Sein Modelltext fliesst als Code ins Codefeld,
  seine Chatzeilen sind nur Statusmeldungen.
- Tests: `src/tests/test_chat_improvements.py` und `test_chat_features.py` (Backend), `test_chat_frontend_modules.py`
  (Node, reine Module), `test_chat_browser.py` (Playwright).

## Office-Plugin (`office`) und OCR-Plugin (`ocr`)

Beide sind ab Werk aus. `office` kapselt LibreOffice und Pandoc (`plugins/office/converter.py`),
stellt dem Plugin `importe` das Interface `docx-converter` bereit und ist Voraussetzung fuer
`inv import-onlyoffice`. `ocr` kapselt die Aufrufe von Tesseract und Ghostscript
(`plugins/ocr/engine.py`); die Wissensbasis nutzt sie, und `inv wissen-ocr`,
`wissen-komprimieren` sowie `wissen-update --ocr/--komprimieren` verlangen das aktivierte Plugin.
Der Zustand wird ausserhalb des Servers ueber `material_core/plugin_state.py` gelesen.

## Importe-Plugin (`importe`)

Das eingebaute Plugin `importe` liefert die Import-Workflows Office (PDF/DOCX →
QMD-Arbeitsblatt; DOCX nur mit aktivem Plugin `office`) und Aufgabenbild (Zwischenablage-Bild → Code): Backend
`plugins/importe/office_import.py`, `task_image_import.py`, `office_routes.py` und
`task_image_routes.py` (Endpunkte unter `/api/document/import/office/…` und
`/api/document/import/task-image/…`, unverändert stabil, inkl. der Bild-Route
`/image` für den MCP-Client des `chat`-Plugins). Der KI-Umbau gestagter Inhalte
läuft über das Interface `chat` (`dependsOn: {"@chat": ">=0.1.0"}`); ohne aktives
Chat-Plugin antwortet der Draft-Endpunkt mit 400 und erklärender Meldung. Frontend:
`plugins/importe/assets/plugin.js` verdrahtet die beiden Modals (HTML-Slots im
Kern-Template) mit `assets/office-import.js` und `assets/task-image-import.js`
(beide unter `modules`) und meldet die Controller beim Kern an; der Kern blendet
den Office-Import-Knopf aus und behandelt eingefügte Bilder ohne Plugin nur noch
als Bild. Abschaltbar über `inv plugin-disable importe`.

## Kalender und Agenda (Plugin `kalender`)

Frontend-Aufbau (`plugins/kalender/assets/`): `plugin.js` enthaelt nur `register(ctx)`; die Teile
liegen in Modulen, die alle unter `modules` im Manifest stehen (nur dort genannte Dateien werden
ausgeliefert): `store.js` (gemeinsamer Zustand, auch `statusLine` und `todayHandle`),
`format.js` (reine Datums-/Chip-Hilfen), `sync.js` (Laden, Abgleichstatus), `settings.js`
(Einstellungen, Sichtbarkeit), `event-form.js` (Termin anzeigen/anlegen), `views.js`
(Monat/Agenda), `today.js` (Heute-Seite). Veraenderlicher Zustand gehoert in `store`
(ein exportiertes `let` liesse sich in anderen Modulen nicht setzen). Neue Module muessen im
Manifest eingetragen werden; `src/tests/test_kalender_modules.py` prueft Manifest, Importnamen
und Dateigroesse (< 500 Zeilen je Modul).

Das eingebaut ausgelieferte Plugin liefert zwei Ansichten auf denselben synchronisierten
Daten: ein Monatsraster (Monatsnavigation, „Heute“, Ganztages-Chips, Tagesliste bei
Zellklick, Termindialog mit Ort und Beschreibung) und eine Agenda (7/14/30/90 Tage ab
Heute oder Sprungdatum, Tag-Gruppen mit Zaehler, Termindialog). Ohne CalDAV-Konto zeigt
die Ansicht den Einrichtungshinweis und oeffnet direkt den Einstellungsdialog; ohne
Netz bleibt der letzte Cache lesbar.

Einstellungen (`GET`/`POST /api/plugins/kalender/settings`): Konten als Liste von
`{label, url, username, password, calendars}` (Kalenderauswahl leer = alle), Zeitzone
(Standard `Europe/Berlin`), `syncIntervalMinutes` (0 = kein Hintergrundabgleich),
Abgleichfenster (`windowPastDays`/`windowFutureDays`). `POST /api/plugins/kalender/sync`
startet einen Auftrag im exklusiven Kanal `kalender-sync` (parallele Starts antworten mit
409): je Konto ein `caldav.DAVClient` mit 15-Sekunden-Timeout, `date_search` im Fenster,
Expandierung von Serien und Ausnahmen ueber `recurring-ical-events`; die normalisierten
Termine (Schluessel `uid@start`, ganztägige Enden inklusiv) landen unter
`.material-ui/plugins/kalender/cache.json`, der Abgleichstand unter `status.json`.
`GET events?from&to` liest ausschliesslich den Cache, `GET status` meldet Konto- und
Abgleichstand, `GET calendars` entdeckt die Kalender der Konten. Der optionale
Intervall-Worker wartet mit kurzem Takt auf `runtime.closing` und zaehlt das Faelligkeitsdatum
selbst, damit der geordnete Shutdown nicht auf den vollen Intervallturnus wartet. Die
Abhaengigkeiten kommen als Extra: `pip install -e '.[kalender]'` (`caldav`,
`recurring-ical-events`); fehlt das Extra, meldet der Plugin-Status die fehlende
Abhaengigkeit mit Installationshinweis statt eines nackten Importfehlers.

Bei fehlgeschlagenen Konten bleiben deren zuletzt geladene Termine und Kalender
im Cache erhalten; erfolgreiche Konten werden weiterhin aktualisiert. Bei
aktiviertem automatischem Abgleich wird ein fehlender oder überfälliger Abgleich
sofort im Hintergrund nach dem Start nachgeholt. Die Ansicht zeigt währenddessen
die gespeicherten Termine. Ein späterer gespeicherter Termin bleibt erhalten. Bei
vorübergehenden Netzwerk- oder Serverfehlern folgen bei aktiviertem automatischem
Abgleich Wiederholungen nach 1, 5 und 15 Minuten (jeweils nach dem letzten Versuch),
danach gilt wieder das normale Intervall. Anmeldefehler lösen keine schnellen
Wiederholungen aus. Mit `syncIntervalMinutes: 0` sind auch automatische Wiederholungen
ausgeschaltet; ein manueller Abgleich bleibt möglich. Der Status zeigt den letzten
erfolgreichen Abgleich und die nächste Fälligkeit; geöffnete Ansichten aktualisieren
sich alle 2 Sekunden. Logs enthalten Fehlertyp und Wiederholbarkeit, keine rohen
DAV-Fehlermeldungen mit möglicherweise enthaltenen Zugangsdaten.

## Erinnerungen-Plugin (`erinnerungen`)

Desktop-Benachrichtigungen bei geschlossener UI als eigenes Plugin mit
`"dependsOn": {"@calendar": ">=0.3.0"}`: Termine, TODOs und Zeitzone kommen ueber das
Interface `ctx.service("calendar")` (`events(from, to)`, `tasks()`, `timezone()`),
nicht direkt ueber das Kalender-Plugin. Ein Hintergrund-Worker (Takt 30 s,
`ctx.workers`) prueft ueber `ctx.windows.live_count()`, ob ein App-Fenster offen ist;
ist keines offen, sendet er pro Tag einmal `notify-send` (ohne `notify-send` nur
Log) fuer Termine, die im Vorlauffenster beginnen, und fuer heute faellige TODOs
(Dedup über `reminders.json` im Plugin-Speicher, 7 Tage Aufbewahrung). Feiertage,
ausgefallene Stunden und erledigte TODOs werden nicht erinnert. Einstellungen liegen
im eigenen Plugin-Speicher (`desktopReminders`, Standard an; `reminderMinutes`,
Standard 15) und sind ueber die Aktion „Erinnerungen“ in der Kalender-/Agenda-
Werkzeugleiste erreichbar (`GET/POST /api/plugins/erinnerungen/settings`,
`GET /api/plugins/erinnerungen/status` mit `sentToday`). Die Benachrichtigung trägt
App-Name „Material-UI“ und Icon (`notify-send --app-name=… --icon=…`), als Text den
Titel plus relevante Angaben: beim Termin Uhrzeit, Ort und Kalender, beim TODO
„Heute fällig“ bzw. „Heute eingeplant · fällig am …“ samt verknüpfter Unterrichtsstunde.
Reine Logik und Benachrichtigung sind in `plugins/erinnerungen/reminders.py` getrennt
(``due_reminders`` / ``ReminderNotifier``, ``notify`` zum Testen austauschbar).

## Suche, Git und Oberfläche


`GET /api/search?q=...&subject=...&grade=...&kind=...&tags=...` durchsucht alle QMD-Quellen
einschließlich Frontmatter im Volltext. Umlaute werden bei der Suche normalisiert,
alle Begriffe müssen vorkommen. `tags` nimmt eine kommagetrennte Liste; ein
Treffer muss alle genannten Tags im Frontmatter tragen. Die Antwort liefert
höchstens 50 Treffer mit
Pfad, Titel, Trefferzeile, Kurzausschnitt und Score; die Facet-Filter greifen
auf die indexierten Metadaten. Ohne Suchbegriff und Filter antwortet die Route
mit `400`. Die Materialauswahl im Frontend fragt sie ab drei Zeichen mit 300 ms
Verzögerung ab und sortiert Volltext- und Metadatentreffer gemeinsam. Volltexttreffer
tragen eine Zeilenangabe und ein „Volltext“-Badge; bereits gelistete Pfade werden
zusammengeführt. Zusätzlich unterstützt die API `pdf`, `area`, `solution` und
`sort` (`relevance`, `title`, `recent`).

`GET /api/document/git?path=...` liefert Status, Diff (maximal 64 KiB) und den
letzten Commit der Datei aus dem Repository-Git. Ohne Git-Repository antwortet
die Route mit `available: false` statt eines Fehlers. Der Dialog „Git“ unter den
erweiterten Optionen zeigt anstehende Änderungen vor dem Commit.

Im Header sind Hell, System und Dunkel gleichzeitig als direkt wählbare Optionen sichtbar;
die Wahl wird in `localStorage` gespeichert. Im Editor öffnet die Eingabe von
`[` gefolgt von mindestens zwei Zeichen eine Baustein-Autocomplete-Liste; Pfeiltasten,
Tab und Enter wählen, Escape schließt. Warnzeilen aus der Renderausgabe
(LaTeX-, Paket-, Typst- und Overfull-Hinweise, höchstens 20) werden im
Renderprotokoll gesondert gesammelt; Zeilennummern im Protokoll sind anklickbar
und springen im Editor zur Stelle, auch in gefalteten Abschnitten.

## Chat

Das Chat-Panel liegt im eingebauten Plugin `chat` (`plugins/chat/`, siehe
„Chat-Plugin (`chat`)“); der Kern stellt nur noch das Dock (HTML-Slot) und den
Header-Knopf bereit und blendet beides aus, wenn das Plugin deaktiviert ist. Der
Chat verbindet drei austauschbare
Modell-Provider — Claude, Codex, Mistral (Vibe) — jeweils über deren lokal
eingeloggte Abo-CLI (`claude`, `codex`, `vibe`) als Subprozess; es gibt dafür
keine eigenen API-Keys oder ein separates Billing. `GET /api/chat/providers`
meldet je Provider `available` (CLI gefunden, per `shutil.which`) und einen
`usage_hint` (nur Mistral liefert echte Kontingentdaten über die
Mistral-Admin-API, `MISTRAL_ADMIN_API_KEY` vorausgesetzt; Claude/Codex
verweisen nur auf `/usage` bzw. `/status` in der jeweiligen CLI). `POST
/api/chat/sessions` legt eine Sitzung für einen Provider an, `POST
/api/chat/sessions/<id>/messages` sendet eine Nachricht und liefert die
Antwort als SSE-Stream (`text`/`tool_call`/`tool_result`/`done`/`error`), `DELETE
/api/chat/sessions/<id>` beendet sie samt Subprozess.

Der Chat sendet bei jeder Nachricht den Pfad und den aktuellen Editorinhalt
(einschließlich ungespeicherter Änderungen, maximal 200 KB) der geöffneten
QMD-/Markdown-/LaTeX-Datei mit. Die Kontextzeile zeigt die aktuelle Datei an.
`propose_document_edit(path, old_text, new_text)` schlägt einen eindeutigen
Textersatz vor. Im Chat erscheinen Vorher/Nachher und „Änderung übernehmen“.
Die Übernahme erfolgt als rückgängig machbare Editoränderung; die bestehenden
Auto-Speichern-/Auto-Render-Einstellungen gelten weiterhin. Wurde die Datei
inzwischen gewechselt oder bearbeitet, wird die Übernahme abgelehnt.
Ohne geöffnetes Dokument bleibt die Wissenssuche verfügbar.

Codex erscheint in der Provider-Auswahl, sobald `codex` im Suchpfad liegt
(alternativ `CODEX_BIN` in `.env`). Installation für das Benutzerkonto:
`npm install -g --prefix ~/.local @openai/codex`; `~/.local/bin` muss im
Suchpfad der Material-UI liegen. `codex login` verbindet das ChatGPT-Konto;
`codex login status` prüft die Anmeldung. Der Chat nutzt standardmäßig
`gpt-6.1-sol`; `CODEX_MODEL` in `.env` überschreibt die Modellauswahl für
die Material-UI. Die globale Codex-Konfiguration wird dabei nicht verändert.
Dokumentinhalt wird über stdin übergeben. Die MCP-Konfiguration mit dem
Projektpfad und der aktuellen App-URL gilt jeweils nur für den einzelnen Aufruf.
Codex-Antworten, Änderungsvorschläge und fortgesetzte Sitzungen werden über
die JSONL-Ereignisse von `codex exec` verarbeitet. Die Such-, Lese- und
Vorschlagswerkzeuge deklarieren ihre fehlenden Schreibnebenwirkungen per
MCP-Annotation, damit sie auch ohne interaktive CLI-Freigaben nutzbar sind.

Ist im Editor Text markiert, zeigt die Kontextzeile „Nur markierter Abschnitt“.
Die Markierung beim Senden begrenzt die Änderungsvorschläge; der Rest des Blatts
dient als Kontext. Auch die Übernahme prüft diese Grenze. Mehrere Vorschläge
derselben Antwort berücksichtigen bereits übernommene Änderungen an der Markierung.
„Antwort abbrechen“ beendet den Stream und die zugehörige CLI-Sitzung samt
Subprozess. Der sichtbare Verlauf bleibt erhalten; die nächste Nachricht beginnt
eine neue Sitzung. „Neuer Chat“ beendet ebenfalls eine laufende Antwort und leert
Verlauf und Eingabefeld. Das Dokument bleibt dabei erhalten.

Jede CLI bekommt die Such-, Lese- und Vorschlagswerkzeuge über einen eigenen, pro Sitzung
gestarteten MCP-Server (`chat/mcp_server.py`, stdio): `search_wissen`
(Volltextsuche über `build/material-index.json`, siehe `inv material-index`),
`search_unterricht` (ruft die laufende Material-UI selbst über `/api/search`
auf) und `read_file` (nur unterhalb `wissen/`/`unterricht/`, siehe
`chat/tools.py:safe_knowledge_path`). Diese drei Werkzeuge pruefen ihre
Pfadgrenze selbst und unabhaengig davon, welche CLI sie aufruft — das ist
gegen alle drei CLIs real verifiziert (u. a. ein `mcp_wissen.read_file`-Aufruf
ausserhalb `wissen/`/`unterricht/` wird vom MCP-Server selbst mit "Pfad liegt
ausserhalb des Projekts" abgelehnt).

**Dateisystem-Sandbox fuer Codex und Vibe:** Nur bei Claude lassen sich die eingebauten
Dateisystem-/Shell-Werkzeuge der CLI abschalten (`--restricted --allowedTools/--tools` nur
auf die MCP-Werkzeugnamen). Codex (`--sandbox read-only` schraenkt nur Schreib-/Netzzugriff
ein, `--add-dir` macht Ordner schreibbar) und Vibe (`--enabled-tools`/`--disabled-tools`
blockieren `file_system.bash` nicht zuverlaessig) behalten sie. Deshalb starten beide ihre
CLI innerhalb von **bubblewrap** (`plugins/chat/sandbox.py`):

- Wurzel-Dateisystem nur lesend (`/usr`, `/etc`, ...), `$HOME` ist ein leeres tmpfs.
- Sichtbar sind nur `wissen/`, `unterricht/`, der Suchindex `build/material-index.json`,
  der Quellbaum und Python fuer den MCP-Server, die Installation der CLI selbst
  (nur lesend) sowie ihr Konfigurationsordner `~/.codex` bzw. `~/.vibe` (schreibbar,
  wegen Token-Aktualisierung und Sitzungen). `foerderempfehlungen/`, `.git`, `.env`,
  `~/.ssh`, `~/.gnupg`, `~/.git-credentials` usw. existieren in der Sandbox nicht.
- Die Umgebung wird geleert; durchgereicht werden nur `PATH`, `LANG`/`LC_*`, Proxy-/CA-
  Variablen, die MCP-Variablen und providerspezifische Praefixe (`OPENAI_`/`CODEX_`
  bzw. `MISTRAL_`/`VIBE_`). `MISTRAL_ADMIN_API_KEY` bleibt immer draussen.
- Das Netz bleibt offen (Modell-API, lokale Material-UI fuer `propose_document_edit`).

Gegen die echten CLIs geprueft (codex-cli 0.160, vibe 3.0.2): `cat ~/.gitconfig` und
`ls ~/.gnupg` ueber das eingebaute Shell-Werkzeug scheitern mit „nicht gefunden“, die
drei MCP-Werkzeuge laufen unveraendert. Ohne `bwrap` (Paket `bubblewrap`) sind Codex und
Vibe **gesperrt**: `/api/chat/providers` meldet `blocked` mit Begruendung, die UI
zeigt sie als „gesperrt“ und `POST /api/chat/sessions` antwortet mit 400. Wer das
bewusst anders will, setzt `MATERIAL_UI_CHAT_ALLOW_UNSANDBOXED=1` (unsicher: die CLI
darf dann alles lesen). Restrisiko: Das Modell kann in der Sandbox den Token der CLI
(`~/.codex/auth.json`, `~/.vibe`) lesen; Netzzugriff und Material in `wissen/`/`unterricht/`
bleiben bewusst erreichbar. Tests: `src/tests/test_chat_sandbox.py` (u. a. echte
bwrap-Laeufe, werden ohne bwrap uebersprungen).

`chat/providers.py` kapselt die Subprozess-/Watchdog-Logik (Timeout, `SIGKILL`
über Prozessgruppe, genau ein laufender Turn pro Sitzung) in
`CliChatProvider`. `ClaudeCliProvider` und `VibeCliProvider` sind gegen die
echten CLIs end-to-end verifiziert (Mehrturn-Sitzungen mit `--resume`,
echte Tool-Aufrufe). `CodexCliProvider`s Flags sind gegen `codex --help`/
`codex exec --help` (Version 0.160.1) korrigiert, ein vollstaendiger
Live-Testlauf scheiterte am Nutzungslimit des Testaccounts (nur Fehlerpfade
verifiziert) — bleibt `experimental=True`. `vibe` ist nicht Teil der
Projekt-Python-Umgebung: `mistral-vibe` verlangt `mcp==1.28.1` (exakt
gepinnt), unser `chat/mcp_server.py` braucht `mcp>=2` (`MCPServer`/`ToolError`
existieren erst dort) — ein direktes `pip install mistral-vibe` ins
Projekt-venv wuerde `mcp` stillschweigend auf 1.x zurückstufen und
`mcp_server.py` brechen. `vibe` deshalb in einem eigenen, isolierten venv
installieren (z. B. `python3 -m venv ~/.local/share/mistral-vibe-venv &&
~/.local/share/mistral-vibe-venv/bin/pip install mistral-vibe`) und nur das
`bin/vibe` daraus auf den `PATH` verlinken (oder `VIBE_BIN` in `.env` auf den
vollen Pfad setzen).

## Suche und Prüfhinweise

Die Volltextsuche bewertet alle passenden QMDs und Decks, bevor sie die besten
50 Treffer zurückgibt. Fach, Klasse, Typ, Tags, PDF-Status und Filterchips gelten
auch für Volltexttreffer; Metadaten- und Volltexttreffer werden gemeinsam sortiert.
Beim Ändern der Suche werden laufende Anfragen abgebrochen und verspätete
Antworten verworfen. Umlaute sind auch über ae/oe/ue auffindbar.

Ein an die Repository-Instanz gebundener Textindex hält bis zu 64 MiB an
Quelltext und normalisiertem Suchtext im Speicher. Jede Suche prüft Dateistand,
neue Quellen und gelöschte Dateien; nur geänderte Inhalte werden erneut gelesen
und ausgewertet. PDF-Dateien werden unabhängig davon auf Existenz geprüft.
`build/`, `h5p/`, `node_modules/` und das Root-Archiv werden nicht durchlaufen.
Erzeugte Decks werden gezielt über ihre QMD-Quellen unter
`build/artefakte/<Quellpfad>.excalidraw` gefunden. Sie übernehmen Fach, Klasse und
Tags ihrer Quelle. Der Index ist nach einem Serverneustart regenerierbar.

QMD-Prüfungen laufen 600 ms nach einer Editoränderung auf dem aktuellen,
gegebenenfalls ungespeicherten Text. `POST /api/check` akzeptiert dafür neben
`path` optional `text`; die Prüfung schreibt keine Datei. Fehlende Bilder und
Vorlagen, fehlende oder ungültige Metadaten sowie der PDF-Status erscheinen als
Markierungen im Editor und in einer anklickbaren Liste darunter. „Prüfen“ öffnet
die Liste direkt. Ungültiges YAML wird mit Quellposition gemeldet. Änderungen
und Dokumentwechsel verwerfen veraltete Markierungen und Antworten.
Vor jedem manuellen oder automatischen Rendern wird der aktuelle Editorinhalt
geprüft. Fehler sperren das Rendern und öffnen die Hinweisliste; Warnungen
blockieren nicht. Die Vorprüfung erkennt auch nicht geschlossene Codeblöcke,
`$$`-Formeln und falsch verschachtelte oder offene LaTeX-Umgebungen. Codebeispiele,
Inline-Code und HTML-Kommentare werden dabei ausgeblendet. SVG-Dateien, die der
Build aus lokalen TikZ-Quellen erzeugt, gelten nicht als fehlend.
Der Server prüft zusätzlich vor dem Anlegen eines Render-Auftrags
(`422 preflight_failed` mit `issues`) und erneut beim Abarbeiten der Warteschlange.
Die Vorprüfung startet keinen Compiler und schreibt keine Datei. Fehler in
beliebigem LaTeX-/Typst-Code oder in externen Werkzeugen können weiterhin erst
beim Rendern erkannt werden.
Renderprotokolle werden nur dann im Editor markiert, wenn sie QMD-Quellzeilen
der passenden Revision enthalten; Zeilen erzeugter TeX-/Typst-Dateien werden
ohne Quellzuordnung nicht auf QMD-Zeilen übertragen.

## Datenintegrität

Dokument- und Aktivitätsantworten enthalten `revision`, einen SHA-256-Wert des
Textes. Der Browser sendet diese Revision beim Speichern zurück. Eine inzwischen
veränderte Datei führt zu `409 Conflict`; der Editor behält seine Änderungen.
Änderungen während eines laufenden Speicherns werden anschließend erneut
gespeichert. Verspätete Antworten einer anderen Dokumentsitzung werden verworfen.
Clients ohne `revision` bleiben kompatibel, verzichten aber auf Konflikterkennung.

Enthält die Datei beim `409` bereits eine eigene Fassung — der aktuellen
Editorfassung, der zuletzt geschriebenen Fassung oder einer Fassung derselben
Speicherfolge — löst der Editor den Konflikt selbst auf: Er übernimmt die
Dateirevision und wiederholt das Speichern einmal. Das Wiederherstellungsfenster
mit Fassungsvergleich erscheint nur noch, wenn die Datei eine fremde Fassung
enthält, etwa aus einem zweiten Fenster oder einem externen Programm.

Neue Dokumente werden atomar ohne Überschreiben veröffentlicht; konkurrierendes
Anlegen desselben Pfads liefert `409 Conflict`. Speichern erhält die bisherigen
Dateirechte. Fehler vor dem Ersetzen der Datei lassen den bisherigen Inhalt
unverändert und entfernen die temporäre Datei.

Auch automatisch berechnete Zielpfade werden vollständig aufgelöst und gegen
die Repository-Grenze geprüft, damit Symlinks keine externen Schreibziele öffnen.
Vor dem Ersetzen wird der Dateistand nach Vorbereitung und `fsync` erneut
geprüft. Eine inzwischen veränderte Datei bleibt erhalten und führt zu `409`.
Nicht kooperierende externe Programme können weiterhin genau zwischen dieser
letzten Prüfung und dem Ersetzen schreiben; eine allgemeine atomare
Compare-and-Swap-Garantie für solche Programme gibt es hier nicht.

Vor jedem geänderten Speichern wird der bisherige Text mit Revision und Zeitpunkt
unter `.material-history/<Dateiname>/` gesichert. Bei einem während des
Speicherns erkannten Konflikt wird auch die externe Fassung gesichert. Die
Historie hält pro Datei bis zu 20 Fassungen und insgesamt 64 MiB; eine einzelne
größere Fassung wird behalten. Der Ordner ist in Git ignoriert. „Versionen“ zeigt
die Historie für QMD-Dateien zum Vergleichen und Wiederherstellen; erst ein
anschließendes Speichern übernimmt die ausgewählte Fassung. Die Lese-APIs sind
`GET /api/document/history?path=...` und
`GET /api/document/history/<id>?path=...`.

Der Browser sichert Änderungen zusätzlich in `localStorage`, getrennt nach
Repository, Quelldatei und Browsersitzung, auch für Kursaktivitäten. Tabs und
Neuladungen verwenden eigene Sicherungsschlüssel. Nach Neuladen bietet ein
Dialog den Entwurf und den aktuellen Dateistand zum Vergleich an. Bei
mehreren Fassungen erlaubt eine Auswahl den Vergleich jedes Entwurfs. Speichern
entfernt nur die Sicherung der eigenen Sitzung; fremde Tabs bleiben erhalten. Bei
Revisionskonflikten erscheint derselbe Dialog. Entwürfe können kopiert,
heruntergeladen oder zur weiteren Bearbeitung übernommen werden. Eine Übernahme
speichert noch nicht auf dem Server. Erfolgreich gespeicherte Entwürfe werden
entfernt; bei deaktiviertem oder vollem Browserspeicher erscheint ein Hinweis.
Diese lokale Sicherung enthält den vollständigen Text und bleibt bis zum
Speichern, Verwerfen oder Löschen der Browserdaten bestehen.

Die Dokumentliste überspringt defekte, verschwundene und nach außerhalb
verweisende QMD-Dateien einzeln. `GET /api/qmds` liefert diese unter `warnings`
mit Pfad und Fehlermeldung; der Index zeigt die Hinweise an. Der Index wird kurz
zwischengespeichert; nach Dateiänderungen von außen liest `POST /api/qmds/reload`
ihn sofort neu ein. Die Ordnernavigation lädt bei jedem Ausklappen nur die direkten
Inhalte und QMD-Metadaten des betreffenden Ordners frisch (`GET /api/folder` mit
`metadata=1`). Der Knopf mit dem Kreissymbol aktualisiert ebenfalls nur den aktuell
ausgewählten Ordner. Andere aufgeklappte Zweige und das geöffnete Dokument bleiben erhalten.

Bildimporte prüfen beide Nutzdaten vor dem Schreiben, bereiten alle Dateien in
einem temporären Verzeichnis vor und nehmen übernommene Dateien bei einem
Fehler zurück. Diese Rücknahme deckt Anwendungsfehler ab; mehrere Dateien bilden
keine gegen Stromausfall abgesicherte Dateisystemtransaktion.

Die Build-Bereinigung berücksichtigt ausschließlich Dateinamen des jeweiligen
Dokuments beziehungsweise seines konfigurierten Outputs. Vorhandene `.tex`- und
`.typ`-Quellen werden beim Aufräumen erhalten. Nach einem Render werden neu
erzeugte Zwischenquellen anhand des vorherigen Dateibestands zugeordnet.
`build/<name>.material-ui.json` protokolliert die übernommenen Artefakte.

## Aufträge und Fehler

Rendern, Slides, Audit und Moodle-Aktionen liefern `202 Accepted` mit `job_id`.
`GET /api/jobs/<job_id>` liefert genau diesen Auftrag mit `resource`, `operation` und `status`,
auch nachdem ein weiterer Auftrag begonnen hat. Zustände sind `queued`,
`running`, `succeeded` und `failed`. Renderaufträge werden nacheinander bearbeitet;
weitere Änderungen für ein bereits wartendes Dokument werden zusammengefasst.
Belegte Audit- und Moodle-Ausführungskanäle antworten mit `409 Conflict`.
Die Historie behält bis zu 200 Einträge; aktive Aufträge werden nicht entfernt.
Aufträge werden bei jeder Änderung atomar unter `.material-ui/jobs.json` gesichert
und beim Start wieder geladen; dort noch als laufend vermerkte Aufträge werden als
gescheitert markiert („Serverneustart“). Der Ordner ist in Git ignoriert.
`GET /api/jobs/stream` liefert dieselben Aktualisierungen als Server-Events
(`text/event-stream`, Keep-alive alle 15 s); der Browser nutzt sie für den
Renderstatus und fällt auf das bisherige Polling zurück, wenn der Stream nicht
verfügbar ist. Renderdienst und Ausführungskanäle halten nur die
IDs ihrer Aufträge; der Status wird ausschließlich im `JobRegistry` geführt.
Die jeweils letzten Kanalzustände bleiben beim Kürzen der Historie verfügbar.

`POST /api/slides/ensure` und `/api/slides/rebuild` führen den Deck-Bau als
Hintergrundauftrag aus. Eine gemeinsame Slides-Instanz serialisiert auch die
Folienbauten nach einem PDF-Render; die Slides-Warteschlange begrenzt wartende
Quellen auf 32 und fasst gleiche Anforderungen zusammen. Werkzeugaufrufe des
Generators laufen über den gemeinsamen `ProcessRunner`; vollständige JSON-/SVG-
Ausgaben bleiben innerhalb dessen Ausgabelimit erhalten. Die globale
Dokument-Sperre wird nur zur Veröffentlichung gehalten, nicht während der
Generierung, Sicherungskopien oder Rücknahme. Die Sperrreihenfolge ist
Deck-Sperre vor Dokument-Sperre; auch auf die Deck-Sperre wird ohne globale
Dokument-Sperre gewartet. Quelle und Ressourcen werden nach den Sicherungskopien
erneut geprüft;
bei Shutdown werden Aufträge beendet und weitere Veröffentlichungen verhindert.

Bei verbundenem Ereignisstrom gleicht der Browser den Renderstatus alle 15 Sekunden
ab. Nach einer Unterbrechung greift das häufigere Polling mit Fehler-Backoff;
nach jeder Wiederverbindung wird der aktuelle Stand geladen.
Verspätete Antworten dürfen neuere Zustände desselben Auftrags nicht ersetzen.
Ein abgeschlossener Auftrag wird unter derselben Job-ID nicht erneut als laufend
angezeigt; veraltete Fehlerantworten lösen keinen neuen Poll-Timer aus.

Die Render-Warteschlange nimmt maximal 32 verschiedene wartende Dokumente auf;
weitere Anfragen erhalten `409 Conflict`. Bestehende Wartelisteneinträge können
weiter aktualisiert werden. Die Prozessverwaltung erlaubt vier gleichzeitige
Prozesse, einschließlich eigener dauerhafter Vorschau- und H5P-Prozesse.
Erfasste Ausgaben kurzer Aufträge werden in temporäre Dateien statt in RAM geschrieben.
Bei mehr als 16 MiB pro Ausgabestrom wird der Prozess samt Prozessgruppe
beendet; im Auftrag bleiben maximal die letzten 64 KiB je Strom mit einem
Kürzungshinweis. Die Größenkontrolle erfolgt alle 100 ms und ist deshalb eine
Abbruchschwelle, keine harte Dateisystemquote. Dauerhafte Prozesse werden über Pipes
ausgelesen; ihre Logdateien werden beim Erreichen des Limits auf den jüngsten Ausschnitt
gekürzt. Fehleranzeigen lesen höchstens die letzten 64 KiB.
Beim Herunterfahren werden neue Aufträge gesperrt, wartende Aufträge beendet,
Prozessgruppen gestoppt und registrierte Worker mit begrenzter Wartezeit eingesammelt.

HTTP-Anfragen haben standardmäßig 15 Sekunden Zeit, einschließlich des Lesens
der Antwort. Schreibaktionen werden nicht automatisch wiederholt. Statusabfragen
werden bei Netzwerkfehlern, Timeouts, HTTP 429 und Serverfehlern mit wachsendem
Abstand von 1 bis maximal 30 Sekunden wiederholt. Ein nach Neustart nicht mehr
vorhandener Auftrag führt zu einem sichtbaren Hinweis und beendet das Polling.
Der Materialindex wird direkt nach dem Serverstart in einem Hintergrund-Thread
vorgewärmt (`warm_index` in `app.py`); das erste `GET /api/qmds` nach einem
Neustart teilt sich diesen Aufbau über den TTLCache-Lock. Der Browser lädt den
Index daher einmalig mit bis zu 120 Sekunden Zeitlimit und einem Wiederholungsversuch,
damit ein kalter Aufbau nach dem Neustart nicht am Standard-Timeout scheitert.

Rendern verwendet eine atomar angelegte Quellkopie mit zufälligem Namen im
gleichen Ordner. So bleiben Ressourcenpfade und Projekteinstellungen erhalten,
und auch Zwischen-PDFs überschreiben keine vorhandene Ausgabe. Temporäre
Quellen werden aus dem Index ausgeschlossen und nach dem Rendern entfernt;
Zwischenartefakte werden dem Originaldokument zugeordnet. Das Ergebnis wird
zunächst separat verwahrt, mit PyMuPDF geöffnet und auf mindestens eine lesbare,
nicht verschlüsselte Seite geprüft. Erst nach erfolgreichem Exitcode,
PDF-Prüfung und erneuter Revisionsprüfung wird die Ausgabe atomar veröffentlicht.
Fehler lassen das letzte veröffentlichte PDF unverändert. Erfolgreiche
Auftragsdetails enthalten `source_revision` zur Zuordnung des PDFs.

Die bisherigen Statusrouten bleiben kompatibel; kursbezogene Abfragen geben
keinen fremden Kursstatus zurück. `GET /api/render` ist nicht mehr zulässig.
Moodle-Remote-Aktionen verwenden weiterhin ausschließlich `inv kurse.*`.

API-Fehler haben die Form
`{"error": {"code": "conflict", "message": "..."}}`.
Eingabefehler melden Dienste und Routen als `InvalidInput` und erhalten damit `400 invalid_input`;
andere `ValueError`-Instanzen stammen aus Programm- oder Datenfehlern und werden als
interner Fehler mit Protokolleintrag gemeldet. Schreibende Browseranfragen verwenden `X-Material-Token` aus dem HTML-Metatag.
Host und Origin werden geprüft. `TESTING=True` deaktiviert nur die Tokenpflicht;
Host- und Origin-Prüfungen bleiben aktiv. Flask muss mindestens Version 3.1 sein.

## Tests

```sh
python3 -m pytest src/tests/test_material_ui.py src/tests/test_material_ui_integrity.py src/tests/test_material_ui_robustness.py src/tests/test_material_ui_desktop.py src/tests/test_material_ui_architecture.py src/tests/test_material_ui_views.py src/tests/test_material_ui_plugins.py src/tests/test_material_ui_kalender.py src/tests/test_project_tasks.py src/tests/test_chat.py -q
```

Browserprüfungen benötigen Playwright mit installiertem Chromium. Moodle- und
Quarto-Aufträge werden in den betreffenden Tests durch lokale Testfunktionen
ersetzt; es werden keine Remote-Moodle-Aktionen ausgeführt.
Die Robustheitsprüfungen decken konkurrierendes Anlegen, volle Datenträger,
defekte Indexeinträge, fehlende/veraltete PDFs, Verbindungsabbrüche,
Serverneustart-Hinweise sowie Entwurfswiederherstellung und Konfliktauflösung ab.
Der isolierte HTTP-Client-Test benötigt zusätzlich Node.js.

## Layoutprüfung und Render-Aktualität

„Prüfen“ und jeder Renderlauf prüfen die vorhandenen PDF- und Folienausgaben
auf überstehende Inhalte und kleine Schrift. Hinweise nennen Ausgabe, Seite
beziehungsweise Folie und erscheinen gemeinsam unter „Prüfhinweise“ sowie in
der Render-Ausgabe. Ein Klick auf einen PDF-Hinweis öffnet die betreffende Seite.
Die Richtwerte sind 8 pt für Arbeitsblätter, 9 pt für Folien-PDFs und 24 px für
Excalidraw-Text; bewusst kleinere Fußzeilen werden gesondert behandelt. Hinweise
blockieren den Build nicht. Die PDF-Prüfung untersucht Text und Bildgrenzen;
in Rasterbilder eingebrannte Schrift wird ohne OCR nicht gemessen.

Reine Indexfelder (`tags`, `subject`, `grade`, `kind`, `deck`) lösen bei bereits
aktuellen Ausgaben keinen automatischen Neubau aus. Titel, Inhalt und unbekannte
Metadaten bleiben renderrelevant. Eigene Vorlagen und explizite Meta-Shortcodes
werden konservativ behandelt. Ein Stempel `<Dateiname>.render.json` im zentralen
Artefaktordner hält die PDF-Eingaben einschließlich referenzierter Bilder,
Includes, Vorlagen und Filter fest. Dadurch bleiben Ausgaben auch nach einem
Neuladen aktuell, wenn nur Tags geändert wurden. Ältere Ausgaben erhalten den
Stempel beim nächsten Build. Explizites „Rendern“ baut weiterhin neu.

## API-Kompatibilität

`GET /api/protocol` liefert `apiVersion` und `capabilities`. Der gemeinsame
Clientvertrag steht in `static/api-contract.json`. Material-UI teilt eine
erfolgreiche Prüfung für 30 Sekunden zwischen Anfragen; Schreibaktionen senden
zusätzlich API-Version und benötigte Fähigkeiten als Header. Der Server prüft
diese vor Ausführung, sodass auch ein zwischengespeicherter Vertrag keinen
inkompatiblen Schreibzugriff erlaubt. Die Present-App prüft ihren Vertrag
weiterhin selbst. Eine falsche Version oder fehlende Fähigkeit führt zu einer
verständlichen Neustartmeldung. Der Serverneustart bleibt dafür auch bei einer
inkompatiblen API erreichbar. Lokale Excalidraw-Dateien lassen sich in der
Present-App weiterhin ohne Material-UI-Server verwenden.

HTML, API-Antworten, Quellen und PDFs verwenden weiterhin `no-store`.
Statische Assets erhalten URLs mit dem Versions-Fingerprint des Servers und
können unverändert aus dem Browsercache geladen werden. Eine Importmap versieht
auch die transitiven ES-Module mit derselben Version. Unversionierte Assets
werden per ETag revalidiert. Ein Vertragsabruf für einen anderen Serverstand
wird abgewiesen, damit alte Module keinen neuen Vertrag übernehmen.

## Arbeitsblatt und Besprechungs-Canvas

Die PDF-Werkzeugleiste bietet „Besprechen“ zum Fortsetzen einer gespeicherten
Besprechung oder zum Starten der ersten. Der Tooltip erklärt die zum aktuellen
Stand passende Aktion. Erst bei vorhandenen Besprechungen erscheint direkt
daneben das Menü mit „Weitere Besprechung anlegen“. Ein Erklärungstext weist
auf die leere Zeichenfläche und den Erhalt vorhandener Besprechungen hin.
Eine zusätzliche Lösungsansicht neben dem Arbeitsblatt
wird nicht angeboten; Lösungsdateien lassen sich wie andere Dokumente öffnen.

„Weitere Besprechung anlegen“ öffnet eine leere, dem AB zugeordnete Excalidraw-Seite.
Sie kann auch ohne PDF-Ausschnitt beschrieben und gespeichert werden. In
Excalidraw öffnet „Aus AB einfügen“ eine Seitenvorschau des Arbeitsblatts oder
seiner zugeordneten Lösung. Fehlende oder veraltete PDFs werden vorher über den
verwalteten Render-Weg aktualisiert. Eine ganze Seite oder ein mit Maus, Stift
oder Touch gewählter Ausschnitt wird als eingebettetes PNG übernommen.
„Aktuelle Zeichenfläche“ ergänzt den bestehenden Stand; „Neue Seite“ legt eine
weitere Seite an. Der Import lädt das Deck nicht neu und erhält Zeichnungen und
Undo-Verlauf. Das eingefügte Bild ist ausgewählt und kann mit dem Auswahlwerkzeug
verschoben werden. Lösungsbilder werden als Lösungsschritt markiert und lassen
sich mit den vorhandenen Lösungswerkzeugen verdecken; der Aufgabenexport lässt
sie aus. „Besprechung fortsetzen“ öffnet einen gespeicherten Stand, bei mehreren
Besprechungen erscheint eine Auswahl.

Das Canvas liegt unter
`archiv/besprechungen/<Arbeitsblatt-Dateipfad>.besprechung/besprechung.excalidraw`.
Weitere Ausschnitte werden in der aktuell geöffneten Szene ergänzt und mit
„Speichern“ gesichert. Neue Besprechungen erhalten einen eigenen Dateiteil
(`besprechung-000002.excalidraw` usw.); frühere Besprechungen bleiben erreichbar.
Große PNG-Ausschnitte werden bei Bedarf auf höchstens 4 MiB Bilddaten
heruntergerechnet. Die Dateigröße der laufenden Szene wird nicht durch einen
Wechsel auf eine andere Besprechung begrenzt.
Die bisherige Historie ist pro Datei bereits auf
20 Fassungen bzw. 64 MiB begrenzt.
Nach einer Übernahme wird der eingefügte Ausschnitt angezeigt.
Änderungen werden mit „Speichern“ in der Präsentationsansicht gesichert;
die bestehenden Revisions-, Konflikt- und Historienfunktionen gelten auch hier.
PDF-Neubau und `inv clean` überschreiben oder löschen diese dauerhaften
Besprechungen nicht. `archiv/` ist lokal und von Git und Datei-Sync ausgeschlossen;
Besprechungen gehören deshalb in die eigene lokale Datensicherung.

Vorhandene Besprechungen aus dem bisherigen Build-Pfad werden beim Öffnen,
vor Umbenennungen nur für die betroffenen Quellen und vor `inv clean` für den
gesamten Altbestand einschließlich Historie und separater
Anmerkungen ins Archiv kopiert. Die alte Fassung bleibt bis zur Bereinigung
als Sicherung erhalten. Eine Markierung verhindert das erneute Importieren nach
einer Umbenennung. Noch offene Präsentationen des alten Build-Pfads müssen über
„Besprechung fortsetzen“ neu geöffnet werden; Schreibversuche auf die migrierte Altdatei
werden mit einem Konflikthinweis abgewiesen.
Datei- und Ordnerumbenennungen über die UI führen Besprechungen und manuelle
Lösungszuordnungen zusammen nach. Bei Zielkonflikten wird abgebrochen;
schlägt die Umbenennung fehl, werden die Zuordnungen und Archivpfade zurückgesetzt.

Die Endpunkte `/api/worksheet`, `/api/worksheet/solution`,
`/api/worksheet/page`, `/api/worksheet/start` und `/api/worksheet/fragment`
befinden sich in
`worksheet_routes.py`; die Oberfläche in `static/worksheet-tools.js`.
PDF-Seiten werden mit PyMuPDF gerastert. Vor Vorschau und Übernahme muss der
PDF-Render-Stempel zur aktuellen Quelle samt Abhängigkeiten passen. Veraltete
oder unbekannte Stände werden in der UI über den verwalteten Render-Weg neu
gebaut; das Backend weist sie bis dahin zurück. Auch das Lösungs-PDF wird erst
nach erfolgreicher Aktualitätsprüfung angezeigt. Ein zusätzlicher
PDF-Revisionsvergleich verhindert, dass ein Ausschnitt aus einer inzwischen
geänderten Seite übernommen wird.


DAV-Zugangsdaten werden ausschließlich in
`.material-ui/plugins/kalender/settings.json` gespeichert (Datei 0600,
Plugin-Verzeichnis 0700). GET und POST der Einstellungen liefern nur Passwortmasken;
DAV-Fehlertexte werden weder an den Browser noch in Statusdateien übernommen.
Konten benötigen HTTPS; Zugangsdaten, Query und Fragmente in der URL sind verboten.
Bei Änderung von URL oder Benutzername muss das Passwort neu eingegeben werden.
`.material-ui/` ist vollständig von Git und über `.sync-exclude.lst` vom Datei-Sync
ausgeschlossen. Bei einem übergeordneten Nextcloud-Sync-Root muss der Ausschluss
zusätzlich im Sync-Client eingerichtet werden. Die Datei enthält das Passwort lokal
im Klartext; sie gehört nicht in geteilte Ordner, Exporte oder Backups ohne Schutz.

Kalender und Agenda bieten direkt sichtbare Kalender+- und TODO+-Symbole zum Erstellen.
Der Dialog übernimmt den Eintragstyp und das heutige Datum; der Typ bleibt änderbar.
In den Kalender-Einstellungen lässt sich für Termine und TODOs jeweils ein eigener
Standardkalender auswählen (auch lokale Speicherung). Es werden jeweils die Kalender
mit passender Unterstützung angeboten. Neu eingerichtete Konten zunächst speichern,
anschließend deren Standardkalender auswählen.
Datierte TODOs werden in Kalender und Agenda als „☐ TODO“ angezeigt. Sie können lokal oder als VTODO in einem CalDAV-Kalender gespeichert
werden. Die Kalenderfähigkeiten werden vor dem Speichern geprüft. Beim Abgleich
werden alle offenen Aufgaben eingelesen, auch ohne Datum oder mit alter Frist.
Undatierte Aufgaben stehen im Eingang der Heute-Ansicht; erledigte und abgebrochene
Aufgaben werden ausgeblendet.

### Ordner bearbeiten und Hinweise

Der Bearbeiten-Knopf am Ordner oeffnet Ordnername, Titel, Thema und
Kurzbeschreibung der Einheit sowie die Ordnerhinweise. In Klassenordnern
unter `unterricht/` wird `einheit.yaml` dabei bei Bedarf angelegt; bestehende
Einsatzdaten und weitere Einheitenangaben bleiben erhalten. Die YAML-Datei
erscheint nicht in der Materialliste.

Hinweise stehen gesammelt in `hinweise.md` und erscheinen als eingeklappter
Bereich am Anfang des Ordners. Bestehende `*-hinweise.md` und `*_hinweise.md`
werden dort gemeinsam angezeigt und beim Speichern der Ordnerangaben in
`hinweise.md` zusammengefuehrt. Neue Hinweise als Abschnitte dieser Datei
ergaenzen. Parallele Aenderungen werden vor dem Speichern erkannt.

### Öffentliche Kalenderhaken für Plugins

Das Kalender-Plugin stellt `@calendar` bereit; Plugins deklarieren
`dependsOn: {"@calendar": ">=0.2.0"}` und nutzen
`ctx.service("calendar").register_source(provider, source_id=…, name=…)`. Die Registrierung
liefert eine idempotente Abmeldefunktion. Die frühere Backend-Fassade `ctx.calendar` und
`ctx.register_calendar_source` sind entfernt.

Frontend-Aktionen verwenden `ctx.calendar.registerAction({ id, mount })` und erhalten
in `mount({ container, refresh })` einen eigenen Toolbar-Container. Eine optional
zurückgegebene Funktion räumt beim Abmelden auf. Die Registry bedient bereits
geöffnete und später geöffnete Kalender-/Agendaansichten. Bestehende DOM-Ereignisse
bleiben erhalten. JS-Module in Unterordnern sind ebenfalls über die Importmap versioniert.

`ctx.units.scheduled()` bietet lesenden Einheitenzugriff und `ctx.workers` den
verwalteten Workerstart mit Shutdown-Signal. Der Kalender verwendet diese Fassaden
anstelle direkter Runtime-Zugriffe. `runtime` und `config` bleiben vorerst für ältere
Plugins verfügbar; Plugins sind weiterhin vertrauenswürdiger lokal installierter Code.


### Heute: offene Aufgaben und Tagesplanung

Die neue Ansicht **Heute** ist beim ersten Start die Standardansicht; eine bereits
gewählte Ansicht bleibt gespeichert. Sie zeigt überfällige und heute fällige oder
geplante TODOs, einen Eingang ohne Datum, spätere Aufgaben und die heutigen Termine.
Die Termine stehen vor den Aufgaben und zeigen Zeitspanne, Ort und Kalender.
Laufende und nächste Termine werden hervorgehoben, vergangene dezenter dargestellt.
Eingang und spätere Aufgaben sind eingeklappt; leere Aufgabengruppen entfallen.
„Planen“ öffnet das Planungsdatum, bereits heute geplante Aufgaben zeigen ihren Status.
Fristen erscheinen mit verständlichen Datumsangaben und einer Hervorhebung bei Überfälligkeit.
Offene CalDAV-Aufgaben werden unabhängig vom Termin-Cachezeitraum eingelesen.
Das Navigationssymbol zeigt die Anzahl der heute relevanten offenen Aufgaben.

Über „Ausblenden“ an TODOs bzw. „Eintrag ausblenden“ im Termindialog lassen sich
Einträge lokal verbergen (bei Serien die ganze Serie). „Sichtbarkeit“ in Heute und
den Kalenderaktionen blendet ganze Kalender aus und stellt ausgeblendete Einträge
wieder her. Die Auswahl bleibt beim Sync erhalten und gilt für Heute, Agenda,
Monatsansicht und Überfällig-Zähler. Der CalDAV-Server bleibt dabei unverändert.

„Heute einplanen“ und das Planungsdatum verändern die ursprüngliche Frist nicht.
Die Planung wird lokal gespeichert; abgelaufene Planungsdaten bleiben sichtbar.
Schlägt das Einplanen fehl, wird das Eingabefeld auf den bestätigten Stand
zurückgesetzt und die Ansicht neu gezeichnet.
„Erledigt“ speichert lokale Aufgaben dauerhaft und schließt CalDAV-Aufgaben zuerst
auf dem Server ab. Bei Verbindungsfehlern bleiben sie offen. An Unterrichtseinheiten
legt „+ TODO“ eine Aufgabe mit einem Link zur Einheit an (CalDAV: X-MATERIAL-UNIT).
Im Erstellungsdialog ist das Fälligkeitsdatum für TODOs optional.
Die Tagesansicht aktualisiert sich alle 30 Sekunden sowie beim Zurückkehren zur UI,
auch nach einem Tageswechsel. Abgleichstand und Quellenfehler bleiben sichtbar.
**Wiederkehrende TODOs:** Der Erstellungsdialog bietet „Wiederholen“
(täglich/wöchentlich/monatlich mit Intervall und optionalem Ende). Lokale und
CalDAV-Einträge mit RRULE werden als `recurring` markiert; das Erledigen einer
CalDAV-Serie verwendet `complete(handle_rrule=True)`, damit die nächste Wiederholung
angelegt wird statt die Serie zu beenden. Serien-Master lassen sich bearbeiten
(Titel, Datum, Wiederholung ändern oder entfernen – Änderungen gelten für die ganze
Serie; das RRULE des Masters wird über `resource.save()` aktualisiert). Einzelne
Ausnahmen einer Serie (RECURRENCE-ID auf der Ressource) bleiben dem ursprünglichen
Kalender vorbehalten.

**Ferienkalender:** In den Kalender-Einstellungen lässt sich ein CalDAV-Kalender
als Ferienkalender wählen (auch „Lokale Termine“). Dessen ganztägige Termine
werden in Kalender, Agenda und Heute mit `holiday: true` markiert und als
„Ferien: …“-Chip dargestellt; `GET /api/plugins/kalender/holidays?from&to` liefert
die betroffenen Tage für andere Plugins (z. B. Stundenplan).

TODOs lassen sich in „Heute“ durch Klick auf ihre Checkbox erledigen. Sie bleiben am
Abschlusstag unter „Heute erledigt“ durchgestrichen sichtbar, auch nach dem Neuladen
oder einem Kalenderabgleich. Ab dem nächsten Tag werden sie nicht weitergeführt.
Der Abschluss von CalDAV-TODOs wird auch im Kalender gespeichert.

### Reduzierte Dokumentansicht

Technische Dokumentangaben stehen unter „Dokumentdetails“. Versionen und Metadaten
sind über „Einstellungen“ in der Editorleiste erreichbar. Die PDF-Leiste bietet
„Slides“ für Präsentationsvorlagen; andere Dokumente zeigen an derselben Stelle
„Besprechen“. Das öffnet vorhandene Besprechungen oder legt bei Bedarf eine an.
Eine zusätzliche neue Besprechung lässt sich über das zugehörige Pfeilmenü anlegen.
Die obere Suchleiste sucht in „Material finden“ innerhalb der aktuellen Auswahl;
in den übrigen Ansichten öffnet sie die globale Materialsuche.

Einheiten können unter „Bearbeiten“ als **Fertig – Bearbeitung abgeschlossen**
markiert werden. `fertig: true` in `einheit.yaml` speichert diesen Status unabhängig
von Einsatzterminen. Ohne Markierung gilt „In Bearbeitung“. Die Einheitenübersicht
zeigt den Status auch bei eingeklappten Einheiten; unter „Filter → Bearbeitungsstatus“
lassen sich offene oder fertige Einheiten auswählen. Zum Überarbeiten die Markierung
wieder entfernen.

Einzelne Arbeitsblätter und Präsentationen haben in der Materialliste einen
„Fertig“-Schalter. Ihre Statuswerte stehen gemeinsam unter `arbeitsblaetter_fertig`
in `einheit.yaml` (mit Dateipfaden relativ zur Einheit; der Schlüsselname stammt aus
der Zeit, als nur ABs einen Schalter hatten). Sind alle ABs und Präsentationen fertig,
wird auch die Einheit automatisch fertig; Lösungen zählen dabei nicht mit.
„Einheit als fertig markieren“ markiert alle enthaltenen ABs und Präsentationen als
fertig. Wird eines davon wieder geöffnet, ist auch die Einheit wieder in Bearbeitung.
Das Entfernen der Fertig-Markierung im Einheiteneditor öffnet alle wieder.
Ein neues AB in einer fertigen Einheit öffnet sie wieder. Eine Präsentation ohne
eigenen Eintrag übernimmt dagegen den gespeicherten Status der Einheit, damit
Einheiten, die vor Einführung des Präsentations-Schalters fertig waren, fertig bleiben;
beim nächsten Speichern erhält sie ihren eigenen Eintrag.

## Architektur und Zuständigkeiten

Die Zuständigkeiten für Indexierung, Dateiänderungen, Browserzustand und Plugins
sind in [Architektur der Material-UI](../../docs/material-ui-architektur.md) dokumentiert.
