"""Source diagnostics for saved documents and unsaved editor snapshots."""
from __future__ import annotations

import re
from pathlib import Path

from material_core.conventions import check_conventions
from material_core.layout import check_layout
from material_ui.document_types import capabilities
from material_core.designs import template_slide_design
from material_core.template_roots import find_template
from material_core.builds import OUTPUT_ROOT, OUTPUT_ARTIFACT_DIR
from material_core.metadata import read_metadata, split_frontmatter, template_value



def position(text: str, offset: int) -> dict[str, int]:
    return {"line": text.count("\n", 0, offset) + 1,
            "column": offset - text.rfind("\n", 0, offset)}


class PreflightFailure(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("Rendern gesperrt: Bitte zuerst die Fehler der Vorprüfung beheben.")


def preflight(builds, source: Path, text: str) -> None:
    issues = document_issues(builds, source, text, preflight_only=True)
    if any(issue["level"] == "error" for issue in issues):
        raise PreflightFailure(issues)


def document_issues(builds, source: Path, text: str, *, preflight_only=False) -> list[dict]:
    issues = []

    def add(level, title, detail, offset=0, length=1):
        issues.append({"level": level, "title": title, "detail": detail,
                       **position(text, offset), "length": length})

    parts = split_frontmatter(text)
    metadata = {}
    valid_metadata = True
    if parts is None:
        if source.suffix == ".qmd" or re.match(r"\A(?:\ufeff)?---\s*\n", text):
            unfinished = bool(re.match(r"\A(?:\ufeff)?---[^\S\r\n]*\r?\n", text))
            add("error" if unfinished else "warning", "YAML-Header nicht geschlossen" if unfinished else "YAML-Header fehlt",
                "Der YAML-Header benötigt eine schließende --- Zeile." if unfinished else "Das Dokument enthält keinen YAML-Header.")
    else:
        try:
            metadata = read_metadata(text)
        except ValueError as error:
            valid_metadata = False
            mark = getattr(error.__cause__, "problem_mark", None)
            offset = len(parts.prefix) + mark.index if mark else len(parts.prefix)
            add("error", "YAML-Header ungültig", str(error), min(offset, len(text)))
        if valid_metadata and not metadata.get("title"):
            add("warning", "Titel fehlt", "Im YAML-Header wurde kein title-Feld gefunden.", len(parts.prefix))
        if valid_metadata:
            for field in ("title", "subject", "grade", "kind", "deck", "material-output"):
                if field in metadata and not isinstance(metadata[field], str):
                    match = re.search(rf"(?m)^{re.escape(field)}\s*:", text)
                    add("error", "Metadaten ungültig", f"{field} muss Text enthalten.", match.start() if match else 0)
    if not capabilities(source, text)["render"]:
        masked, structure = structure_issues(text)
        issues.extend(structure)
        issues.extend(missing_image_issues(source, masked))
        return issues or [{"level": "ok", "title": "Keine Auffälligkeiten", "detail": "Markdown und Frontmatter sind gültig."}]
    if "<!-- material-ui -->" not in text:
        add("info", "Einfügemarke fehlt", "Bilder werden ohne material-ui-Marker am Dokumentende eingefuegt.", len(text))
    pdf_path = None
    if valid_metadata:
        try:
            pdf_path = builds.find_pdf(source, text=text)
        except ValueError as error:
            add("error", "Ausgabepfad ungültig", str(error))
    if not preflight_only and valid_metadata and metadata.get("material-output") != "excalidraw":
        if not pdf_path:
            add("warning", "PDF fehlt", "Fuer diese QMD wurde keine passende PDF-Datei gefunden.")
        elif builds.pdf_is_current(source, text) is False or (builds.pdf_is_current(source, text) is None and (text != source.read_text(encoding="utf-8") or pdf_path.stat().st_mtime + 1 < source.stat().st_mtime)):
            add("warning", "PDF ist veraltet", "Die QMD wurde nach der PDF zuletzt geaendert.")
    if valid_metadata:
        template = template_value(text)
        if template and not resolve_relative(source, template).exists():
            match = re.search(r"(?m)^\s*template\s*:\s*[^\r\n]+", text)
            add("error", "Template nicht gefunden", f"Der Template-Pfad zeigt auf keine Datei: {template}", match.start() if match else 0)
    if not preflight_only and valid_metadata:
        enabled, _ = template_slide_design(text)
        rel = source.relative_to(builds.root)
        deck = builds.root / OUTPUT_ROOT / OUTPUT_ARTIFACT_DIR / rel.with_suffix('.excalidraw') if enabled else None
        issues.extend(check_layout(pdf_path, deck, slides=enabled))
    masked, structure = structure_issues(text)
    issues.extend(structure)
    issues.extend(missing_image_issues(source, masked))
    if not preflight_only:
        issues.extend(convention_issues(source, text))
    return issues or [{"level": "ok", "title": "Keine Auffälligkeiten", "detail": "Pfad, PDF, Bilder und Grundstruktur sehen gut aus."}]


CONVENTION_LIMIT = 5


def convention_issues(source: Path, text: str) -> list[dict]:
    """Material-Konventionen als Hinweise; sie sperren das Rendern nie.

    Wiederholungen derselben Regel werden gekappt, damit etwa viele
    Überschriften mit Trennpunkt die übrigen Prüfhinweise nicht verdrängen.
    """
    issues, counts = [], {}
    findings = check_conventions(source, text)
    totals = {}
    for finding in findings:
        totals[finding.code] = totals.get(finding.code, 0) + 1
    for finding in findings:
        counts[finding.code] = counts.get(finding.code, 0) + 1
        if counts[finding.code] > CONVENTION_LIMIT:
            continue
        rest = totals[finding.code] - CONVENTION_LIMIT
        detail = finding.detail
        if counts[finding.code] == CONVENTION_LIMIT and rest > 0:
            detail += f" ({rest} weitere Stelle{'n' if rest != 1 else ''} dieser Art im Dokument.)"
        issues.append({"level": finding.level, "code": finding.code, "title": finding.title, "detail": detail,
                       **position(text, finding.offset), "length": finding.length})
    return issues


def structure_issues(text: str) -> tuple[str, list[dict]]:
    """Conservative source checks; masking keeps offsets and line numbers intact."""
    issues = []

    def add(title, detail, offset, length=1):
        issues.append({"level": "error", "title": title, "detail": detail,
                       **position(text, offset), "length": length})

    def blank(value):
        return re.sub(r"[^\r\n]", " ", value)

    parts = split_frontmatter(text)
    start = len(text) - len(parts.body) if parts else 0
    masked = blank(text[:start]) + text[start:]
    masked = re.sub(r"<!--[\s\S]*?-->", lambda m: blank(m[0]), masked)
    fence = None
    lines = []
    offset = 0
    for line in masked.splitlines(keepends=True):
        match = re.match(r" {0,3}(`{3,}|~{3,})(.*)", line)
        if fence:
            marker, _, raw = fence
            if match and match[1][0] == marker[0] and len(match[1]) >= len(marker) and not match[2].strip():
                fence = None
                lines.append(blank(line))
            else:
                lines.append(re.sub(r"(?<!\\)%[^\r\n]*", lambda m: blank(m[0]), line) if raw else blank(line))
        elif match:
            fence = (match[1], offset + match.start(1), match[2].strip() == "{=latex}")
            lines.append(blank(line))
        else:
            lines.append(line)
        offset += len(line)
    if fence:
        add("Codeblock nicht geschlossen", f"Der Block benötigt eine schließende Zeile mit {fence[0]}.", fence[1], len(fence[0]))
    masked = re.sub(r"(?m)^\s*%[^\r\n]*", lambda m: blank(m[0]), "".join(lines))
    masked = re.sub(r"(`+)[^`\n]*?\1", lambda m: blank(m[0]), masked)
    # Only display math is unambiguous: single dollars can also denote currency.
    math = None
    for match in re.finditer(r"(?<![\\$])\$\$(?!\$)", masked):
        math = match.start() if math is None else None
    if math is not None:
        add("Formel nicht geschlossen", "Der Formelblock benötigt ein schließendes $$.", math, 2)
    stack = []
    for match in re.finditer(r"(?<!\\)\\(begin|end)\{([^}\n]+)\}", masked):
        name = match[2]
        if match[1] == "begin":
            stack.append((name, match.start(), len(match[0])))
        elif not stack or stack[-1][0] != name:
            add("LaTeX-Umgebung falsch geschlossen", f"Kein passendes \\begin{{{name}}} an dieser Stelle.", match.start(), len(match[0]))
        else:
            stack.pop()
    for name, offset, length in stack:
        add("LaTeX-Umgebung nicht geschlossen", f"Es fehlt \\end{{{name}}}.", offset, length)
    return masked, issues


def resolve_relative(source: Path, value: str) -> Path:
    path = Path(value)
    resolved = (path if path.is_absolute() else source.parent / path).resolve()
    if not resolved.exists():
        builtin = find_template(path.name)
        if builtin is not None:
            return builtin
    return resolved


def missing_image_issues(source: Path, text: str) -> list[dict]:
    issues = []
    # Keep actual match offsets: repeated filenames must point to their own occurrence.
    for pattern in (r"!\[[^\]]*]\(([^)]+)\)", r"\\includegraphics(?:\[[^\]]*])?\{([^}]+)\}"):
        for match in re.finditer(pattern, text):
            raw = match.group(1).strip()
            if re.match(r"^[a-z]+://", raw) or raw.startswith("#") or raw.startswith("data:"):
                continue
            # Markdown permits <paths with spaces> and an optional quoted title.
            if raw.startswith("<") and ">" in raw:
                raw = raw[1:raw.index(">")]
            else:
                raw = re.split(r'\s+["\']', raw, maxsplit=1)[0]
            clean = raw.split("#", 1)[0].split("?", 1)[0].strip()
            resolved = resolve_relative(source, clean)
            # Managed builds generate SVG assets from local TikZ sources first.
            generated = resolved.suffix == ".svg" and resolved.parent == source.parent / "assets" and resolved.with_suffix(".tex").is_file()
            if clean and not resolved.exists() and not generated:
                issues.append({"level": "error", "title": "Bild fehlt", "detail": f"Nicht gefunden: {clean}",
                               **position(text, match.start(1)), "length": len(match.group(1))})
    return issues
