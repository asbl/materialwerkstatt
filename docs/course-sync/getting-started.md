# Installation und erste Schritte

Diese Anleitung richtet sich an Personen, die `course-sync` noch nicht kennen.

## Voraussetzungen

- Python 3.12 oder neuer
- Node.js mit `npx`
- Git
- optional: Moodle-Zugang mit H5P-Rechten

Für Moodle-Uploads nutzt `course-sync` Playwright. Beim ersten Upload kann Playwright
Browser-Dateien nachinstallieren. `inv doctor` prueft die gesamte Umgebung und zeigt
fuer Fehlendes konkrete Installationshinweise.

## Einrichten

`course-sync` ist Teil von material-datenbank (Paket `course_sync` unter `src/`).
Einmalig aus dem material-datenbank-Repo-Root:

```bash
inv setup
```

Das installiert das Python-Paket inklusive des `course-sync`-CLI-Kommandos, legt `.env`
aus der Vorlage an, laedt die H5P-Libraries und installiert den Playwright-Browser.
Manuell statt dessen:

```bash
pip install -e '.[dev]'
inv kurse.update-h5p-libraries
```

Anschließend prüft `inv doctor`, ob alle Werkzeuge bereit sind.

Nach dem Setup sollten diese Befehle funktionieren:

```bash
course-sync --help
inv -l
```

Ohne `pip install -e .` funktionieren die `inv kurse.*`-Tasks trotzdem (sie setzen
`PYTHONPATH` selbst); nur das direkte `course-sync`-Kommando braucht die Installation.

## Bestehenden Kurs bauen und ansehen

```bash
course-sync list-courses --verbose
course-sync export-site h5p-demo
```

Öffne anschließend `build/site/index.html` im Browser oder starte einen einfachen lokalen
Webserver:

```bash
python -m http.server 8000 --directory build/site
```

Die statische Ansicht ist dann unter <http://127.0.0.1:8000/> erreichbar.

## Eigenen Kurs anlegen

```bash
course-sync new-course info-2026 --title "Informatik 2026"
course-sync export-site info-2026
```

Der neue Kurs enthält ein Kapitel und eine lauffähige PythonQuestion. Bearbeite danach:

- `unterricht/kurse/info-2026/index.mdx`
- `unterricht/kurse/info-2026/chapters/001-einstieg.mdx`
- `unterricht/kurse/info-2026/h5p/001-einstieg/hello-world/content.mdx`
- `unterricht/kurse/info-2026/h5p/001-einstieg/hello-world/settings.yml`
- `unterricht/kurse/info-2026/h5p/001-einstieg/hello-world/h5p.json`

## H5P-Dateien exportieren

```bash
course-sync sync info-2026
course-sync audit info-2026
course-sync export-chapter info-2026 001-einstieg
```

Ohne `--output` landen die Dateien unter `unterricht/kurse/<kurs>/exports/<kapitel>/`.

## Statische Website exportieren

```bash
course-sync export-site miniworlds_examples python-2026 --site-url https://courses.example.org
inv kurse.export-site --courses "miniworlds_examples python-2026" --site-url https://courses.example.org
```

Der Export schreibt HTML-Seiten und kopiert die gebauten `.h5p`-Pakete nach `build/site/`
(Standardziel; ein anderes mit `--output` setzen). Die Seite ist rein statisch und
funktioniert lokal genauso wie auf GitHub Pages. Mit `--site-url` erhält der Export
Canonical-Metadaten und eine `CNAME`-Datei für die Custom Domain.

## Moodle konfigurieren

```bash
cp .env.example .env
```

Trage mindestens die Werte ein, die du für deinen Weg brauchst:

- `MOODLE_BASE_URL` und `MOODLE_TOKEN` für API-Import, Status und Ping
- `MOODLE_USERNAME`, `MOODLE_PASSWORD` und `MOODLE_COURSE_URL` für Browser-Uploads

Verbindung prüfen:

```bash
course-sync moodle-ping
```

Ganzen Kurs hochladen und Moodle-Abschnitte mit `index.mdx` abgleichen:

```bash
course-sync upload-course-moodle info-2026 --verify-remote
```

Moodle-Abschnitte, die nicht (mehr) in `index.mdx` vorkommen, bleiben dabei standardmäßig
erhalten. Nur mit der expliziten Option `--prune-extra-sections` werden sie inklusive ihrer
Aktivitäten gelöscht:

