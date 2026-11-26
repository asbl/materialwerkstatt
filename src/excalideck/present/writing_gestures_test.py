"""Regression: Pinch mit Stiftmodus und Schreiben über den Folienrand."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

from playwright.sync_api import sync_playwright
from regression_test import SCENE

def run():
    with tempfile.TemporaryDirectory() as directory, sync_playwright() as pw:
        fixture = Path(directory) / "writing.excalidraw"
        fixture.write_text(json.dumps({**SCENE,"elements":[*SCENE["elements"],
            {"id":"cropped-original","type":"rectangle","x":-500,"y":100,"width":600,"height":100,
             "frameId":"frame","backgroundColor":"#00ff00","strokeColor":"#00ff00","fillStyle":"solid","roughness":0}]}))
        browser = pw.chromium.launch()
        p = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.goto("http://127.0.0.1:4188")
        p.wait_for_selector("canvas")
        p.set_input_files("input[type=file]", str(fixture))
        p.wait_for_timeout(500)
        if p.get_by_title("Präsentationsmodus starten", exact=True).is_visible():
            p.get_by_title("Präsentationsmodus starten", exact=True).click()
        p.get_by_role("button", name="Stift", exact=True).click()
        p.get_by_role("button", name="Extra fein", exact=True).click()
        assert p.evaluate("(()=>{const s=window.__excalidraw.getAppState();return Math.abs(s.currentItemStrokeWidth*s.zoom.value-.5)<1e-6})()")
        # New strokes keep their screen width at 50%, 100%, 400%, 1000%.
        prior = []
        for zoom in (.5, 1, 4, 10):
            p.evaluate("z=>window.__excalidraw.updateScene({appState:{zoom:{value:z},scrollX:0,scrollY:0}})", zoom)
            p.wait_for_timeout(100)
            p.mouse.move(500,350); p.mouse.down(); p.mouse.move(550,380,steps=6); p.mouse.up()
            p.wait_for_timeout(100)
            strokes = p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='freedraw')")
            assert len(strokes[-1]["points"]) > 2 and strokes[-1]["width"] > 0 and strokes[-1]["height"] > 0, strokes[-1]
            assert abs(strokes[-1]["strokeWidth"] * zoom - .5) < 1e-6
            assert [e["strokeWidth"] for e in strokes[:-1]] == prior
            prior = [e["strokeWidth"] for e in strokes]
        p.get_by_role("button",name="Zeichenoptionen",exact=True).click()
        p.get_by_role("button",name="Strichstärke: Fein",exact=True).click()
        p.keyboard.press("Escape")
        assert p.evaluate("window.__excalidraw.getAppState().currentItemStrokeWidth") == .1
        p.get_by_role("button",name="Extra fein",exact=True).click()
        p.evaluate("window.__excalidraw.updateScene({appState:{zoom:{value:1},scrollX:0,scrollY:0}})")
        p.wait_for_timeout(100)
        cdp = p.context.new_cdp_session(p)
        # Trusted pen events exercise the same completion path as a real stylus.
        cdp.send("Input.dispatchMouseEvent",dict(type="mousePressed",x=400,y=400,button="left",buttons=1,clickCount=1,pointerType="pen",force=.5))
        for x in range(410,481,10):
            cdp.send("Input.dispatchMouseEvent",dict(type="mouseMoved",x=x,y=400+(x-400)/2,button="none",buttons=1,pointerType="pen",force=.5))
        cdp.send("Input.dispatchMouseEvent",dict(type="mouseReleased",x=480,y=440,button="left",buttons=0,clickCount=1,pointerType="pen"))
        p.wait_for_timeout(100)
        pen=p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='freedraw').at(-1)")
        assert len(pen["points"])>2 and pen["customData"]["annotationSlide"]=="frame"
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        def touch(kind, points):
            cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [dict(x=x,y=y,id=i) for i,(x,y) in enumerate(points)]})
            p.wait_for_timeout(60)
        def camera():
            return p.evaluate("(()=>{const s=window.__excalidraw.getAppState(); return [s.zoom.value,s.scrollX,s.scrollY]})()")
        before = camera()
        count = p.evaluate("window.__excalidraw.getSceneElements().length")
        touch("touchStart", [(600,400)])
        touch("touchMove", [(620,410)])
        after = camera()
        assert abs(after[1]-before[1]-20/before[0]) < 1
        touch("touchStart", [(620,410),(820,410)])
        for delta in range(10,81,10):
            touch("touchMove", [(620-delta,410),(820+delta,410)])
        assert camera()[0] > before[0]*1.6, (before,camera())
        touch("touchEnd", [])
        assert p.evaluate("window.__excalidraw.getSceneElements().length") == count
        # Bring the frame's left edge into the viewport; write just outside it.
        p.evaluate("window.__excalidraw.updateScene({appState:{zoom:{value:.5},scrollX:600,scrollY:400}})")
        p.wait_for_timeout(200)
        p.get_by_role("button",name="Dick",exact=True).click()
        p.get_by_role("button",name="Stiftfarbe",exact=True).click()
        p.get_by_title("Farbe #e03131",exact=True).click();p.keyboard.press("Escape")
        p.mouse.move(200,350); p.mouse.down(); p.mouse.move(240,380,steps=8); p.mouse.up()
        p.wait_for_timeout(300)
        stroke = p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='freedraw').at(-1)")
        assert stroke and stroke["x"] < 0 and stroke["opacity"] > 0, stroke
        assert len(stroke["points"]) > 2 and stroke["width"] > 0 and stroke["height"] > 0
        assert stroke["customData"]["annotationSlide"] == "frame"
        # A single undo removes the complete stroke; redo restores geometry/ownership.
        p.get_by_title("Rückgängig (Strg+Z)",exact=True).click();p.wait_for_timeout(150)
        assert not p.evaluate("id=>window.__excalidraw.getSceneElements().some(e=>e.id===id)",stroke["id"])
        p.get_by_title("Wiederholen (Strg+Umschalt+Z)",exact=True).click();p.wait_for_timeout(150)
        restored=p.evaluate("id=>window.__excalidraw.getSceneElements().find(e=>e.id===id)",stroke["id"])
        assert restored["points"] == stroke["points"] and restored["customData"]["annotationSlide"] == "frame"
        with p.expect_download() as dl:p.keyboard.press("Control+s")
        saved=Path(directory)/"saved.excalidraw";dl.value.save_as(str(saved))
        reopened=browser.new_page();reopened.goto("http://127.0.0.1:4188");reopened.wait_for_selector("canvas")
        reopened.set_input_files("input[type=file]",str(saved));reopened.wait_for_timeout(500)
        loaded=reopened.evaluate("id=>window.__excalidraw.getSceneElements().find(e=>e.id===id)",stroke["id"])
        assert loaded["points"]==stroke["points"] and loaded["customData"]["annotationSlide"]=="frame"
        reopened.close()
        p.get_by_role("button",name="PDF exportieren",exact=True).click()
        with p.expect_download() as dl:p.get_by_role("button",name="PDF mit Lösungen",exact=True).click()
        pdf=Path(directory)/"outside.pdf";dl.value.save_as(str(pdf));p.keyboard.press("Escape")
        doc=pymupdf.open(pdf);pix=doc[0].get_pixmap();rgb=pix.samples
        red_pixels=sum(rgb[i]>150 and rgb[i+1]<130 and rgb[i+2]<130 for i in range(0,len(rgb),pix.n))
        assert red_pixels>10, dict(red_pixels=red_pixels,stroke=restored,page=(pix.width,pix.height))
        green_x=[(i//pix.n)%pix.width for i in range(0,len(rgb),pix.n) if rgb[i]<100 and rgb[i+1]>180 and rgb[i+2]<100]
        assert green_x and min(green_x)>50, "Originalgrafik darf außerhalb ihres Frames nicht sichtbar werden"
        expected_strokes=p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='freedraw').length")
        p.get_by_role("button",name="Folienübersicht",exact=True).click()
        p.get_by_role("button",name="Folie 1 duplizieren",exact=True).click();p.wait_for_timeout(300)
        p.get_by_role("button",name="Folie 2 anzeigen",exact=True).click();p.wait_for_timeout(200)
        copied=p.evaluate("window.__excalidrawNative.getSceneElements().filter(e=>e.type==='freedraw'&&e.opacity>0)")
        assert len(copied)==expected_strokes, len(copied)
        assert all(e["frameId"] != "frame" and e["customData"]["annotationSlide"] == e["frameId"] for e in copied)
        p.get_by_role("button",name="Folienübersicht schließen",exact=True).click()
        p.get_by_role("button",name="Weitere Werkzeuge",exact=True).click()
        p.get_by_title("Editor-Werkzeuge anzeigen",exact=True).click();p.wait_for_timeout(150)
        p.evaluate("window.__excalidraw.setActiveTool({type:'freedraw'})");p.wait_for_timeout(100)
        p.evaluate("window.__excalidraw.updateScene({appState:{zoom:{value:1},currentItemStrokeWidth:8}})");p.wait_for_timeout(100)
        p.evaluate("window.__excalidraw.updateScene({appState:{currentItemStrokeWidth:4}})");p.wait_for_timeout(100)
        assert p.evaluate("window.__excalidraw.getAppState().currentItemStrokeWidth")==4

        assert not errors, errors
        browser.close()
        print("PASS: vollständige Striche, Zoomstärke, Finger-Pan/Pinch, Undo/Redo, Wiederöffnen, Randnotizen-PDF, Folienkopie, Editor-Stärke")

if __name__ == "__main__":
    server = subprocess.Popen([sys.executable,"-m","http.server","4188","--bind","127.0.0.1","-d",str(Path(__file__).parent/"dist")],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        run()
    finally:
        server.terminate()
