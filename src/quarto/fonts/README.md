# Schriften für Titelköpfe und Überschriften

Die unveränderten Original-Schriftdateien in den Familienordnern stammen aus dem offiziellen
Repository [google/fonts](https://github.com/google/fonts). Jede Familie enthält
ihre eigene vollständige `OFL.txt` mit Copyrightvermerk. Alle hier enthaltenen
Familien stehen unter der SIL Open Font License 1.1.

`manifest.json` hält den konkreten Quell-Commit, die Download-URL und SHA-256
jeder Datei fest. Dateien dieses Pakets bei Updates nicht stillschweigend
ersetzen: Neue Fontversionen benötigen eine neue Herkunftsdokumentation und
eine erneute Layoutprüfung.

Der Ordner `static/` enthält daraus mit `build_static.py` erzeugte, ausdrücklich
veränderte Fassungen: feste Schnitte (600/700 beziehungsweise vorhandene statische
Schnitte), gegebenenfalls optische Größe 20, neue Familiennamen mit Präfix
`Material` und angepasste Stil-Metadaten. Die Glyphenformen werden nicht manuell
bearbeitet. Diese Fassungen stehen ebenfalls unter OFL 1.1; die ursprünglichen
Copyrightvermerke bleiben in Fonts und Lizenzdateien erhalten.
`static-manifest.json` dokumentiert Eingaben, Achsenwerte und Ausgabeprüfsummen.
Zur Neuerzeugung ist FontTools erforderlich, zum Rendern nicht.
Bangers (Überschriften der Anime-Vorlagen) liegt unter `static/` unverändert und unter dem
Originalnamen: Die Schrift ist bereits statisch und reserviert keinen Namen.
Acme heißt in der veränderten Fassung `Material Cartoon`, damit der reservierte
Originalname nicht als Familienname verwendet wird. Barlow Semi Condensed heißt
`Material Sport`, weil Typst Breitenangaben im Familiennamen normalisiert.
Die übrigen Familien heißen `Material <Originalfamilie>`.

Alle Schnitte enthalten `ÄÖÜäöüß`. Das große `ẞ` fehlt in Balsamiq Sans,
Fredoka, Barlow Semi Condensed, Acme und Cinzel; dort greift die angegebene
Ersatzschrift Noto Sans. Für durchgehende Großschreibung daher die tatsächliche
Darstellung prüfen und keine vollständige Zeichenabdeckung voraussetzen.

Die Projektkonfiguration stellt `static/` Quarto/Typst als `font-paths`
bereit. Eine systemweite Installation und externe Fontabrufe beim Rendern sind
nicht erforderlich. Die Schriften dürfen mit den Templates weitergegeben werden;
dabei die zugehörigen Copyrightvermerke und Lizenzdateien erhalten. PDFs mit
eingebetteten Schriften müssen nicht unter OFL veröffentlicht werden.

Die Auswahlrecherche liegt im privaten Ordner `src/quarto/_local/` (nicht versioniert).


## Alice für die literarischen Titelköpfe

`alice/` enthält Alice Regular samt vollständiger OFL 1.1 und Copyrightvermerk
(Copyright 2011 The Alice Project Authors). Die Quelle ist wie die übrigen
Originale auf den Commit in `manifest.json` festgelegt. Cyreal beschreibt
Lewis Carrolls Roman ausdrücklich als Inspiration: https://www.cyreal.org/fonts/alice/.

Der bestehende Paketbau erzeugt daraus den umbenannten festen Schnitt
`static/alice/MaterialAlice-Regular.ttf` mit unveränderten Glyphen. Die
Namens- und Stilmetadaten sind angepasst; auch diese Fassung bleibt unter
OFL 1.1. Lizenz und Copyright werden mitgeliefert, die Ausgabeprüfsumme steht
in `static-manifest.json`. Es gibt nur Regular; keine künstliche Fettung verwenden.

Alice Check-up v7 verwendet Material Alice im Titel mit 22 pt und in den
Themenüberschriften mit 16 pt. Aufgaben, Regelkarten und Fließtext behalten
Noto Sans; Formeln behalten ihre Mathematikschrift. Alice enthält `ÄÖÜäöüß`,
aber kein großes `ẞ`. Der explizite Ersatz Noto Sans deckt dieses Zeichen ab.


## Lilita One (Material Insel)

`lilitaone/` enthält Lilita One Regular samt vollständiger OFL 1.1 und
Copyrightvermerk (Copyright (c) 2011 Juan Montoreano). Quelle ist wie bei den
übrigen Originalen der in `manifest.json` festgelegte Commit von google/fonts.
Die Lizenz legt **Lilita** als reservierten Schriftnamen fest. Deshalb heißt die
veränderte feste Fassung `static/lilitaone/MaterialInsel-Regular.ttf` mit dem
Familiennamen `Material Insel`; kein Namenseintrag enthält den reservierten Namen.
Die Glyphenformen bleiben unverändert, Lizenz und Copyright werden mitgeliefert.
Es gibt nur Regular; keinen künstlichen Fettdruck anfordern (Typst-Gewicht
`regular`). Die Schrift enthält `ÄÖÜäöüß`, aber weder `ẞ` noch Pfeile; für Formeln
und Fließtext bleibt die Materialschrift zuständig.
