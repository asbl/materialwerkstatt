# Render-Templates

Hier liegen die **eingebauten** Typst- und LaTeX-Grundlayouts für Klausuren, Arbeitsblätter,
Förderpläne, Präsentationen und Selbstdiagnosebögen. Welche Dateien eingebaut sind, steht
verbindlich in [`../builtin-templates.json`](../builtin-templates.json).

## Vorlagen sind standardmäßig privat

Neue Vorlagen, Layout-Partials, Freigaben, Designs, Schriften und Tests entstehen im
**ignorierten privaten Ordner** `src/quarto/_local/` (`templates/`, `template-releases/`,
`template-designs.json`, `template-definitions.json`, `design_modules/`, `tests/`, `docs/`).
Dieser Ordner funktioniert wie der eingebaute Bestand: Die Material-UI zeigt private Vorlagen in
der Auswahl, `inv build` und die Template-Versionierung lösen sie über den Dateinamen auf, und
Freigaben (Releases) landen im privaten Speicher. Er wird nie versioniert und nie
synchronisiert (`.gitignore`, `.sync-exclude.lst`).

Der Ordnername ist über `MATERIAL_PRIVATE_DIR` (relativ zu `src/quarto/`) einstellbar; Tests
setzen ihn auf einen nicht vorhandenen Ordner, um den öffentlichen Bestand ohne private
Vorlagen zu prüfen.

### Eine Vorlage ausdrücklich einbauen

Eine private Vorlage wird nur durch eine bewusste Entscheidung eingebaut:

```sh
inv template-freigeben --name worksheet-meine-vorlage                 # Probelauf: Abhängigkeiten und Prüfung
inv template-freigeben --name worksheet-meine-vorlage --lizenz-bestaetigt
```

Der Lauf ermittelt die privaten Abhängigkeiten (Partials, Includes, Assets), lehnt Vorlagen mit
eingebetteten Bilddaten oder Treffern aus der privaten Sperrliste (`_local/brand-denylist.txt`)
ab, verschiebt Dateien, Freigaben und den Katalogeintrag in den eingebauten Bestand und trägt
sie in `builtin-templates.json` ein. Die Bestätigung `--lizenz-bestaetigt` heißt: Vorlage,
Grafiken, Motive, Namen und Schriften sind frei verwendbar und enthalten keine Fremdmarken.
Danach mit `git add` prüfen und committen.

Zwei Sperren verhindern, dass etwas unbeabsichtigt eingebaut wird:

- `inv templates-pruefen` (und `python -m material_core.template_policy check`) meldet jede Datei,
  jeden Freigabe-Ordner und jedes Design in den eingebauten Ordnern, das nicht in
  `builtin-templates.json` steht, sowie eingebettete Bilddaten.
- Der pre-commit-Hook (`inv oss-hook`) und `inv oss-pruefen` brechen Commits mit nicht
  freigegebenen Vorlagen, privaten Pfaden oder Namen ab.

## Eingebaute Designs für Arbeitsblätter und Folien

| Auswahl | Template-Datei |
|---|---|
| Fördermaterial · Klasse 5 (Retro) | `worksheet-foerdermaterial.typst` |
| Retro | `worksheet-retro.typst` |
| Fußball | `worksheet-fussball.typst` |
| Reiten | `worksheet-reiten.typst` |
| Anime | `worksheet-anime.typst` |

Weitere Basis-Vorlagen: `worksheet-informatik`, `worksheet-mini`, `worksheet-a-five`,
`exam-template`, `math-test-template`, `nachpruefung-template`, `foerderplan-template`,
`feedbackbogen-template`, `selbstdiagnose-template`, `checkup-alice`, `latex-template`,
`slides-template` sowie die Folienvorlagen `slide-template` und `slide-<Design>`.
Die Designdaten (Farben, Rahmen, Motive) liegen in `src/material_core/template-designs.json`.

## Aufbau

- `worksheet-design.typst`, `student-fields.typst`, `exam-functions.typst` und die
  `*-layout.typst`-Dateien sind Partials, die Vorlagen über `$name.typst()$` einbinden.
- Slide-Designs liefern `slide-<Design>.typst`; der Hintergrund entsteht aus dem Designdatensatz
  (`material_core/slide_designs.py`). Private Designs erweitern ihn über
  `material_core/private_hooks.py` (Datei `_local/design_modules/design_hooks.py`).
- Vorlagen werden über ihren Dateinamen aufgelöst (`material_core/template_roots.py`): zuerst
  der eingebaute, dann der private Ordner. Der logische Pfad `src/quarto/templates/<Name>`
  bleibt für Oberfläche und Frontmatter gleich, auch wenn die Datei privat liegt.
- Unveränderliche Template-Versionen: siehe `docs/template-versionierung.md`.
- Gestaltungsregeln für neue und überarbeitete Vorlagen (Kopfzeile, Zeilenabstand,
  Mini-AB-Schriftgrößen, Antwortflächen) prüft zum Teil `inv konventionen`.
