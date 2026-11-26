"""Smoke-Test fuer die Present-App (src/excalideck/present).

Erzeugt ein eigenes Testdeck aus einer Outline (keine Kopplung an
Unterrichtsinhalte) und prueft mit Playwright: Deck laden, Foliennavigation,
Freedraw zeichnen, Annotations-Palette (Farben, Strichstaerken, Marker,
Undo/Redo, Folie leeren), Speichern als .excalidraw.

Aufruf: env -u LD_LIBRARY_PATH python3 src/excalideck/present/smoke_test.py
(LD_LIBRARY_PATH muss in der Agent-Shell geleert werden, sonst faellt chromium beim Import.)
"""

import base64
import json
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from pymupdf import Pixmap
from ui_test_helpers import click_toolbar_title, mock_material_protocol
from regression_test import run_checks
from lesson_features_test import run_lesson_checks

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from excalideck.generator import generate_deck  # noqa: E402

DIST = Path(__file__).resolve().parent / "dist"
PORT = 4180
URL = f"http://127.0.0.1:{PORT}/index.html"
OUT = Path("/tmp/excalideck-present-download.excalidraw")

OUTLINE = """# Smoke-Deck

Untertitel fuer den Present-App-Smoke-Test

## Folie A

- Punkt 1 mit etwas Text
- Punkt 2 mit etwas Text

## Folie B

Ein Absatz mit normalerweise ausreichend langem Text.
"""

failures = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        failures.append(name)


def check_template_annotations(browser, directory):
    """Sichtbare Pixel pruefen: Elementzaehlen erkennt verdeckte Striche nicht."""
    frame = {"id": "template-frame", "type": "frame", "name": "Template",
             "x": 0, "y": 0, "width": 1600, "height": 900}
    background = {"id": "template-bg", "type": "image", "frameId": frame["id"],
                  "fileId": "template-file", "status": "saved", "scale": [1, 1],
                  "x": 0, "y": 0, "width": 1600, "height": 900}
    stroke = {"id": "saved-stroke", "type": "freedraw", "frameId": frame["id"],
              "x": 300, "y": 400, "width": 200, "height": 40,
              "points": [[0, 0], [100, 20], [200, 40]], "pressures": [],
              "simulatePressure": True, "strokeWidth": 8, "strokeColor": "#e03131",
              "opacity": 100}
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect width="1600" height="900" fill="#f4efff"/></svg>'
    scene = {"type": "excalidraw", "version": 2, "elements": [stroke, frame, background],
             "files": {"template-file": {"id": "template-file", "mimeType": "image/svg+xml",
                       "dataURL": "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode(),
                       "created": 1}}}
    for element in scene["elements"]:
        element["isDeleted"] = False
    fixture = Path(directory) / "template.excalidraw"
    fixture.write_text(json.dumps(scene), encoding="utf-8")
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def load(path):
        page.goto(URL)
        page.wait_for_selector("canvas")
        page.set_input_files("input[type=file]", str(path))
        page.wait_for_timeout(1000)

    def viewport(x, y):
        return page.evaluate("""([x, y]) => {
            const s = window.__excalidraw.getAppState();
            return [(x + s.scrollX) * s.zoom.value + s.offsetLeft,
                    (y + s.scrollY) * s.zoom.value + s.offsetTop];
        }""", [x, y])

    def colored_pixels(y, color):
        left, top = viewport(290, y - 10)
        right, bottom = viewport(510, y + 50)
        image = Pixmap(page.screenshot(clip={
            "x": left, "y": top, "width": right - left, "height": bottom - top,
        }))
        pixels = image.samples
        return sum((r > 170 and g < 120 and b < 120) if color == "red"
                   else (b > 130 and r < 100 and g < 160)
                   for r, g, b in zip(pixels[0::image.n], pixels[1::image.n], pixels[2::image.n]))

    try:
        load(fixture)
        check("Gespeicherter Strich ist auf Template sichtbar", colored_pixels(400, "red") > 100)
        check("Ladereparatur erzeugt keine ungespeicherten Benutzer-Aenderungen",
              page.locator(".deck-dirty-dot").count() == 0)
        click_toolbar_title(page, "Farbe #1971c2")
        page.mouse.move(*viewport(300, 520))
        page.mouse.down()
        page.mouse.move(*viewport(500, 560), steps=10)
        page.mouse.up()
        page.wait_for_timeout(300)
        check("Neuer Strich bleibt nach Absetzen auf Template sichtbar", colored_pixels(520, "blue") > 100)
        ids = page.evaluate("() => window.__excalidraw.getSceneElements().map(el => el.id).sort()")
        saved = Path(directory) / "template-saved.excalidraw"
        with page.expect_download() as download:
            page.keyboard.press("Control+s")
        download.value.save_as(saved)
        load(saved)
        check("Alter und neuer Strich nach Speichern und Oeffnen sichtbar",
              colored_pixels(400, "red") > 100 and colored_pixels(520, "blue") > 100)
        check("Speichern und Oeffnen erhaelt alle Elemente ohne Duplikate",
              page.evaluate("() => window.__excalidraw.getSceneElements().map(el => el.id).sort()") == ids)

        # In bereits korrekt aufgebauten Decks kann eine Freihandzeichnung
        # absichtlich unter einem Bild liegen: diese Reihenfolge erhalten.
        scene["elements"] = [stroke, background, frame]
        fixture.write_text(json.dumps(scene), encoding="utf-8")
        load(fixture)
        check("Korrekte Decks behalten absichtlich verdeckte Zeichnungen", colored_pixels(400, "red") == 0)
        check("Keine JS-Fehler bei Template-Wiederherstellung", not errors, str(errors[:2]))
    finally:
        page.close()



