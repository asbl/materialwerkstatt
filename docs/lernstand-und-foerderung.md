# Lernstand und Förderung pro Lerneinheit

Neue allgemeine Förderangebote werden separat unter `foerdermaterial/` gepflegt.
Das Metadatenschema, die Verbindung zum zentralen Kompetenzkatalog und die
Abgrenzung zu persönlichen Daten unter `foerderempfehlungen/` beschreibt
[Fördermaterial und persönliche Förderempfehlungen](foerdermaterial-und-empfehlungen.md).
Die unten gezeigte bestehende Einheitenstruktur bleibt bis zur Migration lesbar.

Diagnose, Kompetenzraster, Fördermaterial und Nachtest gehören zur Lerneinheit.
Die Quellen liegen im privaten Unterrichtsrepo. Die Werkzeuge und das Datenmodell
liegen im Werkzeugrepo. Veröffentlichungen werden ausschließlich unter `build/`
erzeugt.

## Neue Einheit vorbereiten

Eine Einheit benötigt eine vorhandene `einheit.yaml` (in der Material-UI anlegbar).
Danach legt dieser Befehl ein noch nicht veröffentlichtes Gerüst an:

```sh
inv lernstand.anlegen --einheit unterricht/mathematik/klasse-06/brueche/vergleichen --kennung mathematik-06-brueche-vergleichen --kompetenz brueche-vergleichen
```

Die QMD-Dateien enthalten bewusst nur Entwurfsmarker. Aufgaben, Lösungen und
Kompetenzbeschreibungen vor einer Freigabe ausarbeiten. Die Diagnose folgt dem
bekannten Stil: kurze Aufgaben, Rechenwege, manuelle Auswertung und konkrete
Förderempfehlungen. Eine automatische Bewertung von Schülerantworten ist nicht
Bestandteil dieses Werkzeugs.

## Ablage und Datenmodell

```text
einheit.yaml
diagnose/ab_lernstand.qmd
foerdermaterial/<kompetenz>/<stufe>/ab_uebungen.qmd
foerdermaterial/<kompetenz>/<stufe>/ab_uebungen-loesung.qmd
nachtest/ab_lernstand.qmd
```

`einheit.yaml` erhält einen optionalen Bereich `lernstand`:

```yaml
lernstand:
  schema: 1
  id: mathematik-06-brueche-vergleichen
  version: '1'
  kompetenzen:
    - id: vergleichen
      titel: Brüche vergleichen
      stufen:
        - id: basis
          beschreibung: Gleichnamige Brüche vergleichen
  materialien:
    - id: eingang
      rolle: diagnose
      quelle: diagnose/ab_lernstand.qmd
      online: true
    - id: gleichnamig
      rolle: foerdermaterial
      titel: Gleichnamige Brüche
      kompetenz: vergleichen
      stufe: basis
      quelle: foerdermaterial/vergleichen/basis/ab_uebungen.qmd
      loesung: foerdermaterial/vergleichen/basis/ab_uebungen-loesung.qmd
      online: true
      loesung_online: false
  aufgaben:
    - id: eingang-01
      nummer: '1'
      diagnose: eingang
      kompetenz: vergleichen
      ausloeser: Antwort falsch oder unsicher; Rechenweg gemeinsam prüfen.
      empfehlung: [gleichnamig]
```

IDs bleiben bei Umbenennungen stabil. Die Listenreihenfolge bestimmt die Anzeige
und Förderreihenfolge; Stufen werden nicht numerisch interpretiert. `2a` und `2b`
können unterschiedliche Wege darstellen. Materialien können über relative Pfade
auch auf andere Einheiten unter `unterricht/` verweisen. Leere Empfehlungen sind
zulässig und werden als fachliche Lücke gemeldet. Prüft eine Aufgabe mehrere
Kompetenzen, erhält jede Zuordnung eine eigene ID bei gleicher Aufgabennummer.

