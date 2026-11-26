# Klausur- und Arbeitsblatt-Syntax

Markdown ist die Autorensprache. Quarto rendert die `.qmd`-Quellen nach LaTeX/PDF;
`src/quarto/filters/exam.lua` uebersetzt semantische Markdown-Divs wie `aufgabe`, `teil`
und `kasten` in LaTeX-Kommandos aus `src/quarto/templates/exam-header.tex`. Die
LaTeX-Grundstruktur liegt in `src/quarto/templates/latex-template.tex`.

Neues Material schreibt rohes LaTeX/Typst (`{=latex}`/`{=typst}`-Rohbloecke,
eigene `\newcommand`/`\newenvironment`, `\begin{tikzpicture}`, `\input{...}`)
grundsaetzlich nicht direkt, sondern nutzt vorhandene Shortcuts oder erweitert
`src/quarto/filters/exam.lua` um einen neuen. `src/tests/test_no_raw_latex_shortcuts.py`
prueft das automatisiert gegen eine Basislinie bestehender Ausnahmen (die
Basislinie liegt wegen der privaten Pfade in `unterricht/.raw-latex-baseline.json`,
nicht in diesem Repo); ein KI-Agent, der auf diese Warnung stoesst, soll einen
bestehenden Shortcut verwenden oder in `exam.lua` einen neuen bauen bzw. einen
bestehenden erweitern (z. B. `farben=`/`kommentar=` bei `[Modell rechenstrich]`),
statt die Stelle unveraendert zu lassen. Wichtige Lektion dabei: Markdown-Shortcuts
werden innerhalb von `{}`-Argumenten eigener LaTeX-Makros oder in rohen
`\begin{...}...\end{...}`-Umgebungen von Pandoc nicht verarbeitet (als unveraendertes
Rohmaterial durchgereicht) -- solche Stellen muessen auf Pandoc-native Konstrukte
(`:::`-Divs, Markdown-Listen/-Tabellen) umgestellt werden, damit ein Shortcut darin
wirkt.

Klausuren koennen ohne Pandoc-`:::`-Bloecke geschrieben werden:

```markdown
[Deckblatt: Klausur · Informatik · E2 | Python · Einführungsphase 2 | Untertitel]
[Schuelerfelder]
[Bewertungsfelder: 54]

[Hinweise]
- Namen auf jede Seite schreiben

[/Hinweise]

[Notenspiegel]
[Seitenumbruch]

## Aufgabe 1: Code lesen [10 P]

### a) [6 P]

Rückgabewert: [Antwortlinie]

[Antwortkasten: 2.5cm]
```

Weitere Marker:

- `[Antwortlinie füllend]` erzeugt eine Antwortlinie über die volle verfügbare
  Breite; in Tabellenzellen füllt sie die Zelle (auch `[antwortlinie fuellend]`).
  Feste Breiten mit `[antwortlinie 1cm]` sind weiterhin möglich.
- `[Platz 1.5cm]` erzeugt ein kleines, hellgraues, randloses Antwortfeld
  (Füllfarbe `#eeeeee`, Höhe 0.45cm) zum Einsetzen eines Ergebnisses mitten im
  Fließtext, z. B. `$356+125=$[Platz 1cm]`. Ohne Breitenangabe (`[Platz]`) gilt
  1.5cm. Breiten in cm, mm oder pt, auch mit Dezimalkomma. Für ein größeres
  Rechenfeld über die volle Breite `[Antwortkasten: <Höhe>]` verwenden.
- `[Eingabetabelle] ... [/Eingabetabelle]` stellt Tabellen mit größerem
  Zellenrand für handschriftliche Eingaben dar. Mit Höhenangabe
  `[Eingabetabelle 1.2cm]` erhält jede Zeile diese Höhe (cm, mm oder pt,
  auch mit Dezimalkomma); der Zellinhalt sitzt unten, sodass über den
  Antwortlinien genug Schreibraum bleibt. In LaTeX wird die Höhe über
  `\extrarowheight` angenähert.
- `[Abstand 2mm]` fügt einen festen vertikalen Abstand ein (cm, mm oder pt),
  auch innerhalb verschachtelter Aufgaben- und Spaltenlayouts.
- `[Schülerfelder 1cm]` fügt über den Schülerfeldern zusätzlichen Platz ein.
  Der Abstand ist in cm frei wählbar (z. B. `0,5cm`); auch
  `[Schuelerfelder 1cm]` funktioniert. Ohne Maß bleibt das bisherige Layout erhalten.
- `[Code-Hinweis] ... [/Code-Hinweis]`
- `[Referenz] ... [/Referenz]`
- `[Infobox: Titel] ... [/Infobox]`, `[Warnbox: Titel] ... [/Warnbox]`,
  `[Tippbox: Titel] ... [/Tippbox]`: hervorgehobene Kästen mit farbigem
  Titel für Erklärungen, Warnungen und Tipps. Der Titel ist optional
  (`[Infobox]` nutzt den Standardtitel Info, Warnbox: Warnung, Tippbox: Tipp).
  Funktionieren mit Typst und LaTeX und stehen in der Material-UI unter
  **Shortcuts** bereit.
