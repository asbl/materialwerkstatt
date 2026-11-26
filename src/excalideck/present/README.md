# Excalideck Present-App

Präsentationsoberfläche für Excalidraw-Decks: ein Fenster, Frames als Folien,
volles Zeichenrecht während der Präsentation. Basis ist die MIT-lizenzierte
React-Komponente `@excalidraw/excalidraw`; der Build erfolgt mit Vite.

## Start

- Über die Material-UI: `.excalidraw`-Datei in der Ordnerliste suchen und die
  Play-Schaltfläche klicken. Die App lädt das Deck automatisch und speichert
  Änderungen auf „Speichern“ direkt in die Repository-Datei zurück.
- Standalone: `inv deck-present` baut (falls nötig) und liefert die App unter
  `http://127.0.0.1:4180/` aus. Das Deck wird über „Öffnen“ oder Drag-and-Drop
  geladen; „Speichern“ lädt die bearbeitete Szene als Datei herunter.

## Bedienung

Beim Erzeugen eines Decks werden LaTeX-Formeln (`$…$` inline, `$$…$$`
abgesetzt, auch mehrzeilig; alternativ `\(…\)` und `\[…\]`) über Quarto/Pandoc
und Typst als SVG eingebettet. Das gilt auch für Überschriften, Aufzählungen
und rote Lösungstexte. Die SVGs enthalten die Schriftzeichen als Pfade und
benötigen beim Präsentieren keine zusätzlichen Schriftarten oder Netzwerkzugriffe.
Formelhaltige Textblöcke werden als Bild bearbeitet; Änderungen am Formeltext
erfolgen in der QMD-Quelle mit anschließendem Neuaufbau des Decks.
Bereits erzeugte Decks müssen dafür über „Präsentation neu bauen“ aktualisiert werden.

Beim Erzeugen verwendet Typst dieselben Textschriften wie Excalidraw. Dafür
`pip install -e '.[deck]'` und im Ordner `src/excalideck/present` einmal `npm ci`
ausführen. Die Webfont-Teilmengen werden temporär zu einer Typst-Schrift
zusammengeführt; alternativ kann die entsprechende Schrift im System installiert sein.
Nicht unterstützte LaTeX-Befehle und Konvertierungswarnungen brechen den Build
mit einer Fehlermeldung ab. LaTeX-Farbbefehle (`\color`, `\textcolor`) werden
ausdrücklich abgewiesen, weil der Konverter Farben verwirft; für rote Formeln
das bestehende Kuerzel `[Rot Lösung $x=2$]` verwenden.

Sobald ein Deck geladen ist, startet die App automatisch im Präsentationsmodus:
Die komplette Excalidraw-UI (Menü, Werkzeugleiste, Zoom) ist ausgeblendet, nur
die aktuelle Folie und eine schlanke Steuerleiste sind sichtbar.

- Pfeiltasten rechts/links oder PageDown/PageUp: Folie weiter/zurück.
- Annotations-Palette (unten mittig, während der Präsentation):
  - Werkzeuge: Stift (Freihand, ab Laden aktiv), Marker (dicker,
    halbtransparenter Strich zum Hervorheben), Text, Laserpointer
    (verblasst automatisch, wird nicht gespeichert), Radierer,
    Auswahl (Anmerkungen verschieben oder einzeln löschen),
    Verschieben (Hand-Werkzeug: Leinwand schieben, ohne zu zeichnen).
  - Handballen: standardmäßig aktiv – nur der Stift zeichnet, der Finger
    verschiebt die Folie (bei aktivem Zeichenwerkzeug; mit Auswahl-Werkzeug
    malt der Finger wie gewohnt eine Markise, Zwei-Finger-Gesten zoomen und
    verschieben weiterhin). Ein Klick schaltet um: Dann zeichnet der Finger wieder
    (z. B. wenn kein Stift dabei ist). Excalidraw würde den Stift-Modus
    erst beim ersten Stift-Kontakt selbst aktivieren; da der eingebaute
    Umschalter im Präsentationsmodus ausgeblendet ist, startet die App
    den Modus hier direkt und hält der Knopf ihn manuell umschaltbar.
  - Zoom-Steuerung (unten rechts, nur im Präsentationsmodus):
    − / + zoomen heraus bzw. hinein, die Prozentanzeige setzt den
    Zoom auf 100 % zurück, „Fit“ passt die aktuelle Folie wieder ins
    Fenster ein. Im Bearbeitungsmodus übernimmt Excalidraws eigene
    Zoom-Steuerung.
  - Neue Texte erscheinen in Helvetica (besser lesbar als der
    Excalidraw-Standard); im Bearbeitungsmodus bleibt die volle
    Excalidraw-Schriftwahl verfügbar.
  - Farbpunkte: schwarz, rot, blau, grün, orange, violett.
  - Strichstärke für den Stift: dünn, mittel, dick (der Marker nutzt
    eine feste Dicke).
  - Rückgängig/Wiederholen wie Strg+Z bzw. Strg+Umschalt+Z.
  - „Stiftstriche löschen“: entfernt alle Anmerkungen (Freihandstriche) auf der
    aktuellen Folie; Folieninhalte bleiben unberührt, Rückgängig stellt
    alles wieder her.
