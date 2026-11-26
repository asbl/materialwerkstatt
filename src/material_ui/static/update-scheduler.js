export function createUpdateScheduler({ state, elements, api, persistDraft, updateSaveIndicator, saveDocument, setStatus, renderDocument, canRender = () => true }) {
  function scheduleAutoUpdate() {
    state.dirty = true;
    const protectedDraft = persistDraft();
    if (!protectedDraft) setStatus("Lokale Sicherung nicht verfügbar. Bitte Änderungen zeitnah speichern oder kopieren.", "error");
    updateSaveIndicator();
    if (!state.autoSave) return;
    if (state.saveTimer) clearTimeout(state.saveTimer);
    if (state.renderTimer) clearTimeout(state.renderTimer);
    state.saveTimer = setTimeout(async () => {
      state.saveTimer = null;
      try {
        const session = state.session;
        const result = await saveDocument();
        if (session !== state.session) return;
        if (!state.course.kursMode && !canRender()) {
          clearScheduledRender();
          setStatus("Notiz gespeichert.", "ok");
          return;
        }
        if (state.course.kursMode) {
          setStatus("Aktivität gespeichert.", "ok");
          return;
        }
        if (state.autoRender && result?.renderNeeded !== false) {
          scheduleRender();
        } else {
          clearScheduledRender();
          setStatus(state.autoRender ? "Gespeichert. Darstellung ist aktuell." : "Gespeichert. Rendern manuell starten.", "ok");
        }
      } catch (error) {
        state.saving = false;
        setStatus(`Speichern fehlgeschlagen: ${error.message}`, "error");
      }
    }, 700);
  }

  function scheduleRender() {
    if (!canRender() || state.course.kursMode || (state.qmdPath?.endsWith(".md") && !state.hasSlides)) return;
    if (state.renderTimer) clearTimeout(state.renderTimer);
    state.renderTimer = setTimeout(async () => {
      state.renderTimer = null;
      if (state.course.kursMode) return;
      try {
        setStatus("Render wird gestartet …", "rendering");
        await renderDocument();
      } catch (error) {
        setStatus(`Render-Start fehlgeschlagen: ${error.message}`, "error");
      }
    }, 1200);
  }

  function clearScheduledRender() {
    if (state.renderTimer) {
      clearTimeout(state.renderTimer);
      state.renderTimer = null;
    }
  }

  function clearTimers() {
    state.pollFailures = {};
    for (const key of ["saveTimer", "renderTimer", "pollTimer", "kursAuditPollTimer", "kursPreviewPollTimer", "kursMoodlePollTimer"]) {
      const owner = key.startsWith("kurs") ? state.course : state;
      if (owner[key]) {
        clearTimeout(owner[key]);
        owner[key] = null;
      }
    }
  }


  return { scheduleAutoUpdate, scheduleRender, clearScheduledRender, clearTimers };
}
