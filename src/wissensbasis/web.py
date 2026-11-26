"""Webquellen: eine Seite als lesbare Kopie in ressourcen/quellen/<fach>/web/<host>/<slug>.md ablegen.

Die Kopie ist die Quelle der Wahrheit. Alles Weitere (Text, Suchindex, Dossier, Karten, Zitatprüfung) läuft wie bei
einem PDF, denn `.md` ist ein bekanntes Format; die Fundstelle einer Karte ist dann ein Abschnitt der Kopie.
Eine erneute Abholung schreibt die Datei nur, wenn sich der Inhalt geändert hat: sonst bliebe kein Hash stabil und
jedes Dossier gälte nach kurzer Zeit als veraltet.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .config import Fach
from .text import slugify

USER_AGENT = "Mozilla/5.0 (compatible; wissensbasis; Lesekopie für Unterrichtsvorbereitung)"
TIMEOUT = 30
MAX_BYTES = 20_000_000
WEB_FOLDER = "web"

FRONTMATTER = re.compile(r"\A---\n.*?\n---\n(.*)\Z", re.DOTALL)

# Beiwerk, das auf fast jeder Seite steht und in einer Quelle nur stört.
SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg",
             "button", "select", "iframe", "template", "dialog"}
# Wortweiser Vergleich (nicht Teilzeichenkette): sonst fällt `<body class="no-sidebars">` als Beiwerk aus.
SKIP_WORDS = {"nav", "navigation", "menu", "menus", "breadcrumb", "breadcrumbs", "sidebar", "sidebars", "footer",
              "cookie", "consent", "social", "share", "sharing", "search", "skip", "skiplink", "banner", "toolbar",
              "masthead", "pager", "pagination"}
NEGATIONS = ("no-", "not-", "without-")
ROOT_TAGS = {"html", "body", "main", "article"}
VOID_TAGS = {"br", "img", "hr", "meta", "link", "input", "source", "col", "area", "base", "embed", "param", "track", "wbr"}
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "section", "article", "blockquote", "figcaption", "table", "dt", "dd"}
HEADINGS = {f"h{level}": "#" * min(level, 6) for level in range(1, 7)}
EMPHASIS = {"strong", "b"}


class _Markdown(HTMLParser):
    """Wandelt eine Seite in schlichtes Markdown: Überschriften, Listen, Fettes und Links bleiben erhalten."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.title = ""
        self._open: list[str] = []
        self._skip_from: int | None = None
        self._in_title = False
        self._link: str | None = None

    # -- Hilfen ---------------------------------------------------------------
    @property
    def _skipping(self) -> bool:
        return self._skip_from is not None

    def _is_noise(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in SKIP_TAGS:
            return True
        if tag in ROOT_TAGS:
            return False
        for key, value in attrs:
            if key not in {"class", "id"} or not value:
                continue
            for token in value.lower().split():
                if token.startswith(NEGATIONS):
                    continue
                if any(word in SKIP_WORDS for word in re.split(r"[-_]+", token)):
                    return True
        return False

    # -- HTMLParser -----------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
            return
        if tag not in VOID_TAGS:
            self._open.append(tag)
        if self._skipping:
            return
        if self._is_noise(tag, attrs):
            self._skip_from = len(self._open) - (0 if tag in VOID_TAGS else 1)
            return
        if tag in HEADINGS:
            self.parts.append(f"\n\n{HEADINGS[tag]} ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in EMPHASIS:
            self.parts.append("**")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            self._link = self._absolute(href)
            if self._link:
                self.parts.append("[")
        elif tag in {"td", "th"}:
            self.parts.append(" · " if self.parts and not self.parts[-1].endswith("\n") else "")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        if tag in VOID_TAGS:
            return
        if tag in self._open:
            while self._open and self._open.pop() != tag:
                pass
        if self._skipping:
            if len(self._open) <= self._skip_from:
                self._skip_from = None
            return
        if tag in HEADINGS or tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in EMPHASIS:
            self.parts.append("**")
        elif tag == "a" and self._link:
            self.parts.append(f"]({self._link})")
            self._link = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skipping:
            self.parts.append(data.replace("[", "(").replace("]", ")") if self._link else data)

    def _absolute(self, href: str) -> str | None:
        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "data:")):
            return None
        return urljoin(self.base_url, href)


