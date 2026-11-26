#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/build"
LOG_FILE="$LOG_DIR/build-qmds.log"

if [[ ! -t 1 && "${BUILD_QMDS_IN_TERMINAL:-0}" != "1" ]]; then
  for terminal in x-terminal-emulator gnome-terminal konsole xfce4-terminal mate-terminal; do
    if command -v "$terminal" >/dev/null 2>&1; then
      case "$terminal" in
        gnome-terminal|mate-terminal|xfce4-terminal)
          BUILD_QMDS_IN_TERMINAL=1 "$terminal" -- bash "$0"
          ;;
        konsole)
          BUILD_QMDS_IN_TERMINAL=1 "$terminal" -e bash "$0"
          ;;
        *)
          BUILD_QMDS_IN_TERMINAL=1 "$terminal" -e bash "$0"
          ;;
      esac
      exit 0
    fi
  done
fi

mkdir -p "$LOG_DIR"
exec > >(tee "$LOG_FILE") 2>&1

echo "Baue alle .qmd-Dateien in:"
echo "$SCRIPT_DIR"
echo

if ! command -v quarto >/dev/null 2>&1; then
  echo "FEHLER: quarto wurde nicht gefunden."
  echo "Installiere Quarto oder stelle sicher, dass 'quarto' im PATH liegt."
  read -r -p "Enter zum Schliessen..." _
  exit 127
fi

if ! command -v invoke >/dev/null 2>&1; then
  echo "FEHLER: invoke wurde nicht gefunden."
  echo "Installiere invoke, damit Build-Artefakte nach build/ und PDFs nach pdf/ verschoben werden."
  read -r -p "Enter zum Schliessen..." _
  exit 127
fi

PROJECT_ROOT="$SCRIPT_DIR"
while [[ "$PROJECT_ROOT" != "/" && ! -f "$PROJECT_ROOT/_quarto.yml" ]]; do
  PROJECT_ROOT="$(dirname -- "$PROJECT_ROOT")"
done

if [[ ! -f "$PROJECT_ROOT/_quarto.yml" ]]; then
  PROJECT_ROOT="$SCRIPT_DIR"
fi

mapfile -d '' QMD_FILES < <(
  find "$SCRIPT_DIR" -maxdepth 1 -type f -name '*.qmd' ! -name '*-old.qmd' -print0 | sort -z
)

if (( ${#QMD_FILES[@]} == 0 )); then
  echo "Keine .qmd-Dateien in diesem Ordner gefunden."
  read -r -p "Enter zum Schliessen..." _
  exit 0
fi

cd "$PROJECT_ROOT" || exit 1

FAILED=0
for qmd in "${QMD_FILES[@]}"; do
  if [[ "$PROJECT_ROOT" == "$SCRIPT_DIR" ]]; then
    source_path="./$(basename -- "$qmd")"
  else
    source_path="${qmd#"$PROJECT_ROOT"/}"
  fi

  echo "==> invoke build --source $source_path"
  if ! invoke build --source "$source_path"; then
    echo "FEHLER beim Bauen von: $source_path"
    FAILED=1
  fi
  echo
done

if (( FAILED == 0 )); then
  echo "Fertig: LaTeX-Artefakte liegen in build/, PDFs in pdf/."
else
  echo "Fertig mit Fehlern. Details stehen in:"
  echo "$LOG_FILE"
fi

read -r -p "Enter zum Schliessen..." _
exit "$FAILED"
