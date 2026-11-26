from __future__ import annotations

import os
import sys


MANAGED_RENDER_VARIABLE = "MATERIAL_BUILD_MANAGED"


def managed_render_environment() -> dict[str, str]:
    return {**os.environ, MANAGED_RENDER_VARIABLE: "1"}


def main() -> int:
    if os.environ.get(MANAGED_RENDER_VARIABLE) == "1":
        return 0
    print(
        "Direktes Quarto-Rendern ist in diesem Projekt gesperrt.\n"
        "Bitte inv build --source <pfad.qmd>, make <pfad.qmd> oder die Material-UI verwenden.\n"
        "Fuer die Vorschau: inv preview --source <pfad.qmd>.\n"
        "Diese Wege sortieren erzeugte PDFs nach build/pdf/ und weitere Artefakte nach build/artefakte/.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
