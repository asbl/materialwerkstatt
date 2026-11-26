Hier liegt der Code fuer die Wissensbasis.

OCR und PDF-Verkleinerung brauchen das ab Werk ausgeschaltete Plugin `ocr` (`inv plugin-enable ocr`).

Die Module scannen Quellen, extrahieren Texte, bauen Suchindexe, pruefen Karten und erzeugen Dossiers sowie Uebersichten.

`pipeline.inspect_all` liefert einen strukturierten Prüfbericht;
`pipeline.check_all` zeigt ihn an. Beide verändern keine Dateien.
Aufnahme, Freigabe und Sortierung erfolgen ausdrücklich über
`wissen-aufnehmen`, `wissen-freigeben` und `wissen-sortieren`.
`wissen-pflegen` kombiniert diese Schritte unter einer gemeinsamen Laufsperre.
