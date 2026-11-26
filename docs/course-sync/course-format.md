# Kursformat und Dateistruktur

Ein `course-sync`-Kurs liegt unter `unterricht/kurse/<kurs>/`. Der Ordnername ist der technische
Kurs-Slug und wird in CLI-Kommandos verwendet.

## Minimalstruktur

```text
unterricht/kurse/info-2026/
  course.yml
  index.mdx
  chapters/
    001-einstieg.mdx
    001-einstieg/
      hello-world/
        content.mdx
```

Alte Aufgabenordner unter `h5p/<kapitel-slug>/<identifier>/` werden weiterhin gelesen.

## `index.mdx`

`index.mdx` definiert die Reihenfolge der Kapitel:

```mdx
# Informatik 2026

<Chapter src="./chapters/001-einstieg.mdx" title="Einstieg" />
<Chapter src="./chapters/002-variablen.mdx" title="Variablen" />
```

Der Dateiname ohne `.mdx` ist der Kapitel-Slug. Dazu passend sucht `course-sync` H5P-
Quellen zuerst unter `chapters/<kapitel-slug>/<identifier>/` und danach als
Rueckfall unter `h5p/<kapitel-slug>/<identifier>/`.

Optional kann ein Kapitel mit `synced={false}` von Kurs-weiten Moodle-Sync-
Operationen ausgenommen werden. Wenn `synced` nicht gesetzt ist, gilt
`synced={true}`.

## `course.yml`

`course.yml` enthält kursweite Einstellungen. H5P-Metadaten, die bisher in jeder
einzelnen `h5p.json` wiederholt wurden, koennen global in `h5pDefaults` stehen:

```yaml
h5pDefaults:
  language: de
  defaultLanguage: de
  mainLibrary: H5P.PythonQuestion
  embedTypes:
    - div
  license: U
  majorVersion: 6
  minorVersion: 90
```

Aktivitäts-spezifische Angaben wie `title` kommen weiter aus dem Question-Tag
oder aus einer optionalen lokalen `h5p.json`.

### `secrets` – Namen und andere nicht-öffentliche Werte

`course.yml` kann ein `secrets`-Mapping definieren, z. B. echte Schülernamen, die
nur auf bestimmten Zielen im Klartext stehen sollen. Die Ersatzwerte sollten echte
Namen aus dem gleichen Sprachraum des Originals sein (fantasy → fantasy, nordisch →
nordisch, hebräisch → hebräisch usw.), damit der Text natürlich bleibt:

```yaml
secrets:
  "Anna": "Lea"
  "Torin": "Eirik"
```

Beim Upload auf ein Moodle-Ziel werden diese Werte in allen H5P-Paketen und
Text-Labels durch die Ersatznamen ersetzt – außer das Ziel deklariert
`keep_secrets: true` in seiner `.moodle-target-<ziel>.yml`:

```yaml
# .moodle-target-schulportal.yml
auth: schulportal-hessen
course_url: https://moodle.example/course/view.php?id=12
keep_secrets: true
```

Ziele ohne `keep_secrets` (und der unbenannte Standard-Sync) bekommen die
Ersetzungen. Die Ersetzung arbeitet case-sensitiv außerhalb von Wortgrenzen
(„Annabell“ bleibt unverändert, „Jonas'“ und „Fenns“ werden mit Ersatz
übertragen), damit Code-Identifier unberührt bleiben. Der Kurs-Quellstand
ändert sich nicht; auch der statische Website-Export (`export-site`) wird
immer mit den Ersetzungen veröffentlicht, weil er öffentlich ist.

## Kapiteldateien

Kapitel enthalten normalen Markdown/MDX-Text und Frage-Platzhalter:

````mdx
## Einstieg

<PythonQuestion
  identifier="hello-world"
  title="Erste Python-Aufgabe"
  instructions="Ändere den Text und führe das Programm aus."
/>

```python question:hello-world starter
print("Hello, world!")
```
````

`identifier` ist der stabile Schlüssel der Aufgabe. Er sollte nach dem ersten Upload
nicht mehr geändert werden, weil Moodle-Aktivitäten darueber wiedererkannt werden.

## Aufgabenordner

Eine Aufgabe liegt unter:

```text
chapters/<kapitel-slug>/<identifier>/
```

### `content.mdx`

`content.mdx` beschreibt den sichtbaren Inhalt und optionale Editor-Blöcke.
Die fruehere `settings.yml` wird als YAML-Frontmatter am Dateianfang notiert:

````mdx
---
contentType: ide_only
pythonRunner: skulpt
pyodideOptions:
  packages: []
---
<Instructions>
Ändere den Text in der print-Anweisung und führe das Programm aus.
</Instructions>

```python editor:startingCode
print("Hello, world!")
```

Optional können zusätzliche Editor-Dateien angegeben werden. Mit
`visibleToLearner: false` und `learnerEditable: false` liegt der Code im
Hintergrund, ohne im Editor der Lernenden sichtbar oder bearbeitbar zu sein:

```yaml editor
options:
  sourceFiles:
  - fileName: helper.py
    code: |
      SECRET = 42
    visibleToLearner: false
    learnerEditable: false
```

```yaml grading
gradingMethod: please_choose
dueDateGroup:
  enableDueDate: false
  duedate: 01.01.1970
testCases: []
```
````

Wichtige Runner:

- `skulpt`: schneller Start, gut für einfache Python-Aufgaben
- `pyodide`: groesser, aber näher an CPython und mit Paketunterstützung

Eine lokale `settings.yml` oder `h5p.json` im Aufgabenordner bleibt aus
Kompatibilitätsgruenden gueltig. Frontmatter in `content.mdx` überschreibt dabei
gleichnamige Werte aus `settings.yml`.

## Generierte Dateien

Diese Ordner sind lokal oder generiert und sollten nicht als Kursquelle bearbeitet werden:

- `unterricht/kurse/<kurs>/build/`
- `unterricht/kurse/<kurs>/exports/`
- `unterricht/kurse/build/site/`
- `.h5p-runtime/`
- `build/scratch/temp/`
- `uploads/`

## Zusammenarbeit

Kursquellen werden per Git geteilt. Zugangsdaten bleiben in `.env` lokal.

Empfohlener Ablauf:

```bash
git pull
git checkout -b feature/neue-aufgabe
inv kurse.sync --course=info-2026
inv kurse.export-site --course=info-2026
git add unterricht/kurse/info-2026
git commit -m "Add variables exercise"
```
