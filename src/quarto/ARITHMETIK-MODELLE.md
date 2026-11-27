# Arithmetik-Modelle als Markdown-Shortcuts

Diese Kürzel werden vom Projektfilter `filters/exam.lua` für Typst und LaTeX
gezeichnet. Die Material-UI bietet sie unter **Shortcuts** an. Im Unterricht
sollen die Modelle beschriftet, zerlegt und zum Erklären verwendet werden.
Ergebnisse werden nicht automatisch eingetragen.

```markdown
[Modell rechenstrich | knoten=3987,4000,4002 | spruenge=+?,+?]

[Modell punktefeld | zeilen=4 | spalten=6]

[Modell flaeche | oben=20,6 | links=10,4]

[Modell hoehenprofil | start=1250 | etappen=-380,-220,-450 | offen=ja]

[Modell hoehenprofil | start=2480 | etappen=+20 m,+500 m | offen=ja]
```

## Rechenstrich

`knoten` enthält 2–6 kommagetrennte Beschriftungen (mit `offen=ja` bis 13). `spruenge` enthält genau
eine Beschriftung weniger als `knoten`; jeder Sprung führt von einem Knoten zum
nächsten in der Liste. Zahlen, Rechenzeichen, `?` und leere
Beschriftungen sind möglich. Die Zeichnung ist schematisch, nicht maßstäblich.
Sprungweiten werden aus der Beschriftung abgelesen. Kommas trennen Einträge;
Dezimalzahlen deshalb mit Dezimalpunkt schreiben.

Die Sprungrichtung folgt dem Vorzeichen: `+`-Sprünge zeigen nach rechts,
`-`-Sprünge nach links. Die Knoten werden dazu nach (geschätztem) Wert auf dem
Strich angeordnet; unbekannte Knoten (`?`) werden aus dem vorherigen Wert plus
Sprung abgeschätzt. Ohne Vorzeichen richtet sich der Sprung nach den Knotenwerten
bzw. der Hauptrichtung der Rechnung. Passt ein Vorzeichen nicht zu bekannten
Knotenwerten (etwa `+10` von 100 nach 90), bricht der Build mit einer
Fehlermeldung ab.

Beispielauftrag: „Ergänze die Sprungweiten. Erkläre, was ihre Summe für
die Rechnung 4002 − 3987 bedeutet.“

Die Sprungfarbe folgt der Richtung: Sprünge nach rechts (Plus) sind rot
(`#c62828`), Sprünge nach links (Minus) blau (`#1565c0`) – Bögen,
Pfeilspitzen, Startpunkte und Sprungbeschriftungen gleichermaßen.
Knotenbeschriftungen und der Zahlenstrich selbst bleiben immer dunkel.
Mit `farbe` werden alle Sprünge einheitlich umgefärbt – etwa `farbe=rot`
(`#c62828`) oder ein Hex-Code wie `farbe=#1565c0`. Mit `farben` lässt sich
stattdessen jeder Sprung einzeln umfärben: ein kommagetrennter Eintrag je
`spruenge`-Eintrag, leer lässt die Richtungsfarbe. Beispiel für einen
hervorgehobenen mittleren Sprung bei „gleiches Verändern“
(`7043-1998 = 7045-2000`):

```markdown
[Modell rechenstrich | knoten=7043,7045,5047,5045 | spruenge=+2,-1998,-2 | farben=,#b35900,]
```

`kommentar` setzt eine zusätzliche Textzeile unter den Zahlenstrich, z. B.
für die ausgeschriebene Rechnung. Der Text wird als einfacher Text gesetzt,
nicht als Mathe (keine LaTeX-Befehle, kein `$...$`). Absichtlich nicht
`beschriftung` genannt: der Name bedeutet bei `[Modell koordinatensystem]`
eine Achsenschrittweite und bei `[Modell bruchrechteck]` einen
ja/nein-Schalter – ein dritter, abweichender Sinn hätte ihn überladen.

```markdown
[Modell rechenstrich | knoten=?,?,?,?,4215 | spruenge=+2000,+300,+40,+8 | kommentar=4215-2348 = 1867]
```

