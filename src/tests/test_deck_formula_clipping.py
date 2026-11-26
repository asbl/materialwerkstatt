"""Browser-Tests fuer Formeln im Excalidraw-Deck der Potenz-Folie.

Typst setzt eine Formelseite nur so hoch wie die Zeilenhoehe; hochgestellte
Exponenten und tief reichende Klammern ragen darueber hinaus. Excalidraw
rasterisiert SVG-Bilder auf einen Canvas und schneidet dabei alles ausserhalb
der viewBox ab. Diese Tests pruefen im Browser (Chromium), dass die Formel-
SVGs des Decks ihre Tinte vollstaendig innerhalb der Bildkante halten.
"""

from __future__ import annotations

import base64
import json
import socket
import shutil
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from excalideck.generator import generate_deck
from material_ui import app as material_app
from material_ui import deck_routes
from material_ui.runtime import RuntimeState, runtime_scope

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - depends on local test environment
    sync_playwright = None


REPO_ROOT = Path(__file__).resolve().parents[2]
SLIDE_QMD = REPO_ROOT / "unterricht" / "mathematik" / "klasse-10" / "potenzen" / "01-einfuehrung" / "slide.qmd"
DECK_REL = "unterricht/mathe/potenzen.excalidraw"

# Rastert jede Formel-SVG (DataURL) wie Excalidraw es tut und zaehlt dunkle
# Tinte im aeusseren Rand: Beschnittene Glyphen enden an der Bildkante.
_RASTERIZE_FORMULAS = """
async (dataUrls) => {
  const results = [];
  for (const dataUrl of dataUrls) {
    const image = new Image();
    image.src = dataUrl;
    await image.decode();
    const scale = 2;
    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(image.naturalWidth * scale);
    canvas.height = Math.ceil(image.naturalHeight * scale);
    const context = canvas.getContext("2d");
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let darkTotal = 0;
    let darkBorder = 0;
    const ring = 2;
    for (let y = 0; y < canvas.height; y++) {
      for (let x = 0; x < canvas.width; x++) {
        const index = (y * canvas.width + x) * 4;
        if (pixels[index + 3] < 16) continue;
        if (pixels[index] + pixels[index + 1] + pixels[index + 2] >= 384) continue;
        darkTotal++;
        if (x < ring || y < ring || x >= canvas.width - ring || y >= canvas.height - ring) darkBorder++;
      }
    }
    results.push({width: canvas.width, height: canvas.height, darkTotal, darkBorder});
  }
  return results;
}
"""


def _formula_data_urls(deck_path: Path) -> list[str]:
    """DataURLs aller Typst-Formel-SVGs des Decks (Skizzen und Hintergründe ausgespart)."""
    data = json.loads(deck_path.read_text(encoding="utf-8"))
    urls = []
    for file in data.get("files", {}).values():
        if file.get("mimeType") != "image/svg+xml":
            continue
        svg = base64.b64decode(file["dataURL"].split(",", 1)[1]).decode()
        if "<defs>" in svg:
            urls.append(file["dataURL"])
    return urls


def _frame_count(deck_path: Path) -> int:
    data = json.loads(deck_path.read_text(encoding="utf-8"))
    return len([element for element in data["elements"] if element.get("type") == "frame" and not element.get("isDeleted")])


@pytest.fixture(scope="module")
def generated_deck(tmp_path_factory) -> Path:
    if not shutil.which("quarto") or not shutil.which("typst"):
        pytest.skip("Quarto/Typst fehlen")
    if not SLIDE_QMD.is_file():
        pytest.skip("Potenz-Folie fehlt im Repo")
    root = tmp_path_factory.mktemp("potenz-deck")
    deck = root / DECK_REL
    deck.parent.mkdir(parents=True, exist_ok=True)
    generate_deck(SLIDE_QMD, output_path=deck)
    return root


@pytest.fixture()
def deck_root(generated_deck: Path, monkeypatch) -> Path:
    monkeypatch.setattr(material_app, "ROOT", generated_deck)
    runtime = RuntimeState()
    factory = material_app.create_app

    def create_test_app():
        app = factory(runtime=runtime)
        app.config.update(TESTING=True)
        return app

    monkeypatch.setattr(material_app, "create_app", create_test_app)
    with runtime_scope(runtime):
        material_app.initialize_runtime(runtime)
        try:
            yield generated_deck
        finally:
            runtime.close()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LiveServer:
    def __init__(self, app, port: int):
        # threaded: Der Browser haelt eine Server-Event-Verbindung offen.
        self.server = make_server("127.0.0.1", port, app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.url = f"http://127.0.0.1:{port}"

    def __enter__(self):
        self.thread.start()
        return self.url

    def __exit__(self, _exc_type, _exc, _tb):
        self.server.shutdown()
        self.thread.join(timeout=5)


def test_potenz_deck_formulas_are_not_clipped_in_browser(deck_root: Path) -> None:
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    deck = deck_root / DECK_REL
    formulas = _formula_data_urls(deck)
    assert len(formulas) >= 5, "Deck der Potenz-Folie sollte Formeln als SVG einbetten"

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="networkidle")
        results = page.evaluate(_RASTERIZE_FORMULAS, formulas)
        browser.close()

    assert len(results) == len(formulas)
    for result in results:
        assert result["darkTotal"] > 0, "Formel-SVG ohne sichtbare Tinte"
        assert result["darkBorder"] == 0, f"Formel-Tinte reicht bis an die Bildkante: {result}"


def test_clipping_check_detects_cut_glyphs(deck_root: Path) -> None:
    """Validiert die Prueflogik: ein an der Kante beschnittenes SVG wird erkannt."""
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    clipped = (
        "data:image/svg+xml;base64,"
        + base64.b64encode(
            '<svg viewBox="0 0 40 20" width="40pt" height="20pt" xmlns="http://www.w3.org/2000/svg">'
            '<path fill="#242333" d="M 2 -6 L 8 -6 L 8 14 L 2 14 Z"/></svg>'.encode()
        ).decode()
    )
    contained = (
        "data:image/svg+xml;base64,"
        + base64.b64encode(
            '<svg viewBox="0 0 40 20" width="40pt" height="20pt" xmlns="http://www.w3.org/2000/svg">'
            '<path fill="#242333" d="M 2 2 L 8 2 L 8 14 L 2 14 Z"/></svg>'.encode()
        ).decode()
    )
    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="networkidle")
        clipped_result, contained_result = page.evaluate(_RASTERIZE_FORMULAS, [clipped, contained])
        browser.close()

    assert clipped_result["darkBorder"] > 0, "Beschnittene Glyphe wurde nicht erkannt"
    assert contained_result["darkBorder"] == 0


def test_present_app_renders_potenz_deck(deck_root: Path) -> None:
    if sync_playwright is None:
        pytest.skip("Playwright ist nicht installiert")
    if not deck_routes._present_built():
        pytest.skip("Present-Build fehlt (inv deck-present)")
    frames = _frame_count(deck_root / DECK_REL)
    assert frames >= 10, "Potenz-Deck sollte die Folien der QMD enthalten"

    with LiveServer(material_app.create_app(), free_port()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{url}/present/?path={DECK_REL}", wait_until="networkidle")
        page.wait_for_selector("canvas", timeout=15000)
        page.wait_for_selector(f"text=1 / {frames}", timeout=15000)
        assert errors == [], str(errors[:2])
        browser.close()
