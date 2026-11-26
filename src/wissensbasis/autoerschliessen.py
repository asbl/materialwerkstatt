from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .config import ROOT, Fach, discover
from .extract import load_pages
from .notes import as_list, load_notes, parse_pages, read_note
from .ordnung import NEU, karten_der_quelle
from .pipeline import find_document
from .scan import load_manifest
from .text import slugify


ARTEFAKT_DIR = ROOT / "build" / "scratch" / "wissen-autoerschliessen"
STANDARD_LLM = os.environ.get("WISSEN_AUTO_LLM", "claude")


@dataclass
class SourcePackage:
    fach: Fach
    doc: dict[str, Any]
    dossier_path: Path
    dossier_meta: dict[str, Any]
    dossier_body: str
    existing_cards: list[tuple[Path, dict[str, Any], str]]
    pages: list[dict[str, Any]]


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _partial_dossiers(fach: Fach) -> list[Path]:
    # Least-recently-touched dossier first: every Lauf rewrites the Dossier-Datei, auch wenn
    # keine Karte aufgenommen wird. Alphabetische Reihenfolge würde sonst an der ersten Quelle
    # ohne weitere erschließbare Seiten (z. B. nur noch Werbung/Register) für immer kleben bleiben.
    notes = [note for note in load_notes(fach) if note.art == "dossier"]
    return [
        note.path
        for note in sorted(notes, key=lambda n: n.path.stat().st_mtime if n.path else 0)
        if note.path is not None and str(note.meta.get("abdeckung", "")).strip().lower() == "teilweise"
    ]


def _page_ranges(values: Any) -> set[int]:
    pages: set[int] = set()
    for value in as_list(values):
        try:
            start, end = parse_pages(value)
        except ValueError:
            continue
        pages.update(range(start, end + 1))
    return pages


def _covered_pages(cards: list[tuple[Path, dict[str, Any], str]]) -> set[int]:
    return _page_ranges(meta.get("seite") for _, meta, _ in cards if meta.get("seite"))


def _choose_pages(all_pages: list[dict[str, Any]], covered: set[int], max_pages: int) -> list[dict[str, Any]]:
    # "Mach weiter" usually means: continue after the last cited page, not fill old
    # front-matter/ad gaps that are formally uncovered but not worth carding. `covered`
    # enthält dafür auch Seiten aus `geprueft_ohne_karte` (gesichtet, aber nichts Kartenwürdiges),
    # sonst würde die Auswahl für immer auf einer solchen Seite hängen bleiben.
    after_last_covered = max(covered) + 1 if covered else 1
    candidates = [
        page for page in all_pages
        if int(page["p"]) >= after_last_covered and int(page["p"]) not in covered and str(page.get("t", "")).strip()
    ]
    if not candidates:
        candidates = [page for page in all_pages if int(page["p"]) not in covered and str(page.get("t", "")).strip()]
    if not candidates:
        candidates = [page for page in all_pages if str(page.get("t", "")).strip()]
    return candidates[:max_pages]


def _load_source_package(fach: Fach, source_id: str, max_pages: int) -> SourcePackage:
    _, doc = find_document(source_id, fach.name)
    dossier_path = fach.dossiers / f"{doc['id']}.md"
    if not dossier_path.exists():
        raise SystemExit(f"Dossier fehlt: {_rel(dossier_path)}")
    dossier_meta, dossier_body = read_note(dossier_path)
    existing_cards: list[tuple[Path, dict[str, Any], str]] = []
    for path in karten_der_quelle(fach, doc["id"]):
        meta, body = read_note(path)
        existing_cards.append((path, meta, body))
    covered = _covered_pages(existing_cards) | _page_ranges(dossier_meta.get("geprueft_ohne_karte"))
    pages = _choose_pages(load_pages(doc["sha256"]), covered, max_pages)
    return SourcePackage(fach, doc, dossier_path, dossier_meta, dossier_body, existing_cards, pages)


