Hier liegen Quarto/Pandoc-Filter.

Die Filter uebersetzen eigene Markdown-Marker in LaTeX- oder andere Ausgabeformen.

Suchfelder, Entscheidungsbäume, Halbierungen und Wachstumsdiagramme sind in
[ALGORITHMEN-MODELLE.md](../ALGORITHMEN-MODELLE.md) dokumentiert. Die Kürzel
funktionieren auch beim Erzeugen von Excalidraw-Decks.

Schülerdialoge unterstützen außerdem `haarfarbe="#d9b34a"` je `.dialogbeitrag`.
Das Design legt keine Namen oder fachlichen Inhalte fest. Beispiele für Dialoge
mit automatisch berechneten schriftlichen Multiplikationen und dreiteiligen
Malkreuzen stehen in [ARITHMETIK-MODELLE.md](../ARITHMETIK-MODELLE.md).

Eingabetabellen akzeptieren auch die Schreibweise `[eingabetabelle 8mm]`
mit dem Abschluss `[/eingabetabelle]`. Die übliche Schreibweise mit großem
`E` bleibt gültig.

Bei versionierten Vorlagen delegiert der Projektfilter an den gebundenen
Versionsfilter in einer eigenen Lua-Umgebung. Das ist nötig, weil Quarto
Projekt- und Dokumentfilter mit gleichem Dateinamen zusammenfassen kann.
`MATERIAL_TEMPLATE_FILTER_DIR` wird durch den BuildService gesetzt und muss
auch in ausführenden Invoke-Tasks erhalten bleiben; ein fehlender gebundener
Filter darf nicht zu einem PDF mit unverarbeiteten Shortcuts führen.