def _tidy(parts: list[str]) -> list[str]:
    text = "".join(parts).replace("\xa0", " ")
    text = re.sub(r"\*\*\s*\*\*", "", text)          # leer gebliebene Auszeichnung
    text = re.sub(r"\[\s*\]\([^)]*\)", "", text)     # Links ohne Text (Bilder, Icons)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line not in {"", "-", "·"}]
    return [line for number, line in enumerate(lines) if number == 0 or line != lines[number - 1]]


def _page_title(raw_title: str, lines: list[str], url: str) -> str:
    """Der <title> trägt meist noch den Seitennamen; der Teil vor dem Trenner genügt."""
    title = re.split(r"\s+[|–—·]\s+", " ".join(raw_title.split()))[0].strip()
    if not title:
        heading = next((line for line in lines if line.startswith("# ")), "")
        title = heading.removeprefix("# ").strip() or urlparse(url).path.rsplit("/", 1)[-1] or url
    return title


def fetch(url: str) -> tuple[bytes, str]:
    """Seite holen; gibt Inhalt und die endgültige URL nach Weiterleitungen zurück."""
    if not urlparse(url).scheme in {"http", "https"}:
        raise SystemExit(f"Keine Web-Adresse: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "de,en;q=0.7"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read(MAX_BYTES), response.geturl()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as error:
        raise SystemExit(f"Seite nicht erreichbar ({url}): {error}") from error


def target_path(fach: Fach, url: str, name: str | None = None) -> Path:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.") or "web"
    stem = name or parsed.path.rstrip("/").rsplit("/", 1)[-1] or host
    return fach.quellen / WEB_FOLDER / host / f"{slugify(stem)}.md"


def snapshot(url: str, title: str, lines: list[str], fetched: date) -> str:
    """Kopfzeilen mit Adresse und Abrufdatum, danach der Text; beides landet im Suchindex."""
    head = [
        "---",
        f"url: {url}",
        f"titel: {title}",
        f"abgerufen: {fetched.isoformat()}",
        "hinweis: Lesekopie einer Webseite (invoke wissen-web). Maßgeblich ist diese Kopie, nicht die Live-Seite.",
        "---",
        "",
    ]
    return "\n".join(head + lines).rstrip() + "\n"


def body_of(text: str) -> str:
    match = FRONTMATTER.match(text)
    return (match.group(1) if match else text).strip()


def holen(url: str, fach: Fach, name: str | None = None, log=print) -> tuple[Path, str]:
    """Eine Seite abholen und als Kopie ablegen. Gibt Pfad und Ergebnis (neu, aktualisiert, unveraendert) zurück."""
    raw, final_url = fetch(url)
    parser = _Markdown(final_url)
    parser.feed(raw.decode("utf-8", "replace"))
    lines = _tidy(parser.parts)
    if sum(len(line) for line in lines) < 200:
        raise SystemExit(
            f"Kaum Text gefunden unter {final_url}. Seiten, die ihren Inhalt erst per JavaScript nachladen, lassen "
            "sich so nicht abholen: Seite von Hand als Text oder PDF sichern und in ressourcen/quellen/<fach>/web/ ablegen."
        )
    title = _page_title(parser.title, lines, final_url)
    path = target_path(fach, final_url, name)
    text = snapshot(final_url, title, lines, date.today())
    if path.exists():
        if body_of(path.read_text(encoding="utf-8")) == body_of(text):
            log(f"[{fach.name}] unverändert: {path.relative_to(fach.quellen.parent).as_posix()}")
            return path, "unveraendert"
        status = "aktualisiert"
    else:
        status = "neu"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    log(f"[{fach.name}] {status}: {path.relative_to(fach.quellen.parent).as_posix()} ({len(lines)} Absätze, „{title}“)")
    return path, status
