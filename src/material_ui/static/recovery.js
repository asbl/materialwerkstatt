import { readDraft, readDrafts, removeDraft } from "./drafts.js";

export function createRecoveryController({ state, api, getEditorText, setEditorText, setStatus,
  clearScheduledRender, openModal, closeModal, renderDiff, flushPendingSave, persistDraft,
  draftPath, updateSaveIndicator }) {
  let recoveryState = null;
  async function showHistory() {
    try {
      await flushPendingSave();
      const session = state.session;
      const path = draftPath();
      const { versions } = await api(`/api/document/history?path=${encodeURIComponent(path)}`);
      if (session !== state.session) return;
      if (!versions.length) {
        setStatus("Noch keine früheren Dateifassungen vorhanden.", "ready");
        return;
      }
      const snapshot = await api(`/api/document?path=${encodeURIComponent(path)}`);
      const draft = await api(`/api/document/history/${versions[0].id}?path=${encodeURIComponent(path)}`);
      if (session !== state.session) return;
      showRecovery(snapshot, draft, true);
      document.getElementById("recoveryTitle").textContent = "Frühere Dateifassung";
      document.getElementById("recoveryDraftLabel").textContent = "Ausgewählte frühere Fassung";
      document.getElementById("recoveryDiff").dataset.leftLabel = "Ausgewählte frühere Fassung";
      renderDiff?.(document.getElementById("recoveryDiff"), snapshot.text, draft.text);
      document.getElementById("recoveryDraftHelp").textContent = "Eine früher gespeicherte Version aus der Versionshistorie. Rechts siehst du die aktuell gespeicherte QMD-Datei.";
      document.getElementById("recoveryVersionsLabel").textContent = "Früher gespeicherte Fassungen";
      document.getElementById("recoveryBackupLabel").textContent = "Frühere Fassung separat sichern";
      document.getElementById("recoveryRestore").textContent = "Frühere Fassung im Editor öffnen";
      document.getElementById("recoveryRestoreHelp").textContent = "Öffnet die ausgewählte frühere Fassung zum Weiterarbeiten. Die Datei wird erst geändert, wenn du speicherst.";
      document.getElementById("recoveryDiscard").textContent = "Aktuellen Dateistand weiterverwenden";
      document.getElementById("recoveryDiscardHelp").textContent = "Öffnet den aktuellen Dateistand im Editor. Die frühere Fassung bleibt in der Versionshistorie erhalten.";
      recoveryState.history = versions;
      document.getElementById("recoveryVersions").replaceChildren(...versions.map((item, index) => new Option(new Date(item.created * 1000).toLocaleString(), String(index))));
      document.getElementById("recoveryHint").textContent = "Frühere Dateifassung. Vergleiche sie mit dem aktuellen Stand. Die Übernahme öffnet sie zur Bearbeitung und speichert noch nicht.";
    } catch (error) {
      setStatus(`Versionshistorie nicht verfügbar: ${error.message}`, "error");
    }
  }

  function offerDraft(snapshot) {
    const draft = readDraft(state.repositoryRoot, draftPath());
    if (!draft) return;
    if (draft.text === snapshot.text) {
      removeDraft(state.repositoryRoot, draftPath(), draft.text, draft.id);
      const remaining = readDrafts(state.repositoryRoot, draftPath()).find(item => item.text !== snapshot.text);
      if (!remaining) return;
      showRecovery(snapshot, remaining, remaining.revision !== snapshot.revision);
      return;
    }
    showRecovery(snapshot, draft, draft.revision !== snapshot.revision);
  }

  function showRecovery(snapshot, draft, conflict) {
    document.getElementById("recoveryTitle").textContent = "Entwurf wiederherstellen";
    document.getElementById("recoveryDraftLabel").textContent = "Deine noch nicht gespeicherten Änderungen";
    document.getElementById("recoveryDraftHelp").textContent = "Dein Text aus dem Editor, im Browser zwischengesichert. Diese Fassung ist noch nicht in der QMD-Datei gespeichert.";
    document.getElementById("recoveryVersionsLabel").textContent = "Im Browser zwischengesicherte Änderungen";
    document.getElementById("recoveryBackupLabel").textContent = "Deine noch nicht gespeicherten Änderungen separat sichern";
    document.getElementById("recoveryRestore").textContent = "Meine Änderungen weiterbearbeiten";
    document.getElementById("recoveryRestoreHelp").textContent = "Öffnet deine noch nicht gespeicherten Änderungen im Editor. Die QMD-Datei wird erst geändert, wenn du speicherst.";
    document.getElementById("recoveryDiscard").textContent = "Änderungen verwerfen · gespeicherte Datei öffnen";
    document.getElementById("recoveryDiscardHelp").textContent = "Löscht die ausgewählte Browser-Zwischensicherung und öffnet die gespeicherte QMD-Datei im Editor. Kopiere oder lade deine Änderungen vorher herunter, falls du sie noch brauchst.";
    for (const identifier of ["recoveryRestore", "recoveryCopy", "recoveryDownload"]) document.getElementById(identifier).disabled = false;
    if (state.saveTimer) clearTimeout(state.saveTimer);
    state.saveTimer = null;
    clearScheduledRender();
    const drafts = [draft, ...readDrafts(state.repositoryRoot, draftPath()).filter(item => item.id !== draft.id && item.text !== draft.text)];
    recoveryState = { snapshot, draft, drafts, session: state.session, path: draftPath() };
    const versions = document.getElementById("recoveryVersions");
    versions.replaceChildren(...drafts.map((item, index) => new Option(`${item.updated ? new Date(item.updated).toLocaleString() : "Aktueller Entwurf"} · ${item.text.slice(0, 50)}`, String(index))));
    document.getElementById("recoveryDraft").value = draft.text;
    document.getElementById("recoveryFile").value = snapshot.text;
    document.getElementById("recoveryDiff").dataset.leftLabel = "Deine noch nicht gespeicherten Änderungen";
    renderDiff?.(document.getElementById("recoveryDiff"), snapshot.text, draft.text);
    document.getElementById("recoveryHint").textContent = conflict
      ? "Die QMD-Datei wurde zwischenzeitlich geändert. Links stehen deine noch nicht gespeicherten Änderungen (Entwurf), rechts die aktuell auf der Festplatte gespeicherte Datei. Wähle unten, mit welcher Fassung du weiterarbeiten möchtest."
      : "Im Browser liegen noch nicht gespeicherte Änderungen (Entwurf). Links siehst du diesen Text, rechts die auf der Festplatte gespeicherte QMD-Datei. Wähle unten, mit welcher Fassung du weiterarbeiten möchtest.";
    openModal(document.getElementById("recoveryModal"), document.getElementById("recoveryRestore"));
  }

  function applyRecovery(restore) {
    const recovery = recoveryState;
    if (!recovery || recovery.session !== state.session || recovery.path !== draftPath()) return;
    state.revision = recovery.snapshot.revision;
    state.lastWrittenText = recovery.snapshot.text;
    setEditorText(restore ? recovery.draft.text : recovery.snapshot.text);
    state.dirty = restore && recovery.draft.text !== recovery.snapshot.text;
    updateSaveIndicator();
    if (state.dirty) {
      if (persistDraft() && recovery.draft.id && readDraft(state.repositoryRoot, recovery.path)?.id !== recovery.draft.id) {
        removeDraft(state.repositoryRoot, recovery.path, recovery.draft.text, recovery.draft.id);
      }
    } else {
      removeDraft(state.repositoryRoot, recovery.path, recovery.draft.text, recovery.draft.id);
    }
    closeModal(document.getElementById("recoveryModal"));
    setStatus(state.dirty ? "Entwurf wiederhergestellt. Bitte prüfen und speichern." : "Dateistand übernommen.", state.dirty ? "ready" : "ok");
  }

  function bindRecovery() {
    document.getElementById("showHistory").addEventListener("click", showHistory);
    document.getElementById("recoveryVersions").addEventListener("change", async event => {
      const recovery = recoveryState;
      const selection = event.target.value;
      let draft = recovery?.drafts[Number(selection)];
      if (recovery?.history) {
        const load = (recovery.load || 0) + 1;
        recovery.load = load;
        const buttons = ["recoveryRestore", "recoveryCopy", "recoveryDownload"].map(identifier => document.getElementById(identifier));
        for (const button of buttons) button.disabled = true;
        try {
          draft = await api(`/api/document/history/${recovery.history[Number(selection)].id}?path=${encodeURIComponent(recovery.path)}`);
          if (recoveryState !== recovery || recovery.load !== load) return;
        } catch (error) {
          if (recoveryState !== recovery || recovery.load !== load) return;
          event.target.value = recovery.selection || "0";
          setStatus(`Version konnte nicht geladen werden: ${error.message}`, "error");
          return;
        } finally {
          if (recoveryState === recovery && recovery.load === load) {
            for (const button of buttons) button.disabled = false;
          }
        }
      }
      if (!draft) return;
      recoveryState.draft = draft;
      recoveryState.selection = selection;
      document.getElementById("recoveryDraft").value = draft.text;
      renderDiff(document.getElementById("recoveryDiff"), document.getElementById("recoveryFile").value, draft.text);
    });
    document.getElementById("recoveryClose").addEventListener("click", () => closeModal(document.getElementById("recoveryModal")));
    document.getElementById("recoveryRestore").addEventListener("click", () => applyRecovery(true));
    document.getElementById("recoveryDiscard").addEventListener("click", () => applyRecovery(false));
    document.getElementById("recoveryCopy").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(document.getElementById("recoveryDraft").value);
        document.getElementById("recoveryHint").textContent = "Entwurf kopiert.";
      } catch {
        document.getElementById("recoveryHint").textContent = "Kopieren nicht verfügbar. Bitte Entwurf herunterladen oder den Text markieren und kopieren.";
      }
    });
    document.getElementById("recoveryDownload").addEventListener("click", () => {
      const url = URL.createObjectURL(new Blob([document.getElementById("recoveryDraft").value], { type: "text/plain;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `${draftPath().split("/").pop() || "material"}.entwurf.txt`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }

  return { showHistory, offerDraft, showRecovery, applyRecovery, bindRecovery };
}