def check_drawing_tools(browser, directory):
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL)
    page.wait_for_selector("canvas")
    page.set_input_files("input[type=file]", str(Path(directory) / "template.excalidraw"))
    page.wait_for_timeout(800)
    state = lambda: page.evaluate("() => window.__excalidraw.getAppState()")
    elements = lambda: page.evaluate("() => window.__excalidraw.getSceneElements()")
    check("Dünn ist beim Laden aktiv", abs(state()["currentItemStrokeWidth"] * state()["zoom"]["value"] - 2) < 1e-6)
    check("Hintergrund und Rahmen sind geschützt", all(e["locked"] for e in elements() if e["type"] in ("frame", "image")))

    def point(x, y):
        s = state()
        return ((x + s["scrollX"]) * s["zoom"]["value"] + s["offsetLeft"],
                (y + s["scrollY"]) * s["zoom"]["value"] + s["offsetTop"])

    click_toolbar_title(page, "Radierer")
    page.mouse.move(*point(300, 400))
    page.mouse.down()
    page.mouse.move(*point(500, 440), steps=12)
    page.mouse.up()
    page.wait_for_timeout(300)
    check("Radierer entfernt Strich, schützt Template", not any(e["id"] == "saved-stroke" for e in elements()) and any(e["id"] == "template-bg" for e in elements()))

    page.get_by_role("button", name="Folie einfügen", exact=True).click()
    page.get_by_role("button", name="▦ Rechenkästchen", exact=True).click()
    page.wait_for_timeout(300)
    grid = next(e for e in elements() if e["type"] == "frame" and e["id"] != "template-frame")
    check("Kästchenfolie direkt nach aktueller Folie", page.locator(".deck-counter").inner_text() == "2 / 2")
    check("Kästchen bedecken die ganze Folie und sind geschützt", len([e for e in elements() if e.get("frameId") == grid["id"] and e["locked"]]) > 90)
    page.keyboard.press("PageUp")
    page.get_by_role("button", name="Folie einfügen", exact=True).click()
    page.get_by_role("button", name="▭ Leerfolie", exact=True).click()
    page.wait_for_timeout(200)
    check("Weitere Einfügung bleibt unmittelbar nach aktueller Folie", page.locator(".deck-counter").inner_text() == "2 / 3")
    page.keyboard.press("PageDown")
    check("Kästchenfolie folgt auf eingefügte Leerfolie", page.locator(".deck-counter").inner_text() == "3 / 3")

    page.get_by_role("button", name="Formen", exact=True).click()
    page.get_by_role("button", name="Rechteck", exact=True).click()
    page.mouse.move(*point(grid["x"] + 300, grid["y"] + 300))
    page.mouse.down()
    page.mouse.move(*point(grid["x"] + 500, grid["y"] + 450), steps=6)
    page.mouse.up()
    page.wait_for_timeout(200)
    rectangle = next(e for e in elements() if e["type"] == "rectangle" and not e.get("locked"))
    page.evaluate("id => window.__excalidraw.updateScene({appState:{selectedElementIds:{[id]:true}}})", rectangle["id"])
    page.get_by_role("button", name="Zeichenoptionen", exact=True).click()
    page.get_by_role("button", name="Konturstil: ┄", exact=True).click()
    page.get_by_role("button", name="Sauberkeit: Glatt", exact=True).click()
    page.get_by_role("button", name="Ecken: Rund", exact=True).click()
    page.get_by_role("slider", name="Deckkraft", exact=True).fill("60")
    updated = next(e for e in elements() if e["id"] == rectangle["id"])
    check("Zeichenoptionen verändern ausgewählte Form", updated["strokeStyle"] == "dashed" and updated["roughness"] == 0 and updated["opacity"] == 60 and updated["roundness"] == {"type": 3})
    page.keyboard.press("Escape")

    # Ein echtes ClipboardEvent mit PNG-Datei prüft denselben Weg wie Strg+V.
    page.evaluate("""async () => {
        const canvas = document.createElement('canvas'); canvas.width=40; canvas.height=30;
        canvas.getContext('2d').fillRect(0,0,40,30);
        const blob = await new Promise(resolve => canvas.toBlob(resolve));
        const data = new DataTransfer(); data.items.add(new File([blob], 'clipboard.png', {type:'image/png'}));
        document.querySelector('.excalidraw').dispatchEvent(new ClipboardEvent('paste', {clipboardData:data,bubbles:true,cancelable:true}));
    }""")
    page.wait_for_timeout(300)
    pasted = [e for e in elements() if e["type"] == "image" and e["id"] != "template-bg"]
    check("Zwischenablage fügt PNG auf aktueller Folie ein", len(pasted) == 1 and pasted[0].get("frameId") == grid["id"])

    for label, draw in (("Lineal", "Kante nachziehen"), ("Geodreieck", "Kante nachziehen"), ("Zirkel", "Kreis zeichnen")):
        page.get_by_role("button", name="Geometriehilfen", exact=True).click()
        page.get_by_role("button", name=label, exact=True).click()
        before = len(elements())
        page.get_by_role("button", name=draw, exact=True).click()
        page.wait_for_timeout(100)
        check(f"{label} erzeugt Zeichnung", len(elements()) == before + 1)
        page.get_by_role("button", name="Geometriehilfe schließen", exact=True).click()

    page.get_by_role("button", name="ExcaliMath", exact=True).click()
    try:
        page.get_by_placeholder("Type LaTeX or use the toolbar above").wait_for(timeout=5000)
    except Exception:
        print("ExcaliMath-Diagnose:", errors, page.locator("body").inner_text()[-1600:], flush=True)
        page.screenshot(path="/tmp/excalideck-math-error.png")
        raise
    page.get_by_placeholder("Type LaTeX or use the toolbar above").fill("x^2 + 1")
    page.get_by_role("button", name="Insert", exact=True).click()
    page.wait_for_timeout(800)
    formulas = [e for e in elements() if (e.get("customData") or {}).get("excalimath_type") == "equation"]
    check("ExcaliMath fügt Formel auf aktueller Folie ein", len(formulas) == 1 and formulas[0].get("frameId") == grid["id"])
    page.get_by_role("button", name="Close ExcaliMath panel", exact=True).click()
    with page.expect_download() as download:
        page.keyboard.press("Control+s")
    target = Path(directory) / "drawing-tools.excalidraw"
    download.value.save_as(target)
    saved = json.loads(target.read_text())
    check("Speichern enthält Clipboard- und Formeldateien", all(e["fileId"] in saved["files"] for e in pasted + formulas))
    page.reload()
    page.set_input_files("input[type=file]", str(target))
    page.wait_for_timeout(700)
    check("Eingefügte Bilder bleiben nach erneutem Laden bearbeitbar", all(not e["locked"] for e in elements() if e["id"] in {x["id"] for x in pasted + formulas}))
    check("Zusatzfolien bleiben nach erneutem Laden vorhanden", page.locator(".deck-counter").inner_text() == "1 / 3")
    page.keyboard.press("PageDown")
    page.keyboard.press("PageDown")
    page.wait_for_function("document.querySelector('.deck-counter').textContent === '3 / 3'")
    # Der Folienzaehler und Excalidraws Viewport werden getrennt aktualisiert.
    page.wait_for_function("""([y, height]) => {
        const s = window.__excalidraw.getAppState();
        const center = (y + height / 2 + s.scrollY) * s.zoom.value;
        return center > 0 && center < document.querySelector('.deck-toolbar').getBoundingClientRect().y;
    }""", arg=[grid["y"], grid["height"]])
    s = state()
    check("Kästchenfolie bleibt nach erneutem Laden an Position 3", 0 < (grid["y"] + grid["height"]/2 + s["scrollY"]) * s["zoom"]["value"] < page.locator(".deck-toolbar").bounding_box()["y"])
    check("Keine JS-Fehler bei neuen Zeichenwerkzeugen", not errors, str(errors[:3]))
    page.screenshot(path="/tmp/excalideck-drawing-tools.png")
    # Material-UI: Zusatzfolien duerfen ausschliesslich im Sidecar leben.
    base = json.loads((Path(directory) / "template.excalidraw").read_text())
    sidecar = {"elements": [], "files": {}, "revision": None}

    def api_route(route):
        nonlocal sidecar
        from urllib.parse import urlsplit
        path = urlsplit(route.request.url).path
        if path == "/api/deck/annotations/save":
            sidecar = {**json.loads(route.request.post_data_json["scene"]), "revision": "annotations-1"}
            route.fulfill(json={"revision": "annotations-1"})
        elif path == "/api/deck/annotations":
            route.fulfill(json={key: value for key, value in sidecar.items() if key != "revision"}, headers={"X-Material-Revision": sidecar["revision"]} if sidecar["revision"] else {})
        elif path == "/api/deck/revision":
            route.fulfill(json={"revision": "deck-1"})
        else:
            route.fulfill(json=base, headers={"X-Material-Revision": "deck-1"})

    contract = json.loads((ROOT / 'src/material_ui/static/api-contract.json').read_text())
    page.route("**/static/api-contract.json", lambda route: route.fulfill(json=contract))
    page.route("**/api/protocol", lambda route: route.fulfill(json=contract))
    mock_material_protocol(page)
    page.route("**/api/deck**", api_route)
    page.add_init_script("window.__MATERIAL_TOKEN__ = 'smoke';")
    page.goto(URL + "?path=fixture.excalidraw")
    page.wait_for_timeout(800)
    if not page.locator(".presenting").count():
        print("Material-Modus:", page.url, errors, page.locator("body").inner_text()[:1000], flush=True)
    page.get_by_role("button", name="Folie einfügen", exact=True).click()
    page.get_by_role("button", name="▦ Rechenkästchen", exact=True).click()
    page.keyboard.press("Control+s")
    page.wait_for_timeout(500)
    check("Zusatzfolie wird im Sidecar gespeichert", any(e["type"] == "frame" for e in sidecar["elements"]) and not any(e["id"] == "template-bg" for e in sidecar["elements"]))
    page.reload()
    page.wait_for_timeout(800)
    check("Sidecar stellt Zusatzfolie ohne Duplikate wieder her", page.locator(".deck-counter").inner_text() == "1 / 2")
    check("Keine JS-Fehler beim Sidecar-Speichern", not errors, str(errors[:3]))
    page.close()


