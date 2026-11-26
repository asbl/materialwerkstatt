"""Excalideck: Markdown-Outlines zu Excalidraw-Decks (inv deck)."""

from __future__ import annotations

from excalideck.generator import DeckExistsError, generate_deck
from excalideck.outline import Block, BoxBlock, DeckOutline, ImageBlock, Slide, TextBlock, parse_outline
from excalideck.printable import PrintableExistsError, generate_printable

__all__ = [
    "Block",
    "BoxBlock",
    "DeckExistsError",
    "DeckOutline",
    "ImageBlock",
    "PrintableExistsError",
    "Slide",
    "TextBlock",
    "generate_deck",
    "generate_printable",
    "parse_outline",
]
