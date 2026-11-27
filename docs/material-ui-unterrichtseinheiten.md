# Unterrichtseinheiten und Einsatzdaten

Die Seitenleistenansicht **Unterrichtseinheiten** (Uhr-Pfeil-Symbol) zeigt zuerst
kompakte Klassen-Badges, darunter direkt die Themen mit ihren Einheiten. Ohne
gespeicherte Ansichtswahl startet die App in den Unterrichtseinheiten
(Standardansicht); eine bewusst gewählte andere Ansicht bleibt beim Start
erhalten. Fach und
Klasse werden im Baum nicht wiederholt. Themen und Einheiten sind nach ihrem
ersten Einsatz im gewählten Zeitraum sortiert. Undatierte Einheiten werden
standardmäßig ausgeblendet. Innerhalb einer Einheit stehen Einsätze aufsteigend
nach Datum.
Das aktive Klassen-Badge ist farbig markiert; die Auswahl bleibt beim Neuladen
bestehen. Standardmäßig erscheinen nur Klassen mit Einsätzen im aktuellen Schuljahr
sowie mit datumsneutralen, wiederkehrenden Einheiten. Unter **Filter → Schuljahr**
lassen sich auch andere Schuljahre auswählen; die angebotenen Schuljahre gelten
für alle Klassen. **Undatierte Einheiten bearbeiten** macht zusätzlich Klassen mit
Entwürfen zugänglich. Neu angelegte Einheiten und offene Entwürfe bleiben erreichbar.
Die Beschriftungen lauten 5–10, E (Klasse 11), Q1/Q2 (Klasse 12) und Q3/Q4
(Klasse 13). Q-Badges unterscheiden die Einsatzdaten nach Schulhalbjahr:
August–Januar bzw. Februar–Juli. Wiederkehrende Einheiten gelten in beiden Halbjahren.
Der Schuljahreswechsel liegt am 1. August. Die Lerngruppe (z. B. 5a) ist optional.

Jeder Materialordner kann eine `einheit.yaml` enthalten. Bestehende QMD-Ordner
sind auch ohne diese Datei über **Undatierte Einheiten bearbeiten** erreichbar;
beim ersten Speichern entsteht sie. Eine
Zusammenfassung kann auch in einem übergeordneten Ordner ohne eigene QMD liegen.
Die Dateien bleiben im privaten Unterrichtsrepository.

```yaml
titel: Multiplikation mit Bibi & Tina
thema: Arithmetik / Multiplikation
kurzbeschreibung: Malkreuz und schriftliche Multiplikation üben.
einsatz:
  - datum: '2026-11-06'
    lerngruppe: 5a
    material: ab_uebungen.qmd
    notiz: Einführung mit gemeinsamem Beispiel
  - datum: '2027-11-05'
    lerngruppe: 5b
    material: ab_uebungen.qmd
```

Das Beispiel illustriert das Dateiformat; die tatsächlichen Einsatzdaten werden
bewusst von der Lehrkraft eingetragen. `material` ist relativ zum Einheitenordner;
ein leerer Wert bezeichnet die gesamte Einheit. Jedes Datum ist ein eigener Einsatz,
auch bei Wiederverwendung derselben Datei in einem anderen Schuljahr. Verknüpfte
Arbeitsblätter können auch aus einem anderen Unterrichtsordner stammen.

In der Ansicht eine Einheit aufklappen und **Zusammenfassung und Einsätze bearbeiten**
wählen. Das Formular beginnt mit dem Thema als Auswahlliste, gefolgt vom Titel der
Lerneinheit; Kurzbeschreibung kann geändert, Einsätze hinzugefügt oder
entfernt werden. **Speichern** schreibt die Datei; zwischenzeitliche Dateiänderungen
führen zu einem Konflikt statt zum Überschreiben. **Aktualisieren** liest externe
Änderungen neu ein. Die Materialknöpfe öffnen das jeweilige Dokument.

Das Feld `thema` bündelt unterschiedliche Ordner unter derselben Themenfolge,
z. B. `Arithmetik / Multiplikation`. Deshalb sind keine Ordnerumzüge notwendig.

Die Themenfolge wird als eine Themenüberschrift dargestellt, z. B.
**Arithmetik / Multiplikation**, darunter direkt die Einheiten. In Klasse 05 sind Multiplikationsmaterialien aus Numeracy,
Fördermaterial und den regulären Einheiten unter diesem Thema zusammengeführt.

