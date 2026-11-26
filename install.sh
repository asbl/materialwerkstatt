#!/usr/bin/env bash
# Installer fuer Material-UI und Werkzeuge (Linux). Legt Quellen und virtuelle Umgebung unter
# ~/.local/share/material-ui an; Systemprogramme (Quarto, TeX, Typst, ...) kommen vom System.
#
#   ./install.sh                    installieren oder aktualisieren
#   ./install.sh --nur-pruefen      nur System-Check, nichts veraendern
#   ./install.sh --system-pakete    fehlende Systempakete per sudo nachinstallieren (mit Rueckfrage)
#   ./install.sh --deinstallieren   Starter und Installationsordner entfernen
#
# Optionen: --prefix <dir>  --repo <url>  --ref <branch|tag>  --yes  --ohne-h5p  --ohne-playwright
set -euo pipefail

PREFIX="${MATERIAL_UI_PREFIX:-${XDG_DATA_HOME:-$HOME/.local/share}/material-ui}"
REPO="${MATERIAL_UI_REPO:-}"   # nur noetig, wenn das Skript nicht im Klon liegt
REF="${MATERIAL_UI_REF:-main}"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
ONLY_CHECK=0 SYSTEM_PACKAGES=0 UNINSTALL=0 ASSUME_YES=0 SETUP_FLAGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --nur-pruefen) ONLY_CHECK=1 ;;
    --system-pakete) SYSTEM_PACKAGES=1 ;;
    --deinstallieren) UNINSTALL=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --ohne-h5p) SETUP_FLAGS+=(--skip-h5p) ;;
    --ohne-playwright) SETUP_FLAGS+=(--skip-playwright) ;;
    --prefix) PREFIX="$2"; shift ;;
    --repo) REPO="$2"; shift ;;
    --ref) REF="$2"; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n== %s\n' "$*"; }
die() { printf 'Fehler: %s\n' "$*" >&2; exit 1; }

if [ "$UNINSTALL" = 1 ]; then
  say "Deinstallation"
  [ -L "$BIN_DIR/material-ui" ] && rm -f "$BIN_DIR/material-ui" && echo "Starter entfernt."
  rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/material-ui.desktop"
  if [ -d "$PREFIX" ]; then
    read -r -p "$PREFIX loeschen (Quellen und venv)? [j/N] " answer
    [ "$answer" = j ] && rm -rf "$PREFIX" && echo "Entfernt."
  fi
  exit 0
fi

# 1. Quellen: laeuft das Skript im Klon, wird dieser verwendet; sonst klonen oder aktualisieren.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ] && [ -f "$SCRIPT_DIR/src/material_core/systemcheck.py" ]; then
  SRC="$SCRIPT_DIR"
else
  SRC="$PREFIX/src"
fi

# Python fuer den Check: der erste Interpreter ab 3.12.
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1 \
     && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"; break
  fi
done

run_check() { "${PYTHON:-python3}" "$SRC/src/material_core/systemcheck.py" "$@"; }

if [ ! -f "$SRC/src/material_core/systemcheck.py" ]; then
  [ -n "$REPO" ] || die "Repository-URL fehlt: --repo <url> oder MATERIAL_UI_REPO setzen (oder das Skript im Klon starten)."
  command -v git >/dev/null 2>&1 || die "git fehlt (Arch: sudo pacman -S git, Debian/Ubuntu: sudo apt install git)."
  say "Hole Quellen nach $SRC"
  mkdir -p "$PREFIX"
  git clone --branch "$REF" "$REPO" "$SRC"
elif [ "$SRC" = "$PREFIX/src" ]; then
  say "Aktualisiere Quellen in $SRC"
  git -C "$SRC" fetch --quiet origin "$REF" && git -C "$SRC" checkout --quiet "$REF" && git -C "$SRC" pull --ff-only --quiet
fi

# 2. System-Check
say "System-Check"
[ -n "$PYTHON" ] || echo "Python 3.12 oder neuer wurde nicht gefunden."
CHECK_STATUS=0
run_check || CHECK_STATUS=$?
[ "$ONLY_CHECK" = 1 ] && exit "$CHECK_STATUS"

if [ "$CHECK_STATUS" != 0 ] && [ "$SYSTEM_PACKAGES" = 1 ]; then
  COMMAND="$(run_check --befehl || true)"
  if [ -n "$COMMAND" ]; then
    say "Systempakete installieren"
    echo "  $COMMAND"
    if [ "$ASSUME_YES" = 1 ]; then answer=j; else read -r -p "Ausfuehren? [j/N] " answer; fi
    if [ "$answer" = j ]; then eval "$COMMAND" || echo "Installation teilweise fehlgeschlagen." >&2; fi
    # Nach der Installation kann ein anderes Python vorhanden sein.
    for candidate in python3.14 python3.13 python3.12 python3; do
      if command -v "$candidate" >/dev/null 2>&1 \
         && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
        PYTHON="$(command -v "$candidate")"; break
      fi
    done
  fi
fi
[ -n "$PYTHON" ] || die "Python 3.12 oder neuer fehlt. Mit --system-pakete nachinstallieren oder manuell einrichten."
"$PYTHON" -c 'import venv, ensurepip' 2>/dev/null || die "venv/ensurepip fehlt (Debian/Ubuntu: sudo apt install python3-venv python3-pip)."

# 3. Virtuelle Umgebung und Paket
say "Richte virtuelle Umgebung ein ($PREFIX/venv)"
mkdir -p "$PREFIX"
[ -x "$PREFIX/venv/bin/python" ] || "$PYTHON" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
"$PREFIX/venv/bin/pip" install --quiet -e "$SRC"

# 4. Projekt einrichten (.env, H5P-Libraries, Playwright-Browser) und Doctor
say "Projekt einrichten"
( cd "$SRC" && "$PREFIX/venv/bin/inv" setup "${SETUP_FLAGS[@]}" ) || echo "Setup meldete Hinweise (siehe oben)." >&2

# 5. Starter
say "Starter"
mkdir -p "$BIN_DIR"
ln -sf "$PREFIX/venv/bin/material-ui" "$BIN_DIR/material-ui"
( cd "$SRC" && "$PREFIX/venv/bin/inv" material-ui-install ) || echo "Desktop-Starter nicht angelegt." >&2
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "Hinweis: $BIN_DIR ist nicht im PATH." ;; esac

say "Fertig"
echo "Starten:        material-ui"
echo "System pruefen: $PREFIX/venv/bin/inv doctor   (oder: $0 --nur-pruefen)"
echo "Aktualisieren:  $0   (erneut ausfuehren)"
