// Excalidraw kann Elemente auch am selben Objekt veraendern. Deshalb werden
// Versionen und Inhaltssignaturen kopiert, statt lebende Referenzen als
// gespeicherten Stand zu verwenden. Kamerawechsel brauchen kein Szenen-JSON.
const signatures = new WeakMap();
const transient = new Set(["version", "versionNonce", "updated", "index", "locked", "status", "lastCommittedPoint"]);
export function elementContent(element) {
  let cached = signatures.get(element);
  if (!cached || cached.version !== element.version || cached.nonce !== element.versionNonce) {
    cached = { version: element.version, nonce: element.versionNonce,
      content: JSON.stringify(Object.fromEntries(Object.entries(element).filter(([key, value]) => !transient.has(key) && !(key === "customData" && (value == null || Object.keys(value).length === 0))))) };
    signatures.set(element, cached);
  }
  return cached.content;
}
export const captureScene = (elements) => elements.map((el) => ({
  id: el.id, reference: el, version: el.version, nonce: el.versionNonce, content: elementContent(el),
}));
export const sameReferences = (a, b) => a === b || (a.length === b.length && a.every((el, i) => el === b[i]));
export const sameSceneVersion = (elements, snapshot) => elements.length === snapshot.length && elements.every((el, i) =>
  el === snapshot[i].reference && el.version === snapshot[i].version && el.versionNonce === snapshot[i].nonce);
export const sameContent = (elements, snapshot) => elements.length === snapshot.length && elements.every((el, i) =>
  el.id === snapshot[i].id && elementContent(el) === snapshot[i].content);

export function validateScene(data) {
  if (!data || !Array.isArray(data.elements) || data.elements.some((el) => !el || typeof el.id !== "string" || typeof el.type !== "string")) {
    throw new Error("Ungültige Excalidraw-Datei: Elemente fehlen oder sind beschädigt.");
  }
  return data;
}
