import { SHORTCUT_EXAMPLES } from "./shortcut-examples.js";
import { shortcutFields, showShortcutOptions } from "./shortcut-options.js";

export const SHORTCUT_TAGS = [
  ["alle", "Alle"],
  ["klausur", "Klausur/Nachprüfung"],
  ["arbeitsblatt", "Arbeitsblatt"],
  ["foerderplan", "Förderplan"],
  ["folie", "Folie/Praesentation"],
  ["kurs", "Kurs (H5P)"]
];

export const SHORTCUTS = [
  {
    id: "modell-bruchrechteck",
    label: "Modell: Anteile im Rechteck",
    tags: ["arbeitsblatt", "folie"],
    hint: "Gleich große Bezugsrechtecke; ? für leere Felder. Raster: nein, ja oder gestrichelt. Beschriftungen bleiben bei ihrer Skizze.",
    code: "[Modell bruchrechteck | werte={{1/8,1/4,1/2,1,2,4,8}} | raster={{gestrichelt}} | beschriftung={{ja}} | bildbreite={{160mm}}]"
  },
  {
    id: "schuelerdialog-farben",
    label: "Schülerdialog: eigene Figurenfarben",
    tags: ["arbeitsblatt"],
    hint: "Generischer Dialog mit frei wählbaren Namen, Haut-, Haar- und Akzentfarben. Fachliche Modelle können als eigener Absatz unter dem Sprechtext stehen.",
    code: ":::: {.schuelerdialog}\n::: {.dialogbeitrag name=\"{{Mia}}\" figur=\"zopf\" haarfarbe=\"{{#d9b34a}}\" hautfarbe=\"{{#ffe1bd}}\" farbe=\"{{#498532}}\"}\n{{Ich erkläre meinen Weg.}}\n:::\n::: {.dialogbeitrag name=\"{{Kim}}\" figur=\"zopf\" haarfarbe=\"{{#a45832}}\" hautfarbe=\"{{#bd825b}}\" farbe=\"{{#426a9c}}\"}\n{{Ich vergleiche unsere Wege.}}\n:::\n::::"
  },
  {
    id: "modell-schriftlich",
    label: "Modell: schriftliche Multiplikation",
    tags: ["arbeitsblatt"],
    hint: "Stellengerechte Musterrechnung. Nullzeilen ein- oder ausblenden; auch unter einer Dialogblase verwendbar.",
    code: "[Modell schriftlich | aufgabe={{356*17}} | nullzeile={{nein}} | bildbreite={{65mm}}]"
  },
  {
    "id": "schuelerdialog-zwei",
    "label": "Schülerdialog: zwei Personen",
    "tags": [
      "arbeitsblatt"
    ],
    "hint": "Zwei kompakte Sprechblasen mit Figuren. Erster Absatz = Aussage; weitere Absätze können Modelle, Bilder oder Formeln enthalten.",
    "code": ":::: {.schuelerdialog}\n::: {.dialogbeitrag name=\"{{Leo}}\" figur=\"{{brille}}\"}\n{{Ich rechne zuerst die erste Teilaufgabe.}}\n:::\n::: {.dialogbeitrag name=\"{{Till}}\" figur=\"{{kurz}}\"}\n{{Ich knüpfe daran an und erkläre meinen nächsten Schritt.}}\n:::\n::::"
  },
  {
    "id": "schuelerdialog-drei",
    "label": "Schülerdialog: drei Personen",
    "tags": [
      "arbeitsblatt"
    ],
    "hint": "Drei Beiträge nebeneinander, etwa zum Vergleichen von Vermutungen oder Rechenwegen. Alle Aussagen und Figuren sind austauschbar.",
    "code": ":::: {.schuelerdialog}\n::: {.dialogbeitrag name=\"{{Esra}}\" figur=\"{{zopf}}\"}\n{{Ich beschreibe meinen Lösungsweg.}}\n:::\n::: {.dialogbeitrag name=\"{{Leo}}\" figur=\"{{brille}}\"}\n{{Ich sehe einen anderen Weg.}}\n:::\n::: {.dialogbeitrag name=\"{{Noah}}\" figur=\"{{locken}}\"}\n{{Ich prüfe, was bei beiden Wegen gleich bleibt.}}\n:::\n::::"
  },
  {
    "id": "schuelerdialog-modelle",
    "label": "Schülerdialog: mit Modellen",
    "tags": [
      "arbeitsblatt"
    ],
    "hint": "Sprechtext und fachlicher Inhalt bleiben getrennt: Modelle, Bilder, Rechnungen oder Listen unterhalb der Sprechblasen. Für beliebige Themen nutzbar.",
    "code": ":::: {.schuelerdialog}\n::: {.dialogbeitrag name=\"{{Mia}}\" figur=\"{{zopf}}\"}\n{{Ich zerlege die Faktoren im Malkreuz.}}\n\n{{[Modell malkreuz | oben=20,6 | links=10,4 | bildbreite=55mm]}}\n:::\n::: {.dialogbeitrag name=\"{{Kim}}\" figur=\"{{kurz}}\"}\n{{Ich beschreibe einen anderen Rechenweg.}}\n\n{{$26 \\cdot 14 = 26 \\cdot 10 + 26 \\cdot 4$}}\n:::\n::::"
  },
  {
    id: "reflexionsfrage-kommentar",
    label: "Reflexionsfrage (nur im Quelltext)",
    tags: ["folie"],
    hint: "Notiz für die Lehrkraft. Bleibt im Markdown und erscheint weder im PDF noch im Deck.",
    code: "<!-- Reflexionsfrage:\n{{Wie begründet ihr euren Rechenweg?}}\n-->"
  },
  {
    id: "aufgabe-ueberschrift",
    label: "Aufgabe (Überschrift)",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Startet eine neue bewertete Aufgabe mit Punktzahl.",
    code: "## Aufgabe {{1}}: {{Kurztitel}} [{{10}} P]"
  },
  {
    id: "teilaufgabe",
    label: "Teilaufgabe",
    tags: ["klausur"],
    hint: "Teilaufgabe a), b), c) … mit eigener Punktzahl.",
    code: "### {{a}}) [{{4}} P]"
  },
  {
    id: "fortsetzung",
    label: "Fortsetzung einer Aufgabe",
    tags: ["klausur"],
    hint: "Markiert die Fortsetzung einer Aufgabe nach einem Seitenumbruch.",
    code: "[Fortsetzung {{1}}: {{Kurztitel}}]"
  },
  {
    id: "antwortlinie",
    label: "Antwortlinie",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Kurze Linie zum handschriftlichen Eintragen im Fließtext.",
    code: "Ergebnis: [Antwortlinie]"
  },
  {
    id: "antwortlinie-breite",
    label: "Antwortlinie mit Breite",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Linie mit eigener Breite in cm, mm oder pt, auch mitten im Text.",
    code: "[antwortlinie {{1cm}}]"
  },
  {
    id: "antwortlinie-fuellend",
    label: "Antwortlinie füllend",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Linie über die volle verfügbare Breite, z. B. in einer Tabellenzelle.",
    code: "[Antwortlinie füllend]"
  },
  {
    id: "eingabetabelle",
    label: "Eingabetabelle",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Tabelle mit Schreibraum in den Zellen. Optionale Zeilenhöhe in cm, mm oder pt; der Zellinhalt sitzt unten, sodass über den Antwortlinien Platz bleibt.",
    code: "[Eingabetabelle {{1cm}}]\n\n| Aufgabe | Lösung |\n|---|---|\n| a) | [Antwortlinie füllend] |\n\n[/Eingabetabelle]"
  },
  {
    id: "schreiblinien",
    label: "Schreiblinien",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Feine Linien über die volle Textbreite mit 8 mm Schreibabstand. Anzahl: 1–30. Als eigenen Absatz einfügen.",
    code: "[Schreiblinien {{2}}]"
  },
  {
    id: "antwortkasten",
    label: "Antwortkasten",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Grauer Kasten in Zeilenbreite zum Eintragen der Lösung.",
    code: "[Antwortkasten: {{3cm}}]"
  },
  {
    id: "platz",
    label: "Platz (kleines Antwortfeld)",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Kleines, hellgraues, randloses Antwortfeld mitten im Fließtext, z. B. hinter einem Gleichheitszeichen.",
    code: "$356+125=$[Platz {{1cm}}]"
  },
  {
    id: "kaestchen",
    label: "Kästchen zum Ankreuzen",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Ankreuzkästchen (Unicode □), z. B. in Tabellen oder Auswahllisten.",
    code: "□ {{Option A}}"
  },
  {
    id: "rechengitter",
    label: "Rechengitter",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Kariertes Rechenfeld: Kästchengröße (cm) | Zeilen | Spalten (optional, nur LaTeX).",
    code: "[Rechengitter {{0.5}} | {{10}} | {{36}}]"
  },
  {
    id: "einheitskreis",
    label: "Einheitskreis mit Winkel",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Zeichnet Achsen, Kreis, Winkel in Grad und Punkt P. 0–90° als Viertelkreis, sonst als Vollkreis; auch negative Winkel und Dezimalzahlen möglich.",
    code: "[Einheitskreis {{75}}]"
  },
  {
    id: "modell-rechenstrich",
    label: "Modell: Rechenstrich",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Schematische Pfeilsprünge zwischen 2–6 Zahlen mit markiertem Anfang. Kommagetrennte Beschriftungen; _ oder ? erzeugt ein leeres Kästchen. Mit offen=ja fehlen die Sprünge – nur Strich und bis zu 13 Knoten. Nicht maßstäblich.",
    code: "[Modell rechenstrich | knoten={{3987,4000,4002}} | spruenge={{+_,+_}}]"
  },
  {
    id: "modell-ziffernraetsel",
    label: "Ziffernrätsel: Karten und Rechenraster",
    tags: ["arbeitsblatt", "klausur"],
    hint: "Ziffernkarten mit Lücken, darunter dieselbe Malaufgabe im Kästchenraster mit vorgegebenem Ergebnis. _ oder ? steht für eine fehlende Ziffer; fehlende Ziffern werden nicht gelöst.",
    code: "[Modell ziffernraetsel | aufgabe={{3_1_*2}} | ergebnis={{6830}} | bildbreite={{60mm}}]"
  },
  {
    id: "modell-vierhundertfeld",
    label: "Modell: 400er-Feld",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Vier 100er-Felder mit Abstand und abgestuften Grautönen zum Markieren und Zerlegen von Malaufgaben.",
    code: "[Modell vierhundertfeld]"
  },
  {
    id: "modell-punktefeld",
    label: "Modell: Punktefeld",
    tags: ["klausur", "arbeitsblatt"],
    hint: "1–12 Reihen mit je 1–20 Punkten zum Beschriften, Zerlegen und Erklären von Malaufgaben.",
    code: "[Modell punktefeld | zeilen={{4}} | spalten={{6}}]"
  },
  {
    id: "modell-flaeche",
    label: "Modell: Teilprodukte als Fläche",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Rechteck mit je zwei Seitenabschnitten; vier leere Teilflächen passend zum Malkreuz. Seitenabschnitte proportional, ohne Ergebnisse.",
    code: "[Modell flaeche | oben={{20,6}} | links={{10,4}}]"
  },
  {
    id: "modell-hoehenprofil-abstieg",
    label: "Modell: Höhenprofil (Abstieg)",
    tags: ["arbeitsblatt"],
    hint: "Schematisches Höhenprofil mit Starthöhe und 1–5 Etappen mit Vorzeichen. offen=ja lässt alle Höhen außer der Starthöhe offen, summe=-1050 spannt den Bogen über alle Etappen.",
    code: "[Modell hoehenprofil | start={{1250}} | etappen={{-380,-220,-450}} | offen={{ja}}]"
  },
  {
    id: "modell-hoehenprofil-aufstieg",
    label: "Modell: Höhenprofil (Aufstieg)",
    tags: ["arbeitsblatt"],
    hint: "Aufstieg analog zum Abstieg: positive Etappen zeichnen das Profil aufwärts. Einheit m macht Höhenmeter sichtbar; offen=ja lässt Zwischen- und Zielhöhen offen – z. B. für Kopfübungen zum Ergänzen.",
    code: "[Modell hoehenprofil | start={{2480}} | etappen={{+20 m,+500 m}} | offen={{ja}}]"
  },
  {
    id: "einheitskreis-aufgaben",
    label: "Einheitskreis: drei Teilaufgaben",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Drei beschriftete Einheitskreise nebeneinander mit frei wählbaren Winkeln.",
    code: "Berechne die Koordinaten des Punktes P.\n\n::: {.abbildungen .list-abc}\n[Einheitskreis {{75}}]\n\n[Einheitskreis {{45}}]\n\n[Einheitskreis {{30}}]\n:::"
  },
  {
    id: "skizze-dreieck",
    label: "Skizze: Dreieck",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Schematisches Dreieck: allgemein, gleichschenklig, recht-A/B/C oder stumpf-A/C. Seiten und Winkel frei beschriften; hoehe=ja ergänzt die Höhe auf AB.",
    code: "::: {.abbildungen cols=2}\n[Skizze dreieck | form={{recht-C}} | a={{7 cm}} | beta={{14°}}]\n:::"
  },
  {
    id: "skizze-dreieck-gedreht",
    label: "Skizze: Dreieck drehen und markieren",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Drehung gegen den Uhrzeigersinn; markiert hebt Seiten a/b/c und Winkel alpha/beta/gamma hervor. Eckpunktnamen lassen sich mit A=, B= und C= ändern.",
    code: "::: {.abbildungen cols=2}\n[Skizze dreieck | form={{allgemein}} | drehung={{150}} | beta={{β}} | markiert={{a,c,beta}}]\n:::"
  },
  {
    id: "skizze-steigung",
    label: "Skizze: Steigungsdreieck",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Waagerechte Strecke x, Höhe h, schräge Strecke s und Steigungswinkel alpha; frei beschriftbar, ohne berechnete Ergebnisse.",
    code: "::: {.abbildungen cols=2}\n[Skizze steigung | x={{7,5 m}} | h={{3,2 m}} | s={{s}} | alpha={{α}}]\n:::"
  },
  {
    id: "skizze-pyramide",
    label: "Skizze: Quadratische Pyramide",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Pyramide mit Spitze S, Mittelpunkt M, Ecke A und gestricheltem Hilfsdreieck; Grundkante a, Höhe h, Seitenkante s.",
    code: "::: {.abbildungen cols=2}\n[Skizze pyramide | a={{10 cm}} | h={{12 cm}} | s={{s}}]\n:::"
  },
  {
    id: "skizze-quader",
    label: "Skizze: Quader mit Raumdiagonale",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Quader mit Raumdiagonale und gestrichelter Projektion auf den Boden; Länge, Breite und Höhe frei beschriften.",
    code: "::: {.abbildungen cols=2}\n[Skizze quader | laenge={{9 m}} | breite={{12 m}} | h={{8 m}}]\n:::"
  },
  {
    id: "skizze-zahlenschloss",
    label: "Skizze: Zahlenschloss",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Schloss mit 1–6 Rädern und 2–9 Einstellungen pro Rad; alle Ziffern stehen am Rad, die mittlere liegt im Anzeigefenster.",
    code: "[Skizze zahlenschloss | raeder={{3}} | ziffern={{3}}]"
  },
  {
    id: "skizze-flaeche",
    label: "Skizze: Quadrat als Fläche",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Quadrat mit beschrifteter Seite a und freiem Innenlabel, z. B. für a · a; Innenlabel leer lassen zum Auslassen.",
    code: "[Skizze flaeche | a={{a}} | innen={{a · a}}]"
  },
  {
    id: "skizze-volumen",
    label: "Skizze: Würfel als Volumen",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Würfel mit Kante a, verdeckte Kanten gestrichelt; Innenlabel frei, z. B. für a · a · a.",
    code: "[Skizze volumen | a={{a}} | innen={{a · a · a}}]"
  },
  {
    id: "skizze-tippzettel",
    label: "Skizze: Tippzettel",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Tippschein mit 1–14 Spielen und 2–4 Tippzeichen pro Zeile; Standard ist ein Fußball-Tippzettel mit 13 Spielen und 1/0/2.",
    code: "[Skizze tippzettel | spiele={{13}} | zeichen={{1,0,2}}]"
  },
  {
    id: "wahr-falsch",
    label: "Wahr-Falsch-Tabelle",
    tags: ["klausur"],
    hint: "Tabellenlayout mit mehr Zeilenabstand für Wahr/Falsch-Aufgaben.",
    code: "[Wahr-Falsch-Layout]\n\n"
      + "| **Nr.** | **Aussage** | **W** | **F** |\n"
      + "| :---: | :--- | :---: | :---: |\n"
      + "| 1 | {{Aussage einfügen}} | □ | □ |\n\n"
      + "[/Wahr-Falsch-Layout]"
  },
  {
    id: "loesung",
    label: "Lösungsabschnitt",
    tags: ["klausur"],
    hint: "Kennzeichnet einen Lösungsabschnitt in Musterlösungen.",
    code: "[Lösung: {{1}}]\n\n{{Lösungstext}}\n\n[/Lösung]"
  },
  {
    id: "erwartungshorizont",
    label: "Erwartungshorizont",
    tags: ["klausur"],
    hint: "Eigene Querformat-Seite für den Erwartungshorizont.",
    code: "[Erwartungshorizont: {{Aufgabe 1}}]\n\n{{Erwartete Lösung}}\n\n[/Erwartungshorizont]"
  },
  {
    id: "hinweise",
    label: "Hinweise-Block",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Kleingedruckter Hinweiskasten, z. B. für Prüfungsregeln.",
    code: "[Hinweise]\n\n- {{Hinweis einfügen}}\n\n[/Hinweise]"
  },
  {
    id: "infobox",
    label: "Infobox",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Hervorgehobener Kasten mit farbigem Titel für Erklärungen und Merkhinweise.",
    code: "[Infobox: {{Titel}}]\n\n{{Text der Infobox}}\n\n[/Infobox]"
  },
  {
    id: "warnbox",
    label: "Warnbox",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Hervorgehobener Kasten für Warnungen und wichtige Hinweise.",
    code: "[Warnbox: {{Titel}}]\n\n{{Text der Warnung}}\n\n[/Warnbox]"
  },
  {
    id: "tippbox",
    label: "Tippbox",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Hervorgehobener Kasten für Tipps und Hilfestellungen.",
    code: "[Tippbox: {{Titel}}]\n\n{{Text des Tipps}}\n\n[/Tippbox]"
  },
  {
    id: "deckblatt",
    label: "Deckblatt",
    tags: ["klausur"],
    hint: "Titelzeile am Seitenanfang: Titel | Untertitel | Zusatztext.",
    code: "[Deckblatt: {{Titel}} | {{Untertitel}} | {{Zusatztext}}]"
  },
  {
    id: "mathe-deckblatt",
    label: "Mathe-Deckblatt",
    tags: ["klausur"],
    hint: "Deckblatt mit Name-/Datumsfeld für Mathe-Arbeiten.",
    code: "[Mathe-Deckblatt: {{Titel}} | {{Datum}}]\n\n[/Mathe-Deckblatt]"
  },
  {
    id: "schuelerfelder",
    label: "Schülerfelder",
    tags: ["klausur"],
    hint: "Zeile für Name und Datum zum Ausfüllen. Optional mit Abstand nach oben: [Schuelerfelder 1cm].",
    code: "[Schuelerfelder]"
  },
  {
    id: "bewertungsfelder",
    label: "Bewertungsfelder",
    tags: ["klausur"],
    hint: "Punkte-/Notenpunkte-Zeile mit Gesamtpunktzahl.",
    code: "[Bewertungsfelder: {{50}}]"
  },
  {
    id: "punkte",
    label: "Punkte an Lösungen",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Setzt die Punktzahl blau und fett direkt an eine Lösung. Auch halbe Punkte sind möglich, z. B. [Punkte 0,5].",
    code: "[Punkte {{1}}]"
  },
  {
    id: "notenspiegel",
    label: "Notenspiegel",
    tags: ["klausur"],
    hint: "Leere Strichliste der Notenpunkte 0–15 zum Ausfüllen.",
    code: "[Notenspiegel]"
  },
  {
    id: "notentabelle",
    label: "Notentabelle",
    tags: ["klausur"],
    hint: "Tabelle Note 1–6 mit Anzahl und nötigen Punkten.",
    code: "[Notentabelle]"
  },
  {
    id: "abstand",
    label: "Vertikaler Abstand",
    tags: ["klausur", "arbeitsblatt", "foerderplan", "folie"],
    hint: "Fügt freien vertikalen Platz ein, auch auf Folien. Höhe in cm, mm oder pt. Als eigenen Absatz einfügen.",
    code: "[abstand {{1cm}}]"
  },
  {
    id: "zwei-spalten",
    label: "Zwei Spalten",
    tags: ["folie", "arbeitsblatt"],
    hint: "Stellt Inhalte nebeneinander, z. B. Skizze links und Gesprächsimpulse rechts. Breite optional in Prozent; Spalten ohne Angabe teilen sich den Rest.",
    code: "::: {.columns}\n::: {.column width=\"{{52}}%\"}\n{{Linke Spalte}}\n:::\n::: {.column}\n{{Rechte Spalte}}\n:::\n:::"
  },
  {
    id: "aufgabenzeilen",
    label: "Tabelle mit Aufgabenzeilen",
    tags: ["arbeitsblatt"],
    hint: "Hebt in einer Markdown-Tabelle jede Zeile hervor, deren erste Zelle mit einem fetten Aufgabenkennzeichen beginnt (z. B. ☐ **1a)**): hellgelb hinterlegt, mit Trennlinie darüber. Kopfzeile hellgrau. Nur für Typst; nicht fette Zeilen gehören zur Aufgabe darüber.",
    code: "::: {.aufgabenzeilen}\n| {{Spalte 1}} | {{Spalte 2}} |\n|:--|:--|\n| ☐ **{{1a)}}** {{Lösung}} | – |\n| ☐ {{Fehlerbild}} | {{Übung}} |\n:::"
  },
  {
    id: "seitenumbruch",
    label: "Seitenumbruch",
    tags: ["klausur"],
    hint: "Seitenumbruch mit Name-Kopfzeile auf der Rückseite.",
    code: "[Seitenumbruch]"
  },
  {
    id: "mini-ab",
    label: "Mini-AB (2x auf A4)",
    tags: ["arbeitsblatt"],
    hint: "Zwei Exemplare pro Seite. Standard: Übungen vorn, Knobelaufgabe hinten mit kopfstehender Lösung im Textkasten. Für Blätter zum Durchschneiden (ab_mini_...).",
    code: "[Mini-AB]\n\n# {{Titel}}\n\n{{Kurze Übungen}}\n\n[/Mini-AB]\n\n[Seitenumbruch]\n\n[Mini-AB]\n\n# {{Knobelaufgabe}}\n\n{{Aufgabenstellung}}\n\n::: {.hinweis-gedreht}\n\n[Infobox: Lösung]\n\n{{Lösung der Knobelaufgabe}}\n\n[/Infobox]\n\n:::\n\n[/Mini-AB]"
  },
  {
    id: "mini-karte",
    label: "Mini-AB: Diagnosekarte",
    tags: ["arbeitsblatt"],
    hint: "Aufgabenfeld mit Nummer, Titel und S/?/H. Benötigt mini-diagnose: true und worksheet-mini.typst; mehrere Karten mit dem Spalten-Shortcut anordnen.",
    code: '::: {.mini-karte nummer="{{1}}" titel="{{Einmaleins}}" hoehe="{{34mm}}"}\n{{Aufgaben als Markdown und Shortcuts}}\n:::'
  },
  {
    id: "mini-auswertung",
    label: "Mini-AB: Lösung und Heftaufgaben",
    tags: ["arbeitsblatt"],
    hint: "Kombinierte Auswertung aus einer Markdown-Tabelle mit drei Spalten. Benötigt mini-diagnose: true; Zeilenumbruch innerhalb einer Zelle mit <br>.",
    code: '::: {.mini-auswertung}\n| Nr. | Lösung | Heftaufgaben |\n|---|---|---|\n| {{1}} | {{Vergleichslösung}} | {{☐ S. 45, Nr. 5}} |\n:::'
  },
  {
    id: "karten",
    label: "Kartensatz (Paare gesucht)",
    tags: ["arbeitsblatt"],
    hint: "Kartenraster mit Buchstaben-Badge für Zuordnungs- und Paar-Aufgaben: Überschrift und Aufgabenstellung, dann eine Karte pro Listenpunkt („Buchstabe: Inhalt“). Spalten optional: [Karten: Titel | spalten=4].",
    code: "[Karten: {{Paare gesucht}}]\n\n{{Elf Karten – fünf Paare, eine Karte bleibt übrig. Finde die Paare.}}\n\n- A: ${{a^2 \\cdot a^3}}$\n- B: ${{(a \\cdot b)^3}}$\n- C: ${{a^5}}$\n\n[/Karten]"
  },
  {
    id: "beweistabelle",
    label: "Beweistabelle",
    tags: ["klausur"],
    hint: "Zweispaltige Tabelle mit mehr Zeilenhöhe für Beweise.",
    code: "[Beweistabelle]\n\n| {{Behauptung}} | {{Begründung}} |\n|---|---|\n\n[/Beweistabelle]"
  },
  {
    id: "eingabetabelle-einfach",
    label: "Eingabetabelle",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Tabelle mit mehr Zeilenhöhe zum handschriftlichen Eintragen.",
    code: "[Eingabetabelle]\n\n| {{Spalte 1}} | {{Spalte 2}} |\n|---|---|\n\n[/Eingabetabelle]"
  },
  {
    id: "code-hinweis",
    label: "Code-Hinweis",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Kleiner, kursiver Hinweistext, z. B. unter Code-Beispielen.",
    code: "[Code-Hinweis]\n\n{{Hinweistext zum Code}}\n\n[/Code-Hinweis]"
  },
  {
    id: "referenz",
    label: "Referenz",
    tags: ["klausur", "arbeitsblatt"],
    hint: "Kleingedruckter Quellenverweis.",
    code: "[Referenz]\n\n{{Quellenangabe}}\n\n[/Referenz]"
  },
  {
    id: "versionen",
    label: "Versionen (A/B nebeneinander)",
    tags: ["klausur"],
    hint: "Zwei Spalten für Parallelversionen derselben Aufgabe.",
    code: "[Versionen]\n\n[Version]\n{{Version A}}\n\n[Version]\n{{Version B}}\n\n[/Versionen]"
  },
  {
    id: "foerderplan-kopf",
    label: "Förderplan-Kopf",
    tags: ["foerderplan"],
    hint: "Kopfbereich des Förderplans mit Schullogo und Stammdaten.",
    code: "[Förderplan-Kopf: {{Name}} | {{Klasse}} | {{Schuljahr}} | {{Lehrkraft}} | {{Fach}} | {{Datum}}]"
  },
  {
    id: "foerderbereich",
    label: "Förderbereich",
    tags: ["foerderplan"],
    hint: "Abschnitt mit Tabelle für einen Förderbereich.",
    code: "[Förderbereich: {{Bereichstitel}}]\n\n"
      + "| Ist-Stand | eigene Maßnahmen | weitere Maßnahmen |\n"
      + "|---|---|---|\n"
      + "| {{Beobachtung}} | {{Maßnahme}} | |\n\n"
      + "[/Förderbereich]"
  },
  {
    id: "unterschriften",
    label: "Unterschriften",
    tags: ["foerderplan"],
    hint: "Unterschriftenzeilen am Ende des Förderplans.",
    code: "[Unterschriften]"
  },
  {
    id: "kurs-warnbox",
    label: "Warn-Box",
    tags: ["kurs"],
    hint: "Admonition-Kasten für Warnungen; wird im Kurs und in H5P als Warnung gerendert.",
    code: "!!! warning {{Titel der Warnung}}\n{{Text der Warnung}}\n!!!"
  },
  {
    id: "kurs-infobox",
    label: "Info-Box",
    tags: ["kurs"],
    hint: "Admonition-Kasten für Hinweise, z. B. für Einsteiger.",
    code: "!!! info {{Titel}}\n{{Hinweistext}}\n!!!"
  },
  {
    id: "kurs-hinweisbox",
    label: "Hinweis-Box",
    tags: ["kurs"],
    hint: "Admonition-Kasten für Anmerkungen und Ausnahmen.",
    code: "!!! note {{Titel}}\n{{Hinweistext}}\n!!!"
  },
  {
    id: "kurs-tippbox",
    label: "Tipp-Box",
    tags: ["kurs"],
    hint: "Admonition-Kasten für Tipps und Hilfestellungen.",
    code: "!!! hint {{Titel}}\n{{Tipp}}\n!!!"
  },
  {
    id: "kurs-code-beispiel",
    label: "Code-Beispiel",
    tags: ["kurs"],
    hint: "Python-Codeblock, den Lernende ausführen können.",
    code: "```python\n{{print(\"Hallo Welt\")}}\n```"
  },
  {
    id: "kurs-code-noeditor",
    label: "Code-Beispiel ohne Editor",
    tags: ["kurs"],
    hint: "Python-Codeblock ohne Editor-Button, z. B. für reine Beispiele.",
    code: "```python noeditor\n{{print(\"Hallo Welt\")}}\n```"
  },
  {
    id: "kurs-editor-startcode",
    label: "Editor: Startcode",
    tags: ["kurs"],
    hint: "Vorbelegter Code im Editor der Aktivität.",
    code: "```python editor:startingCode\n{{# Dein Code hier}}\n```"
  },
  {
    id: "kurs-editor-yaml",
    label: "Editor: zusätzliche Dateien",
    tags: ["kurs"],
    hint: "Zusätzliche Dateien für den Editor; mit visibleToLearner und learnerEditable steuerbar.",
    code: "```yaml editor\noptions:\n  sourceFiles:\n  - fileName: {{helper.py}}\n    code: |\n      {{SECRET = 42}}\n    visibleToLearner: false\n    learnerEditable: false\n```"
  },
  {
    id: "kurs-grading",
    label: "Bewertung (grading)",
    tags: ["kurs"],
    hint: "Bewertungsmethode, Frist und Testfälle der Aktivität.",
    code: "```yaml grading\ngradingMethod: {{please_choose}}\ndueDateGroup:\n  enableDueDate: false\n  duedate: {{01.01.1970}}\ntestCases: []\n```"
  },
  {
    id: "kurs-instructions",
    label: "Anweisungen (Instructions)",
    tags: ["kurs"],
    hint: "Aufgabenstellung der Aktivität im Instructions-Block.",
    code: "<Instructions>\n{{Anweisung an die Lernenden}}\n</Instructions>"
  },
  {
    id: "kurs-abschnitt",
    label: "Abschnittsüberschrift",
    tags: ["kurs"],
    hint: "Gliedert den sichtbaren Inhalt der Aktivität.",
    code: "### {{Titel des Abschnitts}}"
  }
];

