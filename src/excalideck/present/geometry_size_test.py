"""Größe und freie Winkel mit echten Griff- und Zeicheninteraktionen."""
import math


def run_geometry_size_checks(page, check):
    run_angle_preservation_checks(page, check)
    run_geometry_regression_checks(page, check)
    for kind in ("Lineal", "Geodreieck"):
        p = page()
        p.get_by_role("button", name="Geometriehilfen", exact=True).click()
        p.get_by_role("button", name=kind, exact=True).click()
        guide = p.locator(".deck-guide")
        size = p.get_by_role("spinbutton", name="Größe in Prozent", exact=True)
        angle = p.get_by_role("spinbutton", name="Winkel", exact=True)
        size.focus(); size.press("ControlOrMeta+a"); size.press_sequentially("200")
        angle.focus(); angle.press("ControlOrMeta+a"); angle.press_sequentially("-12.5"); angle.press("Enter")
        check(f"{kind}: Prozent und negative Dezimalwinkel lassen sich tippen", guide.get_attribute("data-scale") == "2" and guide.get_attribute("data-angle") == "-12.5")
        size.fill("175")
        angle.fill("23.5")
        check(f"{kind}: Größe und Dezimalwinkel direkt einstellbar", guide.get_attribute("data-scale") == "1.75" and guide.get_attribute("data-angle") == "23.5")
        before = p.evaluate("window.__excalidraw.getSceneElements().length")
        p.get_by_role("button", name="Kante nachziehen", exact=True).click()
        line = p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='line').at(-1)")
        check(f"{kind}: nachgezogene Kante passt zur Skalierung", abs(math.dist(line['points'][0], line['points'][-1]) - 560) < 0.01, str(line.get('points')))
        for edge in (["ruler-guide", "triangle-right-guide", "triangle-left-guide"] if kind == "Geodreieck" else ["ruler-guide"]):
            points = p.get_by_test_id(edge).evaluate("""e=>{const m=e.getScreenCTM();return [0.15,0.8].map(t=>{const a=[e.x1.baseVal.value,e.y1.baseVal.value],b=[e.x2.baseVal.value,e.y2.baseVal.value];const p=new DOMPoint(a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])).matrixTransform(m);return [p.x,p.y]})}""")
            p.mouse.move(*points[0]); p.mouse.down(); p.mouse.move(*points[1], steps=8); p.mouse.up()
            line = p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='line').at(-1)")
            expected = 560 * 0.65 * (math.sqrt(0.5) if edge != "ruler-guide" else 1)
            check(f"{kind}: skalierte Zeichenkante {edge} stimmt", abs(math.dist(line['points'][0], line['points'][-1]) - expected) < 0.1, str([math.dist(line['points'][0],line['points'][-1]),expected]))
        p.get_by_role("button", name="Zurücksetzen", exact=True).click()
        p.get_by_role("checkbox", name="Winkel in 15-Grad-Schritten", exact=True).uncheck()
        handle = p.get_by_role("button", name="Geometriehilfe drehen", exact=True)
        origin = guide.evaluate("e=>[parseFloat(e.style.left),parseFloat(e.style.top)]")
        b = handle.bounding_box(); start = [b['x'] + 22, b['y'] + 22]
        dx, dy = start[0] - origin[0], start[1] - origin[1]
        a = math.radians(22.7)
        end = [origin[0] + dx*math.cos(a)-dy*math.sin(a), origin[1] + dx*math.sin(a)+dy*math.cos(a)]
        p.mouse.move(*start); p.mouse.down(); p.mouse.move(*end, steps=12); p.mouse.up()
        check(f"{kind}: Drehgriff dreht stufenlos ohne Raster", abs(float(guide.get_attribute('data-angle')) - 22.7) < 0.2)
        p.get_by_role("button", name="Zurücksetzen", exact=True).click()
        resize = p.get_by_role("button", name="Geometriehilfe vergrößern", exact=True)
        b = resize.bounding_box(); start = [b['x']+22,b['y']+22]
        end = [origin[i] + (start[i]-origin[i])*1.2 for i in (0,1)]
        p.mouse.move(*start); p.mouse.down(); p.mouse.move(*end, steps=10); p.mouse.up()
        check(f"{kind}: Größengriff skaliert ohne Zeichnung", abs(float(guide.get_attribute('data-scale'))-1.2)<0.01 and p.evaluate('window.__excalidraw.getSceneElements().length') == before + (4 if kind == 'Geodreieck' else 2))
        resize.press("Home")
        check(f"{kind}: Größengriff per Tastatur bedienbar", guide.get_attribute('data-scale') == '1')
        p.get_by_role("button", name="Geometrieoptionen einklappen", exact=True).click()
        resize.dblclick()
        p.wait_for_timeout(100)
        check(f"{kind}: Doppelklick öffnet präzise Einstellungen", angle.is_visible() and angle.evaluate('e=>e===document.activeElement'))
        p.get_by_role("button", name="Zurücksetzen", exact=True).click()
        cdp = p.context.new_cdp_session(p)
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        points = p.get_by_test_id("ruler-guide").evaluate("""e=>{const m=e.getScreenCTM();return [80,200].map(x=>{const p=new DOMPoint(x,0).matrixTransform(m);return [p.x,p.y]})}""")
        mid = [(points[0][i]+points[1][i])/2 for i in (0,1)]
        def touch(event, points):
            cdp.send("Input.dispatchTouchEvent", dict(type=event, touchPoints=[dict(x=x,y=y,id=i) for i,(x,y) in enumerate(points)]))
            p.wait_for_timeout(40)
        count = p.evaluate('window.__excalidraw.getSceneElements().length')
        touch('touchStart', points[:1]); touch('touchStart', points)
        for step in range(1,9):
            a = math.radians(-17*step/8); ratio = 1+0.4*step/8
            target = [[mid[0]+ratio*((x-mid[0])*math.cos(a)-(y-mid[1])*math.sin(a)),mid[1]+ratio*((x-mid[0])*math.sin(a)+(y-mid[1])*math.cos(a))] for x,y in points]
            touch('touchMove',target)
        touch('touchEnd', [])
        check(f"{kind}: Zwei-Finger-Geste skaliert und dreht frei", abs(float(guide.get_attribute('data-scale'))-1.4)<0.01 and abs(float(guide.get_attribute('data-angle'))+17)<0.2)
        check(f"{kind}: Skaliergeste erzeugt keine Zeichnung", p.evaluate('window.__excalidraw.getSceneElements().length') == count)
        for width, height in ((390,844),(844,390)):
            p.set_viewport_size(dict(width=width,height=height))
            size.fill('300'); angle.fill('90')
            p.wait_for_timeout(100)
            for control in (handle,resize):
                check(f"{kind}: Griff bei 300 % auf {width}×{height} erreichbar", control.evaluate('e=>{const b=e.getBoundingClientRect();return b.x>=0&&b.y>=0&&b.right<=innerWidth&&b.bottom<=innerHeight&&e.contains(document.elementFromPoint(b.x+22,b.y+22))}'))
        p.close()