Offene Entwürfe bleiben pro Einheit beim Wechsel von Klasse, Schuljahr oder
Ansicht sowie beim Aktualisieren und beim Speichern einer anderen Einheit erhalten.
Sie werden zusätzlich im Browser-Tab gespeichert und nach dem Neuladen wieder
angeboten. **Abbrechen** fragt vor dem Verwerfen eines bearbeiteten Entwurfs nach.
Mit dem Schließen des Tabs endet diese lokale Zwischenspeicherung.

Fehlende Materialdateien werden als **Material fehlt** angezeigt. Ihre historischen
Einsätze bleiben sichtbar und bearbeitbar. Beim Umbenennen einer Datei über die
Material-UI werden die Einsatzverweise in ihrer Einheit und in übergeordneten
Zusammenfassungen aktualisiert. Externe Umbenennungen können durch die Auswahl des
neuen Materials im Einsatzformular korrigiert werden.

Übergeordnete Einheiten bieten QMD-Materialien aus allen Unterordnern an, auch wenn
diese eigene Zusammenfassungen besitzen. Die jeweiligen Einsatzlisten bleiben
getrennt; Einsätze werden nicht automatisch zwischen Eltern- und Kindeinheiten kopiert.

## Konflikte und Ordneränderungen

Wurde eine Einheit zwischenzeitlich außerhalb des Formulars geändert, bleibt der
Entwurf beim Speichern erhalten. **Mit aktueller Fassung zusammenführen** vergleicht
die ursprüngliche Datei, den Entwurf und die aktuelle Datei. Änderungen an
unterschiedlichen Feldern werden kombiniert. Bei konkurrierenden Änderungen zeigt
die Oberfläche beide Fassungen; pro betroffenem Feld wird ausdrücklich gewählt.
Für die Einsatzliste wird die gesamte Liste verglichen und gewählt. Das Ergebnis
bleibt zunächst ein Entwurf zum Prüfen und Bearbeiten. Erst **Speichern** schreibt
es in die Datei. Weitere zwischenzeitliche Änderungen lösen erneut einen Konflikt
aus, statt überschrieben zu werden.

Ordnerumbenennungen und das Umsortieren nummerierter Ordner aktualisieren auch
Materialverweise in übergeordneten Zusammenfassungen. Referenzen innerhalb des
verschobenen Ordners bleiben relativ gültig. Können die Verweise nicht geschrieben
werden, wird die Verschiebung einschließlich der Build-Artefakte zurückgenommen.
Ungültige Zusammenfassungen werden mit ihrem Dateipfad gemeldet und müssen vor der
Umbenennung korrigiert werden.

Entfällt das ausgewählte Schuljahr durch eine Änderung der Einsätze, springt die
Auswahl auf **Alle Schuljahre** zurück.


## Zeitliche Übersicht und wiederkehrende Materialien

Nach der Klassenwahl erscheinen direkt die Themen. Beispiel Klasse 10:

- Potenzen
  - Einführung · 28.10
  - Ganzzahlige Exponenten · 03.11 · 04.11
  - Rechengesetze · 10.11
- Kopfübungen · wiederkehrend

Die Termine in diesem Beispiel gehören zum Jahr 2026. Einheiten ohne Einsatzdatum
erscheinen im normalen Zeitverlauf nicht. Auch Themen ohne sichtbare Einheiten
bleiben ausgeblendet. Die Schuljahresauswahl bezieht sich auf die gewählte Klasse.
Mehrfache Einsätze derselben Einheit werden gemeinsam aufgelistet und nach Datum
sortiert; bei Einsätzen in unterschiedlichen Kalenderjahren wird auch das Jahr
angezeigt.

**Datumsneutral / wiederkehrend** ist eine allgemeine Eigenschaft jeder Einheit,
keine Sonderregel für den Ordnernamen „Kopfübungen“. Die Markierung lässt sich im
Bearbeitungsformular setzen und wird als `datumsneutral: true` in `einheit.yaml`
gespeichert. Solche Einheiten bleiben unabhängig vom Schuljahresfilter als direkte
Einträge sichtbar, ohne eine zusätzliche Themenebene. Einsatzdaten dürfen trotzdem
weiterhin erfasst werden.

Der direkt unter der Klassenwahl sichtbare Schalter **Undatierte Einheiten bearbeiten**
blendet noch nicht terminierte Einheiten zum Bearbeiten ein. Dort können Einsatzdaten oder die Markierung „datumsneutral“
ergänzt werden. Die Ansicht ist standardmäßig auf datierte und wiederkehrende Einheiten beschränkt;
die gewählte Bearbeitungsoption wird zusammen mit der Ansicht gemerkt. Offene Entwürfe bleiben zusätzlich sichtbar,
damit ungespeicherte Änderungen weiterhin erreichbar sind.

