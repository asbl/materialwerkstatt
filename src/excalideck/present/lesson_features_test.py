"""Unterrichtsfunktionen: echte Browserinteraktionen, PDFs und lokale Wiederherstellung."""
import base64
import copy
import json
import math
from pathlib import Path

import pymupdf
from regression_test import SCENE
from ui_test_helpers import click_toolbar_title


def run_lesson_checks(browser, url, directory, check):
    scene = copy.deepcopy(SCENE)
    scene["elements"].insert(2, {"id": "solution", "type": "rectangle", "frameId": "frame", "x": 700, "y": 300,
        "width": 300, "height": 200, "strokeColor": "#e03131", "backgroundColor": "#e03131", "fillStyle": "solid", "roughness": 0,
        "customData": {"solutionStep": 1, "presenterAnnotation": True}})
    fixture = Path(directory) / "lesson.excalidraw"
    fixture.write_text(json.dumps(scene))
    errors = []

    def page():
        p = browser.new_page(viewport={"width": 1440, "height": 1000})
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.on("dialog", lambda d: d.accept())
        p.goto(url)
        p.wait_for_selector("canvas")
        p.set_input_files("input[type=file]", str(fixture))
        p.wait_for_timeout(350)
        return p

    def add(p, identifier, text="Notiz"):
        # Simulierte Inhaltsänderungen müssen wie echte Benutzereingaben in
        # Excalidraws Historie landen; EVENTUALLY lässt API-Elemente uncommitted.
        p.evaluate("""([id,text])=>{const a=window.__excalidraw,source=a.getSceneElements().find(e=>e.id==='original');a.updateScene({captureUpdate:'IMMEDIATELY',elements:[...a.getSceneElements(),{...source,id,text,originalText:text,x:400,y:400,locked:false,customData:{presenterAnnotation:true}}]});}""",[identifier,text])
        p.wait_for_timeout(80)

    from geometry_size_test import run_geometry_size_checks
    run_geometry_size_checks(page, check)

    from touch_tools_test import run_touch_checks
    run_touch_checks(page, check)

    p = page()
    check("Präsentation blendet Nachbarfolie aus", p.evaluate("window.__excalidrawNative.getSceneElements().find(e=>e.id==='frame-2').opacity") == 0)
    check("Kanonische Nachbarfolie bleibt vollständig erhalten", p.evaluate("window.__excalidraw.getSceneElements().find(e=>e.id==='frame-2').opacity") == 100)
    check("Lösung ist zunächst verdeckt", p.evaluate("window.__excalidrawNative.getSceneElements().find(e=>e.id==='solution').opacity") == 0)
    p.get_by_role("button",name="Lösungsschritte",exact=True).click()
    p.get_by_role("button",name="Nächsten Lösungsschritt zeigen",exact=True).click()
    p.wait_for_timeout(100)
    check("Nächster Lösungsschritt wird sichtbar", p.evaluate("window.__excalidrawNative.getSceneElements().find(e=>e.id==='solution').opacity") == 100)
    p.get_by_role("button",name="Alle Lösungen verdecken",exact=True).click()
    p.keyboard.press("Escape")
    with p.expect_download() as download:
        p.keyboard.press("Control+s")
    saved = Path(directory)/"projection.excalidraw"
    download.value.save_as(saved)
    exported = json.loads(saved.read_text())
    check("Verdeckte Lösung wird vollständig gespeichert", next(e for e in exported["elements"] if e["id"]=="solution")["opacity"]==100)
    check("Ausgeblendete Folie wird vollständig gespeichert", next(e for e in exported["elements"] if e["id"]=="frame-2")["opacity"]==100)
    p.keyboard.press("PageDown")
    p.wait_for_timeout(80)
    check("Folienwechsel blendet nur die neue Folie ein", p.evaluate("window.__excalidrawNative.getSceneElements().find(e=>e.id==='frame-2').opacity") == 100 and p.evaluate("window.__excalidrawNative.getSceneElements().find(e=>e.id==='frame').opacity")==0)
    p.close()

    p = page()
    p.get_by_role("button",name="Weitere Werkzeuge",exact=True).click()
    p.get_by_role("button",name="Nur aktuelle Folie zeigen",exact=True).click()
    p.wait_for_timeout(80)
    check("Isolierte Ansicht ist abschaltbar",p.evaluate("window.__excalidrawNative.getSceneElements().find(e=>e.id==='frame-2').opacity")==100)
    check("Ansichtswechsel erzeugt keine ungespeicherten Inhalte",p.locator(".deck-dirty-dot").count()==0)
    add(p,"step-two","Zweiter Rechenschritt")
    p.evaluate("""()=>{const a=window.__excalidraw;a.updateScene({captureUpdate:'IMMEDIATELY',elements:a.getSceneElements().map(e=>e.id==='step-two'?{...e,customData:undefined,version:e.version+1,versionNonce:e.versionNonce+1}:e)});} """)
    p.wait_for_timeout(60)
    click_toolbar_title(p,"Auswahl: Anmerkungen verschieben oder löschen")
    p.evaluate("window.__excalidraw.updateScene({appState:{selectedElementIds:{'step-two':true}}})")
    p.get_by_role("button",name="Lösungsschritte",exact=True).click()
    p.get_by_role("spinbutton",name="Lösungsschritt",exact=True).fill("2")
    p.get_by_role("button",name="Auswahl als Lösungsschritt markieren",exact=True).click()
    p.wait_for_timeout(80)
    check("Lösungsschritte sind über die Auswahl vorbereitbar",p.evaluate("window.__excalidraw.getSceneElements().find(e=>e.id==='step-two').customData?.solutionStep")==2)
    check("Neu markierter Schritt wird verdeckt",p.evaluate("window.__excalidrawNative.getSceneElements().find(e=>e.id==='step-two').opacity")==0)
    p.get_by_role("button",name="Nächsten Lösungsschritt zeigen",exact=True).click()
    p.get_by_role("button",name="Nächsten Lösungsschritt zeigen",exact=True).click()
    p.wait_for_timeout(80)
    check("Mehrere Lösungsschritte werden nacheinander aufgedeckt",p.evaluate("window.__excalidrawNative.getSceneElements().find(e=>e.id==='step-two').opacity")==100)
    p.keyboard.press("Escape")
    click_toolbar_title(p,"Rückgängig (Strg+Z)")
    p.wait_for_timeout(100)
    check("Lösungsmarkierung lässt sich rückgängig machen",not p.evaluate("window.__excalidraw.getSceneElements().find(e=>e.id==='step-two').customData?.solutionStep"))
    check("Rückgängig erhält den sichtbaren Text",p.evaluate("""()=>{const e=window.__excalidrawNative.getSceneElements().find(e=>e.id==='step-two');return e.text==='Zweiter Rechenschritt' && e.opacity===100 && !e.locked;}"""))
    click_toolbar_title(p,"Wiederholen (Strg+Umschalt+Z)")
    p.wait_for_timeout(100)
    check("Lösungsmarkierung lässt sich wiederholen",p.evaluate("window.__excalidraw.getSceneElements().find(e=>e.id==='step-two').customData?.solutionStep")==2)
    p.get_by_role("button",name="Lösungsschritte",exact=True).click()
    p.get_by_role("button",name="Alle Lösungen verdecken",exact=True).click()
    p.wait_for_timeout(80)
    check("Wiederholte Lösung lässt sich verdecken",p.evaluate("window.__excalidrawNative.getSceneElements().find(e=>e.id==='step-two').opacity")==0)
    p.keyboard.press("Escape")
    click_toolbar_title(p,"Rückgängig (Strg+Z)")
    p.wait_for_timeout(100)
    check("Rückgängig einer verdeckten Markierung zeigt den Aufgabeninhalt",p.evaluate("""()=>{const e=window.__excalidraw.getSceneElements().find(e=>e.id==='step-two');return !e.customData?.solutionStep && window.__excalidrawNative.getSceneElements().find(e=>e.id===e.id).opacity===100;}"""))
    p.close()

    p = page()
    p.get_by_role("button",name="Folienübersicht",exact=True).click()
    p.get_by_role("textbox",name="Titel Folie 1",exact=True).fill("Nicht übernehmen")
    p.get_by_role("textbox",name="Titel Folie 1",exact=True).press("Escape")
    check("Escape bricht eine Umbenennung ab",p.evaluate("window.__excalidraw.getSceneElements().find(e=>e.id==='frame').name")=="A")
    p.get_by_role("textbox",name="Titel Folie 1",exact=True).fill("Neue Überschrift")
    p.get_by_role("textbox",name="Titel Folie 1",exact=True).press("Enter")
    p.get_by_role("button",name="Folie 1 nach unten",exact=True).click()
    p.wait_for_timeout(120)
    order=p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='frame').sort((a,b)=>a.customData.presentationOrder-b.customData.presentationOrder).map(e=>e.id)")
    check("Übersicht sortiert Folien ohne Koordinatenverschiebung", order==["frame-2","frame"] and p.evaluate("window.__excalidraw.getSceneElements().find(e=>e.id==='frame').x")==0)
    check("Übersicht benennt Folien um", p.evaluate("window.__excalidraw.getSceneElements().find(e=>e.id==='frame').name")=="Neue Überschrift")
    p.evaluate("""()=>{const a=window.__excalidraw,c=document.createElement('canvas');c.width=30;c.height=20;a.addFiles([{id:'clone-image-file',dataURL:c.toDataURL(),mimeType:'image/png',created:Date.now()}]);const t=a.getSceneElements().find(e=>e.id==='paper');a.updateScene({elements:[...a.getSceneElements(),{...t,id:'clone-image',type:'image',x:200,y:500,width:60,height:40,fileId:'clone-image-file',status:'saved',scale:[1,1],crop:null,locked:false,customData:{presenterAnnotation:true}}]})}""")
    p.get_by_role("button",name="Folie 2 duplizieren",exact=True).click()
    p.wait_for_timeout(200)
    frames=p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='frame')")
    duplicate=next(e for e in frames if e["id"] not in ("frame","frame-2"))
    check("Duplizieren erzeugt eine dritte Folie", len(frames)==3)
    check("Duplizieren übernimmt alle Folieninhalte", p.evaluate("id=>window.__excalidraw.getSceneElements().filter(e=>e.frameId===id).length",duplicate["id"])==4)
    click_toolbar_title(p,"Folienhintergrund schützen")
    check("Duplizierte Folieninhalte lassen sich zum Bearbeiten entsperren",p.evaluate("id=>window.__excalidraw.getSceneElements().filter(e=>e.frameId===id&&e.type==='text').every(e=>!e.locked)",duplicate["id"]))
    check("Duplizieren erhält eingebettete Bilddateien",p.evaluate("id=>{const a=window.__excalidraw,el=a.getSceneElements().find(e=>e.frameId===id&&e.type==='image');return !!el&&!!a.getFiles()[el.fileId]}",duplicate["id"]))
    p.get_by_role("button",name="Folie 1 anzeigen",exact=True).click()
    check("Miniatur navigiert direkt zur gewünschten Folie",p.locator(".deck-counter").inner_text()=="1 / 3")
    p.wait_for_timeout(500)
    check("Miniaturen enthalten gerenderte Folien",p.locator(".deck-slide-preview canvas").first.evaluate("c=>c.width>1 && c.height>1"))
    with p.expect_download() as download:p.keyboard.press("Control+s")
    stored=Path(directory)/"ordered.excalidraw";download.value.save_as(stored)
    p.reload();p.wait_for_selector("canvas");p.set_input_files("input[type=file]",str(stored));p.wait_for_timeout(250)
    check("Folienorganisation bleibt beim Wiederöffnen erhalten",p.locator(".deck-counter").inner_text()=="1 / 3" and p.evaluate("window.__excalidraw.getSceneElements().find(e=>e.id==='frame').name")=="Neue Überschrift")
    p.close()

    p=page()
    for kind in ("dots","ruled","coordinates","number-line","grid","blank"):
        p.get_by_role("button",name="Hintergründe",exact=True).click()
        p.get_by_role("combobox",name="Hintergrundvorlage",exact=True).select_option(kind)
        p.get_by_role("spinbutton",name="Rasterabstand",exact=True).fill("50")
        if kind in ("coordinates","number-line"):p.get_by_role("spinbutton",name="Achsenskalierung",exact=True).fill("2")
        p.get_by_role("button",name="Auf aktuelle Folie anwenden",exact=True).click()
        p.keyboard.press("Escape")
        paper=p.evaluate("window.__excalidraw.getSceneElements().find(e=>e.id==='frame').customData.paper")
        check(f"Hintergrund {kind} wird mit Raster gespeichert",paper["kind"]==kind and paper["spacing"]==50)
        check(f"Hintergrund {kind} erhält Aufgabeninhalt",p.evaluate("window.__excalidraw.getSceneElements().some(e=>e.id==='original')"))
    p.close()

    p=page()
    add(p,"draft-note","Nach Browserabsturz erhalten")
    p.get_by_text("Entwurf lokal gesichert",exact=True).wait_for(timeout=6000)
    p.reload()
    p.get_by_role("button",name="Entwurf wiederherstellen",exact=True).wait_for(timeout=6000)
    p.get_by_role("button",name="Entwurf wiederherstellen",exact=True).click()
    p.wait_for_timeout(250)
    check("Lokaler Entwurf ist nach Reload ohne Dateiauswahl wiederherstellbar",p.evaluate("window.__excalidraw.getSceneElements().some(e=>e.id==='draft-note')"))
    check("Wiederhergestellter Entwurf bleibt ungespeichert",p.locator(".deck-dirty-dot").count()==1)
    p.get_by_text("Entwurf lokal gesichert",exact=True).wait_for(timeout=6000)
    p.reload();p.get_by_role("button",name="Entwurf wiederherstellen",exact=True).wait_for(timeout=6000)
    p.get_by_role("button",name="Entwurf wiederherstellen",exact=True).click();p.wait_for_timeout(180)
    check("Entwurf bleibt auch bei wiederholter Wiederherstellung vollständig",p.evaluate("window.__excalidraw.getSceneElements().some(e=>e.id==='draft-note')"))
    with p.expect_download():p.keyboard.press("Control+s")
    p.wait_for_timeout(300)

    p.reload();p.wait_for_selector("canvas");p.wait_for_timeout(150)
    check("Gespeicherter Entwurf wird nicht erneut angeboten",p.get_by_role("button",name="Entwurf wiederherstellen",exact=True).count()==0)
    p.close()

    p=page()
    click_toolbar_title(p,"Strichstärke mittel")
    click_toolbar_title(p,"Farbe #e03131")
    p.keyboard.press("Escape")
    p.get_by_role("button",name="Zeichenoptionen",exact=True).click();p.get_by_role("slider",name="Deckkraft",exact=True).fill("80");p.keyboard.press("Escape")
    click_toolbar_title(p,"Marker: dicker, halbtransparenter Strich")
    click_toolbar_title(p,"Farbe #2f9e44");p.keyboard.press("Escape")
    p.get_by_role("button",name="Zeichenoptionen",exact=True).click();p.get_by_role("slider",name="Deckkraft",exact=True).fill("45");p.keyboard.press("Escape")
    p.get_by_role("button",name="Formen",exact=True).click();p.get_by_role("button",name="Rechteck",exact=True).click()
    p.get_by_role("button",name="Zeichenoptionen",exact=True).click();p.get_by_role("button",name="Strichstärke: Dick",exact=True).click();p.get_by_role("slider",name="Deckkraft",exact=True).fill("60");p.keyboard.press("Escape")
    click_toolbar_title(p,"Stift (Stylus zeichnet direkt auf die Folie)")
    state=p.evaluate("window.__excalidraw.getAppState()")
    check("Stift behält eigene Farbe, Dicke und Deckkraft",state["currentItemStrokeColor"]=="#e03131" and abs(state["currentItemStrokeWidth"]*state["zoom"]["value"]-4)<1e-6 and state["currentItemOpacity"]==80)
    click_toolbar_title(p,"Marker: dicker, halbtransparenter Strich")
    state=p.evaluate("window.__excalidraw.getAppState()")
    check("Marker behält eigenes Profil",state["currentItemStrokeColor"]=="#2f9e44" and state["currentItemStrokeWidth"]==16 and state["currentItemOpacity"]==45)
    p.get_by_role("button",name="Formen",exact=True).click();p.get_by_role("button",name="Rechteck",exact=True).click()
    state=p.evaluate("window.__excalidraw.getAppState()")
    check("Formen behalten eigenes Profil",state["currentItemStrokeWidth"]==8 and state["currentItemOpacity"]==60)
    click_toolbar_title(p,"Stift (Stylus zeichnet direkt auf die Folie)")
    p.get_by_role("button",name="Stiftfarbe",exact=True).click();p.get_by_role("button",name="Aktuellen Stift als Lieblingsstift 1 speichern",exact=True).click();p.keyboard.press("Escape")
    click_toolbar_title(p,"Strichstärke dünn")
    p.get_by_role("button",name="Stiftfarbe",exact=True).click();p.get_by_role("button",name="Lieblingsstift 1",exact=True).click();p.keyboard.press("Escape")
    check("Lieblingsstift stellt das gespeicherte Profil her",p.evaluate("(()=>{const s=window.__excalidraw.getAppState();return Math.abs(s.currentItemStrokeWidth*s.zoom.value-4)<1e-6})()"))
    p.close()

    p=page()
    p.get_by_role("button",name="Geometriehilfen",exact=True).click();p.get_by_role("button",name="Lineal",exact=True).click()
    edge=p.get_by_test_id("ruler-guide").bounding_box()
    # Die Kante außerhalb des 44px-Touchgriffs greifen (BBox enthält auch die Hit-Stroke).
    p.mouse.move(edge["x"]+50,edge["y"]+12);p.mouse.down();p.mouse.move(edge["x"]+150,edge["y"]+35,steps=8);p.mouse.up();p.wait_for_timeout(120)
    line=p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='line').at(-1)")
    check("Lineal führt schräges Ziehen exakt an der Kante",line and line["height"]==0 and line["width"]>50)
    p.get_by_role("spinbutton",name="Winkel",exact=True).fill("33")
    check("Winkelfeld erlaubt exakte Werte trotz aktivem Drehraster",p.get_by_role("spinbutton",name="Winkel",exact=True).input_value()=="33")
    p.get_by_role("button",name="Geometriehilfe schließen",exact=True).click()
    p.get_by_role("button",name="Geometriehilfen",exact=True).click();p.get_by_role("button",name="Zirkel",exact=True).click()
    circle=p.get_by_test_id("compass-guide").evaluate("""el=>{const m=el.getScreenCTM(),c=new DOMPoint(el.cx.baseVal.value,el.cy.baseVal.value).matrixTransform(m),edge=new DOMPoint(el.cx.baseVal.value+el.r.baseVal.value,el.cy.baseVal.value).matrixTransform(m);return {cx:c.x,cy:c.y,r:Math.hypot(edge.x-c.x,edge.y-c.y)}}""");cx=circle["cx"];cy=circle["cy"];r=circle["r"]
    p.mouse.move(cx+r,cy);p.mouse.down()
    for i in range(1,10):p.mouse.move(cx+(r+5)*math.cos(i*math.pi/18),cy+(r+5)*math.sin(i*math.pi/18))
    p.mouse.up();p.wait_for_timeout(100)
    arc=p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='line').at(-1)")
    check("Zirkel erzeugt geführten Kreisbogen",arc and len(arc["points"])>10,str(arc and {"points":len(arc["points"])}))
    p.get_by_role("button",name="Kreisbogen zeichnen",exact=True).click();p.wait_for_timeout(100)
    check("Kreisbogen ist auch per Winkelangabe erstellbar",len(p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='line').at(-1).points"))>50)
    p.close()

    p=page()
    p.get_by_role("button",name="ExcaliMath",exact=True).click()
    p.get_by_placeholder("Type LaTeX or use the toolbar above").fill("x^2 + 1")
    p.get_by_role("button",name="Insert",exact=True).click();p.wait_for_timeout(300)
    p.get_by_role("button",name="Close ExcaliMath panel",exact=True).click()
    formula=p.evaluate("window.__excalidraw.getSceneElements().find(e=>e.customData?.excalimath_type==='equation')")
    p.evaluate("""()=>{const a=window.__excalidraw,c=document.createElement('canvas');c.width=200;c.height=100;c.getContext('2d').fillStyle='#1971c2';c.getContext('2d').fillRect(0,0,200,100);a.addFiles([{id:'pdf-image-file',dataURL:c.toDataURL(),mimeType:'image/png',created:Date.now()}]);const template=a.getSceneElements().find(e=>e.id==='paper');a.updateScene({elements:[...a.getSceneElements(),{...template,id:'pdf-image',type:'image',x:150,y:500,width:200,height:100,fileId:'pdf-image-file',status:'saved',scale:[1,1],crop:null,locked:false,customData:{presenterAnnotation:true}}]})}""")
    p.wait_for_timeout(100)
    files=[]
    for solutions in (False,True):
        p.get_by_role("button",name="PDF exportieren",exact=True).click()
        with p.expect_download(timeout=20000) as download:p.get_by_role("button",name="PDF mit Lösungen" if solutions else "PDF nur mit Aufgaben",exact=True).click()
        target=Path(directory)/("solutions.pdf" if solutions else "tasks.pdf");download.value.save_as(target);files.append(target)
        p.keyboard.press("Escape")
    counts=[];image_counts=[];formula_counts=[]
    for target in files:
        with pymupdf.open(target) as document:
            check(f"PDF {target.name} enthält eine Seite je Folie",len(document)==2)
            scale=document[0].rect.width/1600
            clip=pymupdf.Rect(formula['x']*scale,formula['y']*scale,(formula['x']+formula['width'])*scale,(formula['y']+formula['height'])*scale)
            formula_pixels=document[0].get_pixmap(matrix=pymupdf.Matrix(2,2),clip=clip,alpha=False).samples
            formula_counts.append(sum(max(r,g,b)<100 for r,g,b in zip(formula_pixels[0::3],formula_pixels[1::3],formula_pixels[2::3])))
            pixels=document[0].get_pixmap(matrix=pymupdf.Matrix(.5,.5),alpha=False).samples
            counts.append(sum(r>150 and g<100 and b<100 for r,g,b in zip(pixels[0::3],pixels[1::3],pixels[2::3])))
            image_counts.append(sum(b>120 and r<100 for r,g,b in zip(pixels[0::3],pixels[1::3],pixels[2::3])))
    check("PDF-Export erhält eingefügte Bilder und Formeln",all(n>400 for n in image_counts) and all(n>10 for n in formula_counts))
    check("Aufgaben-PDF enthält keine verdeckte Lösung",counts[0]==0)
    check("Lösungs-PDF enthält die Lösung trotz verdeckter Präsentation",counts[1]>1000)
    p.close()
    check("Keine JS-Fehler bei Unterrichtsfunktionen",not errors,str(errors[:3]))

if __name__ == "__main__":
    import subprocess
    import sys
    import tempfile
    from playwright.sync_api import sync_playwright
    failed=[]
    def check(name,condition,detail=""):
        print(f"[{'PASS' if condition else 'FAIL'}] {name} {detail}",flush=True)
        if not condition:failed.append(name)
    server=subprocess.Popen([sys.executable,"-m","http.server","4187","--bind","127.0.0.1","-d",str(Path(__file__).parent/"dist")],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        with tempfile.TemporaryDirectory() as directory,sync_playwright() as playwright:
            browser=playwright.chromium.launch()
            run_lesson_checks(browser,"http://127.0.0.1:4187/index.html",directory,check)
            browser.close()
    finally:server.terminate()
    sys.exit(bool(failed))
