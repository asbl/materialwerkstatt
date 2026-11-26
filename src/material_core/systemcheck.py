#!/usr/bin/env python3
"""System-Check: welche Programme sind vorhanden, was fehlt und wie installiert man es.

Reine Standardbibliothek, damit der Check vor `pip install` laeuft (z. B. aus `install.sh`):

    python3 src/material_core/systemcheck.py            # Bericht
    python3 src/material_core/systemcheck.py --befehl   # nur der Installationsbefehl
    python3 src/material_core/systemcheck.py --json     # maschinenlesbar
    python3 src/material_core/systemcheck.py --pakete   # nur die Paketnamen (z. B. fuer PKGBUILD)

Stufen: `basis` (ohne geht nichts), `bauen` (PDF-Build), `empfohlen`, `optional`.
Der Exit-Code ist 1, wenn Programme der Stufen `basis` oder `bauen` fehlen.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

MANAGERS = ("pacman", "apt", "dnf", "zypper")
REQUIRED_LEVELS = ("basis", "bauen")
LEVELS = ("basis", "bauen", "empfohlen", "optional")

# Je Eintrag: Schluessel, Stufe, Programme (eines genuegt), Zweck, Pakete je Paketmanager,
# Hinweis fuer Fremdquellen. Fehlt ein Manager in `pakete`, ist das Programm dort nicht
# gepackt und `hinweis` nennt den Weg.
TOOLS: list[dict] = [
    {
        "key": "python",
        "level": "basis",
        "binaries": ["python3"],
        "purpose": "Laufzeit (3.11 oder neuer)",
        "packages": {"pacman": ["python"], "apt": ["python3"], "dnf": ["python3"], "zypper": ["python3"]},
        "hint": "https://www.python.org/downloads/",
    },
    {
        "key": "venv",
        "level": "basis",
        "binaries": [],
        "module": "venv",
        "purpose": "virtuelle Umgebung (python3 -m venv) und ensurepip",
        "packages": {"apt": ["python3-venv", "python3-pip"], "pacman": ["python-pip"], "dnf": ["python3-pip"], "zypper": ["python3-pip"]},
    },
    {
        "key": "git",
        "level": "basis",
        "binaries": ["git"],
        "purpose": "Quellen holen und aktualisieren",
        "packages": {m: ["git"] for m in MANAGERS},
    },
    {
        "key": "quarto",
        "level": "bauen",
        "binaries": [os.environ.get("QUARTO", "quarto")],
        "purpose": "Markdown/QMD zu PDF rendern",
        "packages": {},
        "aur": ["quarto-cli-bin"],
        "hint": "https://quarto.org/docs/get-started/ (Arch: AUR quarto-cli-bin)",
    },
    {
        "key": "pdflatex",
        "level": "bauen",
        "binaries": [os.environ.get("PDFLATEX", "pdflatex")],
        "purpose": "LaTeX-Vorlagen und Klausuren",
        "packages": {
            "pacman": ["texlive-basic", "texlive-latex", "texlive-latexrecommended", "texlive-fontsrecommended"],
            "apt": ["texlive-latex-base", "texlive-latex-recommended", "texlive-fonts-recommended"],
            "dnf": ["texlive-latex", "texlive-collection-latexrecommended", "texlive-collection-fontsrecommended"],
            "zypper": ["texlive-latex", "texlive-collection-latexrecommended", "texlive-collection-fontsrecommended"],
        },
    },
    {
        "key": "rsvg-convert",
        "level": "bauen",
        "binaries": ["rsvg-convert"],
        "purpose": "SVG zu PDF (Skizzen, Einheitskreis)",
        "packages": {"pacman": ["librsvg"], "apt": ["librsvg2-bin"], "dnf": ["librsvg2-tools"], "zypper": ["rsvg-convert"]},
    },
    {
        "key": "pdftocairo",
        "level": "bauen",
        "binaries": [os.environ.get("PDFTOCAIRO", "pdftocairo")],
        "purpose": "TikZ-Assets zu SVG (poppler)",
        "packages": {"pacman": ["poppler"], "apt": ["poppler-utils"], "dnf": ["poppler-utils"], "zypper": ["poppler-tools"]},
    },
    {
        "key": "typst",
        "level": "empfohlen",
        "binaries": ["typst"],
        "purpose": "Typst-Vorlagen (Arbeitsblaetter, Folien)",
        "packages": {"pacman": ["typst"], "dnf": ["typst"], "zypper": ["typst"]},
        "hint": "https://github.com/typst/typst/releases (Debian/Ubuntu: Release-Binary oder cargo install typst-cli)",
    },
    {
        "key": "lualatex",
        "level": "empfohlen",
        "binaries": ["lualatex"],
        "purpose": "LuaLaTeX-Vorlagen mit eigenen Schriften",
        "packages": {
            "pacman": ["texlive-luatex"],
            "apt": ["texlive-luatex"],
            "dnf": ["texlive-luatex"],
            "zypper": ["texlive-luatex"],
        },
    },
    {
        "key": "qpdf",
        "level": "empfohlen",
        "binaries": ["qpdf"],
        "purpose": "PDF-Nachbearbeitung",
        "packages": {m: ["qpdf"] for m in MANAGERS},
    },
    {
        "key": "browser",
        "level": "empfohlen",
        "binaries": ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome"],
        "purpose": "Material-UI als eigenes App-Fenster (sonst Standardbrowser)",
        "packages": {"pacman": ["chromium"], "apt": ["chromium"], "dnf": ["chromium"], "zypper": ["chromium"]},
        "hint": "Ubuntu: apt install chromium-browser bzw. Snap/Flatpak",
    },
    {
        "key": "node",
        "level": "optional",
        "binaries": ["node", "npx"],
        "purpose": "markdownlint, Editor-Bundle und Excalideck neu bauen",
        "packages": {m: ["nodejs", "npm"] for m in MANAGERS},
    },
    {
        "key": "pandoc",
        "level": "optional",
        "binaries": ["pandoc"],
        "purpose": "Import von Office-Dateien",
        "packages": {"pacman": ["pandoc-cli"], "apt": ["pandoc"], "dnf": ["pandoc"], "zypper": ["pandoc"]},
    },
    {
        "key": "libreoffice",
        "level": "optional",
        "binaries": ["libreoffice", "soffice"],
        "purpose": "Import von Office-Dateien",
        "packages": {"pacman": ["libreoffice-fresh"], "apt": ["libreoffice"], "dnf": ["libreoffice"], "zypper": ["libreoffice"]},
    },
    {
        "key": "tesseract",
        "level": "optional",
        "binaries": ["tesseract"],
        "purpose": "OCR in der Wissensbasis",
        "packages": {"pacman": ["tesseract", "tesseract-data-deu"], "apt": ["tesseract-ocr", "tesseract-ocr-deu"],
                     "dnf": ["tesseract", "tesseract-langpack-deu"], "zypper": ["tesseract-ocr", "tesseract-ocr-traineddata-german"]},
    },
    {
        "key": "ghostscript",
        "level": "optional",
        "binaries": ["gs"],
        "purpose": "PDFs der Wissensbasis komprimieren",
        "packages": {m: ["ghostscript"] for m in MANAGERS},
    },
    {
        "key": "imagemagick",
        "level": "optional",
        "binaries": ["magick", "convert"],
        "purpose": "Bildkonvertierung beim Import",
        "packages": {m: ["imagemagick"] for m in MANAGERS},
    },
    {
        "key": "notify-send",
        "level": "optional",
        "binaries": ["notify-send"],
        "purpose": "Desktop-Benachrichtigungen",
        "packages": {"pacman": ["libnotify"], "apt": ["libnotify-bin"], "dnf": ["libnotify"], "zypper": ["libnotify-tools"]},
    },
    {
        "key": "xdotool",
        "level": "optional",
        "binaries": ["xdotool"],
        "purpose": "Fenster in den Vordergrund holen (X11)",
        "packages": {m: ["xdotool"] for m in MANAGERS},
    },
    {
        "key": "bwrap",
        "level": "optional",
        "binaries": ["bwrap"],
        "purpose": "Sandbox fuer Chat-Werkzeuge",
        "packages": {"pacman": ["bubblewrap"], "apt": ["bubblewrap"], "dnf": ["bubblewrap"], "zypper": ["bubblewrap"]},
    },
]


def detect_manager() -> str | None:
    """Paketmanager der Distribution (ueber os-release, sonst ueber vorhandene Programme)."""
    ids: list[str] = []
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key in {"ID", "ID_LIKE"}:
                ids.extend(value.strip().strip('"').lower().split())
    except OSError:
        pass
    by_id = {
        "arch": "pacman", "manjaro": "pacman", "endeavouros": "pacman",
        "debian": "apt", "ubuntu": "apt", "linuxmint": "apt", "pop": "apt",
        "fedora": "dnf", "rhel": "dnf", "centos": "dnf",
        "opensuse": "zypper", "suse": "zypper", "sles": "zypper",
    }
    for distro in ids:
        for prefix, manager in by_id.items():
            if distro.startswith(prefix):
                return manager
    return next((m for m in MANAGERS if shutil.which(m)), None)


def _python_ok() -> tuple[bool, str]:
    found = next((shutil.which(n) for n in ("python3.14", "python3.13", "python3.12", "python3.11", "python3") if shutil.which(n)), None)
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    return sys.version_info >= (3, 11), f"{found or sys.executable} (laeuft unter {version})"


def check_tools() -> list[dict]:
    """Ergebnisliste: je Werkzeug `ok`, gefundener Pfad und die uebrigen Felder aus TOOLS."""
    results = []
    for tool in TOOLS:
        entry = dict(tool)
        found = None
        if tool["key"] == "python":
            ok, found = _python_ok()
        elif tool.get("module"):
            ok = importlib.util.find_spec("venv") is not None and importlib.util.find_spec("ensurepip") is not None
            found = "venv + ensurepip" if ok else None
        else:
            path = next((shutil.which(b) for b in tool["binaries"] if shutil.which(b)), None)
            ok, found = path is not None, path
        entry["ok"] = ok
        entry["found"] = found
        results.append(entry)
    return results


def missing(results: list[dict], levels: tuple[str, ...] = LEVELS) -> list[dict]:
    return [r for r in results if not r["ok"] and r["level"] in levels]


def install_plan(results: list[dict], manager: str | None, levels: tuple[str, ...] = LEVELS) -> dict:
    """Pakete je Manager fuer alles Fehlende; Fremdquellen (AUR, Download) getrennt."""
    packages: list[str] = []
    aur: list[str] = []
    manual: list[tuple[str, str]] = []
    for entry in missing(results, levels):
        names = entry.get("packages", {}).get(manager or "", [])
        if names:
            packages.extend(n for n in names if n not in packages)
        elif manager == "pacman" and entry.get("aur"):
            aur.extend(n for n in entry["aur"] if n not in aur)
        else:
            manual.append((entry["key"], entry.get("hint", "kein Paket bekannt")))
    return {"manager": manager, "packages": packages, "aur": aur, "manual": manual}


def install_command(plan: dict) -> str:
    manager, packages = plan["manager"], plan["packages"]
    if not packages or not manager:
        return ""
    verbs = {
        "pacman": "sudo pacman -S --needed",
        "apt": "sudo apt install",
        "dnf": "sudo dnf install",
        "zypper": "sudo zypper install",
    }
    return f"{verbs[manager]} {' '.join(shlex.quote(p) for p in packages)}"


def report(results: list[dict], manager: str | None, levels: tuple[str, ...] = ("basis", "bauen", "empfohlen")) -> str:
    lines = [f"Paketmanager: {manager or 'unbekannt'}", ""]
    labels = {"basis": "Basis", "bauen": "PDF-Build", "empfohlen": "Empfohlen", "optional": "Optional"}
    for level in LEVELS:
        lines.append(f"{labels[level]}:")
        for r in (r for r in results if r["level"] == level):
            state = "ok" if r["ok"] else ("FEHLT" if level in REQUIRED_LEVELS else "fehlt")
            detail = r["found"] if r["ok"] else r["purpose"]
            lines.append(f"  [{state:>5}] {r['key']:<13} {detail}")
        lines.append("")
    plan = install_plan(results, manager, levels)
    command = install_command(plan)
    if command:
        lines += ["Fehlendes ueber das System installieren:", f"  {command}"]
    if plan["aur"]:
        lines.append(f"  AUR (z. B. mit yay/paru): {' '.join(plan['aur'])}")
    for key, hint in plan["manual"]:
        lines.append(f"  {key}: {hint}")
    if not (command or plan["aur"] or plan["manual"]):
        lines.append("Nichts zu installieren.")
    if "optional" not in levels and missing(results, ("optional",)):
        lines.append("Optionale Programme fehlen; mit --alles in den Befehl aufnehmen.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="Ergebnis als JSON ausgeben")
    parser.add_argument("--befehl", action="store_true", help="nur den Installationsbefehl ausgeben")
    parser.add_argument("--pakete", action="store_true", help="nur die fehlenden Paketnamen ausgeben")
    parser.add_argument("--alles", action="store_true", help="Befehl auch fuer optionale Programme (Standard: ohne Stufe optional)")
    parser.add_argument("--manager", choices=MANAGERS, help="Paketmanager erzwingen (Standard: erkennen)")
    args = parser.parse_args(argv)

    manager = args.manager or detect_manager()
    results = check_tools()
    levels = LEVELS if args.alles else ("basis", "bauen", "empfohlen")
    plan = install_plan(results, manager, levels)
    if args.json:
        print(json.dumps({"manager": manager, "tools": [
            {k: r[k] for k in ("key", "level", "ok", "found", "purpose")} for r in results
        ], "plan": plan}, ensure_ascii=False, indent=2))
    elif args.befehl:
        print(install_command(plan))
    elif args.pakete:
        print(" ".join(plan["packages"]))
    else:
        print(report(results, manager, levels))
    return 1 if missing(results, REQUIRED_LEVELS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
