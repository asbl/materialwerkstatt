// Termine laden, Abgleichstatus und Statuszeile.

import { isoDate } from "./format.js";
import { store } from "./store.js";

export function findByKey(key) {
  return [...store.events, ...store.agendaTasks, ...(store.todayEvents || []), ...(store.tasks || [])].find((event) => event.key === key) || null;
}

export async function fetchEvents(ctx, from, to) {
  const request = store.pending && store.pending.from === from && store.pending.to === to
    ? store.pending
    : (store.pending = ctx.api(`/api/plugins/kalender/events?from=${from}&to=${to}`));
  const data = await request;
  store.pending = null;
  store.events = data.events || [];
  store.eventsFrom = from;
  store.eventsTo = to;
  store.window = data.window || null;
  store.sourceErrors = data.sourceErrors || [];
  return store.events;
}

export function renderSourceErrors(section) {
  const warning = section.querySelector("[data-kal=source-errors]");
  const errors = store.sourceErrors || [];
  warning.hidden = errors.length === 0;
  warning.textContent = errors.map((error) => `${error.name}: ${error.message}`).join(" ");
}

export function eventsOn(date) {
  const day = isoDate(date);
  return store.events.filter((event) => event.startDate <= day && (event.endDate || event.startDate) >= day);
}

export async function refreshStatus(ctx) {
  store.status = await ctx.api("/api/plugins/kalender/status");
  return store.status;
}

function statusText() {
  if (!store.status) return "";
  if (!store.status.configured) return "Noch kein CalDAV-Konto eingerichtet.";
  const last = store.status.lastSync;
  if (!last) return "Noch nicht synchronisiert. „Synchronisieren“ startet den Abgleich.";
  const when = new Date(last.time * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  if (last.ok) return `Letzter Abgleich: ${when} · ${last.eventCount} Termine`;
  const success = store.status.lastSuccessfulSync;
  const previous = success != null
    ? `Letzter erfolgreicher Abgleich: ${new Date(success * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}.`
    : "Noch kein erfolgreicher Abgleich.";
  const next = store.status.nextSync;
  const retry = next
    ? `${store.status.retryPending ? "Erneuter Versuch" : "Nächster Abgleich"} in ${Math.max(1, Math.ceil((next * 1000 - Date.now()) / 60000))} Minuten.`
    : store.status.intervalMinutes
      ? "Automatischer Abgleich ist aktiviert."
      : "Automatischer Abgleich ist ausgeschaltet.";
  return `Letzter Versuch (${when}): ${last.message} ${previous} ${retry}`;
}

export async function syncNow(ctx, after) {
  try {
    store.status = { ...(store.status || {}), syncRunning: true };
    renderStatusLine();
    const data = await ctx.api("/api/plugins/kalender/sync", { method: "POST" });
    await ctx.events.waitForJob(data.job_id, {
      onUpdate: (record) => {
        if (record.running) return;
      }
    });
  } catch (error) {
    store.status = { ...(store.status || {}), syncRunning: false, syncError: error.message };
    renderStatusLine();
    ctx.ui.setStatus(`Kalender-Sync fehlgeschlagen: ${error.message}`, "error");
    return;
  }
  try {
    await refreshStatus(ctx);
    if (after) await after();
  } finally {
    renderStatusLine();
  }
}

export function renderStatusLine() {
  if (!store.statusLine) return;
  for (const line of document.querySelectorAll('[data-kal=status]')) {
  const syncRunning = store.status && store.status.syncRunning;
  line.textContent = syncRunning ? "Kalender wird aktualisiert … Gespeicherte Termine bleiben sichtbar." : statusText();
  line.classList.toggle("error", Boolean(!syncRunning && store.status && store.status.lastSync && store.status.lastSync.ok === false));
  line.classList.toggle("empty", Boolean(store.status && !store.status.configured));
  }
}