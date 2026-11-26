// Sichtbarkeit ist eine Projektion der Szene, kein Loeschen von Folieninhalten.
// Speicherung, Entwuerfe, Miniaturen und Export erhalten immer die Originalwerte.
export const belongsToSlide = (element, frame) => {
  if (!frame || frame.id === "__canvas__") return true;
  if (element.customData?.annotationSlide) return element.customData.annotationSlide === frame.id;
  if (element.id === frame.id || element.frameId === frame.id) return true;
  if (element.frameId || element.type === "frame") return false;
  const x = element.x + (element.width || 0) / 2, y = element.y + (element.height || 0) / 2;
  return x >= frame.x && x <= frame.x + frame.width && y >= frame.y && y <= frame.y + frame.height;
};
export const solutionStep = (element) => Math.max(0, Math.floor(Number(element.customData?.solutionStep) || 0));

export class PresentationScene {
  constructor() {
    this.hidden = new Map();
    this.decoded = new WeakMap();
    this.settings = { presenting: false, isolate: true, frame: null, revealed: 0 };
  }
  configure(settings) { this.settings = settings; }
  decode = (elements) => elements.map((element) => {
    const hint = element.customData?.__excalideckProjection;
    const original = hint ?? this.hidden.get(element.id);
    if (!original) return element;
    const cached = this.decoded.get(element);
    if (cached?.version === element.version && cached.nonce === element.versionNonce && cached.original === original) return cached.element;
    const customData = { ...element.customData };
    delete customData.__excalideckProjection;
    const restored = { ...element, opacity: original.opacity, locked: original.locked,
      ...(hint ? { customData: hint.hadCustomData ? hint.nullCustomData ? null : customData : undefined } : {}) };
    this.decoded.set(element, { version: element.version, nonce: element.versionNonce, original, element: restored });
    return restored;
  });
  encode = (elements) => {
    const { presenting, isolate, frame, revealed, revealedByFrame } = this.settings;
    return elements.map((element) => {
      const drawingHere = this.drawing && element.type === "freedraw" &&
        !this.drawing.known.has(element.id) && this.drawing.frameId === frame?.id;
      const hidden = presenting && frame && ((isolate && !drawingHere && !belongsToSlide(element, frame)) || solutionStep(element) > (element.frameId ? revealedByFrame?.[element.frameId] ?? revealed : revealed));
      if (!hidden) { this.hidden.delete(element.id); return element; }
      const old = this.hidden.get(element.id);
      if (!old || old.opacity !== element.opacity || old.locked !== element.locked) {
        this.hidden.set(element.id, { opacity: element.opacity, locked: element.locked });
      }
      return { ...element, opacity: 0, locked: true, customData: { ...element.customData,
        __excalideckProjection: { opacity: element.opacity, locked: element.locked,
          hadCustomData: element.customData !== undefined, nullCustomData: element.customData === null } } };
    });
  };
  bind(native) {
    this.native = native;
    return new Proxy(native, { get: (target, property) => {
      if (property === "getSceneElements") return () => this.decode(target.getSceneElements());
      if (property === "getSceneElementsIncludingDeleted") return () => this.decode(target.getSceneElementsIncludingDeleted());
      if (property === "updateScene") return (update) => target.updateScene({ ...update,
        ...(update.elements ? { elements: this.encode(update.elements) } : {}) });
      const value = target[property];
      return typeof value === "function" ? value.bind(target) : value;
    } });
  }
  refresh(captureUpdate) {
    if (!this.native) return;
    const actual = this.native.getSceneElementsIncludingDeleted();
    const encoded = this.encode(this.decode(actual));
    // Nur Werte vergleichen: neue Objektidentitaeten durch Decode sind keine
    // neue Sichtbarkeit und duerfen keine onChange-Schleife ausloesen.
    const selected = this.native.getAppState().selectedElementIds;
    const selectionChanged = Object.entries(selected).some(([id, value]) => value && this.hidden.has(id));
    if (selectionChanged || actual.some((el, i) => el.opacity !== encoded[i].opacity || el.locked !== encoded[i].locked || JSON.stringify(el.customData?.__excalideckProjection) !== JSON.stringify(encoded[i].customData?.__excalideckProjection))) {
      this.native.updateScene({ elements: encoded, captureUpdate,
        ...(selectionChanged ? { appState: { selectedElementIds: Object.fromEntries(Object.entries(selected).filter(([id]) => !this.hidden.has(id))) } } : {}) });
    }
  }
}