- Speichern: schreibt die Szene zurück (Material-UI: Repository-Datei,
  Standalone: Download). Strg+S löst das Speichern direkt aus; der orange
  Punkt am Speichern-Knopf zeigt ungespeicherte Änderungen an, und beim
  Verlassen einer ungespeicherten Szene warnt der Browser.
- Ohne Frames ist die gesamte Leinwand eine Folie: die App legt einen
  Pseudo-Rahmen über die Bounding-Box aller sichtbaren Elemente und zeigt
  einen entsprechenden Hinweis an.
- Ältere Decks mit Frames vor ihren Inhalten werden beim Öffnen korrigiert.
  Bereits vor solchen Frames gespeicherte Freihandstriche erscheinen wieder
  über dem Template-Hintergrund. Die Datei wird erst beim Speichern geändert;
  korrekt aufgebaute Decks behalten ihre Ebenenreihenfolge.
- Versionen (Material-UI): listet die serverseitig archivierten Fassungen
  aus `.material-history/` auf; das Laden einer Version ersetzt die Szene
  und führt die separaten Anmerkungen ohne Duplikate wieder zusammen.
- Anmerkungen separat (Material-UI, Voreinstellung): speichert ausschließlich
  Anmerkungen im Sidecar `.material-annotations/`; das Deck selbst bleibt
  unberührt und lässt sich unabhängig weiterbearbeiten.
- Externe Änderungen (Material-UI): die App fragt `GET /api/deck/revision`
  ab und meldet Abweichungen; beim Speichern eines überholten Stands bietet
  der Konfliktdialog „Neu laden“, „Trotzdem speichern“ (mit serverseitiger
  Archivierung) oder „Später“ an.
- Vollbild für den Beamer; Esc verlässt das Vollbild. Während der Präsentation
  sitzt der Knopf oben rechts und zeigt den aktiven Vollbild-Zustand an
  (zusätzlich unter „Weitere Werkzeuge“); im Bearbeitungsmodus oben in der
  Werkzeugleiste.
- Bearbeiten: zeigt die volle Excalidraw-UI wieder (Werkzeuge, Formen, Text);
  „Präsentieren“ kehrt in den Präsentationsmodus zurück.
- Fit: aktuelle Folie in das Fenster einpassen (nur im Bearbeitungsmodus;
  im Präsentationsmodus passt jede Folie beim Wechsel automatisch).

## Entwicklung

- `npm install` und `npm run build` erzeugen `dist/` (gitignored).
- `smoke_test.py` prüft mit Playwright gegen `dist/`: Laden, Navigation,
  Zeichnen und Speichern. In Agent-Shells `env -u LD_LIBRARY_PATH` setzen.
- App-Quelle: `src/App.jsx`. Beim Laden durchläuft die Szene
  `restoreElements()`, damit unvollständige Elemente (z. B. aus Excaligen)
  ihre Pflichtfelder erhalten; ohne diesen Schritt crasht das Hit-Testing.

## Erweiterte Zeichenwerkzeuge

