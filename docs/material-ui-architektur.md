# Architektur der Material-UI

Die Anwendung bleibt ein lokaler Flask-Prozess mit ES-Modulen im Browser.
`ApplicationServices` ist der Ort für die Erzeugung gemeinsam genutzter Dienste;
Routen und Plugins erzeugen keine eigenen Einheitenservices.

## Lesen und Schreiben

`SourceCatalog` hält die Dateierkennung und die begrenzten Text-/Frontmatter-Caches.
`DocumentService` berechnet daraus Materialeinträge. Indexaufbau, Suche und
Einheitenübersicht verändern keine Quelldateien. Lösungsdateinamen werden bei der
Klassifikation berücksichtigt, ohne Frontmatter zu schreiben.

Beim Erstellen und Speichern werden Lösungsmetadaten weiterhin normalisiert.
Bestehende externe Dateien lassen sich ausdrücklich mit
`POST /api/materials/repair-solution-metadata` aktualisieren. Der Aufruf liefert
`changed` (relative Pfade) und `warnings` und ist wiederholbar. Er ist kein Teil
des Starts oder eines lesenden API-Aufrufs.

`FileOperations` koordiniert Umbenennen, Verschieben und Löschen. Die Routen
übersetzen HTTP-Eingaben und Ausgaben. Dateiprüfungen, Worksheet-Sperren,
Referenzaktualisierung und Rollback liegen im Anwendungsfall beziehungsweise in
den dazugehörigen Domänendiensten. Der vorhandene `UnitService` hält die
Transaktion für Referenzänderungen; `FolderService` nutzt dieselbe Instanz.

## Änderungen und Caches

Ein `MaterialChanges`-Verteiler gehört zu jeder Anwendung. Erfolgreiche
Dateioperationen veröffentlichen `MaterialChange(kind, paths)`. Der gemeinsame
Service invalidiert den Dokumentindex; dieser meldet `invalidated`, woraufhin
die Einheitenübersicht und bei strukturellen Änderungen die Plugin-Indizes
invalidiert werden. Bestehende Aufrufer von `invalidate_qmd_cache()` nehmen
dadurch ebenfalls am gemeinsamen Ablauf teil.

Benachrichtigungen erfolgen nach dem Commit. Ein fehlerhafter zusätzlicher
Listener wird protokolliert und verhindert weitere Listener nicht. Die
vorhandenen Fingerprint- und TTL-Prüfungen bleiben für externe Editor- und
Git-Änderungen erhalten. Die Caches sind abgeleitete Daten; die Dateien bleiben
die maßgebliche Quelle.

## Zustand im Browser

`createSearchState()` besitzt die Suchbegriffe für globale und kontextuelle
Suche. Dokumenttitel sind reine Anzeige und kein Suchzustand. Ansichtswechsel
stellen den jeweiligen Suchbegriff wieder her. Das Schließen eines Dokuments
verändert den Suchbegriff der Themenansicht nicht. `createFulltextState()`
(Modul `static/fulltext-state.js`) besitzt den Volltext-Zustand des Pickers
(Treffer, Quellen, Ladetoken, Timer) – der Picker ist der einzige Verbraucher,
der globale App-State enthält diese Felder nicht mehr.

`createDocumentState()` bündelt Beginn, Übernahme und Schließen einer
Dokumentsitzung. Jede Ladeoperation erhält einen Token; verspätete Antworten
können eine neuere Sitzung nicht überschreiben. Speichern und Konfliktbehandlung
bleiben beim `DocumentSession`-Controller. Der gemeinsame App-State bleibt als
Kompatibilitätsmodell für vorhandene Controller erhalten; neue Controller sollen
Aktionen und lesende Snapshots verwenden.

`WorkspaceModeRegistry` serialisiert Moduswechsel, lässt beim erneuten Betreten
auch ein anderes Dokument desselben Modus öffnen und räumt fehlgeschlagene
Eintritte wieder auf. Kurszustand wird vom Kurs-Plugin gesetzt.

## Plugins und Layout

Der Backend-Kontext bietet Host-Ports Version 1: `documents`, `builds`,
`processes`, `jobs`, `workers`, `units`, `render` (Render-Warteschlange des Kerns,
Auftrags-ID) und `search` (Such-Provider für `/api/search`) sowie den gemeinsamen
`unit_service`. Die eingebauten Plugins greifen darüber auf Host-Dienste zu und
verwenden kein `ctx.runtime` mehr. `runtime` bleibt für externe Plugins vorerst
als Kompatibilitätszugriff erhalten; dies ist keine Sandbox. Die unveränderliche
`AppConfig` bleibt für bestehende Plugins verfügbar.

Frontend-Kontexte deklarieren `apiVersion: 1`. Die Startverdrahtung stellt
Abhängigkeiten pro Plugin bereit; Chat und Importe bekommen keinen allgemeinen
App-State. Für Kurse bleibt ein begrenzter kompatibler Zustandsausschnitt.