## Einheit einer freien Stunde zuweisen

In der Planungsansicht hat jede kommende, noch freie Stunde neben **+ Lerneinheit** die Aktion
**Einheit zuweisen**. Sie öffnet unter der Stunde eine Auswahl mit den Einheiten derselben Klasse
und desselben Fachs. Noch nie eingesetzte Einheiten stehen zuerst, danach folgt die Sortierung
nach Thema und Titel; die Suchzeile grenzt nach Titel und Thema ein. Einheiten mit ungespeicherten
Änderungen oder mit bereits eingetragenem Einsatz an diesem Tag sind nicht wählbar. Die Auswahl ist
vollständig per Tastatur bedienbar (Escape schließt sie und gibt den Fokus zurück).

Die Zuweisung schreibt einen Einsatz mit Datum und Lerngruppe der Stunde (Revisionsprüfung wie bei
**Weiteres Datum**; bei einem Konflikt bleibt alles unverändert). Die Statuszeile bietet
**Rückgängig** an; das entfernt genau diesen Einsatz wieder. Einsätze gelten pro Tag und Lerngruppe,
bei einer Doppelstunde zeigen deshalb beide Stunden dieselbe Einheit.

**Ziehen als Abkürzung:** Jede Einheitenkarte hat links einen Griff (⠿). Wird er auf eine freie
Stunde gezogen, trägt die Ansicht den Einsatz genauso ein wie die Auswahl, inklusive **Rückgängig**.
Beim Start des Ziehens klappen freie Tage auf; am oberen und unteren Rand der Ansicht scrollt sie
automatisch. Stunden einer anderen Klasse oder eines anderen Fachs werden gestrichelt markiert und
nehmen die Einheit nicht an. Escape bricht das Ziehen ab. Ziehen ist nur eine Abkürzung: die
Auswahl bleibt der Weg per Tastatur und für Touch-Geräte ohne feine Zeigersteuerung.

Schnittstelle: `POST /api/units/dates` akzeptiert zusätzlich `material` (Einsatz für ein einzelnes
Material statt der ganzen Einheit) und `remove: [{datum, lerngruppe, material}]` zum Entfernen
einzelner Einsätze; Entfernen ist idempotent. Gleiches Datum mit anderem Material ist ein eigener
Einsatz, derselbe Einsatz wird nicht doppelt angelegt.

## Kompakte Materialliste

Aufgeklappte Einheiten zeigen eine Liste mit Dokumenttiteln und Typ-Icons statt
Dateinamen als große Schaltflächen. Zusammengehörige Arbeitsblätter und Lösungen
stehen in einer Zeile: Die Lösung ist über das Lösungssymbol rechts erreichbar.
Die Zuordnung erfolgt anhand des gleichen relativen Dateistamms mit dem Suffix
`-loesung` oder `-loesungen`. Nicht zugeordnete Lösungen bleiben eigene Listeneinträge.
Lange Titel werden gekürzt; der vollständige Titel, Typ und Dateipfad erscheinen
im Tooltip. Alle Dokumente bleiben über Links per Tastatur und in neuen Tabs erreichbar.

Über **Zu Einheit hinzufügen** in der Materialsuche lässt sich ein vorhandenes
Arbeitsblatt in einer weiteren Einheit verwenden. Die Einheit speichert unter
`verlinkte_materialien` einen Pfad relativ zu ihrem Ordner. Das Arbeitsblatt
erscheint in ihrer Materialliste und steht im Feld **Material** eines Einsatzes
zur Auswahl. Die Quelle und ihre Ressourcen bleiben an ihrem Pfad. Beim
Umbenennen über die Material-UI werden Verknüpfungen und Einsätze mitgeführt.
Sobald die Einsätze dieses Blatts entfernt sind, kann auch die Verknüpfung
entfernt werden.

Das Datum steht nur im Einheitenkopf. Einsatzdetails mit Lerngruppe, Material oder
Notiz werden separat aufklappbar angeboten. Automatisch erzeugte Zusammenfassungen,
die mit `Materialien:` beginnen, wiederholen die Liste nicht. Eigene Beschreibungen
bleiben unter **Notizen** erreichbar; im Bearbeitungsformular ist die vollständige
Zusammenfassung weiterhin vorhanden. **Bearbeiten** öffnet die Metadaten und Einsätze.

