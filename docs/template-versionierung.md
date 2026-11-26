# Prozess für unveränderliche Template-Versionen

Status: Prozessentwurf auf Grundlage des aktuellen Template- und Buildsystems.
Die technische Versionierung und die Bestandsmigration sind noch umzusetzen.

## Ziel und Grundregel

Eine Änderung der Schriftgröße, Abstände oder anderer Layoutdetails erzeugt eine
neue Template-Version. Bereits angelegte Arbeitsblätter behalten ihre bisherige
Version, auch bei einem vollständigen Neubau. Veröffentlichte Versionen werden
weder überschrieben noch gelöscht. Auch Fehlerkorrekturen ergeben eine neue Version.

Für den Alltag reichen fortlaufende Versionen pro Vorlage: v1, v2, v3.
Beispiel: „Retro · v1 · Grundschrift 11 pt“ und „Retro · v2 · Grundschrift 12 pt“.
Die Größen sind hier Beispiele, keine Aussage über die aktuellen Vorlagen.

## Ablauf im Alltag

1. In der Vorlagenverwaltung eine vorhandene Version auswählen und „Neue Version
   erstellen“ verwenden. Das erzeugt einen bearbeitbaren Entwurf als Kopie.
2. Im Entwurf beispielsweise die Grundschrift ändern. Die freigegebene
   Ausgangsversion bleibt erhalten. Mehrere Änderungen am Entwurf benötigen noch
   keine weiteren Versionsnummern.
3. Eine Vorschau mit einem kurzen und einem mehrseitigen AB sowie einem
   Lösungsblatt bauen. Umbrüche, Tabellen, Kästen und Antwortflächen prüfen.
4. Den Entwurf als nächste Version freigeben und eine kurze Änderungsnotiz
   hinterlegen, etwa „Grundschrift 11 → 12 pt; Zeilenabstand angepasst“.
5. Die neue Version bei Bedarf als Vorauswahl für **neu angelegte** ABs setzen.
   Beim Anlegen wird die konkrete Version gespeichert.
6. Ein vorhandenes AB bleibt auf seiner Version. Für eine Umstellung ausdrücklich
   „Template-Version wechseln“ wählen, Vorschau prüfen und die Änderung speichern.
   Ein Rückwechsel auf die vorherige Version bleibt möglich.

Das Öffnen, Speichern, Kopieren oder Neubauen eines bestehenden ABs aktualisiert
seine Template-Version nicht. Eine Kopie übernimmt zunächst die Version des Originals.
Eine Änderung der Vorauswahl löst keine Bestandsmigration aus.

## Nachfrage beim Rendern

Material-UI und `inv build` fragen vor dem Rendern einmal pro Dokument und
neuer freigegebener Version, ob diese übernommen werden soll. Die Auswahl
wird mit `template-update-reviewed` im Frontmatter gespeichert. Bei Zustimmung
ändert sich zusätzlich die Bindung `template-release`; bei Ablehnung wird mit
der bisherigen Version gerendert. Die nächste neue Freigabe löst erneut eine
Nachfrage aus. Das gilt auch für Auto-Render und bleibt nach Neustarts erhalten.

`inv build` fragt im interaktiven Terminal. Ohne Terminal erfordert eine offene
Entscheidung eine ausdrückliche Wahl mit `--template-update=latest` oder
`--template-update=keep`; ohne diese Wahl wird der Build angehalten. Bereits
beantwortete Angebote werden nicht erneut gestellt. Bei mehreren Dokumenten
gilt eine angegebene Wahl für alle noch offenen Angebote dieses Build-Aufrufs.

## Was eine Version enthalten muss

Die Hauptdatei allein genügt nicht: Aktuell verwenden Vorlagen unter anderem
`exam-functions.typst`, `worksheet-design.typst`, `student-fields.typst` und
designspezifische Layout-Partials. `_quarto.yml` stellt außerdem globale Partials,
Filter und Formatvorgaben bereit. Änderungen dort können das Ergebnis beeinflussen.

Eine Freigabe muss daher ein abgeschlossenes Paket bilden:

- Hauptvorlage und sämtliche transitiven Partials, Includes, Typst-Imports und Assets;
- layoutwirksame Filter und Formatvorgaben als feste Abhängigkeiten;
- die effektiven Standardwerte für Schriftgröße, Schriftfamilie und Seitenlayout;
- Manifest mit Template-ID, Version, Änderungsnotiz und Prüfsummen aller Paketdateien.

Gemeinsame Dateien dürfen zwischen unveränderlichen Paketen dedupliziert werden,
sofern auch die referenzierten Abhängigkeiten unveränderlich und fest adressiert sind.
Ein Verweis auf eine weiter bearbeitete gemeinsame Datei ist keine Versionierung.
Dokumentspezifische Layoutüberschreibungen bleiben Teil der jeweiligen QMD-Datei.