def _next_sources(fach: Fach, limit: int, max_pages: int, match: str | None = None) -> list[SourcePackage]:
    packages: list[SourcePackage] = []
    for dossier in _partial_dossiers(fach):
        source_id = dossier.stem
        if match and match.lower() not in source_id.lower() and match.lower() not in dossier.read_text(encoding="utf-8").lower():
            continue
        packages.append(_load_source_package(fach, source_id, max_pages))
        if len(packages) >= limit:
            break
    return packages


def _taxonomy_excerpt(fach: Fach) -> str:
    tax = yaml.safe_load(fach.taxonomie.read_text(encoding="utf-8")) or {}
    fields = ["typen", "belegarten", "themen", "prinzipien", "kompetenzen", "materialtypen"]
    compact = {field: sorted((tax.get(field) or {}).keys()) for field in fields}
    return yaml.safe_dump(compact, allow_unicode=True, sort_keys=False)


def _cards_excerpt(cards: list[tuple[Path, dict[str, Any], str]]) -> str:
    parts = []
    for path, meta, body in cards:
        parts.append(
            "\n".join(
                [
                    f"### {_rel(path)}",
                    f"titel: {meta.get('titel', path.stem)}",
                    f"seite: {meta.get('seite', '')}",
                    f"kern: {meta.get('kern', '')}",
                    body[:1800],
                ]
            )
        )
    return "\n\n".join(parts) or "(keine vorhandenen Karten)"


def _pages_excerpt(pages: list[dict[str, Any]]) -> str:
    blocks = []
    for page in pages:
        text = str(page.get("t", "")).strip()
        if len(text) > 4500:
            text = text[:4500] + "\n[... gekürzt ...]"
        blocks.append(f"--- SEITE {page['p']} ---\n{text}")
    return "\n\n".join(blocks)


