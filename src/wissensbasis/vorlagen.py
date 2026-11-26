"""Vorlagen: reusable task templates written in the LaTeX shorthand of the Fördermaterial (foerder-header.tex).

`check` validates them (tags, pages, sections, every LaTeX command, linked worksheets, copied source examples),
`build` renders all examples into one catalogue PDF with the real header, like doku/zeichnungen-katalog.qmd.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import ROOT, Fach
from .notes import STATUS_VALUES, Note, as_list, load_templates, parse_pages, sections

GENERATED = "generiert von wissensbasis (invoke wissen-vorlagen-build); nicht von Hand ändern"
BUILD_DIR = "build"
CATALOGUE = "vorlagen-katalog.qmd"
LATEX_BLOCK = re.compile(r"```latex\n(.*?)\n```", re.DOTALL)
OLD_BLOCK = re.compile(r"```markdown\n")
COMMAND = re.compile(r"\\([A-Za-z]+)")
ENVIRONMENT = re.compile(r"\\begin\{([A-Za-z*]+)\}")
DEFINITION = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|NewDocumentCommand|DeclareDocumentCommand|def)\*?\{?\\([A-Za-z]+)"
)
ENV_DEFINITION = re.compile(r"\\(?:newenvironment|renewenvironment|NewDocumentEnvironment|newtcolorbox)\{([A-Za-z*]+)\}")
TEMPLATE_REQUIRED = ["titel", "status", "format", "quelle", "belege", "themen", "klassenstufen", "modell", "kuerzel"]
TEMPLATE_SECTIONS = ["Muster", "Umsetzung", "Variationen", "Lehrerfragen"]
TAG_FIELDS = {"themen": "themen", "prinzipien": "prinzipien", "format": "formate", "modell": "modelle"}
# Binary expressions like 47+29, 18\cdot15, 6{,}03-5{,}97 in an example; compared against the source text.
EXPRESSION = re.compile(r"(\d+(?:\{?,\}?\d+)?)\s*(\+|-|\\cdot|:)\s*(\d+(?:\{?,\}?\d+)?)")
SOURCE_OPERATORS = {"+": r"\+", "-": r"[-—–]", "\\cdot": r"[xX×·*]", ":": r"[+÷:/]"}
MIN_EXPRESSION_DIGITS = 4  # 4+3 is everywhere; only flag expressions with at least this many digits


@dataclass(frozen=True)
class Sprache:
    """What a template may use: commands and environments of the header files plus plain LaTeX."""
    header_commands: set[str]
    header_environments: set[str]
    allowed_commands: set[str]
    allowed_environments: set[str]
    basic_environments: set[str]
    preview_headers: list[Path]


def load_language(fach: Fach) -> Sprache | None:
    path = fach.wissen / "_config" / "vorlagen.yaml"
    if not path.exists():
        return None
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    header = ROOT / str(config.get("kuerzel_header", ""))
    previews = [ROOT / str(item) for item in as_list(config.get("vorschau_header"))]
    header_commands: set[str] = set()
    header_environments: set[str] = set()
    extra_commands: set[str] = set()
    extra_environments: set[str] = set()
    for file in {header, *previews}:
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8")
        commands, environments = set(DEFINITION.findall(text)), set(ENV_DEFINITION.findall(text))
        if file == header:
            header_commands |= commands
            header_environments |= environments
        extra_commands |= commands
        extra_environments |= environments
    basic_environments = {str(item) for item in as_list(config.get("latex_umgebungen"))}
    return Sprache(
        header_commands=header_commands,
        header_environments=header_environments,
        allowed_commands=extra_commands | {str(item) for item in as_list(config.get("latex_basis"))},
        allowed_environments=extra_environments | basic_environments,
        basic_environments=basic_environments,
        preview_headers=previews,
    )


def latex_blocks(template: Note) -> list[str]:
    return [block.strip() for block in LATEX_BLOCK.findall(template.body) if block.strip()]


def _shorthand(block: str, sprache: Sprache) -> tuple[set[str], set[str]]:
    """(header shorthands used, unknown commands/environments) of one LaTeX block."""
    environments = set(ENVIRONMENT.findall(block))
    commands = set(COMMAND.findall(block)) - {"begin", "end"}
    used = (commands & sprache.header_commands) | (environments & sprache.header_environments - sprache.basic_environments)
    unknown = {f"\\{name}" for name in commands - sprache.allowed_commands}
    unknown |= {f"{{{name}}}" for name in environments - sprache.allowed_environments}
    return used, unknown


def _number(text: str) -> str:
    return text.replace("{,}", ",").replace(",", "[.,]")


def _normalized(expression: str) -> str:
    return re.sub(r"\s+", "", expression.replace("{,}", ",").replace("\\cdot", "·").replace("*", "·"))


def _copied(text: str, source_text: str) -> list[str]:
    """Expressions of the template that also stand in the source (OCR writes × as x, ÷ as +)."""
    found = []
    for left, operator, right in EXPRESSION.findall(text):
        if len(re.sub(r"\D", "", left + right)) < MIN_EXPRESSION_DIGITS:
            continue
        pattern = rf"(?<![\d.,]){_number(left)}\s*{SOURCE_OPERATORS[operator]}\s*{_number(right)}(?![\d])"
        if re.search(pattern, source_text):
            found.append(f"{left.replace('{,}', ',')} {operator.replace(chr(92) + 'cdot', '·')} {right.replace('{,}', ',')}")
    return found


def check(fach: Fach, taxonomy: dict, docs: dict, pages_of) -> tuple[list[str], list[str]]:
    """(errors, warnings) for all templates; `pages_of(doc)` returns the page texts of a source."""
    errors: list[str] = []
    warnings: list[str] = []
    sprache = load_language(fach)
    templates = load_templates(fach, errors)
    if templates and sprache is None:
        errors.append(f"{fach.wissen.name}/_config/vorlagen.yaml fehlt (Sprache der Vorlagen)")
    for template in templates:
        name = template.path.relative_to(fach.wissen).as_posix()
        meta = template.meta
        for key in TEMPLATE_REQUIRED:
            if not meta.get(key):
                errors.append(f"{name}: Feld '{key}' fehlt")
        if meta.get("status") and meta["status"] not in STATUS_VALUES:
            errors.append(f"{name}: status '{meta['status']}' unbekannt (erlaubt: {', '.join(sorted(STATUS_VALUES))})")
        for key, group in TAG_FIELDS.items():
            for value in as_list(meta.get(key)):
                if value not in (taxonomy.get(group) or {}):
                    errors.append(f"{name}: '{value}' steht nicht in taxonomie.yaml ({group})")
        if template.path.parent.name != template.dok:
            errors.append(f"{name}: liegt nicht im Ordner der Quelle '{template.dok}'")
        if not (fach.dossiers / f"{template.dok}.md").exists():
            errors.append(f"{name}: kein Dossier quellen/{template.dok}.md")

        doc = docs.get(template.dok)
        pages = pages_of(doc) if doc else []
        if doc is None:
            errors.append(f"{name}: Quelle '{template.dok}' nicht im Manifest")
        for beleg in as_list(meta.get("belege")):
            if not isinstance(beleg, dict) or not beleg.get("seite") or not beleg.get("fokus"):
                errors.append(f"{name}: jeder Beleg braucht 'seite' und 'fokus'")
                continue
            try:
                start, end = parse_pages(beleg["seite"])
            except ValueError as error:
                errors.append(f"{name}: {error}")
                continue
            if doc is not None and not 1 <= start <= end <= len(pages):
                errors.append(f"{name}: Beleg-Seite {beleg['seite']} außerhalb 1–{len(pages)}")

        parts = sections(template.body)
        for section in TEMPLATE_SECTIONS:
            if section not in parts:
                errors.append(f"{name}: Abschnitt '## {section}' fehlt")
        for section in parts:
            if section not in TEMPLATE_SECTIONS:
                errors.append(f"{name}: unbekannter Abschnitt '## {section}'")
        if OLD_BLOCK.search(template.body):
            errors.append(f"{name}: ```markdown-Block mit alter Shortcut-Syntax; Beispiele als ```latex mit den Kürzeln schreiben")
        blocks = latex_blocks(template)
        if not blocks:
            errors.append(f"{name}: kein ```latex-Block mit Beispielaufgaben im Abschnitt '## Umsetzung'")

        if sprache is not None and blocks:
            used: set[str] = set()
            for block in blocks:
                block_used, unknown = _shorthand(block, sprache)
                used |= block_used
                for item in sorted(unknown):
                    errors.append(f"{name}: {item} ist weder Kürzel des Headers noch in latex_basis/latex_umgebungen")
            listed = {str(item) for item in as_list(meta.get("kuerzel"))}
            if used - listed:
                warnings.append(f"{name}: 'kuerzel' fehlt {', '.join(sorted(used - listed))}")
            if listed - used:
                warnings.append(f"{name}: 'kuerzel' nennt {', '.join(sorted(listed - used))}, im Beispiel nicht benutzt")

        for path in as_list(meta.get("umsetzungen")):
            if not (ROOT / str(path)).is_file():
                errors.append(f"{name}: Umsetzung {path} existiert nicht")

        if pages:
            allowed = {_normalized(str(item)) for item in as_list(meta.get("uebernommen"))}
            copied = sorted(hit for hit in set(_copied(template.body, " ".join(pages))) if _normalized(hit) not in allowed)
            if copied:
                warnings.append(f"{name}: Beispiel steht so auch in der Quelle ({'; '.join(copied)}), eigene Zahlen wählen")
    return errors, warnings


def _catalogue(fach: Fach, templates: list[Note], sprache: Sprache | None, output_dir: Path) -> str:
    headers = [os.path.relpath(path, output_dir) for path in (sprache.preview_headers if sprache else [])]
    lines = [
        "---",
        f'title: "Vorlagen-Katalog {fach.name}"',
        "lang: de",
        "fontsize: 9pt",
        "format:",
        "  pdf:",
        "    pdf-engine: lualatex",
        "    mainfont: TeX Gyre Heros",
        "    sansfont: TeX Gyre Heros",
        "    monofont: TeX Gyre Cursor",
        "    include-in-header:",
        *[f"      - {header}" for header in headers],
        "---",
        "",
        f"<!-- {GENERATED} -->",
        "",
        "\\small",
        f"\\begin{{mathedeckblatt}}{{Vorlagen-Katalog {fach.name}}}{{}}",
        "\\end{mathedeckblatt}",
        "",
        "\\lernbox{Jede Vorlage aus \\texttt{wissen/" + fach.name + "/vorlagen/} mit ihren Beispielen, gerendert mit dem "
        "Header des Fördermaterials. Der Katalog ist der Sichttest: Was hier falsch aussieht, sieht auch im Arbeitsblatt falsch aus.}",
        "",
    ]
    for template in templates:
        meta = template.meta
        belege = ", ".join(f"S. {beleg.get('seite')}" for beleg in as_list(meta.get("belege")) if isinstance(beleg, dict))
        info = (f"Format: {meta.get('format', '')} · Modelle: {', '.join(str(m) for m in as_list(meta.get('modell')))} · "
                f"Klasse {'/'.join(str(k) for k in as_list(meta.get('klassenstufen')))} · Quelle: {template.dok}, {belege} · "
                f"Umsetzungen im Fördermaterial: {len(as_list(meta.get('umsetzungen')))}")
        lines += ["\\newpage", "", f"# {template.titel}", "", "```{=latex}",
                  "\\hinweisbox{\\footnotesize " + info.replace("_", "\\_").replace("%", "\\%") + "}", "```", ""]
        for block in latex_blocks(template):
            lines += ["```{=latex}", block, "```", "", "\\vspace{0.3cm}", ""]
    return "\n".join(lines) + "\n"


def build(fach: Fach, render: bool = True, log=print) -> tuple[list[Note], list[str]]:
    """Write build/vorlagen-katalog.qmd with every template's examples and (optionally) render it to PDF."""
    output_dir = fach.vorlagen / BUILD_DIR
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    problems: list[str] = []
    built: list[Note] = []
    for template in load_templates(fach, problems):
        if not latex_blocks(template):
            problems.append(f"{template.ref}: kein ```latex-Block mit Beispielaufgaben")
            continue
        built.append(template)
    catalogue = output_dir / CATALOGUE
    catalogue.write_text(_catalogue(fach, built, load_language(fach), output_dir), encoding="utf-8")
    if render and built:
        if shutil.which("quarto") is None:
            problems.append("quarto nicht gefunden, Katalog nur als .qmd geschrieben")
        else:
            log(f"[{fach.name}] rendere {catalogue.relative_to(ROOT)} …")
            result = subprocess.run(["quarto", "render", str(catalogue)], cwd=ROOT, capture_output=True, text=True)
            if result.returncode != 0:
                tail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-8:])
                problems.append(f"quarto render fehlgeschlagen:\n{tail}")
    return built, problems