export function createShortcutController({ state, elements, escapeHtml, normalizeSearch, openModal, closeModal, insertTemplate, insertText, focusEditor, scheduleAutoUpdate }) {
  let clearOptions = null;

  function openShortcutsModal() {
    clearOptions?.();
    clearOptions = null;
    elements.shortcutsSearch.value = "";
    state.shortcutFilter = state.course.kursMode
      ? "kurs"
      : (state.shortcutFilter === "kurs" ? "alle" : state.shortcutFilter);
    renderShortcutChips();
    renderShortcutsList();
    openModal(elements.shortcutsModal, elements.shortcutsSearch);
  }

  function closeShortcutsModal() {
    clearOptions?.();
    clearOptions = null;
    closeModal(elements.shortcutsModal);
  }

  function renderShortcutChips() {
    const tags = state.course.kursMode
      ? SHORTCUT_TAGS.filter(([id]) => id === "kurs")
      : SHORTCUT_TAGS.filter(([id]) => id !== "kurs");
    elements.shortcutsChips.innerHTML = tags.map(([id, label]) => (
      `<button type="button" class="chip${state.shortcutFilter === id ? " active" : ""}" data-tag="${id}">${escapeHtml(label)}</button>`
    )).join("");
    for (const chip of elements.shortcutsChips.querySelectorAll(".chip")) {
      chip.addEventListener("click", () => {
        state.shortcutFilter = chip.dataset.tag;
        renderShortcutChips();
        renderShortcutsList();
      });
    }
  }

  function renderShortcutsList() {
    const query = normalizeSearch(elements.shortcutsSearch.value);
    const items = SHORTCUTS.filter((item) => {
      if (state.course.kursMode ? !item.tags.includes("kurs") : item.tags.includes("kurs")) return false;
      if (state.shortcutFilter !== "alle" && !item.tags.includes(state.shortcutFilter)) return false;
      if (!query) return true;
      return normalizeSearch([item.label, item.hint, SHORTCUT_EXAMPLES[item.id] || "", item.code].join(" ")).includes(query);
    });
    elements.shortcutsList.innerHTML = items.length
      ? items.map(shortcutCardHtml).join("")
      : `<div class="empty-result">Keine Treffer.</div>`;
    for (const card of elements.shortcutsList.querySelectorAll(".shortcut-card")) {
      card.addEventListener("click", () => insertShortcut(card.dataset.id));
    }
  }

  function shortcutCardHtml(item) {
    const preview = escapeHtml(item.code).replace(/\{\{(.*?)\}\}/g, '<span class="shortcut-placeholder">$1</span>');
    return `<button type="button" class="shortcut-card" data-id="${escapeHtml(item.id)}">
    <span class="shortcut-title">${escapeHtml(item.label)}</span>
    <span class="shortcut-example"><span class="shortcut-example-label">Beispiel</span><span>${escapeHtml(SHORTCUT_EXAMPLES[item.id] || item.hint)}</span></span>
    <span class="shortcut-hint">${escapeHtml(item.hint)}</span>
    <span class="shortcut-hint">${shortcutFields(item).length ? "Einstellungen anpassen …" : "Direkt einfügen"}</span>
    <pre class="shortcut-code">${preview}</pre>
  </button>`;
  }

  function insertShortcut(id) {
    const item = SHORTCUTS.find((entry) => entry.id === id);
    if (!item) return;
    if (shortcutFields(item).length) {
      clearOptions?.();
      clearOptions = showShortcutOptions({
        item, escapeHtml,
        body: elements.shortcutsModal.querySelector(".shortcuts-body"),
        onBack: () => {
          clearOptions?.();
          clearOptions = null;
          elements.shortcutsList.querySelector(`[data-id="${item.id}"]`)?.focus();
        },
        onInsert: (code) => finishInsert(code, true),
      });
      return;
    }
    finishInsert(item.code);
  }

  function finishInsert(code, configured = false) {
    closeShortcutsModal();
    setTimeout(() => {
      if (configured) insertText(code);
      else insertTemplate(code);
      focusEditor?.();
      scheduleAutoUpdate();
    }, 0);
  }

  function openShortcutFromEditor(id) {
    openShortcutsModal();
    insertShortcut(id);
  }

  return { openShortcutsModal, closeShortcutsModal, renderShortcutChips, renderShortcutsList, insertShortcut, openShortcutFromEditor };
}