- `::: {.box farbe="blau"} ... :::` rahmt Inhalt in einem schlichten,
  farbigen Kasten ohne Titelleiste (Text beginnt meist mit `**Überschrift**`
  als erster Zeile). `farbe` ist `blau`, `tuerkis`, `orange` oder `lila`
  (Standard `blau`); für benannte Kästen mit Titelleiste stattdessen
  Infobox/Warnbox/Tippbox verwenden. Nützlich, um mehrere farblich
  unterschiedene Beispiele nebeneinander darzustellen (siehe `.spalten`
  unten). Funktioniert mit Typst und LaTeX.
- `::: {.spalten} ::: {.spalte} ... ::: ::: {.spalte} ... ::: :::` (auch
  `.columns`/`.column`) setzt beliebig viele Blöcke nebeneinander; optional
  `breite="38"` (Prozent) pro Spalte, Rest wird gleichmäßig verteilt. Jede
  Spalte darf mehrere Absätze/Blöcke enthalten (auch verschachtelte `.box`
  oder Bilder). Für reine Aufzählungen mit festen Spalten eignet sich
  stattdessen Quartos eingebautes `::: {layout-ncol="3"} a) ... b) ... :::`
  (fließt Listenpunkte gleichmäßig in N Spalten, kein eigener Shortcut nötig).
- `[Versionen]`, `[Version]`, `[Version]`, `[/Versionen]`
- `[Mini-AB] ... [/Mini-AB]` rendert den Inhalt zweimal auf eine A4-Seite,
  getrennt durch eine gepunktete Schnittlinie in der Seitenmitte. Innerhalb des
  Blocks schaltet das Layout auf kompakte Stile (kleinere Schrift, engere
  Überschriften, einzeilige Schülerfelder, reduzierte Tabellenabstände);
  Tabellen verlieren ihre Rahmenlinien, Antwortlinien erscheinen dezent grau,
  damit das Blatt ruhig bleibt. `[Eingabetabelle 0.6cm]` passt gut zu den
  halben Seitenhöhen. Für Blätter im Mini-Format gilt die Namenskonvention
  `ab_mini_...` (Namensregel für Blätter, die mehrfach je Seite gedruckt werden). Funktioniert mit Typst und LaTeX.

Mathe-Arbeiten koennen zusaetzlich diese Marker verwenden:

- `[Mathe-Deckblatt: Titel | Datum] ... [/Mathe-Deckblatt]`
- `[Notentabelle]`
- `[Rechengitter 0.5 | 15]` mit Kästchengröße in cm und Zeilenzahl
- `[Rechengitter 0.5 | 15 | 36]` mit optionaler Spaltenzahl
- `[Schreiblinien 2]` als eigener Absatz: zwei feine Linien über die volle Textbreite
  mit 8 mm Schreibabstand (1–30 Zeilen, ohne Zahl eine Zeile). Funktioniert mit
  Typst und LaTeX und ist in der Material-UI unter **Shortcuts** verfügbar.
- `[Beweistabelle] ... [/Beweistabelle]`

Einheitskreis-Aufgaben lassen sich ohne Bilddateien mit `[Einheitskreis 75]`
zeichnen. Der Winkel wird in Grad angegeben (auch negativ oder mit Dezimalpunkt/-komma).
Von 0 bis 90 Grad wird ein Viertelkreis gezeichnet, sonst ein Vollkreis.
Achsen, Winkelmarkierung und Punkt P werden automatisch erzeugt; die Koordinaten
bleiben zum Berechnen offen. Bei mehr als einer Umdrehung zeigt die Markierung
eine volle Umdrehung, die Beschriftung weiterhin den eingegebenen Winkel.
Fuer Teilaufgaben nebeneinander:

```markdown
::: {.abbildungen .list-abc}
[Einheitskreis 75]

[Einheitskreis 45]

[Einheitskreis 30]
:::
```

Die Material-UI bietet beide Varianten unter **Shortcuts** an.
Der LaTeX/PDF-Export dieser Zeichnungen benoetigt `rsvg-convert` (Paket `librsvg2-bin`);
Typst verwendet die erzeugten SVG-Zeichnungen direkt.

Geometrische Planfiguren werden mit `[Skizze typ | option=Beschriftung]` erzeugt.
Sie sind schematisch; Beschriftungen veraendern keine Laengen oder Winkel.
Die Ausgabe enthaelt keine berechneten Ergebnisse. Beispiele:

```markdown
::: {.abbildungen .list-abc}
[Skizze dreieck | form=recht-C | a=7 cm | beta=14°]

[Skizze dreieck | form=allgemein | b=8 cm | c=10 cm | alpha=50° | hoehe=ja]
:::

::: {.abbildungen cols=2}
[Skizze steigung | x=7,5 m | h=3,2 m | s=s | alpha=α]

[Skizze pyramide | a=10 cm | h=12 cm | s=s]

[Skizze quader | laenge=9 m | breite=12 m | h=8 m]
:::
```

