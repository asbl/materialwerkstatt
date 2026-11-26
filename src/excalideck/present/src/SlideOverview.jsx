import { useEffect, useRef, useState } from "react";
import { slideCanvas } from "./lesson-export";

function Thumbnail({ api, frame, revision }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const canvas = await slideCanvas(api.getSceneElements(), frame, api.getFiles(), api.getAppState(), { solutions: false, size: 240 });
        if (!cancelled && canvasRef.current) {
          const output = canvasRef.current;
          output.width = canvas.width; output.height = canvas.height;
          output.getContext("2d").drawImage(canvas, 0, 0);
        }
        canvas.width = canvas.height = 0;
      } catch { /* Titel und Navigation bleiben auch ohne Miniatur nutzbar. */ }
    }, 350);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [api, frame, revision]);
  return <canvas ref={canvasRef} aria-hidden="true" />;
}
function SlideRow({ api, frame, position, count, active, revision, goTo, rename, move, duplicate, drop }) {
  const [name, setName] = useState(frame.name ?? "Folie");
  const cancelRename = useRef(false);
  useEffect(() => setName(frame.name ?? "Folie"), [frame.name]);
  return <li className={active ? "active" : ""} draggable onDragStart={(event) => event.dataTransfer.setData("application/x-excalideck-slide", frame.id)}
    onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); drop(event.dataTransfer.getData("application/x-excalideck-slide"), frame.id); }}>
    <button className="deck-slide-preview" aria-label={`Folie ${position + 1} anzeigen`} aria-current={active ? "page" : undefined} onClick={() => goTo(position)}>
      <Thumbnail api={api} frame={frame} revision={revision} /><span>{position + 1}. {frame.name || "Folie"}</span>
    </button>
    <input aria-label={`Titel Folie ${position + 1}`} disabled={frame.id === "__canvas__"} value={name} maxLength={120} onChange={(event) => setName(event.target.value)}
      onBlur={() => { if (cancelRename.current) { cancelRename.current = false; return; } if (name.trim() && name !== frame.name) rename(frame.id, name.trim()); }}
      onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); if (event.key === "Escape") { cancelRename.current = true; setName(frame.name ?? "Folie"); event.currentTarget.blur(); } }} />
    <div className="deck-slide-actions">
      <button aria-label={`Folie ${position + 1} nach oben`} disabled={position === 0} onClick={() => move(position, -1)}>↑</button>
      <button aria-label={`Folie ${position + 1} nach unten`} disabled={position === count - 1} onClick={() => move(position, 1)}>↓</button>
      <button aria-label={`Folie ${position + 1} duplizieren`} disabled={frame.id === "__canvas__"} onClick={() => duplicate(frame.id)}>⧉</button>
    </div>
  </li>;
}
export default function SlideOverview({ api, slides, index, revision, close, ...actions }) {
  return <aside className="deck-overview" aria-label="Folienübersicht">
    <div className="deck-panel-header"><strong>Folienübersicht</strong><button aria-label="Folienübersicht schließen" onClick={close}>×</button></div>
    <p>Ziehen zum Sortieren oder Pfeile verwenden.</p>
    <ol>{slides.map((frame, position) => <SlideRow key={frame.id} api={api} frame={frame} position={position} count={slides.length}
      active={index === position} revision={revision} {...actions} />)}</ol>
  </aside>;
}
