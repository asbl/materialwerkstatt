"""Isolated Markdown preview shared by notes and plugin documents."""
from html import escape
import re

from markdown_it import MarkdownIt


def markdown_html(text, base="/", title=""):
    match = re.match(r"\A---\r?\n.*?\r?\n---(?:\r?\n|$)", text, re.S)
    if match:
        from material_ui.metadata import read_metadata
        try:
            title = read_metadata(text).get("title", title)
        except ValueError:
            pass
        text = text[match.end():]
    renderer = MarkdownIt("commonmark", {"html": False}).enable("table")
    return ('<!doctype html><html lang="de"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            'img-src \'self\' data:; style-src \'unsafe-inline\'; base-uri \'self\'">'
            f'<base href="{escape(base, quote=True)}">'
            '<style>body{color:#202124;background:#faf9f6;font:17px/1.7 system-ui,sans-serif;'
            'margin:0;padding:32px}main{max-width:800px;margin:auto;overflow-wrap:anywhere}'
            'h1,h2,h3{line-height:1.3}img{max-width:100%}pre{overflow:auto;padding:16px;background:#eee}'
            'code{font-size:.9em}blockquote{border-left:3px solid #aaa;margin-left:0;padding-left:20px}'
            'table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px 12px}'
            'a{color:#185abc}</style></head><body><main>'
            + (f'<h1>{escape(str(title))}</h1>' if title else '')
            + renderer.render(text) + '</main></body></html>')
