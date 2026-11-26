# Alice Check-up Template

Das Template `src/quarto/templates/checkup-alice.typst` verbindet Regelkarten
links mit den zugehörigen Aufgaben rechts. V5 wurde am Potenz-Check-up für
Klasse 10 mit zwei AB-Seiten und vier Lösungsseiten geprüft. Ältere
Freigaben bleiben erhalten.

## Gestaltung der neuen Fassung

- Drei Themenbereiche je AB-Seite statt einer einzigen langen Regelspalte.
- Gleiche Symbole an Regelkarte und Aufgabenbereich: Fläschchen, Spielkarte,
  Schlüssel oder Uhr. Die Zuordnung funktioniert auch ohne Farbdruck.
- Sachliche Aufgabentitel, literarische Serifenschrift nur im Titel und in den
  Themenüberschriften; Erklärungen und Aufgaben bleiben in Noto Sans.
- Grundschrift 12 pt und Zeilenabstand mindestens 0,65 em. Die Grundschrift
  wird aus dem Dokument übernommen. Die Zweitseitenfassung wurde mit 12 pt
  geprüft; eine größere Schrift kann zusätzliche Seiten benötigen.
- Druckränder links/rechts 9 mm, oben 8 mm, unten 10 mm.
- Randlose Aufgabenraster; reine Formelzellen werden als abgesetzte Formeln
  gesetzt, damit hohe Brüche nicht in benachbarte Zeilen hineinragen.
- Die Quadratskizze verwendet weiterhin den vorhandenen Skizzen-Shortcut.
  Ihr leerer Außenbereich wird für die Darstellung beschnitten. Die beiden
  Seitenlabels und das Innenlabel bleiben vollständig und lesbar erhalten.
  Der Ausschnitt ist auf den eingefrorenen Quadrat-Shortcut abgestimmt.

## QMD-Struktur

Dokumente benötigen das Template sowie `src/quarto/filters/checkup.lua` als
Dokumentfilter. Pfade zum Filter sind relativ zur Quelle anzugeben. Beim
Anlegen neuer Materialien eine konkrete Template-Freigabe und den zugehörigen
Kontext binden.

```markdown
::::::: {.checkpage}
:::::: {.check-section motif="bottle" topic="Wachsen und Schrumpfen"}
::::: {.regeln}
### Wiederholte Änderung

Startwert mal Änderungsfaktor hoch Anzahl der Schritte.
:::::
::::: {.aufgaben}
## 1 Größen vergleichen

Hier stehen die Aufgaben und gegebenenfalls randlose Markdown-Tabellen.
:::::
::::::
:::::::
```

Eine neue Seite beginnt mit einem `.pagebreak`-Block. `.check-section`
erwartet genau zwei Inhaltsbereiche in der Reihenfolge Regeln, Aufgaben.
Die Abschnitte werden beim Druck zusammengehalten. Bei umfangreichen
Abschnitten deshalb Inhalte aufteilen, statt Schrift und Abstand zu reduzieren.

Für das Quadratmodell kann ein `.check-figure`-Block verwendet werden: zuerst
`.check-sketch` mit `[Skizze flaeche | a=s | innen=9 dm²]`, danach
`.figure-questions` mit den zugehörigen Fragen. Diese Darstellung wird als
56 mm breite Skizze neben dem Fragetext gesetzt.

Lösungsblätter verwenden `checkup-solutions: true`. Ihre Inhalte bleiben normale
Markdown-Absätze mit bewusst gesetzten Seitenumbrüchen. Rechenfolgen bleiben
über den vorhandenen `[Rechenfolge: ...]`-Shortcut editierbar.

## Vorschläge für weitere Template-Verbesserungen

Die folgenden Punkte sind Vorschläge und nicht Teil der aktuellen Freigabe.

| Priorität | Vorschlag | Nutzen und notwendige Prüfung |
|---|---|---|
| Hoch | Expliziter Schwarzweißmodus | Lavendelflächen durch feine Konturen und weiße Karten ersetzen. Kontrast und Graustufen am gedruckten Exemplar prüfen. Die Piktogramme müssen ohne Farbe unterscheidbar bleiben. |
| Hoch | Formel- und Grafikbeschriftungen an die Grundschrift koppeln | Die aktuelle Fassung ist auf 12 pt abgestimmt. Für Varianten mit größerer Grundschrift müssen Formeln, Piktogramme und Skizzenlabels gemeinsam mitwachsen; alle Varianten separat rendern und prüfen. |
| Hoch | Seitenprüfung mit verständlicher Warnung | Zu hohe Themenbereiche und zusätzliche Folgeseiten melden. Keine automatische Schriftverkleinerung; stattdessen den betroffenen Bereich nennen. |
| Mittel | Konfigurierbare Regelbreite | Zwei geprüfte Varianten anbieten, etwa 50 und 58 mm. Breite nach Formellänge und Sprachumfang wählen. Lange Formeln und zweispaltige Aufgaben jeweils prüfen. |
| Mittel | Verschiedene Rasterbreiten für Aufgaben | Spalten nicht immer gleich breit machen. Eine lange Begründung kann zwei kurze Formelspalten ersetzen. Mehr Freiheit erst nach Renderprüfung freigeben. |
| Mittel | Eigene Kopfzeile für Lösungsfolgeseiten | Kleiner Titel mit Aufgabenspanne unterstützt das Sortieren der vier Lösungsseiten. Dafür oben ausreichend Raum reservieren. |
| Niedrig | Eine zusätzliche kleine Buchillustration | Ein einzelnes, eigenes Feder- oder Türmotiv könnte den literarischen Charakter stärken. Nur verwenden, wenn es weder Erklärungen noch Modelle verdrängt. |