def _prompt(package: SourcePackage, *, max_cards: int) -> str:
    source_id = package.doc["id"]
    card_dir = package.fach.karten / NEU / source_id
    return textwrap.dedent(
        f"""
        Du erschließt eine lokale Wissensbasis für Mathematikdidaktik. Erzeuge aus dem Quellenpaket neue, belegbare Karten.

        Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, ohne Markdown-Zaun, ohne Erklärung.

        JSON-Schema, informell. `cards` ist eine Liste, die zwei verschiedene Kartenarten mischen darf,
        unterschieden durch `frontmatter.typ`: (1) eine normale Karte (jeder `typ` außer `aufgabe`) — eine
        didaktische Aussage über die Quelle; (2) eine Aufgaben-Karte (`typ: aufgabe`) — eine vollständige,
        direkt einsetzbare Aufgabe (kein Fließtext über Aufgaben, sondern die Aufgabe selbst), die in
        `karten/aufgaben/` landet, nicht bei der Quelle. Beide Formen im Vergleich:

        {{
          "cards": [
            {{
              "slug": "03-kurzer-dateiname-ohne-md",
              "frontmatter": {{
                "titel": "...",
                "status": "entwurf",
                "kern": "ein knapper Satz",
                "nach": ["Autor 2008"],
                "quelle": "{source_id}",
                "quelle_hash": "{package.doc["sha256"]}",
                "typ": "unterrichtsidee",
                "belegart": "praxis",
                "seite": "10-13",
                "themen": ["modellieren"],
                "klassenstufen": [5, 6],
                "prinzipien": ["realitaetsbezug"],
                "kompetenzen": ["modellieren"],
                "zitat": ["kurzes exakt im OCR vorkommendes Fragment"]
              }},
              "sections": {{
                "Aussage": "...",
                "Planung": "...",
                "Prüffrage": "..."
              }}
            }},
            {{
              "slug": "kurzer-thematischer-dateiname-ohne-nummer",
              "frontmatter": {{
                "titel": "...",
                "status": "entwurf",
                "typ": "aufgabe",
                "materialtypen": ["einstieg"],
                "quellen": [{{"quelle": "{source_id}", "seite": "10-13"}}],
                "themen": ["bruchzahlen"],
                "klassenstufen": [7, 8],
                "prinzipien": ["grundvorstellungen"]
              }},
              "sections": {{
                "Aufgabe": "vollständiger Aufgabentext in reinem Markdown, Formeln als Inline-LaTeX ($\\\\frac{{1}}{{8}}$)",
                "Ziel": "welche Grundvorstellung/Kompetenz wird aktiviert oder geprüft",
                "Einsatz": "Sozialform, Zeitpunkt, Lehrerinterventionen",
                "Variationen": "optional: Varianten für andere Klassenstufen/Schwierigkeitsgrade",
                "Hinweise": "optional: typische Schülerantworten, häufige Fehler"
              }},
              "qmd": "## Grundaufgabe\\n\\n...\\n\\n---\\n\\n## Umkehraufgabe\\n\\n...\\n\\n---\\n\\n## Zunehmende Öffnung\\n\\n**a)** ...\\n**b)** ...\\n**c)** ...\\n\\n---\\n\\n## Variationen nach Klassenstufe\\n\\n**Klasse N – Thema:** ..."
            }}
          ],
          "dossier_update": {{
            "abdeckung": "teilweise",
            "abdeckung_text": "**Abdeckung:** ...",
            "fundstellen_text": "**Erschlossene Fundstellen:** ...",
            "geprueft_ohne_karte": ["48-52"]
          }}
        }}

        Regeln:
        - Erzeuge höchstens {max_cards} Karten.
        - Erzeuge eine normale Karte nur, wenn aus den Seiten eine echte, wiederverwendbare didaktische Aussage
          hervorgeht. Erzeuge eine Aufgaben-Karte nur, wenn die Seite eine konkrete, für sich einsetzbare Aufgabe
          zeigt (nicht nur eine Erwähnung oder Beschreibung einer Aufgabe).
        - Keine Dopplungen zu vorhandenen Karten.
        - `seite` bzw. `quellen[].seite` muss eine einzelne Seite oder zusammenhängende Spanne sein, z. B. "14" oder "14-16".
        - Bei normalen Karten muss jedes `zitat` exakt als kurzes Fragment im OCR-Text der angegebenen Seite/Spanne vorkommen.
        - Nutze nur Werte aus der Taxonomie (auch für `materialtypen`).
        - `Aussage` gibt die Quelle wieder; `Planung` und `Prüffrage` sind abgeleitete Praxisnutzen.
        - Bei Aufgaben-Karten: `qmd` folgt exakt der festen Abschnittsfolge Grundaufgabe/Umkehraufgabe/Zunehmende
          Öffnung/Variationen nach Klassenstufe, getrennt durch `---`; nicht sinnvolle Abschnitte weglassen.
          Reines Markdown, keine foerder-header-Kürzel. `## Variationen`/`## Hinweise` im `.md` sind optional,
          `## Aufgabe` und `## Ziel` sind Pflicht.
        - Dateinamen müssen neu sein. Zielordner für normale Karten: {_rel(card_dir)}; für Aufgaben-Karten:
          {_rel(package.fach.karten / "aufgaben")} (flacher, quellenunabhängiger Dateiname ohne Nummer-Präfix).
        - Dossiertexte dürfen den bisherigen Stand ersetzen, sollen aber ehrlich offen lassen, was noch nicht erschlossen ist.
        - `abdeckung` ist ein geschlossenes Feld mit genau diesen vier erlaubten Werten: "keine", "strukturell",
          "teilweise", "vollstaendig". Kein anderer Wert (z. B. "weitgehend") ist zulässig.
        - `geprueft_ohne_karte`: alle Seiten/Spannen aus QUELLENSEITEN, die du gesichtet hast, aber zu denen keine
          Karte entstand (z. B. Werbung, Register, Inhaltsverzeichnis, Wiederholung bereits kartierter Inhalte).
          Diese Seiten werden dauerhaft übersprungen, also nur Seiten eintragen, bei denen das gerechtfertigt ist.

        TAXONOMIE:
        {_taxonomy_excerpt(package.fach)}

        DOSSIER {_rel(package.dossier_path)}:
        ---
        {yaml.safe_dump(package.dossier_meta, allow_unicode=True, sort_keys=False).strip()}
        ---
        {package.dossier_body}

        VORHANDENE KARTEN:
        {_cards_excerpt(package.existing_cards)}

        QUELLENSEITEN:
        {_pages_excerpt(package.pages)}
        """
    ).strip() + "\n"


