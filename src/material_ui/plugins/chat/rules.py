"""Kurzfassung der Material-Konventionen fuer den Chat (Quelle: CLAUDE.md, Abschnitte
"Aufgabenkennzeichnung", "Loesungen", "Sonstige Hinweise"; mechanisch geprueft von
``material_core.conventions``).

Der Chat gibt dem Modell diese Regeln einmal pro Sitzung und Dokumenttyp mit und bietet das
Werkzeug ``check_document`` an, damit Entwuerfe vor dem Vorschlag selbst geprueft werden."""

from __future__ import annotations

from pathlib import PurePosixPath

from material_core.conventions import is_slide_path, is_worksheet_path

KINDS = ("worksheet", "mini", "solution", "slide", "other")
KIND_LABELS = {
    "worksheet": "Arbeitsblatt", "mini": "Mini-Arbeitsblatt", "solution": "Lösungsblatt",
    "slide": "Folien", "other": "Material",
}

COMMON = (
    "Überschriften ohne Punkte oder Mittelpunkte als Trenner; Aufgabennummer und Titel stehen mit Leerzeichen getrennt.",
    "Untertitel im Dokumentkopf leer lassen (nur auf ausdrücklichen Wunsch setzen).",
    "Keine Hinweise, ob im Heft, im Kopf oder auf dem Blatt gerechnet wird.",
    "Zeichnungen und Rechenmodelle über vorhandene Markdown-Shortcuts statt eigener SVG- oder Canvas-Grafiken.",
    "Platzhalter und mathematische Antwortfelder sind hellgrau und randlos (#eeeeee).",
)
BY_KIND = {
    "worksheet": (
        "Aufgaben nach Anforderungsbereichen staffeln: AFB I fett (**a)**), AFB II normal (b)), AFB III rot ([c)]{.zusatz}).",
        "Nur Aufgabenbuchstaben bzw. Teilaufgabennummern kennzeichnen; Aufgabenstellung und Formeln bleiben normal.",
        "Von AFB I über II zu III steigern; AFB III sparsam und nur für wirklich anspruchsvolle Teilaufgaben.",
        "Keine Differenzierungslisten, Metahinweise (\"Kern: a, c\") oder Legende im Schülertext.",
    ),
    "mini": (
        "Vorderseite: kurze Übungen; Rückseite: eigenständige Knobelaufgabe mit um 180 Grad gedrehter Lösung im Textkasten.",
        "Mindestens 11 pt Grundschrift, keine verkleinerten Überschriften oder Tabellen.",
        "AFB-Kennzeichnung wie beim Arbeitsblatt (I fett, II normal, III rot mit .zusatz).",
    ),
    "solution": (
        "Ergebnisse mit der Span-Klasse .loesung blau hervorheben, Erklärungen in normaler Textfarbe.",
        "Ausführlich und erklärend: Rechenwege, Zusammenhänge, typische Fehler in kurzen, schülerfreundlichen Absätzen.",
        "Deutlicher Lösungstitel; das Design des zugehörigen Arbeitsblatts verwenden.",
    ),
    "slide": (
        "Folien sparsam texten: pro Folie eine Skizze oder ein Modell-Kürzel.",
        "Reflexions- und Verständnisfragen nur als HTML-Kommentar (<!-- Reflexionsfrage: … -->), nie als sichtbarer Folieninhalt.",
        "Gesprächsimpulse bleiben Kommentar im Quelltext; Aufgabenstellungen bleiben sichtbar.",
    ),
    "other": (),
}


def kind_for_path(path: str) -> str:
    posix = PurePosixPath(path)
    name = posix.name.lower()
    if is_slide_path(posix):
        return "slide"
    if "loesung" in name or "lösung" in name:
        return "solution"
    if name.startswith("ab_mini_"):
        return "mini"
    if is_worksheet_path(posix):
        return "worksheet"
    return "other"


def rules_text(kind: str) -> str:
    rules = (*BY_KIND.get(kind, ()), *COMMON)
    return f"Projektregeln für {KIND_LABELS.get(kind, 'Material')}:\n" + "\n".join(f"- {rule}" for rule in rules)
