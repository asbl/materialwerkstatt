# Skizzen-Kürzel für Algorithmen

Die Marker funktionieren in QMD-Materialien über `filters/exam.lua` und in
Excalidraw-Präsentationen über `inv deck`. Gezeichnet wird durch
`filters/algorithm_sketches.lua`; externe Grafikdateien sind nicht nötig.
Bildtexte werden XML-escaped. Unbekannte Optionen und ungültige Werte brechen
den Build mit einer Fehlermeldung ab.

## Suchfelder und Suchzustände

```markdown
[Skizze suchfeld | werte=4,9,13,18,27,31,42,56,68,85 | verdeckt=ja | ziel=31]
[Skizze suchfeld | verdeckt=ja | offen=5 | links=6 | rechts=10 | mitte=8 | ziel=31]
[Skizze suchfeld | verdeckt=ja | offen=5,8 | links=6 | rechts=7 | treffer=6 | ziel=31]
[Skizze suchfeld | verdeckt=ja | offen=5,6,7,8 | links=7 | rechts=6 | ziel=35]
```

- `werte`: 1–12 kurze Zahlen, durch Kommas getrennt. Standard ist die erste
  Beispielreihe oben. Positionen sind unabhängig von Werten und beginnen bei 1.
- `verdeckt=ja`: Werte zunächst verbergen; Standard `nein`.
- `offen`: bereits aufgedeckte Positionen. `mitte` und `treffer` werden immer
  aufgedeckt. `mitte` markiert das aktuell geprüfte Element orange;
  `treffer` markiert es grün und zeigt den erfolgreichen Abbruch.
- `links`/`rechts`: inklusive Suchgrenzen, Standard 1/Anzahl Werte.
  Ausgeschlossene Positionen bleiben lesbar und werden durchgestrichen.
  Für `links > rechts` wird der erfolglose Abbruch angezeigt.
- `ziel`: Beschriftung des Suchwerts; verändert nicht automatisch den Zustand.

Der Marker beschreibt einen Zustand. Die Autorin oder der Autor legt die
Zugriffsfolge und Suchgrenzen fest; es wird keine Suche simuliert.

## Bäume und Halbieren

```markdown
[Skizze suchbaum | werte=4,9,13,18,27,31,42,56,68,85 | ebenen=2 | markiert=5,8]
[Skizze ebenenbaum | ebenen=4]
[Skizze halbierung | start=32 | schritte=5]
[Skizze suchablauf]
[Skizze suchablauf | teil=abbruch]
[Skizze suchablauf | teil=vergleich]
```

`suchbaum` erzeugt einen binären Suchentscheidungsbaum aus 1–15 streng
aufsteigenden Werten. Er verwendet rekursiv die untere Mitte. `markiert`
enthält Positionen der ursprünglichen Werteliste, nicht Zahlenwerte.
`ebenen=1..4` begrenzt die sichtbaren Ebenen; Standard 4.
`ebenenbaum` zeigt einen vollständigen Baum mit bis zu vier Ebenen ohne
Zahlenwerte. Die Wurzel liegt auf Ebene 1.

`halbierung` zeigt eine Eingabegröße von `start=2..64` und höchstens sechs
Halbierungsschritte. Standard: 32 und fünf Schritte; kein Ergebnis darf
kleiner als 1 werden. `suchablauf` stellt die beiden Abbruchfälle und die
Rückkehr zur Bereichsprüfung nach einer Halbierung dar. `teil=abbruch` und
`teil=vergleich` trennen diese Entscheidungen für größere Darstellungen auf
zwei Folien. Standard ist `teil=gesamt`.

## Wachstum und obere Schranken

```markdown
[Skizze wachstum | kurven=konstant,logarithmisch | xmax=32 | ymax=6]
[Skizze wachstum | kurven=linear,quadratisch | xmax=8 | ymax=64]
[Skizze wachstum | kurven=kosten,schranke | xmax=8 | ymax=32 | schwelle=2]
```

Ein bis drei Kurven werden gemeinsam auf **einer linearen Skala** gezeichnet.
Funktionswerte werden für n≥1 dargestellt und am Diagrammrand beschnitten.
`xmax=2..100`, `ymax=2..100000` bestimmen die ausdrücklich beschrifteten
Achsenbereiche. Pro Folie möglichst zwei Kurven vergleichen.

| Kürzel | Funktion |
|---|---|
| `konstant` | 1 |
| `logarithmisch` | log₂ n |
| `linear` | n |
| `nlogn` | n · log₂ n |
| `quadratisch` | n² |
| `kubisch` | n³ |
| `exponentiell` | 2ⁿ |
| `kosten` | 2n + 4 |
| `schranke` | 4n |

`schwelle` markiert den Beginn einer oberen Schranke für das konkrete
Beispiel `2n+4 ≤ 4n`. Dafür `kurven=kosten,schranke` und `schwelle=2` verwenden.

## Kosten und wiederholte Operationen

```markdown
[Skizze kostenbalken | werte=1,2,3,4]
[Skizze operationen | zeilen=1 | spalten=4]
[Skizze operationen | zeilen=4 | spalten=4]
[Skizze spaltenaddition | oben=723573 | unten=232683]
[Skizze suchvergleich | offen=ja]
[Skizze suchvergleich]
```

`kostenbalken` zeigt bis zu zehn nichtnegative Schrittzahlen nach Zielposition.
`operationen` stellt 1–5 Zeilen und 1–8 Spalten dar; ein Kästchen entspricht
einer Operation. Die Bedeutung der Schleifen ergänzt der Gesprächsimpuls.
`spaltenaddition` akzeptiert zwei gleich lange Ziffernfolgen mit höchstens
zehn Stellen und lässt das Ergebnis zur gemeinsamen Erarbeitung offen.
`suchvergleich` zeigt eine feste Worst-Case-Tabelle für 10, 1.000, 1.000.000
und 100.000.000 Elemente. `offen=ja` lässt die Ergebnisfelder leer.
