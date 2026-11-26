# Hinweise zu Drittsoftware

Dieses Projekt steht unter der MIT-Lizenz (siehe `LICENSE`). Es enthaelt oder verwendet
folgende Drittsoftware unter eigenen Lizenzen.

## Schriften (SIL Open Font License 1.1)

Quelle: <https://github.com/google/fonts> (Commit und Pruefsummen in
`src/quarto/fonts/manifest.json`). Je Familie liegt der Lizenztext als `OFL.txt` neben den
Schriftdateien. Die statischen Instanzen unter `src/quarto/fonts/static/` entstehen mit
`src/quarto/fonts/build_static.py` und tragen eigene Namen (`Material...`), wie es die OFL
bei Reserved Font Names verlangt; die Lizenz liegt jeweils daneben.

| Familie | Copyright |
| --- | --- |
| Acme | Juan Pablo del Peral |
| Alice | The Alice Project Authors |
| Baloo 2 | The Baloo 2 Project Authors |
| Bangers (unveraendert) | The Bangers Project Authors |
| Balsamiq Sans | The Balsamiq Sans Project Authors |
| Barlow Semi Condensed | The Barlow Project Authors |
| Bitter | The Bitter Project Authors |
| Cinzel | The Cinzel Project Authors |
| Fredoka | The Fredoka Project Authors |
| Lilita One | Juan Montoreano |
| Outfit | The Outfit Project Authors |
| Pixelify Sans | The Pixelify Sans Project Authors |
| Source Serif 4 | The Source Serif 4 Project Authors |
| Space Grotesk | The Space Grotesk Project Authors |

Die Schriften duerfen mit Software gebuendelt, aber nicht allein verkauft werden.

## Mitgelieferter Code

- `src/course_sync/vendor/h5p-cli-1.1.5.tgz`: npm-Paket `h5p-cli`, MIT, (c) H5P Group.
  Der Lizenztext liegt im Archiv unter `package/LICENSE`; siehe `src/course_sync/vendor/NOTICE`.
- `src/material_ui/static/editor.bundle.js`: erzeugtes Bundle (Vite) aus `src/editor-app/`;
  enthaelt CodeMirror 6 (MIT, (c) Marijn Haverbeke und andere).
- `src/excalideck/present/`: baut gegen Excalidraw (MIT), `@excalimath/core`, React (MIT).
  Das Build-Ergebnis `dist/` ist nicht versioniert.

## Python-Abhaengigkeiten (werden nicht mitgeliefert)

Flask (BSD-3-Clause), markdown-it-py (MIT), invoke (BSD-2-Clause), Playwright (Apache-2.0),
PyYAML (MIT), ruamel.yaml (MIT), httpx (BSD-3-Clause), numpy (BSD-3-Clause), mcp (MIT),
optional caldav, recurring-ical-events, fonttools, excaligen.

**PyMuPDF** (`pymupdf`) steht unter **AGPL-3.0** (alternativ kommerziell). Es wird nur
installiert, nicht kopiert. Wer dieses Projekt als Netzdienst anbietet oder
weiterverteilt, muss die AGPL-Pflichten von PyMuPDF selbst pruefen.

## Laufzeitwerkzeuge (nicht mitgeliefert)

Quarto, LaTeX, Typst, rsvg-convert und poppler (pdftocairo) werden vom System gestellt und
unterliegen ihren eigenen Lizenzen. Die H5P-Libraries werden nicht versioniert, sondern bei
Bedarf aus den jeweiligen Releases geladen (`inv kurse.update-h5p-libraries`).
