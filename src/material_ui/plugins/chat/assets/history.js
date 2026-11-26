// Lokaler Chatverlauf im Browser (localStorage): mehrere Chats ("Threads") mit Sitzung, Provider und Modell.
//
// Gespeichert werden nur Nutzer- und Antworttexte; keine Dokumentinhalte, Werkzeugdaten oder
// Aenderungsvorschlaege. Aelteres Format (ein Chat unter material-ui:chat-state) wird uebernommen.

export const THREADS_KEY = "material-ui:chat-threads";
export const LEGACY_KEY = "material-ui:chat-state";
export const MAX_MESSAGES = 60;
export const MAX_CHARS = 120_000;
export const MAX_THREADS = 20;
export const MAX_TOTAL_CHARS = 400_000;

export function trimMessages(messages) {
  const kept = [];
  let chars = 0;
  for (const message of messages.slice(-MAX_MESSAGES).reverse()) {
    chars += message.text.length;
    if (chars > MAX_CHARS) break;
    kept.push(message);
  }
  return kept.reverse();
}

function safeStorage(storage) {
  try { return storage ?? globalThis.localStorage ?? null; } catch { return null; }
}

const cleanMessages = (messages) => (Array.isArray(messages)
  ? messages.filter((m) => m && ["user", "assistant"].includes(m.role) && typeof m.text === "string")
  : []);

export function newThreadId() {
  return `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
}

export function createThread(fields = {}) {
  return {
    id: newThreadId(), title: "", docPath: "", sessionId: null, providerId: null, model: "",
    messages: [], updated: Date.now(), ...fields,
  };
}

export function titleFor(thread) {
  const first = thread.messages.find((message) => message.role === "user");
  const text = (first?.text || "").replace(/\s+/g, " ").trim();
  const base = text ? (text.length > 40 ? `${text.slice(0, 40)}…` : text) : "Neuer Chat";
  const file = thread.docPath ? thread.docPath.split("/").pop() : "";
  return file ? `${base} · ${file}` : base;
}

function normalizeThread(value) {
  if (!value || typeof value !== "object" || typeof value.id !== "string") return null;
  const thread = createThread({
    id: value.id,
    docPath: typeof value.docPath === "string" ? value.docPath : "",
    sessionId: typeof value.sessionId === "string" ? value.sessionId : null,
    providerId: typeof value.providerId === "string" ? value.providerId : null,
    model: typeof value.model === "string" ? value.model : "",
    messages: trimMessages(cleanMessages(value.messages)),
    updated: Number.isFinite(value.updated) ? value.updated : 0,
  });
  thread.title = titleFor(thread);
  return thread;
}

export function loadThreads(storage) {
  const store = safeStorage(storage);
  if (!store) return { activeId: null, threads: [] };
  try {
    const data = JSON.parse(store.getItem(THREADS_KEY) || "null");
    if (data && Array.isArray(data.threads)) {
      const threads = data.threads.map(normalizeThread).filter(Boolean);
      return { activeId: threads.some((t) => t.id === data.activeId) ? data.activeId : (threads[0]?.id ?? null), threads };
    }
    const legacy = JSON.parse(store.getItem(LEGACY_KEY) || "null");
    if (legacy && typeof legacy === "object") {
      const thread = normalizeThread({ ...legacy, id: newThreadId() });
      if (thread && (thread.messages.length || thread.sessionId)) return { activeId: thread.id, threads: [thread] };
    }
  } catch { /* beschaedigte Daten: neu beginnen */ }
  return { activeId: null, threads: [] };
}

// Begrenzt Anzahl und Gesamtgroesse; der aktive Chat bleibt immer erhalten.
export function pruneThreads(threads, activeId) {
  const size = (thread) => thread.messages.reduce((sum, message) => sum + message.text.length, 0);
  const active = threads.find((thread) => thread.id === activeId);
  const kept = active ? [active] : [];
  let chars = active ? size(active) : 0;
  for (const thread of [...threads].sort((a, b) => b.updated - a.updated)) {
    if (thread === active) continue;
    if (kept.length >= MAX_THREADS || chars + size(thread) > MAX_TOTAL_CHARS) continue;
    kept.push(thread);
    chars += size(thread);
  }
  return threads.filter((thread) => kept.includes(thread));
}

export function saveThreads(state, storage) {
  const store = safeStorage(storage);
  if (!store) return false;
  try {
    const threads = pruneThreads(state.threads, state.activeId)
      .filter((thread) => thread.messages.length || thread.sessionId || thread.id === state.activeId);
    const meaningful = threads.some((thread) => thread.messages.length || thread.sessionId);
    if (!meaningful) store.removeItem(THREADS_KEY);
    else {
      store.setItem(THREADS_KEY, JSON.stringify({
        version: 2, activeId: state.activeId,
        threads: threads.map((thread) => ({ ...thread, messages: trimMessages(thread.messages) })),
      }));
    }
    store.removeItem(LEGACY_KEY);
    return true;
  } catch {
    return false; // Speicher voll oder gesperrt: Chat funktioniert weiter, nur ohne Verlauf
  }
}

export function clearAllThreads(storage) {
  const store = safeStorage(storage);
  try { store?.removeItem(THREADS_KEY); store?.removeItem(LEGACY_KEY); } catch { /* ignorieren */ }
}
