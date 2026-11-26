"""Browser-Regressionen aus dem Slides-UI-Audit (lokale Fixtures, keine Remote-API)."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from ui_test_helpers import click_toolbar_title, mock_material_protocol

SCENE = {"type": "excalidraw", "version": 2, "files": {}, "elements": [
    {"id": "paper", "type": "rectangle", "x": 0, "y": 0, "width": 1600, "height": 900,
     "frameId": "frame", "backgroundColor": "#ffffff", "fillStyle": "solid", "roughness": 0},
    {"id": "original", "type": "text", "x": 120, "y": 120, "width": 150, "height": 30,
     "frameId": "frame", "text": "Original", "fontSize": 24, "fontFamily": 2},
    {"id": "frame", "type": "frame", "name": "A", "x": 0, "y": 0, "width": 1600, "height": 900},
    {"id": "frame-2", "type": "frame", "name": "B", "x": 0, "y": 1200, "width": 1600, "height": 900},
]}


def run_checks(browser, url, directory, check):
    fixture = Path(directory) / "regression.excalidraw"
    fixture.write_text(json.dumps(SCENE))
    errors = []

    def standalone(width=1440, height=1000):
        p = browser.new_page(viewport={"width": width, "height": height})
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.goto(url)
        try:
            p.wait_for_selector("canvas", timeout=10000)
        except Exception:
            print("Browserfehler:", errors, p.locator("body").inner_text()[:1000], flush=True)
            p.screenshot(path="/tmp/excalideck-regression-error.png")
            raise
        p.set_input_files("input[type=file]", str(fixture))
        p.wait_for_timeout(300)
        return p

    def material(revision=None, hold=False):
        p = browser.new_page(viewport={"width": 1440, "height": 1000})
        p.on("pageerror", lambda e: errors.append(str(e)))
        context = {"requests": [], "pending": [], "revision": revision}

        def route(r):
            path = urlsplit(r.request.url).path
            if path.endswith("/save"):
                context["requests"].append({"target": path, **r.request.post_data_json})
                if hold:
                    context["pending"].append(r)
                    return
                if path.endswith("annotations/save") and r.request.post_data_json["revision"] != context["revision"]:
                    r.fulfill(status=409, json={"error": "Konflikt"})
                    return
                context["revision"] = "saved-rev"
                r.fulfill(json={"revision": "saved-rev"})
            elif path.endswith("/annotations"):
                r.fulfill(json={"elements": [], "files": {}}, headers={"X-Material-Revision": context["revision"]} if context["revision"] else {})
            elif path.endswith("/history"):
                r.fulfill(json={"versions": [{"id": "past", "created": 1700000000}]})
            elif path.endswith("/history/past"):
                older = {**SCENE, "elements": [{**el, "text": "Frühere Fassung"} if el["id"] == "original" else el for el in SCENE["elements"]]}
                r.fulfill(json={"text": json.dumps(older)})
            elif path.endswith("/revision"):
                r.fulfill(json={"revision": "deck-rev"})
            else:
                r.fulfill(json=SCENE, headers={"X-Material-Revision": "deck-rev"})

        mock_material_protocol(p)
        p.route("**/api/deck**", route)
        p.add_init_script("window.__MATERIAL_TOKEN__ = 'regression';")
        p.goto(url + "?path=original.excalidraw")
        try:
            p.wait_for_selector(".presenting", timeout=5000)
        except Exception:
            print("Material-Browserfehler:", errors, p.url, p.locator("body").inner_text()[:1600], flush=True)
            p.screenshot(path="/tmp/excalideck-material-error.png")
            raise
        p.wait_for_timeout(300)
        return p, context

    def add(p, identifier):
        p.evaluate("""id => {const a = window.__excalidraw, source=a.getSceneElements().find(e=>e.id==='original');
            a.updateScene({elements:[...a.getSceneElements(), {...source,id,x:400,text:id,originalText:id,locked:false}]});}
        """, identifier)
        p.wait_for_timeout(80)

    p, context = material("existing-sidecar")
    add(p, "annotation")
    p.keyboard.press("Control+s")
    p.wait_for_timeout(200)
    check("Sidecar übernimmt Header-Revision", context["requests"][-1]["revision"] == "existing-sidecar")
    check("Vorhandener Sidecar speichert ohne falschen Konflikt", p.get_by_role("alertdialog").count() == 0)
    p.close()

    for full in (False, True):
        p, context = material(hold=True)
        if full:
            click_toolbar_title(p, "Anmerkungen separat speichern: nur Anmerkungen werden gespeichert, das Deck bleibt unberührt")
        add(p, "before-save")
        p.keyboard.press("Control+s")
        p.wait_for_timeout(100)
        p.keyboard.press("Control+s")
        p.wait_for_timeout(50)
        check(f"Nur eine Speicheranfrage gleichzeitig ({full=})", len(context["requests"]) == 1)
        add(p, "during-save")
        context["pending"][0].fulfill(json={"revision": "saved-rev"})
        p.wait_for_timeout(200)
        check(f"Neue Anmerkung überlebt laufendes Speichern ({full=})", p.evaluate("window.__excalidraw.getSceneElements().some(e=>e.id==='during-save')"))
        check(f"Neuere Änderungen bleiben ungespeichert ({full=})", p.locator(".deck-dirty-dot").count() == 1)
        p.keyboard.press("Control+s")
        p.wait_for_timeout(100)
        request = context["requests"][-1]
        check(f"Folgespeicherung enthält neue Anmerkung ({full=})", any(e["id"] == "during-save" for e in json.loads(request["scene"])["elements"]))
        check(f"Folgespeicherung nutzt neue Revision ({full=})", request["revision"] == "saved-rev")
        context["pending"][-1].fulfill(json={"revision": "saved-rev-2"})
        p.wait_for_timeout(100)
        check(f"Erst die Folgespeicherung setzt sauber ({full=})", p.locator(".deck-dirty-dot").count() == 0)
        p.close()

    for full in (False, True):
        p, context = material(hold=True)
        if full:
            click_toolbar_title(p, "Anmerkungen separat speichern: nur Anmerkungen werden gespeichert, das Deck bleibt unberührt")
        add(p, "mutable")
        p.keyboard.press("Control+s")
        p.wait_for_timeout(100)
        p.evaluate("""() => { const a=window.__excalidraw; const e=a.getSceneElements().find(e=>e.id==='mutable'); e.text='Während Speichern bearbeitet';e.originalText=e.text;e.version++;e.versionNonce++;a.updateScene({elements:a.getSceneElements()}); }""")
        context["pending"][0].fulfill(json={"revision": "saved-rev"})
        p.wait_for_timeout(100)
        check(f"Änderung am selben Objekt bleibt nach Speichern ungespeichert ({full=})", p.locator(".deck-dirty-dot").count() == 1)
        p.keyboard.press("Control+s")
        p.wait_for_timeout(100)
        check(f"Folgespeicherung erfasst bearbeitetes Objekt ({full=})", any(e.get("text") == "Während Speichern bearbeitet" for e in json.loads(context["requests"][-1]["scene"])["elements"]))
        context["pending"][-1].fulfill(json={"revision": "saved-rev-2"})
        p.wait_for_timeout(100)
        check(f"Bearbeitetes Objekt wird nach Folgespeicherung sauber ({full=})", p.locator(".deck-dirty-dot").count() == 0)
        p.close()

    p, context = material()
    click_toolbar_title(p, "Folienhintergrund schützen")
    check("Entsperren zeigt vollständigen Speichermodus", p.get_by_title("Gesamte Szene in die Deck-Datei speichern (Strg+S)", exact=True).count() == 1)
    p.evaluate("""() => {const a=window.__excalidraw;a.updateScene({elements:a.getSceneElements().map(e=>e.id==='original'?{...e,text:'Bearbeitet',originalText:'Bearbeitet',version:e.version+1}:e)});} """)
    p.keyboard.press("Control+s")
    p.wait_for_timeout(150)
    check("Bearbeitete Originaltexte werden vollständig gespeichert", any(e.get("text") == "Bearbeitet" for e in json.loads(context["requests"][-1]["scene"])["elements"]))
    p.close()

    p, context = material()
    add(p, "unsaved-history")
    click_toolbar_title(p, "Frühere Fassungen der Deck-Datei laden")
    p.get_by_role("button", name="Laden", exact=True).click()
    check("Versionswechsel schützt ungespeicherte Arbeit", p.get_by_role("button", name="Verwerfen und wechseln", exact=True).is_visible())
    p.get_by_role("button", name="Verwerfen und wechseln", exact=True).click()
    p.wait_for_timeout(200)
    check("Geladene Version bleibt ungespeichert", p.locator(".deck-dirty-dot").count() == 1)
    check("Version wird als vollständiges Deck angeboten", p.get_by_title("Gesamte Szene in die Deck-Datei speichern (Strg+S)", exact=True).is_visible())
    click_toolbar_title(p, "Folienhintergrund schützen")
    check("Lokaler Schlosswechsel verliert Versionsänderung nicht", p.locator(".deck-dirty-dot").count() == 1)
    p.keyboard.press("Control+s")
    p.wait_for_timeout(150)
    check("Versionsübernahme speichert die ältere Fassung", any(e.get("text") == "Frühere Fassung" for e in json.loads(context["requests"][-1]["scene"])["elements"]))
    p.close()

    p = standalone()
    add(p, "unsaved")
    click_toolbar_title(p, "Editor-Werkzeuge anzeigen")
    p.set_input_files("input[type=file]", str(fixture))
    p.get_by_role("button", name="Auf dieser Folie bleiben", exact=True).click()
    check("Abgebrochener Dateiwechsel behält Zeichnung", p.evaluate("window.__excalidraw.getSceneElements().some(e=>e.id==='unsaved')"))
    check("Abbruch verlässt die Folienansicht nicht", p.locator(".deck-dialog-backdrop").count() == 0)
    p.set_input_files("input[type=file]", str(fixture))
    with p.expect_download():
        p.get_by_role("button", name="Speichern und wechseln", exact=True).click()
    p.wait_for_timeout(150)
    check("Speichern und Wechseln lädt das neue Deck", not p.evaluate("window.__excalidraw.getSceneElements().some(e=>e.id==='unsaved')"))
    add(p, "discarded")
    click_toolbar_title(p, "Editor-Werkzeuge anzeigen")
    p.set_input_files("input[type=file]", str(fixture))
    p.get_by_role("button", name="Verwerfen und wechseln", exact=True).click()
    p.wait_for_timeout(150)
    check("Explizites Verwerfen wechselt das Deck", not p.evaluate("window.__excalidraw.getSceneElements().some(e=>e.id==='discarded')"))
    click_toolbar_title(p, "Editor-Werkzeuge anzeigen")
    invalid = Path(directory) / "invalid.excalidraw"
    invalid.write_text("{invalid")
    p.set_input_files("input[type=file]", str(invalid))
    p.wait_for_timeout(100)
    check("Ungültiger Import zeigt verständlichen Fehler", p.locator(".deck-error").count() == 1)
    check("Ungültiger Import erhält die Szene", p.evaluate("window.__excalidraw.getSceneElements().length") == 4)
    p.close()

    p, context = material()
    click_toolbar_title(p, "Editor-Werkzeuge anzeigen")
    p.set_input_files("input[type=file]", str(fixture))
    p.wait_for_timeout(150)
    with p.expect_download():
        p.keyboard.press("Control+s")
    check("Dateiimport trennt vorherigen Material-Speicherpfad", not context["requests"])
    p.close()

    p = standalone()
    click_toolbar_title(p, "Folienhintergrund schützen")
    click_toolbar_title(p, "Rückgängig (Strg+Z)")
    p.wait_for_timeout(100)
    check("Erster Undo entfernt das geladene Deck nicht", p.evaluate("window.__excalidraw.getSceneElements().length") == 4)
    p.get_by_role("button", name="Weitere Werkzeuge", exact=True).click()
    locked = p.evaluate("window.__excalidraw.getSceneElements().find(e=>e.id==='paper')?.locked")
    check("Schloss folgt Undo", p.get_by_role("button", name="Folienhintergrund schützen", exact=True).get_attribute("aria-pressed") == str(bool(locked)).lower(), str(p.evaluate("({pressed:document.querySelector('[aria-label=\"Folienhintergrund schützen\"]').getAttribute('aria-pressed'),canonical:window.__excalidraw.getSceneElements().map(e=>({id:e.id,locked:e.locked})),native:window.__excalidrawNative?.getSceneElements().map(e=>({id:e.id,locked:e.locked,hint:e.customData?.__excalideckProjection}))})")))
    p.keyboard.press("Escape")
    p.evaluate("""() => {const a=window.__excalidraw;a.updateScene({elements:a.getSceneElements().map(e=>e.id==='frame'?{...e,x:3000,version:e.version+1}:e)});} """)
    click_toolbar_title(p, "Aktuelle Folie einpassen")
    state = p.evaluate("window.__excalidraw.getAppState()")
    check("Fit benutzt aktuelle Frame-Koordinaten", abs((3800 + state["scrollX"]) * state["zoom"]["value"] - state["width"]/2) < 2)
    p.close()

    for width, height in ((1440,1000), (1280,720), (1024,768), (768,1024), (390,844)):
        p = standalone(width, height)
        box = p.locator(".deck-toolbar").bounding_box()
        check(f"Toolbar bleibt kompakt bei {width}px", box["height"] < height * .23)
        outside = p.evaluate("""() => [...document.querySelectorAll('.deck-toolbar button')].some(e=>{const r=e.getBoundingClientRect();return r.width && (r.left<0||r.right>innerWidth||r.bottom>innerHeight)});""")
        check(f"Toolbar bleibt im Viewport bei {width}px", not outside)
        p.get_by_role("button", name="Zeichenoptionen", exact=True).click()
        panel = p.locator(".deck-dropup-panel").bounding_box()
        check(f"Zeichenoptionen vollständig erreichbar bei {width}px", panel["x"] >= 0 and panel["y"] >= 0 and panel["x"]+panel["width"] <= width and panel["y"]+panel["height"] <= height)
        check(f"Stift zeigt keine Pfeiloptionen bei {width}px", p.get_by_role("button", name="Pfeiltyp: Eckig", exact=True).count() == 0)
        p.keyboard.press("Escape")
        check(f"Escape gibt Menüfokus zurück bei {width}px", p.get_by_role("button", name="Zeichenoptionen", exact=True).evaluate("e=>e===document.activeElement"))
        p.screenshot(path=f"/tmp/excalideck-ui-{width}.png")
        if width == 390:
            native_visible = p.evaluate("""() => [...document.querySelectorAll('.excalidraw button')].some(e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden')""")
            check("Mobile native Palette ist im Präsentationsmodus ausgeblendet", not native_visible)
        p.close()

    p = standalone()
    add(p, "deleted-annotation")
    p.evaluate("""() => {const a=window.__excalidraw;a.updateScene({elements:a.getSceneElementsIncludingDeleted().map(e=>e.id==='deleted-annotation'?{...e,isDeleted:true,version:e.version+1}:e)});} """)
    with p.expect_download():
        p.keyboard.press("Control+s")
    click_toolbar_title(p, "Folienhintergrund schützen")
    check("Gelöschte Historienelemente erzeugen nach Speichern keinen falschen Dirty-Status", p.locator(".deck-dirty-dot").count() == 0)
    p.close()

    p = standalone()
    p.get_by_role("button", name="Geometriehilfen", exact=True).click()
    p.get_by_role("button", name="Zirkel", exact=True).click()
    p.get_by_role("button", name="Kreis zeichnen", exact=True).click()
    p.wait_for_timeout(80)
    first = p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='ellipse').at(-1)")
    click_toolbar_title(p, "Hineinzoomen (Strg+ +)")
    p.get_by_role("button", name="Kreis zeichnen", exact=True).click()
    p.wait_for_timeout(80)
    second = p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='ellipse').at(-1)")
    check("Zirkelradius bleibt beim Zoomen gleich", first["width"] == second["width"] == 200)
    check("Geometriehilfe behält ihren Mittelpunkt beim Zoomen", first["x"] == second["x"] and first["y"] == second["y"])
    p.get_by_role("button", name="Geometriehilfe schließen", exact=True).click()
    p.close()

    p = standalone()
    add(p, "selected")
    click_toolbar_title(p, "Auswahl: Anmerkungen verschieben oder löschen")
    p.evaluate("window.__excalidraw.updateScene({appState:{selectedElementIds:{selected:true}}})")
    p.get_by_role("button", name="Zeichenoptionen", exact=True).click()
    p.get_by_title("Auswahl löschen", exact=True).click()
    p.wait_for_timeout(100)
    check("Löschen bereinigt Auswahl und Optionen", p.locator(".deck-dropup-panel small").inner_text() == "Für neue Zeichnungen" and p.get_by_title("Auswahl löschen", exact=True).is_disabled())
    p.keyboard.press("Escape")
    click_toolbar_title(p, "Stift (Stylus zeichnet direkt auf die Folie)")
    p.get_by_role("button", name="Zeichenoptionen", exact=True).click()
    p.keyboard.press("ArrowRight")
    check("Offene Zeichenoptionen blockieren Foliennavigation", p.locator(".deck-counter").inner_text() == "1 / 2")
    p.keyboard.press("Escape")
    p.evaluate("""() => { const stringify=JSON.stringify; window.sceneSerializations=0; JSON.stringify=function(value,...args){if(Array.isArray(value)&&value[0]?.type)window.sceneSerializations++;return stringify.call(JSON,value,...args)}; }""")
    for _ in range(3):
        p.evaluate("window.__excalidraw.updateScene({appState:{scrollX:window.__excalidraw.getAppState().scrollX+1}})")
        p.wait_for_timeout(50)
    check("Kamerabewegung serialisiert kein vollständiges Deck", p.evaluate("window.sceneSerializations") == 0)
    p.close()
    check("Keine JS-Fehler in Audit-Regressionen", not errors, str(errors[:3]))


if __name__ == "__main__":
    import subprocess
    import sys
    import tempfile
    from playwright.sync_api import sync_playwright

    failed = []

    def check(name, condition, detail=""):
        print(f"[{'PASS' if condition else 'FAIL'}] {name} {detail}", flush=True)
        if not condition:
            failed.append(name)

    server = subprocess.Popen([sys.executable, "-m", "http.server", "4186", "--bind", "127.0.0.1", "-d", str(Path(__file__).parent / "dist")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with tempfile.TemporaryDirectory() as directory, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            run_checks(browser, "http://127.0.0.1:4186/index.html", directory, check)
            browser.close()
    finally:
        server.terminate()
    sys.exit(bool(failed))