Materialrollen sind `diagnose`, `nachtest`, `wegweiser` und `foerdermaterial`.
`online` ist eine ausdrückliche Freigabe; fehlende Freigaben bedeuten `false`.
Für Lösungen sind zusätzlich `loesung_online: true` und die Exportoption
`--loesungen` erforderlich. Ohne diese Option bleiben sie aus dem Paket entfernt.

## Prüfen, bauen und exportieren

```sh
inv lernstand.pruefen --einheit <einheitenordner>
inv lernstand.export --einheit <einheitenordner> --build
inv lernstand.export --einheit <einheitenordner> --build --loesungen
inv check-output-layout
```

Der Export verwendet den verwalteten Build mit dessen Abhängigkeitsprüfung und
Render-Lock. Bereits aktuelle PDFs werden wiederverwendet. Ohne `--build` müssen
die PDFs schon vorhanden sein und einen gültigen Render-Nachweis besitzen.
Fehlende Nachweise erfordern einen verwalteten Neubau mit `--build`. Bei fehlenden Quellen oder einem
Buildfehler bleibt die vorherige Veröffentlichung erhalten.

Unter `build/lernstand/<id>/` entstehen:

- `katalog.json`: Version, Kompetenzen, Materialverweise, SHA-256-Digests und
  Aufgabenempfehlungen; ausschließlich freigegebene Inhalte, keine Quellpfade.
- `index.html`: Vorschauseite mit Downloads und einem aus den Zuordnungen erzeugten Wegweiser.
- `dateien/`: PDFs unter stabilen Material-IDs.
- `paket.zip`: dieselben Dateien für Übertragung oder einen späteren Plattformimport.

Die Material-UI bündelt alle Unterordner eines Lernstandspakets in einer Einheit.
„Lernstand & Förderung“ zeigt Diagnosen, Lösungen, die Kompetenz-Stufen-Tabelle
und Prüfergebnisse. Förderstufen, Empfehlungen und Veröffentlichungsfreigaben
lassen sich dort bearbeiten. Das Veröffentlichungspaket kann heruntergeladen werden; die Option
„Freigegebene Lösungen einschließen“ nimmt zusätzlich ausdrücklich freigegebene
Lösungen mit.
Grundstruktur, neue Kompetenzen und Materialien werden in `einheit.yaml` gepflegt.

## Upload

Ein allgemeiner Upload in ein Webverzeichnis ist vorbereitet:

```sh
inv lernstand.upload --einheit <einheitenordner> --ziel user@server:/srv/lernstand/einheiten --trocken
inv lernstand.upload --einheit <einheitenordner> --ziel user@server:/srv/lernstand/einheiten --build
```

Alternativ konfiguriert `LERNSTAND_UPLOAD_ZIEL` das Ziel. SSH-Zugang und rsync müssen
vorhanden sein. Der Befehl synchronisiert ausschließlich das Unterverzeichnis
`<ziel>/<einheit-id>/`, entfernt dort veraltete Dateien und schreibt nach Erfolg
`build/lernstand/<id>-upload.json`. `--trocken` zeigt nur den geplanten Aufruf und
baut oder überträgt nichts. Zugangsdaten gehören nicht in die Einheitenmetadaten.

Dies veröffentlicht eine eigenständige statische Seite. Es importiert keine
Diagnose in die bestehende Anwendung unter lernstand.example.org.
Deren Serverzugang, Quellcode und Importschnittstelle liegen hier nicht vor;
eine direkte Integration muss nach Prüfung dieser Schnittstelle ergänzt werden.
Es wurde keine Live-Veröffentlichung vorgenommen.

## Migration Klasse 05

Der bisher verstreute Förderkurs liegt unter:

```text
unterricht/mathematik/klasse-05/lernstandsdiagnose/arithmetische-grundlagen/
```

Dort liegen Eingangsdiagnose, Wegweiser, sieben Kompetenzbereiche mit den
bestehenden Stufen und der Nachtest zusammen. Bestehende Dokumentnamen bleiben
für die Kompatibilität erhalten. Gemeinsam genutzte Layouts bleiben unter
`klasse-05/materialgestaltung/`.

