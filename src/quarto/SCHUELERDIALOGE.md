# Schülerdialoge als wiederverwendbare Shortcuts

Die Bausteine setzen ein bis vier Beiträge nebeneinander: eine Sprechblase,
eine kleine eigene Vektorfigur mit Namen und optional fachlichen Inhalt darunter.
Sprechblasen bekommen dieselbe Höhe; Figuren und Modelle beginnen auf gleicher Höhe.
Die Texte bleiben editierbarer Markdown-Text und lassen sich durchsuchen und kopieren.
Die Beispiele übernehmen keine Illustrationen aus Schulbüchern.

## Schnellstart

```markdown
:::: {.schuelerdialog}
::: {.dialogbeitrag name="Leo" figur="brille"}
Ich multipliziere zuerst $68$ mit $8$.

$68\cdot8=544$
:::
::: {.dialogbeitrag name="Till" figur="kurz"}
Danach multipliziere ich $544$ mit $125$. Was fällt dir auf?

$544\cdot125=68000$
:::
::::
```

Der **erste Absatz** eines Beitrags ist der gesprochene Text. Er kann mehrere
Sätze, Hervorhebungen und Inline-Formeln enthalten. Ein Zeilenumbruch im
Quelltext gehört noch zum selben Absatz; eine Leerzeile beendet die Sprechblase.
Weitere Absätze erscheinen unter der Figur. Dort sind gewöhnliches Markdown,
Bilder und die vorhandenen `[Modell ...]`-Shortcuts möglich. Bilder gehören
immer in diesen Inhaltsbereich, nicht in den ersten Absatz.

## Namen, Figuren und Farben

- `name="Mia"`: notwendiger Anzeigename; bei weiteren Beiträgen darf dieselbe
  Person erneut auftreten.
- `figur="brille"`, `kurz`, `locken` oder `zopf`: vier eigene Vektorfiguren.
  Ohne Angabe werden die vier Varianten der Reihe nach gewählt.
- `figur="keine"`: nur Name und Sprechblase, z. B. für einen sachlichen Dialog.
- `farbe="#25674c"`: optionale Akzentfarbe für Kontur, Namen und Kleidung.
  Erlaubt sind sechsstellige Hex-Farben. Ohne Angabe bekommt jede Person eine
  eigene ruhige Akzentfarbe.

Die Figurenwahl ist unabhängig vom Namen und vom Thema. Für mehr als vier
Beiträge einen weiteren Dialogblock beginnen. Lange Aussagen kürzen oder auf
mehrere Beiträge verteilen; ein Dialog wird innerhalb einer Seite zusammengehalten.

## Modelle und andere Themen

```markdown
:::: {.schuelerdialog}
::: {.dialogbeitrag name="Mia" figur="zopf"}
Ich zeige meine Zerlegung im Malkreuz.

[Modell malkreuz | oben=20,6 | links=10,4 | bildbreite=55mm]
:::
::: {.dialogbeitrag name="Kim" figur="kurz"}
Ich erkläre dieselbe Aufgabe mit einer Rechnung.

$26\cdot14=26\cdot10+26\cdot4$
:::
::::
```

Unter den Beiträgen können ebenso ein Bruchmodell, ein Bild, ein Textauszug,
eine Beobachtung oder eine Liste stehen. Die Verteilung der Modellinhalte ist
frei; ein Beitrag kann auch nur aus einer Sprechblase bestehen.

## Editor und Beispiele

In der Material-UI gibt es unter **Arbeitsblatt** drei Shortcuts:

1. **Schülerdialog: zwei Personen**
2. **Schülerdialog: drei Personen**
3. **Schülerdialog: mit Modellen**

Namen und Aussagen werden im Einfügedialog angepasst; Figuren können dort
gewählt werden. Unter `src/quarto/filters/examples/schuelerdialoge/ab_beispiele.qmd`
liegen vier ausgearbeitete Beispiele: Rechenkette, Nullzeilen, Vergleich von
Malkreuz und schriftlicher Multiplikation sowie Bruchrechnung.

Bauen: `inv build --source src/quarto/filters/examples/schuelerdialoge/ab_beispiele.qmd`.
Die PDF liegt zentral unter `build/pdf/src/quarto/filters/examples/schuelerdialoge/`.

Die Bausteine verwenden den Projektfilter `exam.lua` und dessen Hilfsdatei
`student-dialog.lua`. Typst/PDF verwendet gerundete Sprechblasen mit Zeigern;
LaTeX verwendet dieselben Inhalte mit rechteckigen Sprechkästen. Die bestehenden
verwalteten Build-Wege laden beide Dateien automatisch. Excalidraw-Decks
unterstützen diesen Arbeitsblatt-Baustein bislang nicht.
