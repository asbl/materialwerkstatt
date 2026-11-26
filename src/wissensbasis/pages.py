from __future__ import annotations

import shutil
from collections import defaultdict
from datetime import date
from fnmatch import fnmatch
from urllib.parse import quote

from .config import Fach
from .notes import Note, as_list, load_notes, load_taxonomy, load_templates, parse_pages, sections
from .ordnung import Ordnung
from .scan import load_manifest

GENERATED = "<!-- generiert von wissensbasis (invoke wissen-build); nicht von Hand ändern -->"
DERIVED_NOTE = (
    "*Lesehinweis:* „Aussage“ und „Beispiel“ geben die Quelle wieder (Fundstelle: bei PDFs die PDF-Seite, gedruckte Seite "
    "in Klammern; bei Webquellen der Abschnitt der gespeicherten Lesekopie). "
    "„Planung“ und „Prüffrage“ sind Ableitungen der Kartenautorin bzw. des Kartenautors und nicht Aussagen der Quelle."
)
UNIT_LABELS = {"seite": "PDF-S.", "abschnitt": "Abschnitt", "folie": "Folie", "bild": "Bild"}
BRIEFING_FACETS = {"themen": "themen"}
CHECKLIST_FACETS = {"prinzipien": "prinzipien", "kompetenzen": "kompetenzen"}


def _german_date(value) -> str:
    """YAML liest `abgerufen: 2026-09-23` als Datum; angezeigt wird es wie in der Zitierweise."""
    return value.strftime("%d.%m.%Y") if isinstance(value, date) else str(value)


def _label(taxonomy: dict, group: str, tag: str) -> str:
    return (taxonomy.get(group) or {}).get(tag, {}).get("label", tag)


def _grades(cards: list[Note]) -> str:
    grades = sorted({int(grade) for card in cards for grade in as_list(card.meta.get("klassenstufen"))})
    if not grades:
        return "–"
    return str(grades[0]) if len(grades) == 1 else f"{grades[0]}–{grades[-1]}"


def _card_grades(card: Note) -> str:
    grades = sorted(int(grade) for grade in as_list(card.meta.get("klassenstufen")))
    if not grades:
        return "Klassenstufe offen"
    consecutive = grades == list(range(grades[0], grades[-1] + 1))
    if len(grades) > 2 and consecutive:
        return f"Kl. {grades[0]}–{grades[-1]}"
    return "Kl. " + "/".join(str(grade) for grade in grades)


def _href(note: Note, prefix: str = "") -> str:
    """Dateinamen enthalten Tags ('… #aufgaben #prio1.md'): '#' und Leerzeichen für Markdown-Links kodieren."""
    return prefix + quote(f"{note.ref}.md")


def _is_card_index(note: Note) -> bool:
    return note.meta.get("art") in {"aufgaben-index"}


def _is_task_card(note: Note) -> bool:
    return note.meta.get("typ") == "aufgabe"