Tags und Notizen lassen sich ohne Umweg über das Formular direkt auf der Einheitenkarte
bearbeiten: Der dezente Stift neben den Tag-Chips beziehungsweise hinter **Notizen**
öffnet eine kurze Inline-Eingabe — Tags kommagetrennt mit Vorschlagsliste, Notizen
als Mehrzeilenfeld. **Speichern** schreibt über dieselbe Revisionssicherung wie das
Bearbeitungsformular und lädt die Ansicht neu; **Abbrechen** (oder `Esc`) stellt den
Zustand vor der Eingabe wieder her und fragt bei Änderungen nach. Solange ein Entwurf
des großen Formulars geöffnet ist, bleibt die Inline-Bearbeitung gesperrt.

## Neue Lerneinheiten und Arbeitsblätter

**Hinzufügen → Neue Lerneinheit** in der Seitenleiste legt einen neuen Materialordner mit
`einheit.yaml` an. Fach und Klasse sind vorbelegt. Das Formular beginnt mit dem **Thema**
als Auswahlliste der vorhandenen Themen der Jahrgangsstufe; dahinter folgt der **Titel der
Lerneinheit**, optional ein erstes Datum oder „datumsneutral“. Über „+ Neues Thema…“ lässt
sich ein neues Thema direkt eintragen. Vorhandene Ordner
werden nicht überschrieben. Neu angelegte Einheiten ohne Termin bleiben bis zum
Neuladen sichtbar, damit direkt Materialien ergänzt werden können. Danach sind sie
wie andere undatierte Einheiten über die Bearbeitungsoption erreichbar.

**Neues AB** innerhalb einer Einheit öffnet den vorhandenen Materialdialog mit
vorbelegtem Typ Arbeitsblatt, Fach, Klasse, Thema und festem Zielordner. Titel,
Vorlage und Mini-Format können dort gewählt werden. Die Datei wird direkt im
Einheitenordner mit dem Präfix `ab_` beziehungsweise `ab_mini_` angelegt und
anschließend im Editor geöffnet; die Materialliste aktualisiert sich automatisch.

Vor den Dateititeln stehen neben den Icons auch sichtbare Typkürzel wie **AB:**,
**Slide:** und **Lösung:**. Der Lösungszugang eines Arbeitsblatts ist zusätzlich mit
„Lösung“ beschriftet.

## Vorhandene Ordner einbinden

**Hinzufügen → Vorhandenen Ordner einbinden** in der Einheitenansicht öffnet eine durchsuchbare Ordnerauswahl
für die gewählte Klasse. Alternativ den
Klassen-/Materialordner in der Ordneransicht öffnen und auswählen: Darunter
erscheint die Aktion **Als Lerneinheit einbinden** mit Uhr-Symbol. Dabei ist der
Ordner bereits vorausgewählt.

Titel und Thema werden aus einer vorhandenen Zusammenfassung oder dem Ordnernamen
vorbelegt; das Thema steht auch hier vor dem Titel und wird als Auswahlliste
der vorhandenen Themen der Jahrgangsstufe mit einer Option für ein neues Thema
angeboten. Datum wählen, optional Lerngruppe ergänzen und **Einbinden und Datum
speichern** anklicken. Die Einheit erscheint danach im passenden Schuljahr.
Vorhandene Einsätze, Notizen und weitere Metadaten bleiben erhalten; derselbe
Einsatz für die gesamte Einheit wird nicht doppelt eingetragen. Materialien werden
weder verschoben noch kopiert. Fehlende Zusammenfassungen werden als `einheit.yaml`
im gewählten Ordner angelegt, vorhandene Zusammenfassungen ergänzt.

Wurde die Zusammenfassung zwischenzeitlich geändert, wird das Speichern blockiert.
**Ordnerdaten neu laden** übernimmt die aktuelle Zusammenfassung; das eingegebene
Datum und die Lerngruppe bleiben erhalten. Danach kann das Datum erneut ergänzt
werden, ohne neu hinzugekommene Einsätze zu überschreiben.

## Tags der Lerneinheiten

`einheit.yaml` unterstützt `tags: [vertretung, multiplikation]` unabhängig von
Dokument-Tags. Die Einheitenansicht zeigt diese Tags und bietet im
Bearbeitungsformular ein Feld mit Vorschlägen an. „Tags filtern“ akzeptiert
mehrere kommagetrennte Tags; eine Einheit muss alle angegebenen Tags tragen.
Klassen-, Schuljahres- und Datumsfilter gelten zusätzlich. Tags werden bei
Konflikten wie die anderen Felder zusammengeführt.

Klasse 05 verwendet fachliche Themenordner. Förderkurs und Numeracy sind Tags
und liegen mit ihren Einheiten direkt unter dem jeweiligen fachlichen Thema.
Gemeinsame Vorlagen und Zeichnungen liegen unter `materialgestaltung/`.


## Themen verwalten

