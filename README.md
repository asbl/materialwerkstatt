# Teaching Materials Quarto

Markdown ist hier die Autorensprache: Unterrichtsmaterial liegt als `.qmd` vor und wird
per Quarto nach LaTeX/PDF gerendert. Das Repository buendelt vier Werkzeuge:

- **Quarto-Build**: Klausuren, Arbeitsblaetter und Decks bauen (`src/quarto/`, Filter
  `exam.lua`, Templates in `src/quarto/templates/`).
- **Material-UI**: lokale Web-App zum Bearbeiten und Rendern von QMDs mit Vorschau.
  Das externe [Blog-Plugin](docs/blog.md) bearbeitet Markdown-Beiträge offline
  und erzeugt mit Pelican eine statische Blog-Website.
- **course-sync**: interaktive H5P-Kurse als Textdateien pflegen und nach Moodle hochladen
  (Einstieg: [docs/course-sync/getting-started.md](docs/course-sync/getting-started.md)).
- **Wissensbasis**: Fachdidaktik-Quellen erschliessen, durchsuchen und als Karten aufbereiten
  (Einstieg: [wissen/README.md](wissen/README.md)).

## Voraussetzungen

- Python 3.12 oder neuer
- Quarto
- LaTeX mit `pdflatex`
- `rsvg-convert` (Einheitskreis-/Skizzen-PDFs) und `pdftocairo` (TikZ-SVG-Assets)
- optional: Playwright-Browser (Moodle-Uploads), Chromium/Chrome (Material-UI als Desktop-App)
- nur mit dem jeweiligen Plugin (siehe [Optionale Plugins](#optionale-plugins)): LibreOffice und
  Pandoc (`office`), Tesseract und Ghostscript (`ocr`)
- nur zum Mitarbeiten: Node.js mit `npx` (markdownlint, Editor-Bundle, Praesentationsansicht
  `inv deck-present`)

`inv doctor` prueft all das und zeigt fuer Fehlendes konkrete Installationshinweise.

## Installation

**Schnell (Linux):** `./install.sh` prueft zuerst das System, klont/aktualisiert die Quellen
nach `~/.local/share/material-ui`, legt eine virtuelle Umgebung an, fuehrt `inv setup` aus und
installiert den Starter `material-ui`. Systemprogramme (Quarto, TeX, Typst, Chromium, ...)
bleiben beim System:

```sh
./install.sh --nur-pruefen     # nur System-Check, nichts wird veraendert
./install.sh --system-pakete   # fehlende Pakete per sudo nachinstallieren (mit Rueckfrage)
python3 src/material_core/systemcheck.py --befehl   # nur den Installationsbefehl anzeigen
```

Der Check (`src/material_core/systemcheck.py`, auch als `inv doctor`) erkennt den Paketmanager
(pacman, apt, dnf, zypper), meldet je Stufe (Basis, PDF-Build, empfohlen, aktivierte Plugins,
optional, Entwicklung) was
vorhanden ist und nennt die passenden Pakete, bei Quarto und Typst auch Fremdquellen (AUR,
Release-Download). Mit `--json` und `--pakete` ist er fuer Paketbauer maschinenlesbar.

### Optionale Plugins

Zwei eingebaute Plugins sind ab Werk **aus**, damit ihre Programme nur braucht, wer sie nutzt:

| Plugin | Wofuer | Programme |
| --- | --- | --- |
| `office` | DOCX-Import in der Material-UI, `inv import-onlyoffice` | LibreOffice, Pandoc |
| `ocr` | `inv wissen-ocr`, `wissen-komprimieren`, `wissen-update --ocr/--komprimieren` | Tesseract, Ghostscript |

```sh
inv plugin-enable office            # nennt gleich die fehlenden Pakete; danach Server neu starten
./install.sh --system-pakete        # installiert auch die Pakete aktivierter Plugins
```

Der PDF-Import braucht keines der beiden. Wer DOCX oder OCR schon vor dieser Aufteilung genutzt
hat, muss das Plugin einmal aktivieren (je Inhaltsordner, Zustand in `daten/plugins.json`).

**Programm und Inhalte trennen:** Unter Einstellungen, Reiter „Ordner“, laesst sich ein
Inhaltsordner waehlen (z. B. in einem Nextcloud- oder Syncthing-Ordner); danach den Server neu
starten. Dort liegen `unterricht/`, `wissen/`, `ressourcen/quellen/`, eigene Vorlagen
(`src/quarto/_local/`), `plugins/` und `build/`. Das Programm legt dort zusaetzlich eine
verwaltete Kopie seiner Filter, Vorlagen und Schriften (`src/`), `_quarto.yml` und `tasks.py` an;
sie wird bei jedem Start abgeglichen und darf nicht bearbeitet werden. `inv build` laeuft im
Inhaltsordner wie im Programmordner. Die Einstellung gilt je Rechner
(`~/.config/material-ui/workspace.json`), `MATERIAL_HOME` hat Vorrang. Vom Sync auszuschliessen
sind `build/`, `.h5p-runtime/`, `.material-ui/`, `.env` und `foerderempfehlungen/`. Vorhandene
Inhalte werden nicht automatisch verschoben.

**Mehrere Rechner:** Gemeinsame Programmdaten liegen unter `daten/` und werden mitsynchronisiert:
Stundenplan, Erinnerungen, lokale Termine, Aufgabenplanung, Planungsmarker, Stundenausfaelle,
Tags, aktivierte Plugins, Chat-Prompts und Loesungsverknuepfungen. `.material-ui/` bleibt je
Rechner (Job-Verlauf, Kalender-Cache, Kalenderkonten mit Passwort); das Kalenderkonto wird deshalb
auf jedem Rechner einmal unter demselben Namen eingerichtet. Frueher lokal abgelegte Dateien
wandern beim ersten Zugriff nach `daten/`; liegt dort schon eine, hat sie Vorrang. Material-UI
nicht auf zwei Rechnern gleichzeitig benutzen und vor dem Wechsel den Sync abwarten, sonst
entstehen Konfliktkopien.

Tests, die zu den Inhalten gehoeren, liegen bei ihnen (`unterricht/kurse/<kurs>/tests/`,
`src/quarto/_local/tests/`) und laufen mit `inv test-inhalte`; `inv test` prueft das Werkzeug.

**Manuell:**


```sh
git clone <repo-url>
cd material-datenbank
# Optional: eigenes Unterrichtsmaterial und eigene H5P-Kurse (getrennte Repos, damit Quellen
# nicht mit den Werkzeugen im selben Git landen) als Arbeitskopien einhaengen:
# git clone <inhalts-repo> unterricht
# git clone <kurs-repo> unterricht/kurse
# Ohne diese Ordner laufen Werkzeuge und Tests unveraendert; `unterricht/` ist gitignoriert.
inv setup      # pip install -e ., .env anlegen, H5P-Libraries, Playwright-Browser
# Zum Mitarbeiten (Testwerkzeuge): inv setup --entwicklung bzw. ./install.sh --entwicklung
inv doctor     # Umgebungspruefung mit Installationshinweisen
```

Manuell statt `inv setup`: `pip install -e .` im Repo-Root. Optional fuer die
Schulportal-Anmeldung bei Moodle-Zielen: `inv setup --schulportal` bzw.
`pip install -e src/sph_login`. Fuer H5P-Kurse
zusaetzlich `inv kurse.update-h5p-libraries`; fuer Moodle-Uploads `.env.example`
nach `.env` kopieren und Zugangsdaten eintragen.

Neueste Library-Versionen aus dem lokalen h5p-dev-Repo uebernehmen (packt die
neuesten `.h5p`-Dateien aus `<h5p-dev>/export/` nach `ressourcen/libraries/`
und `.h5p-runtime/libraries/`; der naechste `inv kurse.build` packt alle
Inhalte neu):

```sh
inv kurse.sync-h5p-dev --h5p-dev-dir=<pfad>/h5p-dev
```

## Schnellstart

```sh
inv -l                                  # alle verfuegbaren Tasks anzeigen
inv build --source <pfad.zur.datei.qmd>  # einzelnes Dokument nach PDF bauen
inv preview --source <pfad.qmd>         # Live-Vorschau im Browser
inv material-ui                         # Web-App unter http://127.0.0.1:8765
inv plugin-list                         # Material-UI-Plugins mit Status anzeigen
```

Architektur und API-Vertraege: [docs/architecture.md](docs/architecture.md) und
[src/material_ui/README.md](src/material_ui/README.md).

## Klausur- und Arbeitsblatt-Syntax

Klausuren und Arbeitsblaetter werden mit semantischen Markern geschrieben
(`[Deckblatt: ...]`, `[Schuelerfelder]`, `[Skizze ...]`, `[Einheitskreis 75]`,
`[Modell ...]`). Die vollstaendige Marker-Referenz steht in
[docs/klausur-syntax.md](docs/klausur-syntax.md).

## Build

```sh
make
```

Einzeldokument:

```sh
make unterricht/informatik/klasse-11/klausuren/klausur-e2-25-26/klausur-e2.qmd
```

Direkt mit Invoke:

```sh
inv build
inv build --source unterricht/informatik/klasse-11/klausuren/klausur-e2-25-26/klausur-e2.qmd
inv build --source unterricht/informatik/klasse-11/klausuren/klausur-e2-25-26/klausur-e2-loesung.qmd
```

Quarto erzeugt die Build-Dateien zuerst im jeweiligen Materialordner. Nach
einem erfolgreichen Build verschiebt `src/project_tasks.py` alle Ausgaben in
den zentralen, ignorierten Build-Ordner auf Repo-Ebene: PDFs nach
`build/pdf/<quellpfad>/`, LaTeX- und sonstige Build-Artefakte (`.tex`, `.log`,
`.aux`, alte `.typ` usw.) nach `build/artefakte/<quellpfad>/`. Der Site-Export
der Kurse liegt unter `build/site/`. Der ganze Ordner `build/` wird weder
committet noch synchronisiert und laesst sich jederzeit loeschen --
`inv build-status` zeigt Groessen und groesste PDFs, `inv build-prune`
entfernt verwaiste PDFs (Quelle geloescht) und mit `--aelter-als <tage>`
auch alte.

PDF-Politik: In `unterricht/` liegen keine PDFs -- `inv check-output-layout`
erzwingt das. Build-PDFs entstehen nur in `build/pdf/`, PDF-Quellen und
importierte Original-PDFs werden mit `inv pdf-erschliessen` in die
Wissensbasis unter `wissen/` verschoben (Arbeitsblaetter nach
`wissen/arbeitsblatt/<klasse>/<thema>/`, Curricula nach
`wissen/<fach>/curriculum/`). Grossdateien und nicht regenerierbare
Endprodukte (z. B. Felix-Druckbuendel, Rechenbausteine-Hefte) liegen im
ignorierten `archiv/`-Ordner im Repo-Root.
Direkte `quarto render`- und `quarto preview`-Aufrufe werden durch einen
`pre-render`-Hook in `_quarto.yml` abgewiesen. Build, Material-UI und
Onlyoffice-Import geben ihre Render-Subprozesse gezielt frei. Fuer die Vorschau
`inv preview --source <pfad.qmd>` verwenden; deren Artefakte werden beim Beenden
umsortiert. Die Sperre schuetzt vor versehentlichen Aufrufen innerhalb dieses
Quarto-Projekts, nicht vor absichtlichem Umgehen der Projektkonfiguration. Mit
`inv check-output-layout` lassen sich versehentlich neben Unterrichts-QMDs
abgelegte PDFs finden, auch wenn Git sie ignoriert. Fremdmaterial ohne
zugehoerige QMD wird dabei nicht beanstandet.
Einzelne Arbeitsblaetter, Klausuren, Klassenarbeiten und Nachpruefungen liegen
jeweils nach Dokumenttyp in einem eigenen Unterordner zusammen mit ihren Assets.

Die Render-Muster in `_quarto.yml` beginnen mit `/unterricht/`. Der fuehrende
Slash verankert sie an der Quarto-Projektwurzel, damit Quarto beim Rendern
keine Kurs-Builds oder Site-Exporte durchsucht.

Fördermaterial online (PDFs in die Ordnerstruktur der Online-Plattform kopieren):

```sh
inv foerder-online                 # Blätter nach build/foerder-online/<thema>/<Stufe>/ kopieren
inv foerder-online --build         # vorher fehlende und veraltete PDFs neu bauen (nacheinander)
inv foerder-online --loesungen     # Musterlösungen zusätzlich in je einen Unterordner Loesungen
inv foerder-online --aufraeumen    # PDFs im Ziel löschen, die es in der Quelle nicht mehr gibt
inv foerder-online --trocken       # nur anzeigen
inv foerder-online --ziel ~/upload/foerdermaterial   # anderer Zielordner (oder $FOERDER_ONLINE_ZIEL)
```

Neue Diagnose- und Förderangebote werden pro Lerneinheit beschrieben; siehe
[Lernstand und Förderung](docs/lernstand-und-foerderung.md) für Aufbau, UI, Export und Upload.

Die bisherigen Ordnernamen der Plattform stehen in der Einheitenbeschreibung
(`online_pfad`); für noch nicht migrierte Materialien in `src/foerder_online.py`
(`ONLINE`, z. B. `Stufe1` bei Division und `Stufe 1a` bei Operationsverständnis).
Ordner ohne Eintrag (Überschlag, Unterrichtsmaterial) werden gemeldet und mit
`--alles` mitkopiert. `inv clean --trocken` zeigt lokale Build-Artefakte, ohne
etwas zu loeschen; `inv clean` entfernt den zentralen Build-Ordner `build/`
samt `.quarto/`, laesst dabei aber `build/scratch/` stehen. Mit
`inv clean --artefakte` werden zusaetzlich die lokalen Scratch-Ausgaben unter
`build/scratch/` entfernt.

Onlyoffice-Dokumente seitenstabil nach QMD importieren (Plugin `office`,
einmalig `inv plugin-enable office`):

```sh
inv import-onlyoffice \
  --source _eingang/onlyoffice/klasse-10/trigonometrie \
  --ziel unterricht/mathematik/klasse-10/trigonometrie/arbeitsblaetter
```

Der Import erzeugt pro `.docx` zwei QMDs und legt das von LibreOffice
gerenderte Original-PDF neben der DOCX-Quelle im `_eingang/` ab. Von dort
wird es in die Wissensbasis erschlossen:

```sh
inv pdf-erschliessen \
  --quelle _eingang/onlyoffice/klasse-10/trigonometrie \
  --ziel arbeitsblatt/mathematik/klasse-10/trigonometrie \
  --verlinken unterricht/mathematik/klasse-10/trigonometrie/arbeitsblaetter
```

Das PDF landet unter `wissen/arbeitsblatt/<klasse>/<thema>/`, per SHA-256
dedupliziert (identische PDFs werden nur einmal gespeichert) und in
`wissen/_pdf-erschliessung.json` verzeichnet. `--verlinken` setzt in den
QMDs die `material.import.source-pdf`-Referenz auf das erschlossene PDF.

Der Import erzeugt pro `.docx` zwei QMDs:

- `<name>.qmd`: seitenstabil, bettet das von LibreOffice gerenderte Original-PDF
  per `pdfpages` ein und wird direkt gerendert.
- `<name>-entwurf.qmd`: editierbarer Pandoc-Entwurf mit extrahierten Medien.
  Diese Fassung ist als Startpunkt zum Nachbauen gedacht; Seitenzahl und Layout
  sind dort noch nicht garantiert.

Beim Standardlauf rendert die Pipeline das seitenstabile QMD und bricht ab,
wenn die Seitenzahl nicht exakt der Onlyoffice-PDF-Ausgabe entspricht.
`--overwrite` ersetzt vorhandene QMDs, `--no-draft` laesst den Entwurf weg,
`--no-validate` ueberspringt Rendern und Seitenpruefung.

Live-Vorschau:

```sh
make preview
inv preview
```

Lokale Material-UI fuer Arbeitsblaetter:

Als Desktop-App unter Linux installieren:

```sh
inv material-ui-install
```

Danach erscheint **Material UI** im Anwendungsmenue. Dort per Rechtsklick an den
Dash/Dock anheften. QMD-Dateien im Repository lassen sich in Nautilus per
Doppelklick oder **Oeffnen mit → Material UI** laden. Der Starter startet den
lokalen Server bei Bedarf und oeffnet ein eigenes Chromium-App-Fenster mit der
gewaehlten Datei. Chromium oder Google Chrome muss installiert sein.
Bei QMDs ausserhalb des Repositories erscheint ein Importdialog: Zielpfad waehlen
und **Importieren und oeffnen** bestaetigen. Die QMD wird kopiert; das Original
bleibt erhalten. Verknuepfte Bilder, Templates und weitere Dateien werden nicht
mitkopiert und muessen bei Bedarf separat uebernommen werden. Vorhandene Dateien
werden nicht ueberschrieben. Abbrechen verwirft den Importauftrag. Noch offene
Importauftraege laufen nach 24 Stunden ab.
Der Installer aktualisiert auch den Icon-Cache. Unter GNOME/Wayland nutzt das
App-Fenster bei vorhandenem XWayland dessen Fensterzuordnung fuer das eigene
Dock-Icon. Bereits laufende App-Fenster nach einer Starter-Aktualisierung schliessen
und erneut oeffnen, damit Chromium die neuen Startoptionen uebernimmt.
Der Server bleibt nach dem Schliessen des Fensters fuer weitere Aufrufe aktiv;
Server- und Browserlogs liegen unter `~/.local/state/material-ui/`
(bzw. unter `$XDG_STATE_HOME`). Verwaltung ohne App-Fenster:

```sh
inv material-ui-server --action status
inv material-ui-server --action start
inv material-ui-server --action stop
inv material-ui-server --action restart
```

Vor Stop/Neustart Aenderungen speichern. Beim Oeffnen startet der Starter einen
fehlenden Server und startet einen veralteten Server nach Code-Aenderungen
automatisch neu. Einen aktuellen Server verwendet er weiter. Alternativ nach
Installation des Python-Pakets: `material-ui --server status` (bzw. `start`, `stop`,
`restart`). Zum manuellen Start im Browser:

```sh
inv material-ui
```

Die Webapp oeffnet `http://127.0.0.1:8765` und verbindet Clipboard-/Drag-and-drop-Import
mit QMD-Bearbeitung und Quarto-Render-Vorschau. Beim Auswaehlen einer `.qmd` wird
automatisch das zugehoerige vorhandene PDF gesucht (zentral unter `build/pdf/`,
direkter Ausgabeort, `build/`) und angezeigt. Fehlt das PDF oder ist es aelter als die QMD, wird es bei
aktiviertem Auto-Render auch direkt nach dem Oeffnen erzeugt. Ohne Auto-Render weist
die Vorschau auf den Button „Rendern“ hin; Renderfehler werden angezeigt.
QMD-Aenderungen werden nach kurzer Pause automatisch
gespeichert, neu gerendert und in der Vorschau geladen. Wird die Quelle waehrend
eines Renderns gespeichert, laeuft dieser Render fertig; anschliessend wird der
neueste gespeicherte Stand gerendert. Mehrere Aenderungen werden dabei zu einem
einzigen Folgerender zusammengefasst. Importierte Bilder werden als
`assets/<name>-original.png`, `assets/<name>-clean.png` und `assets/<name>.meta.yaml`
neben der gewaehlten `.qmd`-Datei. Einfache Bearbeitungen: Zuschneiden, Graustufen,
gruenen Hintergrund aufhellen und Bereiche weiss ueberdecken.

Der einklappbare Index links zeigt Ordner, benachbarte Materialien und die
Ueberschriften des aktuellen Dokuments. Ueber die Ordnersuche lassen sich auch
Pfadenden wie `10/trigonometrie` oeffnen. Bei Kursen lassen sich Kapitel aufklappen
und einzelne Aktivitaeten zur Bearbeitung ihrer Quelldatei und zur Vorschau
auswaehlen. Aenderungen werden lokal gespeichert; die Aktivitaetsvorschau kann
anschliessend aktualisiert werden. Dokument- und Kursaktionen (einschliesslich
Audit und Moodle-Aktionen) stehen unten im Index.

Voraussetzungen und Pruefung der Installation: siehe oben (`inv doctor`).

Architektur, API-Vertraege und Regressionstests der Material-UI sind in
[`src/material_ui/README.md`](src/material_ui/README.md) beschrieben.
Die gemeinsame Build- und Kursarchitektur, Exportregeln und Prüfabläufe stehen
in [`docs/architecture.md`](docs/architecture.md). `inv test` startet die gesamte
Testsammlung; dafür die Entwicklungsabhängigkeiten mit `pip install -e '.[dev]'`
installieren.
Die Testsammlung umfasst zusätzlich `src/quarto/_local/tests/` (Tests privater Vorlagen,
nur lokal vorhanden; fehlt der Ordner, entfallen sie). Den öffentlichen Bestand ohne private
Vorlagen prüft `MATERIAL_PRIVATE_DIR=_nicht_vorhanden inv test`. Vor dem Weitergeben des
Werkzeugrepos: `inv oss-pruefen` (und einmalig `inv oss-hook` für den pre-commit-Hook).

## Zeichnungen

TikZ-Zeichnungen in `assets/*.tex` werden vor `inv build` automatisch als SVG
kompiliert. Die SVGs werden anschliessend wie normale Bildassets in Quarto
eingebunden.

Regeln fuer TikZ-Zeichnungen:

- Verwende ausschliesslich benannte Koordinaten.
- Definiere alle Masse am Anfang als Variablen.
- Masslinien liegen mindestens 6 mm ausserhalb der Figur.
- Masshilfslinien enden 1 mm vor der Figurenkante.
- Beschriftungen werden mit Anchors positioniert, nicht durch Leerzeichen.
- Keine manuell geschaetzten Pixel- oder Textabstaende.
- Verwende LaTeX fuer Brueche und Einheiten.

## Excalidraw-Decks

- `inv deck --source <outline.md>` erzeugt aus einer Markdown-Outline ein
  `.excalidraw`-Deck (One-Shot-Scaffold): `## ` beginnt eine Folie, Bullets
  werden zu Textbloecken, `![](bild.svg)` bettet ein Bild ein, `[Modell …]`
  zeichnet ein Modell-Kuerzel beim Generieren automatisch als SVG,
  `[Infobox: Titel]` … `[/Infobox]` (ebenso Warnbox/Tippbox) rahmt den Inhalt
  als farbigen Kasten mit Titelzeile ein. Danach ist die
  `.excalidraw`-Datei die Quelle der Wahrheit; existierende Decks werden nicht
  ueberschrieben (`--force` nur bewusst, Anmerkungen gehen verloren).
- Schriften sind im Outline-Frontmatter einstellbar: `font-ueberschriften:`
  (Standard `Excalifont`) fuer Titel und `###`-Abschnitte, `font-text:`
  (Standard `Normal`, Helvetica-artig) fuer Absaetze und Bullets. Verfuegbare
  Schriften: Excalifont, Normal, Code, Hand-drawn, Nunito, Lilita One,
  Comic Shaans.
- `inv deck-present` baut (falls noetig) die Present-App und liefert sie unter
  `http://127.0.0.1:4180/` aus. Frames sind Folien, PageDown/PageUp blaettert,
  waehrend der Praesentation kann frei annotiert werden.
- `inv deck-print --source <outline.md>` erzeugt aus derselben Outline eine
  druckbare QMD neben der Outline; Modell-Kuerzel und Box-Marker stehen
  unverändert in der QMD und werden beim Bauen vom Projektfilter gezeichnet
  (die Filterangabe wird automatisch mitgeschrieben). Das PDF entsteht wie
  ueblich mit
  `inv build --source <outline.qmd>` in `build/pdf/`. Die Outline bleibt die Quelle,
  die QMD laesst sich jederzeit neu erzeugen (manuelle Aenderungen werden ohne
  `--force` nicht ueberschrieben).
- `inv deck-slides --source <outline.md>` erzeugt zusaetzlich eine Slide-QMD
  (`<name>-slides.qmd`), die die Outline als echte Folien rendert: 16:9-Seiten
  (160 × 90 mm), Titelfolie, eine `##`-Folie pro Seite, handschriftliche
  Excalidraw-Schrift (Virgil 3 YOFF, Paket `rnote-fonts`; ohne das Paket fällt
  das Template auf Aptos zurueck). Rendern ebenfalls mit
  `inv build --source <name>-slides.qmd`.
- In der Material-UI hat jede `.excalidraw`-Datei eine Play-Schaltflaeche, die
  das Deck im Praesentationsmodus oeffnet; Speichern schreibt die Szene mit
  Revisionspruefung in die Repository-Datei zurueck.
- Details: `src/excalideck/present/README.md` und `src/material_ui/README.md`.

## Quellenstruktur

```text
unterricht/
  informatik/
    klasse-11/
      klausuren/
        klausur-e2-25-26/
          klausur-e2.qmd
          klausur-e2.pdf
  mathematik/
    klasse-09/
      kreise/
        arbeitsblaetter/
          umfang-durchmesser/
            umfang-durchmesser.qmd
            umfang-durchmesser.pdf
            assets/
    quadratische-funktionen/
      klassenarbeiten/
        klassenarbeit2526/
          klassenarbeit-4-2526.qmd
          klassenarbeit-4-2526.pdf
    klasse-06/
      nachpruefungen/
        nachpruefung-klasse-6-bruchrechnung-2026/
          nachpruefung-klasse-6-bruchrechnung-2026-schriftlich.qmd
          nachpruefung-klasse-6-bruchrechnung-2026-muendlich.qmd
          assets/
  kurse/
    python-2026/
      index.mdx
      chapters/
  organisation/
    foerderplaene/
      foerderplan-vorlage.qmd
      assets/
src/
  quarto/
    templates/
      latex-template.tex
      exam-header.tex
    filters/
      exam.lua
  tests/
    wissensbasis/
```

## Wissensbasis (Fachdidaktik)

Jeder Ordner `ressourcen/quellen/<fach>/` (z. B. `ressourcen/quellen/mathematik/`) wird rekursiv und formatoffen erfasst
(PDF, DOCX, PPTX, ODF, EPUB, HTML, Text, Bilder per OCR). Dazu kommen Webquellen: `invoke wissen-web <url>` legt
eine Seite als Lesekopie in `ressourcen/quellen/<fach>/web/<host>/` ab (siehe unten). Die Dateien in `ressourcen/quellen/<fach>/` bleiben
die einzige Quelle; alles Abgeleitete liegt in `wissen/<fach>/` und lässt sich jederzeit neu erzeugen. Neue Dateien
oder Ordner werden beim nächsten Update automatisch aufgenommen, ein neuer Ordner `ressourcen/quellen/informatik/` legt ein
neues Fach an.

```sh
invoke wissen-update                 # scannen, Text extrahieren, Suchindex aktualisieren
invoke wissen-web "https://…"        # Webseite als Lesekopie speichern und gleich erschließen
invoke wissen-status                 # Stand ohne Scan
invoke wissen-suche "Grundvorstellung Bruch"   # Volltext über Quellen, Karten und Dossiers
invoke wissen-suche fehlerkultur --karten      # nur Karten und Dossiers (--ohne-literatur: Literaturseiten ausblenden)
invoke wissen-lies grundvorstellungen --von 4 --bis 5   # Seiten einer Quelle lesen
invoke plugin-enable ocr             # einmalig, Voraussetzung fuer OCR und Verkleinern
invoke wissen-ocr --match "Fehler"   # gescannte PDFs per OCR nachziehen (langsam, ca. 2 s/Seite)
invoke wissen-komprimieren --trocken # PDFs verkleinern testen, ohne etwas zu ändern (danach ohne --trocken)
invoke wissen-update --ocr --komprimieren   # Scan, OCR, dann Verkleinerung, dann Index (in dieser Reihenfolge)
invoke wissen-test                   # automatische Tests der Werkzeuge
invoke wissen-check                  # Tags, Seitenangaben und Zitate der Karten prüfen
invoke wissen-aufnehmen              # neue Karten ausdrücklich aufnehmen oder zurückstellen
invoke wissen-freigeben              # fehlerfreie Entwürfe ausdrücklich freigeben
invoke wissen-sortieren              # Karten nach Bereich und Quelle einsortieren
invoke wissen-pflegen                # prüfen, aufnehmen, freigeben und einsortieren
invoke wissen-build                  # INDEX.md, Themen-Kompaktseiten, Detailseiten und Prüffragen-Listen erzeugen
```

- `wissen/<fach>/_config/quellenarten.yaml` ordnet Pfaden eine Quellenart zu (theorie, zeitschrift, schulbuch, web, …).
- `wissen/<fach>/_config/taxonomie.yaml` ist das freigegebene Vokabular für Themen, Kompetenzen und Prinzipien.
- `wissen/<fach>/quellen/<id>.md` (Dossier) und `karten/<id>/*.md` (Karteikarten) enthalten die Erschließung.
  Jede Karte nennt Quelle, Fundstelle (`seite:` = PDF-Seite, bei Webquellen der Abschnitt der Lesekopie) und ein
  wörtliches Zitat; `wissen-check` prüft, dass das Zitat dort steht. Einstieg und Arbeitsweise (auch für KI): `wissen/README.md`. Ändert sich eine Quelle, meldet `wissen-update` das Dossier als veraltet.
- `wissen/<fach>/vorlagen/<id>/*.md` enthält Aufgaben- und Arbeitsblattvorlagen mit Parametern, Modellen und
  Markdown-Shortcuts. Diese Vorlagen werden suchindexiert, aber nicht wie Belegkarten gegen wörtliche Zitate geprüft.
- `wissen/.cache/` (Textcache, Suchindex) ist nicht versioniert.

### Webquellen

`invoke wissen-web "<url>"` holt eine Seite und legt sie als **Lesekopie** in
`ressourcen/quellen/<fach>/web/<host>/<seite>.md` ab: Kopfzeilen mit Adresse, Titel und Abrufdatum, darunter der Text als
schlichtes Markdown (Überschriften, Listen, Auszeichnung und Links bleiben erhalten). Navigation, Kopf- und Fußzeilen,
Suchformulare und Cookie-Banner werden weggelassen. Danach läuft automatisch `wissen-update`.

- **Maßgeblich ist die Kopie, nicht die Live-Seite.** Zitate werden gegen sie geprüft, und das Dossier nennt mit
  `url:` und `abgerufen:` (beides Pflicht, `wissen-check` besteht darauf), worauf sie sich bezieht.
- Fundstelle einer Karte ist der **Abschnitt** der Kopie (rund 3000 Zeichen), nicht eine Seitenzahl;
  `invoke wissen-lies <id> --von 1 --bis 3` zeigt die Abschnitte.
- Ein erneuter Aufruf **überschreibt nur bei geändertem Inhalt** („unverändert“, „aktualisiert“). So bleibt der Hash
  stabil; ändert sich die Seite wirklich, meldet `wissen-check` Dossier und Karten zur Durchsicht.
- Seiten, die ihren Inhalt erst per JavaScript nachladen, kommen nicht durch (Abbruch mit Hinweis). Solche Seiten von
  Hand als PDF oder Text sichern und in `ressourcen/quellen/<fach>/web/` ablegen.
- `--name kurzname` setzt den Dateinamen, `--fach informatik` das Fach, `--no-update` überspringt den Scan.

### Verkleinern der PDFs

`wissen-komprimieren` verkleinert Scans mit Ghostscript, aber erst **nach** der OCR (Dokumente mit Status `needs_ocr` werden
übersprungen). Das Profil richtet sich nach der Quellenart: `lesen` (150 dpi) für Bücher und Aufsätze, `drucken` (200 dpi,
gedacht für DIN A4) für Hefte, Übungen und Kopiervorlagen. Einstellungen und Schwellen stehen in
`wissen/<fach>/_config/quellenarten.yaml` (`komprimierung:`); eine Regel kann mit `profil:` überschreiben.

Das **Original wird ersetzt** (kein Backup im Repo), aber nur, wenn alle Tests bestehen: gleiche Seitenzahl und -größe,
Sichtvergleich von 5 Seiten, Textschicht bzw. OCR-Vergleich gegen den OCR-Text des Originals, `qpdf --check`, mindestens
10 % Ersparnis. Danach werden Hash in Manifest, Dossiers und Karten sowie der Textcache umgestellt, die `id` bleibt.
Wird der Lauf mitten drin unterbrochen, schließt das nächste `wissen-update` die Umstellung ab. Bestandene und gescheiterte
Dokumente werden gemerkt (`--erneut` wiederholt sie).

Ausgenommen werden PDFs mit Formularfeldern, Anhängen oder Passwort (Ghostscript würde Felder und Anhänge stillschweigend
verwerfen), Dateien unter 3 MB und Dateien, die höchstens 1,2-fach über der Zielauflösung liegen; in diesen Fällen bleibt das
Original. Bereits Verkleinertes wird nie ein zweites Mal verkleinert. Verliert Ghostscript bei einem beschädigten PDF Seiten, wird einmal mit einer
mit qpdf reparierten Fassung neu versucht; gelingt auch das nicht, bleibt das Original.

**Original zurückgelegt?** Wird eine Datei erkannt, die das Original eines komprimierten Buchs ist (Hash `vorher_sha256`),
behält das Dokument seine `id`, den OCR-Text und die Karten (Status `wiederhergestellt`, der nächste Lauf komprimiert erneut).
Liegt das Original neben der komprimierten Fassung, gilt es als **Duplikat** und wird nicht ein zweites Mal gelesen, indexiert
oder verkleinert. Dasselbe gilt für identische Dateien. Verschwindet die komprimierte Fassung, übernimmt das Original deren `id`.

Es läuft immer nur ein schreibender Lauf (Sperre in `wissen/.cache/lauf.lock`). Ein einzelnes defektes PDF oder eine defekte
Seite bricht den Lauf nicht ab, sondern wird im Manifest vermerkt (`ocr_fehlerseiten`, Status `fehler`).

## Lizenz

Dieses Projekt steht unter der MIT-Lizenz, siehe [LICENSE](LICENSE). Das vendorte
`h5p-cli` (MIT, H5P Group) wird mit eigenem Lizenztext ausgeliefert; Hinweise dazu in
[src/course_sync/vendor/NOTICE](src/course_sync/vendor/NOTICE). Schriften (OFL) und weitere
Drittsoftware sind in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) aufgefuehrt. Zur
Mitarbeit siehe [CONTRIBUTING.md](CONTRIBUTING.md), zu Sicherheitsmeldungen
[SECURITY.md](SECURITY.md).
