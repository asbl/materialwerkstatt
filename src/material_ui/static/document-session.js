import { updatePresentationActions } from "./presentation-actions.js";
import { createRecoveryController } from "./recovery.js";
export async function saveLatest({ read, write, isCurrent, onSaved }) {
  while (isCurrent()) {
    const text = read();
    const result = await write(text);
    if (!isCurrent()) return;
    onSaved(text, result);
    if (read() === text) return;
  }
}

import { writeDraft, removeDraft } from "./drafts.js";

export function createDocumentSession({ documentState, state, elements, api, getEditorText, setEditorText, setStatus, clearScheduledRender, openModal, closeModal, renderDiff, loadKursIndex, updateSaveIndicator }) {
  let changeCheck = null;
  const { showHistory, offerDraft, showRecovery, applyRecovery, bindRecovery } = createRecoveryController({
    state, api, getEditorText, setEditorText, setStatus, clearScheduledRender,
    openModal, closeModal, renderDiff, flushPendingSave, persistDraft, draftPath, updateSaveIndicator
  });

  function draftPath() {
    return state.course.kursMode ? state.course.kursActivity?.path : state.qmdPath;
  }

  function checkExternalChanges() {
    if (!state.qmdPath || !state.revision || (state.course.kursMode && !state.course.kursActivity)) return Promise.resolve();
    if (changeCheck?.session === state.session) {
      // Der laufende Abruf kann den Dateistand vor einer inzwischen erfolgten externen
      // Änderung gelesen haben: danach genau einmal nachprüfen statt sein Ergebnis zu übernehmen.
      // Hat er schon einen Konflikt gezeigt (false), bleibt es dabei.
      changeCheck.followUp ??= changeCheck.promise.then(result => (result === false ? false : checkExternalChanges()));
      return changeCheck.followUp;
    }
    const session = state.session;
    const activity = state.course.kursMode && state.course.kursActivity;
    const endpoint = activity
      ? `/api/kurse/${encodeURIComponent(state.course.kursSlug)}/activities/${encodeURIComponent(activity.id)}`
      : `/api/document?path=${encodeURIComponent(state.qmdPath)}`;
    const pendingSave = state.savePromise;
    const check = { session };
    const revisionAtStart = state.revision;
    check.promise = (async () => {
      // Einen bereits gestarteten eigenen Schreibvorgang erst abschließen lassen.
      if (pendingSave) await pendingSave;
      if (session !== state.session) return;
      const snapshot = await api(endpoint, { cache: "no-store" });
      if (session !== state.session || snapshot.revision === state.revision) return;
      // Der Abruf kann einen eigenen Schreibvorgang überholt haben (z. B. nach „Änderung übernehmen“
      // im Chat): dann ist der Stand veraltet oder von uns selbst, kein externer Konflikt.
      if (state.savePromise || state.revision !== revisionAtStart) return;
      if (snapshot.text === state.lastWrittenText) {
        state.revision = snapshot.revision;
        return;
      }
      const text = getEditorText();
      if (text !== snapshot.text && (state.dirty || text !== state.lastWrittenText)) {
        persistDraft();
        showRecovery(snapshot, { text, revision: state.revision }, true);
        return false;
      }
      state.revision = snapshot.revision;
      state.lastWrittenText = snapshot.text;
      if (text !== snapshot.text) setEditorText(snapshot.text, { preserveSelection: true });
      state.dirty = false;
      if (!activity) {
        state.hasSlides = Boolean(snapshot.hasSlides);
        documentState?.setCapabilities(snapshot.capabilities);
        updatePresentationActions(elements.slidesPlay, snapshot);
      }
      updateSaveIndicator();
      setStatus("Aktueller Dateistand geladen.", "ok");
    })().finally(() => {
      if (changeCheck === check) changeCheck = null;
    });
    changeCheck = check;
    return check.promise;
  }

  function persistDraft() {
    const path = draftPath();
    if (!path || !state.revision) return true;
    return writeDraft(state.repositoryRoot, path, getEditorText(), state.revision);
  }

  async function confirmDiscardOrSave() {
    if (!state.dirty && !state.saveTimer && !state.savePromise) return true;
    await flushPendingSave();
    return true;
  }

  async function flushPendingSave() {
    if (state.saveTimer) {
      clearTimeout(state.saveTimer);
      state.saveTimer = null;
    }
    if (state.dirty || state.savePromise) {
      await saveDocument();
    }
  }

  async function saveDocument() {
    const requestedSession = state.session;
    if (changeCheck?.session === state.session && await changeCheck.promise === false) {
      throw new Error("Die Datei wurde extern geändert. Bitte zuerst den Dateikonflikt klären.");
    }
    if (requestedSession !== state.session) return;
    if (!state.qmdPath || (state.course.kursMode && !state.course.kursActivity)) return;
    if (state.savePromise) return state.savePromise;
    const session = state.session;
    const path = state.qmdPath;
    const slug = state.course.kursSlug;
    const activity = state.course.kursMode && state.course.kursActivity;
    const draftPath = activity ? activity.path : path;
    const endpoint = activity
      ? `/api/kurse/${encodeURIComponent(slug)}/activities/${encodeURIComponent(activity.id)}`
      : "/api/document";
    state.saving = true;
    const written = [];
    let renderNeeded = false;
    const pendingSave = saveLatest({
      read: getEditorText,
      write: async text => {
        const post = () => api(endpoint, {
          method: "POST",
          body: JSON.stringify({ path, text, revision: state.revision })
        });
        try {
          const data = await post();
          written.push(text);
          if (session === state.session) state.lastWrittenText = text;
          return data;
        } catch (error) {
          if (session !== state.session) throw error;
          if (error.status !== 409) throw error;
          const snapshot = await api(activity ? endpoint : `/api/document?path=${encodeURIComponent(path)}`);
          if (session !== state.session) throw error;
          if (snapshot.text !== text && snapshot.text !== state.lastWrittenText && !written.includes(snapshot.text)) throw error;
          state.revision = snapshot.revision;
          const data = await post();
          written.push(text);
          if (session === state.session) state.lastWrittenText = text;
          return data;
        }
      },
      isCurrent: () => session === state.session,
      onSaved: (text, data) => {
        state.revision = data.revision;
        if (data.text != null) {
          state.lastWrittenText = data.text;
          if (getEditorText() === text) {
            setEditorText(data.text);
            text = data.text;
          }
        }
        renderNeeded ||= data.renderNeeded !== false;
        if (!activity) {
          state.hasSlides = Boolean(data.hasSlides);
          documentState?.setCapabilities(data.capabilities);
          updatePresentationActions(elements.slidesPlay, data);
        }
        state.dirty = getEditorText() !== text;
        updateSaveIndicator();
        removeDraft(state.repositoryRoot, draftPath, text);
        if (state.dirty) persistDraft();
      }
    }).then(() => {
      if (session !== state.session) return;
      document.dispatchEvent(new CustomEvent("material-document-saved", { detail: { path } }));
      setStatus("Gespeichert.", "ok");
      if (activity) loadKursIndex(slug);
      return { renderNeeded };
    }).catch(async error => {
      if (session === state.session) {
        persistDraft();
        if (error.status === 409) {
          const snapshot = await api(activity ? endpoint : `/api/document?path=${encodeURIComponent(path)}`);
          if (session === state.session) showRecovery(snapshot, { text: getEditorText(), revision: state.revision }, true);
        }
      }
      throw error;
    }).finally(() => {
      if (state.savePromise === pendingSave) {
        state.saving = false;
        state.savePromise = null;
        updateSaveIndicator();
      }
    });
    state.savePromise = pendingSave;
    return pendingSave;
  }

  return { checkExternalChanges, bindRecovery, draftPath, showHistory, persistDraft, offerDraft, showRecovery, applyRecovery, confirmDiscardOrSave, flushPendingSave, saveDocument };
}