class Context:
    """Everything needed to render a card reference: dossiers, manifest paths, taxonomy."""

    def __init__(self, fach: Fach) -> None:
        self.fach = fach
        self.taxonomy = load_taxonomy(fach)
        notes = load_notes(fach)
        all_cards = [note for note in notes if note.art == "karte" and not _is_card_index(note)]
        self.cards = [note for note in all_cards if not _is_task_card(note)]
        self.task_cards = [note for note in all_cards if _is_task_card(note)]
        self.dossiers = {note.dok: note for note in notes if note.art == "dossier"}
        self.templates = load_templates(fach)
        self.ordnung = Ordnung(fach, notes)
        self.manifest = load_manifest(fach)
        self.documents = {doc["id"]: doc for doc in self.manifest["dokumente"]}

    def short_source(self, card: Note) -> str:
        dossier = self.dossiers.get(card.dok)
        if dossier is None:
            return card.dok
        if dossier.meta.get("kurzzitat"):
            return str(dossier.meta["kurzzitat"])
        authors = as_list(dossier.meta.get("autoren"))
        year = dossier.meta.get("jahr")
        if authors:
            return f"{str(authors[0]).split()[-1]}{' ' + str(year) if year else ''}"
        return dossier.titel

    def pages(self, card: Note) -> str:
        """Fundstelle in der Einheit des Dokuments: PDF-Seite, Abschnitt einer Web- oder Textquelle, Folie, Bild."""
        start, end = parse_pages(card.meta["seite"])
        span = f"{start}" if start == end else f"{start}–{end}"
        unit = ((self.documents.get(card.dok) or {}).get("text") or {}).get("einheit", "seite")
        if unit != "seite":
            return f"{UNIT_LABELS.get(unit, unit.capitalize())} {span}"
        offset = (self.dossiers.get(card.dok).meta.get("seitenversatz") if card.dok in self.dossiers else None)
        if offset is None:
            return f"PDF-S. {span}"
        printed = f"{start + offset}" if start == end else f"{start + offset}–{end + offset}"
        return f"S. {printed} (PDF-S. {span})"

    def origin(self, card: Note) -> str:
        """'nach Malle 2004 (zitiert bei Wittmann 2006)' when the statement stems from another author."""
        later = as_list(card.meta.get("nach"))
        return f"nach {', '.join(str(name) for name in later)} (zitiert bei {self.short_source(card)})" if later else ""

    def references(self, cards: list[Note]) -> list[str]:
        lines = []
        for dok in sorted({card.dok for card in cards}):
            dossier = self.dossiers.get(dok)
            citation = dossier.meta.get("zitierweise") if dossier else None
            first = next(card for card in cards if card.dok == dok)
            lines.append(f"- **{self.short_source(first)}**: {' '.join(str(citation).split()) if citation else dok}")
        return lines

    def file(self, card: Note) -> str:
        doc = self.documents.get(card.dok)
        return doc["pfad"] if doc else "?"

    def location(self, card: Note) -> str:
        """Webquellen nennen die Adresse und das Abrufdatum, denn die Datei ist nur die Lesekopie."""
        dossier = self.dossiers.get(card.dok)
        url = dossier.meta.get("url") if dossier else None
        if not url:
            return f"Datei: `{self.file(card)}`"
        fetched = dossier.meta.get("abgerufen")
        return f"<{url}>" + (f" (abgerufen am {_german_date(fetched)})" if fetched else "") + f" · Kopie: `{self.file(card)}`"

    def source_line(self, card: Note) -> str:
        return f"{self.short_source(card)}, {self.pages(card)}"


def _draft(card: Note) -> str:
    """Marker for cards the teacher has not released yet."""
    return "" if card.meta.get("status") == "freigegeben" else " **[Entwurf, nicht freigegeben]**"


def _derived(card: Note, name: str) -> str:
    return sections(card.body).get(name, "")


def _card_detail(card: Note, context: Context, heading: str) -> list[str]:
    parts = sections(card.body)
    typ = _label(context.taxonomy, "typen", card.meta.get("typ", ""))
    belegart = _label(context.taxonomy, "belegarten", card.meta.get("belegart", ""))
    lines = [
        f"{heading} {card.titel}{_draft(card)}",
        "",
        f"*{typ} · {belegart} · {_card_grades(card)}*  ",
        f"*Quelle: {context.source_line(card)} · {context.location(card)}*"
        + (f"  \n*Herkunft der Aussage: {context.origin(card)}*" if context.origin(card) else ""),
        "",
    ]
    for name in ("Aussage", "Beispiel", "Planung", "Prüffrage"):
        if name in parts:
            text = parts[name] if "\n\n" in parts[name] else " ".join(parts[name].split())
            lines += [f"**{name}.** {text}" if "\n\n" not in text else f"**{name}:**\n\n{text}", ""]
    return lines


MAX_DETAIL_CHARS = 30000


def _detail_name(tag: str, number: int) -> str:
    return f"{tag}-details.md" if number == 1 else f"{tag}-details-{number}.md"