def _strip_json(text: str) -> str:
    text = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence:
        return fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def _run_llm(prompt: str, *, budget_usd: float | None = None) -> str:
    cmd = [STANDARD_LLM, "-p", "--output-format", "text", "--permission-mode", "dontAsk"]
    if budget_usd is not None:
        cmd += ["--max-budget-usd", str(budget_usd)]
    # Prompt via stdin, nicht als argv-Element: lange Quellenpakete (OCR-Text + Kartenliste)
    # überschreiten sonst in manchen Umgebungen das effektive ARG_MAX (trotz großzügigem
    # Limit, weil vererbte Umgebungsvariablen das Budget schon ausschöpfen können).
    result = subprocess.run(cmd, cwd=ROOT, input=prompt, check=True, text=True, capture_output=True)
    return result.stdout


def _dump_frontmatter(meta: dict[str, Any]) -> str:
    return yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=1000).strip()


def _card_text(frontmatter: dict[str, Any], sections: dict[str, str]) -> str:
    body_parts = []
    for heading in ("Aussage", "Beispiel", "Planung", "Prüffrage"):
        text = str(sections.get(heading, "")).strip()
        if text:
            body_parts.append(f"## {heading}\n\n{text}")
    return f"---\n{_dump_frontmatter(frontmatter)}\n---\n\n" + "\n\n".join(body_parts).strip() + "\n"


def _aufgabe_text(frontmatter: dict[str, Any], sections: dict[str, str]) -> str:
    body_parts = []
    for heading in ("Aufgabe", "Ziel", "Einsatz", "Variationen", "Hinweise"):
        text = str(sections.get(heading, "")).strip()
        if text:
            body_parts.append(f"## {heading}\n\n{text}")
    return f"---\n{_dump_frontmatter(frontmatter)}\n---\n\n" + "\n\n".join(body_parts).strip() + "\n"


def _aufgabe_qmd(title: str, name: str, body: str) -> str:
    # Header deterministisch bauen statt von der LLM zu verlangen: _metadata.yml im Ordner liefert
    # pdf-engine/Schriften, aber `title` fehlt sonst -> `\@title` undefiniert -> LaTeX-Fehler ab Seite 2.
    header = {"title": f"Aufgabe: {title}", "lang": "de", "fontsize": "10pt",
              "format": {"pdf": {"output-file": f"{name}.pdf"}}}
    comment = f"<!-- Aufgaben-Beispiel zu karten/aufgaben/{name}.md -->"
    return f"---\n{_dump_frontmatter(header)}\n---\n\n{comment}\n\n{body.strip()}\n"


def _aufgabe_filename(aufgaben_dir: Path, slug: str, title: str) -> str:
    base = slugify(re.sub(r"^\d+-", "", str(slug or "").removesuffix(".md").strip()) or title)
    name = base
    suffix = 2
    while (aufgaben_dir / f"{name}.md").exists() or (aufgaben_dir / f"{name}.qmd").exists():
        name = f"{base}-{suffix}"
        suffix += 1
    return name


