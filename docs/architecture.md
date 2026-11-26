# Architektur der Material-Werkzeuge

Die Werkzeuge bleiben ein modularer Monolith. Invoke, CLI und Flask koordinieren
Anwendungsfälle; Dateisystemzugriffe und Builds liegen in gemeinsam nutzbaren
Python-Paketen.

## Gemeinsamer Kern

`src/material_core/filesystem.py` stellt atomare Text-, Byte- und Kopieroperationen
bereit. Temporäre Dateien liegen auf demselben Dateisystem wie das Ziel. Vor dem
Ersetzen wird der Inhalt mit `fsync` geschrieben; Fehler entfernen die temporäre
Datei. Dokumentrevisionen, Sync-Metadaten, Inhaltsdateien und Wissensmanifeste
verwenden diese Bausteine.

`src/material_core/builds.py` führt den gemeinsamen Dokument-Build für
`inv build --source ...` und die Material-UI aus:

1. Quelle und Revision erfassen, benötigte TikZ-Assets bauen.
2. Eine eindeutig benannte Quellkopie im ursprünglichen Ordner rendern.
3. Zwischenartefakte nach `build/artefakte/` übernehmen.
4. Exitcode und PDF prüfen, anschließend die Quellrevision erneut vergleichen.
5. Das geprüfte PDF atomar unter `build/pdf/` veröffentlichen.

Fehler vor der Veröffentlichung lassen das bisherige PDF erhalten. Manuell
geschriebene `.tex`- und `.typ`-Quellen bleiben bestehen. `material_ui.builds`
exportiert die Klassen für bisherige Aufrufer weiterhin.

## Kursanwendung

`CourseApplication(config)` in `src/course_sync/application.py` besitzt ihre
eigenen Dienste, Sperren, Vorschau-Caches und Runtime-Zustände. Konfigurationen
für andere Projektwurzeln entstehen mit `AppConfig.with_root(...)`. Die
Dienstfabriken werden direkt an der Anwendung definiert und anwendungsbezogen
zwischengespeichert; ein zweiter Service-Registry-Layer entfällt.

`cli.py` verbindet die CLI-Argumente mit der Anwendung. `main.py` ist der
Einstiegspunkt und stellt bisherige Modulzugriffe über eine Standardanwendung
weiterhin bereit. Neuer Anwendungscode verwendet `CourseApplication` direkt.
Die Material-UI besitzt je Runtime eine eigene Kursanwendung.

`site_export.py` enthält den statischen Export; `moodle_workflows.py` bündelt
die Kurs-Uploads und deren Prüfabläufe. Remote-Moodle-Kommandos bleiben für
KI-Agenten ausschließlich über die vorgesehenen `inv kurse.*`-Tasks zulässig.

## Export und Veröffentlichung

Ein nicht leerer Exportordner benötigt ein gültiges Exportmanifest. Projekt-
und Kursquellen, unsichere Manifestpfade und Symlinks in verwalteten Zielpfaden
werden abgewiesen. Ein Export darf fremde Dateien weder überschreiben noch
bereinigen.

Der vollständige neue Export entsteht zunächst in einem temporären Ordner.
Unveränderte Dateien werden dort nach Möglichkeit über Hardlinks wiederverwendet;
Schreibzugriffe ersetzen die jeweilige Datei atomar. So benötigt ein großer
Export keine vollständige zweite Kopie seiner unveränderten Pakete.
Erst danach werden geänderte Dateien atomar ersetzt und überzählige Dateien
aus dem vorherigen Manifest entfernt. Unveränderte Dateien behalten ihren
Zeitstempel; der Zielordner behält seinen Inode. Bei einem Veröffentlichungsfehler
werden bereits veränderte Dateien aus einer Sicherung zurückgenommen.

Die Veröffentlichung mehrerer Dateien ist keine Dateisystemtransaktion gegen
Stromausfall. Während der Übernahme können Leser kurzzeitig unterschiedliche
Dateigenerationen sehen. HTML und Manifest werden nach den übrigen Dateien
übernommen.

## Quellen und Inhaltstypen

`CourseActivity` ist das gemeinsame Transportmodell. `PythonQuestionBlock` ist
ein kompatibler Alias auf dieselbe Klasse. Die Inhaltstypen unter
`classes/content_types/` sind Adapter für Hashing und Serialisierung;
`activity_to_content_type(...)` wählt den passenden Adapter.

Alle Aktivitätsmodelle verwenden die Pfadregeln aus `content_paths.py`:

- Autorquellen können unter `h5p/` oder `chapters/` liegen.
- Aufbereitete H5P-Inhalte gehören nach `build/content/`.
- Pakete gehören nach `build/h5p/`, Build-Hashes nach `build/hashes/`.

Der Paketbau rekonstruiert ausschließlich seine generierten Arbeitsverzeichnisse.
Autorquellen und explizit referenzierte H5P-Archive werden dabei erhalten.
Alte Dateien außerhalb von `build/` werden nicht mehr anhand ihres Namens
automatisch als Build-Abfall gelöscht; eine Bereinigung erfordert eine bewusste
Prüfung ihres Inhalts und ihrer Verwendung.

Parser und Vorschau verwenden die Quelldatei-Ermittlung und Inhalts-Fingerprints
aus `course_sources.py`. Neben MDX werden Sidecars, Konfigurationen und Ressourcen
erfasst; generierte Ordner und versteckte Zustandsdateien bleiben ausgeschlossen.
Dateinamen und Inhalt bestimmen den Fingerprint, auch bei unveränderter Größe
oder unverändertem Änderungszeitpunkt. Der Vorschau-Cache wird nur gespeichert,
wenn sich die Quellen während des Parsens nicht verändert haben.

## Wissensbasis

`pipeline.inspect_all(...)` liefert einen strukturierten `CheckReport`.
`pipeline.check_all(...)` gibt den Bericht aus und liefert die Fehleranzahl.
Beide Wege verändern keine Karten oder Freigaben.

- `inv wissen-check`: ausschließlich prüfen.
- `inv wissen-aufnehmen`: neue Karten aufnehmen oder zurückstellen.
- `inv wissen-freigeben`: fehlerfreie Entwürfe freigeben.
- `inv wissen-sortieren`: Karten einsortieren.
- `inv wissen-pflegen`: prüfen, aufnehmen, freigeben und einsortieren.

Schreibende Pflegeaktionen verwenden dieselbe Laufsperre wie die übrige Pipeline.
Die automatische Erschließung verwendet ausdrücklich `wissen-pflegen`, um ihren
bisherigen vollständigen Bearbeitungsablauf beizubehalten.

## Tests

Die Entwicklungsumgebung benötigt `pip install -e '.[dev]'`.
`inv test` führt die gesamte Testsammlung mit pytest aus;
`inv test --path src/tests/test_build_service.py` prüft gezielt einen Bereich.
`inv kurse.test` und die Testschranken der Kurs-Releases verwenden ebenfalls
pytest, damit sowohl freie Testfunktionen als auch `unittest.TestCase` erfasst
werden.

Regressionstests prüfen insbesondere Exportfehler und Rücknahme, fremde Dateien,
Manifestpfade, H5P-Änderungen bei gleichem Zeitstempel, getrennte Anwendungen,
fehlgeschlagene Schreibvorgänge, gemeinsame Builds und rein lesende Wissenschecks.
