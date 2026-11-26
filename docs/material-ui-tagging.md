# Plan: Tag-gesteuerte Materialstruktur

Ziel: Dateien lassen sich taggen. Langfristig ist die Struktur der Material-UI
nicht mehr ordnergetrieben, sondern tag-gesteuert — oder beides parallel.

## Ausgangslage

- Die Navigation der Material-UI ist ordnergetrieben: `/api/folder`, Breadcrumbs
  und die Ordnerliste in `static/app.js` bauen auf Verzeichnispfaden auf.
- `DocumentService.qmd_entry()` in `src/material_ui/documents.py` leitet
  `subject`, `grade`, `thema` und `kind` aus den Pfadbestandteilen ab
  (`grade_part`, `topic_part`, `infer_kind`). Ordner tragen also semantische
  Bedeutung.
- Es existiert bereits eine formatbewahrende Frontmatter-Infrastruktur:
  `src/material_core/metadata.py` (ruamel.yaml, `read_metadata`, `set_fields`,
  `set_template`) sowie `POST /api/document/metadata` und das Metadaten-Panel
  (`static/metadata-panel.js`) fuer title/subtitle/author/date.
- Das vorhandene "Tags"-Eingabefeld gehoert ausschliesslich zum Bildimport
  (Asset-Metadaten) und ist kein Dokument-Tagging.
- Die Suche (`src/material_ui/search.py`) filtert nach `subject`, `grade` und
  `kind` — jeweils pfadabgeleitet.

## Phase 0 — Datenmodell-Entscheidung

Tags leben im YAML-Frontmatter jeder QMD als Liste:

```yaml
---
title: Einheitskreis
tags: [mathematik, klasse-10, trigonometrie, arbeitsblatt]
---
```

Begruendung: dateilokal, git-diff-freundlich, kein Sync-Problem beim Umbenennen
oder Verschieben, und es nutzt die bestehende Metadaten-Maschinerie. Eine
zentrale Registry-Datei waere eine zweite Quelle der Wahrheit und veraltet
zwangslaeufig. Das Tag-Vokabular ist frei, wird aber aus dem Index aggregiert
(fuer Autocomplete und Zaehlungen).

## Phase 1 — Backend (umgesetzt)

1. `src/material_core/metadata.py`: `set_fields` unterstuetzt neben skalaren
   Zeichenketten auch Listen von Zeichenketten (leere Liste entfernt den
   Eintrag), weiterhin formatbewahrend bezueglich Kommentare, Anfuehrungszeichen
   und Dokumentkoerper.
2. `DocumentService.qmd_entry()`: `tags` aus dem Frontmatter im Index-Entry
   (`tags_from_text`); `DocumentService.tag_counts()` aggregiert das
   Vokabular mit Vorkommenszaehlung.
3. Routen in `src/material_ui/document_routes.py`:
   - `GET /api/tags` — Vokabular mit Vorkommenszaehlung aus dem Index.
   - Abweichend vom urspruenglichen Plan gibt es keinen separaten
     `POST /api/document/tags`: Tags werden ueber die bestehende Route
     `POST /api/document/metadata` mit `fields.tags` geschrieben. Sie laeuft
     damit durch den Editor-Text und den Revisions-/Speichermechanismus,
     statt ihn zu umgehen; eine zweite Schreibroute wuerde
     Speicherkonflikte mit der offenen Editorsitzung riskieren.
4. `src/material_ui/search.py`: `tags`-Filter-Parameter (kommagetrennt,
   UND-Verknuepfung) neben den bestehenden `subject`/`grade`/`kind`-Filtern;
   das Ergebnis fuehrt die Tags mit.

## Phase 2 — Frontend (umgesetzt)

1. Metadaten-Panel (`static/metadata-panel.js`): Tag-Feld (kommagetrennt) mit
   Autocomplete gegen `GET /api/tags` — gleicher Dialog wie Titel/Autor, gleicher
   Speicherweg ueber `POST /api/document/metadata`.
2. Materialauswahl: Umschalter "Ordner / Tags" ueber der Ordnerliste. Die
   Tag-Ansicht zeigt Tag-Chips mit Zaehlung; Auswahl filtert die
   Dokumentliste, Mehrfachauswahl ist erlaubt (UND). Die Ordneransicht bleibt
   unveraendert daneben — das ist das "oder beides".