def _existing_number_prefix(paths: list[Path]) -> int:
    maximum = 0
    for path in paths:
        match = re.match(r"(\d+)-", path.name)
        if match:
            maximum = max(maximum, int(match.group(1)))
    return maximum


def _normalise_slug(slug: str, title: str, number: int) -> str:
    slug = slug.removesuffix(".md").strip()
    slug = re.sub(r"^\d+-", "", slug)
    slug = slugify(slug or title)
    return f"{number:02d}-{slug}.md"


def _merge_list(existing: Any, additions: Any) -> list[Any]:
    result = list(as_list(existing))
    for value in as_list(additions):
        if value not in result:
            result.append(value)
    return result


def _update_dossier(package: SourcePackage, update: dict[str, Any], cards: list[dict[str, Any]]) -> None:
    meta = dict(package.dossier_meta)
    if update.get("abdeckung"):
        meta["abdeckung"] = update["abdeckung"]
    if update.get("geprueft_ohne_karte"):
        meta["geprueft_ohne_karte"] = _merge_list(meta.get("geprueft_ohne_karte"), update["geprueft_ohne_karte"])
    for field in ("themen", "prinzipien", "klassenstufen"):
        additions: list[Any] = []
        for card in cards:
            additions.extend(as_list((card.get("frontmatter") or {}).get(field)))
        meta[field] = _merge_list(meta.get(field), additions)
    body = package.dossier_body
    # Lambda statt String als Ersetzung: re.sub würde sonst Backslashes im LLM-Text
    # (z. B. aus LaTeX-Fragmenten) als Rückverweise wie \1 oder \s deuten und abstürzen.
    if update.get("abdeckung_text"):
        text = str(update["abdeckung_text"]).strip()
        body = re.sub(r"(?m)^\*\*Abdeckung:\*\*.*$", lambda _: text, body)
    if update.get("fundstellen_text"):
        text = str(update["fundstellen_text"]).strip()
        body = re.sub(r"(?m)^\*\*Erschlossene Fundstellen:\*\*.*$", lambda _: text, body)
    package.dossier_path.write_text(f"---\n{_dump_frontmatter(meta)}\n---\n\n{body.strip()}\n", encoding="utf-8")


def _apply_result(package: SourcePackage, result: dict[str, Any]) -> list[Path]:
    cards = list(result.get("cards") or [])
    written: list[Path] = []
    card_dir = package.fach.karten / NEU / package.doc["id"]  # wissen-pflegen nimmt auf und sortiert ein
    aufgaben_dir = package.fach.karten / "aufgaben"  # fester Ordner, wissen-sortieren rührt ihn nicht an
    number = _existing_number_prefix(karten_der_quelle(package.fach, package.doc["id"])) + 1
    for card in cards:
        fm = dict(card.get("frontmatter") or {})
        title = str(fm.get("titel") or card.get("slug") or "karte")
        fm.setdefault("status", "entwurf")
        if fm.get("typ") == "aufgabe":
            fm.setdefault("quellen", [{"quelle": package.doc["id"]}])
            aufgaben_dir.mkdir(parents=True, exist_ok=True)
            name = _aufgabe_filename(aufgaben_dir, str(card.get("slug") or ""), title)
            path = aufgaben_dir / f"{name}.md"
            path.write_text(_aufgabe_text(fm, dict(card.get("sections") or {})), encoding="utf-8")
            written.append(path)
            qmd = str(card.get("qmd") or "").strip()
            if qmd:
                qmd_path = aufgaben_dir / f"{name}.qmd"
                qmd_path.write_text(_aufgabe_qmd(title, name, qmd), encoding="utf-8")
                written.append(qmd_path)
            continue
        fm.setdefault("quelle", package.doc["id"])
        fm.setdefault("quelle_hash", package.doc["sha256"])
        card_dir.mkdir(parents=True, exist_ok=True)
        filename = _normalise_slug(str(card.get("slug") or ""), title, number)
        path = card_dir / filename
        while path.exists():
            number += 1
            filename = _normalise_slug(str(card.get("slug") or ""), title, number)
            path = card_dir / filename
        path.write_text(_card_text(fm, dict(card.get("sections") or {})), encoding="utf-8")
        written.append(path)
        number += 1
    if result.get("dossier_update"):
        _update_dossier(package, dict(result["dossier_update"]), cards)
        written.append(package.dossier_path)
    return written