Themen stehen in allen Lerneinheiten-Formularen vor dem Titel. Das Thema ist eine
Auswahlliste mit den vorhandenen Themen der Jahrgangsstufe im jeweiligen Fach;
„+ Neues Thema…“ trägt direkt ein neues Thema ein. Die Auswahllisten gleichen
Schreibabweichungen wie Groß-/Kleinschreibung ab und wählen dann das
vorhandene Thema, statt ein Duplikat anzulegen; beim Anlegen einer Einheit
übernimmt der Server zusätzlich dessen vorhandene Schreibweise. Ein beim
Löschen neu benanntes Ersatzthema wird dagegen unverändert übernommen.

Über **Thema löschen…** neben der Themaauswahl wird ein Thema entfernt. Seine
Einheiten behalten Titel, Termine und Materialien und wechseln in ein Ersatzthema,
das aus den übrigen Themen gewählt oder als neues Thema benannt wird. Eine
Rückfrage nennt die Anzahl der Einheiten vor dem Löschen. Es werden keine Ordner
verschoben, sondern nur das `thema`-Feld der `einheit.yaml`-Dateien der
ausgewählten Fach-/Klassen-Teilmenge angepasst.

Ordner ohne eigene `einheit.yaml`, deren Thema aus dem Ordnerpfad abgeleitet wird,
blockieren das Löschen mit einer Meldung; sie müssen zuerst als Lerneinheit
eingebunden oder umbenannt werden. Angefangene Formulare übernehmen nach dem
Löschen das Ersatzthema, damit ein gelöschtes Thema nicht versehentlich neu
entsteht. Offene Einheiten-Entwürfe werden beim nächsten Speichern über den
üblichen Änderungsvergleich aufgelöst.


## Ansicht und angefangene Formulare behalten

Klasse, Schuljahr, Tagfilter, aufgeklappte Themen und Einheiten sowie die Scrollposition
bleiben beim Aktualisieren und Neuladen im selben Browser-Tab erhalten. Auch die
Formulare für neue Einheiten, Ordner-Einbindungen und schnelle Datumeinträge werden
zwischengespeichert. Die Speicherung ist pro Projekt getrennt. Erfolgreiches Speichern
oder bewusstes Abbrechen entfernt den jeweiligen Formularentwurf.

**Hinzufügen** bündelt das Anlegen und Einbinden. **Weitere Optionen** enthält
Aktualisieren und die Bearbeitungsansicht für undatierte Einheiten. Beim Anlegen
stehen Fach und Klasse unter **Weitere Angaben**; ihre Vorbelegung bleibt erhalten.
Eine Ordnersuche ohne passenden Treffer setzt die Auswahl zurück und deaktiviert
das Speichern, bis ausdrücklich wieder ein Ordner gewählt wird.

## Datum schnell ergänzen

In einer aufgeklappten Einheit öffnet **Termine** die bereits gespeicherten Termine
des gewählten Schuljahrs als ausgefüllte Datumsfelder. Diese können direkt geändert
werden; Materialzuordnung, Lerngruppe und Notizen bleiben dabei erhalten.
**Weiteres Datum** fügt ausdrücklich einen neuen Termin hinzu. Die Lerngruppenwahl
gilt nur für neue Termine.
**Termine speichern** ergänzt alle angegebenen Einsätze gemeinsam; vorhandene
Notizen, Tags und Termine bleiben erhalten. Doppelte Einsätze der gesamten Einheit
mit gleichem Datum und gleicher Lerngruppe werden vermieden.

Bei zwischenzeitlichen Änderungen bleiben die Eingaben erhalten. **Aktuelle Einheit
laden** übernimmt die aktuelle Dateirevision; die eingegebenen Termine können danach
erneut gespeichert werden. Der vollständige Metadateneditor ist weiterhin über
**Bearbeiten** erreichbar.


## Aktive Unterrichtseinheit erkennen

Die ausgewählte Einheit erhält einen farbigen Rahmen, einen leicht hinterlegten
Bereich und einen hervorgehobenen Titel. Die tatsächlich geöffnete Datei wird in
dieser Einheit zusätzlich markiert. Beim Öffnen eines Materials oder Wechseln des
Dokument-Tabs folgt die Markierung dem geöffneten Material; die zugehörige Einheit
wird bei Bedarf aufgeklappt und in den sichtbaren Bereich geholt. Die Auswahl bleibt
auch beim Aktualisieren und Neuladen erhalten.

