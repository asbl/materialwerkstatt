# Fördermaterial und persönliche Förderempfehlungen

## Ablage

`foerdermaterial/` liegt neben `unterricht/` und enthält ausschließlich allgemeine
Übungen, Hilfen und Lösungen. Der Bereich ist im Werkzeugrepo ignoriert und für
eine eigene private Versionierung vorgesehen; ein Remote wird nicht automatisch
angelegt. Klausuren und Musterlösungen bleiben im privaten Unterrichtsrepo.

`foerderempfehlungen/` enthält Schülerdaten, Klausurauswertungen, individuelle
Förderpläne und persönliche Ausgaben einschließlich temporärer Renderdateien.
Der gesamte Ordner ist von Git und über `.sync-exclude.lst` vom Datei-Sync
ausgeschlossen. Keine `.gitkeep`-Datei und kein eigenes Git-Repository anlegen,
kein `git add -f`. Der Ordner hat lokal Berechtigung 0700. Liegt der Sync-Root
oberhalb des Projekts, muss der Ausschluss zusätzlich im Sync-Client eingetragen
werden; die Datei allein bestätigt keinen aktiven Client-Ausschluss.

Der allgemeine Materialeditor und sein QMD-Index sperren diesen Bereich. Das ist
keine Betriebssystem-Sandbox: Plugins laufen als vertrauenswürdiger Python-Code.
Ein späteres Förderplanungsplugin muss eigene private Speicherung und Builds
verwenden. Persönliche Dateien gehören niemals in `build/`, Projektlogs, den
allgemeinen Export oder an externe KI-Dienste. Getrennte verschlüsselte Backups
der nicht regenerierbaren Schülerdaten sind erforderlich.

## Allgemeine Förderangebote: Schema 1

Pro Angebot liegt eine `angebot.yaml` unter
`foerdermaterial/<fach>/<thema>/<angebot>/`. Die ID bleibt bei Verschiebungen
stabil und ist im gesamten Fördermaterialbestand eindeutig.

```yaml
schema: 1
id: mathe-zahlen-vergleichen-basis
titel: Zahlen vergleichen und ordnen
zentrale_kompetenzen:
  - fach: mathematik
    id: zahlen-vergleichen-ordnen
niveau: basis
dauer_minuten: 15
aufgaben:
  - quelle: ab_zahlen-vergleichen.qmd
    fundstelle: 'Aufgaben 1a–d und 2'
hilfen:
  - quelle: ab_zahlen-vergleichen.qmd
    fundstelle: 'Beispiel vor Aufgabe 1'
loesungen:
  - quelle: ab_zahlen-vergleichen-loesung.qmd
    fundstelle: 'Lösungen zu Aufgaben 1 und 2'
```

Pflicht: `schema`, `id`, `titel`, `zentrale_kompetenzen`, `niveau`, `aufgaben`.
`hilfen`, `loesungen` und `dauer_minuten` sind optional. Niveau ist eine fachliche
Bezeichnung, keine automatisch geordnete Skala. Fundstellen sind verbindliche,
manuell geprüfte Angaben; der Validator prüft nicht die tatsächliche Nummerierung
im Dokument. Fehlende oder leere Hilfs-/Lösungslisten bedeuten kein hinterlegtes
Angebot. Es gibt keine automatische Veröffentlichungsfreigabe.

Quellen sind relativ zur `angebot.yaml` und müssen nach Auflösung von `..` und
Symlinks innerhalb von `foerdermaterial/` liegen. Nur QMD-Quellen sind zulässig.
Die Dateiexistenz prüft `audit`, Struktur und Kompetenzverweise prüft `validate`.
`material_core.foerdermaterial.catalog(root)` prüft zusätzlich eindeutige IDs.
Unbekannte Metadatenfelder werden abgewiesen. Die erlaubten Textfelder dürfen
ebenfalls keine personenbezogenen Inhalte enthalten.

## Bestehende Lernstandskompetenzen verbinden

Lokale IDs und Förderstufen bleiben erhalten. In `einheit.yaml` bekommt jede
lokale Kompetenz eine explizite Liste zentraler Referenzen:

```yaml
lernstand:
  # Weitere bestehende Pflichtfelder bleiben unverändert.
  kompetenzen:
    - id: vergleichen
      titel: Zahlen vergleichen
      zentrale_kompetenzen:
        - fach: mathematik
          id: zahlen-vergleichen-ordnen
      stufen:
        - id: basis
          beschreibung: Natürliche Zahlen vergleichen
```

`fach` und `id` identifizieren die zentrale Teilkompetenz. Mehrere Referenzen
sind erlaubt. Unbekannte und doppelte Referenzen werden abgewiesen; identische
Titel erzeugen keine automatische Zuordnung. Alte Einheiten ohne Zuordnung
bleiben gültig, der Lernstandsaudit meldet die ausstehende Zuordnung als Hinweis.
Es werden keine fachlichen Zuordnungen ohne Prüfung am Bestand erfunden.

Die allgemeine Unterrichtsabdeckung „eingeführt/geübt/geprüft“ bleibt vom
personenbezogenen Kompetenzstand getrennt. Bestehende Förderblätter werden in
diesem Schritt noch nicht verschoben; UI, Buildintegration und Migration sind
ein eigener Folgeschritt.
