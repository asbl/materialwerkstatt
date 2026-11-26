export function createTemplateUpdateController({ state, api, getEditorText, setEditorText, flushPendingSave, saveDocument, confirmUpdate = message => window.confirm(message) }) {
  let pending = null;

  async function check() {
    const session = state.session;
    const path = state.qmdPath;
    const isCurrent = () => session === state.session && path === state.qmdPath;
    if (!path || state.course.kursMode) return true;
    await flushPendingSave();
    if (!isCurrent()) return false;
    const { offer } = await api(`/api/document/template-update?path=${encodeURIComponent(path)}`);
    if (!isCurrent()) return false;
    if (!offer) return true;
    const text = getEditorText();
    const accept = await confirmUpdate(
      `Für dieses Dokument ist Template-Version v${offer.version} verfügbar (bisher v${offer.currentVersion}).\n\n`
      + (offer.note ? `${offer.note}\n\n` : "")
      + "Jetzt die neueste Version verwenden?\nOK: aktualisieren · Abbrechen: bisherige Version behalten.\nDie Entscheidung gilt für dieses Dokument; bei einer neuen Version fragen wir erneut."
    );
    if (!isCurrent() || text !== getEditorText()) return false;
    const data = await api("/api/document/template-update", {
      method: "POST", body: JSON.stringify({ text, release: offer.release, accept })
    });
    if (!isCurrent() || text !== getEditorText()) return false;
    setEditorText(data.text);
    await saveDocument();
    return isCurrent();
  }

  function beforeRender() {
    if (pending?.session === state.session) return pending.promise;
    const operation = { session: state.session };
    operation.promise = check().finally(() => { if (pending === operation) pending = null; });
    pending = operation;
    return operation.promise;
  }

  return { beforeRender };
}