**Termine** bedeutet „vorhandene Termine anzeigen und bearbeiten“, nicht „es fehlt
noch ein Datum“. Bei einem bestehenden Einsatz am 06.11. steht dieses Datum bereits
im Formular. Erst **Weiteres Datum** fügt einen neuen Einsatz hinzu. Änderungen an
bestehenden Terminen und neue Termine werden gemeinsam gegen die geladene
Dateirevision geprüft, damit zwischenzeitliche Änderungen nicht überschrieben werden.

Materialien lassen sich in der Lerneinheiten-Ansicht am Materiallink auf die
Überschrift einer anderen Einheit ziehen, auch wenn diese zugeklappt ist.
Verschoben wird die einzelne Markdown-/QMD-Datei. Gleichnamige Dateien am Ziel
werden nicht überschrieben. Offene Dokumentänderungen werden vorab über den
üblichen Speicherweg gesichert; Einheitenentwürfe müssen zuerst gespeichert
werden. Besprechungen und explizite Lösungszuordnungen bleiben verknüpft.
Die Einsatztermine der bisherigen Einheit bleiben erhalten; beim Verlassen der
Einheit entfällt dort nur der Verweis auf die verschobene Datei. Verweise in
übergeordneten Einheiten und in Lernstanddaten werden aktualisiert.


Beim Ziehen werden Zeigerereignisse verwendet; erst ab sechs Pixeln Bewegung
beginnt ein Verschub. Ein normaler Klick öffnet weiterhin das Material.
Offene Tabs werden auf den neuen Pfad umgestellt, auch wenn gerade ein anderes
Dokument aktiv ist. Relative Bilder, Includes und Links werden vor dem Verschub
geprüft: Solche Dokumente werden mit einer Meldung abgewiesen, statt Verweise zu
beschädigen. Die Ressourcen werden nicht automatisch kopiert. Absolute Pfade,
Webadressen und reine Abschnittsanker verhindern den Verschub nicht.

## Unterricht vorausplanen

Kalendertermine sind in die bestehende Einheitenliste eingebunden. Es gibt keine
zusätzliche Planungsliste und keinen zweiten Scrollbereich. Zugeordnete Stunden
erscheinen als aufklappbare Datumszeilen innerhalb ihrer Lerneinheit. Die Datumsangabe
im Einheitenkopf bleibt erhalten; Ausfälle werden dort zusätzlich knapp angezeigt.

Kommende, noch unbelegte Unterrichtstage stehen als schmale Zeilen **Noch offen**
zwischen den Themenblöcken, nach Datum des Themenbeginns eingeordnet. Mehrere
Stunden am selben Tag werden zusammengefasst. Erst beim Aufklappen erscheinen
Uhrzeit, Kurs und die dezenten Aktionen **+ Lerneinheit** und **Ausfall**.
Zugeordnete Termine werden nicht noch einmal als freie Termine angezeigt, auch
wenn die zugehörige Einheit durch einen Filter ausgeblendet ist.

**+ Lerneinheit** öffnet das Anlegeformular mit Datum, Klasse, Fach und Lerngruppe.
**Ausfall** kennzeichnet genau dieses Vorkommen lokal; **Ausfall aufheben** macht
dies rückgängig. Kalender und bestehende Einsatzdaten werden nicht verändert.

Ohne Schuljahresfilter endet die Vorschau zunächst am Ende des laufenden Schuljahres
(31. Juli). Erst nach dem Ende der letzten tatsächlichen Unterrichtsstunde dieses
Schuljahres wird das nächste Schuljahr samt Wechsel-Trenner eingeblendet. Ferien und
markierte Ausfälle zählen nicht als verbleibende Stunden. Maßgeblich sind alle
Klassen und Halbjahre, nicht nur der aktive Klassenfilter. Ohne geladene Stunden
oder bei fehlerhaften Quellen wird das nächste Schuljahr nicht vorzeitig freigegeben.
Mit ausdrücklichem Schuljahresfilter erscheint das gewählte Schuljahr samt Abschlussgrenze. Die Q-Halbjahresauswahl gilt auch für
die Termine. Fehlende oder nicht geladene Kalenderquellen können Lücken verursachen.
Unterrichtstermine an Ferientagen werden automatisch ausgeblendet, sowohl bei
zugeordneten Einheiten als auch bei freien Tagen. Grundlage sind die ganztägigen
Einträge des in den Kalendereinstellungen gewählten Ferienkalenders, einschließlich
aller Tage mehrtägiger Ferien. Ohne ausdrückliche Auswahl werden geladene Kalender
mit „Ferien“ oder „Feiertage“ im Namen automatisch berücksichtigt. Gespeicherte Einsatzdaten bleiben erhalten.
Schmale Trennlinien in derselben Liste markieren den Halbjahreswechsel am
**1. Februar** und den Schuljahreswechsel am **1. August** entsprechend der bisherigen
Einteilung; dies sind keine aus dem Ferienkalender ermittelten Unterrichtsbeginn-Daten.


