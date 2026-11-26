from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "unterricht/mathematik/klasse-05/materialgestaltung/foerdermaterial-vorlagen/foerder-header.tex"
NUMERACY_HEADER = ROOT / "unterricht/mathematik/klasse-05/materialgestaltung/numeracy-modelle/numeracy-modelle.tex"
pytestmark = pytest.mark.skipif(
    not HEADER.is_file() or not NUMERACY_HEADER.is_file(),
    reason="Private LaTeX-Beispiele fehlen",
)


PREAMBLE = r"""
\documentclass{article}
\usepackage[a4paper,margin=2cm]{geometry}
\usepackage{xcolor}
\usepackage{tikz}
\usepackage{tabularx}
\usepackage{array}
\usepackage{enumitem}
\usepackage{multicol}
\usepackage{fancyvrb}
\usepackage{needspace}
\usepackage[most]{tcolorbox}
\usepackage{fancyhdr}
\usepackage{etoolbox}
\usepackage{xstring}
\usepackage{pdflscape}
\usepackage{fontspec}
\usepackage{unicode-math}
\usepackage[nobottomtitles*]{titlesec}
\usepackage{colortbl}
\usetikzlibrary{calc}
\newcommand{\headingfont}{\sffamily}
\newif\ifexamshownameheader
\examshownameheadertrue
\newenvironment{mathedeckblatt}[2]{}{}
\newcommand{\antwortkasten}[1]{}
\newcommand{\answergrid}[3]{}
\newcommand{\platz}[1][1.5cm]{\colorbox{gray!15}{\makebox[#1]{\rule{0pt}{0.45cm}}}}
"""


