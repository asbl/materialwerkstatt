// Gemeinsame Zeiger-Geste zum Ziehen (Maus, Stift, Touch) ohne HTML5-Drag-and-drop.
// Die Geste startet erst nach einer kleinen Schwelle, damit normale Klicks erhalten bleiben,
// und lässt sich mit Escape abbrechen. Der Aufrufer liefert nur die fachlichen Teile.
//
//   startPointerDrag({ event, handle, onStart, onMove, onDrop, onEnd })
//   - event: das pointerdown-Ereignis (wird hier mit preventDefault übernommen)
//   - handle: Element, das die Zeigererfassung hält (meist das gezogene Element)
//   - onStart(): einmal beim Überschreiten der Schwelle
//   - onMove(moveEvent): bei jeder Bewegung während des Ziehens
//   - onDrop(upEvent): beim Loslassen nach einem echten Zug (nicht bei Escape oder Abbruch)
//   - onEnd({ dragged }): immer am Ende; dragged sagt, ob die Schwelle überschritten wurde
export const DRAG_THRESHOLD = 6;

export function startPointerDrag({ event, handle, threshold = DRAG_THRESHOLD, onStart = () => {}, onMove = () => {}, onDrop = () => {}, onEnd = () => {} }) {
  event.preventDefault();
  handle.setPointerCapture?.(event.pointerId);
  const pointerId = event.pointerId, startX = event.clientX, startY = event.clientY;
  let dragged = false, cancelled = false;
  const move = moveEvent => {
    if (moveEvent.pointerId !== pointerId || cancelled) return;
    if (!dragged && Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) < threshold) return;
    if (!dragged) { dragged = true; onStart(); }
    moveEvent.preventDefault();
    onMove(moveEvent);
  };
  const key = keyEvent => { if (keyEvent.key === 'Escape' && dragged) { cancelled = true; keyEvent.stopPropagation(); } };
  const finish = endEvent => {
    if (endEvent.pointerId !== pointerId) return;
    if (handle.hasPointerCapture?.(pointerId)) handle.releasePointerCapture(pointerId);
    document.removeEventListener('pointermove', move);
    document.removeEventListener('pointerup', finish);
    document.removeEventListener('pointercancel', finish);
    document.removeEventListener('keydown', key, true);
    try { if (dragged && !cancelled && endEvent.type === 'pointerup') onDrop(endEvent); }
    finally { onEnd({ dragged }); }
  };
  document.addEventListener('pointermove', move, { passive: false });
  document.addEventListener('pointerup', finish);
  document.addEventListener('pointercancel', finish);
  document.addEventListener('keydown', key, true);
}