Überlappen sich Sprünge (gemischte Sprungrichtungen), wächst die Bogenhöhe mit
der Sprungweite: Weite Sprünge wölben sich über flache, die Bögen schneiden
sich nicht. Sprungbeschriftungen tragen einen weißen Halo und bleiben auch
dann lesbar, wenn ein Bogen durch sie läuft.

Mit `offen=ja` werden nur der Strich und die Knoten gezeichnet – Bögen,
Pfeilspitzen und Sprungbeschriftungen fehlen, `spruenge` darf wegfallen. Die
Sprünge ergänzt man selbst. Ohne Bögen sind bis zu 13 `knoten` möglich, etwa
`knoten=0,,,,,,1` für sechs gleich große Abschnitte. Beispielauftrag „Zeichne die Sprünge am
Rechenstrich ein und notiere ihre Weiten.“ Leere `knoten`-Einträge zwischen
zwei beschrifteten Werten ergeben gleichmäßig verteilte, unbeschriftete
Strichmarken zum Selbsteintragen, z. B. `knoten=2486,,,,` für einen Strich,
der nur links mit `2486` beginnt.

## Punktefeld

`zeilen` ist eine ganze Zahl von 1 bis 12, `spalten` von 1 bis 20. Es werden
genau so viele Reihen und Punkte pro Reihe gezeichnet. Die Faktoren und
die Gesamtzahl werden nicht beschriftet.

Beispielauftrag: „Beschrifte die Faktoren. Zerlege das Feld in zwei Teile
und schreibe dazu eine Summe aus zwei Malaufgaben.“

`produkt=ja` schreibt die Gesamtzahl der Punkte unter das Feld, z. B.
`[Modell punktefeld | zeilen=3 | spalten=5 | produkt=ja]` mit der 15. Für
Divisionsaufgaben, in denen das Produkt gegeben und ein Faktor gesucht ist.
`zuschnitt=eng` schneidet die Zeichenfläche eng um Punkte und Produkt zu, damit
kleine Felder in schmalen Spalten groß genug erscheinen
(`bildbreite=40mm` für 3 × 5 Punkte).

`seiten=ja` schreibt die Seitenlängen an das Feld: links die Zeilenzahl, oben die
Spaltenzahl (bei Teilung je Teilfeld), jeweils in einer Klammer. Mit `produkt=ja`
steht die Gesamtzahl dann in der Mitte des Feldes.

`teilung=10` zerlegt die Spalten nach der angegebenen Zahl (`teilung=10,2` schneidet
nach 10 und weiteren 2 Spalten; der Rest bildet das letzte Teilfeld, höchstens vier
Teilfelder). Jedes Teilfeld wird in einer eigenen Farbe umrandet (rot, blau, grün,
gelb wie im 400er-Feld); mit `produkt=ja` steht das Produkt des Teilfelds in seiner
Mitte, in der Farbe des Teilfelds. `seiten` und `teilung` schneiden die Zeichenfläche
wie `zuschnitt=eng` zu.
`gesucht=ja` (braucht `seiten=ja`) ersetzt die Spaltenzahlen oben durch ein `?`, damit bei
Divisionsaufgaben erkennbar ist, welcher Teil berechnet wird; Zeilenzahl und Produkte bleiben stehen.
Beispiel: `[Modell punktefeld | zeilen=6 | spalten=14 | teilung=10 | produkt=ja | seiten=ja | bildbreite=60mm]`
zeigt 6 · 10 = 60 und 6 · 4 = 24 als zwei Teilfelder.

## 400er-Feld mit Rechteck

`[Modell vierhundertfeld | zeilen=16 | spalten=18]` färbt das Rechteck oben
links ein und zerlegt es an den Zehnerstellen. Optionen für Divisionsaufgaben:

- `zerlegung=spalten` zerlegt nur die Spalten (zwei Teilflächen für
  $288:16=160:16+128:16$), `zerlegung=zeilen` nur die Zeilen; Standard ist `beide`.
