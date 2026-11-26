import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CaptureUpdateAction, convertToExcalidrawElements } from "@excalidraw/excalidraw";

import { useGuideHandlePosition } from "./use-guide-handle-position";
import { useGuideManipulation } from "./use-guide-manipulation";
import { rotatePoint, projectToEdge, arcPoints, angleDelta, lineSkeleton } from "./guided-geometry";

const icons = {
  slides: "M3 4h5v16H3Z M11 4h10v16H11Z M13 8h6 M13 12h6",
  reveal: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
  grid: "M3 3h18v18H3Z M9 3v18 M15 3v18 M3 9h18 M3 15h18",
  export: "M12 3v12 M7 10l5 5 5-5 M4 17v4h16v-4",
  pen: "m4 20 4-1L20 7l-3-3L5 16l-1 4Z M14 7l3 3", marker: "m4 16 6 4L21 7l-6-4L4 16Z M3 21h8",
  eraser: "m3 14 9-10 9 8-8 9H9l-6-7Z M8 9l9 8", selection: "m5 3 14 10-7 1-3 7L5 3Z",
  hand: "M8 12V5a2 2 0 0 1 4 0v6-7a2 2 0 0 1 4 0v7-5a2 2 0 0 1 4 0v9c0 5-3 7-7 7-3 0-5-2-7-5l-3-5a2 2 0 0 1 3-2l2 2Z",
  undo: "M9 5 3 11l6 6 M3 11h11a6 6 0 0 1 0 12", redo: "m15 5 6 6-6 6 M21 11H10a6 6 0 0 0 0 12",
  shapes: "M3 3h8v8H3Z M16 14l6 8H10l6-8Z M21 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  settings: "M3 6h18 M3 12h18 M3 18h18 M7 3v6 M16 9v6 M9 15v6",
  plus: "M12 3v18 M3 12h18", clipboard: "M9 5H5v17h14V5h-4 M9 2h6v6H9Z",
  fullscreen: "M3 9V3h6 M15 3h6v6 M21 15v6h-6 M9 21H3v-6",
  trash: "M3 6h18 M9 6V3h6v3 M6 6l1 15h10l1-15 M10 10v7 M14 10v7",
  save: "M3 3h15l3 3v15H3Z M7 3v6h10V3 M7 21v-8h10v8",
  lock: "M5 10h14v11H5Z M8 10V6a4 4 0 0 1 8 0v4",
  ruler: "m3 17 14-14 5 5L8 22 3 17Z M7 13l3 3 M11 9l3 3 M15 5l3 3",
};
export function Icon({ name }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={icons[name] || icons.settings} /></svg>;
}

export function Dropup({ label, icon, children, color }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 12, top: 12 });
  const button = useRef(null);
  const panel = useRef(null);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const anchor = button.current.getBoundingClientRect();
      const box = panel.current.getBoundingClientRect();
      const left = Math.max(12, Math.min(anchor.left + anchor.width / 2 - box.width / 2, innerWidth - box.width - 12));
      const top = Math.max(12, Math.min(anchor.top - box.height - 10, innerHeight - box.height - 12));
      setPosition((old) => old.left === left && old.top === top ? old : { left, top });
    };
    place();
    panel.current.querySelector("button:not(:disabled), input:not(:disabled)")?.focus({ preventScroll: true });
    const observer = new ResizeObserver(place);
    observer.observe(panel.current);
    window.addEventListener("resize", place);
    return () => { observer.disconnect(); window.removeEventListener("resize", place); };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const outside = (event) => {
      if (!button.current?.contains(event.target) && !panel.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);
  return <div className="deck-dropup">
    <button ref={button} title={label} aria-label={label} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}>
      {color ? <span className="deck-color-preview" style={{ background: color }} /> : <Icon name={icon} />}<span aria-hidden="true">▴</span>
    </button>
    {open && createPortal(<div ref={panel} className="deck-dropup-panel" role="dialog" aria-label={label} style={position}>
      {typeof children === "function" ? children(() => setOpen(false)) : children}
    </div>, document.body)}
  </div>;
}

