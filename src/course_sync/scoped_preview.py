"""Startet die lokale Vorschau fuer genau einen Kurs.

`course_sync.main serve` bereitet beim Start alle lokalen Kurse vor, bevor der
Server ueberhaupt antwortet (siehe main.prepare_preview_runtime(None)). Fuer
eine einzelne Kurs-Vorschau (z.B. aus der Material-UI heraus) ist das
unnoetig langsam. Dieses Modul ruft dieselbe serve_preview-Implementierung
auf, beschraenkt die Vorbereitung aber auf den angegebenen Kurs.
"""

from __future__ import annotations

import argparse
import sys

from course_sync.classes.cli.preview_server import serve_preview
from course_sync.application import get_application

application = get_application()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("course", help="Kurs-Slug, z.B. python-2026")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)

    course_dir = application.COURSES_DIR / args.course
    if not course_dir.is_dir():
        print(f"Kurs nicht gefunden: {args.course}", file=sys.stderr)
        return 1

    serve_preview(
        args.port,
        courses_dir=application.COURSES_DIR,
        runtime_proxy_prefix=application.RUNTIME_PROXY_PREFIX,
        h5p_runtime_port=application.H5P_RUNTIME_PORT,
        ensure_h5p_runtime_server=application.ensure_h5p_runtime_server,
        load_course_preview_state=application.load_course_preview_state,
        preview_controller=application.preview_controller,
        resolve_runtime_question_from_path=application.resolve_runtime_question_from_path,
        ensure_runtime_question_ready=application.ensure_runtime_question_ready,
        rewrite_runtime_html=application.rewrite_runtime_html,
        escape_inline=application.escape_inline,
        start_runtime_question_preparation=application.start_runtime_question_preparation,
        rebuild_runtime_question=application.rebuild_runtime_question,
        prepare_preview_runtime=lambda: application.prepare_preview_runtime(course_dir),
        template_renderer=application.template_renderer,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
