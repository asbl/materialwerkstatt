# Entwurf: Planung per Zuweisen und Ziehen, Termin zu Material, Aufräumen von units.js

Stand: 2026-11-20. Umgesetzt sind U0 bis U3 und der Schnitt von `units.js`: Einheit zuweisen mit Rückgängig (`material` und `remove` in
`POST /api/units/dates`), Ziehen einer Einheitenkarte auf eine freie Stunde, Verschieben bestehender Einsätze (Griff an der Stundenzeile oder
Knopf „Verschieben“ mit Auswahl der freien Stunden, Rückgängig über `updates`; der Server lehnt ein Verschieben auf einen Tag mit gleichem Einsatz ab),
Material am Termin (`material-ui:open-material`) und „Einheit zuweisen“ auf Heute (`material-ui:assign-unit`, nur sichtbar, wenn die Einheitenansicht
vorhanden ist). Aus `units.js` sind `unit-dates.js` (Datumsformular), `unit-new-form.js` (Neue Lerneinheit) und `unit-filters.js` (Filterleiste)
herausgelöst. Die Filter Fach, Lerngruppe und „nur ohne Termin“ sind ebenfalls umgesetzt. Lerngruppen berücksichtigen explizite Einsätze und die automatische Zuordnung nach Schuljahr; „nur ohne Termin“ beschränkt die Liste, der Bearbeitungsschalter für undatierte Einheiten bleibt unabhängig davon.

Der Entwurf baut auf dem vorhandenen Stand auf (Einheitenansicht, Kalender-Plugin, `@calendar`-Schnittstelle) und beschreibt die
nächsten großen Schritte der Material-UI.

## 1. Ausgangslage (was es schon gibt)

Geprüft im Code, nicht nur in der Doku:

- **Planungsansicht** (`static/unit-planning.js`): Zeigt je Klasse und Schuljahr die Unterrichts-
  stunden aus dem Kalender. Stunden mit zugewiesener Einheit stehen in deren Karte, kommende
  Stunden ohne Einheit als „Noch offen“-Zeilen. Pro Stunde gibt es heute genau zwei Aktionen:
  **+ Lerneinheit** (legt eine *neue* Einheit an, `create(event)` in `units.js`) und **Ausfall**.
- **Termine zu bestehender Einheit**: `POST /api/units/dates` (`UnitService.append_dates`) hängt
  Einsatzdaten an eine bestehende Einheit an, mit Revisionsprüfung. Die Oberfläche dafür ist das
  Formular „weiteres Datum“ in der Einheitenkarte (`quickDates`), also Datum von Hand eintippen.
- **Einheit am Termin sichtbar**: Das Kalender-Plugin ordnet Einsätze den Stunden zu
  (`service.py`, Feld `event.units`). Heute-Seite, Monatsliste und Agenda zeigen
  „↳ Einheitentitel“ und öffnen die Einheit über das Ereignis `material-ui:open-unit`.
- **Filter**: Schuljahr, Bearbeitungsstatus und Tags (`unit-filters` in `units.js`).
- **Material ziehen**: Material zwischen Einheiten verschieben per Pointer-Geste
  (`units.js`, Abschnitt `unit-drop-target`). Das ist die Vorlage für weiteres Ziehen.

## 2. Lücken

1. Eine **bestehende** Einheit lässt sich nicht aus der Planungsansicht einer freien Stunde
   zuweisen. Man muss die Einheit suchen, das Datumsformular öffnen und das Datum tippen.
2. Einsätze lassen sich nicht auf eine andere Stunde verschieben (Datum ändern ist nur im
   Formular möglich).
3. Vom Termin gelangt man nur zur **Einheit**, nicht zum konkreten Material des Einsatzes,
   obwohl `einsatz[].material` das schon speichert.
4. Auf der Heute-Seite hat eine Stunde ohne Einheit keine Aktion („Einheit zuweisen“).
5. `units.js` ist eine einzige Closure mit etwa 1400 Zeilen. Jede neue Funktion landet dort.

## 3. Ziel 1: Einheit einer Stunde zuweisen

### Bedienung

- Jede „Noch offen“-Stunde bekommt neben **+ Lerneinheit** die Aktion **Einheit zuweisen**.
  Sie öffnet eine kleine Auswahl mit den Einheiten derselben Klasse und desselben Fachs,
  sortiert nach „noch nie eingesetzt“, dann nach Thema. Eine Suchzeile filtert nach Titel.
- Zusätzlich lässt sich eine Einheitenkarte an einem Griff auf eine freie Stunde ziehen.
  Dasselbe gilt für bereits zugewiesene Tage: Ziehen auf eine andere freie Stunde ändert das
  Datum dieses Einsatzes (statt ein zweites anzulegen).
- Die Auswahl ist der **Tastaturweg** und der Weg für Touch und schmale Fenster. Ziehen ist
  nur eine Abkürzung dazu, nie die einzige Möglichkeit.