## Eigene Trenner

**Hinzufügen → Trenner hinzufügen** öffnet ein Formular für Titel, Datum und Farbe.
Vorschläge sind Notenschluss, Noteneintragung und Elternsprechtag; eigene Titel sind
möglich. In **Alle Schuljahre** bleiben auch vergangene Trenner sichtbar. Ein
gewählter Schuljahresfilter grenzt sie auf das jeweilige Schuljahr ein; die
Begrenzung künftiger Schuljahre gilt weiterhin. Das Datum enthält zur eindeutigen
Zuordnung auch die Jahreszahl.
Ein Trenner gilt wahlweise für alle Klassen oder nur die ausgewählte Klasse.
Er erscheint als farbige Linie in derselben zeitlichen Liste wie die Einheiten und
freien Termine, auch an unterrichtsfreien Tagen. Schuljahres- und Q-Halbjahresfilter
gelten auch für eigene Trenner.

Jeder eigene Trenner erscheint zugleich als **ganztägiger Termin** am gewählten
Datum im Kalender, in der Agenda und am jeweiligen Tag unter Heute, mit derselben
Farbe. Auch bereits gespeicherte Trenner werden automatisch berücksichtigt.
Ändern von Titel, Datum oder Farbe und Löschen wirken unmittelbar auf den
Kalendertermin; es gibt keine getrennten Kopien. Die Termine gehören zur lokalen
Kalenderquelle **Unterrichtsplanung**.

Ein Klick auf den Trenner öffnet das Formular zum Ändern oder Löschen. Die Einträge
liegen dauerhaft im lokalen Plugin-Speicher (`planning-markers.json`), unabhängig
von Unterrichtsmaterial und Kalender-Synchronisation. Zwischenzeitliche Änderungen
werden beim Speichern erkannt und nicht überschrieben.

## Markdown-Notizen zur Einheit

**Neue Notiz** ergänzt ein eigenständiges Dokument neben Arbeitsblättern und Folien.
Es entsteht eine Datei `notiz_<titel>.md` direkt im Einheitenordner mit YAML-Frontmatter
(`title`, `kind: Notiz`, `tags`). Der vorhandene Markdown-Editor öffnet sie ohne
PDF-Vorschau, Rendern, Präsentieren oder Besprechungs-Canvas. Speichern,
Entwurfswiederherstellung, Tabs und Konfliktschutz funktionieren wie bei anderen
Dokumenten. Auch **Neues Material → Notiz** steht zur Verfügung.

Notizen erscheinen in Materialliste, Suche und Tagansicht. In den Einsatzdaten kann
`material` auf die Markdown-Datei zeigen, beispielsweise am 11.11.2026 auf
`notiz_buchaufgaben.md`. Das Datum bleibt in `einheit.yaml`; dieselbe Notiz kann
mehrfach verwendet werden. Eine Einheit benötigt kein Arbeitsblatt.

Erfasst werden Markdown-Dateien mit Präfix `notiz_` oder Frontmatter `kind: Notiz`.
Allgemeine Ordnerhinweise bleiben in der reservierten Datei `hinweise.md`.
Notizen bekommen kein Renderformat und keine Templatebindung und werden von den
QMD-Sammelbuilds nicht erfasst.

Beim Umbenennen bleiben Notizen Markdown-Dateien. Reservierte Hinweisnamen wie
`hinweise.md` sind dafür gesperrt. Wird das Präfix `notiz_` entfernt, muss gültiges
Frontmatter mit `kind: Notiz` den Dokumenttyp weiterhin kennzeichnen. Abgelehnte
Umbenennungen ändern weder die Datei noch ihre Einsatzverweise.

### Notizen zu einem Arbeitsblatt

Neben jedem Arbeitsblatt liegt optional eine Notizdatei `<ab-stamm>-notizen.md`,
zum Beispiel `ab_bruchrechnen.qmd` und `ab_bruchrechnen-notizen.md`. Sie nimmt
Rückmeldungen für den nächsten Durchlauf auf (was gut lief, was anzupassen ist)
und verhält sich ansonsten wie eine Einheitennotiz: Markdown-Editor ohne
PDF-Vorschau, kein Rendern, keine Präsentation.