def run_geometry_regression_checks(page, check):
    for kind in ("Lineal", "Geodreieck"):
        p = page()
        p.get_by_role("button", name="Geometriehilfen", exact=True).click()
        p.get_by_role("button", name=kind, exact=True).click()
        guide = p.locator(".deck-guide")
        angle = p.get_by_role("spinbutton", name="Winkel", exact=True)
        size = p.get_by_role("spinbutton", name="Größe in Prozent", exact=True)
        angle.fill("30")
        origin = guide.evaluate("e=>[parseFloat(e.style.left),parseFloat(e.style.top)]")
        handle = p.get_by_role("button", name="Geometriehilfe drehen", exact=True)
        box = handle.bounding_box()
        x, y = box["x"]+22, box["y"]+22
        dx, dy = x-origin[0], y-origin[1]
        a = math.pi/6
        p.mouse.move(x,y); p.mouse.down()
        p.mouse.move(origin[0]+dx*math.cos(a)-dy*math.sin(a), origin[1]+dx*math.sin(a)+dy*math.cos(a), steps=10)
        p.mouse.up()
        rotated = float(guide.get_attribute("data-angle"))
        check(f"{kind}: Winkelfeld folgt Drehgriff bei bestehendem Fokus", abs(rotated-60)<0.1 and float(angle.input_value()) == rotated)
        p.get_by_role("button", name="Kante nachziehen", exact=True).click()
        check(f"{kind}: Fokusverlust überschreibt Drehung nicht", abs(float(guide.get_attribute("data-angle"))-60)<0.1)
        p.get_by_role("button", name="Zurücksetzen", exact=True).click()
        size.fill("150")
        box = p.get_by_role("button", name="Geometriehilfe vergrößern", exact=True).bounding_box()
        x, y = box["x"]+22, box["y"]+22
        p.mouse.move(x,y); p.mouse.down()
        p.mouse.move(origin[0]+(x-origin[0])*1.2, origin[1]+(y-origin[1])*1.2, steps=10); p.mouse.up()
        scaled = float(guide.get_attribute("data-scale"))
        check(f"{kind}: Prozentfeld folgt Größengriff bei bestehendem Fokus", abs(scaled-1.8)<0.01 and abs(float(size.input_value())-scaled*100)<0.1)
        p.get_by_role("button", name="Kante nachziehen", exact=True).click()
        check(f"{kind}: Fokusverlust überschreibt Skalierung nicht", abs(float(guide.get_attribute("data-scale"))-1.8)<0.01)
        # Auch Zwischenwerte bleiben editierbar und werden erst beim Verlassen begrenzt.
        size.fill("5")
        check(f"{kind}: Unvollständige Größenangabe bleibt editierbar", size.input_value()=="5" and abs(float(guide.get_attribute("data-scale"))-1.8)<0.01)
        size.press("Enter")
        check(f"{kind}: Größenangabe wird beim Bestätigen begrenzt", guide.get_attribute("data-scale")=="0.25" and size.input_value()=="25")
        angle.fill("0"); angle.press("Enter")
        p.get_by_role("button", name="Geometrieoptionen einklappen", exact=True).click()
        # Echte Maus- und Touch-Gesten auf der kleinen Fläche müssen bewegen, ohne zu zeichnen.
        cdp = p.context.new_cdp_session(p)
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        for method in ("Maus", "Touch"):
            point = p.locator(".deck-guide-face").evaluate("""(e,y)=>{const p=new DOMPoint(160,y).matrixTransform(e.getScreenCTM());return [p.x,p.y]}""",35 if kind=="Lineal" else 75)
            prior = guide.evaluate("e=>[parseFloat(e.style.left),parseFloat(e.style.top)]")
            count = p.evaluate("window.__excalidraw.getSceneElements().length")
            if method == "Maus":
                p.mouse.move(*point); p.mouse.down(); p.mouse.move(point[0]+25,point[1]+10,steps=8); p.mouse.up()
            else:
                cdp.send("Input.dispatchTouchEvent", dict(type="touchStart",touchPoints=[dict(x=point[0],y=point[1],id=0)]))
                cdp.send("Input.dispatchTouchEvent", dict(type="touchMove",touchPoints=[dict(x=point[0]+25,y=point[1]+10,id=0)]))
                cdp.send("Input.dispatchTouchEvent", dict(type="touchEnd",touchPoints=[]))
            p.wait_for_timeout(60)
            after = guide.evaluate("e=>[parseFloat(e.style.left),parseFloat(e.style.top)]")
            check(f"{kind}: Fläche bei 25 % per {method} verschiebbar ohne Zeichnung", abs(after[0]-prior[0]-25)<1 and abs(after[1]-prior[1]-10)<1 and p.evaluate("window.__excalidraw.getSceneElements().length")==count)
        points = p.get_by_test_id("ruler-guide").evaluate("""e=>[120,270].map(x=>{const p=new DOMPoint(x,0).matrixTransform(e.getScreenCTM());return [p.x,p.y]})""")
        count = p.evaluate("window.__excalidraw.getSceneElements().length")
        p.mouse.move(*points[0]);p.mouse.down();p.mouse.move(*points[1],steps=8);p.mouse.up()
        check(f"{kind}: Zeichenkante bei 25 % weiterhin bedienbar", p.evaluate("window.__excalidraw.getSceneElements().length")==count+1)
        p.close()

    p = page()
    p.get_by_role("button", name="Geometriehilfen", exact=True).click()
    p.get_by_role("button", name="Geodreieck", exact=True).click()
    for width,height in ((390,844),(844,390),(1440,1000)):
        p.set_viewport_size(dict(width=width,height=height))
        misses = []
        for scale in (25,100,300):
            for angle in (-180,-90,-45,0,45,90,180):
                p.get_by_role("spinbutton",name="Größe in Prozent",exact=True).fill(str(scale))
                p.get_by_role("spinbutton",name="Winkel",exact=True).fill(str(angle))
                for collapsed in (True,False):
                    p.get_by_role("button",name="Geometrieoptionen "+("einklappen" if collapsed else "ausklappen"),exact=True).click()
                    p.wait_for_timeout(60)
                    reachable = p.locator(".deck-guide-rotate").evaluate_all("""els=>els.every(e=>{const b=e.getBoundingClientRect();return b.x>=0&&b.y>=0&&b.right<=innerWidth&&b.bottom<=innerHeight&&e.contains(document.elementFromPoint(b.x+22,b.y+22))})""")
                    if not reachable: misses.append([scale,angle,collapsed])
        check(f"{width}×{height}: beide Griffe in 42 Größen/Winkel/Panel-Konfigurationen erreichbar", not misses, str(misses))
    p.close()