export function DrawingOptions({ api, state, shortcut, tool, penScreenWidth = null, onPenWidth }) {
  const selected = api?.getSceneElements().filter((el) => state.selectedElementIds?.[el.id] && !el.locked) || [];
  const value = (prop) => {
    const el = selected[0];
    if (!el && prop === "strokeWidth" && penScreenWidth != null) return penScreenWidth;
    if (prop === "roundness") return el ? (el.roundness ? "round" : "sharp") : state.currentItemRoundness;
    if (prop === "arrowType") return el?.type === "arrow" ? (el.elbowed ? "elbow" : el.roundness ? "round" : "sharp") : state.currentItemArrowType;
    return el && prop in el ? el[prop] : state[`currentItem${prop[0].toUpperCase()}${prop.slice(1)}`];
  };
  const types = selected.length ? selected.map((el) => el.type) : [tool];
  const has = (...allowed) => types.some((type) => allowed.includes(type));
  const fillable = has("rectangle", "ellipse", "diamond");
  const arrows = has("arrow");
  const corners = has("rectangle", "diamond", "line", "arrow");
  const change = (prop, v) => {
    if (!selected.length && prop === "strokeWidth" && penScreenWidth != null) {
      onPenWidth(v);
      return;
    }
    const ids = new Set(selected.map((e) => e.id));
    const patch = (el) => {
      if (prop === "roundness") return { roundness: v === "round" ? { type: ["rectangle", "diamond"].includes(el.type) ? 3 : 2 } : null };
      if (prop === "arrowType") {
        if (el.type !== "arrow") return {};
        const end = el.points.at(-1);
        const points = v === "elbow" ? [[0, 0], [end[0], 0], end] : [[0, 0], end];
        return { elbowed: v === "elbow", roundness: v === "round" ? { type: 2 } : null, points, fixedSegments: v === "elbow" ? [] : null };
      }
      return { [prop]: v };
    };
    api?.updateScene({
      elements: api.getSceneElementsIncludingDeleted().map((el) => ids.has(el.id)
        ? { ...el, ...patch(el), version: el.version + 1, versionNonce: Math.floor(Math.random() * 2 ** 31) } : el),
      appState: { [`currentItem${prop[0].toUpperCase()}${prop.slice(1)}`]: v },
      captureUpdate: CaptureUpdateAction.IMMEDIATELY,
    });
  };
  const choices = (prop, title, items) => <fieldset><legend>{title}</legend><div className="deck-option-row">{items.map(([v, label]) => <button key={String(v)} aria-label={`${title}: ${label}`} title={label} aria-pressed={value(prop) === v} className={value(prop) === v ? "active" : ""} onClick={() => change(prop, v)}>{label}</button>)}</div></fieldset>;
  return <>
    <small>{selected.length ? `${selected.length} ausgewählt` : "Für neue Zeichnungen"}</small>
    <label>Strich <input aria-label="Strichfarbe" type="color" value={value("strokeColor") || "#1e1e1e"} onChange={(e) => change("strokeColor", e.target.value)} /></label>
    {choices("strokeWidth", "Strichstärke", [[0.5, "Extra fein"], [1, "Fein"], [2, "Dünn"], [4, "Mittel"], [8, "Dick"]])}
    {choices("strokeStyle", "Konturstil", [["solid", "―"], ["dashed", "┄"], ["dotted", "┈"]])}
    {choices("roughness", "Sauberkeit", [[0, "Glatt"], [1, "Skizze"], [2, "Grob"]])}
    {fillable && choices("backgroundColor", "Füllfarbe", [["transparent", "Ohne"], ["#d0ebff", "Blau"], ["#d3f9d8", "Grün"], ["#fff3bf", "Gelb"]])}
    {fillable && choices("fillStyle", "Füllstil", [["solid", "Voll"], ["hachure", "Schraffiert"], ["cross-hatch", "Kreuz"]])}
    {corners && choices("roundness", "Ecken", [["sharp", "Eckig"], ["round", "Rund"]])}
    {arrows && choices("startArrowhead", "Pfeilanfang", [[null, "Ohne"], ["arrow", "←"], ["dot", "●"]])}
    {arrows && choices("endArrowhead", "Pfeilspitze", [[null, "Ohne"], ["arrow", "→"], ["triangle", "▶"]])}
    {arrows && choices("arrowType", "Pfeiltyp", [["sharp", "Gerade"], ["round", "Rund"], ["elbow", "Eckig"]])}
    <label>Deckkraft {value("opacity") ?? 100} %<input aria-label="Deckkraft" type="range" min="0" max="100" value={value("opacity") ?? 100} onChange={(e) => change("opacity", Number(e.target.value))} /></label>
    <fieldset disabled={!selected.length}><legend>Ebenen</legend><div className="deck-option-row">
      <button title="Ganz nach hinten" onClick={() => shortcut("[", true)}>⇊</button><button title="Nach hinten" onClick={() => shortcut("[", false)}>↓</button>
      <button title="Nach vorne" onClick={() => shortcut("]", false)}>↑</button><button title="Ganz nach vorne" onClick={() => shortcut("]", true)}>⇈</button>
    </div></fieldset>
    <fieldset disabled={!selected.length}><legend>Aktionen</legend><div className="deck-option-row">
      <button title="Duplizieren" onClick={() => shortcut("d", false)}>⧉</button>
      <button title="Auswahl löschen" onClick={() => api.updateScene({ elements: api.getSceneElementsIncludingDeleted().map((e) => selected.includes(e) ? { ...e, isDeleted: true, version: e.version + 1 } : e), appState: { selectedElementIds: {} }, captureUpdate: CaptureUpdateAction.IMMEDIATELY })}><Icon name="trash" /></button>
    </div><label>Link <input type="url" aria-label="Objektlink" key={selected[0]?.id} defaultValue={selected[0]?.link || ""} placeholder="https://…" onBlur={(e) => { if (e.target.validity.valid) change("link", e.target.value || null); }} /></label></fieldset>
  </>;
}

