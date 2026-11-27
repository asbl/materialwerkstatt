// Update-Hinweis im Kopfbereich und Einstellungen, Reiter „Version“.

const RECHECK_MS = 6 * 60 * 60 * 1000;
const DISMISSED_KEY = "material-ui:update-dismissed";

function dismissedVersion() {
  try { return localStorage.getItem(DISMISSED_KEY); } catch { return null; }
}

export function describeUpdate(data, dismissed = null) {
  const offered = Boolean(data.updateAvailable) && !data.restartRequired;
  let summary = "Die App ist aktuell.";
  if (data.restartRequired) summary = "Aktualisiert. Die neue Version läuft nach einem Neustart des Servers.";
  else if (offered) summary = `Version ${data.latest} ist verfügbar.`;
  else if (!data.enabled) summary = "Die Update-Prüfung ist abgeschaltet (MATERIAL_UI_UPDATE_CHECK).";
  else if (data.error) summary = "Es konnte nicht nach Updates gesucht werden.";
  else if (!data.latest) summary = "Es ist noch keine Version veröffentlicht.";
  let hint = "";
  if (offered && data.kind === "package") hint = "Die App ist als Paket installiert. Bitte über die Paketverwaltung aktualisieren.";
  else if (offered && data.kind !== "git") hint = "Diese Installation kann sich nicht selbst aktualisieren.";
  return {
    summary, hint,
    canApply: offered && data.kind === "git",
    // „Später“ blendet nur den Hinweis zu genau dieser Version aus.
    notify: data.restartRequired || (offered && data.latest !== dismissed),
    badge: data.restartRequired ? "Neustart nötig" : `Update ${data.latest}`,
    canDismiss: offered && data.latest !== dismissed
  };
}

export function createUpdateController({ api, restartServer, openUpdateSettings }) {
  const byId = id => document.getElementById(id);
  const notice = byId("updateNotice");
  const status = byId("updateStatus");
  let data = null;
  let busy = false;

  function render(next) {
    data = next;
    const view = describeUpdate(data, dismissedVersion());
    notice.hidden = !view.notify;
    byId("updateNoticeLabel").textContent = view.badge;
    notice.title = view.summary;
    notice.setAttribute("aria-label", view.summary);
    byId("updateCurrent").textContent = data.current || "unbekannt";
    byId("updateSummary").textContent = view.summary;
    byId("updateHint").textContent = view.hint;
    byId("updateApply").hidden = !view.canApply;
    byId("updateDismiss").hidden = !view.canDismiss;
    byId("updateRestart").hidden = !data.restartRequired;
    byId("updateCheck").disabled = !data.enabled;
    const link = byId("updateRelease");
    link.hidden = !(data.updateAvailable && /^https:\/\//.test(data.url));
    if (!link.hidden) link.href = `${data.url}/releases/tag/v${data.latest}`;
    status.textContent = data.message || data.error || "";
  }

  async function check(refresh = false) {
    if (busy) return;
    try {
      render(await api(`/api/update${refresh ? "?refresh=1" : ""}`, { timeout: 30000 }));
    } catch (error) {
      status.textContent = error.message;
    }
  }

  async function apply() {
    if (!window.confirm(`Jetzt auf Version ${data.latest} aktualisieren? Danach startet der Server neu; ungespeicherte Änderungen gehen verloren.`)) return;
    busy = true;
    byId("updateApply").disabled = true;
    status.textContent = "Wird aktualisiert … Das kann einige Minuten dauern.";
    try {
      render(await api("/api/update/apply", { method: "POST", timeout: 900000, body: JSON.stringify({ version: data.latest }) }));
      await restartServer({ confirmed: true });
    } catch (error) {
      status.textContent = error.message;
    } finally {
      busy = false;
      byId("updateApply").disabled = false;
    }
  }

  notice.addEventListener("click", () => openUpdateSettings());
  byId("updateApply").addEventListener("click", apply);
  byId("updateRestart").addEventListener("click", () => restartServer());
  byId("updateCheck").addEventListener("click", async () => {
    status.textContent = "Suche nach Updates …";
    await check(true);
  });
  byId("updateDismiss").addEventListener("click", () => {
    try { localStorage.setItem(DISMISSED_KEY, data.latest); } catch { /* nur Komfort */ }
    render(data);
    status.textContent = "Der Hinweis erscheint erst bei der nächsten Version wieder.";
  });

  // Das App-Fenster bleibt oft tagelang offen.
  const start = () => { check(); setInterval(() => check(), RECHECK_MS); };

  return { start, load: () => check() };
}
