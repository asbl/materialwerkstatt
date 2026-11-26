# Material-UI: Druckverlauf-Plugin (Plan)

Stand 2026-11-24. Ziel: Die Material-UI soll anzeigen, **wo (an welchem Dokument) schon einmal ein
Druckauftrag gestartet wurde** – und das Plugin soll später erweiterbar sein.

## Ausgangslage

- Neu im Kern: Knopf „PDF drucken“ in der Render-Leiste (`#printPdf`, `printCurrentPdf()` in
  `static/app.js`). Er lädt das aktuelle PDF in einen unsichtbaren Frame und öffnet den
  Druckdialog des Browsers. Beim Start feuert er `document` das Ereignis
  `material:print-started` mit `{ path, pdf, at }` (QMD-Pfad, PDF-Pfad, Zeitstempel).
- Das externe Plugin `druck` (Katalog `material-ui-plugins`) liest CUPS-Aufträge und ordnet
  sie per Fenstertitel („geöffnet“-Journal) einem Dokument zu. Das ist eine Heuristik und
  versagt bei gleichen Titeln (AB, Mini-AB, Folien).
- Der Kern kennt kein Druckwissen; Plugins dürfen den Kern nicht importieren, nur über
  `ctx` und Host-Dienste arbeiten.

## Entscheidung

Neues kleines Plugin **`druckverlauf`** (eingebaut unter `src/material_ui/plugins/druckverlauf/`,
`provides: ["print-history"]`). Es speichert nur, **was die Material-UI selbst gestartet hat** –
exakt, ohne Titelraten. `druck` kann später den Dienst `print-history` zur genaueren
Zuordnung nutzen (`dependsOn` optional), muss es aber nicht.

Begründung gegen „`druck` erweitern“: Dessen Kernaufgabe ist CUPS-Überwachung und braucht
`pycups`; der Verlauf soll auch ohne CUPS laufen und unabhängig installierbar sein.

## Datenmodell (M1)

Speicher: `ctx.storage` → `.material-ui/plugins/druckverlauf/verlauf.json` (privat, 0600),
Liste, neueste zuletzt, Obergrenze 2000 Einträge:

```json
{ "id": "uuid", "path": "unterricht/…/ab_x.qmd", "pdf": "build/pdf/…/ab_x.pdf",
  "at": 1795000000.0, "copies": null, "printer": null, "source": "ui-button" }
```

`copies`/`printer` bleiben in M1 leer (der Browserdialog meldet sie nicht); die Felder sind
reserviert, damit Erweiterungen (siehe unten) keine Migration brauchen.

Datenschutz: Pfade unter `foerderempfehlungen/` werden nie gespeichert (wie im `druck`-Plugin).
Es werden keine Dokumentinhalte oder Schülerdaten abgelegt.

## Schnittstellen (M1)

Backend (Blueprint, Präfix `/api/druckverlauf/`):

- `POST /api/druckverlauf/ereignis` – Body `{path, pdf, at}`; validiert den Pfad gegen den
  Dokumentindex, speichert, antwortet `{ok, eintrag}`.
- `GET /api/druckverlauf/dokument?path=…` – Einträge zu einem Dokument (`zuletzt`, `anzahl`).
- `GET /api/druckverlauf/uebersicht?tage=7|30|alle` – gruppiert je Dokument.

Dienst: `ctx.register_service("print-history", PrintHistory)` mit
`record(path, pdf, at, **meta)`, `for_document(path)`, `overview(days)`.

Frontend (`assets/plugin.js`):

1. Hört auf `material:print-started` und schickt es an `/ereignis`.
2. Zeigt am geöffneten Dokument ein Kennzeichen „zuletzt gedruckt am …, N×“ (Tooltip), und
   in der Dateiliste einen dezenten Marker (Index-Provider `ctx.index.register`, damit
   `/api/qmds` ein Feld `printedAt` erhält – Filter „noch nie gedruckt“ ist dann nur
   noch eine Filteroption).
3. Ansicht „Gedruckt“ in der Rail: Liste je Dokument, Datum, Klick öffnet das Dokument über
   `ctx.documents.open`.

## Offene Entscheidung für den Kern (vor M1 klären)

Das DOM-Ereignis genügt für den Anfang. Sauberer ist ein deklarierter Host-Hook
(`hostApis: ["print"]` oder `ctx.events.on("print-started", fn)` im `pluginContext` in
`static/plugins/loader.js`), samt Eintrag in `static/api-contract.json`. Empfehlung: Hook
einführen, sobald ein zweites Plugin darauf hört; bis dahin das DOM-Ereignis.

## Meilensteine

| Stufe | Inhalt |
|---|---|
| M0 | erledigt: Knopf und Ereignis im Kern |
| M1 | Plugin-Gerüst, Speicher, Routen, Kennzeichen am Dokument, Tests |
| M2 | Rail-Ansicht „Gedruckt“, Filter „noch nie gedruckt“ im Index (`printedAt`) |
| M3 | Weitere Druckwege melden ebenfalls (Folien-PDF, Sammeldruck, Plan/Stundenplan) über denselben Ereignisnamen mit `kind` |
| M4 | Abgleich mit `druck`: bestätigter CUPS-Auftrag ergänzt `printer`, `copies`, `status` am Eintrag (Zuordnung über Zeitfenster + Titel, nur ergänzend) |
| M5 | Mögliche Erweiterungen: Klassenbezug („für 10b gedruckt“), Stückzahl-Eingabe vor dem Druck, Export/Bereinigung alter Einträge, Hinweis „seit dem Druck geändert“ (Vergleich der PDF-Version `pdf_version()` mit dem gedruckten Stand) |

## Tests (M1)

- Backend: Pfadprüfung, Ausschluss `foerderempfehlungen/`, Obergrenze, Aggregation.
- Frontend (`src/tests/…frontend`): Ereignis → POST; Kennzeichen erscheint nach Antwort.
- Ohne Plugin läuft der Knopf unverändert (Ereignis ohne Hörer).

## Risiken

- Der Browser meldet nicht, ob im Dialog wirklich gedruckt oder abgebrochen wurde. Gespeichert
  wird daher „Druck gestartet“; die Anzeige sagt entsprechend „Druck gestartet am …“, nicht
  „gedruckt“. M4 liefert die Bestätigung über CUPS.
- PDF-Frame-Druck funktioniert je nach Browser/Desktop-Hülle unterschiedlich; Rückfall ist das
  Öffnen des PDFs im Tab (im Knopf bereits umgesetzt).