// Zwischenwerte beim Tippen (z. B. „-” oder „2” vor „200”) nicht überschreiben.
function GuideNumberInput({ label, value, min, max, step, onChange, inputRef }) {
  const [draft, setDraft] = useState(String(value));
  const [editing, setEditing] = useState(false);
  const applied = useRef(value);
  const pending = useRef(false);
  useEffect(() => {
    // Eine Geste ist eine neue Eingabe und ersetzt auch einen offenen Entwurf.
    if (!editing || value !== applied.current) {
      applied.current = value; pending.current = false; setDraft(String(value));
    }
  }, [value, editing]);
  return <input ref={inputRef} aria-label={label} type="number" min={min} max={max} step={step} value={draft}
    onFocus={() => setEditing(true)}
    onChange={event => {
      setDraft(event.target.value); pending.current = true;
      const next = event.target.valueAsNumber;
      if (Number.isFinite(next) && next >= min && next <= max) {
        applied.current = next; pending.current = false; onChange(next);
      }
    }}
    onBlur={() => {
      const next = !pending.current || draft.trim() === "" ? value : Number(draft);
      const bounded = Number.isFinite(next) ? Math.max(min, Math.min(max, next)) : value;
      if (pending.current) onChange(bounded);
      applied.current = bounded; pending.current = false;
      setDraft(String(bounded)); setEditing(false);
    }}
    onKeyDown={event => { if (event.key === "Enter") { event.stopPropagation(); event.currentTarget.blur(); } }} />;
}

