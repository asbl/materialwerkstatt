"""Verhindert neue rohe LaTeX/Typst-Konstrukte in Unterrichtsmaterial.

Prüft, dass niemand (auch kein KI-Agent) statt eines Markdown-Shortcuts aus
src/quarto/filters/exam.lua rohes {=latex}/{=typst}, \\newcommand/\\newenvironment,
\\begin{tikzpicture} oder \\input{...} direkt in neues Material schreibt. Bestehende
Vorkommen sind in einer Basislinie erfasst (siehe BASELINE_PATH); die Zahl darf pro
Datei nicht wachsen. Die Basislinie liegt bewusst in den privaten Inhaltsrepos
(unterricht/, foerdermaterial/), nicht in diesem Werkzeugrepo, da sie Dateipfade aus
dort referenziert.

Baseline aktualisieren, nachdem rohes LaTeX/Typst bewusst durch einen Shortcut ersetzt
wurde (Zahl sinkt) oder ein neuer, geprüfter Ausnahmefall entstanden ist:
    python3 src/tests/test_no_raw_latex_shortcuts.py --update-baseline
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOTS = ["unterricht", "foerdermaterial"]
BASELINE_PATH = Path("unterricht/.raw-latex-baseline.json")

PATTERNS = {
    "raw_format": re.compile(r"\{=(?:latex|typst)\}"),
    "newcommand": re.compile(r"\\(?:re)?newcommand\{"),
    "newenvironment": re.compile(r"\\(?:re)?newenvironment\{"),
    "tikzpicture": re.compile(r"\\begin\{tikzpicture\}"),
    "raw_input": re.compile(r"\\input\{"),
}

HINT = (
    "Rohes LaTeX/Typst statt Markdown-Shortcut gefunden. Bitte einen bestehenden "
    "Shortcut aus src/quarto/filters/exam.lua verwenden (siehe docs/klausur-syntax.md) "
    "oder dort einen neuen Shortcut bauen bzw. einen bestehenden erweitern (z. B. um "
    "farben=/kommentar=-Parameter), statt {=latex}/{=typst}-Rohbloecke, "
    "\\newcommand/\\newenvironment-Makros, \\begin{tikzpicture} oder \\input{...} "
    "direkt im Material zu schreiben."
)

EXCLUDED_PATH_PARTS = ("/.material-history/", "/_eingang/")


def strip_frontmatter(text):
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[end + 4 :]
    return text


def scan_file(path):
    text = path.read_text(encoding="utf-8")
    body = strip_frontmatter(text)
    return sum(len(pattern.findall(body)) for pattern in PATTERNS.values())


def current_counts():
    counts = {}
    for root in ROOTS:
        base = Path(root)
        if not base.is_dir():
            continue
        for qmd in sorted(base.rglob("*.qmd")):
            posix = qmd.as_posix()
            if any(part in posix for part in EXCLUDED_PATH_PARTS):
                continue
            n = scan_file(qmd)
            if n:
                counts[posix] = n
    return counts


def load_baseline():
    if not BASELINE_PATH.is_file():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.mark.skipif(not Path("unterricht").is_dir(), reason="unterricht/ nicht ausgecheckt")
def test_no_new_raw_latex_outside_baseline():
    baseline = load_baseline()
    current = current_counts()
    problems = [
        f"{path}: {count} Vorkommen (Basislinie erlaubt {baseline.get(path, 0)})"
        for path, count in sorted(current.items())
        if count > baseline.get(path, 0)
    ]
    assert not problems, HINT + "\n\nBetroffene Dateien:\n" + "\n".join(problems)


if __name__ == "__main__":
    if "--update-baseline" in sys.argv:
        counts = current_counts()
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(
            json.dumps(counts, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Basislinie geschrieben: {BASELINE_PATH} ({len(counts)} Dateien)")
    else:
        print("Nutzung: python3 src/tests/test_no_raw_latex_shortcuts.py --update-baseline")
