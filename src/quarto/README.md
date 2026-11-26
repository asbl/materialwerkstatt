Hier liegt die Quarto-Technik.

Der Ordner enthaelt Filter und Templates, die Quarto beim Rendern der Unterrichts- und Organisationsmaterialien verwendet.

Der `pre-render`-Hook in der Projektkonfiguration ruft
`src/quarto_render_guard.py` auf. Ohne die nur fuer verwaltete Subprozesse
gesetzte Variable `MATERIAL_BUILD_MANAGED=1` bricht er vor dem Rendern ab.
Freigegeben werden `inv build`, `inv preview`, der Onlyoffice-Import und die
Material-UI. Die Freigabe wird nicht in die Umgebung des aufrufenden Terminals
geschrieben. Der Hook gilt fuer dieses Quarto-Projekt; unabhaengige Projekte
mit eigener Konfiguration sind davon nicht betroffen.