def _briefing(tag: str, cards: list[Note], context: Context) -> dict[str, str]:
    """Return {file name: text}: a compact page plus detail pages (split at MAX_DETAIL_CHARS)."""
    label = _label(context.taxonomy, "themen", tag)
    ordered = sorted(cards, key=lambda card: (card.dok, parse_pages(card.meta["seite"])))

    chunks: list[list[Note]] = [[]]
    size = 0
    for card in ordered:
        text = "\n".join(_card_detail(card, context, "###"))
        if chunks[-1] and size + len(text) > MAX_DETAIL_CHARS:
            chunks.append([])
            size = 0
        chunks[-1].append(card)
        size += len(text)

    files: dict[str, str] = {}
    for number, chunk in enumerate(chunks, start=1):
        lines = [f"# {label}: Karten im Detail" + (f" (Teil {number} von {len(chunks)})" if len(chunks) > 1 else ""), "",
                 GENERATED, "", f"Kompakte Übersicht: [{tag}.md]({tag}.md)", "", DERIVED_NOTE, ""]
        for card in chunk:
            lines += _card_detail(card, context, "##")
        lines += ["## Quellenangaben", ""] + context.references(chunk)
        files[_detail_name(tag, number)] = "\n".join(lines).rstrip() + "\n"

    sources = {card.dok for card in cards}
    lines = [
        f"# {label}", "", GENERATED, "",
        f"{len(cards)} Karten aus {len(sources)} Quellen · Klassenstufen {_grades(cards)}", "",
        DERIVED_NOTE, "",
    ]
    lines += _priority_section(tag, context)
    lines += ["## Kernaussagen", ""]
    for card in ordered:
        typ = _label(context.taxonomy, "typen", card.meta.get("typ", ""))
        origin = f" ({context.origin(card)})" if context.origin(card) else ""
        lines.append(
            f"- [**{card.titel}**]({_href(card, '../')}){_draft(card)} ({typ}, {_card_grades(card)}) – {card.meta['kern']} "
            f"*{context.source_line(card)}{origin}*"
        )
    checks = [(card, _derived(card, "Prüffrage")) for card in ordered if _derived(card, "Prüffrage")]
    if checks:
        lines += ["", "## Prüffragen zu diesem Thema", ""]
        for card, question in checks:
            lines.append(f"- {' '.join(question.split())} *({card.titel}; {context.short_source(card)})*")
    templates = [template for template in context.templates if tag in as_list(template.meta.get("themen"))]
    if templates:
        lines += ["", "## Vorlagen zum Nachbauen", "",
                  "Aufgabenformate mit Beispielen in den Kürzeln des Fördermaterials (eigene Zahlen, Fundstellen im Kopf der Datei).", ""]
        lines += [_template_line(template, context, "../") for template in templates]
    lines += ["", "## Quellenangaben", ""] + context.references(ordered)
    lines += ["", "## Volltext der Karten", ""]
    for number, chunk in enumerate(chunks, start=1):
        lines.append(f"- [{_detail_name(tag, number)}]({_detail_name(tag, number)}) ({len(chunk)} Karten)")
    files[f"{tag}.md"] = "\n".join(lines).rstrip() + "\n"
    return files


FIRST_READ = 8


def _priority_line(card: Note, context: Context, note: str = "") -> str:
    typ = _label(context.taxonomy, "typen", card.meta.get("typ", ""))
    return (f"- **P{context.ordnung.stufe(card)}** [**{card.titel}**]({_href(card, '../')}){_draft(card)} ({typ}, "
            f"{_card_grades(card)}) – {card.meta['kern']} *{context.source_line(card)}*{note}")


def _priority_section(tag: str, context: Context) -> list[str]:
    """Leitquellen des Bereichs und die wichtigsten Karten des Themas (Regeln: _config/prioritaet.yaml)."""
    order = context.ordnung
    pflicht, rest = order.auswahl({tag})
    lines = ["## Zuerst lesen", "",
             f"Nach Priorität (P1 bis P3, Regeln in `_config/prioritaet.yaml`). Gezielter: "
             f"`invoke wissen-auswahl {tag} --zweck stundenentwurf|aufgaben|pruefen|foerdern [--klasse N]`.", ""]
    if pflicht:
        lines += [f"**Immer berücksichtigen (Leitquellen für {order.bereich(tag)}):**", ""]
        lines += [_priority_line(hit.card, context) for hit in pflicht]
        lines.append("")
    lines += [_priority_line(hit.card, context) for hit in rest[:FIRST_READ]]
    purposes = defaultdict(set)
    for rule in order.rules.get("leitquellen") or []:
        for zweck in as_list(rule.get("zwecke")):
            purposes[zweck].add(str(rule.get("quelle")))
    for zweck, sources in sorted(purposes.items()):
        label = ((order.rules.get("zwecke") or {}).get(zweck) or {}).get("label", zweck)
        names = sorted({context.short_source(card) for card in order.cards if any(fnmatch(card.dok, s) for s in sources)})
        if names:
            lines += ["", f"*{label}: immer auch {', '.join(names)} heranziehen* (`invoke wissen-auswahl {tag} --zweck {zweck}`)."]
    return lines + [""]


def _template_line(template: Note, context: Context, prefix: str) -> str:
    fmt = _label(context.taxonomy, "formate", str(template.meta.get("format", "")))
    models = ", ".join(_label(context.taxonomy, "modelle", str(model)) for model in as_list(template.meta.get("modell")))
    used = len(as_list(template.meta.get("umsetzungen")))
    return (f"- [**{template.titel}**]({_href(template, prefix)}){_draft(template)} ({fmt}, {_card_grades(template)}) – "
            f"{models}; {used} Umsetzung{'en' if used != 1 else ''} im Fördermaterial *({context.short_source(template)})*")


