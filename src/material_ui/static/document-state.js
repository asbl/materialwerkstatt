// Lifecycle transitions shared by document and plugin editors. Async results must
// carry the load/session token; old requests cannot populate a newer workspace.
export function createDocumentState(state) {
  let capabilities = Object.freeze({ edit: true, render: true, present: true });
  function begin() {
    state.session += 1;
    state.documentLoad += 1;
    state.renderJob = null;
    capabilities = Object.freeze({ edit: false, render: false, present: false });
    state.savePromise = null;
    state.saving = false;
    return state.documentLoad;
  }
  function accept(snapshot, token = state.documentLoad) {
    if (token !== state.documentLoad) return false;
    capabilities = Object.freeze({ edit: true, render: true, present: true, ...snapshot.capabilities });
    state.qmdPath = snapshot.path;
    state.revision = snapshot.revision;
    state.lastWrittenText = snapshot.text;
    state.dirty = false;
    return true;
  }
  return Object.freeze({
    begin,
    accept,
    canRender: () => capabilities.render,
    setCapabilities(value) { capabilities = Object.freeze({ ...capabilities, ...value }); },
    isCurrent: token => token === state.documentLoad,
    close() {
      begin();
      accept({ path: "", revision: null, text: null });
      capabilities = Object.freeze({ edit: false, render: false, present: false });
      state.hasSlides = false;
    },
    snapshot: () => Object.freeze({ path: state.qmdPath, revision: state.revision, session: state.session })
  });
}