- Nach der Zuweisung steht in der Statuszeile „Einheit X am 06.11. eingetragen. Rückgängig“.
  Rückgängig entfernt genau diesen Einsatz wieder (siehe Backend).

### Umsetzung

Frontend:

- Neues Modul `static/unit-assign.js`, ohne Zugriff auf Zustand von `units.js`. Es bekommt
  `api`, die Einheitenliste und Callbacks (`onAssigned(saved)`, `onError(message)`) und bietet
  `openAssignPicker({ event, anchor })` sowie `enableDragAssign({ section, slotSelector })`.
- Das Ziehen übernimmt das Pointer-Muster aus dem Material-Ziehen (Schwelle 6 px,
  `suppressMaterialClick`, Zielmarkierung per Klasse). Dieser Code wird dazu in eine
  gemeinsame Hilfsfunktion `pointerDrag({ start, over, drop })` ausgelagert. Das ist Teil von
  Ziel 3.
- `unit-planning.js` rendert den Knopf und reicht das Ereignis nach außen. Es erhält dafür
  den Callback `assign(event)` neben `create(event)`.

Backend:

- Zuweisen nutzt `POST /api/units/dates` unverändert (`dates: [datum]`, `lerngruppe`,
  `revision`). Die Revisionsprüfung gilt weiter: Bei Konflikt lädt die Ansicht die Einheit neu
  und zeigt die vorhandene Konfliktmeldung.
- **Neu, klein**: `append_dates` nimmt optional `material` an und übernimmt es in den neuen
  Einsatz. Die Duplikatprüfung (`not use.get('material')`) vergleicht dann auch das Material.
  Damit trägt Ziel 2 keine Datenformatänderung nach.
- **Neu, klein**: `POST /api/units/dates` erhält `remove: [{datum, lerngruppe, material}]`
  für „Rückgängig“, mit derselben Revisionsprüfung. Alternativ nimmt Rückgängig die
  Revision aus der Antwort und ruft `save()` mit der Einsatzliste vor der Zuweisung auf.
  Empfehlung: `remove`, weil es weniger Zustand im Browser braucht.
- Prüfung auf Fach und Klasse bleibt serverseitig maßgeblich (Einheit zu Klasse und Fach der
  Stunde), die Oberfläche filtert nur vor.

### Randfälle, die der Entwurf ausdrücklich abdeckt

- **Doppelstunde**: Einsätze gelten pro Datum und Lerngruppe, nicht pro Stunde. Zwei Stunden
  am selben Tag zeigen dieselbe Einheit. Die Auswahl bietet deshalb „Tag zuweisen“ an und
  markiert beide Zeilen. Ein Einsatz je Einzelstunde wäre eine Datenformatänderung (siehe
  offene Fragen).
- **Ausfall**: Ausgefallene Stunden bieten keine Zuweisung an (wie heute bei „+ Lerneinheit“).
- **Datumsneutrale Einheiten** erscheinen in der Auswahl in eigener Gruppe, behalten aber
  ihre Eigenschaft.
- **Gleiche Einheit, gleicher Tag**: wird nicht doppelt eingetragen, die Meldung nennt das.
- **Zwei Fenster**: Konflikt per Revision wie bisher, kein stilles Überschreiben.

## 4. Ziel 2: Vom Termin zum Material

- Das Kalender-Plugin liefert in `event.units` zusätzlich `material` (relativer Pfad aus dem
  Einsatz, leer bei „ganze Einheit“). Änderung nur in der Zuordnung in `service.py`, wo
  `linked.append({...})` steht; das Feld ist additiv, ältere Oberflächen ignorieren es.
- Heute-Seite, Monatsliste und Agenda zeigen bei vorhandenem Material einen zweiten Knopf
  „Material öffnen“ neben dem Einheitenlink. Es öffnet über ein neues Ereignis
  `material-ui:open-material` mit dem Pfad das Dokument im Editor. Das Ereignis ist additiv
  und wird im Plugin-Vertrag unter den Kalender-Schnittstellen aufgeführt, analog zu
  `material-ui:open-unit`.
- Heute-Seite: Stunden **ohne** Einheit erhalten „Einheit zuweisen“. Das Kalender-Plugin
  kennt die Einheitenliste nicht. Es sendet `material-ui:assign-unit` mit
  `{ datum, lerngruppe, fach, klasse }`; der Kern öffnet dazu den Auswahldialog aus Ziel 1
  und wechselt bei Bedarf in die Einheitenansicht. Fehlt die Einheitenansicht, bleibt der
  Knopf unsichtbar.

## 5. Ziel 3: Aufräumen von units.js (Voraussetzung, aber in kleinen Schritten)

Kein Umbau auf einmal, sondern vier Schnitte, jeweils ohne Verhaltensänderung und einzeln
auslieferbar:

1. `pointerDrag` aus dem Material-Ziehen herauslösen (wird von Ziel 1 gebraucht).
2. Datumsformular (`quickDates`, Zeilen um 1250 bis 1290) nach `static/unit-dates.js`.
3. Formular „Neue Lerneinheit“ nach `static/unit-new-form.js`.
4. Filterleiste nach `static/unit-filters.js`, zugleich Ort für neue Filter (Ziel 4).

