import { useEffect, useMemo, useRef } from "react";
import { CaptureUpdateAction, restoreElements } from "@excalidraw/excalidraw";
import { ExcaliMath } from "@excalimath/core";

export default function MathTools({ api, frame, close }) {
  const container = useRef(null);
  useEffect(() => {
    container.current?.querySelector('[aria-label="Toggle ExcaliMath panel"]')?.click();
  }, []);
  // ExcaliMath 1.3.1 setzt selbst keine frameId und berechnet bei Zoom die
  // Einfuegeposition anders. Neue Objekte als Gruppe auf der aktuellen Folie
  // zentrieren; Bearbeitungen bestehender Objekte behalten ihre Position.
  const bridge = useMemo(() => ({
    getAppState: () => api.getAppState(),
    getSceneElements: () => api.getSceneElements(),
    getFiles: () => api.getFiles(),
    addFiles: (files) => api.addFiles(files),
    updateScene: (update) => {
      if (!update.elements) { api.updateScene(update); return; }
      const existing = new Map(api.getSceneElements().map((el) => [el.id, el]));
      const added = update.elements.filter((el) => !existing.has(el.id));
      let dx = 0, dy = 0;
      if (added.length && frame) {
        const left = Math.min(...added.map((e) => e.x));
        const top = Math.min(...added.map((e) => e.y));
        const right = Math.max(...added.map((e) => e.x + e.width));
        const bottom = Math.max(...added.map((e) => e.y + e.height));
        dx = frame.x + frame.width / 2 - (left + right) / 2;
        dy = frame.y + frame.height / 2 - (top + bottom) / 2;
      }
      const elements = update.elements.map((el) => {
        const old = existing.get(el.id);
        return old === el ? el : old ? { ...el, frameId: old.frameId, locked: old.locked, version: Math.max(el.version || 1, old.version + 1) }
          : { ...el, x: el.x + dx, y: el.y + dy, frameId: frame?.id === "__canvas__" ? null : frame?.id };
      });
      const activeFrame = elements.find((e) => e.id === frame?.id);
      const ordered = activeFrame ? [...elements.filter((e) => e.id !== activeFrame.id), activeFrame] : elements;
      api.updateScene({ ...update, elements: restoreElements(ordered.map((e) => ({ ...e, index: null })), null), captureUpdate: CaptureUpdateAction.IMMEDIATELY });
    },
  }), [api, frame]);
  return <div className="deck-math" ref={container} onClick={(event) => { if (event.target.closest('[aria-label="Close ExcaliMath panel"]')) close(); }}><ExcaliMath excalidrawAPI={bridge} theme="light" /></div>;
}
