"""Touch-Drehung und fortlaufendes Zeichnen mit echten Browsergesten."""
import math


def run_touch_checks(page, check):
    for kind in ("Lineal", "Geodreieck", "Zirkel"):
        p = page()
        cdp = p.context.new_cdp_session(p)
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        def touch(event, points):
            cdp.send("Input.dispatchTouchEvent", {"type": event, "touchPoints": [dict(x=x, y=y, id=i, radiusX=2, radiusY=2, force=1) for i, (x, y) in enumerate(points)]})
            p.wait_for_timeout(40)
        p.get_by_role("button", name="Geometriehilfen", exact=True).click()
        p.get_by_role("button", name=kind, exact=True).click()
        count = p.evaluate("window.__excalidraw.getSceneElements().length")
        origin = p.locator(".deck-guide").evaluate("e=>[parseFloat(e.style.left),parseFloat(e.style.top)]")
        box = p.get_by_role("button", name="Geometriehilfe drehen", exact=True).bounding_box()
        start = [box['x']+box['width']/2, box['y']+box['height']/2]
        dx, dy = start[0]-origin[0], start[1]-origin[1]
        touch('touchStart', [start])
        for step in range(1, 7):
            a = math.radians(step*5)
            touch('touchMove', [[origin[0]+dx*math.cos(a)-dy*math.sin(a), origin[1]+dx*math.sin(a)+dy*math.cos(a)]])
        touch('touchEnd', [])
        angle = float(p.locator('.deck-guide').get_attribute('data-angle'))
        check(f'{kind}: Drehgriff lässt sich mit einem Finger drehen', abs(angle-30)<2, str(angle))
        p.get_by_role("button", name="Geometriehilfe drehen", exact=True).press('Home')
        # Erster Finger liegt auf der Zeichenkante: der zweite muss den Entwurf abbrechen.
        selector = '[data-testid="compass-guide"]' if kind == 'Zirkel' else '[data-testid="ruler-guide"]'
        points = p.locator(selector).evaluate("""e=>{const m=e.getScreenCTM();return (e.tagName==='circle'?[[200,100],[100,200]]:[[70,0],[210,0]]).map(([x,y])=>{const p=new DOMPoint(x,y).matrixTransform(m);return [p.x,p.y]})}""")
        mid = [(points[0][j]+points[1][j])/2 for j in (0,1)]
        touch('touchStart', [points[0]])
        touch('touchStart', points)
        for step in range(1,7):
            a=math.radians(step*5)
            rotated=[]
            for x,y in points:
                dx,dy=x-mid[0],y-mid[1]
                rotated.append([mid[0]+dx*math.cos(a)-dy*math.sin(a),mid[1]+dx*math.sin(a)+dy*math.cos(a)])
            touch('touchMove', rotated)
        touch('touchEnd', [])
        angle = float(p.locator('.deck-guide').get_attribute('data-angle'))
        check(f'{kind}: zwei Finger drehen direkt an der Fläche', abs(angle-30)<2, str(angle))
        check(f'{kind}: Drehgesten erzeugen keine Zeichnung', p.evaluate('window.__excalidraw.getSceneElements().length') == count)
        # Nach der Mehrfingergeste müssen Verschieben und Zeichnen weiter funktionieren.
        handle=p.get_by_role('button',name='Geometriehilfe verschieben',exact=True).bounding_box()
        start=[handle['x']+handle['width']/2,handle['y']+handle['height']/2]
        prior=p.locator('.deck-guide').evaluate('e=>[parseFloat(e.style.left),parseFloat(e.style.top)]')
        touch('touchStart',[start]);touch('touchMove',[[start[0]+25,start[1]+15]]);touch('touchEnd',[])
        after=p.locator('.deck-guide').evaluate('e=>[parseFloat(e.style.left),parseFloat(e.style.top)]')
        check(f'{kind}: nach dem Drehen per Finger verschiebbar',abs(after[0]-prior[0]-25)<2 and abs(after[1]-prior[1]-15)<2)
        points=p.locator(selector).evaluate("""e=>{const m=e.getScreenCTM();return (e.tagName==='circle'?Array.from({length:10},(_,i)=>[100+100*Math.cos(i*Math.PI/18),100+100*Math.sin(i*Math.PI/18)]):[[70,0],[210,0]]).map(([x,y])=>{const p=new DOMPoint(x,y).matrixTransform(m);return [p.x,p.y]})}""")
        touch('touchStart',[points[0]])
        for point in points[1:]:touch('touchMove',[point])
        touch('touchEnd',[])
        check(f'{kind}: gedrehte Zeichenkante funktioniert per Touch',p.evaluate('window.__excalidraw.getSceneElements().length')==count+1)
        # Ein dritter Kontakt darf das feste Fingerpaar nicht verschieben.
        # CDP beendet bei touchEnd alle Kontakte; gezieltes pointerup/cancel
        # prüft hier zusätzlich das einzelne Anheben bzw. den Kontaktabbruch.
        for ending in ('pointerup', 'pointercancel'):
            p.evaluate("""()=>{window.guideTouchIds=[];window.recordGuideTouch=e=>{if(e.pointerType==='touch')guideTouchIds.push(e.pointerId)};document.addEventListener('pointerdown',window.recordGuideTouch,true)}""")
            points=p.locator('.deck-guide-face').evaluate("""e=>{const m=e.getScreenCTM();return (e.tagName==='circle'?[[70,70],[110,70],[110,120]]:[[70,25],[140,25],[240,25]]).map(([x,y])=>{const p=new DOMPoint(x,y).matrixTransform(m);return [p.x,p.y]})}""")
            touch('touchStart',[points[0]]);touch('touchStart',points[:2]);touch('touchStart',points)
            prior=p.locator('.deck-guide').evaluate('e=>[parseFloat(e.style.left),parseFloat(e.style.top),Number(e.dataset.angle)]')
            pointer_id=p.evaluate('window.guideTouchIds[0]')
            p.locator('.deck-guide').dispatch_event(ending,dict(pointerId=pointer_id,pointerType='touch',bubbles=True))
            # Die verbleibenden Finger nur um einen Pixel verschieben.
            cdp.send('Input.dispatchTouchEvent',dict(type='touchMove',touchPoints=[dict(x=point[0],y=point[1]+1,id=i+1) for i,point in enumerate(points[1:])]))
            p.wait_for_timeout(80)
            after=p.locator('.deck-guide').evaluate('e=>[parseFloat(e.style.left),parseFloat(e.style.top),Number(e.dataset.angle)]')
            check(f'{kind}: Fingerwechsel bei {ending} ohne Positionssprung',abs(after[0]-prior[0])<2 and abs(after[1]-prior[1]-1)<2 and abs(after[2]-prior[2])<1,str([prior,after]))
            touch('touchEnd',[])
            p.evaluate("document.removeEventListener('pointerdown',window.recordGuideTouch,true)")
        p.close()

    p=page()
    def choose(name):
        p.get_by_role('button', name='Formen', exact=True).click()
        p.get_by_role('button', name=name, exact=True).click()
    def draw(y):
        points=p.evaluate("""y=>{const s=window.__excalidraw.getAppState();return [400,650].map(x=>[(x+s.scrollX)*s.zoom.value+s.offsetLeft,(y+s.scrollY)*s.zoom.value+s.offsetTop])}""",y)
        p.mouse.move(*points[0]);p.mouse.down();p.mouse.move(*points[1],steps=8);p.mouse.up();p.wait_for_timeout(150)
    choose('Linie')
    toggle=p.get_by_role('button',name='Linienwerkzeug beibehalten',exact=True)
    check('Weiterzeichnen ist bei Linien standardmäßig aktiv',toggle.get_attribute('aria-pressed')=='true')
    before=p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='line').length")
    draw(500);draw(580)
    check('Zwei Linien nacheinander ohne erneute Werkzeugwahl',p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='line').length")==before+2 and p.evaluate("window.__excalidraw.getAppState().activeTool.type")=="line")
    toggle.click();draw(660)
    check('Weiterzeichnen lässt sich abschalten',p.evaluate("window.__excalidraw.getAppState().activeTool.type")=="selection")
    choose('Pfeil')
    p.get_by_role('button',name='Linienwerkzeug beibehalten',exact=True).click()
    draw(740);draw(820)
    check('Auch Pfeile können fortlaufend gezeichnet werden',p.evaluate("window.__excalidraw.getSceneElements().filter(e=>e.type==='arrow').length")>=2 and p.evaluate("window.__excalidraw.getAppState().activeTool.type")=="arrow")
    p.close()

    p=page()
    def state():return p.evaluate("window.__excalidraw.getAppState().activeTool.type")
    for name in ('Linie','Pfeil'):
        p.get_by_role('button',name='Formen',exact=True).click();p.get_by_role('button',name=name,exact=True).click()
        p.keyboard.press('Escape');p.wait_for_timeout(80)
        check(f'{name}: Esc direkt nach der Werkzeugwahl beendet Zeichnen',state()=='selection')
        p.get_by_role('button',name='Formen',exact=True).click();p.get_by_role('button',name=name,exact=True).click()
        p.get_by_role('button',name='Linienwerkzeug beibehalten',exact=True).click()
        p.keyboard.press('Escape');p.wait_for_timeout(80)
        check(f'{name}: Esc nach Weiterzeichnen beendet Zeichnen',state()=='selection')
    p.get_by_role('button',name='Formen',exact=True).click();p.get_by_role('button',name='Linie',exact=True).click()
    p.get_by_role('button',name='Zeichenoptionen',exact=True).click();p.keyboard.press('Escape');p.wait_for_timeout(80)
    check('Esc schließt zuerst Zeichenoptionen und behält das Werkzeug',state()=='line' and p.locator('.deck-dropup-panel').count()==0)
    p.keyboard.press('Escape');p.wait_for_timeout(80)
    check('Erneutes Esc beendet das Linienwerkzeug',state()=='selection')
    p.get_by_role('button',name='Formen',exact=True).click();p.get_by_role('button',name='Linie',exact=True).click()
    p.get_by_role('button',name='Geometriehilfen',exact=True).click();p.get_by_role('button',name='Lineal',exact=True).click()
    field=p.get_by_role('spinbutton',name='Winkel',exact=True);field.fill('45');field.press('Escape')
    check('Esc in einem Eingabefeld lässt Werkzeug und Eingabe bestehen',state()=='line' and field.input_value()=='45')
    p.close()

    # Der Drehgriff muss nach Drehen, Einklappen und Resize erreichbar bleiben.
    for width,height in ((390,844),(844,390),(1024,768)):
        p=page();p.set_viewport_size(dict(width=width,height=height));p.wait_for_timeout(150)
        for kind in ('Lineal','Geodreieck','Zirkel'):
            p.get_by_role('button',name='Geometriehilfen',exact=True).click();p.get_by_role('button',name=kind,exact=True).click()
            handle=p.get_by_role('button',name='Geometriehilfe drehen',exact=True)
            for collapsed in (False,True):
                if collapsed:p.get_by_role('button',name='Geometrieoptionen einklappen',exact=True).click()
                for angle in (0,90,-90,180):
                    # Tastatur läuft durch denselben Drehhandler, auch beim Zirkel.
                    handle.press('Home')
                    if kind!='Zirkel' and not collapsed:
                        p.get_by_role('spinbutton',name='Winkel',exact=True).fill(str(angle))
                    else:
                        # Jeden Tastenschritt einzeln flushen, um React-State nicht zu bündeln.
                        for i in range(abs(angle)//(1 if kind=='Zirkel' else 15)):
                            handle.press('ArrowLeft' if angle<0 else 'ArrowRight')
                    p.wait_for_timeout(40)
                    reachable=handle.evaluate("""e=>{const b=e.getBoundingClientRect(),x=b.x+b.width/2,y=b.y+b.height/2;return b.x>=0&&b.y>=0&&b.right<=innerWidth&&b.bottom<=innerHeight&&e.contains(document.elementFromPoint(x,y))}""")
                    check(f'{kind} {width}×{height} {angle}° Optionen {"zu" if collapsed else "offen"}: Drehgriff erreichbar',reachable)
            if kind=='Zirkel':
                p.set_viewport_size(dict(width=height,height=width));p.wait_for_timeout(150)
                reachable=handle.evaluate("""e=>{const b=e.getBoundingClientRect();return b.x>=0&&b.y>=0&&b.right<=innerWidth&&b.bottom<=innerHeight&&e.contains(document.elementFromPoint(b.x+22,b.y+22))}""")
                check(f'{width}×{height}: Drehgriff nach Orientierungswechsel erreichbar',reachable)
            p.get_by_role('button',name='Geometriehilfe schließen',exact=True).click()
        p.close()