```bash
course-sync upload-course-moodle info-2026 --prune-extra-sections
```

Ein einzelnes Kapitel gezielt hochladen:

```bash
course-sync upload-chapter-moodle info-2026 001-einstieg
```

Headless-Uploads brauchen entweder einen gültigen Storage-State oder Moodle-Zugangsdaten. Für einen Kurs `info-2026`
werden zuerst die kursbezogenen Variablen gelesen:

```env
MOODLE_INFO_2026_COURSE_URL=https://moodle.example.org/course/view.php?id=42
MOODLE_INFO_2026_USERNAME=mein-login
MOODLE_INFO_2026_PASSWORD=mein-passwort
```

Danach funktioniert der Upload ohne sichtbaren Browser:

```bash
course-sync upload-course-moodle info-2026 --headless --verify-remote
```

Mehrere Ziele für denselben Kurs werden über `--target` gewählt. Beispiel:

```env
MOODLE_INFO_2026_SCHULE_COURSE_URL=https://moodle.example.org/course/view.php?id=42
MOODLE_INFO_2026_SCHULE_USERNAME=mein-login
MOODLE_INFO_2026_SCHULE_PASSWORD=mein-passwort
```

```bash
course-sync upload-course-moodle info-2026 --target=schule
```

Nicht-geheime Einstellungen eines Ziels können alternativ versioniert im Kurs
liegen. Beispiel `unterricht/kurse/info-2026/.moodle-target-schule.yml`:

```yaml
auth: schulportal-hessen
course_url: https://moodle.example.org/course/view.php?id=42
```

Zugangsdaten bleiben weiterhin in `.env` oder in CI-Secrets. Für das Beispiel
heißen sie `MOODLE_INFO_2026_SCHULE_USERNAME` und
`MOODLE_INFO_2026_SCHULE_PASSWORD`.

Ziele, auf denen die in `course.yml` definierten `secrets` (z. B. echte Namen)
im Klartext bleiben sollen, setzen `keep_secrets: true` in derselben Datei. Alle
anderen Ziele bekommen die neutralen Ersetzungen – siehe
[Kursformat: secrets](./course-format.md#secrets--namen-und-andere-nicht-ffentliche-werte).

```yaml
auth: schulportal-hessen
course_url: https://moodle.example.org/course/view.php?id=42
keep_secrets: true
```

## Qualität prüfen und veröffentlichen

Der lokale Audit baut den Kurs und prüft typische Probleme in Quellen und H5P-Paketen:

```bash
course-sync audit info-2026
```

Nach einem Upload kann `verify-moodle` die eingebetteten H5P-Frames im Remote-Kurs prüfen. Dabei zählt nicht nur der Moodle-Titel, sondern sichtbarer Inhalt im H5P-Frame.

```bash
course-sync verify-moodle info-2026 --headless
```

Der Komfortbefehl `publish` führt Audit, Upload, Remote-Verifikation und Statusausgabe in einem Lauf aus:

```bash
course-sync publish info-2026 --headless
```

## Moodle-Upload: Zwei Nutzer erforderlich

Für Browser-Uploads (Playwright) und API-Zugriffe werden **zwei separate Moodle-Nutzer** benötigt:

- **Playwright-Nutzer**: Muss als Trainer/in oder ähnlich im Kurs eingeschrieben sein
  (Browser-Login für den Upload)
- **Webservice-Nutzer** (Token): Muss ebenfalls im Kurs eingeschrieben sein
  (API-Zugriffe für den Upload)

Es reicht nicht, nur einen der beiden einzuschreiben — sonst scheitert der Upload
mit einem Login-Fehler.

## Typische Probleme

`course-sync: command not found`

Führe `pip install -e .` im material-datenbank-Repo-Root aus (oder nutze die
`inv kurse.*`-Tasks, die keine Installation brauchen).

`Kurs '...' wurde nicht gefunden`

Nutze `course-sync list-courses` und prüfe den Ordnernamen unter `unterricht/kurse/`.

Fehlende H5P-Libraries

```bash
course-sync update-h5p-libraries
```

Preview-Port belegt, falls du die alte dynamische Preview nutzt

```bash
course-sync serve --port 8770
```