def _task_sources(task: Note, context: Context) -> str:
    lines = []
    for entry in as_list(task.meta.get("quellen")):
        if not isinstance(entry, dict):
            continue
        source_id = str(entry.get("quelle", ""))
        if not source_id:
            continue
        dossier = context.dossiers.get(source_id)
        title = str(dossier.meta.get("kurzzitat") or dossier.titel) if dossier else source_id
        page = f", S. {entry['seite']}" if entry.get("seite") else ""
        lines.append(f"{title}{page}")
    return "; ".join(lines) if lines else "ohne Quellenbeleg"


def _task_line(task: Note, context: Context, prefix: str) -> str:
    topics = ", ".join(_label(context.taxonomy, "themen", tag) for tag in as_list(task.meta.get("themen")))
    materials = ", ".join(_label(context.taxonomy, "materialtypen", tag) for tag in as_list(task.meta.get("materialtypen")))
    details = " · ".join(part for part in (_card_grades(task), topics, materials) if part)
    return f"- [**{task.titel}**]({_href(task, prefix)}){_draft(task)} ({details}) – *{_task_sources(task, context)}*"


def _checklist(facet: str, tag: str, cards: list[Note], context: Context) -> str:
    label = _label(context.taxonomy, facet, tag)
    lines = [f"# {label}", "", GENERATED, "",
             f"Prüffragen aus {len(cards)} Karten. Details stehen auf den Themenseiten und in den verlinkten Karten.", ""]
    for card in sorted(cards, key=lambda c: (c.dok, parse_pages(c.meta["seite"]))):
        thema = ", ".join(_label(context.taxonomy, "themen", theme) for theme in as_list(card.meta.get("themen")))
        question = _derived(card, "Prüffrage")
        planning = _derived(card, "Planung")
        lines.append(f"## [{card.titel}]({_href(card, '../')}){_draft(card)}")
        lines.append(f"*{thema} · {_card_grades(card)} · {context.source_line(card)}*")
        lines.append("")
        if question:
            lines += [f"**Prüffrage:** {question}", ""]
        elif planning:
            lines += [f"**Planung:** {planning}", ""]
    return "\n".join(lines).rstrip() + "\n"


def _priority_overview(context: Context) -> list[str]:
    order = context.ordnung
    levels = defaultdict(int)
    for card in context.cards:
        levels[order.stufe(card)] += 1
    lines = ["## Priorisierung und Ablage", "",
             "Karten liegen unter `karten/<bereich>/<quelle>/<name> #<kategorie> #prio<n>.md`; neue Karten kommen nach "
             "`karten/_neu/` und werden von `invoke wissen-pflegen` aufgenommen (oder nach `karten/_zurueckgestellt/` gelegt) "
             "und einsortiert. Regeln: `_config/prioritaet.yaml`. Schnellauswahl: "
             "`invoke wissen-auswahl <thema> [--zweck stundenentwurf|aufgaben|pruefen|foerdern] [--klasse N]`.", "",
             "Stufen: " + ", ".join(f"P{level} {levels[level]}" for level in sorted(levels)) + ". Leitquellen (immer berücksichtigen):", ""]
    for rule in order.rules.get("leitquellen") or []:
        scope = [*as_list(rule.get("bereiche")), *as_list(rule.get("themen")),
                 *(f"Zweck {zweck}" for zweck in as_list(rule.get("zwecke")))]
        cards = [card for card in context.cards if fnmatch(card.dok, str(rule.get("quelle", "")))]
        names = sorted({context.short_source(card) for card in cards}) or [str(rule.get("quelle"))]
        lines.append(f"- **{', '.join(names)}** ({len(cards)} Karten) für {', '.join(scope)}: {rule.get('grund', '')}")
    return lines + [""]