- `produkte=ja` schreibt das Produkt jeder Teilfläche hinein (hier 160 und 128).
- `seite=zeilen` (oder `spalten`, `beide`) markiert die Seite mit einer Klammer
  und nennt die Anzahl, z. B. die 16 als Teiler.

## Flächenmodell

`oben` und `links` enthalten jeweils eine bis drei positive Zahlen bis 10000 für
die Seitenabschnitte. Die Abschnitte werden innerhalb jeder Seite proportional
gezeichnet. `[Modell flaeche | oben=26 | links=14]` zeigt ein unzerlegtes
Rechteck. Zwei Zahlen zerlegen die jeweilige Seite; sind beide Seiten zerlegt,
entstehen vier leere Teilflächen. Die beiden gesamten
Seiten werden unabhängig voneinander auf die Zeichenfläche skaliert.

Beispielauftrag: „Ordne jedem Teilrechteck ein Feld im Malkreuz zu.
Erkläre, warum die vier Teilprodukte zusammen das Gesamtergebnis ergeben.“

## Höhenprofil

`start` ist eine positive Zahl bis 10000 (Starthöhe), `etappen` enthält 1–5
kommagetrennte Höhenänderungen mit Vorzeichen, Zahl und optionaler Einheit
m, z. B. `-380`, `+200` oder `+20 m`. Die Zwischenhöhen werden berechnet
und an die Knoten geschrieben; jede Etappe steht mit weißem Hof direkt auf
ihrem Abschnitt – die Zahl gehört sichtbar zu dieser Etappe, ohne als
Streckenmaß missverstanden zu werden (Höhenmeter, nicht Weglänge).
Aufstiege funktionieren analog zum
Abstieg: positive Etappen wie `+20,+500` zeichnen das Profil aufwärts,
`summe=+520` spannt den Bogen über den Aufstieg. Mit `offen=ja` bleiben alle
Höhen außer der Starthöhe als `?` offen. Mit `summe=-1050` spannt sich ein
Bogen vom ersten zum letzten Knoten, beschriftet mit der angegebenen Summe –
für „mehrere Subtrahenden erst zusammenfassen“. Mit `farbe` (Hex-Code oder
`rot`) wird nur dieser Summenbogen samt Pfeilspitze und Beschriftung
eingefärbt; Profil, Knoten und Etappen bleiben dunkel. Die Zeichnung ist
schematisch, nicht maßstäblich.

Beispielauftrag: „Schätze die Höhe der Hütte. Erkläre, warum du die drei
Abstiege erst addieren und dann einmal abziehen darfst.“

## Bauen

Materialien mit `inv build --source <pfad.qmd>` oder `make <pfad.qmd>` bauen.
PDFs liegen zentral unter `build/pdf/`, weitere Artefakte unter `build/artefakte/`. Der LaTeX-Export
benötigt `rsvg-convert`; Typst verwendet die SVG-Modelle direkt.


## Malkreuz mit Lücken

`[Modell malkreuz | felder=20,?,?,200,?,2,?,8 | bildbreite=64mm]`

`felder` gibt die acht Felder zeilenweise ohne das Malzeichen an:
oben zwei Randzahlen, dann linke Randzahl und zwei Teilprodukte,
dann die zweite linke Randzahl und zwei Teilprodukte. `?` lässt das Feld
leer zum Ergänzen. Vorgegebene Teilprodukte werden unverändert angezeigt;
fehlende Zahlen werden nicht automatisch berechnet. Die Option ist eine
Alternative zu `oben`/`links` und wird nicht mit ihnen kombiniert.

## Ziffernrätsel: Karten und Rechenraster

```markdown
[Modell ziffernraetsel | aufgabe=3_1_*2 | ergebnis=6830 | bildbreite=60mm]
```

Oben stehen die Ziffernkarten der Malaufgabe. `_` oder `?` lässt eine Karte
leer, vorgegebene Ziffern bleiben sichtbar. Darunter steht dieselbe Aufgabe
in einem zweizeiligen Kästchenraster mit dem vorgegebenen Ergebnis in der
zweiten Zeile. Jede Ziffer hat eine eigene Stelle; die Einer des letzten
Faktors und des Ergebnisses stehen untereinander. Fehlende Ziffern werden
**nicht** berechnet oder angezeigt.