def main():
    import shutil
    import socket
    import subprocess

    global PORT, URL
    with socket.socket() as address:
        address.bind(("127.0.0.1", 0))
        PORT = address.getsockname()[1]
    URL = f"http://127.0.0.1:{PORT}/index.html"
    with tempfile.TemporaryDirectory() as tmp:
        # Ein paralleler Vite-Build ersetzt dist/ samt gehashter Dateien.
        # Jeder Testlauf verwendet deshalb seinen eigenen, festen Buildstand.
        served_dist = Path(tmp) / "present-build"
        shutil.copytree(DIST, served_dist)
        outline = Path(tmp) / "smoke-deck.md"
        outline.write_text(OUTLINE, encoding="utf-8")
        deck = generate_deck(outline)
        data = json.loads(deck.read_text(encoding="utf-8"))
        # Auch bestehende Decks aus dem alten Generator muessen funktionieren:
        # dort stand jeder Frame vor seinen Kindern (inkl. Template-Bild).
        legacy_elements = []
        for frame in (el for el in data["elements"] if el["type"] == "frame"):
            legacy_elements.append(frame)
            legacy_elements.extend(el for el in data["elements"] if el.get("frameId") == frame["id"])
        for element in legacy_elements:
            element.pop("index", None)
        data["elements"] = legacy_elements
        deck.write_text(json.dumps(data), encoding="utf-8")
        base = len(data["elements"])
        slides = sum(1 for element in data["elements"] if element["type"] == "frame")

        server = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1", "-d", str(served_dist)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(URL)
                page.wait_for_selector("canvas", timeout=15000)

                page.set_input_files("input[type=file]", str(deck))
                page.wait_for_timeout(1500)
                check(
                    f"Folienzaehler zeigt 1 / {slides} nach Laden",
                    page.locator(f"text=1 / {slides}").count() >= 1,
                )

                # Vollbild-Knopf am oberen Rand: in der Praesentation direkt
                # erreichbar, ohne das Dropup "Weitere Werkzeuge" zu oeffnen.
                fullscreen_button = page.locator(".deck-top-fullscreen")
                check(
                    "Vollbild-Knopf oben waehrend der Praesentation sichtbar",
                    fullscreen_button.is_visible(),
                )
                button_box = fullscreen_button.bounding_box()
                toolbar_box = page.locator(".deck-toolbar").bounding_box()
                check(
                    "Vollbild-Knopf liegt ueber der unteren Palette",
                    button_box["y"] < toolbar_box["y"],
                    f"(Knopf y={button_box['y']}, Palette y={toolbar_box['y']})",
                )
                # Headlesse Browser unterstuetzen echte Vollbildwechsel nicht
                # immer deshalb Vertrag und Zustand hier simulieren.
                page.evaluate(
                    """() => {
                        const element = document.documentElement;
                        let active = false;
                        Object.defineProperty(document, "fullscreenElement", {
                            configurable: true,
                            get: () => (active ? element : null),
                        });
                        element.requestFullscreen = () => {
                            active = true;
                            document.dispatchEvent(new Event("fullscreenchange"));
                            return Promise.resolve();
                        };
                        document.exitFullscreen = () => {
                            active = false;
                            document.dispatchEvent(new Event("fullscreenchange"));
                            return Promise.resolve();
                        };
                    }"""
                )
                fullscreen_button.click()
                page.wait_for_timeout(200)
                check(
                    "Vollbild-Knopf zeigt aktivierten Vollbild-Zustand",
                    fullscreen_button.get_attribute("aria-pressed") == "true",
                )
                fullscreen_button.click()
                page.wait_for_timeout(200)
                check(
                    "Zweiter Klick verlaesst das Vollbild",
                    fullscreen_button.get_attribute("aria-pressed") == "false",
                )

                page.keyboard.press("PageDown")
                page.wait_for_timeout(400)
                check(f"PageDown -> 2 / {slides}", page.locator(f"text=2 / {slides}").count() >= 1)
                page.keyboard.press("PageDown")
                page.wait_for_timeout(400)
                check(f"PageDown -> 3 / {slides}", page.locator(f"text=3 / {slides}").count() >= 1)
                page.keyboard.press("PageUp")
                page.wait_for_timeout(400)
                check(f"PageUp -> 2 / {slides}", page.locator(f"text=2 / {slides}").count() >= 1)

                # Fokus-Fix: Canvas-Klick fokussiert Container, dann Tastaturkuerzel.
                # Achtung: Excalidraw-Canvases haben transformierte Riesen-Bounding-Boxes,
                # daher Viewport-Koordinaten statt canvas.bounding_box() verwenden.
                cx, cy = 640, 400
                page.mouse.click(cx, cy)
                page.keyboard.press("x")
                page.wait_for_timeout(300)
                tool = page.evaluate("() => window.__excalidraw.getAppState().activeTool.type")
                check("Kuerzel X nach Canvas-Klick aktiviert Freedraw", tool == "freedraw", f"(tool={tool})")

                page.mouse.move(cx, cy)
                page.mouse.down()
                page.mouse.move(cx + 120, cy + 60, steps=8)
                page.mouse.up()
                page.wait_for_timeout(500)
                n = page.evaluate("() => window.__excalidraw.getSceneElements().length")
                # Im Praesentationsmodus ist Freedraw ab Laden aktiv, der Fokus-Klick
                # erzeugt daher einen Punkt: Basis-Elemente + Punkt + Strich.
                check("Gezeichneter Strich erzeugt Element", n == base + 2, f"(n={n}, base={base})")
                visible_order = page.evaluate("""() => {
                    const elements = window.__excalidraw.getSceneElements();
                    return elements.filter(el => el.type === 'freedraw').every(stroke => {
                        const frameIndex = elements.findIndex(el => el.id === stroke.frameId);
                        const strokeIndex = elements.indexOf(stroke);
                        return frameIndex > strokeIndex && elements.every((el, i) =>
                            el.frameId !== stroke.frameId || el.type === 'freedraw' || i < strokeIndex);
                    });
                }""")
                check("Striche liegen auch bei alten Decks ueber den Folieninhalten", visible_order)

                # Farbpalette: roten Farbpunkt waehlen.
                click_toolbar_title(page, "Farbe #e03131")
                page.wait_for_timeout(200)
                color = page.evaluate(
                    "() => window.__excalidraw.getAppState().currentItemStrokeColor"
                )
                check("Farbpunkt setzt Stiftfarbe", color == "#e03131", f"(color={color})")

                # Strichstaerke: dick waehlen.
                click_toolbar_title(page, "Strichstärke dick")
                page.wait_for_timeout(200)
                width = page.evaluate(
                    "() => { const s=window.__excalidraw.getAppState(); return s.currentItemStrokeWidth*s.zoom.value; }"
                )
                check("Strichstärke dick setzt Strichbreite 8", abs(width - 8) < 1e-6, f"(width={width})")

                # Neue Texte nutzen den besser lesbaren Helvetica-Standard.
                font = page.evaluate(
                    "() => window.__excalidraw.getAppState().currentItemFontFamily"
                )
                check(
                    "Neue Texte nutzen Helvetica (fontFamily 2)",
                    font == 2,
                    f"(font={font})",
                )

                # Marker: dicker, halbtransparenter Strich.
                click_toolbar_title(page, "Marker: dicker, halbtransparenter Strich")
                page.wait_for_timeout(200)
                app_state = page.evaluate("() => window.__excalidraw.getAppState()")
                check(
                    "Marker aktiviert Freedraw mit Breite 16",
                    app_state["activeTool"]["type"] == "freedraw"
                    and app_state["currentItemStrokeWidth"] == 16,
                    f"(tool={app_state['activeTool']['type']}, width={app_state['currentItemStrokeWidth']})",
                )
                check("Marker setzt Deckkraft 35", app_state["currentItemOpacity"] == 35)

                # Zurueck zum Stift: volle Deckkraft, letzte Strichstaerke.
                click_toolbar_title(page, "Stift (Stylus zeichnet direkt auf die Folie)")
                page.wait_for_timeout(200)
                app_state = page.evaluate("() => window.__excalidraw.getAppState()")
                check(
                    "Stift stellt Deckkraft 100 und Breite 8 wieder her",
                    app_state["currentItemOpacity"] == 100
                    and abs(app_state["currentItemStrokeWidth"] * app_state["zoom"]["value"] - 8) < 1e-6,
                    f"(opacity={app_state['currentItemOpacity']}, width={app_state['currentItemStrokeWidth']})",
                )

                # Werkzeugketten duerfen weder Marker- noch Formenbreite
                # als neue Stift-Voreinstellung uebernehmen.
                for label, expected in (("dünn", 2), ("mittel", 4)):
                    page.get_by_title(f"Strichstärke {label}", exact=True).click()
                    for title in ("Radierer", "Text auf die Folie schreiben", "Auswahl: Anmerkungen verschieben oder löschen"):
                        click_toolbar_title(page, "Marker: dicker, halbtransparenter Strich")
                        click_toolbar_title(page, title)
                        page.wait_for_timeout(100)
                        click_toolbar_title(page, "Stift (Stylus zeichnet direkt auf die Folie)")
                        page.wait_for_timeout(100)
                        current = page.evaluate("() => window.__excalidraw.getAppState()")
                        check(f"Stift bleibt {label} nach Marker → {title}", abs(current["currentItemStrokeWidth"] * current["zoom"]["value"] - expected) < 1e-6 and current["currentItemOpacity"] == 100)
                    page.get_by_role("button", name="Formen", exact=True).click()
                    page.get_by_role("button", name="Rechteck", exact=True).click()
                    page.get_by_role("button", name="Zeichenoptionen", exact=True).click()
                    page.get_by_role("button", name="Strichstärke: Dick", exact=True).click()
                    page.keyboard.press("Escape")
                    click_toolbar_title(page, "Stift (Stylus zeichnet direkt auf die Folie)")
                    page.wait_for_timeout(100)
                    current = page.evaluate("() => window.__excalidraw.getAppState()")
                    check(f"Formenbreite überschreibt Stift {label} nicht", abs(current["currentItemStrokeWidth"] * current["zoom"]["value"] - expected) < 1e-6)
                    click_toolbar_title(page, "Radierer")
                    page.locator(".excalidraw").focus()
                    page.keyboard.press("x")
                    page.wait_for_timeout(150)
                    current = page.evaluate("() => window.__excalidraw.getAppState()")
                    check(f"Tastenkürzel stellt Stift {label} wieder her", current["activeTool"]["type"] == "freedraw" and abs(current["currentItemStrokeWidth"] * current["zoom"]["value"] - expected) < 1e-6)
                click_toolbar_title(page, "Strichstärke dick")

                # Handballen-Erkennung: standardmäßig aktiv – nur der Stift zeichnet,
                # der Finger verschiebt die Folie.
                PEN_MODE_TITLE = "Handballen-Erkennung: nur der Stift zeichnet, der Finger verschiebt die Folie – abschalten, damit der Finger zeichnet (z. B. ohne Stift)"
                app_state = page.evaluate("() => window.__excalidraw.getAppState()")
                check(
                    "penMode ist standardmäßig aktiv (nur Stift zeichnet)",
                    app_state["penMode"] is True,
                    f"(penMode={app_state['penMode']})",
                )

                # Finger-Touch zeichnet bei penMode nicht, sondern verschiebt die Folie.
                cdp = page.context.new_cdp_session(page)
                cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
                def touch(event, points):
                    cdp.send("Input.dispatchTouchEvent", {"type": event, "touchPoints": [dict(x=x, y=y, id=i, radiusX=2, radiusY=2, force=1) for i, (x, y) in enumerate(points)]})
                    page.wait_for_timeout(40)
                def freedraw_count():
                    return page.evaluate("() => window.__excalidraw.getSceneElements().filter(e => e.type === 'freedraw' && !e.isDeleted).length")
                before = page.evaluate("() => { const s = window.__excalidraw.getAppState(); return { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value, elements: window.__excalidraw.getSceneElements().filter(e => e.type === 'freedraw' && !e.isDeleted).length }; }")
                touch("touchStart", [(400, 300)])
                touch("touchMove", [(460, 340)])
                touch("touchEnd", [])
                page.wait_for_timeout(150)
                after = page.evaluate("() => { const s = window.__excalidraw.getAppState(); return { scrollX: s.scrollX, scrollY: s.scrollY, zoom: s.zoom.value, elements: window.__excalidraw.getSceneElements().filter(e => e.type === 'freedraw' && !e.isDeleted).length }; }")
                check(
                    "Finger verschiebt bei penMode die Folie und zeichnet nicht",
                    after["elements"] == before["elements"]
                    and abs((after["scrollX"] - before["scrollX"]) - (460 - 400) / after["zoom"]) < 2
                    and abs((after["scrollY"] - before["scrollY"]) - (340 - 300) / after["zoom"]) < 2,
                    f"(scroll {before['scrollX']:.1f},{before['scrollY']:.1f} -> {after['scrollX']:.1f},{after['scrollY']:.1f}, freedraw {before['elements']} -> {after['elements']})",
                )

                # penMode aus: der Finger zeichnet wieder.
                click_toolbar_title(page, PEN_MODE_TITLE)
                page.wait_for_timeout(200)
                app_state = page.evaluate("() => window.__excalidraw.getAppState()")
                check(
                    "Handballen-Knopf deaktiviert penMode (Finger zeichnet wieder)",
                    app_state["penMode"] is False,
                    f"(penMode={app_state['penMode']})",
                )
                before_count = freedraw_count()
                touch("touchStart", [(500, 400)])
                touch("touchMove", [(560, 440)])
                touch("touchEnd", [])
                page.wait_for_timeout(200)
                check(
                    "Ohne penMode zeichnet der Finger wieder",
                    freedraw_count() == before_count + 1,
                    f"(freedraw {before_count} -> {freedraw_count()})",
                )
                page.locator(".excalidraw").focus()
                page.keyboard.press("Control+z")
                page.wait_for_timeout(150)
                cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False, "maxTouchPoints": 1})

                click_toolbar_title(page, PEN_MODE_TITLE)
                page.wait_for_timeout(200)
                app_state = page.evaluate("() => window.__excalidraw.getAppState()")
                check(
                    "Handballen-Knopf aktiviert penMode wieder",
                    app_state["penMode"] is True,
                    f"(penMode={app_state['penMode']})",
                )

                # Zoom-Widget: Knöpfe, Prozentanzeige (Reset) und Fit.
                zoom0 = page.evaluate("() => window.__excalidraw.getAppState().zoom.value")
                click_toolbar_title(page, "Hineinzoomen (Strg+ +)")
                page.wait_for_timeout(200)
                zoom1 = page.evaluate("() => window.__excalidraw.getAppState().zoom.value")
                check("Zoom-Knopf vergrößert", zoom1 > zoom0, f"({zoom0} -> {zoom1})")
                shown = page.locator(".deck-zoom .deck-zoom-value").inner_text().strip()
                check(
                    "Zoom-Anzeige zeigt Prozentwert",
                    shown == f"{round(zoom1 * 100)} %",
                    f"(shown={shown!r}, erwartet {round(zoom1 * 100)} %)",
                )
                click_toolbar_title(page, "Herauszoomen (Strg+-)")
                page.wait_for_timeout(200)
                zoom2 = page.evaluate("() => window.__excalidraw.getAppState().zoom.value")
                check("Zoom-Knopf verkleinert", zoom2 < zoom1, f"({zoom1} -> {zoom2})")
                click_toolbar_title(page, "Zoom auf 100 % zurücksetzen (Strg+0)")
                page.wait_for_timeout(200)
                zoom3 = page.evaluate("() => window.__excalidraw.getAppState().zoom.value")
                check("Prozentanzeige setzt Zoom auf 100 %", abs(zoom3 - 1) < 0.001, f"(zoom={zoom3})")
                click_toolbar_title(page, "Aktuelle Folie einpassen")
                page.wait_for_timeout(300)
                zoom4 = page.evaluate("() => window.__excalidraw.getAppState().zoom.value")
                check("Fit passt Folie ein (Zoom weicht von 100 % ab)", abs(zoom4 - 1) > 0.01, f"(zoom={zoom4})")

                # Zoom-Untergrenze: Knopf deaktiviert bei 10 %.
                click_toolbar_title(page, "Zoom auf 100 % zurücksetzen (Strg+0)")
                page.wait_for_timeout(200)
                for _ in range(9):
                    click_toolbar_title(page, "Herauszoomen (Strg+-)")
                    page.wait_for_timeout(60)
                zoom_min = page.evaluate("() => window.__excalidraw.getAppState().zoom.value")
                check("Zoom stoppt bei 10 %", abs(zoom_min - 0.1) < 0.001, f"(zoom={zoom_min})")
                check(
                    "Herauszoomen am Minimum deaktiviert",
                    page.get_by_title("Herauszoomen (Strg+-)").is_disabled(),
                )
                click_toolbar_title(page, "Zoom auf 100 % zurücksetzen (Strg+0)")
                page.wait_for_timeout(200)

                # Verschieben: Hand-Werkzeug aktivieren und wieder zum Stift.
                click_toolbar_title(page, "Verschieben: Leinwand mit gedrücktem Stift/Finger schieben, ohne zu zeichnen")
                page.wait_for_timeout(200)
                tool = page.evaluate("() => window.__excalidraw.getAppState().activeTool.type")
                check("Verschieben aktiviert Hand-Werkzeug", tool == "hand", f"(tool={tool})")
                click_toolbar_title(page, "Stift (Stylus zeichnet direkt auf die Folie)")
                page.wait_for_timeout(200)
                tool = page.evaluate("() => window.__excalidraw.getAppState().activeTool.type")
                check("Stift stellt Freedraw wieder her", tool == "freedraw", f"(tool={tool})")

                # Undo/Redo ueber die Palette.
                click_toolbar_title(page, "Rückgängig (Strg+Z)")
                page.wait_for_timeout(300)
                n = page.evaluate("() => window.__excalidraw.getSceneElements().length")
                check("Rückgängig entfernt letzten Strich", n == base + 1, f"(n={n}, base={base})")
                click_toolbar_title(page, "Wiederholen (Strg+Umschalt+Z)")
                page.wait_for_timeout(300)
                n = page.evaluate("() => window.__excalidraw.getSceneElements().length")
                check("Wiederholen stellt den Strich wieder her", n == base + 2, f"(n={n}, base={base})")

                # Folie leeren: nur Anmerkungen (Freedraw) verschwinden.
                click_toolbar_title(page, "Stiftstriche auf dieser Folie löschen")
                page.wait_for_timeout(300)
                n = page.evaluate("() => window.__excalidraw.getSceneElements().length")
                check("Folie leeren entfernt Anmerkungen", n == base, f"(n={n}, base={base})")
                click_toolbar_title(page, "Rückgängig (Strg+Z)")
                page.wait_for_timeout(300)
                n = page.evaluate("() => window.__excalidraw.getSceneElements().length")
                check("Folie leeren ist rückgängig machbar", n == base + 2, f"(n={n}, base={base})")

                with page.expect_download() as dl_info:
                    click_toolbar_title(page, "Als .excalidraw speichern")
                dl_info.value.save_as(OUT)
                with open(OUT, encoding="utf-8") as f:
                    saved = json.load(f)
                types = {el["type"] for el in saved["elements"]}
                check("Gespeicherte Szene enthaelt Frames", "frame" in types)
                check("Gespeicherte Szene enthaelt Gezeichnetes (freedraw)", "freedraw" in types)
                families = {
                    el.get("fontFamily")
                    for el in saved["elements"]
                    if el["type"] == "text"
                }
                check(
                    "Gespeicherte Szene nutzt Excalifont (5) und Normal (2)",
                    families == {5, 2},
                    str(families),
                )
                check("Keine JS-Fehler auf der Seite", len(errors) == 0, str(errors[:2]))

                # Frameless-Deck: gesamte Leinwand als eine Folie.
                click_toolbar_title(page, "Editor-Werkzeuge anzeigen")
                page.wait_for_timeout(300)
                check(
                    "Zoom-Widget im Bearbeitungsmodus ausgeblendet",
                    page.locator(".deck-zoom").count() == 0,
                )
                frameless = Path(tmp) / "frameless.excalidraw"
                frameless.write_text(
                    json.dumps(
                        {
                            "type": "excalidraw",
                            "version": 2,
                            "elements": [
                                {
                                    "type": "text",
                                    "id": "t1",
                                    "x": 100,
                                    "y": 100,
                                    "width": 200,
                                    "height": 40,
                                    "text": "Freie Leinwand",
                                    "isDeleted": False,
                                }
                            ],
                            "files": {},
                        }
                    ),
                    encoding="utf-8",
                )
                page.set_input_files("input[type=file]", str(frameless))
                page.wait_for_timeout(1200)
                check("Frameless-Deck zeigt 1 / 1", page.locator("text=1 / 1").count() >= 1)
                check(
                    "Frameless-Hinweis sichtbar",
                    page.locator(".deck-frameless-hint").count() == 1,
                )

                # Ungespeichert-Punkt nach Zeichnung; Strg+S speichert und entfernt ihn.
                page.mouse.click(cx, cy)
                page.mouse.move(cx, cy)
                page.mouse.down()
                page.mouse.move(cx + 90, cy + 40, steps=4)
                page.mouse.up()
                page.wait_for_timeout(500)
                check(
                    "Ungespeichert-Punkt nach Zeichnung",
                    page.locator(".deck-dirty-dot").count() == 1,
                )
                with page.expect_download() as ctrl_info:
                    page.keyboard.press("Control+s")
                ctrl_info.value.save_as(OUT)
                page.wait_for_timeout(500)
                check(
                    "Strg+S speichert und entfernt den Ungespeichert-Punkt",
                    page.locator(".deck-dirty-dot").count() == 0,
                )
                check("Keine JS-Fehler nach Frameless- und Speicherchecks", len(errors) == 0, str(errors[:2]))

                check_template_annotations(browser, tmp)
                check_drawing_tools(browser, tmp)
                run_checks(browser, URL, tmp, check)
                run_lesson_checks(browser, URL, tmp, check)
                browser.close()
        finally:
            server.terminate()

    writing = subprocess.run([sys.executable, str(Path(__file__).with_name("writing_gestures_test.py"))], timeout=120)
    check("Schreiben: Geometrie, Zoom, History, Speichern, Kopie und PDF", writing.returncode == 0)
    print()
    if failures:
        print("FEHLER:", ", ".join(failures))
        sys.exit(1)
    print("Alle Checks bestanden.")


if __name__ == "__main__":
    main()