- Beim Öffnen ist **Dünn (2)** eingestellt. Häufige Werkzeuge verwenden Icons
  mit Tooltips und zugänglichen Beschriftungen.
- Das Schloss schützt Rahmen und vorhandene Folieninhalte vor Radierer,
  Auswahl und Verschieben. Bestehende Freihandstriche bleiben radierbar.
  Für Änderungen am Folieninhalt den Schutz unter „Weitere Werkzeuge“ bewusst
  ausschalten. In der Material-UI schaltet dies sichtbar auf das Speichern des
  gesamten Decks um. Neue Zeichnungen und eingefügte Bilder bleiben bearbeitbar.
- **+ → Leerfolie / Rechenkästchen** fügt unmittelbar hinter der aktuellen
  Folie ein. Das Raster füllt die gesamte Folie; sein Hintergrund ist gesperrt.
  Zusatzfolien und ihre Reihenfolge werden auch beim separaten Speichern
  der Anmerkungen erhalten. Bestehende Folien werden nicht verschoben.
- Bilder mit **Strg+V / Cmd+V** einfügen oder das Zwischenablage-Icon verwenden.
  Das Icon benötigt die Clipboard-Berechtigung des Browsers und einen sicheren
  Kontext (HTTPS oder localhost); Tastatur-Einfügen funktioniert auch ohne
  die programmgesteuerte Clipboard-API. Bilder werden auf der aktuellen Folie
  zentriert und mit der Szene bzw. den Anmerkungen gespeichert.
- **Formen** öffnet ein Dropup für Rechteck, Ellipse, Raute, Linie und Pfeil.
  Bei Linien und Pfeilen hält **Weiterzeichnen** das Werkzeug für mehrere
  Striche aktiv (standardmäßig eingeschaltet). Zum Beenden Auswahl oder Esc wählen.
  Umschalt beim Zeichnen begrenzt Formen auf Kreise, Quadrate bzw. feste Winkel.
- **Zeichenoptionen** enthält Strichfarbe/-stärke, Konturstil, Sauberkeit,
  Füllung, Ecken, Pfeiltypen/-spitzen, Deckkraft, Ebenen und Objektaktionen.
  Einstellungen gelten für die Auswahl und für neue Zeichnungen. Gesperrte
  Folieninhalte sind von Änderungen ausgenommen.
- **Geometriehilfen**: Alle drei Hilfen lassen sich an der Fläche oder am
  Verschiebegriff bewegen und direkt am ↻-Griff oder mit zwei Fingern drehen.
  Der Drehgriff zeigt den Winkel und unterstützt Pfeiltasten/Pos1. Er weicht
  Bildschirmrändern und Bedienelementen aus. Die Geometrieoptionen lassen
  sich am ▴-Button einklappen; die Hilfe bleibt dabei bedienbar.
  Lineal und Geodreieck lassen sich außerdem über das
  Winkelfeld (auch mit Dezimalwerten) drehen und mit „Kante nachziehen“ eine
  präzise Linie erzeugen. Das 15°-Raster gilt nur für Drehgesten und lässt sich
  für stufenloses Drehen abschalten. Der ↔-Griff, ein Größenregler und ein
  Prozentfeld skalieren beide Hilfen von 25 bis 300 %. Mit zwei Fingern kann
  gleichzeitig gedreht, verschoben und skaliert werden. Reines Verschieben und
  Skalieren erhält den exakten Ausgangswinkel auch bei aktivem Raster.
  Zwei-Finger-Drehungen werden über 1° erkannt, damit kleine Touch-Abweichungen
  den Winkel nicht verändern; feinere Einstellungen sind am Drehgriff oder im
  Winkelfeld möglich. Doppelklick auf Fläche
  oder Griff öffnet die Einstellungen und fokussiert das Winkelfeld.
  „Zurücksetzen“ stellt 100 % und 0° wieder her. Kanten, Skala und gezeichnete
  Linien passen sich der Größe an; der Nullpunkt bleibt beim Skalieren am Griff
  bzw. über die Einstellungen fest.
  Der Zirkel zeichnet einen Kreis mit einstellbarem Radius. Die transparenten
  Hilfen selbst werden nicht gespeichert. Sie folgen der Folie beim Zoomen
  und Verschieben; Radius und Position beziehen sich auf die Zeichnung. Ein
  Rechenkästchen entspricht dem eingestellten Rasterabstand (standardmäßig
  25 Zeicheneinheiten). Für geführte Linien und Bögen den Stift direkt auf
  einer blauen Kante bzw. dem Kreis ansetzen und ziehen. Es sind keine
  kalibrierten Zentimeter.