`aufgabe` enthält zwei Faktoren mit jeweils 1–6 Ziffern oder Lücken;
als Malzeichen sind `*`, `·`, `×` und `x` erlaubt. `ergebnis` enthält
1–12 Ziffern. Mehrstellige Zahlen beginnen nicht mit 0. Die Breite lässt
sich wie bei anderen Modellen über `bildbreite` (10–250 mm) steuern.
Bei vierstelliger Zahl mal einstelliger Zahl ergeben 42 mm Bildbreite
ungefähr 5-mm-Kästchen. In der Material-UI steht der Shortcut
**„Ziffernrätsel: Karten und Rechenraster“** bereit.

## Schriftliche Multiplikation als Modell

```markdown
[Modell schriftlich | aufgabe=356*17 | bildbreite=65mm]
[Modell schriftlich | aufgabe=346*107 | nullzeile=ja | bildbreite=65mm]
```

Das Modell berechnet Teilprodukte und Ergebnis automatisch. Jede Ziffer steht
in ihrer Stellenwertspalte; rechts der verschobenen Teilprodukte bleiben
Stellen frei. `nullzeile=ja` zeigt Nullzeilen, `nein` lässt sie weg (Standard).
`endnullen=ja` schreibt verschobene Teilprodukte mit Nullen aus (`34600` statt
`346` mit freien Stellen). `teilrechnungen=ja` nennt neben jeder Zeile die
Rechnung, z. B. `346 · 100`. Beide sind standardmäßig `nein`.
Bei versionierten Dokumenten wird ein Release mit diesen Optionen benötigt.
Die Faktoren dürfen je 1–6 Ziffern enthalten, die Bildbreite beträgt 10–250 mm.
Malkreuze unterstützen mit `oben` und `links` jeweils bis zu drei Teilzahlen,
z. B. `oben=300,50,6 | links=10,7`.

## Dialoge mit Rechenmodellen

```markdown
:::: {.schuelerdialog}
::: {.dialogbeitrag name="Mia" figur="zopf" haarfarbe="#d9b34a" farbe="#498532"}
Ich zerlege beide Faktoren.

[Modell malkreuz | oben=300,50,6 | links=10,7 | bildbreite=65mm]
:::
::: {.dialogbeitrag name="Kim" figur="zopf" haarfarbe="#a45832" farbe="#426a9c"}
Ich fasse die Teilprodukte zusammen.

[Modell schriftlich | aufgabe=356*17 | bildbreite=65mm]
:::
::::
```

Namen, Texte, Figuren und Farben sind unabhängig vom Thema oder Design.
`haarfarbe` überschreibt die Haarfarbe der generischen Figur, `farbe` die
Akzent- und Kleidungsfarbe; beide akzeptieren sechsstellige Hex-Codes.
Der erste Absatz eines Beitrags ist die Sprechblase; Modelle folgen darunter.
Die Material-UI bietet „Schülerdialog: eigene Figurenfarben“ und
„Modell: schriftliche Multiplikation“ als konfigurierbare Shortcuts.

Mit `gruppen=zeilen` verwenden Malkreuz und schriftliche Multiplikation
passende Farben: Alle Felder einer Malkreuzzeile haben dieselbe Farbe wie
das daraus gebildete schriftliche Teilprodukt. Bei beiden Modellen müssen
die Faktoren dazu in derselben Reihenfolge zerlegt sein. Standard ist die
bisherige Feldfärbung im Malkreuz (`gruppen=felder`) beziehungsweise eine
neutrale Rechnung (`gruppen=keine`). Große Produkte im dreispaltigen
Malkreuz werden automatisch kleiner gesetzt, damit sie in ihr Feld passen.


## Anteile im Rechteckmodell

```markdown
[Modell bruchrechteck | werte=1/8,1/4,1/2,1,2,4,8 | raster=gestrichelt | bildbreite=160mm]
[Modell bruchrechteck | werte=3/4,5/4 | raster=ja]
```