Die wichtigsten nächsten Schritte wären Schwarzweißdruck und automatische
Überlaufhinweise. Weitere Figuren, Hintergründe oder Spielmechaniken hätten
derzeit einen geringeren Nutzen für das Lesen und Lernen.

## Erweiterung v4

V4 ergänzt einen zweispaltigen Graphenvergleich über `.check-plots` mit zwei
`.plot`-Bereichen. Verwendet werden weiterhin Koordinatensystem-Shortcuts,
etwa `funktion=parabel` und neu `funktion=kubik`. `schrift=28` vergrößert die
Beschriftung in SVG-Einheiten, sodass sie bei 64 mm Bildbreite ungefähr
11 pt entspricht. Die Textgrundschrift bleibt 12 pt.

Der kompakte Ausschnitt ist für die geprüften Bereiche `x=-3..3` und
`y=-1,5..1,5` ausgelegt. Die Achsenskalierung bleibt gleich; der Ausschnitt
entfernt nur weißen Außenraum. Für andere Bereiche ist eine eigene
Renderprüfung erforderlich. Zwei frei gewählte Bereiche sind damit nicht
automatisch als passend geprüft.

Das Beispiel enthält nun aktive Ergänzungsfelder in der Potenzfolge,
beide Wurzelgesetze und die im Abdeckungsaudit priorisierten Aufgaben.
Die Freigaben v1 bis v3 bleiben erhalten. Das vierseitige Lösungsblatt
behandelt alle neuen Teilaufgaben mit passenden Rechenwegen und einer
Tabelle zu den sechs grafischen Lösungsfällen.

## Kompakte Modelle v5

V5 ergänzt drei Darstellungen und eine Umformungshilfe, ohne Aufgaben zu
streichen. Das Beispiel bleibt bei zwei AB-Seiten und vier Lösungsseiten,
mit unverändert 12 pt Grundschrift und mindestens 0,65 em Zeilenabstand.

- Das Faktorenmodell verwendet drei unterklammerte Zweiergruppen statt einer
  ausgeschriebenen Erklärung.
- `[vier Stellen]{.code-slots}` erzeugt vier hellgraue, randlose Felder in der
  Textzeile. Die Anzahl der Möglichkeiten steht daneben; das Ergebnis wird
  nicht vorgegeben.
- `.check-cubes` mit `size="20"` enthält genau zwei unbeschriftete
  `[Skizze volumen | a= | innen=]`-Shortcuts in getrennten Absätzen.
  Der Bildausschnitt entfernt nur ungenutzten Außenraum. Die Bildbreiten
  betragen 20 und 10 mm, entsprechend dem Verhältnis der Kantenlängen.
  Die Beschriftungen $a$ und $a/2$ werden separat in der Grundschrift gesetzt
  und deshalb nicht mit dem kleinen Würfel verkleinert. `size` ist zwischen
  15 und 25 mm zulässig; andere Größen benötigen eine erneute Layoutprüfung.
- Die Regelkarte zu Zehnerpotenzen zeigt das Angleichen eines Exponenten
  anstelle der bisherigen beiden Zahlenbeispiele. Die allgemeine Definition
  der wissenschaftlichen Schreibweise bleibt erhalten.

Die Würfelskizze nennt keine Flächen- oder Volumenfaktoren: Diese bleiben
Gegenstand von Aufgabe 6c. Alle Freigaben v1 bis v4 bleiben unverändert.


## Literarische Schriftfassung v7

V7 verwendet Alice Regular für Titel (22 pt) und Themenüberschriften (16 pt),
mit Noto Sans als expliziter Ersatzschrift. Die paketierte, umbenannte Fassung
heißt `Material Alice`; ihre Glyphen sind unverändert. Alice besitzt nur den
regulären Schnitt. Daher wird keine künstliche Fettung oder Schrägstellung
verwendet. Aufgabenüberschriften, Regelkarten, 12-pt-Fließtext und Formeln
behalten die bisherigen Schriften und Größen.

Die Fontsoftware wird unter SIL OFL 1.1 einschließlich Copyright und Lizenztext
in `src/quarto/fonts/alice/` und `src/quarto/fonts/static/alice/` mitgeliefert.
Herkunft, Quell-Commit, Umbenennung und SHA-256 sind in den Fontmanifesten
festgehalten. Eine Systeminstallation oder ein Online-Abruf beim Bauen ist
nicht erforderlich. Die OFL überträgt sich nicht auf die erzeugten PDFs.

Hintergrund und Vergleich: [Schriftrecherche](audits/alice-template-schriften-2026-11-16.md).
Ältere Freigaben bleiben unverändert. Die Übernahme für Check-up und Lösungen
wurde mit dem Umsetzungsauftrag im Chat bestätigt.