Regel für jeden Schnitt: Das Modul erhält Abhängigkeiten als Argumente, liest keinen
Closure-Zustand und hat ein kleines Testprotokoll (siehe Abschnitt 7). Das ist dieselbe
Linie wie die in `material-ui-architektur.md` beschriebene schrittweise Entfernung globaler
Zustandsfelder.

## 6. Ziel 4 (klein): Filter erweitern

Zu den vorhandenen Filtern Schuljahr, Status und Tags kommen **Fach**, **Lerngruppe** und
„nur ohne Termin“. Sie werden wie die anderen über `persistWorkspace` gemerkt und zählen in
der Zusammenfassung „Filter · aktiv“ mit. Der Filter „nur ohne Termin“ ersetzt in der Praxis
den Schalter „Undatierte Einheiten bearbeiten“ nicht, sondern ergänzt ihn: der Schalter
bestimmt, was bearbeitbar sichtbar ist, der Filter schränkt die Liste ein.

## 7. Meilensteine mit Abnahme

| Schritt | Inhalt | Abnahme |
|---|---|---|
| U0 | Schnitt 1 und 2 aus Abschnitt 5 | Keine Verhaltensänderung; vorhandene Einheiten-Tests grün; Material-Ziehen und Datumsformular manuell wie vorher |
| U1 | Auswahl „Einheit zuweisen“ in der Planungsansicht, `append_dates` mit `material` und `remove` | Backendtests: Zuweisen, Duplikat, Revisionskonflikt, falsche Klasse oder Fach, Entfernen; Frontendtest: Auswahl öffnet, filtert, schreibt, Rückgängig stellt her; per Tastatur bedienbar |
| U2 | Ziehen auf freie Stunde und Verschieben eines Einsatzes | Pointer-Test mit Zielmarkierung; Abbruch mit Escape; kein Verschieben auf ausgefallene Stunde |
| U3 | Termin zu Material, Zuweisen aus Heute | `event.units[].material` vorhanden und von bestehenden Kalendertests nicht berührt; Knöpfe auf Heute, Monatsliste und Agenda; ohne Einheitenansicht kein Knopf |
| U4 | Schnitt 3 und 4 und neue Filter | Konventionen und Tests grün; Filterzustand überlebt Neuladen |

Reihenfolge: U0, U1, U3, U2, U4. U3 steht vor U2, weil es mehr Alltagsnutzen bringt als
das Ziehen und weniger Risiko trägt.

Tests: Backend in `src/tests/test_material_ui_units.py`, Kalenderanteile in
`src/tests/test_material_ui_kalender.py`. Für das Frontend gibt es mehrere Modultests
(`src/tests/test_*_frontend*.py`); die Abdeckung der Planungsansicht habe ich nicht im Einzelnen
geprüft. Vor U1 ist zu klären, ob ein neuer Frontendtest in diesem Stil genügt oder ein
Browsertest nötig ist.

## 8. Risiken

- **`planningCache`**: Nach Zuweisen, Verschieben und Entfernen muss der Cache geleert werden
  (`clearUnitPlanningCache`), sonst zeigt die Ansicht den alten Stand. Der bestehende
  Ausfall-Pfad macht das schon und dient als Muster.
- **Offene Entwürfe**: Wie beim Fertig-Status gilt: Hat die Einheit ungespeicherte Änderungen
  (`drafts`, `quickDates`), wird nicht zugewiesen, sondern um Speichern gebeten.
- **Lerngruppenabgleich**: Die Zuordnung Stunde zu Gruppe läuft über `group_key` und die
  Standardgruppe des Schuljahrs. Die Auswahl muss exakt dieselbe Gruppe an `append_dates`
  übergeben wie die Anzeige danach erwartet, sonst erscheint die Einheit nicht in der Stunde.
- **Plugin-Vertrag**: Beide neuen Ereignisse und das Feld `material` sind additiv. Sie
  gehören in die Kalender-Schnittstellen der Plugin-Doku und, wenn das Muster des Projekts es
  verlangt, als Fähigkeit in den API-Vertrag (`plugin-calendar-actions` ist das Vorbild).

## 9. Offene Entscheidungen

1. **Einsatz pro Tag oder pro Stunde?** Empfehlung: pro Tag lassen. Ein Feld `stunde` im
   Einsatz wäre eine Formatänderung in `einheit.yaml` für einen seltenen Fall.
2. **Ziehen oder nur Auswahl?** Empfehlung: erst Auswahl (U1), Ziehen (U2) danach, wenn die
   Auswahl im Alltag spürbar zu langsam ist.
3. **„Material öffnen“ im Kalender**: Soll bei Einsätzen ohne Material (ganze Einheit) nur
   die Einheit öffnen oder zusätzlich das erste Material? Empfehlung: nur die Einheit.