@pytest.mark.skipif(shutil.which("lualatex") is None, reason="lualatex ist nicht installiert")
@pytest.mark.parametrize(
    ("name", "body"),
    [
        (
            "positive_auto_labels",
            r"""
            \begin{zahlenstrich}{1280}{1815}
            \markierung(1280)
            \markierung(1300)
            \markierung(1800)
            \markierung(1815)
            \pfeil(1280)(1300)
            \pfeil(1300)(1800)
            \pfeil(1800)(1815)
            \end{zahlenstrich}
            """,
        ),
        (
            "negative_auto_label",
            r"""
            \begin{zahlenstrich}{55}{123}
            \markierung(55)
            \markierung(78)
            \markierung(123)
            \pfeil(123)(78)
            \pfeil[][draw=pxgreen](78)(55)
            \end{zahlenstrich}
            """,
        ),
        (
            "custom_labels_and_width",
            r"""
            \begin{zahlenstrich}[8.5]{987}{1002}
            \markierung(987)
            \markierung[1\,000](1000)
            \markierung(1002)
            \pfeil[$+13$](987)(1000)
            \pfeil[$+2$][draw=pxgreen](1000)(1002)
            \end{zahlenstrich}
            """,
        ),
        (
            "raw_tikz_escape_hatch",
            r"""
            \begin{zahlenstrich}{0}{10}
            \markierung[Start](0)
            \markierung[Ziel][below=4mm](10)
            \pfeil(0)(10)
            \rohTikZ{\node[px note] at (3.6,0.8) {Detail};}
            \end{zahlenstrich}
            """,
        ),
    ],
)
def test_zahlenstrich_latex_syntax_compiles(tmp_path: Path, name: str, body: str) -> None:
    tex = tmp_path / f"{name}.tex"
    tex.write_text(
        textwrap.dedent(
            rf"""
            {PREAMBLE}
            \input{{{HEADER.as_posix()}}}
            \begin{{document}}
            {body}
            \end{{document}}
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["lualatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert tex.with_suffix(".pdf").exists()


@pytest.mark.skipif(shutil.which("lualatex") is None, reason="lualatex ist nicht installiert")
@pytest.mark.parametrize(
    ("name", "body"),
    [
        (
            "streifenmodell_parts_and_braces",
            r"""
            \begin{streifenmodell}[0.15]
            \bteil{0}{18}{px bar b}{18}
            \bteil{18}{30}{px bar d}{12}
            \bteil{30}{50}{px bar c}{Rest}
            \bgesamt{0}{50}{Taschengeld: 50}
            \bunter{0}{30}{zusammen weg: $18+12=30$}
            \end{streifenmodell}
            """,
        ),
        (
            "streifenmodell_placeholders",
            r"""
            \begin{streifenmodell}[1.25]
            \foreach \i in {0,...,4}{\bplatz{\i}{\i+1}{px bar c}\bbeschr{\i+0.5}{Beet \the\numexpr\i+1\relax}}
            \bgesamt{0}{5}{60 Zwiebeln}
            \end{streifenmodell}
            """,
        ),
        (
            "streifenfrei",
            r"""
            \streifenfrei[0.1]{60}{10}
            """,
        ),
    ],
)
def test_streifenmodell_latex_syntax_compiles(tmp_path: Path, name: str, body: str) -> None:
    tex = tmp_path / f"{name}.tex"
    tex.write_text(
        textwrap.dedent(
            rf"""
            {PREAMBLE}
            \input{{{HEADER.as_posix()}}}
            \begin{{document}}
            {body}
            \end{{document}}
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["lualatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert tex.with_suffix(".pdf").exists()


@pytest.mark.skipif(shutil.which("lualatex") is None, reason="lualatex ist nicht installiert")
@pytest.mark.parametrize(
    ("name", "body"),
    [
        (
            "flaechenmodell_parts",
            r"""
            \begin{flaechenmodell}[0.2][0.15]
            \fteil{0}{0}{10}{12}{px bar}{$120$}
            \fteil{10}{0}{16}{12}{px bar b}{$72$}
            \foben{5}{12}{10}\foben{13}{12}{6}\flinks{0}{6}{12}
            \end{flaechenmodell}
            """,
        ),
        (
            "zahlenstrichgruppe_two_rows",
            r"""
            \begin{zahlenstrichgruppe}[0.08]{130}
            \zahlenzeile{Kette}
            \zmarkierung(55)\zmarkierung(78)\zmarkierung(123)
            \zpfeil(123)(78)
            \zpfeil[][draw=pxgreen](78)(55)
            \zahlenzeile{Klammer}
            \zmarkierung(55)\zmarkierung(123)
            \zpfeil[$-68$ auf einmal][draw=pxorange](123)(55)
            \end{zahlenstrichgruppe}
            """,
        ),
        (
            "zahlenstrichgruppe_empty_rows",
            r"""
            \begin{zahlenstrichgruppe}[0.08]{130}
            \zahlenzeile{Kette}\zfreiheit
            \zmarkierung(60)\zmarkierung(85)\zmarkierung(130)
            \zahlenzeile{Klammer}\zfreiheit
            \zmarkierung(60)\zmarkierung(130)
            \end{zahlenstrichgruppe}
            """,
        ),
        (
            "restzahlenstrahl",
            r"""
            \restzahlenstrahl{83}{27}{noch übrig?}
            """,
        ),
    ],
)
def test_flaechenmodell_and_zahlenstrichgruppe_compile(tmp_path: Path, name: str, body: str) -> None:
    tex = tmp_path / f"{name}.tex"
    tex.write_text(
        textwrap.dedent(
            rf"""
            {PREAMBLE}
            \input{{{HEADER.as_posix()}}}
            \begin{{document}}
            {body}
            \end{{document}}
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["lualatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert tex.with_suffix(".pdf").exists()


def test_foerdermaterial_qmd_uses_drawing_shortcuts_instead_of_raw_tikz() -> None:
    base = ROOT / "unterricht/mathematik/klasse-05"
    catalogue = base / "materialgestaltung/foerdermaterial-vorlagen/zeichnungen-katalog.qmd"
    sources = [catalogue, *base.glob("*/foerderkurs-*/*.qmd"),
               *base.glob("lernstandsdiagnose/arithmetische-grundlagen/foerdermaterial/*/*/*.qmd")]
    found = []
    catalogue_examples = 0
    for path in sorted(sources):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if r"\begin{tikzpicture}" in line:
                if path == catalogue:
                    catalogue_examples += 1
                else:
                    found.append(f"{path.relative_to(base)}:{line_no}")
    assert not found, "Neue rohe TikZ-Blöcke statt Zeichenkürzeln: " + ", ".join(found)
    assert catalogue_examples == 2, "Die zwei dokumentierten Detailbeispiele im Katalog prüfen."


@pytest.mark.skipif(shutil.which("lualatex") is None, reason="lualatex ist nicht installiert")
def test_numeracy_model_shortcuts_compile(tmp_path: Path) -> None:
    tex = tmp_path / "numeracy_modelle.tex"
    tex.write_text(
        textwrap.dedent(
            rf"""
            {PREAMBLE}
            \definecolor{{examprimary}}{{HTML}}{{1565C0}}
            \definecolor{{examprimarylight}}{{HTML}}{{DCE8F8}}
            \input{{{NUMERACY_HEADER.as_posix()}}}
            \begin{{document}}
            \begin{{modellzahlenstrich}}[5]{{38}}{{43}}
            \mmarkierung(38)
            \mmarkierung(43)
            \mpfeil(38)(43)
            \mabstand(38)(43){{$5$}}
            \end{{modellzahlenstrich}}

            \begin{{modellflaeche}}[0.2][0.15]
            \mteil[fill=examprimarylight]{{0}}{{0}}{{10}}{{12}}{{120}}
            \mteil[dashed,fill=red!8]{{10}}{{0}}{{16}}{{12}}{{72}}
            \moben{{5}}{{12}}{{10}}
            \mlinks{{0}}{{6}}{{12}}
            \end{{modellflaeche}}

            \begin{{modellzuordnung}}
            \mzknoten{{0}}{{-0.6}}{{Start}}
            \mzlabel{{0.6}}{{Kisten}}
            \mzlabel{{0}}{{Wert}}
            \mzkopf{{1}}{{1}}
            \mzkopf{{2}}{{100}}
            \mzwert{{1}}{{27}}
            \mzwert{{2}}{{2700}}
            \mzschritt{{1.25}}{{1.75}}{{$\times100$}}
            \end{{modellzuordnung}}

            \begin{{modellflaechefrei}}
            \mteil{{0}}{{0}}{{8}}{{3}}{{$3\cdot8$}}
            \mteil{{10}}{{0}}{{14}}{{6}}{{$6\cdot4$}}
            \end{{modellflaechefrei}}
            \end{{document}}
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["lualatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert tex.with_suffix(".pdf").exists()


def test_build_powerful_numeracy_templates_use_model_shortcuts() -> None:
    base = ROOT / "wissen/mathematik/vorlagen/build-powerful-numeracy"
    found: list[tuple[str, int]] = []
    for path in sorted(base.rglob("*.md")):
        rel = path.relative_to(base).as_posix()
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if r"\begin{tikzpicture}" in line:
                found.append((rel, line_no))

    assert not found, (
        "Neue rohe tikzpicture-Blöcke in build-powerful-numeracy gefunden. "
        "Bitte die Modellkürzel aus ZEICHNEN.md/Vorlagen-README benutzen: "
        + ", ".join(f"{path}:{line}" for path, line in found)
    )


def test_numeracy_worksheets_use_model_shortcuts() -> None:
    base = ROOT / "unterricht/mathematik/klasse-05"
    found: list[tuple[str, int]] = []
    for path in sorted(base.glob("*/numeracy-modelle/*.qmd")):
        if not path.is_file() or ".material-history" in path.parts:
            continue
        rel = path.relative_to(base).as_posix()
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if r"\begin{tikzpicture}" in line:
                found.append((rel, line_no))

    assert not found, (
        "Numeracy-Blätter sollen Modellkürzel statt rohem TikZ verwenden: "
        + ", ".join(f"{path}:{line}" for path, line in found)
    )


def test_rechenstrategien_uses_model_shortcuts_for_number_lines() -> None:
    path = ROOT / "unterricht/mathematik/klasse-05/rechenstrategien/rechenstrich/ab_rechenstrategien.qmd"
    found = [
        line_no
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if r"\begin{tikzpicture}" in line
    ]

    assert not found, (
        "Rechenstrategien soll fuer Rechenstriche die Modellkürzel statt rohem TikZ verwenden: "
        + ", ".join(str(line) for line in found)
    )
