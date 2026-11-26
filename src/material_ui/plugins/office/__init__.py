"""Office-Plugin: DOCX-Import mit LibreOffice und Pandoc.

Stellt dem Plugin `importe` das Interface `docx-converter` bereit; `inv import-onlyoffice`
nutzt `converter` direkt. Ab Werk aus, damit LibreOffice und Pandoc nur braucht, wer DOCX importiert.
"""
from __future__ import annotations


class DocxConverter:
    def to_pdf(self, source, output_dir):
        from . import converter

        return converter._convert_docx_to_pdf(source, output_dir)

    def to_markdown(self, source, cwd, media_rel):
        from . import converter

        return converter.extract_markdown(source, cwd, media_rel)


def register(ctx) -> None:
    ctx.register_service("docx-converter", DocxConverter())
