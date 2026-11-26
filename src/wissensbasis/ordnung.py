"""Priorisierung, Aufnahme und Einsortierung der Karten. Die Regeln stehen in wissen/<fach>/_config/prioritaet.yaml."""
from __future__ import annotations

from material_core.filesystem import atomic_write_text

import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from fnmatch import fnmatch
from pathlib import Path

import yaml

from .config import Fach
from .notes import ZURUECKGESTELLT, Note, as_list, load_notes, load_taxonomy, parse_pages, read_note

NEU = "_neu"  # Eingang für neue Karten (autoerschliessen, von Hand); wissen-pflegen sortiert von dort ein
FESTE_ORDNER = {"aufgaben"}  # Aufgabenkarten mit .qmd, Build und eigenem README bleiben, wo sie sind
TAG = re.compile(r"\s+#[^\s#]+")
WORT = re.compile(r"[a-zäöüß]{4,}")


def load_rules(fach: Fach) -> dict:
    path = fach.wissen / "_config" / "prioritaet.yaml"
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def is_evidence_card(note: Note) -> bool:
    """Belegkarten aus Quellen; Aufgabenkarten und Index-Dateien haben eigene Regeln."""
    return note.art == "karte" and note.meta.get("typ") != "aufgabe" and note.meta.get("art") != "aufgaben-index"


def _admitted(card: Note) -> bool:
    return card.meta.get("status") == "freigegeben" or card.meta.get("aufnahme") == "aufgenommen"


@dataclass
class Treffer:
    card: Note
    punkte: int
    gruende: list[str] = field(default_factory=list)