// Geometriehilfen liegen über der Leinwand und werden nicht mitgespeichert.
// Ihre Kanten/Kreise erzeugen normale, editierbare Excalidraw-Elemente.
export function GeometryGuide({ kind, api, frame, view, close }) {
  const cellSize = Math.max(10, Math.min(100, Number(frame?.customData?.paper?.spacing) || 25));
  const [position, setPosition] = useState(() => ({
    x: (frame?.x ?? 0) + (frame?.width ?? 800) / 3,
    y: (frame?.y ?? 0) + (frame?.height ?? 600) / 3,
  }));
  const [angle, setAngle] = useState(0);
  const [controlsExpanded, setControlsExpanded] = useState(true);
  const [radius, setRadius] = useState(100);
  const [scale, setScale] = useState(1);
  const angleInput = useRef(null);
  const openSettings = () => { setControlsExpanded(true); requestAnimationFrame(() => angleInput.current?.focus()); };
  const [snapAngle, setSnapAngle] = useState(true);
  const [arcStart, setArcStart] = useState(0);
  const [arcEnd, setArcEnd] = useState(180);
  const [preview, setPreview] = useState(null);
  const gesture = useRef(null);
  const camera = view ?? api.getAppState();
  const zoom = camera.zoom?.value ?? 1;
  const screenX = (position.x + camera.scrollX) * zoom + camera.offsetLeft;
  const screenY = (position.y + camera.scrollY) * zoom + camera.offsetTop;
  const handleCenter = rotatePoint([(kind === "compass" ? radius : 320 * scale) * zoom + 32, 0], angle, { x: screenX, y: screenY });
  const handlePosition = useGuideHandlePosition(handleCenter[0] - 22, handleCenter[1] - 22);
  const resizeCenter = rotatePoint([320 * scale * zoom + 32, (kind === "triangle" ? 160 : 45) * scale * zoom + 32], angle, { x: screenX, y: screenY });
  const resizePosition = useGuideHandlePosition(resizeCenter[0] - 22, resizeCenter[1] - 22, handlePosition);
  const manipulation = useGuideManipulation({ position, angle, zoom, screenX, screenY,
    snap: kind !== "compass" && snapAngle, scale, setScale: kind === "compass" ? undefined : setScale, setPosition, setAngle,
    cancelDrawing: () => { gesture.current = null; setPreview(null); } });
  const style = () => {
    const state = api.getAppState();
    return { strokeColor: state.currentItemStrokeColor, strokeWidth: state.currentItemStrokeWidth,
      strokeStyle: state.currentItemStrokeStyle, opacity: state.currentItemOpacity,
      frameId: frame?.id === "__canvas__" ? null : frame?.id };
  };
  const appendPoints = (points) => {
    const added = convertToExcalidrawElements([lineSkeleton(points, style())]);
    api.updateScene({ elements: [...api.getSceneElements(), ...added], captureUpdate: CaptureUpdateAction.IMMEDIATELY });
  };
  const pointer = (event) => [(event.clientX - camera.offsetLeft) / zoom - camera.scrollX, (event.clientY - camera.offsetTop) / zoom - camera.scrollY];
  const begin = (event, edge = null) => {
    event.preventDefault(); event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = pointer(event);
    if (edge) {
      const endpoints = edge.map((p) => rotatePoint(p.map(value => value * scale), angle, position));
      const start = projectToEdge(point, ...endpoints);
      gesture.current = { endpoints, start, points: [start, start] };
    } else {
      const initial = Math.atan2(point[1] - position.y, point[0] - position.x);
      gesture.current = { initial, previous: initial, sweep: 0, points: arcPoints(position, radius, initial, 0) };
    }
    setPreview(gesture.current.points);
  };
  const trace = (event) => {
    const current = gesture.current;
    if (!current) return;
    event.preventDefault(); event.stopPropagation();
    const point = pointer(event);
    if (current.endpoints) current.points = [current.start, projectToEdge(point, ...current.endpoints)];
    else {
      const next = Math.atan2(point[1] - position.y, point[0] - position.x);
      current.sweep += angleDelta(current.previous, next); current.previous = next;
      current.points = arcPoints(position, radius, current.initial, current.sweep);
    }
    setPreview([...current.points]);
  };
  const finish = (event) => {
    if (!gesture.current) return;
    trace(event);
    const points = gesture.current.points;
    gesture.current = null; setPreview(null);
    if (points.some((point) => Math.hypot(point[0] - points[0][0], point[1] - points[0][1]) > 2 / zoom)) appendPoints(points);
  };
  const guided = (edge) => ({ onPointerDown: (event) => begin(event, edge), onPointerMove: trace, onPointerUp: finish,
    onPointerCancel: () => { gesture.current = null; setPreview(null); },
    style: { pointerEvents: "stroke", touchAction: "none", cursor: "crosshair" }, stroke: "transparent", // Die Zeichenkante darf bei kleinen Hilfen nicht die ganze Verschiebefläche belegen.
    strokeWidth: Math.min(24 / (zoom * (kind === "compass" ? 1 : scale)), kind === "ruler" ? 45 : kind === "triangle" ? 64 : Infinity), fill: "none" });
  const draw = () => {
    if (!api) return;
    const s = api.getAppState();
    const { x, y } = position;
    const common = { strokeColor: s.currentItemStrokeColor, strokeWidth: s.currentItemStrokeWidth,
      strokeStyle: s.currentItemStrokeStyle, opacity: s.currentItemOpacity, roughness: 0,
      frameId: frame?.id === "__canvas__" ? null : frame?.id };
    const a = angle * Math.PI / 180;
    const shape = kind === "compass"
      ? { type: "ellipse", x: x - radius, y: y - radius, width: 2 * radius, height: 2 * radius }
      : { type: "line", x, y, points: [[0, 0], [320 * scale * Math.cos(a), 320 * scale * Math.sin(a)]] };
    const elements = convertToExcalidrawElements([{ ...common, ...shape }]);
    api.updateScene({ elements: [...api.getSceneElements(), ...elements], captureUpdate: CaptureUpdateAction.IMMEDIATELY });
  };
  return <>
    <div className="deck-geometry-controls" role="group" aria-label="Geometriehilfe">
      <strong>{kind === "ruler" ? "Lineal" : kind === "triangle" ? "Geodreieck" : "Zirkel"}</strong>
      <button aria-label={controlsExpanded ? "Geometrieoptionen einklappen" : "Geometrieoptionen ausklappen"}
        aria-expanded={controlsExpanded} aria-controls="deck-geometry-options" onClick={() => setControlsExpanded(!controlsExpanded)}>{controlsExpanded ? "▴" : "▾"}</button>
      <button aria-label="Geometriehilfe schließen" onClick={close}>×</button>
      <div id="deck-geometry-options" className="deck-geometry-options" hidden={!controlsExpanded}>
      {kind === "compass" ? <label>Radius <input aria-label="Zirkelradius" type="range" min={cellSize} max="400" step={cellSize / 5} value={radius} onChange={(e) => setRadius(+e.target.value)} />{Number((radius / cellSize).toFixed(2))} Kästchen</label>
         : <div className="deck-guide-settings">
        <label>Größe <input aria-label="Größe" type="range" min="25" max="300" step="1" value={Math.round(scale * 100)} onChange={e => setScale(+e.target.value / 100)} /></label>
        <label className="deck-guide-value"><GuideNumberInput label="Größe in Prozent" min={25} max={300} step={1} value={Number((scale * 100).toFixed(1))} onChange={value => setScale(value / 100)} /> %</label>
        <label>Winkel <GuideNumberInput inputRef={angleInput} label="Winkel" min={-180} max={180} step={0.1} value={Number(angle.toFixed(1))} onChange={setAngle} /> °</label>
        <label className="deck-guide-snap"><input aria-label="Winkel in 15-Grad-Schritten" type="checkbox" checked={snapAngle} onChange={e => setSnapAngle(e.target.checked)} />Beim Drehen: 15°-Raster</label>
      </div>}
      {kind === "compass" && <>
        <label>Von <input aria-label="Kreisbogen Startwinkel" type="number" min="-360" max="360" value={arcStart} onChange={(e) => setArcStart(+e.target.value)} />°</label>
        <label>Bis <input aria-label="Kreisbogen Endwinkel" type="number" min="-360" max="360" value={arcEnd} onChange={(e) => setArcEnd(+e.target.value)} />°</label>
        <button onClick={() => appendPoints(arcPoints(position, radius, (arcStart + angle) * Math.PI / 180, (arcEnd - arcStart) * Math.PI / 180))}>Kreisbogen zeichnen</button>
      </>}
      {kind !== "compass" && <button onClick={() => { setScale(1); setAngle(0); }}>Zurücksetzen</button>}
      <button onClick={draw}>{kind === "compass" ? "Kreis zeichnen" : "Kante nachziehen"}</button>
      <small>{kind === "compass" ? "Fläche/✥ verschieben · ↻ oder zwei Finger drehen · Am Kreis zeichnen" : "✥ verschieben · ↻ drehen · ↔ skalieren · Zwei Finger: drehen & skalieren · Doppelklick: Einstellungen · An der Kante zeichnen"}</small>
      </div>
    </div>
    <div className="deck-guide" data-angle={angle} data-scale={scale} onDoubleClick={kind === "compass" ? undefined : openSettings} {...manipulation.surface} style={{ left: screenX, top: screenY, transform: `rotate(${angle}deg)` }}>
      <svg width={kind === "compass" ? radius * 2 + 4 : 324} height={kind === "triangle" ? 168 : kind === "compass" ? radius * 2 + 4 : 50}
        style={{ transform: `scale(${zoom * (kind === "compass" ? 1 : scale)})`, transformOrigin: "0 0", ...(kind === "compass" ? { left: -radius * zoom, top: -radius * zoom } : {}) }}>
        {kind === "compass" ? <><circle className="deck-guide-face" cx={radius} cy={radius} r={radius} {...manipulation.move} />
          <path d={`M${radius} ${radius}h${radius}`} strokeDasharray="5 4" /><path d={`M${radius - 8} ${radius}h16 M${radius} ${radius - 8}v16`} /></>
          : <><path className="deck-guide-face" d={kind === "triangle" ? "M0 0H320L160 160Z" : "M0 0H320V45H0Z"} {...manipulation.move} />
            {Array.from({ length: 33 }, (_, i) => <path key={i} d={`M${i * 10} 0v${i % 5 ? 8 : 18}`} />)}
            {kind === "ruler" && Array.from({ length: 7 }, (_, i) => <text key={i} x={i * 50} y="34" fontSize="10" stroke="none" fill="#1971c2">{Number((i * 50 * scale / cellSize).toFixed(2))}</text>)}
            {kind === "triangle" && Array.from({ length: 7 }, (_, i) => { const a = i * Math.PI / 6; return <text key={i} x={160 + 94 * Math.cos(a)} y={94 * Math.sin(a) + 4} textAnchor="middle" fontSize="10" stroke="none" fill="#1971c2">{i * 30}°</text>; })}
            {kind === "triangle" && <><path d="M160 0v160 M80 0a80 80 0 0 0 160 0" />{Array.from({ length: 19 }, (_, i) => { const a = i * Math.PI / 18; return <path key={i} d={`M${160 + 80 * Math.cos(a)} ${80 * Math.sin(a)}L${160 + 70 * Math.cos(a)} ${70 * Math.sin(a)}`} />; })}</>}
          </>}
        {kind === "compass" ? <circle data-testid="compass-guide" cx={radius} cy={radius} r={radius} {...guided(null)} /> : <>
          <line data-testid="ruler-guide" x1="0" y1="0" x2="320" y2="0" {...guided([[0, 0], [320, 0]])} />
          {kind === "triangle" && <>
            <line data-testid="triangle-right-guide" x1="320" y1="0" x2="160" y2="160" {...guided([[320, 0], [160, 160]])} />
            <line data-testid="triangle-left-guide" x1="160" y1="160" x2="0" y2="0" {...guided([[160, 160], [0, 0]])} />
          </>}
        </>}
      </svg>
      <button aria-label="Geometriehilfe verschieben" title="Mit Finger oder Stift verschieben" className="deck-guide-handle" {...manipulation.move}>✥</button>
      {createPortal(<button aria-label="Geometriehilfe drehen" title="Zum Drehen ziehen · Pfeiltasten drehen · Pos1 setzt zurück" className="deck-guide-rotate"
        style={handlePosition} onDoubleClick={kind === "compass" ? undefined : openSettings} {...manipulation.rotate}>
        <span>↻<small>{Math.round(angle)}°</small></span>
      </button>, document.body)}
      {kind !== "compass" && createPortal(<button aria-label="Geometriehilfe vergrößern" title="Zum Vergrößern ziehen · Pfeiltasten ändern die Größe · Doppelklick: Einstellungen" className="deck-guide-rotate deck-guide-resize"
        style={resizePosition} {...manipulation.resize} onDoubleClick={openSettings}><span>↔<small>{Math.round(scale * 100)} %</small></span></button>, document.body)}
    </div>
    {preview && createPortal(<svg className="deck-guide-preview" aria-hidden="true"><polyline fill="none" stroke={api.getAppState().currentItemStrokeColor}
      strokeWidth={api.getAppState().currentItemStrokeWidth * zoom} points={preview.map(([x, y]) => `${(x + camera.scrollX) * zoom + camera.offsetLeft},${(y + camera.scrollY) * zoom + camera.offsetTop}`).join(" ")} /></svg>, document.body)}
  </>;
}
