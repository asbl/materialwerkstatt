import { worksheetNotesFor } from "./ui-utils.js";
/** Besprechungs-Canvas zum Arbeitsblatt öffnen und fortsetzen. */
export function createWorksheetTools({ state, api, openDeckModal, setStatus, flushPendingSave, openWorksheetNote = null, selectDocument }) {
  const canvasButton = document.createElement("button");
  canvasButton.type = "button";
  canvasButton.textContent = "Weitere Besprechung anlegen";
  canvasButton.setAttribute("aria-describedby", "discussion-new-description");
  const resume = document.createElement("button");
  resume.type = "button";
  resume.textContent = "Besprechen";
  const defaultTitle = "Vorhandene Besprechung öffnen oder die erste starten";
  resume.title = defaultTitle;
  const noteButton = document.createElement("button");
  noteButton.type = "button";
  noteButton.textContent = "Neue Notiz anlegen";
  noteButton.title = "Neue Notiz anlegen";
  const discussion = document.createElement("div");
  discussion.className = "discussion-actions";
  discussion.hidden = true;
  const menu = document.createElement("details");
  menu.className = "discussion-menu";
  // Gleicher Name wie das Dokumentmenue: Der Browser schliesst das jeweils andere sofort
  // beim Oeffnen, nicht erst im spaeter eintreffenden toggle-Ereignis.
  menu.name = "document-menu";
  menu.hidden = true;
  const summary = document.createElement("summary");
  summary.textContent = "▾";
  summary.setAttribute("aria-label", "Weitere Besprechungsoptionen");
  summary.title = "Weitere Besprechungsoptionen";
  const options = document.createElement("div");
  options.className = "document-settings-panel";
  const description = document.createElement("p");
  description.id = "discussion-new-description";
  description.className = "discussion-description";
  description.textContent = "Startet mit einer leeren Zeichenfläche. Vorhandene Besprechungen bleiben erhalten.";
  menu.append(summary, options);
  options.append(canvasButton, description);
  // Notizen oeffnen den Notizeditor; das Deck bleibt unberuehrt.
  discussion.append(resume, menu);
  if (openWorksheetNote) {
    noteButton.onclick = run(async () => {
      const path = state.qmdPath;
      await flushPendingSave();
      if (!path || state.qmdPath !== path) return;
      const [existing] = worksheetNotesFor(state.qmds, path);
      if (existing) await selectDocument(existing.path);
      else await openWorksheetNote(path);
    });
    discussion.append(noteButton);
  }
  document.getElementById("slidesPlay").after(discussion);
  document.addEventListener("material-presentation-actions", event => {
    const hasNotes = worksheetNotesFor(state.qmds, state.qmdPath).length > 0;
    noteButton.textContent = hasNotes ? "Notizen" : "Neue Notiz anlegen";
    noteButton.title = hasNotes ? "Vorhandene Notizen öffnen" : "Neue Notiz anlegen";
    discussion.hidden = !state.qmdPath || event.detail.presentation || event.detail.present === false || state.course.kursMode;
    if (!discussion.hidden) refreshDiscussionInfo();
  });

  const sessionsDialog = document.createElement("dialog");
  sessionsDialog.className = "worksheet-crop-dialog";
  sessionsDialog.innerHTML = '<h2>Besprechung öffnen</h2><div data-parts></div><button type="button" data-close>Schließen</button>';
  document.body.append(sessionsDialog);
  sessionsDialog.querySelector("[data-close]").onclick = () => sessionsDialog.close();
  function chooseCanvas(result) {
    const parts = result.canvases || [];
    if (parts.length <= 1) { openDeckModal(result.canvas, "", state.qmdPath); return; }
    const list = sessionsDialog.querySelector("[data-parts]");
    list.replaceChildren();
    parts.forEach((part, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `Besprechung ${index+1} · ${(part.bytes / 1024 / 1024).toFixed(1)} MiB`;
      button.onclick = () => { sessionsDialog.close(); openDeckModal(part.path, "", state.qmdPath); };
      list.append(button);
    });
    sessionsDialog.showModal();
  }

  let documentVersion = 0;
  let informationVersion = 0;
  let starting = false;

  function updateDiscussionInfo(result) {
    informationVersion++;
    menu.hidden = !result?.canvas;
    if (menu.hidden) menu.open = false;
    resume.title = !result ? defaultTitle : !result.canvas
      ? "Erste Besprechung mit einer leeren Zeichenfläche starten"
      : result.canvases?.length > 1
        ? "Vorhandene Besprechung auswählen und fortsetzen"
        : "Vorhandene Besprechung fortsetzen";
  }

  async function refreshDiscussionInfo() {
    const path = state.qmdPath;
    const version = documentVersion;
    const information = ++informationVersion;
    try {
      const result = await api(`/api/worksheet?path=${encodeURIComponent(path)}`);
      if (version === documentVersion && path === state.qmdPath && information === informationVersion) {
        updateDiscussionInfo(result);
      }
    } catch {
      // Der Hauptbutton versucht den Abruf beim Anklicken erneut.
    }
  }

  function run(action) {
    return async () => {
      try { await action(); }
      catch (error) { setStatus(error.message, "error"); }
    };
  }
  async function startDiscussion() {
    if (starting) return;
    const path = state.qmdPath;
    const version = documentVersion;
    if (!path) throw new Error("Bitte zuerst ein Arbeitsblatt öffnen.");
    starting = true;
    canvasButton.disabled = true;
    try {
      await flushPendingSave();
      if (version !== documentVersion) return;
      const result = await api("/api/worksheet/start", { method: "POST", body: JSON.stringify({ path }) });
      if (version === documentVersion) {
        updateDiscussionInfo({ canvas: result.path });
        refreshDiscussionInfo();
        openDeckModal(result.path, "", path);
      }
    } finally {
      starting = false;
      canvasButton.disabled = false;
    }
  }
  canvasButton.onclick = run(async () => { menu.open = false; await startDiscussion(); });
  resume.onclick = run(async () => {
    menu.open = false;
    const path = state.qmdPath;
    const version = documentVersion;
    await flushPendingSave();
    if (version !== documentVersion) return;
    const result = await api(`/api/worksheet?path=${encodeURIComponent(path)}`);
    if (version !== documentVersion || state.qmdPath !== path) return;
    updateDiscussionInfo(result);
    if (result.canvas) chooseCanvas(result);
    else await startDiscussion();
  });
  // Dokumentwechsel schließt offene Besprechungsmenüs.
  const reset = () => {
    discussion.hidden = true;
    menu.open = false;
    documentVersion++;
    updateDiscussionInfo(null);
    if (sessionsDialog.open) sessionsDialog.close();
  };
  document.addEventListener("material-document-changed", reset);
}