Jedes ganze Bezugsrechteck bleibt gleich groß und gleich hoch. Ein gestrichelter
Rand zeigt das Ganze, die blaue Markierung seinen Anteil. Mehrere Ganze stehen
nebeneinander. `raster=ja` zeichnet durchgezogene Teilungslinien;
`raster=gestrichelt` gestrichelte; `nein` lässt sie weg.
`werte` enthält 1–12 Brüche oder ganze Zahlen von 0 bis 8 (Nenner 1–64).
Ein `?` erzeugt ein leeres, ungeteiltes Bezugsrechteck zum eigenen Unterteilen.
`bildbreite` steuert die Breite der gesamten Folge (10–250 mm).

Beschriftungen werden gemeinsam mit der Skizze platziert:

```markdown
[Modell bruchrechteck | werte=?,?,1/8,1/4,1/2,1,2,4,8 | raster=gestrichelt | beschriftung=ja | texte=?,?,?,?,?,2⁰,2¹,2²,? | bildbreite=180mm]
```

`beschriftung=ja` zeigt den Wert direkt unter der jeweiligen Skizze.
`texte` ergänzt eine zweite Zeile mit einem Eintrag pro Modell; Unicode-Hochzahlen wie `2⁰` bleiben unverändert erhalten. `?` lässt eine Schreiblinie. Standardmäßig sind beide
Beschriftungszeilen ausgeschaltet. Alle Beschriftungen sitzen mittig unter
der gesamten zugehörigen Gruppe, auch bei mehreren Ganzen.

## Mehrere Funktionsgraphen

```markdown
[Koordinatensystem | x=-4..4 | y=-2..6 | funktionen=x^2;1 | farben=#b34300;#1565c0 | beschriftung=1]
```

`funktionen` enthält durch Semikolon getrennte Funktionsterme in `x`.
`farben` enthält dazu genau eine Farbe pro Term (`rot` oder `#rrggbb`).
Ohne `farben` gilt `farbe` für alle Terme. Unterstützt werden Zahlen,
`+ - * / ^`, Klammern, `pi` und `sin`, `cos`, `tan`, `sqrt`, `abs`, `exp`,
`log` (natürlicher Logarithmus). Multiplikation explizit schreiben: `0.5*x^2`.
Beispiel: `funktionen=sin(x);sqrt(x);2*x-1`.
Nicht definierte Werte und außerhalb des sichtbaren Bereichs liegende Abschnitte
werden ausgelassen. Die Darstellung erfolgt durch numerische Abtastung;
bei sehr schnellen Schwingungen oder Polstellen den Bereich passend wählen.
Die bisherigen Optionen `funktion=parabel` und `funktion=kubik` bleiben gültig.

Mit `funktionsnamen=ja` werden die Gleichungen direkt an den Graphen in deren
jeweiliger Farbe angezeigt, zum Beispiel `y = x²` und `y = 1`. Weiße Konturen
halten die Schrift vor Raster und Kurven lesbar. Standardmäßig sind die
Funktionsnamen ausgeschaltet (`funktionsnamen=nein`). Die Achsenoption
`beschriftung=1` steuert weiterhin ausschließlich die Zahlen an den Achsen.

```markdown
[Koordinatensystem | x=-4..4 | y=-2..6 | funktionen=x^2;1 | farben=#b34300;#1565c0 | funktionsnamen=ja | beschriftung=1]
```

Eigene kurze Namen sind ebenfalls möglich: `funktionsnamen=f;g`.
Genau einen Eintrag pro Graphen angeben; ein leerer Eintrag lässt den betreffenden
Graphen unbeschriftet, etwa `funktionsnamen=;y = 1`.
Bei versionierten Dokumenten wird ein Release mit dieser Option benötigt.


## Ergebnisse in Lösungsblättern

`[$3^4=81$]{.loesung}` hebt ein Ergebnis blau hervor. Die Erklärung davor
oder danach bleibt in normaler Textfarbe.
