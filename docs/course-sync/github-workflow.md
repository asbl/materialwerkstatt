# Vollständig auf GitHub arbeiten

> **Hinweis:** Dieses Dokument beschreibt den Workflow aus dem eigenstaendigen
> course-sync-Repo (eigene Codespace-Config, eigene GitHub-Actions-Workflows
> `course-ci.yml`/`publish-moodle.yml`/`pages.yml`). Seit dem Umzug nach
> material-datenbank wurden diese Workflows und die `.devcontainer/`-Config nicht
> uebernommen (eine lokale Referenzkopie liegt nur im privaten Arbeitsbaum). Ob/wie CI, Codespaces und Moodle-Publish-Workflows fuer
> material-datenbank neu eingerichtet werden, ist noch offen.

Kursinhalte können ohne lokale Installation im Browser bearbeitet, geprüft und nach
Moodle veröffentlicht werden. Git bleibt die Quelle; Moodle ist ein kontrolliertes
Veröffentlichungsziel.

## 1. Repository als Codespace öffnen

Auf der Repository-Seite **Code → Codespaces → Create codespace on main** wählen. Der
Container installiert `course-sync`, Node, die H5P-Werkzeuge und alle benötigten
Libraries automatisch.

Im Codespace einen Branch anlegen:

```bash
git switch -c content/meine-aenderung
```

Kursquellen liegen unter `unterricht/kurse/<kurs>/`. Eine Vorschau lässt sich vollständig im
Browser starten:

```bash
course-sync audit python-2026
course-sync export-site python-2026
python -m http.server 8000 --directory unterricht/kurse/build/site
```

Codespaces öffnet Port 8000 als Vorschau. Danach die Änderung committen, pushen und
über die Codespaces-Oberfläche einen Pull Request anlegen.

## 2. Pull Requests prüfen

Der Workflow **Check course sources** führt automatisch aus:

- Unit-Tests,
- Audit aller Kurse,
- vollständigen statischen Export.

Die erzeugte Website steht im Workflow-Lauf sieben Tage als Artefakt
`course-preview` zur Verfügung. Für `main` sollte Branch Protection eingerichtet und
der Check `test-and-build` verpflichtend gemacht werden.

## 3. Moodle-Ziele als GitHub Environments konfigurieren

Unter **Settings → Environments** je ein Environment anlegen, zum Beispiel `staging`
und `production`. In jedem Environment diese Secrets hinterlegen:

| Secret | Inhalt |
| --- | --- |
| `MOODLE_COURSE_URL` | Vollständige URL des Zielkurses |
| `MOODLE_USERNAME` | In den Kurs eingeschriebener Upload-Nutzer |
| `MOODLE_PASSWORD` | Passwort des Upload-Nutzers |
| `MOODLE_BASE_URL` | Moodle-Basis-URL, falls API-Funktionen benötigt werden |
| `MOODLE_TOKEN` | Webservice-Token, falls API-Funktionen benötigt werden |

Für `production` sollten **Required reviewers** aktiviert werden. Secrets werden erst
nach dieser Freigabe an den Job übergeben und erscheinen nicht im Repository.

## 4. Nach Moodle veröffentlichen

Unter **Actions → Publish course to Moodle → Run workflow** auswählen:

1. Kursordner eingeben, zum Beispiel `python-2026`.
2. Environment `staging` oder `production` auswählen.
3. `keep_extra_sections` normalerweise aktiviert lassen.
4. Workflow starten und gegebenenfalls die Environment-Freigabe erteilen.

Der Workflow installiert Chromium, führt den Kurs-Audit aus, lädt den Kurs hoch und
prüft anschließend die eingebetteten H5P-Aktivitäten im Zielsystem. Pro Kombination
aus Kurs und Environment läuft höchstens ein Publishing-Job gleichzeitig.

## Sicherheitsmodell

- Pull-Request-Workflows erhalten keine Moodle-Secrets und verändern Moodle nicht.
- Moodle-Veröffentlichungen werden ausschließlich manuell gestartet.
- Ein geschütztes GitHub Environment trennt Staging und Produktion.
- Nicht in `index.mdx` vorhandene Moodle-Abschnitte bleiben standardmäßig erhalten.
- `.env` bleibt nur eine optionale Alternative für lokale Nutzung.