Öffentliche Pakete können beispielsweise unter
`src/quarto/templates/releases/retro/v1/` liegen; bearbeitbare Entwürfe liegen
außerhalb von `releases/`. Vorlagen sind standardmäßig **privat**: Freigaben nicht
ausdrücklich eingebauter Vorlagen liegen im ignorierten Speicher
`src/quarto/_local/template-releases/`, eingebaute in `src/quarto/template-releases/`
(Liste: `src/quarto/builtin-templates.json`, Aufnahme nur über `inv template-freigeben`).
Frühere Frontmatter-Bezüge auf den eingebauten Pfad werden bei privaten Vorlagen automatisch
auf den privaten Speicher aufgelöst; Freigabedateien werden dabei nicht verändert.
Release-Pakete sind Quellen und gehören nicht in den regenerierbaren `build/`-Ordner.

## Bindung eines Arbeitsblatts

Jedes AB erhält eine eindeutige Bindung aus Template-ID und Versionsnummer.
Der Build löst daraus genau das zugehörige Paket auf. Es gibt beim Bauen keinen
automatischen Rückfall auf „neueste Version“. Eine fehlende oder beschädigte
Version führt zu einer verständlichen Fehlermeldung.

Das ist eine neue Funktion: Ein zusätzliches YAML-Feld allein würde heute keine
Dateien einfrieren. Der Resolver muss versionierte Paketpfade vollständig erhalten.
Die aktuelle Auflösung in `BuildService.render_text` erkennt zentrale Vorlagen
anhand des Dateinamens; eine gleichnamige Datei aus einer anderen Version darf
künftig nicht versehentlich an ihre Stelle treten. Globale Partials und Filter
dürfen die Paketabhängigkeiten nicht stillschweigend überschreiben oder doppelt laufen.
UI, Template-Wechsel, direkte verwaltete Builds und Build-Cache müssen dieselbe
Versionsauflösung verwenden. Auch Designinformationen für erzeugte Slides sind
an die Version zu binden, soweit sie zur Ausgabe des Templates gehören.

## Einführung für vorhandene ABs

1. Vor der nächsten Layoutänderung den aktuellen Stand je Vorlage als v1 sichern,
   einschließlich der Abhängigkeiten und lokalen Designs.
2. Bestandsaufnahme aller QMDs: explizite Vorlagen, geerbte Standardvorlagen,
   lokale Kopien und individuelle Partials unterscheiden. Unklare Zuordnungen
   melden und einzeln klären.
3. Bestehende ABs ausdrücklich auf die entsprechende v1 binden. Dabei nur die
   Bindung ändern, keine Schriftgrößen oder Inhalte. Individuelle Abweichungen
   ebenfalls erhalten, gegebenenfalls als eigenes Paket.
4. Vor und nach der Umstellung ausgewählte PDFs mit identischer Werkzeug- und
   Schriftumgebung neu bauen und visuell vergleichen. Seitenzahl allein genügt
   nicht. Erst nach erfolgreicher Prüfung neue Layoutversionen freigeben.

v1 konserviert den heutigen Stand. Falls ein altes PDF noch mit einer inzwischen
veränderten Vorlage gebaut wurde, muss dessen damaliger Stand gesondert aus der
Historie rekonstruiert werden; die heutige Vorlage kann ihn nicht rückwirkend sichern.

## Technische Absicherung und Abnahmekriterien

- Freigeben erzeugt ein neues Paket; eine vorhandene Versionsnummer darf nicht
  überschrieben werden. Manifest und Prüfsummen werden beim Build geprüft.
  Ein CI-Check verhindert zusätzlich Änderungen und Löschungen bestehender Releases.
- Ein Regressionstest veröffentlicht v2 mit anderer Schriftgröße und baut danach
  ein an v1 gebundenes AB erneut: Es verwendet weiterhin vollständig v1.
- Weitere Tests prüfen verschachtelte Partials, globale Vorgaben, fehlende Pakete,
  neue ABs mit aktueller Vorauswahl sowie Wechsel und Rückwechsel der Version.
- Der Build-Cache berücksichtigt Paketversion und sämtliche Abhängigkeiten.
  Ein Neubau darf ein fehlendes oder manipuliertes Paket nicht verdecken.
- PDFs werden ausschließlich über die verwalteten Buildwege erzeugt, beispielsweise
  `inv build --source <pfad.qmd>`. Nach Änderungen an Materialien folgt
  `inv check-output-layout`.

Die Versionierung schützt vor nachträglichen Template-Änderungen. Für langfristig
identische Umbrüche müssen zusätzlich verwendete Schriften und Versionen von
Quarto, Pandoc und Typst beziehungsweise LaTeX reproduzierbar festgehalten werden.