class Ordnung:
    def __init__(self, fach: Fach, notes: list[Note] | None = None) -> None:
        self.fach = fach
        self.rules = load_rules(fach)
        self.taxonomy = load_taxonomy(fach)
        notes = load_notes(fach) if notes is None else notes
        self.dossiers = {note.dok: note for note in notes if note.art == "dossier"}
        self.cards = [note for note in notes if is_evidence_card(note)]

    # --- Regeln ---------------------------------------------------------------------------------

    def _points(self, group: str) -> dict:
        return (self.rules.get("punkte") or {}).get(group) or {}

    def bereich(self, tag: str) -> str:
        return ((self.taxonomy.get("themen") or {}).get(tag) or {}).get("bereich", "sonstige")

    def card_bereich(self, card: Note) -> str:
        themen = as_list(card.meta.get("themen"))
        return self.bereich(themen[0]) if themen else "sonstige"

    def quellenart(self, card: Note) -> str:
        dossier = self.dossiers.get(card.dok)
        return str(dossier.meta.get("quellenart", "")) if dossier else ""

    def leitregeln(self, card: Note) -> list[dict]:
        return [rule for rule in self.rules.get("leitquellen") or [] if fnmatch(card.dok, str(rule.get("quelle", "")))]

    def leitgrund(self, card: Note, themen: set[str], zweck: str | None) -> str:
        """Warum die Karte für diese Themen/diesen Zweck immer dazugehört ('' = gar nicht)."""
        bereiche = {self.bereich(tag) for tag in themen}
        for rule in self.leitregeln(card):
            if (bereiche & set(as_list(rule.get("bereiche"))) or themen & set(as_list(rule.get("themen")))
                    or (zweck and zweck in as_list(rule.get("zwecke")))):
                return str(rule.get("grund") or f"Leitquelle {rule.get('quelle')}")
        return ""

    def punkte(self, card: Note) -> int:
        total = self._points("belegart").get(card.meta.get("belegart"), 0)
        total += self._points("quellenart").get(self.quellenart(card), 0)
        total += sum(value for pattern, value in self._points("quellen").items() if fnmatch(card.dok, str(pattern)))
        return int(total)

    def stufe(self, card: Note) -> int:
        if str(card.meta.get("prioritaet", "")) in {"1", "2", "3"}:
            return int(card.meta["prioritaet"])
        if self.leitregeln(card):
            return 1
        points = self.punkte(card)
        for level, minimum in sorted((int(key), int(value)) for key, value in (self.rules.get("stufen") or {}).items()):
            if points >= minimum:
                return level
        return 3

    # --- Ablage ---------------------------------------------------------------------------------

    def dateiname(self, card: Note) -> str:
        base = TAG.sub("", card.path.stem).strip()
        tags = [(self.rules.get("kategorien") or {}).get(card.meta.get("typ"), card.meta.get("typ") or "karte"),
                f"prio{self.stufe(card)}"]
        if self.leitregeln(card):
            tags.append("leitquelle")
        if card.meta.get("status") != "freigegeben":
            tags.append("entwurf")
        return f"{base} {' '.join('#' + tag for tag in tags)}.md"

    def ziel(self, card: Note) -> Path:
        return self.fach.karten / self.card_bereich(card) / (card.dok or "ohne-quelle") / self.dateiname(card)

    # --- Auswahl --------------------------------------------------------------------------------

    def themen_zu(self, query: str) -> set[str]:
        """Themen-Kürzel, Bereich (z. B. arithmetik) oder ein Wort aus Label/Synonymen."""
        themen = self.taxonomy.get("themen") or {}
        if query in themen:
            return {query}
        by_area = {tag for tag, entry in themen.items() if (entry or {}).get("bereich") == query}
        if by_area:
            return by_area
        needle = query.casefold()
        found = {tag for tag, entry in themen.items()
                 if needle in tag or needle in str((entry or {}).get("label", "")).casefold()
                 or any(needle == str(word).casefold() for word in (entry or {}).get("synonyme") or [])}
        if not found:
            raise SystemExit(f"Kein Thema zu '{query}'. Themen: {', '.join(sorted(themen))}")
        return found

    def auswahl(self, themen: set[str], zweck: str | None = None, klasse: int | None = None) -> tuple[list[Treffer], list[Treffer]]:
        """(immer berücksichtigen, übrige nach Punkten) für die Themen, optional mit Zweck und Klassenstufe."""
        zwecke = self.rules.get("zwecke") or {}
        if zweck and zweck not in zwecke:
            raise SystemExit(f"Unbekannter Zweck '{zweck}'. Zwecke: {', '.join(zwecke)}")
        type_bonus = (zwecke.get(zweck) or {}).get("typen") or {}
        pflicht: list[Treffer] = []
        rest: list[Treffer] = []
        for card in self.cards:
            if not _admitted(card):
                continue
            tagged = set(as_list(card.meta.get("themen"))) & themen
            grund = self.leitgrund(card, themen, zweck)
            if not tagged and not grund:
                continue
            hit = Treffer(card, self.punkte(card))
            if tagged:
                hit.punkte += 2 if as_list(card.meta.get("themen"))[0] in themen else 1
            if type_bonus.get(card.meta.get("typ")):
                hit.punkte += int(type_bonus[card.meta["typ"]])
                hit.gruende.append(f"passt zu {zweck}")
            grades = [int(grade) for grade in as_list(card.meta.get("klassenstufen"))]
            if klasse is not None and grades:
                hit.punkte += 1 if klasse in grades else -3
            if str(card.meta.get("prioritaet", "")) == "1":
                hit.punkte += 3
            if grund:
                hit.gruende.insert(0, f"Leitquelle: {grund}")
                pflicht.append(hit)
            else:
                rest.append(hit)
        order = lambda hit: (-hit.punkte, hit.card.dok, parse_pages(hit.card.meta.get("seite") or 0))  # noqa: E731
        return sorted(pflicht, key=order), sorted(rest, key=order)

    # --- Aufnahme -------------------------------------------------------------------------------

    def entscheide(self, card: Note, admitted: list[Note]) -> tuple[bool, str]:
        rules = self.rules.get("aufnahme") or {}
        twin, similarity = self._nearest(card, admitted)
        if twin is not None:
            same_place = twin.dok == card.dok and _overlap(twin, card)
            limit = float(rules.get("duplikat_schwelle_gleiche_seite" if same_place else "duplikat_schwelle", 0.5))
            if similarity >= limit and self.punkte(twin) >= self.punkte(card):
                return False, f"Dublette von {twin.path.relative_to(self.fach.wissen).as_posix()} (Ähnlichkeit {similarity:.2f})"
        if self.leitregeln(card):
            return True, "Leitquelle"
        points = self.punkte(card)
        enough = int(rules.get("genug_karten", 12))
        counts = {tag: sum(1 for other in admitted if tag in as_list(other.meta.get("themen")))
                  for tag in as_list(card.meta.get("themen"))}
        if points < int(rules.get("mindestpunkte", 3)) and counts and min(counts.values()) >= enough:
            return False, (f"schwach belegt ({points} Punkte) und alle Themen haben schon mindestens {enough} Karten "
                           f"({', '.join(f'{tag} {count}' for tag, count in counts.items())})")
        thin = [tag for tag, count in counts.items() if count < enough]
        return True, f"{points} Punkte" + (f", ergänzt dünnes Thema {', '.join(thin)}" if thin else "")

    def _nearest(self, card: Note, others: list[Note]) -> tuple[Note | None, float]:
        words, shingles = _words(card), _shingles(card)
        best: tuple[Note | None, float] = (None, 0.0)
        for other in others:
            if other.path == card.path:
                continue
            other_words, other_shingles = _words(other), _shingles(other)
            jaccard = len(words & other_words) / max(1, len(words | other_words))
            containment = len(shingles & other_shingles) / max(1, min(len(shingles), len(other_shingles)))
            if max(jaccard, containment) > best[1]:
                best = (other, max(jaccard, containment))
        return best

    def regel_warnungen(self) -> list[str]:
        name = "_config/prioritaet.yaml"
        if not self.rules:
            return [f"{name} fehlt: keine Priorisierung, Karten werden nur nach Bereich und Quelle einsortiert"]
        warnings = []
        typen = set(self.taxonomy.get("typen") or {})
        bereiche = {(entry or {}).get("bereich") for entry in (self.taxonomy.get("themen") or {}).values()}
        for rule in self.rules.get("leitquellen") or []:
            if not any(fnmatch(dok, str(rule.get("quelle", ""))) for dok in self.dossiers):
                warnings.append(f"{name}: Leitquelle '{rule.get('quelle')}' passt auf kein Dossier")
            for area in as_list(rule.get("bereiche")):
                if area not in bereiche:
                    warnings.append(f"{name}: Bereich '{area}' unbekannt (vorhanden: {', '.join(sorted(bereiche))})")
            for zweck in as_list(rule.get("zwecke")):
                if zweck not in (self.rules.get("zwecke") or {}):
                    warnings.append(f"{name}: Zweck '{zweck}' ist unter zwecke nicht definiert")
        for zweck, entry in (self.rules.get("zwecke") or {}).items():
            for typ in (entry or {}).get("typen") or {}:
                if typ not in typen:
                    warnings.append(f"{name}: Typ '{typ}' bei Zweck '{zweck}' steht nicht in taxonomie.yaml")
        for typ in typen - set(self.rules.get("kategorien") or {}):
            warnings.append(f"{name}: Typ '{typ}' hat keine Kategorie für den Dateinamen")
        return warnings