`inv foerder-online` bleibt als bisheriger PDF-Export verfügbar. Die expliziten
`online_pfad`-Einträge der Materialien erhalten die bisherigen Online-Pfade
(einschließlich Schreibweisen wie `Stufe1`). `--alles` nimmt weitere freigegebene
Förderblätter mit. Lösungen benötigen auch hier `loesung_online: true`.

Die Zuordnungen übernehmen die vorhandenen Auswertungstabellen. Für die
Eingangsaufgabe 8 (Größen umwandeln) fehlt bisher ein eigenes Förderangebot;
die Prüfung meldet das, statt einen unpassenden Verweis einzutragen.

## Plugin-Grenze

Das eingebaute Plugin `lernstand` heißt in der Oberfläche **Lernstand: Export und
Veröffentlichung**. Es ist standardmäßig aktiviert. Über den Plugin-Dialog oder
Invoke lässt es sich für die Material-UI abschalten:

```sh
inv plugin-disable lernstand
inv plugin-enable lernstand
```

Änderungen wirken nach einem Serverneustart. Bei deaktiviertem Plugin entfallen
Exportroute und Download-Bedienelemente. Diagnoseübersicht, Kompetenz-Stufen-Matrix,
Fördereditor und gespeicherte Zuordnungen funktionieren weiter.

Die Verantwortlichkeiten sind getrennt:

| Teil | Ort | Aufgabe |
| --- | --- | --- |
| Fachliches Modell | `src/material_core/lernstand.py` | Daten lesen, validieren und referenzieren; Lücken prüfen |
| Einheitenverwaltung | `src/material_ui/units.py`, `static/units.js` | Materialien, Kompetenzen und Zuordnungen bearbeiten |
| Veröffentlichungsformat | `src/material_ui/plugins/lernstand/export.py` | PDFs auswählen, Vorschauseite, Katalog und ZIP erzeugen |
| Uploadadapter | `src/material_ui/plugins/lernstand/upload.py` | Paket per rsync übertragen und Erfolg protokollieren |
| Pluginanbindung | `plugins/lernstand/__init__.py`, `assets/plugin.js` | Exportroute und UI-Aktion registrieren |
| Invoke | `src/lernstand_tasks.py` | Befehlsparameter an Kern beziehungsweise Plugin-Dienste übergeben |

Die Plugin-Dienste sind ohne laufende Flask-App nutzbar. Deshalb bleiben die
explizit aufgerufenen `inv lernstand.export`- und `inv lernstand.upload`-Befehle
auch verfügbar, wenn das Plugin im UI deaktiviert ist. Die Abschaltung steuert
die Serverintegration, sie entfernt das installierte Python-Paket nicht.

Die kanonische Exportroute ist `POST /api/plugins/lernstand/export`. Der bisherige
Pfad `/api/units/lernstand/export` bleibt als vom Plugin bereitgestellter Alias
erhalten; bei deaktiviertem Plugin sind beide Routen abwesend. Der Kern importiert
keinen Export- oder Uploaddienst. Ein späterer Adapter für die bestehende
Online-Plattform gehört ebenfalls in das Plugin.

## Absicherung nach dem Audit vom 2026-11-05

Uploads und HTTP-Downloads verwenden einen eigenen, unveränderlichen Paketstand.
Parallele Exporte ersetzen diesen Stand nicht. Nach dem Upload wird zusätzlich
der SHA-256-Digest der übertragenen ZIP im Statusbericht gespeichert; der
Status beschreibt den lokalen Uploadstand, keine unabhängige Remote-Verifikation.

Im bisherigen `foerder-online`-Export enthalten neue Standardziele die
Einheiten-ID. Explizite bisherige Online-Pfade bleiben erhalten; widersprüchliche
Zielbelegungen führen vor dem Kopieren zu einem Fehler. Neue Entwürfe werden bei
einem Fehler während der Anlage zurückgerollt, sodass der Aufruf wiederholbar ist.