3. Suche: Das Tag-Feld der Suchmaske filtert die Treffer der Materialauswahl
   clientseitig und wird an die Volltextsuche (`tags`-Parameter) weitergereicht.

Zusaetzlich umgesetzt: `subject`, `grade`, `thema` und `kind` im Index-Entry
bevorzugen nicht leere Frontmatter-Eintrage vor der Pfadableitung
(`header_text` in `qmd_entry`); die Pfadableitung bleibt Fallback fuer
ungetaggte Bestandsdateien.

## Phase 3 — Bestandsmigration (umgesetzt)

- Invoke-Task `inv tags-backfill` in `src/project_tasks.py`: schreibt die heute
  pfadabgeleiteten Attribute (`subject`, `grade`, `thema`, `kind`) als Tags ins
  Frontmatter aller QMDs, wo `tags` fehlt oder leer ist. `--trocken` zeigt nur
  an, was passieren wuerde; Dateien mit ungueltigem YAML, Lese- oder
  Schreibfehlern werden uebersprungen und gemeldet. Bestehende tags-Eintraege
  bleiben unberuehrt. Der tags-Block wird textuell eingefuegt, damit die
  Formatierung des bestehenden YAML-Headers (Einrueckung, Block-Scalars in
  `header-includes`) unveraendert bleibt. Der `wissen`-Submodule bleibt ausgespart, weil die UI
  seine Eintraege nicht anzeigt und Schreibzugriffe den Submodule dirty machen
  wuerden; der Dateiname und der generische Fallback-Typ "Material" werden
  nicht als Tags uebernommen.
- Danach verlieren Ordner ihre semantische Bedeutung: neue Dateien koennen
  flacher abgelegt werden, ohne dass Suche und Filter etwas verlieren.

## Phase 4 — Langfristige Umstellung

- UI-Default-Ansicht wird die Tag-Sicht; die Ordneransicht bleibt als Option.
- Die Pfadableitung in `qmd_entry()` entfaellt, sobald der Backfill
  abgeschlossen ist — bis dahin ist sie der Kompatibilitaets-Fallback.

## Tests und Doku (umgesetzt)

- `src/tests/test_material_ui.py`: `GET /api/tags`, Tag-Filter in der Suche,
  `tags` im Index-Entry, Frontmatter-Bevorzugung vor der Pfadableitung,
  Tag-Listen ueber `POST /api/document/metadata` sowie Playwright-Tests fuer
  die Tag-Ansicht der Materialauswahl und das Tag-Feld der Suchmaske.
- `src/tests/test_project_tasks.py`: `inv tags-backfill` im Trockenlauf und
  im Schreiblauf, einschliesslich der Erhaltung bestehender Tags.
- `src/tests/test_material_ui_architecture.py`: `set_fields` mit Tag-Listen
  (Kommentare und Body bleiben unberuehrt) und ein Node-Modultest fuer
  `parseTagInput` in `static/metadata-panel.js`.
- `src/material_ui/README.md` dokumentiert die neue Route, den `tags`-Eintrag
  und die Tag-Ansicht.
- Nebenbei repariert: `test_folder_list_opens_deck_source_md_in_editor` in
  `src/tests/test_material_ui_decks.py` erwartete noch die entfernte
  `#qmdText`-Textarea aus der Editor-Modernisierung und schlug auf HEAD fehl;
  er prueft jetzt den Editor-Text ueber `window.materialEditor.getText()`.

## Offene Punkte

- `.excalidraw`-Dateien sind JSON und koennen kein Frontmatter tragen; sie
  tauchen aber in der Ordnerliste auf. Optionen: Tags ueber eine
  Sidecar-Datei, ueber eine Dateinamen-Konvention, oder Excalidraw-Dateien
  zunaechst ungetaggt lassen. Empfehlung fuer Phase 1: ungetaggt lassen und
  das Thema vertagen.
- `.md`-Dateien koennen problemlos Frontmatter tragen und liessen sich spaeter
  in denselben Mechanismus aufnehmen.