def run_angle_preservation_checks(page, check):
    """N01: Reine Größen-/Positionsänderungen dürfen den Winkel nicht einrasten lassen."""
    for kind in ("Lineal", "Geodreieck"):
        for snap in (True, False):
            for initial in (23.5, -23.5):
                p = page()
                p.get_by_role("button", name="Geometriehilfen", exact=True).click()
                p.get_by_role("button", name=kind, exact=True).click()
                p.get_by_role("checkbox", name="Winkel in 15-Grad-Schritten", exact=True).set_checked(snap)
                guide = p.locator(".deck-guide")
                cdp = p.context.new_cdp_session(p)
                cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
                def touch(event, points):
                    cdp.send("Input.dispatchTouchEvent", dict(type=event, touchPoints=[dict(x=x,y=y,id=i) for i,(x,y) in enumerate(points)]))
                    p.wait_for_timeout(30)
                for mode, ratio, turn, shift in (
                    ("nur skalieren", 1.4, 0, (0,0)),
                    ("nur verschieben", 1, 0, (24,18)),
                    ("skalieren mit Messrauschen", 1.2, 0, (0,0)),
                    ("bewusst drehen und skalieren", 1.4, 17 if initial>0 else -17, (12,-8)),
                ):
                    p.get_by_role("spinbutton", name="Größe in Prozent", exact=True).fill("100")
                    field = p.get_by_role("spinbutton", name="Winkel", exact=True)
                    field.fill(str(initial)); field.press("Enter")
                    p.get_by_role("button", name="Geometrieoptionen einklappen", exact=True).click()
                    origin = guide.evaluate("e=>[parseFloat(e.style.left),parseFloat(e.style.top)]")
                    points = p.get_by_test_id("ruler-guide").evaluate("""e=>[90,230].map(x=>{const p=new DOMPoint(x,0).matrixTransform(e.getScreenCTM());return [p.x,p.y]})""")
                    mid = [(points[0][i]+points[1][i])/2 for i in (0,1)]
                    count = p.evaluate("window.__excalidraw.getSceneElements().length")
                    touch("touchStart", points[:1]); touch("touchStart", points)
                    angles = []
                    for step in range(1,9):
                        t = step/8
                        noise = 0.2*math.sin(t*math.pi) if mode=="skalieren mit Messrauschen" else 0
                        a = math.radians(turn*t + noise)
                        r = 1+(ratio-1)*t
                        target = [[mid[0]+shift[0]*t+r*((x-mid[0])*math.cos(a)-(y-mid[1])*math.sin(a)),mid[1]+shift[1]*t+r*((x-mid[0])*math.sin(a)+(y-mid[1])*math.cos(a))] for x,y in points]
                        touch("touchMove", target)
                        angles.append(float(guide.get_attribute("data-angle")))
                    touch("touchEnd", [])
                    expected_angle = round((initial+turn)/15)*15 if snap and turn else initial+turn
                    angle_now = float(guide.get_attribute("data-angle"))
                    prefix = f"{kind}, Raster {snap}, {initial}°: {mode}"
                    angle_ok = abs(angle_now-expected_angle)<0.01
                    if not turn:
                        angle_ok = angle_ok and all(abs(angle-initial)<0.0001 for angle in angles)
                    check(prefix+" — Winkel stimmt während und nach der Geste", angle_ok, str(angles))
                    # Nullpunkt folgt Skalierung/Translation um die Fingermitte mit dem effektiven Winkel.
                    a = math.radians(expected_angle-initial)
                    dx,dy = origin[0]-mid[0],origin[1]-mid[1]
                    expected = [mid[0]+shift[0]+ratio*(dx*math.cos(a)-dy*math.sin(a)),mid[1]+shift[1]+ratio*(dx*math.sin(a)+dy*math.cos(a))]
                    after = guide.evaluate("e=>[parseFloat(e.style.left),parseFloat(e.style.top)]")
                    check(prefix+" — Größe und Nullpunkt stimmen", abs(float(guide.get_attribute("data-scale"))-ratio)<0.001 and math.dist(after,expected)<0.1, str([after,expected]))
                    check(prefix+" — keine Zeichnung erzeugt", p.evaluate("window.__excalidraw.getSceneElements().length")==count)
                    p.get_by_role("button", name="Geometrieoptionen ausklappen", exact=True).click()
                p.close()