Typen: `dreieck`, `steigung`, `pyramide`, `quader`. Dreiecksformen: `allgemein`
(Standard), `gleichschenklig`, `recht-A`, `recht-B`, `recht-C`, `stumpf-A`,
`stumpf-C`. Die Dreiecksseiten heissen standardmaessig `a`, `b`, `c` und liegen
gegenueber von `A`, `B`, `C`; `alpha`, `beta`, `gamma` beschriften optional die
Winkel. `hoehe=ja` zeichnet im allgemeinen oder gleichschenkligen Dreieck die
Hoehe auf `AB` samt Fusspunkt `H` ein. Leere Werte blenden eine Beschriftung aus.
Die Material-UI bietet die vier Skizzentypen ebenfalls unter **Shortcuts** an.

Dreiecke lassen sich mit `drehung=150` gegen den Uhrzeigersinn drehen;
Beschriftungen bleiben dabei aufrecht. `A=D | B=F | C=E` benennt die Ecken um,
`a=d | b=f | c=e` die jeweils gegenüberliegenden Seiten. `markiert=a,c,beta`
hebt Seiten und Winkel farbig und mit kräftigerer Linie hervor. Winkelmarkierungen
ohne eigene Beschriftung erhalten automatisch α, β bzw. γ.

```markdown
[Skizze dreieck | form=allgemein | drehung=150 | beta=β | markiert=a,c,beta]

[Skizze dreieck | form=allgemein | drehung=30 | hoehe=ja | h=h]
```

Bei Pyramiden markiert `alpha=φ` den Winkel zwischen Seitenkante und ihrer
Projektion in die Grundfläche.

Für verständnisorientierte Arithmetik-Aufgaben gibt es außerdem
`[Modell rechenstrich | knoten=3987,4000,4002 | spruenge=+?,+?]`,
`[Modell punktefeld | zeilen=4 | spalten=6]` und
`[Modell flaeche | oben=20,6 | links=10,4]`.
Diese Shortcuts funktionieren mit Typst und LaTeX und stehen in der Material-UI
bereit. Beispiele und Optionen: [Arithmetik-Modelle](../src/quarto/ARITHMETIK-MODELLE.md).

### Hautfarbe von Dialogfiguren

Die Hautfarbe lässt sich pro `dialogbeitrag` unabhängig von Frisur, Haar- und Akzentfarbe einstellen, z. B.:

```markdown
:::: {.schuelerdialog layout="kompakt"}
::: {.dialogbeitrag name="Mia" figur="zopf" haarfarbe="#d9b34a" hautfarbe="#ffe1bd" farbe="#498532"}
Ich erkläre meinen Weg.
:::
::::
```

`hautfarbe` erwartet einen sechsstelligen Hex-Farbcode. Ohne Angabe gilt die bisherige Vorgabe der Figur. Im Editor bietet „Schülerdialog: eigene Figurenfarben“ ein Hautfarbenfeld pro Person. Die Einstellung gilt für normales und kompaktes Layout sowie den LaTeX-Export.

### Mini-AB mit Diagnosekarten und kombinierter Auswertung

Mit `mini-diagnose: true` im YAML-Kopf und `worksheet-mini.typst` als Template
steht ein Diagnose-Layout zur Verfügung. Inhalte bleiben Markdown; die Gestaltung
liegt in `worksheet-mini-diagnose-layout.typst`. Die Material-UI bietet beide
Bausteine unter **Shortcuts** an.

```markdown
[Mini-AB]

# Mein Check

::: {.mini-karte nummer="1" titel="Einmaleins" hoehe="34mm"}
$7\cdot8=$ [Antwortlinie 12mm]
:::

[/Mini-AB]
```

Mehrere Karten werden mit dem vorhandenen `.columns`-/`.column`-Shortcut
nebeneinander angeordnet. `hoehe` ist eine feste Kartenhöhe von 20 bis 120 mm;
bei übervollen Karten Inhalte reduzieren oder Höhe anpassen. Die Kopfzeile
enthält Nummer, Titel und die Einschätzung S / ? / H.

```markdown
::: {.mini-auswertung}
| Nr. | Lösung | Heftaufgaben |
|---|---|---|
| 1 | $7\cdot8=56$<br>Vergleiche deinen Weg. | ☐ S. 45, Nr. 5 |
:::
```

Die Auswertung benötigt genau eine Tabelle mit drei Spalten, Kopf und mindestens
einer Inhaltszeile. `<br>` erzeugt einen Zeilenumbruch innerhalb einer Zelle.
Die Tabelle verwendet die ganze Mini-AB-Breite und lesbare 10,5-Punkt-Schrift.
Typst rendert das Diagnose-Layout; LaTeX erhält die Markdown-Inhalte ohne die
speziellen Diagnose-Rahmen. Punktefeld, Malkreuz, Rechengitter, Schreiblinien,
Antwortlinien und Abstände verwenden weiterhin die bestehenden Shortcuts.
