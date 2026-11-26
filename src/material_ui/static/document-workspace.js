import { createDocumentState } from "./document-state.js";
import { updatePresentationActions } from "./presentation-actions.js";
import { saveLastDocumentPreference } from "./ui-utils.js";

export function createDocumentWorkspace({ search, documentState, state, elements, api, editor,
  clearTimers, clearRenderReport, clearFulltextSearch, setRenderingIndicator,
  setKursMode, syncActiveDocumentMarkers, restoreTabs, updateDocumentUrl,
  updateSaveIndicator, hideRenderPanel, setStatus,
  closePicker, openDeckModal, courseEntryForPath, confirmDiscardOrSave,
  workspaceModes, registerTab, renderFolderNavigation, offerDraft, documentLabel,
  scheduleRender, uiIcon }) {
  documentState ||= createDocumentState(state);
  let pdfLoadVersion = 0;
  let loadedPdfVersion = null;
  function closeDocument() {
    state.hasSlides = false;
    elements.slidesPlay.hidden = true;
    document.dispatchEvent(new Event("material-document-changed"));
    documentState.close();
    clearTimers();
    clearRenderReport();
    clearFulltextSearch();
    setRenderingIndicator(false);
    setKursMode(false);
    updatePresentationActions(elements.slidesPlay, {});
    document.dispatchEvent(new CustomEvent("material-document-opened", { detail: { path: "" } }));
    syncActiveDocumentMarkers();
    restoreTabs([]);
    updateDocumentUrl("");
    saveLastDocumentPreference("");
    editor.setEditorText("");
    updateSaveIndicator();
    elements.documentInfo.textContent = "Kein Dokument geöffnet. Oben suchen, links in der Navigation wählen oder „Neues Material“ anlegen.";
    elements.documentInfo.hidden = false;
    elements.documentInfo.classList.remove("warning");
    elements.documentDetails.replaceChildren();
    elements.documentDetails.hidden = true;
    if (search) search.closeDocument();
    else if (state.navigationView !== "tagTree") elements.documentSearch.value = "";
    hideRenderPanel();
    showPdf(null);
    setStatus("Bereit.", "ready");
  }


  async function selectDocument(path, options = {}) {
    if (path.toLowerCase().endsWith(".excalidraw")) {
      openDeckModal(path);
      closePicker();
      return;
    }
    const entry = state.qmds.find((item) => item.path === path) || courseEntryForPath(path);
    path = entry?.path || path;
    if (!path || path === state.qmdPath) {
      closePicker();
      return;
    }
    if (!(await confirmDiscardOrSave())) return;
    // Workspace-Modus statt fest verdrahtetem Kurs-Zweig: Das kurse-Plugin
    // registriert einen Modus mit entryFor(); ohne Modus wird das Dokument geladen.
    const modeHit = workspaceModes?.modeForPath(path);
    if (modeHit) {
      await workspaceModes.enter(modeHit.mode, modeHit.entry || entry);
    } else {
      await loadDocument(path);
      if (options.line) editor.jumpToLine(options.line);
    }
    closePicker();
  }


  async function loadDocument(path) {
    if (!path) return;
    clearRenderReport();
    const load = documentState.begin();
    document.dispatchEvent(new Event("material-document-changed"));
    clearTimers();
    setRenderingIndicator(false);
    await setKursMode(false);
    if (!documentState.isCurrent(load)) return;
    editor.setAriaLabel("QMD-Editor");
    editor.setReadOnly(true);
    let data;
    try {
      data = await api(`/api/document?path=${encodeURIComponent(path)}`);
    } finally {
      if (load === state.documentLoad) editor.setReadOnly(false);
    }
    if (!documentState.accept(data, load)) return;
    document.dispatchEvent(new CustomEvent("material-document-opened", { detail: { path: data.path } }));
    state.hasSlides = data.hasSlides;
    updatePresentationActions(elements.slidesPlay, data);
    syncActiveDocumentMarkers();
    registerTab(data.path);
    updateDocumentUrl(data.path);
    const documentFolder = data.path.split("/").slice(0, -1).join("/");
    if (state.navigationView === "folder") renderFolderNavigation(documentFolder);
    else state.navigationFolder = documentFolder;
    saveLastDocumentPreference(data.path);
    editor.setAriaLabel(data.capabilities?.render === false ? "Markdown-Notizeditor" : "QMD-Editor");
    editor.setEditorText(data.text);
    state.dirty = false;
    updateSaveIndicator();
    offerDraft(data);
    elements.klasse.value = data.klasse || "";
    elements.thema.value = data.thema || "";
    const documentWarning = updateDocumentInfo(data);
    hideRenderPanel();
    const entry = state.qmds.find((item) => item.path === data.path);
    if (search) search.displayDocument(entry ? documentLabel(entry) : data.path);
    else if (state.navigationView !== "tagTree") elements.documentSearch.value = entry ? documentLabel(entry) : data.path;
    showPdf(data.pdf, false, data.pdfVersion);
    const markdownSource = data.path.toLowerCase().endsWith(".md");
    if (!documentWarning) {
      if (markdownSource) setStatus("Markdown-Quelle geladen.", "ready");
      else setStatus(data.pdf ? `PDF geladen: ${data.pdf}` : "Noch kein PDF für diese QMD gefunden.", data.pdf ? "ok" : "ready");
    }
    const stalePdf = data.pdfCurrent == null
      ? data.pdfMtime && data.sourceMtime && data.pdfMtime + 1 < data.sourceMtime
      : !data.pdfCurrent;
    if (state.autoRender && (!markdownSource || state.hasSlides) && (!data.pdf || stalePdf || data.slidesCurrent === false)) {
      setStatus("PDF-Vorschau wird erstellt …", "rendering");
      if (!data.pdf) elements.pdfEmptyState.textContent = "PDF-Vorschau wird erstellt …";
      scheduleRender();
    }
  }

  function showPdf(path, force = false, version = null) {
    if (!path) {
      state.loadedPdf = "";
      elements.pdfPreview.removeAttribute("src");
      elements.pdfEmptyState.textContent = "Noch kein PDF vorhanden. Mit „Rendern“ eine Vorschau erstellen.";
      elements.pdfEmptyState.hidden = false;
      return;
    }
    elements.pdfEmptyState.hidden = true;
    if (!force && path === state.loadedPdf && (!version || version === loadedPdfVersion)) return;
    state.loadedPdf = path;
    loadedPdfVersion = version;
    // Die Viewer-Leiste ist ausgeblendet (die eigene Vorschau-Leiste bleibt die einzige);
    // Zoom per Strg+Mausrad, volle Bedienung ueber "PDF im Tab oeffnen".
    // Auch der integrierte PDF-Viewer muss einen Neubau unter demselben
    // Dateinamen neu laden, statt seine bisherige Dokumentinstanz zu behalten.
    elements.pdfPreview.src = `/api/pdf?path=${encodeURIComponent(path)}&v=${encodeURIComponent(version || `${Date.now()}-${++pdfLoadVersion}`)}#toolbar=0&navpanes=0`;
  }

  function updateDocumentInfo(data) {
    if (!elements.documentInfo) return false;
    const lines = data.text ? data.text.split(/\r?\n/).length : 0;
    const chars = data.text ? data.text.length : 0;
    elements.documentInfo.textContent = state.qmds.find(entry => entry.path === data.path)?.title || data.path.split('/').pop();
    elements.documentDetails.replaceChildren();
    elements.documentDetails.hidden = true;
    // The active tab already identifies the document. Keep the empty-state row
    // for navigation guidance, and report document warnings through setStatus.
    elements.documentInfo.hidden = true;
    const suspiciouslyShort = Boolean(data.pdf && lines < 12 && chars < 800);
    const stalePdf = Boolean(data.pdf && (data.pdfCurrent == null
      ? data.pdfMtime && data.sourceMtime && data.pdfMtime + 1 < data.sourceMtime
      : !data.pdfCurrent));
    elements.documentInfo.classList.toggle("warning", suspiciouslyShort || stalePdf);
    if (suspiciouslyShort) {
      setStatus("Warnung: QMD ist sehr kurz, PDF stammt vermutlich aus altem Render.", "error");
      return true;
    } else if (stalePdf) {
      setStatus("QMD neuer als PDF. Bitte neu rendern.", "error");
      return true;
    }
    return false;
  }


  return { closeDocument, selectDocument, loadDocument, showPdf };
}
