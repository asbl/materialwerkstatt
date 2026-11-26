import { paperElements, BACKGROUNDS } from "./slide-backgrounds";
// Zusatzfolien bleiben im Sidecar: vorhandene Frames werden nicht verschoben.
export function sortSlides(frames) {
  const ordered = [...frames].sort((a, b) => a.y - b.y || a.x - b.x);
  if (frames.some((frame) => Number.isFinite(frame.customData?.presentationOrder))) {
    return [...frames].sort((a, b) => (a.customData?.presentationOrder ?? Infinity) - (b.customData?.presentationOrder ?? Infinity) || a.y - b.y || a.x - b.x);
  }
  const ids = new Set(frames.map((f) => f.id));
  const children = new Map();
  for (const frame of ordered) {
    const parent = frame.customData?.insertAfter;
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push(frame);
  }
  for (const siblings of children.values()) siblings.reverse();
  const result = [];
  const visited = new Set();
  const visit = (frame) => {
    if (visited.has(frame.id)) return;
    visited.add(frame.id);
    result.push(frame);
    (children.get(frame.id) ?? []).forEach(visit);
  };
  ordered.filter((f) => !ids.has(f.customData?.insertAfter)).forEach(visit);
  ordered.forEach(visit);
  return result;
}

export function newSlide(elements, current, grid, id = crypto.randomUUID()) {
  const width = current?.width || 1600;
  const height = current?.height || 900;
  const x = current?.x || 0;
  const y = elements.reduce((bottom, el) => Math.max(bottom, el.y + el.height), 0) + 120;
  const frame = { id, type: "frame", x, y, width, height, name: typeof grid === "string" ? BACKGROUNDS.find(([id]) => id === grid)?.[1] ?? "Folie" : grid ? "Rechenkästchen" : "Leerfolie",
    customData: { insertAfter: current?.id }, locked: true };
  const kind = typeof grid === "string" ? grid : grid ? "grid" : "blank";
  frame.customData.paper = { kind, spacing: 25, axisStep: 1 };
  return [...paperElements(frame, kind), frame];
}

export const isBackground = (el, deckIds) => el.type === "frame" ||
  el.customData?.slideBackground || el.customData?.slideContent || (deckIds.has(el.id) && el.type !== "freedraw" && !el.customData?.presenterAnnotation && !el.customData?.excalimath_type);

export function duplicateSlide(elements, frame, isStatic = (el) => el.type === "frame" || el.customData?.slideBackground || el.customData?.slideContent) {
  const members = elements.filter((el) => el.id === frame.id || el.frameId === frame.id);
  const ids = new Map(members.map((el) => [el.id, crypto.randomUUID()]));
  const groups = new Map();
  const dy = Math.max(0, ...elements.map((el) => el.y + el.height)) + 120 - frame.y;
  return members.map((el) => ({ ...structuredClone(el), id: ids.get(el.id), y: el.y + dy, index: null,
    locked: isStatic(el) ? true : el.locked,
    frameId: ids.get(el.frameId) ?? null, containerId: ids.get(el.containerId) ?? null,
    boundElements: el.boundElements?.map((bound) => ({ ...bound, id: ids.get(bound.id) })).filter((bound) => bound.id) ?? null,
    startBinding: el.startBinding && ids.has(el.startBinding.elementId) ? { ...el.startBinding, elementId: ids.get(el.startBinding.elementId) } : null,
    endBinding: el.endBinding && ids.has(el.endBinding.elementId) ? { ...el.endBinding, elementId: ids.get(el.endBinding.elementId) } : null,
    groupIds: el.groupIds.map((id) => { if (!groups.has(id)) groups.set(id, crypto.randomUUID()); return groups.get(id); }),
    name: el.type === "frame" ? `${el.name || "Folie"} – Kopie` : el.name,
    customData: { ...el.customData, presenterAnnotation: !isStatic(el),
      ...(el.customData?.annotationSlide ? { annotationSlide: ids.get(el.customData.annotationSlide) ?? el.customData.annotationSlide } : {}),
      ...(isStatic(el) && el.type !== "frame" ? { slideContent: true } : {}),
      ...(el.type === "frame" ? { insertAfter: frame.id, presentationOrder: undefined } : {}) },
    version: 1, versionNonce: Math.floor(Math.random() * 2 ** 31),
  }));
}
