# Blog-Plugin

Das Blog-Plugin liegt in einem eigenen Git-Repository unter `plugins/blog/`.
Plugin-Code, Pelican-Theme, Tests und vollständige Anleitung werden dort gepflegt.
Material-UI lädt es als projektlokales Plugin; Blog-Inhalte liegen weiterhin
separat unter `blog/`, die erzeugte Website unter `build/blog/`.

Nach dem Einhängen der Plugin-Arbeitskopie installieren:

```sh
pip install -e plugins/blog
inv material-ui
```

Das Plugin bringt seine Abhängigkeiten und den Befehl `material-blog` mit.
Die Invoke-Tasks `inv blog.build`, `inv blog.publish` usw. werden über den
Paket-Entry-Point `material_ui.tasks` eingebunden. Ohne das Paket bleiben die
übrigen Werkzeuge verfügbar. Vollständige Anleitung: `plugins/blog/README.md`.

Veröffentlichungs- und Backup-Schlüssel bleiben außerhalb beider Repositories
unter dem lokalen Benutzer-Konfigurationsverzeichnis.

Blogbeiträge öffnen sich im regulären Dokumenteditor. Die Markdown-Vorschau zeigt
auch ungespeicherte Änderungen und funktioniert ebenso für Notizen. Sie benötigt
keinen Pelican-Build. Speichern, Verlauf, lokale Wiederherstellung und
Konflikterkennung verwenden die vorhandene Dokumentlogik.

Der Status unterscheidet Entwürfe und zur Veröffentlichung vorgesehene Texte von
nachweislich veröffentlichten Ständen. Nach einer erfolgreichen Veröffentlichung
mit öffentlicher Prüfung merkt sich das Plugin die veröffentlichten Revisionen
lokal unter `build/`. Spätere Änderungen werden gesondert angezeigt. Für frühere
Veröffentlichungen ohne diesen Nachweis bleibt der Status unbekannt.

Die Inline-Rechtschreibprüfung verwendet die deutschen Wörterbücher des Browsers;
sie müssen dort installiert und aktiviert sein. Für zusätzliche Rechtschreib- und
Grammatikhinweise kann ein lokaler LanguageTool-HTTP-Server angebunden werden:
`MATERIAL_LANGUAGETOOL_URL=http://localhost:8081` beim Start der Material-UI setzen.
Die Anwendung verwendet dessen `/v2/check`-Schnittstelle, markiert Fundstellen im
Editor und zeigt Vorschläge beim Darüberfahren bzw. unter den Prüfhinweisen.
Ohne lokalen Dienst bleibt die Browserprüfung verfügbar. Öffentliche
LanguageTool-Dienste werden nicht angesprochen; Metadaten und Codeblöcke sind von
der lokalen Prüfung ausgenommen. Nach Konfigurationsänderungen den Server neu starten.