- **∑ ExcaliMath** bietet Formeln, Funktionsgraphen und STEM-Formen. Das Paket
  `@excalimath/core` ist auf Version 1.3.1 festgelegt und wird erst beim Öffnen
  nachgeladen. Der Adapter zentriert neue Objekte auf der aktuellen Folie,
  setzt die Frame-Zuordnung und integriert Änderungen in Undo/Redo. SVG-Dateien
  und `customData` werden über die vorhandenen Speicherwege mitgespeichert;
  keine externe Whiteboard-Seite ist erforderlich. Die Plugin-Oberfläche ist
  derzeit englisch. Plotly wird vom Paket bei Graphen zusätzlich geladen.

Integration geprüft anhand der Paket-Typen und des Quellcodes von
[ExcaliMath](https://github.com/tamerUAE/excalimath) sowie der installierten
Version (`node_modules/@excalimath/core/dist/`). Der Browser-Smoke-Test prüft
auch Radierer-Schutz, Einfügeposition, Zeichenoptionen, Clipboard-PNG,
Geometriehilfen, Formeleinfügung und Speichern/Wiederöffnen der neuen Objekte.


## Speichern, Fokus und kompakte Palette

- Die Palette zeigt die häufigen Werkzeuge direkt. Farben liegen unter
  „Stiftfarbe“; Laser, Handballen, Hintergrundschutz, Versionen, Vollbild,
  Bearbeiten und „Stiftstriche löschen“ unter „Weitere Werkzeuge“.
- Zeichenoptionen passen sich an Werkzeug und Auswahl an. Dropups bleiben
  innerhalb des sichtbaren Fensters; Escape gibt den Fokus an den Auslöser
  zurück. Während eines Menüs oder Dialogs wechseln Pfeiltasten keine Folien.
- „Fit“ berücksichtigt die Toolbar und die aktuelle Position des Frames.
  Auch die mobile Excalidraw-Palette ist beim Präsentieren ausgeblendet.
- Speicheranfragen sind pro Sitzung serialisiert. Während einer laufenden
  Speicherung kann weitergezeichnet werden; spätere Änderungen bleiben
  erhalten und als ungespeichert markiert. Speicherzustände sind sichtbar und
  werden zusätzlich über eine Live-Statusregion ausgegeben.
- Die Sidecar-Revision wird aus dem Header `X-Material-Revision` gelesen.
  Änderungen an vorhandenen Deck-Inhalten benötigen vollständiges Speichern;
  sie werden nicht mehr durch eine leere Sidecar-Speicherung als erledigt markiert.
- Dateiwechselschutz bietet Speichern, Verwerfen und Abbrechen. Ein lokaler
  Dateiimport löst die vorherige Bindung an einen Material-Speicherpfad.
  Ungültige Dateien zeigen einen Fehler und ersetzen die Szene nicht.
- Das Laden einer früheren Version schützt ebenfalls ungespeicherte Arbeit und
  verlangt anschließend vollständiges Speichern des Decks.
- Kamerabewegungen lösen keine vollständige JSON-Serialisierung mehr aus.
  Inhaltssignaturen werden pro Element und Version zwischengespeichert;
  gespeicherte Snapshots bleiben auch bei Änderungen am selben Objekt stabil.
- `env -u LD_LIBRARY_PATH python3 src/excalideck/present/regression_test.py`
  prüft die Auditfälle separat; `smoke_test.py` führt sie ebenfalls aus.


## Unterrichtsfunktionen

1. **Folienübersicht:** Das Miniaturen-Icon öffnet eine einklappbare Übersicht.
   Miniaturen anklicken zum Springen; Titel bearbeiten; Folien per Ziehen oder
   Pfeiltasten sortieren und über ⧉ duplizieren. Duplikate erhalten neue
   Element-, Gruppen- und Bindungs-IDs, teilen sich aber vorhandene Bilddateien.
   Reihenfolge und Titel werden in der Szene gespeichert. Bei Änderungen an
   ursprünglichen Folien wird vollständiges Speichern angeboten. Eine alte
   Leinwand ohne Frames bleibt in der Übersicht als einzelne Folie navigierbar.
2. **Lokale Entwurfssicherung:** Nach einer Zeichenpause wird der komplette
   ungespeicherte Stand einschließlich Bildern lokal in IndexedDB gesichert.
   Nach einem Reload bietet die App die Wiederherstellung an; lokale Dateien
   müssen dafür nicht erneut ausgewählt werden. Materialdecks werden ihrem
   Materialpfad zugeordnet. Ein wiederhergestellter Entwurf bleibt ungespeichert,
   bis er bewusst gespeichert wird. Erfolgreiches Speichern bzw. explizites
   Verwerfen entfernt die Sicherung. Maximal 20 Entwürfe bleiben erhalten.
   Die Sicherung ist an Browser und Ursprung gebunden und ersetzt keine
   gespeicherte Deck-Datei oder externe Datensicherung.
3. **Lösungsschritte:** Im Menü mit dem Auge eine Auswahl einem nummerierten
   Schritt zuordnen. Für vorbereitete Originalinhalte ggf. den Hintergrundschutz
   ausschalten. Gebundene Beschriftungen und Gruppen werden mit markiert.
   In der Präsentation beginnen Lösungen verdeckt; „Nächsten Lösungsschritt
   zeigen“ deckt sie in aufsteigender Reihenfolge auf. Sichtbarkeit wird je
   Folie geführt. „Alle Lösungen verdecken“ startet die betreffende Folie neu.
   Im Bearbeitungsmodus bleiben alle Inhalte sichtbar. Die Markierung wird
   mitgespeichert; das vorübergehende Verdecken verändert keine Originalfarben
   oder Deckkraftwerte.
4. **Aktuelle Folie isolieren:** Standardmäßig werden in der Präsentation nur
   die aktuelle Folie und ihre Inhalte gezeigt. Unter „Weitere Werkzeuge“ lässt
   sich dies abschalten. Stiftstriche dürfen über den Folienrand hinausgehen und bleiben der
   aktiven Folie zugeordnet. In der Präsentation werden sie nicht am Rahmen abgeschnitten. Im Editor ist die ganze Szene wieder sichtbar.
5. **Werkzeugprofile und Lieblingsstifte:** Stift, Marker, Formen und Text
   behalten eigene Farbe, Dicke und Deckkraft sowie Konturstil und Sauberkeit.
   Neue Sitzungen verwenden dünnen Stift als Ausgangswert; explizite eigene
   Profile werden lokal gemerkt. In „Stiftfarbe“ stehen drei Lieblingsstifte
   bereit. Mit ☆ den aktiven Stift im gewünschten Platz speichern, mit ✎
   wieder aufrufen. Die Profile bleiben von den eigentlichen Folieninhalten
   unabhängig.
6. **Geführte Geometrie:** Am Lineal und an allen drei Geodreieckskanten kann
   gezogen werden; der Strich wird exakt auf die jeweilige Kante projiziert.
   Die Winkelangabe rastet optional in 15°-Schritten ein. Am Kreis entlangziehen
   erzeugt einen Kreisbogen mit festem Radius. Alternativ Anfangs- und Endwinkel
   eingeben und „Kreisbogen zeichnen“ wählen. Jede abgeschlossene Geste erzeugt
   ein normales, auswählbares Element und einen einzelnen Undo-Schritt.
7. **Mathematische Hintergründe:** Unter dem Raster-Icon zwischen Leerfolie,
   Rechenkästchen, Punktepapier, Linien, Koordinatensystem und Zahlengerade
   wählen. Rasterabstand und Achsenskalierung sind einstellbar. Auf die aktuelle
   Folie anwenden oder eine neue Folie mit der Vorlage einfügen. Vorhandene
   Aufgaben und eigene Anmerkungen bleiben als Elemente erhalten; Papier liegt
   über vollflächigen Vorlagen und unter dem übrigen Inhalt. Punktepapier wird
   als kompakte eingebettete SVG-Datei gespeichert, nicht als Tausende Punkte.
8. **PDF mit Unterrichtsstand:** Unter dem Export-Icon „PDF nur mit Aufgaben“
   oder „PDF mit Lösungen“ wählen. Jede Folie wird in der gespeicherten
   Reihenfolge als eigene PDF-Seite exportiert, einschließlich Bildern,
   ExcaliMath-Formeln und eigenen Anmerkungen. Die Aufgabenfassung lässt die
   als Lösungsschritte markierten Elemente aus. Der Export läuft lokal auch
   ohne Material-Server. Die PDF besteht aus hochauflösenden Bildseiten;
   es gibt keine zusätzliche auswählbare Textebene.

Die neuen Funktionen werden durch `lesson_features_test.py` geprüft. Der
vollständige `smoke_test.py` führt diese Prüfungen ebenfalls aus. Einzelaufruf:
`env -u LD_LIBRARY_PATH python3 src/excalideck/present/lesson_features_test.py`.

Abschließende Prüfung dieser Erweiterung: **202 Browserprüfungen** im vollständigen
Smoke-Test und **16 Deck-/Material-UI-Tests** erfolgreich. Die Browserprüfungen
öffnen die erzeugten PDFs zusätzlich mit PyMuPDF und kontrollieren Seitenzahl,
Lösungsfilter, Bildinhalte und Formeln. Der Hintergrundschutz ist eine
Ansichtseinstellung; Undo/Redo betrifft die Zeichnungen und Inhaltsänderungen.


### Geometrie-Regressionen

`geometry_size_test.py` prüft Größe und Drehung einschließlich der Befunde aus
dem Geometrie-Audit vom Oktober 2026:
Eingabefokus beim Ziehen, kleine Verschiebeflächen per Maus und Touch sowie beide
Griffe in 126 Kombinationen aus Viewport, Größe, Winkel und geöffneten Optionen.
Die Prüfungen laufen auch über `lesson_features_test.py` im vollständigen Smoke-Test.
Für den gezielten Lauf aus dem Repository-Root:

```sh
npm --prefix src/excalideck/present run build
env -u LD_LIBRARY_PATH python3 src/excalideck/present/geometry_size_test.py --touch
```

Die Tests starten einen lokalen HTTP-Server auf einem freien Port und verwenden
ein temporäres Testdeck. `--touch` ergänzt die bestehenden Touch- und
Werkzeugregressionen. Ohne diese Option läuft nur die Geometrieprüfung.

### Schreiben und Zoom

Im Stiftmodus verschiebt ein Finger bei aktivem Zeichenwerkzeug die Ansicht;
zwei Finger zoomen um ihren Mittelpunkt und verschieben gleichzeitig. Das
funktioniert auch außerhalb des Folienrahmens. Auswahl, Text, Bild und Hand
verwenden weiterhin die nativen Excalidraw-Gesten.

Die Palette bietet zusätzlich **Extra fein (0,5)** und **Fein (1)**.
Die Stiftstärke für neue Freihandstriche bleibt auf dem Bildschirm beim Zoomen
gleich. Bereits geschriebene Striche skalieren mit der Folie. Marker und Formen
verwenden weiterhin Zeicheneinheiten. Lieblingsstifte speichern die Bildschirmstärke.

Gezielte Browserprüfung:
`env -u LD_LIBRARY_PATH python3 src/excalideck/present/writing_gestures_test.py`.

Randnotizen erweitern die Seitenfläche beim PDF-Export und in den Miniaturen.
Der Ausschnitt der ursprünglichen Aufgaben bleibt dabei erhalten. Die
Folienzuordnung neuer Striche erfolgt nach dem Absetzen; Undo/Redo und Speichern
übernehmen den vollständigen Strich. Die native Stärkenwahl im Editor wird mit
dem Stiftprofil synchronisiert.