def _render_check(paths: list[Path]) -> str:
    """Quarto-Sichttest für neue Aufgaben-Karten (.qmd); informativ, blockiert den Lauf nicht (wie bei Vorlagen)."""
    lines = []
    for path in [path for path in paths if path.suffix == ".qmd"]:
        result = subprocess.run(["invoke", "build", "--source", str(_rel(path))], cwd=ROOT, text=True, capture_output=True)
        status = "ok" if result.returncode == 0 else "FEHLER"
        lines.append(f"Sichttest {_rel(path)}: {status}")
        if result.returncode != 0:
            lines.append((result.stdout + result.stderr).strip()[-2000:])
    return "\n".join(lines)


def _run_check_build(fach: Fach, *, build: bool) -> tuple[int, str]:
    commands = [["invoke", "wissen-pflegen", "--fach", fach.name]]
    if build:
        commands.append(["invoke", "wissen-build", "--fach", fach.name])
    combined = []
    code = 0
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        combined.append(result.stdout)
        combined.append(result.stderr)
        if result.returncode != 0:
            code = result.returncode
            break
    return code, "\n".join(part for part in combined if part)


def run(
    fach_name: str = "mathematik",
    *,
    limit: int = 1,
    match: str | None = None,
    max_pages: int = 18,
    max_cards: int = 6,
    llm: bool = False,
    apply: bool = False,  # noqa: A002 - invoke flag name is intentionally user-facing
    build: bool = True,
    budget_usd: float | None = None,
    log=print,
) -> None:
    fach = discover(fach_name)[0]
    packages = _next_sources(fach, limit, max_pages, match)
    if not packages:
        log(f"[{fach.name}] keine passenden teilweise erschlossenen Dossiers gefunden")
        return
    run_dir = ARTEFAKT_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    log(f"Artefakte: {_rel(run_dir)}")
    for index, package in enumerate(packages, start=1):
        source_id = package.doc["id"]
        prompt = _prompt(package, max_cards=max_cards)
        prompt_path = run_dir / f"{index:02d}-{source_id}.prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        page_list = ", ".join(str(page["p"]) for page in package.pages)
        log(f"[{index}/{len(packages)}] {source_id}: Prompt mit Seiten {page_list} -> {_rel(prompt_path)}")
        if not llm:
            continue
        raw = _run_llm(prompt, budget_usd=budget_usd)
        response_path = run_dir / f"{index:02d}-{source_id}.response.json"
        response_path.write_text(raw, encoding="utf-8")
        log(f"  LLM-Antwort: {_rel(response_path)}")
        try:
            result = json.loads(_strip_json(raw))
        except json.JSONDecodeError as error:
            raise SystemExit(f"LLM-Antwort ist kein JSON ({response_path}): {error}") from error
        if not apply:
            log("  nicht angewendet (ohne --apply)")
            continue
        written = _apply_result(package, result)
        for path in written:
            log(f"  geschrieben: {_rel(path)}")
        code, output = _run_check_build(fach, build=build)
        check_path = run_dir / f"{index:02d}-{source_id}.check.txt"
        check_path.write_text(output, encoding="utf-8")
        log(output.strip())
        if code != 0:
            raise SystemExit(f"Validierung fehlgeschlagen; Details: {_rel(check_path)}")
        render_output = _render_check(written)
        if render_output:
            render_path = run_dir / f"{index:02d}-{source_id}.render.txt"
            render_path.write_text(render_output, encoding="utf-8")
            log(render_output.strip())
