import { useRef } from "react";
import { angleDelta } from "./guided-geometry";

// Kleine Winkelabweichungen bei zwei Fingern sind oft Messrauschen beim Schieben/Skalieren.
const touchRotationThreshold = Math.PI / 180;

const degrees = (angle) => ((angle + 180) % 360 + 360) % 360 - 180;

// Griff und Flaeche bewegen das Hilfsmittel, Drehgriff und zwei Finger drehen
// es. Zeichen-Gesten werden beim zweiten Finger abgebrochen, nie gespeichert.
export function useGuideManipulation({ position, angle, zoom, screenX, screenY, snap, scale = 1, setScale, setPosition, setAngle, cancelDrawing }) {
  const drag = useRef(null);
  const rotation = useRef(null);
  const resizing = useRef(null);
  const contacts = useRef(new Map());
  const multi = useRef(null);
  const constrained = (value) => degrees(snap ? Math.round(value / 15) * 15 : value);
  const consume = (event) => { event.preventDefault(); event.stopPropagation(); };
  const release = () => { drag.current = null; rotation.current = null; resizing.current = null; };
  const move = {
    onPointerDown(event) {
      consume(event);
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { id: event.pointerId, x: position.x, y: position.y, clientX: event.clientX, clientY: event.clientY };
    },
    onPointerMove(event) {
      if (drag.current?.id !== event.pointerId || multi.current) return;
      consume(event);
      const start = drag.current;
      setPosition({ x: start.x + (event.clientX - start.clientX) / zoom, y: start.y + (event.clientY - start.clientY) / zoom });
    },
    onPointerUp: release,
    onPointerCancel: release,
  };
  const rotate = {
    onPointerDown(event) {
      consume(event);
      event.currentTarget.setPointerCapture(event.pointerId);
      rotation.current = { id: event.pointerId, previous: Math.atan2(event.clientY - screenY, event.clientX - screenX), start: angle, delta: 0 };
    },
    onPointerMove(event) {
      const current = rotation.current;
      if (!current || current.id !== event.pointerId || multi.current) return;
      consume(event);
      const next = Math.atan2(event.clientY - screenY, event.clientX - screenX);
      current.delta += angleDelta(current.previous, next);
      current.previous = next;
      setAngle(constrained(current.start + current.delta * 180 / Math.PI));
    },
    onPointerUp: release,
    onPointerCancel: release,
    onKeyDown(event) {
      if (!["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
      consume(event);
      setAngle(event.key === "Home" ? 0 : constrained(angle + (event.key === "ArrowLeft" ? -1 : 1) * (snap ? 15 : 1)));
    },
  };
  const clampScale = value => Math.max(0.25, Math.min(3, value));
  const resize = {
    onPointerDown(event) {
      consume(event); cancelDrawing();
      event.currentTarget.setPointerCapture(event.pointerId);
      resizing.current = { id: event.pointerId, scale, distance: Math.max(1, Math.hypot(event.clientX - screenX, event.clientY - screenY)) };
    },
    onPointerMove(event) {
      const current = resizing.current;
      if (!current || current.id !== event.pointerId || multi.current) return;
      consume(event);
      setScale(clampScale(current.scale * Math.hypot(event.clientX - screenX, event.clientY - screenY) / current.distance));
    },
    onPointerUp: release,
    onPointerCancel: release,
    onKeyDown(event) {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home"].includes(event.key)) return;
      consume(event);
      setScale(event.key === "Home" ? 1 : clampScale(scale + (["ArrowLeft", "ArrowDown"].includes(event.key) ? -0.05 : 0.05)));
    },
  };
  const baseline = () => {
    const pair = [...contacts.current.keys()].slice(0, 2);
    const [a, b] = pair.map(id => contacts.current.get(id));
    return { pair, mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], origin: [screenX, screenY], position,
      scale, distance: Math.max(1, Math.hypot(b[0] - a[0], b[1] - a[1])),
      angle, previous: Math.atan2(b[1] - a[1], b[0] - a[0]), delta: 0 };
  };
  const touchEnd = (event) => {
    if (event.pointerType !== "touch") return;
    contacts.current.delete(event.pointerId);
    if (multi.current) {
      consume(event);
      if (!contacts.current.size) multi.current = null;
      else if (contacts.current.size >= 2 && multi.current.pair.some(id => !contacts.current.has(id))) {
        // Ein Ersatzfinger braucht die aktuelle Position als neue Basis.
        multi.current = baseline();
      }
    }
    if (event.type === "pointercancel") release();
  };
  const surface = {
    onPointerDownCapture(event) {
      if (event.pointerType !== "touch") return;
      contacts.current.set(event.pointerId, [event.clientX, event.clientY]);
      if (contacts.current.size < 2) return;
      consume(event); release(); cancelDrawing();
      if (!multi.current || multi.current.pair.some(id => !contacts.current.has(id))) multi.current = baseline();
      for (const id of contacts.current.keys()) event.currentTarget.setPointerCapture(id);
    },
    onPointerMoveCapture(event) {
      if (!contacts.current.has(event.pointerId)) return;
      contacts.current.set(event.pointerId, [event.clientX, event.clientY]);
      const current = multi.current;
      if (!current) return;
      consume(event);
      if (contacts.current.size < 2) return;
      const [a, b] = current.pair.map(id => contacts.current.get(id));
      const next = Math.atan2(b[1] - a[1], b[0] - a[0]);
      current.delta += angleDelta(current.previous, next); current.previous = next;
      // Ohne erkennbare Drehung den exakten Ausgangswinkel behalten, auch außerhalb
      // des Rasters. Bei Rückkehr in die Toleranz gilt das erneut: versetzte
      // Pointer-Updates einer reinen Translation dürfen keine Rasterung festhalten.
      const angleNow = Math.abs(current.delta) <= touchRotationThreshold
        ? current.angle : constrained(current.angle + current.delta * 180 / Math.PI);
      const delta = (angleNow - current.angle) * Math.PI / 180;
      const scaleNow = setScale ? clampScale(current.scale * Math.hypot(b[0] - a[0], b[1] - a[1]) / current.distance) : current.scale;
      const ratio = scaleNow / current.scale;
      const dx = current.origin[0] - current.mid[0], dy = current.origin[1] - current.mid[1];
      const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      const x = mid[0] + (dx * Math.cos(delta) - dy * Math.sin(delta)) * ratio;
      const y = mid[1] + (dx * Math.sin(delta) + dy * Math.cos(delta)) * ratio;
      setAngle(angleNow);
      setScale?.(scaleNow);
      setPosition({ x: current.position.x + (x - current.origin[0]) / zoom, y: current.position.y + (y - current.origin[1]) / zoom });
    },
    onPointerUpCapture: touchEnd,
    onPointerCancelCapture: touchEnd,
  };
  return { move, rotate, resize, surface };
}
