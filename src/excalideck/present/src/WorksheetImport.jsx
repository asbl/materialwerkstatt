import { useEffect, useRef, useState } from "react";
import { assertCompatibility } from "../../../material_ui/static/protocol.js";

const ZOOM_MIN = 0.6;
const ZOOM_MAX = 6;

async function request(url, body) {
  if (body) await assertCompatibility();
  const response = await fetch(url, {
    signal: AbortSignal.timeout(15000),
    ...(body ? { method: "POST", headers: { "Content-Type": "application/json", "X-Material-Token": window.__MATERIAL_TOKEN__ ?? "" }, body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.error?.message || `HTTP ${response.status}`);
  }
  return response;
}

export default function WorksheetImport({ owner, insert, close }) {
  const [source, setSource] = useState(owner);
  const [solution, setSolution] = useState(null);
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState(null);
  const [imageReady, setImageReady] = useState(false);
  const [base, setBase] = useState(null);
  const [view, setView] = useState({ zoom: 1, pan: [0, 0] });
  const [crop, setCrop] = useState(null);
  const [chosen, setChosen] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [hover, setHover] = useState(null);
  const [panMode, setPanMode] = useState(false);
  const [target, setTarget] = useState("current");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const stage = useRef(null);
  const dialog = useRef(null);
  const drag = useRef(null);
  const panner = useRef(null);
  const pinch = useRef(null);
  const pointers = useRef(new Map());
  const imageAspect = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const previous = document.activeElement;
    dialog.current.showModal();
    return () => { mounted.current = false; previous?.focus(); };
  }, []);
  useEffect(() => {
    let active = true;
    request(`/api/worksheet?path=${encodeURIComponent(owner)}`).then(r => r.json()).then(data => {
      if (active) setSolution(data.solution);
    }).catch(error => { if (active) setMessage(error.message); });
    return () => { active = false; };
  }, [owner]);

  function clampPan(zoom, pan) {
    const box = stage.current?.getBoundingClientRect();
    if (!base || !box?.width || !box?.height) return pan;
    const scaledWidth = base.w * zoom, scaledHeight = base.h * zoom;
    const [x, y] = pan;
    return [
      scaledWidth <= box.width ? (box.width - scaledWidth) / 2 : Math.max(box.width - scaledWidth, Math.min(0, x)),
      scaledHeight <= box.height ? (box.height - scaledHeight) / 2 : Math.max(box.height - scaledHeight, Math.min(0, y)),
    ];
  }
  function zoomAt(cx, cy, factor) {
    if (!base) return;
    setView(current => {
      const zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, current.zoom * factor));
      const ux = (cx - current.pan[0]) / current.zoom, uy = (cy - current.pan[1]) / current.zoom;
      return { zoom, pan: clampPan(zoom, [cx - ux * zoom, cy - uy * zoom]) };
    });
  }
  function pointerStage(event) {
    const box = stage.current.getBoundingClientRect();
    return [event.clientX - box.left, event.clientY - box.top];
  }
  function point(event) {
    const [x, y] = pointerStage(event);
    const width = base?.w ? view.zoom * base.w : 1;
    const height = base?.h ? view.zoom * base.h : 1;
    return [
      Math.max(0, Math.min(1, width > 0 ? (x - view.pan[0]) / width : 0)),
      Math.max(0, Math.min(1, height > 0 ? (y - view.pan[1]) / height : 0)),
    ];
  }
  function pinchMove() {
    const active = [...pointers.current.entries()];
    if (active.length < 2 || !pinch.current || !base) return;
    const [ax, ay] = active[0][1], [bx, by] = active[1][1];
    const dist = Math.hypot(bx - ax, by - ay) || pinch.current.dist;
    const box = stage.current.getBoundingClientRect();
    const mid = [ (ax + bx) / 2 - box.left, (ay + by) / 2 - box.top ];
    const start = pinch.current;
    const zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, start.zoom * (dist / start.dist)));
    const scale = zoom / start.zoom;
    const pan = clampPan(zoom, [ mid[0] - (start.mid[0] - start.pan[0]) * scale,
                                 mid[1] - (start.mid[1] - start.pan[1]) * scale ]);
    setView({ zoom, pan });
  }

  useEffect(() => {
    let active = true, objectUrl;
    setPreview(null); setImageReady(false); setBase(null); setCrop(null); setChosen(null);
    setTasks([]); setHover(null); setView({ zoom: 1, pan: [0, 0] });
    setMessage("Aktuelles PDF wird vorbereitet …");
    (async () => {
      const query = `path=${encodeURIComponent(source)}`;
      const info = await (await request(`/api/document?${query}`)).json();
      if (!active) return;
      if (!info.pdf || info.pdfCurrent !== true) {
        const job = await (await request("/api/render", { path: source })).json();
        while (active) {
          const status = await (await request(`/api/jobs/${job.job_id}`)).json();
          if (!active) return;
          if (!status.running) {
            if (!status.ok) throw new Error(status.message || "PDF-Erstellung fehlgeschlagen.");
            break;
          }
          await new Promise(resolve => setTimeout(resolve, 500));
        }
      }
      if (!active) return;
      const response = await request(`/api/worksheet/page?${query}&page=${page}`);
      const blob = await response.blob();
      if (!active) return;
      objectUrl = URL.createObjectURL(blob);
      setPreview({ url: objectUrl, count: Number(response.headers.get("X-PDF-Pages")), revision: response.headers.get("X-PDF-Revision") });
      setMessage("");
    })().catch(error => { if (active) setMessage(error.message); });
    return () => { active = false; drag.current = null; panner.current = null; pinch.current = null; pointers.current.clear(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [source, page]);

  useEffect(() => {
    if (!preview) { setTasks([]); setChosen(null); return; }
    let active = true;
    request(`/api/worksheet/tasks?path=${encodeURIComponent(source)}&page=${page}`)
      .then(response => response.json())
      .then(data => { if (active) setTasks(Array.isArray(data?.tasks) ? data.tasks : []); })
      .catch(() => { if (active) setTasks([]); });
    return () => { active = false; };
  }, [source, page, preview]);

  // Der Zoom läuft als nativer Wheel-Listener: React registriert onWheel
  // passiv, preventDefault würde dort ignoriert werden.
  useEffect(() => {
    const element = stage.current;
    if (!element || !preview) return;
    const onWheel = event => {
      if (!imageReady || !base) return;
      event.preventDefault();
      const box = element.getBoundingClientRect();
      zoomAt(event.clientX - box.left, event.clientY - box.top, Math.exp(-event.deltaY * 0.0016));
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [preview, imageReady, base]);

  useEffect(() => {
    const element = stage.current;
    if (!element || !preview) return;
    const fit = () => {
      const aspect = imageAspect.current;
      const width = element.clientWidth, height = element.clientHeight;
      if (!aspect || width <= 0 || height <= 0) return;
      const fitted = Math.min(width, height * aspect);
      setBase({ w: fitted, h: fitted / aspect });
    };
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    return () => observer.disconnect();
  }, [preview]);

  useEffect(() => {
    setView(current => ({ zoom: current.zoom, pan: clampPan(current.zoom, current.pan) }));
  }, [base]);

  function loaded(event) {
    const image = event.currentTarget;
    imageAspect.current = image.naturalWidth / image.naturalHeight || 1;
    const element = stage.current;
    if (element && imageAspect.current) {
      const width = element.clientWidth, height = element.clientHeight;
      const fitted = Math.min(width, height * imageAspect.current);
      setBase({ w: fitted, h: fitted / imageAspect.current });
    }
    setImageReady(true);
  }

  function chooseTask(task, index) {
    setCrop(task.rect);
    setChosen(index);
    if (!base) return;
    const box = stage.current?.getBoundingClientRect();
    if (!box?.width) return;
    setView(current => {
      if (current.zoom === 1) return current;
      const centerX = (task.rect[0] + task.rect[2]) / 2 * base.w * current.zoom;
      const centerY = (task.rect[1] + task.rect[3]) / 2 * base.h * current.zoom;
      return { zoom: current.zoom, pan: clampPan(current.zoom, [ box.width / 2 - centerX, box.height / 2 - centerY ]) };
    });
  }

  async function add() {
    if (!preview || !imageReady || busy) return;
    setBusy(true); setMessage("Ausschnitt wird eingefügt …");
    try {
      const fragment = await (await request("/api/worksheet/fragment", {
        path: owner, source, page, crop: crop || [0, 0, 1, 1], pdfRevision: preview.revision,
      })).json();
      if (!mounted.current) return;
      insert(fragment, target === "new", source !== owner);
      close();
    } catch (error) { if (mounted.current) setMessage(error.message); }
    finally { if (mounted.current) setBusy(false); }
  }

  function onPointerDown(event) {
    if (busy || !imageReady || !base) return;
    const [x, y] = pointerStage(event);
    pointers.current.set(event.pointerId, [x, y]);
    if (pointers.current.size === 2) {
      drag.current = null;
      panner.current = null;
      const active = [...pointers.current.values()];
      pinch.current = {
        dist: Math.hypot(active[1][0] - active[0][0], active[1][1] - active[0][1]) || 1,
        zoom: view.zoom, pan: view.pan,
        mid: [ (active[0][0] + active[1][0]) / 2, (active[0][1] + active[1][1]) / 2 ],
      };
      setCrop(null);
      return;
    }
    if (event.button !== 0 && event.button !== 1) return;
    event.preventDefault();
    try { event.currentTarget.setPointerCapture(event.pointerId); }
    catch { /* Capture ist optional: bei nicht aktiven Pointer-Ids ungueltig */ }
    if (panMode || event.button === 1) {
      panner.current = { id: event.pointerId, x, y, pan: view.pan };
      return;
    }
    if (drag.current) return;
    drag.current = { id: event.pointerId, start: point(event) };
    setCrop(null);
    setChosen(null);
  }
  function onPointerMove(event) {
    if (!pointers.current.has(event.pointerId)) return;
    const [x, y] = pointerStage(event);
    pointers.current.set(event.pointerId, [x, y]);
    if (pointers.current.size >= 2) {
      pinchMove();
      return;
    }
    if (panner.current?.id === event.pointerId) {
      const start = panner.current;
      setView(current => ({ zoom: current.zoom, pan: clampPan(current.zoom, [ start.pan[0] + x - start.x, start.pan[1] + y - start.y ]) }));
      return;
    }
    if (drag.current?.id !== event.pointerId) return;
    const [sx, sy] = drag.current.start, [a, b] = point(event);
    setCrop([Math.min(sx, a), Math.min(sy, b), Math.max(sx, a), Math.max(sy, b)]);
  }
  function onPointerEnd(event) {
    if (pointers.current.delete(event.pointerId)) {
      if (pointers.current.size < 2) pinch.current = null;
    }
    if (panner.current?.id === event.pointerId) panner.current = null;
    if (drag.current?.id === event.pointerId) {
      drag.current = null;
      setCrop(current => current && current[2] - current[0] > .005 && current[3] - current[1] > .005 ? current : null);
    }
  }

  return <dialog ref={dialog} className="deck-worksheet-import" aria-label="Aus AB einfügen" onCancel={e => { e.preventDefault(); if (!busy) close(); }} onKeyDown={e => e.stopPropagation()}>
    <header><strong>Aus AB einfügen</strong><button onClick={close} disabled={busy}>Schließen</button></header>
    <p>Rahmen um die Aufgabe ziehen oder eine erkannte Aufgabe antippen. Zoomen mit Mausrad oder zwei Fingern.</p>
    <div className="deck-worksheet-controls">
      <label>Quelle <select aria-label="Quelle" value={source} disabled={busy} onChange={e => { setSource(e.target.value); setPage(1); }}>
        <option value={owner}>Arbeitsblatt</option>{solution && <option value={solution.path}>Lösung</option>}
      </select></label>
      <button disabled={busy || !preview || page <= 1} onClick={() => setPage(page - 1)}>Zurück</button>
      <span>Seite {page} / {preview?.count || "…"}</span>
      <button disabled={busy || !preview || page >= preview.count} onClick={() => setPage(page + 1)}>Weiter</button>
      <button disabled={busy} onClick={() => { setCrop(null); setChosen(null); }}>Ganze Seite</button>
      <label>Einfügen in <select aria-label="Einfügen in" value={target} disabled={busy} onChange={e => setTarget(e.target.value)}>
        <option value="current">Aktuelle Zeichenfläche</option><option value="new">Neue Seite</option>
      </select></label>
      <button className="deck-worksheet-insert" disabled={busy || !preview || !imageReady} onClick={add}>Einfügen</button>
      <span className="deck-worksheet-zoom">
        <button aria-label="Verkleinern" disabled={!imageReady} onClick={() => { const box = stage.current.getBoundingClientRect(); zoomAt(box.width / 2, box.height / 2, 1 / 1.25); }}>−</button>
        <span aria-live="polite">{imageReady ? Math.round(view.zoom * 100) : "…"} %</span>
        <button aria-label="Vergrößern" disabled={!imageReady} onClick={() => { const box = stage.current.getBoundingClientRect(); zoomAt(box.width / 2, box.height / 2, 1.25); }}>+</button>
        <button disabled={!imageReady || (view.zoom === 1 && !crop)} onClick={() => setView({ zoom: 1, pan: [0, 0] })}>Fit</button>
        <button className="deck-worksheet-pan" aria-pressed={panMode} disabled={!imageReady}
          title="Ansicht verschieben: umschalten und ziehen; zwei Finger verschieben und zoomen gleichzeitig"
          onClick={() => setPanMode(current => !current)}>Verschieben</button>
      </span>
    </div>
    {tasks.length > 0 && <div className="deck-worksheet-tasks" role="group" aria-label="Aufgabe wählen">
      {tasks.map((task, index) => <button key={`${task.label}-${index}`} type="button" title={task.title}
        className={chosen === index ? "chosen" : ""}
        aria-pressed={chosen === index}
        onPointerEnter={() => setHover(task.rect)}
        onPointerLeave={() => setHover(null)}
        onFocus={() => setHover(task.rect)}
        onBlur={() => setHover(null)}
        onClick={() => chooseTask(task, index)}>{task.label}</button>)}
    </div>}
    {source !== owner && <p>Die Lösung wird als verdeckbarer Lösungsschritt eingefügt.</p>}
    <p role="status">{message}</p>
    {preview && <div className={`deck-worksheet-stage${panMode ? " panning" : ""}`} ref={stage}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerEnd}
      onPointerCancel={onPointerEnd}>
      {/* Das Bild mountet immer: sein onLoad liefert das Seitenverhaeltnis,
          aus dem die Zeichenflaeche (base) gemessen wird. */}
      <div className="deck-worksheet-canvas" style={base ? {
        width: `${base.w}px`, height: `${base.h}px`,
        transform: `translate(${view.pan[0]}px, ${view.pan[1]}px) scale(${view.zoom})`,
      } : { width: "0", height: "0" }}>
        <img src={preview.url} alt="PDF-Seite zur Ausschnittauswahl" draggable={false} onLoad={loaded}
          onError={() => setMessage("Seitenbild konnte nicht angezeigt werden. Bitte erneut öffnen.")} />
        {hover && <div className="deck-worksheet-region" aria-hidden="true"
          style={{ left: `${hover[0]*100}%`, top: `${hover[1]*100}%`, width: `${(hover[2]-hover[0])*100}%`, height: `${(hover[3]-hover[1])*100}%` }} />}
        {crop && <div className="deck-worksheet-selection"
          style={{ left: `${crop[0]*100}%`, top: `${crop[1]*100}%`, width: `${(crop[2]-crop[0])*100}%`, height: `${(crop[3]-crop[1])*100}%` }} />}
      </div>
    </div>}
  </dialog>;
}
