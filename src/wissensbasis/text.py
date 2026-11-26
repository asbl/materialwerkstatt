from __future__ import annotations

import re
import unicodedata

QUOTE_TRANSLATION = str.maketrans(
    {"„": '"', "“": '"', "”": '"', "»": '"', "«": '"', "‚": "'", "‘": "'", "’": "'", "–": "-", "—": "-"}
)


LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"})


def fix_ligatures(text: str) -> str:
    return text.translate(LIGATURES)


def clean_page(text: str) -> str:
    """Light normalisation that keeps line breaks (readable when a page is shown)."""
    text = fix_ligatures(text).replace("\xad", "").replace("\r", "")
    text = re.sub(r"(?<=[a-zäöüß])-\n(?=[a-zäöüß])", "", text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def flat(text: str) -> str:
    """Single-line form used for the search index."""
    return re.sub(r"\s+", " ", text).strip()


def match_form(text: str) -> str:
    """Form used to check that a quote really occurs on a page."""
    text = unicodedata.normalize("NFC", text).translate(QUOTE_TRANSLATION).lower()
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)
    return re.sub(r"[\s\"'*_]+", "", text)


def slugify(text: str, limit: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text.replace("ß", "ss"))
    text = text.encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:limit].strip("-") or "dokument"


REFERENCE_ENTRY = re.compile(r"\((?:19|20)\d{2}[a-z]?\)\s*[:.,]")
REFERENCE_MIN_ENTRIES = 4


def is_reference_page(text: str) -> bool:
    """Bibliography pages: many 'Autor (Jahr):' style entries. Used to rank such pages last in searches."""
    return len(REFERENCE_ENTRY.findall(text)) >= REFERENCE_MIN_ENTRIES