def _words(card: Note) -> set[str]:
    return set(WORT.findall(f"{card.titel} {card.meta.get('kern', '')}".lower()))


def _shingles(card: Note) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-zäöüß0-9]+", card.body.lower())
    return {tuple(words[index:index + 4]) for index in range(len(words) - 3)}


def _overlap(first: Note, second: Note) -> bool:
    try:
        a, b = parse_pages(first.meta.get("seite")), parse_pages(second.meta.get("seite"))
    except ValueError:
        return False
    return a[0] <= b[1] and b[0] <= a[1]


def _set_fields(path: Path, fields: dict) -> None:
    """Felder ans Ende des Frontmatters schreiben (vorhandene gleichen Namens werden ersetzt)."""
    text = path.read_text(encoding="utf-8")
    head, body = text[4:].split("\n---", 1)
    lines = [line for line in head.splitlines() if not any(line.startswith(f"{key}:") for key in fields)]
    lines += yaml.safe_dump(fields, allow_unicode=True, sort_keys=False, width=10**6).strip().splitlines()
    atomic_write_text(path, "---\n" + "\n".join(lines) + "\n---" + body)


def _move(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(source, target)


def _prune(root: Path) -> None:
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), key=lambda path: -len(path.parts)):
        top = directory.relative_to(root).parts[0]
        if top not in FESTE_ORDNER and directory.name != NEU and not any(directory.iterdir()):
            directory.rmdir()


