# Rechenfolge

Der Shortcut zeichnet eine Folge mit beliebig wählbaren mathematischen Werten
und beschrifteten Pfeilen. Er eignet sich für Potenzen, additive Folgen,
Bruchfolgen oder mehrschrittige Rechnungen. Die Inhalte bleiben als Text in der
QMD-Datei bearbeitbar. Die Darstellung übernimmt die Farben der Arbeitsblattvorlage.

Der Filter `src/quarto/filters/rechenfolge.lua` ist in `_quarto.yml` registriert.
Für Dokumente außerhalb des Projekts den Filter zusätzlich einbinden; die
Typst-Vorlage muss die Farbvariablen `primary` und `primary-light` bereitstellen.

Eine eigene Absatzzeile verwenden. Mathematik in `$…$` einschließen, damit
Markdown etwa Exponenten nicht als andere Textformatierung interpretiert.

```markdown
[Rechenfolge: werte=$1$|$3$|$5$|$7$; schritt=$+2$; breite=120mm]
```

Mit optionaler zweiter Zeile:

```markdown
[Rechenfolge: werte=$2^2$|$2^1$|$2^0$|$2^{-1}$; zusatz=$4$|$2$|$1$|$\frac12$; schritt=$:2$; breite=120mm]
```

Unterschiedliche Rechenschritte:

```markdown
[Rechenfolge: werte=$3$|$6$|$5$|$25$; schritte=$\cdot2$|$-1$|$\cdot5$; breite=130mm]
```

- `werte`: mindestens zwei Werte, durch `|` getrennt.
- `zusatz`: optionale zweite Zeile, gleich viele Einträge wie `werte`.
- `schritt`: ein wiederholtes Rechenzeichen für alle Pfeile.
- `schritte`: individuelle Beschriftungen, eine pro Verbindung; hat Vorrang vor `schritt`.
- `breite`: Gesamtbreite in Millimetern; Standard `150mm`. Passend zur Anzahl
  und Länge der Werte wählen. Lange Beschriftungen passen nicht in die festen
  9-mm-Zwischenräume; dafür kürzere mathematische Zeichen verwenden.

Die Typst-Darstellung verwendet 11 pt, Felder von 17 mm Höhe und separate
Zwischenräume für Operatoren und Pfeile. Sie ist unabhängig von einem SVG.
Andere Ausgabeformate erhalten eine vereinfachte Textfolge.

`$\square$` erzeugt ein hellgraues, randloses Antwortfeld (10 mm × 5 mm), auch als
Teil einer Formel. Beispiel: `werte=$2^{\square}$|$2^{\square}$` mit
`zusatz=$\frac18$|$1$`. Dafür wird kein SVG benötigt.