Nur das Host-Stylesheet definiert das Workspace-Raster, einschließlich der
Kombinationen aus Notiz, Chat, Fokusmodus und eingeklappter Seitenleiste.
Plugin-Stylesheets gestalten ihren Inhalt. `createWorkspaceChrome()` übernimmt
von Plugins deklarierte sichtbare und verborgene Host-Slots; konkrete Kurs-Slots
werden im Kurs-Plugin ausgewählt.

Die Service-Erzeugung von `CourseApplication` besitzt einen eigenen reentranten
Lock. Hintergrundvorbereitung der H5P-Libraries darf das Erzeugen rein lesender
Kursdienste nicht über den Workspace-Lock blockieren. Dateiänderungen behalten
ihren bisherigen Workspace-Lock.

## Prüfungen

`test_material_ui_boundaries.py` prüft die zentralen Architektur-Invarianten mit
kleinen synthetischen Beständen. Die bestehenden API- und Browsertests prüfen
zusätzlich die Einbindung in Notizen, Materialsuche, Kurse und Dateioperationen.
Die Grenzen sind bewusst schrittweise eingeführt: globale Zustandsfelder und
der externe Runtime-Kompatibilitätszugriff sind noch nicht vollständig entfernt.

## Oberflächenrahmen

Der Rahmen der Oberfläche folgt wenigen Regeln, die für neue Ansichten und Plugins gelten:

- **Eine Kopfzeile.** Marke, Suche, „Neu“ (mit Menü für Nebenwege wie den Import), Ansichtsumschalter
  (Bearbeiten, Geteilt, Vorschau), Fokus-Modus, Status, Chat, Hilfe und das Einstellungsmenü
  stehen in einer Zeile. Farbschema, Auto-Speichern und Auto-Render liegen im Einstellungsmenü.
  Unter 1400 px zeigt die Marke nur das Symbol, unter 1200 px steht die Suche in einer eigenen
  Zeile, unter 700 px ordnet sich die Kopfzeile für das Telefon neu an. Es gibt keinen eigenen
  Streifen für den Ansichtsumschalter mehr.
- **Suche und Befehle (`Strg+K`).** `Strg+K` springt in die Suche. Ein `>` am Anfang schaltet die
  Materialsuche auf Befehle der Oberfläche um (`registerCommands` in `picker.js`, Liste in `app.js`).
  Ein Befehl besteht aus `id`, `label`, optional `hint`, `icon`, `keywords`, `available()` und
  `run()`; er ruft vorhandene Knöpfe auf und führt keine eigene Logik aus.
- **Beschriftete Rail.** Jede Ansicht der Rail zeigt Symbol und eine Kurzbeschriftung. Kurztext,
  Kopfzeile des Index und Gruppe stehen in `VIEW_LABELS` (`views.js`); Plugins können `label`,
  `heading` und `group` an `ctx.views.register` mitgeben, sonst gilt das erste Wort des Titels.
  Der Kopf des Index nennt die aktive Ansicht, Trennlinien gliedern die Rail in Gruppen.
- **Eine Leiste in der Einheitenansicht.** Filter, Hinzufügen und „Mehr“ sind Chips mit Popover
  (`.unit-toolbar`). Die Einheitenkarte zeigt Titel, Status und Termine kompakt, freie Stunden nach
  der letzten Einheit klappen bis auf die nächsten fünf hinter „N weitere offene Stunden anzeigen“.
- **Frontmatter im Editor eingeklappt.** Frontmatter ab fünf Zeilen ist beim Öffnen eingeklappt
  („Metadaten · Titel“); kürzeres bleibt sichtbar. Der Editor wird aus `src/editor-app` mit
  `npm run build` gebaut.
- **PDF-Vorschau mit einer Leiste.** Die Leiste des eingebauten PDF-Viewers ist ausgeblendet
  (`#toolbar=0&navpanes=0`); „PDF im Tab öffnen“ öffnet die volle Bedienung (Seiten, Zoom, Suche, Drucken).
- **Schmale Fenster.** Unter 1200 px ist der Index eine Schublade mit abgedunkeltem Hintergrund; ein
  Klick daneben, `Esc` oder das Öffnen eines Dokuments schließt sie.
- **Gestaltungsgrundlage.** Abstände (`--space-*`), Radien (`--radius-*`), Schatten (`--shadow-*`),
  Fokusring (`--focus-ring`) und Farben kommen aus Tokens in `app.css`. Das Host-Stylesheet besteht aus
  `app.css` bis `app-modes.css`; die Reihenfolge in `templates/index.html` ist die Kaskade.
  `test_material_ui_chrome.py` sichert Aufteilung, Tokens und die Elemente des Rahmens.