def main():
    """Nach npm run build lokal ausführbar; --touch ergänzt die bestehenden Touch-Checks."""
    import argparse
    import json
    import tempfile
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    from regression_test import SCENE

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--touch", action="store_true")
    args = parser.parse_args()
    dist = Path(__file__).resolve().parent / "dist"
    if not (dist / "index.html").exists():
        parser.error("Produktionsbuild fehlt; zuerst npm run build im present-Ordner ausführen")

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    failures = []
    checks = 0
    errors = []
    def check(name, passed, detail=""):
        nonlocal checks
        checks += 1
        print(f"[{'PASS' if passed else 'FAIL'}] {name} {detail}", flush=True)
        if not passed:
            failures.append(name)

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(dist)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
            fixture = Path(tmp) / "geometry.excalidraw"
            fixture.write_text(json.dumps(SCENE), encoding="utf-8")
            browser = pw.chromium.launch(headless=True)
            def page():
                p = browser.new_page(viewport=dict(width=1440,height=1000))
                p.on("pageerror", lambda error: errors.append(str(error)))
                p.goto(f"http://127.0.0.1:{server.server_port}")
                p.wait_for_selector("canvas")
                p.set_input_files("input[type=file]", str(fixture))
                p.wait_for_timeout(400)
                return p
            run_geometry_size_checks(page, check)
            if args.touch:
                from touch_tools_test import run_touch_checks
                run_touch_checks(page, check)
            check("Keine JavaScript-Laufzeitfehler", not errors, str(errors))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(f"{checks-len(failures)}/{checks} Prüfungen bestanden.")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