Der Notizen-Knopf am Arbeitsblatt (Materialliste der Einheit, Ordneransicht und
Besprechungsaktionen offener QMD-Dateien) legt die Datei mit
`title: Notizen zu …` und `kind: Notiz` an, falls sie fehlt, und öffnet sie
sonst direkt. In der Ordner- und der Einheitenansicht erscheint die Notiz
dann mit dem Kurzlabel **Notiz** direkt unter dem Arbeitsblatt, genauso wie
Lösungen (`…-loesung.qmd`) gepaart angezeigt werden. Beim Umbenennen eines
Arbeitsblatts bleibt der Dateiname der Notiz unverändert; die Paarung folgt
dem Dateinamens-Suffix, wie es auch bei Lösungen der Fall ist.

## Ordnerstruktur am Einheitenmodell ausrichten

Die Ansicht leitet Fach, Klasse, Thema und Einheit primär aus `einheit.yaml` ab,
nicht aus Ordnernamen; Ordnerumzüge sind deshalb nie zwingend. Die folgende Liste
richtet sich an Strukturfragen, die die Ansicht nicht selbst lösen kann.

Bereits bereinigt (Stufe 1, Stand 12.11.2026):

- Pseudo-Einheiten an der Klassenwurzel entfernt („Klasse 10“, „Klasse 12“ mit
  `thema: klasse-10` bzw. `klasse-12`, ohne eigene Materialien). Die
  Reihenplanungen liegen jetzt als echte Einheiten unter dem Thema Organisation:
  `mathematik/klasse-10/organisation/reihenplanung-2025-26/` und
  `informatik/klasse-12/organisation/reihenplanung-q1-2026-27/`, jeweils mit
  QMD- und HTML-Fassung samt Versionshistorie.
- `informatik/Q1/` ist aufgelöst. Beide Materialordner liegen jetzt als Einheiten
  des Themas Algorithmen unter `informatik/klasse-12/algorithmen/`
  (`analyse-von-algorithmen` mit side-Präsentation,
  `sortieralgorithmen-im-vergleich` mit Arbeitsblatt). Klasse-12 entspricht dem
  Q1-Label der Ansicht; ein Ordner `informatik/Q1` wird vom Scan nicht als
  Klassenordner erkannt.
- `informatik/klasse-11/klausuren/klausur-e1-2026/` erhielt eine `einheit.yaml`
  und erscheint damit wie die E2-Klausur unter dem Thema Klausuren.
- Thema-Duplikat konsolidiert: `mathematik/klasse-10/kopfübungen/alt` trägt jetzt
  `thema: Kopfübungen` statt der Kleinschreibung und gruppiert wie die
  Haupteinheit unter einem Thema.
- Leere Ordner entfernt (leere `assets/`-Anlage der Q1-Einführung, leerer
  Render-Zwischenordner unter `sachkunde/felix/lernstrategie/`).

Offene Punkte — Umsetzung und Entscheidungen (Stand 12.11.2026):

- `mathematik/klasse-05/multiplizieren-und-dividieren/…` verdoppelte denselben
  Namen. Die Einheit trägt `thema: Multiplikation` und liegt jetzt direkt im
  zugehörigen Themenordner:
  `klasse-05/multiplikation/multiplizieren-und-dividieren/`; der leere Wrapper
  ist entfernt. Termine und Materialverweise sind unverändert.
- `mathematik/klasse-09/kreise/arbeitsblaetter/…` sortierte nach Materialart.
  Die Einheit liegt jetzt direkt unter `kreise/umfang-durchmesser/`; das
  Composite-Thema `kreise / arbeitsblaetter` bleibt bewusst unverändert, da
  das `thema`-Feld die Themenfolge unabhängig von Ordnern bündelt.
- `mathematik/klasse-10/kopfübungen/` ist Einheit und Container der
  Nebeneinheit `alt/`. Belassen: Übergeordnete Einheiten mit eigenen
  Materialien und Untereinheiten sind ein dokumentiertes Muster (gleiche Form
  wie `trigonometrie/` mit `arbeitsblaetter/`, `klausur-2026/` und
  `klausuren/`); es liegt kein Strukturfehler vor.
- `mathematik/klasse-10/trigonometrie/klausur-2026/` gruppiert vier
  Klausur-Einheiten. Belassen: Eine Umbenennung zu `klausuren` würde mit der
  bestehenden Einheit `trigonometrie/klausuren/` kollidieren.
- `organisation/` an der Wurzel (Elternbriefe, Konferenzen) liegt außerhalb des
  Fach-/Klassenrasters und ist in der Ansicht unsichtbar. Belassen als bewusste
  Ablage außerhalb des Unterrichts; klassenbezogene Organisationseinheiten
  (Muster: `klasse-05/organisation/elternabend/`) lassen sich bei Bedarf
  anlegen.