def _index(context: Context, counts: dict[str, dict[str, int]]) -> str:
    fach, taxonomy = context.fach, context.taxonomy
    status: dict[str, int] = defaultdict(int)
    for doc in context.manifest["dokumente"]:
        status[(doc.get("text") or {}).get("status", "offen")] += 1
    lines = [
        f"# Wissensbasis {fach.name}", "", GENERATED, "",
        f"{len(context.manifest['dokumente'])} Dokumente in `{context.manifest['quellenordner']}/` "
        f"({', '.join(f'{name} {count}' for name, count in sorted(status.items()))}). "
        f"Erschlossen: {len(context.dossiers)} Dossiers, {len(context.cards)} Karten "
        f"({sum(1 for card in context.cards if card.meta.get('status') == 'freigegeben')} freigegeben, "
        f"{sum(1 for card in context.cards if card.meta.get('status') != 'freigegeben')} Entwurf), "
        f"{len(context.task_cards)} Aufgabenkarten, {len(context.templates)} Vorlagen.", "",
        "Einstieg und Arbeitsweise: [../README.md](../README.md)", "",
        *_priority_overview(context),
        "## Themen (Kompaktseiten; Volltext der Karten jeweils verlinkt)", "",
        "| Thema | Karten | Klassenstufen |", "|---|---|---|",
    ]
    by_area: dict[str, list[str]] = defaultdict(list)
    for tag in counts["themen"]:
        by_area[(taxonomy.get("themen") or {}).get(tag, {}).get("bereich", "sonstige")].append(tag)
    for area in sorted(by_area):
        lines.append(f"| **{area}** | | |")
        for tag in sorted(by_area[area]):
            cards = [card for card in context.cards if tag in as_list(card.meta.get("themen"))]
            lines.append(f"| [{_label(taxonomy, 'themen', tag)}](themen/{tag}.md) | {len(cards)} | {_grades(cards)} |")
    for facet in CHECKLIST_FACETS:
        if not counts[facet]:
            continue
        lines += ["", f"## {facet.capitalize()} (Prüffragen-Listen)", "", "| Eintrag | Karten |", "|---|---|"]
        for tag in sorted(counts[facet]):
            lines.append(f"| [{_label(taxonomy, facet, tag)}]({facet}/{tag}.md) | {counts[facet][tag]} |")
    if context.templates:
        lines += ["", "## Vorlagen (Aufgabenformate zum Nachbauen)", "",
                  "Beispiele in den Kürzeln des Fördermaterials; Katalog: `invoke wissen-vorlagen-build` → "
                  "`vorlagen/build/vorlagen-katalog.pdf`. Arbeitsweise: [vorlagen/README.md](vorlagen/README.md)", ""]
        lines += [_template_line(template, context, "") for template in context.templates]
    if context.task_cards:
        lines += ["", "## Aufgabenkarten (gebrauchsfertige Beispiele)", "",
                  "Konkrete Aufgabenbeispiele in reinem Markdown; Arbeitsweise: [karten/aufgaben/README.md](karten/aufgaben/README.md)", ""]
        lines += [_task_line(task, context, "") for task in context.task_cards]
    lines += ["", "## Quellen mit Dossier", "", "| Quelle | Art | Abdeckung | Karten | Vorlagen |", "|---|---|---|---|---|"]
    for dok, dossier in sorted(context.dossiers.items(), key=lambda item: item[1].titel):
        cards = sum(1 for card in context.cards if card.dok == dok)
        templates = sum(1 for template in context.templates if template.dok == dok)
        lines.append(f"| [{dossier.titel}](quellen/{dok}.md) | {dossier.meta.get('quellenart', '')} | "
                     f"{dossier.meta.get('abdeckung', '')} | {cards} | {templates} |")
    return "\n".join(lines) + "\n"


def build(fach: Fach) -> dict[str, dict[str, int]]:
    """Regenerate INDEX.md, one briefing per Thema and one checklist per Prinzip/Kompetenz from the cards."""
    context = Context(fach)
    counts: dict[str, dict[str, int]] = {}
    for facet, group in {**BRIEFING_FACETS, **CHECKLIST_FACETS}.items():
        directory = fach.wissen / facet
        shutil.rmtree(directory, ignore_errors=True)
        by_tag: dict[str, list[Note]] = defaultdict(list)
        for card in context.cards:
            for tag in as_list(card.meta.get(facet)):
                by_tag[tag].append(card)
        if by_tag:
            directory.mkdir(parents=True)
        for tag, cards in by_tag.items():
            if facet in BRIEFING_FACETS:
                for name, text in _briefing(tag, cards, context).items():
                    (directory / name).write_text(text, encoding="utf-8")
            else:
                (directory / f"{tag}.md").write_text(_checklist(group, tag, cards, context), encoding="utf-8")
        counts[facet] = {tag: len(cards) for tag, cards in by_tag.items()}
    (fach.wissen / "INDEX.md").write_text(_index(context, counts), encoding="utf-8")
    return counts