def aufnehmen(fach: Fach, errors: list[str], log=print) -> list[str]:
    """Neue Karten (Entwurf ohne Prüffehler und ohne Feld 'aufnahme') aufnehmen oder zurückstellen."""
    ordnung = Ordnung(fach)
    admitted = [card for card in ordnung.cards if _admitted(card)]
    decided = []
    for card in ordnung.cards:
        name = card.path.relative_to(fach.wissen).as_posix()
        if card.meta.get("status") != "entwurf" or card.meta.get("aufnahme") or any(error.startswith(f"{name}:") for error in errors):
            continue
        accept, reason = ordnung.entscheide(card, admitted)
        _set_fields(card.path, {"aufnahme": "aufgenommen" if accept else "zurueckgestellt", "aufnahme_grund": reason,
                                "aufnahme_am": date.today().isoformat()})
        if accept:
            admitted.append(card)
            log(f"[{fach.name}] aufgenommen: {name} ({reason})")
        else:
            _move(card.path, fach.karten / ZURUECKGESTELLT / (card.dok or "ohne-quelle") / (TAG.sub("", card.path.stem).strip() + ".md"))
            log(f"[{fach.name}] zurückgestellt: {name} ({reason})")
        decided.append(name)
    return decided


def sortieren(fach: Fach, dry_run: bool = False, log=print) -> list[tuple[Path, Path]]:
    """Aufgenommene Karten nach karten/<bereich>/<quelle>/<name #tags>.md verschieben; Entwürfe ohne Aufnahme bleiben liegen."""
    ordnung = Ordnung(fach)
    moves = []
    taken = {card.path for card in ordnung.cards}
    for card in ordnung.cards:
        if card.path.relative_to(fach.karten).parts[0] in FESTE_ORDNER:
            continue
        if card.meta.get("status") == "entwurf" and card.meta.get("aufnahme") != "aufgenommen":
            continue
        target = ordnung.ziel(card)
        if target == card.path:
            continue
        if target in taken or target.exists():
            log(f"[{fach.name}] nicht einsortiert, Ziel belegt: {card.path.relative_to(fach.wissen)} -> {target.relative_to(fach.wissen)}")
            continue
        taken.add(target)
        moves.append((card.path, target))
        if not dry_run:
            _move(card.path, target)
    if not dry_run:
        _prune(fach.karten)
    return moves


def karten_der_quelle(fach: Fach, quelle: str) -> list[Path]:
    """Alle Kartendateien einer Quelle, gleich in welchem Bereichsordner (auch zurückgestellte)."""
    paths = []
    for path in sorted(fach.karten.rglob("*.md")) if fach.karten.exists() else []:
        try:
            meta, _ = read_note(path)
        except ValueError:
            continue
        if str(meta.get("quelle", "")) == quelle:
            paths.append(path)
    return paths
