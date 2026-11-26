import { useEffect, useRef, useState } from "react";

const DATABASE = "excalideck-drafts-v1";
function database() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("drafts", { keyPath: "key" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
export async function draftOperation(mode, action) {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction("drafts", mode);
      const request = action(transaction.objectStore("drafts"));
      transaction.oncomplete = () => resolve(request?.result);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally { db.close(); }
}
export function draftKey(path, name, elements) {
  // Stabile Element-IDs unterscheiden gleichnamige lokale Dateien; Serverdecks
  // bleiben auch nach einem Neuaufbau ueber ihren Materialpfad auffindbar.
  return path ? `material:${path}` : `local:${name}:${elements.find((el) => el.type === "frame")?.id ?? elements[0]?.id ?? "empty"}`;
}
export function useLocalDraft({ identity, revision, dirty, api, sceneRevision, makeScene, name, restoredKey }) {
  const [candidate, setCandidate] = useState(null);
  const [status, setStatus] = useState(null);
  const [ready, setReady] = useState(false);
  const keyRef = useRef(identity);
  const generation = useRef(0);
  const makeRef = useRef(makeScene);
  makeRef.current = makeScene;
  keyRef.current = identity;
  useEffect(() => {
    let cancelled = false;
    generation.current++;
    setCandidate(null); setReady(false); setStatus(null);
    if (!identity) return;
    draftOperation("readonly", (store) => store.get(identity)).then((saved) => {
      if (cancelled) return;
      setCandidate(saved?.key === restoredKey ? null : saved ?? null); setReady(true);
    }).catch(() => { if (!cancelled) { setStatus("Lokale Sicherung nicht verfügbar"); setReady(true); } });
    return () => { cancelled = true; generation.current++; };
  }, [identity]);
  useEffect(() => {
    if (!identity || !ready || candidate || !api) return;
    const serial = ++generation.current;
    const timer = setTimeout(async () => {
      if (keyRef.current !== identity || serial !== generation.current) return;
      try {
        if (!dirty) {
          await draftOperation("readwrite", (store) => store.delete(identity));
          if (serial === generation.current) setStatus(null);
          return;
        }
        const scene = makeRef.current();
        await draftOperation("readwrite", (store) => {
          store.put({ key: identity, name, savedAt: Date.now(), revision, scene });
          // Begrenzung nach erfolgreichem Schreiben, Bilder bleiben im selben
          // IndexedDB-Datensatz und brauchen keinen kleinen localStorage-Slot.
          const all = store.getAll();
          all.onsuccess = () => all.result.sort((a, b) => b.savedAt - a.savedAt).slice(20).forEach((old) => store.delete(old.key));
        });
        if (serial === generation.current) setStatus("Entwurf lokal gesichert");
      } catch { if (serial === generation.current) setStatus("Lokale Sicherung nicht verfügbar"); }
    }, dirty ? 650 : 0);
    return () => { clearTimeout(timer); generation.current++; };
  }, [identity, ready, candidate, dirty, sceneRevision, api, revision]);
  const dismiss = async () => {
    if (!identity) return;
    await draftOperation("readwrite", (store) => store.delete(identity)).catch(() => {});
    setCandidate(null);
  };
  const cancel = () => { generation.current++; };
  const clearSaved = async () => {
    cancel();
    const keys = new Set([identity, restoredKey].filter(Boolean));
    await draftOperation("readwrite", (store) => { for (const key of keys) store.delete(key); }).catch(() => {});
    if (keyRef.current === identity) setStatus(null);
  };
  return { candidate, status, dismiss, cancel, clearSaved, accept: () => setCandidate(null) };
}
