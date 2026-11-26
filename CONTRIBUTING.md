# Mitarbeit

Danke fuers Interesse. Dieses Repository enthaelt nur die **Werkzeuge** (Material-UI,
course-sync, Quarto-Filter und -Vorlagen). Unterrichtsmaterial, Kurse und Wissensbasis liegen
in separaten privaten Repos und sind nicht Teil dieses Projekts.

## Entwicklung einrichten

```sh
git clone <repo-url> && cd material-datenbank
inv setup --entwicklung && inv doctor
# Die Tests der optionalen Plugins brauchen zusaetzlich pandoc, libreoffice, tesseract und ghostscript.
MATERIAL_PRIVATE_DIR=_nicht_vorhanden inv test   # Tests ohne private Vorlagen
```

Die App und die Tests muessen ohne `unterricht/`, `wissen/` und `src/quarto/_local/`
vollstaendig laufen.

## Regeln

- Nichts Privates committen: keine absoluten Benutzerpfade, Hostnamen, Zugangsdaten oder
  Namen aus Schule und Unterricht; Beispiele mit `example.org` und relativen Pfaden.
  `inv oss-pruefen` und der Hook (`inv oss-hook`) pruefen das.
- Neue Vorlagen, Designs und Schriften nur mit geklaerter Lizenz (keine Fremdmarken oder
  geschuetzten Figuren). Neue Schriften brauchen ihren Lizenztext und einen Eintrag in
  `THIRD-PARTY-NOTICES.md`.
- Bestehende Vorlagen-Releases nicht aendern, sondern neue Versionen anlegen.
- Quellen sind Markdown/QMD; `.typ` ist nur ein Build-Artefakt.
- Aenderungen mit Tests belegen; `inv konventionen` und `inv check-output-layout` sollen
  sauber durchlaufen.

## Pull Requests

Kleine, fokussierte Aenderungen mit kurzer Beschreibung (Was und Warum). Mit dem Einreichen
stimmen Sie zu, dass Ihr Beitrag unter der MIT-Lizenz des Projekts steht.
