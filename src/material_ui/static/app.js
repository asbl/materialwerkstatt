import { createMarkdownPreview } from "./markdown-preview.js";
import { createDocumentState } from "./document-state.js";
import { createSearchState } from "./search-state.js";
import { createSearchProviderRegistry } from "./search-providers.js";
import { createFulltextState } from "./fulltext-state.js";
import { createTemplateUpdateController } from "./template-updates.js";
import { createImageImportController } from "./image-import.js";
import { registerUnitsView } from "./units.js";
import { createWorksheetTools } from "./worksheet-tools.js";
import { createDocumentWorkspace } from "./document-workspace.js";
import { stateView } from "./state-view.js";
import { createSlidesController } from "./slides-panel.js";
import { createUpdateScheduler } from "./update-scheduler.js";
import { createDiagnosticsController } from "./diagnostics.js";
import { createTemplateCatalog } from "./template-catalog.js";
import { createNavigationController } from "./navigation.js";
import { createViewRegistry, loadActiveViewPreference } from "./views.js";
import { loadPlugins } from "./plugins/loader.js";
import { createWorkspaceChrome, createWorkspaceLayout } from "./workspace-layout.js";
import { createAppState, collectElements } from "./app-state.js";
import { formatTimestamp, saveAutoRenderPreference, saveTagYearFilterPreference, saveAutoSavePreference, normalizeSearch, slug, escapeHtml, loadLastDocumentPreference, saveLastDocumentPreference } from "./ui-utils.js";
import { api } from "./api.js";
import { createDocumentSession } from "./document-session.js";
import { createWorkspaceModeRegistry } from "./workspace-modes.js";
import { createPathResolverRegistry } from "./path-resolvers.js";
import { createImageController } from "./images.js";
import { createEditorController } from "./editor.js";
import { createTemplateController } from "./templates.js";
import { createModalController } from "./modals.js";
import { createThemeController } from "./theme.js";
import { createShortcutController, SHORTCUTS } from "./shortcuts.js";
import { createPickerController } from "./picker.js";
import { createRenderPanelController } from "./render-panel.js";
import { createJobsController } from "./jobs-panel.js";
import { createSettingsController } from "./settings.js";
import { renderDiff } from "./diff.js";
import { createFileActionController } from "./file-actions.js";
import { createQmdImportController } from "./qmd-import.js";
import { createNewDocumentController } from "./new-document.js";
import { createMetadataController } from "./metadata-panel.js";
import { createGitController } from "./git-panel.js";
import { createTabsController } from "./tabs.js";
import { createWindowController } from "./windows.js";

const state = createAppState();
const documentState = createDocumentState(state);
const elements = collectElements();
const search = createSearchState({ elements, getContext: () => state.navigationView });
// Lokale Such-Quellen der Plugins (ctx.search.registerProvider) fuer den Picker.
const searchProviders = createSearchProviderRegistry();
// Volltext-Zustand des Pickers (eigenes Modul statt globalem App-State).
const fulltext = createFulltextState();

// Plugin-Features (chat, importe) registrieren ihre Controller hier; ohne geladenes
// Plugin bleiben die Hooks No-Ops und die zugehörigen UI-Elemente werden ausgeblendet.
const pluginControllers = { chat: null, officeImport: null, taskImageImport: null };
const refreshChatContext = () => pluginControllers.chat?.refreshContext?.();
const ensureChatProvidersLoaded = () => pluginControllers.chat?.ensureProvidersLoaded?.();


function createSaveFeedback(element) {
  let timer = null;
  return (outcome, message = "") => {
    if (!element) return;
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    if (outcome === "clear") {
      element.hidden = true;
      element.replaceChildren();
      return;
    }
    const icon = outcome === "ok" ? "success" : "warning";
    element.className = `save-feedback ${outcome}`;
    element.innerHTML = `<svg class="icon" aria-hidden="true" focusable="false"><use href="/static/icons.svg#${icon}"></use></svg>${escapeHtml(message)}`;
    element.hidden = false;
    if (outcome === "ok") timer = setTimeout(() => { element.hidden = true; }, 3000);
  };
}

const flashDocSaveFeedback = createSaveFeedback(elements.docSaveFeedback);
const flashCourseSaveFeedback = createSaveFeedback(elements.courseSaveFeedback);

async function saveDocumentWithFeedback() {
  try {
    await saveDocument();
    flashDocSaveFeedback("ok", "Gespeichert");
  } catch (error) {
    flashDocSaveFeedback("error", "Speichern fehlgeschlagen");
    throw error;
  }
}

// Eigene Änderungen sichern und danach den Dateistand von der Platte übernehmen
// (wie „Neu laden“). Liefert false, wenn inzwischen ein anderes Dokument aktiv ist.
async function reloadCurrentDocument() {
  const path = state.qmdPath;
  if (!path || !(await confirmDiscardOrSave())) return false;
  const editorFocused = elements.editorHost.contains(document.activeElement);
  await loadDocument(path);
  if (state.qmdPath !== path) return false;
  // Der Editor ist während des Ladens schreibgeschützt und verliert dabei den Fokus.
  if (editorFocused && !elements.editorHost.contains(document.activeElement)) editor.focus();
  return true;
}

let manualRender = null;

// Manuelles Rendern (Button, Strg+Enter) lädt die Datei vorher neu, damit Editor
// und PDF denselben Stand zeigen, auch nach Änderungen von außen. Ungespeicherte
// Änderungen bleiben unberührt: renderDocument prüft sie erst und speichert danach;
// ein abweichender Dateistand meldet sich dort als Konflikt.
function reloadAndRenderDocument() {
  if (manualRender) return manualRender;
  manualRender = (async () => {
    try {
      const unchanged = !state.dirty && !state.saveTimer && !state.savePromise;
      if (unchanged && !state.course.kursMode && state.qmdPath && documentState.canRender()) {
        if (!(await reloadCurrentDocument())) return;
        clearScheduledRender();
      }
      await renderDocument();
    } catch (error) {
      setStatus(`Render-Start fehlgeschlagen: ${error.message}`, "error");
    } finally {
      manualRender = null;
    }
  })();
  return manualRender;
}

const { uiIcon, openModal, closeModal, trapModalFocus } = createModalController({ state: stateView(state, ["lastFocus"]), focusEditor: () => editor.focus() });
const themeController = createThemeController();
const markdownPreview = createMarkdownPreview({ state, api, canRender: documentState.canRender, getText: () => editor.getEditorText() });

const { scheduleAutoUpdate, scheduleRender, clearScheduledRender, clearTimers } = createUpdateScheduler({
  canRender: documentState.canRender,
  state: stateView(state, [
    "autoRender", "autoSave", "course", "dirty", "hasSlides", "pollFailures", "pollTimer",
    "qmdPath", "renderJob", "renderTimer", "saveTimer", "saving", "session"
  ]), elements, api, persistDraft: () => persistDraft(), updateSaveIndicator,
  saveDocument: () => saveDocument(), setStatus, renderDocument: () => renderDocument()
});

const { loadTemplates, populateTemplateSelect, renderTemplatePreview } = createTemplateCatalog({ state: stateView(state, ["slideTemplates", "templates"]), elements: stateView(elements, ["newTemplate", "templateSelect"]), api, escapeHtml });

const views = createViewRegistry({
  state: stateView(state, ["navigationView"]),
  rail: elements.viewRail,
  sections: elements.indexContent,
  onLeaveActive: async () => {
    if (!state.course.kursMode) return true;
    if (!(await confirmDiscardOrSave())) return false;
    closeDocument();
    return true;
  },
  saveActiveView: (id) => {
    try {
      localStorage.setItem("material-ui:active-view", id);
    } catch {
      // Die UI funktioniert auch ohne persistierte Ansichtswahl.
    }
  }
});

// Plugin-Registries: Pfad-Resolver (z. B. Kurs-MDX) und Workspace-Modi (z. B. "kurs").
const pathResolvers = createPathResolverRegistry();
const setWorkspaceChrome = createWorkspaceChrome(elements);
const workspaceModes = createWorkspaceModeRegistry();
// PfadResolver für Nicht-QMD-Pfade; Plugins (z. B. kurse) registrieren hier.
const courseEntryForPath = (path) => pathResolvers.resolve(path);

const {
  setNavigationView, renderTagNavigation, openTagRenameModal, closeTagRenameModal,
  applyTagRename, navigateFolderInput, loadFolderChildren, syncActiveDocumentMarkers,
  selectFolderRow, renderFolderNavigation, reloadCurrentFolder
} = createNavigationController({ search,
  state: stateView(state, [
    "course", "folderCache", "folderTreeLoaded", "navigationFolder",
    "navigationLoad", "navigationView", "qmdPath", "qmds", "rootTags", "tagParents",
    "tagYearFilter"
  ]), elements: stateView(elements, [
    "applyTagRename", "folderEntries", "folderNavigation", "folderNavHeading",
    "folderViewButton",
    "folderViewControls", "navigationFolder", "navigationFolders", "newDocInFolder",
    "tagEntries", "tagNavigation",
    "tagNavigationHint", "tagRenameModal", "tagRenameParent", "tagRenameParentOptions",
    "tagRenameRoot", "tagRenameSegment", "tagRenameStatus", "tagTreeViewButton",
    "tagBadges", "tagBadgePanel", "tagPagination", "tagBreadcrumbs", "tagBack", "tagActiveFilters", "tagFilterDetails", "tagTopicsHeading", "tagYearFilter", "tagSearch", "tagKindFilter", "tagReset", "tagResults", "tagResultsHeading", "tagPageStatus", "tagPrevious", "tagNext"
  ]), views, api, escapeHtml, uiIcon, openModal, closeModal, setStatus,
  courseEntryForPath: path => courseEntryForPath(path),
  fileActionButtons: entry => fileActionButtons(entry),
  folderMetadataChanged: () => {
    renderFilterChips();
    renderFacetFilters();
    renderDocumentResults(false);
  },
  refreshChatContext: () => refreshChatContext()
});

const {
  setIndexCollapsed, setFocusMode, setFocusModePersisted, setChatOpen,
  setChatOpenPersisted, applyIndexWidth, bindPreviewControls, bindIndexResizer
} = createWorkspaceLayout({ elements: stateView(elements, [
    "chatInput", "indexContent", "indexResizer", "showChat", "toggleFocusMode",
    "toggleIndex", "workspace"
  ]), uiIcon, ensureChatProvidersLoaded: () => ensureChatProvidersLoaded() });


const templateUpdates = createTemplateUpdateController({
  state: stateView(state, ["session", "qmdPath", "course"]), api,
  getEditorText: () => editor.getEditorText(),
  setEditorText: text => editor.setEditorText(text),
  flushPendingSave: () => flushPendingSave(),
  saveDocument: () => saveDocument()
});

const {
  setRenderingIndicator, renderDocument, pollRender, readJobStatus,
  initJobStream, showRenderPanel, showCheckPanel, hideRenderPanel,
  reopenRenderPanel, clearRenderReport, jumpToLogLine
} = createRenderPanelController({
  canRender: documentState.canRender,
  state: stateView(state, [
    "course", "loadedPdf", "pollFailures", "pollTimer", "qmdPath", "renderJob",
    "renderReport", "session"
  ]), elements: stateView(elements, [
    "pdfEmptyState", "pdfRenderingOverlay", "renderCommand", "renderExitCode", "renderLog",
    "renderPanel", "renderPanelTitle", "renderSource", "showRenderPanel"
  ]), api, escapeHtml, setStatus, showPdf, flushPendingSave: () => flushPendingSave(),
  jumpToLine: (line) => editor.jumpToLine(line),
  beforeRender: async () => await diagnostics.check({ beforeRender: true }) && await templateUpdates.beforeRender(),
  onPreflightFailure: issues => diagnostics.rejectRender(issues),
  onRenderStatus: data => diagnostics.updateRender(data)
});

const {
  renderFilterChips, renderFacetFilters, bindFacetChange, renderDocumentResults,
  documentSearchQuery, documentLabel, openPicker, closePicker, handlePickerKeys,
  scheduleFulltextSearch, clearFulltextSearch, registerCommands, focusSearch
} = createPickerController({ search, searchProviders, fulltext, state: stateView(state, [
    "activeFilter", "activeResult", "facetFilters", "filteredQmds", "qmdPath", "qmds"
  ]), elements: stateView(elements, [
    "documentResults", "documentSearch", "filterChips", "gradeFilter", "kindFilter",
    "pdfFilter", "searchOverlay", "sortFilter", "subjectFilter", "tagFilter",
    "tagFilterOptions"
  ]), api, escapeHtml, normalizeSearch, selectDocument, uiIcon });

const { loadTabs, restoreTabs, registerTab, removeTab, renameTab, closeTab, bindTabs } = createTabsController({
  state: stateView(state, ["autoSave", "dirty", "qmdPath", "savePromise", "saveTimer", "tabs"]), elements: stateView(elements, ["documentTabs"]), escapeHtml, uiIcon, tabLabel, selectDocument, closeDocument,
  flushPendingSave: () => flushPendingSave(), setStatus, onDeleted: () => unitsView.refresh()
});

const windowController = createWindowController({
  api,
  onOpenPath: (path) => selectDocument(path),
  onOpenImport: (token) => openQmdImport(token)
});

const editor = createEditorController({
  checkExternalChanges: () => checkExternalChanges(),
  onShortcut: id => openShortcutFromEditor(id),
  onSelectionChange: () => refreshChatContext(),
  onDocumentChange: () => { diagnostics.schedule(); markdownPreview.schedule(); },
  state: stateView(state, ["course", "qmdPath"]), elements: stateView(elements, ["editorHost", "editorStatus"]), scheduleAutoUpdate,
  flushPendingSave: () => flushPendingSave(), saveDocument: () => saveDocumentWithFeedback(),
  saveCourseActivity: () => saveAndRefreshCourseActivity(), setStatus, renderDocument: () => reloadAndRenderDocument(),
  shortcuts: SHORTCUTS, normalizeSearch
});

const diagnostics = createDiagnosticsController({ state: stateView(state, ["course", "dirty", "qmdPath", "revision", "session"]), api, editor, setStatus });

const { checkExternalChanges, bindRecovery, draftPath, showHistory, persistDraft, offerDraft, showRecovery, applyRecovery, confirmDiscardOrSave, flushPendingSave, saveDocument } = createDocumentSession({ documentState,
  state: stateView(state, [
    "course", "dirty", "hasSlides", "lastWrittenText", "qmdPath", "repositoryRoot",
    "revision", "savePromise", "saveTimer", "saving", "session"
  ]), elements: stateView(elements, ["slidesPlay"]), api, getEditorText: () => editor.getEditorText(), setEditorText: (text, options) => editor.setEditorText(text, options),
  setStatus, clearScheduledRender, openModal, closeModal, renderDiff,
  loadKursIndex: slug => loadKursIndex(slug), updateSaveIndicator
});
const { playSlides } = createSlidesController({
  api, button: elements.slidesPlay,
  getDocument: () => !state.course.kursMode && state.qmdPath && state.hasSlides
    ? { path: state.qmdPath, session: state.session } : null,
  flush: flushPendingSave, setStatus, openDeck: openDeckModal
});

// Kurs-Logik liegt im Plugin `kurse` (registriert einen Workspace-Modus mit Actions).
// Der Kern delegiert an den aktiven Modus; vor dem Laden des Plugins sind die
// Aufrufe No-ops (außer setKursMode, das nur die Kern-Slots umschaltet).
const kursActions = () => workspaceModes.actions() || {};
// Verlassen des Kursmodus räumt auch den aktiven Modus ab, damit ein erneutes
// Öffnen über enter() nicht an activeMode === mode hängen bleibt.
const setKursMode = (active) => {
  if (!active) return workspaceModes.leave();
};
const openKursView = (entry) => {
  const hit = entry?.path ? workspaceModes.modeForPath(entry.path) : null;
  if (hit) return workspaceModes.enter(hit.mode, hit.entry || entry);
};
const loadKursIndex = (...args) => kursActions().loadKursIndex?.(...args);
const openKursActivity = (...args) => kursActions().openKursActivity?.(...args);
const refreshCourseActivityPreview = (...args) => kursActions().refreshCourseActivityPreview?.(...args);
const saveAndRefreshCourseActivity = (...args) => kursActions().saveAndRefreshCourseActivity?.(...args);
const startKursAudit = (...args) => kursActions().startKursAudit?.(...args);
const pollKursAudit = (...args) => kursActions().pollKursAudit?.(...args);
const moodleChapterOptionsHtml = (...args) => kursActions().moodleChapterOptionsHtml?.(...args) ?? "";
const openMoodleConfirm = (...args) => kursActions().openMoodleConfirm?.(...args);
const closeMoodleConfirmModal = (...args) => kursActions().closeMoodleConfirmModal?.(...args);
const startKursMoodleJob = (...args) => kursActions().startKursMoodleJob?.(...args);
const pollKursMoodleJob = (...args) => kursActions().pollKursMoodleJob?.(...args);
const startKursPreview = (...args) => kursActions().startKursPreview?.(...args);
const stopKursPreview = (...args) => kursActions().stopKursPreview?.(...args);
const pollKursPreview = (...args) => kursActions().pollKursPreview?.(...args);
const showKursPreviewMessage = (...args) => kursActions().showKursPreviewMessage?.(...args);
const showKursPreviewError = (...args) => kursActions().showKursPreviewError?.(...args);
const showKursPreview = (...args) => kursActions().showKursPreview?.(...args);
const { loadFile, redraw, finishDrag, edits, resetCropBox, isCropped, currentTool, canvasPoint, normalizedBox, clampBox, drawSelection, fitImage, setImageZoom, applyCanvasZoom, clearImageState, readAsDataUrl, loadImage, imageToPngDataUrl, normalizeImage, canvasToBlob, dataUrlToBlob } = createImageController({ state: state.image, elements: stateView(elements, [
    "actualSize", "canvas", "filename", "fitImage", "grayscale", "imageStatus", "imageZoom",
    "importAsset", "removeGreen", "resetCrop", "undoWhiteout"
  ]), slug });

const { openTemplateModal, closeTemplateModal, applySelectedTemplate, removeTemplate, selectTemplateType } = createTemplateController({
  state: stateView(state, ["hasSlides", "qmdPath", "session", "templates"]), elements: stateView(elements, [
    "applyTemplate", "removeTemplate", "slidesPlay", "templateModal", "templatePreview", "templateSelect",
    "templateStatus", "templateType"
  ]), getEditorText: () => editor.getEditorText(), setEditorText: (text, options) => editor.setEditorText(text, options), setStatus, scheduleAutoUpdate, populateTemplateSelect, renderTemplatePreview, openModal, closeModal
});

const { openShortcutsModal, closeShortcutsModal, renderShortcutsList, openShortcutFromEditor } = createShortcutController({
  state: stateView(state, ["course", "shortcutFilter"]), elements: stateView(elements, ["shortcutsChips", "shortcutsList", "shortcutsModal", "shortcutsSearch"]), escapeHtml, normalizeSearch, openModal, closeModal,
  insertTemplate: editor.insertTemplate, insertText: editor.insertText, focusEditor: editor.focus, scheduleAutoUpdate
});

const { fileActionButtons, openFileAction, closeFileActionModal, confirmFileAction } = createFileActionController({
  state: stateView(state, ["qmdPath", "tabs", "navigationFolder"]), elements, api, escapeHtml, uiIcon, openModal, closeModal,
  applyQmds, loadDocument, selectDocument, renameTab, closeTab, removeTab, flushPendingSave: () => flushPendingSave(), setStatus, onDeleted: () => unitsView.refresh()
});

const { openQmdImport, cancelQmdImport, confirmQmdImport } = createQmdImportController({
  state: stateView(state, ["qmdPath"]), elements, api, openModal, closeModal, updateDocumentUrl, applyQmds, loadDocument, confirmDiscardOrSave, setStatus
});

const { isKursKind, openNewDocModal, closeNewDocModal, applyTemplateSuggestion, updateNewDocPathPreview, createNewDocument } = createNewDocumentController({
  state: stateView(state, ["autoRender", "slideTemplates", "templates"]), elements: stateView(elements, [
    "newDocModal", "newDocQuartoFields", "newDocStatus", "newFilename", "newGrade",
    "newKind", "newKursFields", "newKursLanguage", "newKursSlug", "newSubject",
    "newTargetFolder", "newTargetFolderField", "newTemplate", "newTemplatePreview",
    "newTitle", "newTopic", "newMiniField", "newMini", "createNewDoc"
  ]), api, normalizeSearch, slug, openModal, closeModal, applyQmds, loadDocument,
  openKursView, confirmDiscardOrSave, setStatus, renderTemplatePreview, populateTemplateSelect, scheduleRender, playSlides, onCreated: () => unitsView.refresh()
});

const { openMetadataModal, closeMetadataModal, applyMetadata } = createMetadataController({
  state: stateView(state, ["course", "qmdPath"]), elements, api, getEditorText: () => editor.getEditorText(), setEditorText: (text, options) => editor.setEditorText(text, options),
  scheduleAutoUpdate, openModal, closeModal, setStatus
});

const { openGitModal, closeGitModal, refreshGit } = createGitController({
  state: stateView(state, ["course", "qmdPath"]), elements, api, openModal, closeModal, flushPendingSave: () => flushPendingSave(), setStatus
});

const { openJobsModal, closeJobsModal, refreshJobs } = createJobsController({ state, elements: stateView(elements, ["jobsList", "jobsModal", "jobsStatus", "refreshJobs"]), api, openModal, closeModal, setStatus });

const { openSettingsModal, closeSettingsModal } = createSettingsController({ elements, api, openModal, closeModal, setStatus, restartServer });

const workspace = createDocumentWorkspace({ search, documentState,
  state: stateView(state, [
    "autoRender", "dirty", "documentLoad", "hasSlides", "lastWrittenText", "loadedPdf",
    "navigationFolder", "navigationView", "qmdPath", "qmds", "renderJob", "revision",
    "session"
  ]), elements: stateView(elements, [
    "documentInfo", "documentDetails", "documentSearch", "klasse", "pdfEmptyState", "pdfPreview", "slidesPlay",
    "thema"
  ]), api,
  editor, clearTimers, clearRenderReport, clearFulltextSearch, setRenderingIndicator,
  setKursMode, syncActiveDocumentMarkers, restoreTabs, updateDocumentUrl,
  updateSaveIndicator, hideRenderPanel, setStatus, closePicker, openDeckModal,
  courseEntryForPath, confirmDiscardOrSave, workspaceModes, registerTab,
  renderFolderNavigation, offerDraft, documentLabel, scheduleRender, uiIcon
});

function closeDocument(...args) { return workspace.closeDocument(...args); }
function selectDocument(...args) { return workspace.selectDocument(...args); }
function loadDocument(...args) { return workspace.loadDocument(...args); }
function showPdf(...args) { return workspace.showPdf(...args); }

const unitsView = registerUnitsView({ views, api, selectDocument,
  deleteMaterial: path => openFileAction("delete", path),
  openWorksheetNote,
  beforeMove: () => confirmDiscardOrSave(),
  onMoved: async (source, result) => { renameTab(source, result.path); applyQmds(result); if (state.qmdPath === source) await loadDocument(result.path); },
  getDocumentPath: () => state.qmdPath, createNote: unit => openNewDocModal(unit.path, { kind: "Notiz", subject: unit.fach, grade: unit.klasse.replace("klasse-", ""), topic: unit.data.thema, title: "", filename: "" }), createWorksheet: unit => openNewDocModal(unit.path, { kind: "Arbeitsblatt", subject: unit.fach, grade: unit.klasse.replace("klasse-", ""), topic: unit.data.thema, title: "", filename: "" }) });

const { importAsset } = createImageImportController({
  state: stateView(state, ["image", "session", "qmdPath", "revision", "dirty"]),
  elements: stateView(elements, ["insert", "canvas", "filename", "width", "alt", "source", "page", "kind", "description", "klasse", "thema", "tags", "taskBlock"]),
  api, editor, flushPendingSave, canvasToBlob, dataUrlToBlob, edits,
  showPdf, setStatus, clearImageState, closeImageModal, scheduleRender
});

init();

async function init() {
  bindEvents();
  bindTabs();
  themeController.init();
  initJobStream();
  windowController.start();
  views.activateInitial();
  const savedView = loadActiveViewPreference();
  if (savedView && savedView !== state.navigationView && views.has(savedView)) {
    await views.switchTo(savedView);
  } else if (!savedView) {
    // Ohne gespeicherte Ansichtswahl starten die Unterrichtseinheiten als
    // Standardansicht (frueher: implizit "Heute" ueber den Plugin-Loader);
    // gespeicherte Wahlen - auch Plugin-Ansichten - bleiben bewusst erhalten.
    await views.switchTo("units");
  }
  // Plugins vor dem ersten Dokumentladen laden, damit Pfad-Resolver und
  // Workspace-Modi (z. B. kurse) beim Öffnen bereitstehen.
  const hostDependencies = {
    state, elements, api, escapeHtml, setWorkspaceChrome, search, documentState,
    clearRenderReport, clearTimers, updateDocumentUrl, saveLastDocumentPreference,
    hideRenderPanel, documentLabel, renderFolderNavigation, confirmDiscardOrSave,
    setEditorText: (text, options) => editor.setEditorText(text, options), editor,
    offerDraft, flushPendingSave: () => flushPendingSave(), setStatus, readJobStatus,
    showRenderPanel, openModal, closeModal, setRenderingIndicator, updateSaveIndicator,
    flashSaveFeedback: flashCourseSaveFeedback, registerTab, selectDocument,
    applyQmds, loadDocument,
    registerController: (name, controller) => { pluginControllers[name] = controller; },
    chat: {
      elements: stateView(elements, [
        "chatContext", "chatInput", "chatMessages", "chatModel", "chatNew", "chatProvider", "chatSend",
        "chatStop", "chatUsage"
      ]),
      getDocument: () => {
        if (state.course.kursMode || !state.qmdPath || !/\.(qmd|md|tex)$/i.test(state.qmdPath)) return null;
        const selection = editor.getSelection();
        return { path: state.qmdPath, text: editor.getEditorText(),
          selection: selection?.end > selection?.start ? selection : null };
      },
      replaceText: (offset, length, text) => {
        editor.setSelectionRange(offset, offset + length);
        editor.insertText(text);
      },
      openDocument: path => selectDocument(path)
    },
    taskImage: {
      state: stateView(state, ["dirty", "qmdPath", "session"]),
      getEditorText: () => editor.getEditorText(),
      setEditorText: (text, options) => editor.setEditorText(text, options)
    }
  };
  await loadPlugins({
    api, views, state, units: unitsView,
    ui: { openModal, closeModal, setStatus },
    workspace: workspaceModes,
    documents: pathResolvers,
    documentPreview: markdownPreview,
    search: searchProviders,
    openDocument: path => selectDocument(path),
    saveCurrentDocument: () => flushPendingSave(),
    hostApis: {
      // Namen entsprechen `hostApis` in den plugin.json; jedes Plugin erhält nur, was es deklariert.
      chat: () => ({ chat: hostDependencies.chat, registerController: hostDependencies.registerController }),
      "task-import": () => Object.fromEntries([
        "taskImage", "openModal", "closeModal", "applyQmds", "loadDocument", "confirmDiscardOrSave",
        "setStatus", "flushPendingSave", "registerController"
      ].map(key => [key, hostDependencies[key]])),
      "course-workspace": () => ({
        ...hostDependencies,
        chat: undefined, taskImage: undefined,
        state: stateView(state, ["course", "dirty", "documentLoad", "lastWrittenText", "loadedPdf",
          "navigationView", "qmdPath", "qmds", "renderJob", "revision", "session"])
      })
    },
    onStatus: setStatus
  }).catch(() => {});
  // UI-Elemente ohne geladenes Plugin ausblenden (Chat-Dock-Button, Office-Import).
  document.getElementById("showChat").hidden = !pluginControllers.chat;
  setChatOpen(Boolean(pluginControllers.chat) && elements.workspace.classList.contains("chat-open"));
  document.getElementById("officeImportBtn").hidden = !pluginControllers.officeImport;
  elements.newMenuToggle.hidden = !pluginControllers.officeImport;
  await loadTemplates();
  await loadQmds();
  const token = new URLSearchParams(window.location.search).get("import");
  if (token) await openQmdImport(token);
}

function tabLabel(path) {
  const entry = state.qmds.find((item) => item.path === path) || courseEntryForPath(path);
  return entry?.title || entry?.stem || path.split("/").pop() || path;
}

function updateDocumentUrl(path) {
  document.title = path ? `${tabLabel(path)} – Material UI` : "Material UI";
  const url = new URL(window.location.href);
  url.searchParams.delete("import");
  if (path) url.searchParams.set("path", path);
  else url.searchParams.delete("path");
  window.history.replaceState(null, "", url);
}

function bindArrowKeyListNavigation(container) {
  container.addEventListener("keydown", (event) => {
    if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
    const focusable = [...container.querySelectorAll("button, summary")].filter(element => element.checkVisibility() && !(element.matches("summary") && element.querySelector("button")));
    const index = focusable.indexOf(document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    const next = focusable[(index + (event.key === "ArrowDown" ? 1 : -1) + focusable.length) % focusable.length];
    next?.focus();
  });
}

function bindEvents() {
  bindRecovery();
  document.getElementById("qmdImportForm").addEventListener("submit", confirmQmdImport);
  for (const id of ["qmdImportClose", "qmdImportBackdrop"]) {
    document.getElementById(id).addEventListener("click", cancelQmdImport);
  }
  document.getElementById("fileActionForm").addEventListener("submit", confirmFileAction);
  for (const id of ["fileActionCancel", "fileActionClose", "closeFileActionModal"]) {
    document.getElementById(id).addEventListener("click", closeFileActionModal);
  }
  document.getElementById("metadataModal").addEventListener("click", (event) => {
    if (event.target.id === "closeMetadataModal" || event.target.id === "closeMetadataModalButton") closeMetadataModal();
  });
  document.getElementById("applyMetadata").addEventListener("click", applyMetadata);
  elements.tagRenameModal.addEventListener("click", (event) => {
    if (event.target.id === "closeTagRenameModal" || event.target.id === "closeTagRenameModalButton") closeTagRenameModal();
  });
  elements.applyTagRename.addEventListener("click", applyTagRename);
  document.getElementById("gitModal").addEventListener("click", (event) => {
    if (event.target.id === "closeGitModal" || event.target.id === "closeGitModalButton") closeGitModal();
  });
  document.getElementById("refreshGit").addEventListener("click", refreshGit);
  for (const id of ["closeDeckModal", "closeDeckModalButton"]) {
    document.getElementById(id).addEventListener("click", closeDeckModal);
  }
  elements.documentDetails.addEventListener("click", event => {
    const link = event.target.closest("[data-deck-link]");
    if (link) openDeckModal(link.dataset.deckLink);
  });
  document.getElementById("deleteOpenDocument").addEventListener("click", () => {
    if (state.qmdPath) openFileAction("delete", state.qmdPath);
  });
  window.addEventListener("unhandledrejection", event => {
    setStatus(event.reason?.message || "Aktion fehlgeschlagen.", "error");
    event.preventDefault();
  });
  window.addEventListener("beforeunload", event => {
    if (!state.dirty && !state.savePromise) return;
    persistDraft();
    event.preventDefault();
    event.returnValue = "";
  });
  try {
    setIndexCollapsed(localStorage.getItem("material-ui:index-collapsed") === "true");
  } catch {
    setIndexCollapsed(false);
  }
  try {
    setFocusMode(localStorage.getItem("material-ui:focus-mode") === "true");
  } catch {
    setFocusMode(false);
  }
  try {
    setChatOpen(localStorage.getItem("material-ui:chat-open") === "true");
  } catch {
    setChatOpen(false);
  }
  bindIndexResizer();
  bindPreviewControls();
  elements.toggleIndex.addEventListener("click", () => {
    const collapsed = !elements.workspace.classList.contains("index-collapsed");
    setIndexCollapsed(collapsed);
    try {
      localStorage.setItem("material-ui:index-collapsed", String(collapsed));
    } catch {
      return;
    }
  });
  elements.toggleFocusMode.addEventListener("click", () => {
    setFocusModePersisted(!elements.workspace.classList.contains("focus-mode"));
  });
  elements.navigationFolder.addEventListener("change", () => {
    // Blur nach bereits ausgefuehrter Navigation: kein erneutes Rendern, sonst
    // wird der Ordnerliste der Klick unter dem Zeiger weggerendert.
    if (elements.navigationFolder.value.trim().replace(/^\/+|\/+$/g, "") === state.navigationFolder) return;
    navigateFolderInput();
  });
  elements.reloadIndex.addEventListener("click", async () => {
    elements.reloadIndex.disabled = true;
    try {
      setStatus("Ansicht wird aktualisiert …", "rendering");
      const view = views.view(state.navigationView);
      const data = state.navigationView === "folder"
        ? await reloadCurrentFolder()
        : await (view?.onRefresh || view?.onActivate)?.();
      if (!data?.warnings?.length) setStatus("Ansicht aktualisiert.", "ready");
    } catch (error) {
      setStatus(`Ansicht konnte nicht aktualisiert werden: ${error.message}`, "error");
    } finally {
      elements.reloadIndex.disabled = false;
    }
  });
  elements.navigationFolder.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      navigateFolderInput();
    }
  });
  let draggedFolder = null;
  const folderRow = event => event.target.closest('summary[data-folder][draggable="true"]');
  elements.folderEntries.addEventListener("dragstart", event => {
    const row = folderRow(event);
    if (!row || event.target.closest("button")) { event.preventDefault(); return; }
    draggedFolder = row.dataset.folder;
    event.dataTransfer.setData("application/x-material-folder", draggedFolder);
    event.dataTransfer.effectAllowed = "move";
  });
  const siblingDrop = event => {
    const row = folderRow(event);
    return row && draggedFolder && row.dataset.folder !== draggedFolder
      && row.dataset.folder.split("/").slice(0, -1).join("/") === draggedFolder.split("/").slice(0, -1).join("/") ? row : null;
  };
  elements.folderEntries.addEventListener("dragover", event => {
    if (siblingDrop(event)) { event.preventDefault(); event.dataTransfer.dropEffect = "move"; }
  });
  elements.folderEntries.addEventListener("drop", event => {
    const row = siblingDrop(event);
    if (!row) return;
    event.preventDefault();
    const siblings = [...row.closest("ul").children]
      .map(li => li.querySelector(':scope > details > summary[draggable="true"]')).filter(Boolean);
    openFileAction("reorder-folder", draggedFolder, siblings.indexOf(row) + 1);
    draggedFolder = null;
  });
  elements.folderEntries.addEventListener("dragend", () => { draggedFolder = null; });
  elements.folderEntries.addEventListener("click", (event) => {
    const unitFolder = event.target.closest("button[data-unit-folder]");
    if (unitFolder) {
      event.preventDefault();
      unitsView.attachFolder(unitFolder.dataset.unitFolder);
      return;
    }
    const renameFolder = event.target.closest("button[data-rename-folder]");
    if (renameFolder) {
      event.preventDefault();
      openFileAction("rename-folder", renameFolder.dataset.renameFolder);
      return;
    }
    const newInFolder = event.target.closest("button[data-new-in-folder]");
    if (newInFolder) {
      event.preventDefault();
      openNewDocModal(newInFolder.dataset.newInFolder);
      return;
    }
    const worksheetNote = event.target.closest("button[data-worksheet-note]");
    if (worksheetNote) {
      event.preventDefault();
      openWorksheetNote(worksheetNote.dataset.worksheetNote);
      return;
    }
    const summary = event.target.closest("summary[data-folder]");
    if (summary) {
      selectFolderRow(summary.dataset.folder);
      return;
    }
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.folder !== undefined) renderFolderNavigation(button.dataset.folder);
    if (button.dataset.document) selectDocument(button.dataset.document);
    if (button.dataset.rename !== undefined) openFileAction("rename", button.dataset.rename);
    if (button.dataset.delete !== undefined) openFileAction("delete", button.dataset.delete);
    if (button.dataset.present) openDeckModal(button.dataset.present);
  });
  elements.folderEntries.addEventListener("toggle", (event) => {
    const details = event.target;
    if (!(details instanceof HTMLDetailsElement) || details.dataset.folder === undefined || !details.open) return;
    const list = details.querySelector(":scope > ul");
    if (list) loadFolderChildren(details.dataset.folder, list);
  }, true);
  elements.tagYearFilter.addEventListener("change", () => {
    state.tagYearFilter = elements.tagYearFilter.value;
    saveTagYearFilterPreference(state.tagYearFilter);
    renderTagNavigation();
  });
  elements.tagEntries.addEventListener("contextmenu", (event) => {
    const target = event.target.closest("[data-tag]");
    if (!target) return;
    event.preventDefault();
    openTagRenameModal(target.dataset.tag);
  });
  bindArrowKeyListNavigation(elements.folderEntries);
  bindArrowKeyListNavigation(elements.tagEntries);
  bindArrowKeyListNavigation(elements.tagResults);
  elements.tagResults.addEventListener("click", event => {
    const button = event.target.closest("button[data-document]");
    if (button) selectDocument(button.dataset.document);
  });
  editor.initEditorExtensions();
  elements.autoRender.checked = state.autoRender;
  elements.autoSave.checked = state.autoSave;
  elements.autoSave.addEventListener("change", () => {
    state.autoSave = elements.autoSave.checked;
    saveAutoSavePreference(state.autoSave);
    if (state.autoSave) {
      setStatus("Auto-Speichern aktiv.", "ready");
      if (state.dirty) scheduleAutoUpdate();
    } else {
      if (state.saveTimer) {
        clearTimeout(state.saveTimer);
        state.saveTimer = null;
      }
      updateSaveIndicator();
      setStatus("Auto-Speichern aus. Änderungen bitte manuell speichern.", "ready");
    }
  });
  elements.showJobs.addEventListener("click", openJobsModal);
  elements.showSettings.addEventListener("click", openSettingsModal);
  elements.restartServer.addEventListener("click", restartServer);
  elements.refreshJobs.addEventListener("click", refreshJobs);
  elements.closeJobsModal.addEventListener("click", closeJobsModal);
  elements.closeJobsModalButton.addEventListener("click", closeJobsModal);
  const closeHelpModal = () => closeModal(elements.helpModal);
  elements.showHelp.addEventListener("click", () => openModal(elements.helpModal, elements.closeHelpModalButton));
  elements.closeHelpModal.addEventListener("click", closeHelpModal);
  elements.closeHelpModalButton.addEventListener("click", closeHelpModal);
  elements.showChat.addEventListener("click", () => {
    setChatOpenPersisted(!elements.workspace.classList.contains("chat-open"));
  });
  elements.closeChatDock.addEventListener("click", () => setChatOpenPersisted(false));
  elements.documentSearch.addEventListener("input", () => {
    search.setQuery(elements.documentSearch.value);
    if (state.navigationView === "tagTree") {
      elements.tagSearch.dispatchEvent(new Event("input"));
      closePicker();
      return;
    }
    renderDocumentResults(true);
    scheduleFulltextSearch();
    openPicker();
  });
  elements.documentSearch.addEventListener("focus", () => {
    if (state.navigationView !== "tagTree") openPicker();
  });
  elements.documentSearch.addEventListener("keydown", event => {
    if (state.navigationView !== "tagTree") handlePickerKeys(event);
  });
  elements.togglePicker.addEventListener("click", () => {
    if (state.navigationView === "tagTree") { elements.documentSearch.focus(); return; }
    if (elements.searchOverlay.hidden) openPicker();
    else closePicker();
  });
  elements.headerMenuToggle.addEventListener("click", () => {
    if (elements.headerMenuPanel.hidden) openHeaderMenu();
    else closeHeaderMenu();
  });
  elements.headerMenuPanel.addEventListener("click", (event) => {
    if (event.target.closest("button:not([data-theme-option])")) closeHeaderMenu();
  });
  elements.newMenuToggle.addEventListener("click", () => {
    if (elements.newMenuPanel.hidden) openNewMenu();
    else closeNewMenu();
  });
  elements.newMenuPanel.addEventListener("click", (event) => {
    if (event.target.closest("button")) closeNewMenu();
  });
  bindFacetChange(() => {
    renderDocumentResults(true);
    scheduleFulltextSearch();
    openPicker();
  });

  for (const button of [elements.reloadDoc, elements.reloadCourseActivity]) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        if (state.course.kursMode) {
          const activity = state.course.kursActivity;
          if (activity) await openKursActivity(activity.chapter, activity.id);
        } else if (await reloadCurrentDocument() && !state.qmdPath.toLowerCase().endsWith(".md")) {
          clearScheduledRender();
          await renderDocument();
        }
      } catch (error) {
        setStatus(`Neu laden fehlgeschlagen: ${error.message}`, "error");
      } finally {
        button.disabled = button === elements.reloadCourseActivity && !state.course.kursActivity;
      }
    });
  }
  elements.saveDoc.addEventListener("click", async () => {
    try {
      await flushPendingSave();
      await saveDocument();
      flashDocSaveFeedback("ok", "Gespeichert");
    } catch (error) {
      flashDocSaveFeedback("error", "Speichern fehlgeschlagen");
      setStatus(`Speichern fehlgeschlagen: ${error.message}`, "error");
    }
  });
  elements.renderDoc.addEventListener("click", reloadAndRenderDocument);
  document.getElementById("openPdfTab").addEventListener("click", () => {
    const source = elements.pdfPreview.getAttribute("src");
    if (!source) {
      setStatus("Noch kein PDF vorhanden.", "ready");
      return;
    }
    const url = new URL(source, window.location.href);
    url.hash = "";
    window.open(url.href, "_blank", "noopener");
  });
  document.getElementById("printPdf").addEventListener("click", printCurrentPdf);
  elements.slidesPlay.addEventListener("click", playSlides);
  elements.autoRender.addEventListener("change", () => {
    state.autoRender = elements.autoRender.checked;
    saveAutoRenderPreference(state.autoRender);
    if (state.autoRender) {
      setStatus("Auto-Render aktiv.", "ready");
      if (state.qmdPath && !state.dirty) scheduleRender();
    } else {
      clearScheduledRender();
      setStatus("Auto-Render aus. Rendern manuell starten.", "ready");
    }
  });
  elements.closeRenderPanel.addEventListener("click", hideRenderPanel);
  elements.showRenderPanel.addEventListener("click", reopenRenderPanel);
  elements.renderStatus.addEventListener("click", reopenRenderPanel);
  elements.renderLog.addEventListener("click", (event) => {
    const reference = event.target.closest(".log-line-ref");
    if (reference) jumpToLogLine(Number(reference.dataset.line));
  });
  elements.renderLog.addEventListener("keydown", (event) => {
    const reference = event.target.closest?.(".log-line-ref");
    if (!reference || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    jumpToLogLine(Number(reference.dataset.line));
  });
  elements.kursAuditBtn.addEventListener("click", startKursAudit);
  elements.kursPreviewBtn.addEventListener("click", () => startKursPreview());
  elements.kursChapterList.addEventListener("click", (event) => {
    const activity = event.target.closest("button[data-activity]");
    if (activity) openKursActivity(activity.dataset.chapter, activity.dataset.activity);
  });
  elements.saveCourseActivity.addEventListener("click", saveAndRefreshCourseActivity);
  elements.courseShortcutsHelp.addEventListener("click", openShortcutsModal);
  elements.kursPreviewStopBtn.addEventListener("click", stopKursPreview);
  elements.moodleVerifyBtn.addEventListener("click", () => startKursMoodleJob("verify"));
  elements.moodleUploadChapterBtn.addEventListener("click", () => {
    const chapter = elements.moodleChapterSelect.value;
    if (!chapter) return;
    openMoodleConfirm("upload-chapter", { chapter });
  });
  elements.moodleUploadCourseBtn.addEventListener("click", () => openMoodleConfirm("upload-course"));
  elements.moodlePublishBtn.addEventListener("click", () => openMoodleConfirm("publish"));
  elements.closeMoodleConfirmModal.addEventListener("click", closeMoodleConfirmModal);
  elements.closeMoodleConfirmModalButton.addEventListener("click", closeMoodleConfirmModal);
  elements.moodleConfirmCancelBtn.addEventListener("click", closeMoodleConfirmModal);
  elements.newDoc.addEventListener("click", () => openNewDocModal());
  document.getElementById("officeImportBtn").addEventListener("click", () => pluginControllers.officeImport?.openOfficeImportModal());
  elements.newDocInFolder.addEventListener("click", () => openNewDocModal(state.navigationFolder || "."));
  elements.addImage.addEventListener("click", () => openImageModal());
  elements.changeTemplate.addEventListener("click", openTemplateModal);
  elements.editMetadata.addEventListener("click", openMetadataModal);
  function positionDocumentMenu(menu) {
    const panel = menu.querySelector(":scope > .document-settings-panel");
    if (!panel) return;
    panel.style.setProperty("--menu-offset-x", "0px");
    const bounds = panel.getBoundingClientRect();
    const left = Math.max(8, Math.min(bounds.left, document.documentElement.clientWidth - bounds.width - 8));
    panel.style.setProperty("--menu-offset-x", `${left - bounds.left}px`);
    panel.style.setProperty("--menu-max-height", `${Math.max(0, window.innerHeight - bounds.top - 8)}px`);
  }
  window.addEventListener("resize", () => {
    document.querySelectorAll(".document-settings[open], .discussion-menu[open]").forEach(positionDocumentMenu);
  });
  document.addEventListener("toggle", event => {
    const menu = event.target;
    if (!menu.matches?.(".document-settings[open], .discussion-menu[open]")) return;
    positionDocumentMenu(menu);
    document.querySelectorAll(".document-settings[open], .discussion-menu[open]").forEach(other => {
      if (other !== menu) other.open = false;
    });
  }, true);
  document.querySelector(".document-settings").addEventListener("click", event => {
    if (event.target.closest("button, a")) {
      event.currentTarget.querySelector(":scope > summary").focus();
      event.currentTarget.open = false;
    }
  });
  elements.showGit.addEventListener("click", openGitModal);
  elements.shortcutsHelp.addEventListener("click", openShortcutsModal);
  elements.closeShortcutsModal.addEventListener("click", closeShortcutsModal);
  elements.closeShortcutsModalButton.addEventListener("click", closeShortcutsModal);
  elements.shortcutsSearch.addEventListener("input", renderShortcutsList);
  elements.checkDoc.addEventListener("click", checkDocument);
  elements.closeImageModal.addEventListener("click", closeImageModal);
  elements.closeImageModalButton.addEventListener("click", closeImageModal);
  elements.closeTemplateModal.addEventListener("click", closeTemplateModal);
  elements.closeTemplateModalButton.addEventListener("click", closeTemplateModal);
  elements.closeNewDocModal.addEventListener("click", closeNewDocModal);
  elements.closeNewDocModalButton.addEventListener("click", closeNewDocModal);
  elements.cancelNewDoc.addEventListener("click", closeNewDocModal);
  elements.applyTemplate.addEventListener("click", applySelectedTemplate);
  elements.removeTemplate.addEventListener("click", removeTemplate);
  elements.createNewDoc.addEventListener("click", createNewDocument);
  elements.templateSelect.addEventListener("change", () => renderTemplatePreview(elements.templateSelect, elements.templatePreview));
  elements.templateType.addEventListener("change", () => selectTemplateType());
  elements.newTemplate.addEventListener("change", () => renderTemplatePreview(elements.newTemplate, elements.newTemplatePreview));
  elements.newKind.addEventListener("change", applyTemplateSuggestion);
  elements.newTitle.addEventListener("input", updateNewDocPathPreview);
  elements.newTopic.addEventListener("input", updateNewDocPathPreview);
  elements.newSubject.addEventListener("input", updateNewDocPathPreview);
  elements.newGrade.addEventListener("input", updateNewDocPathPreview);
  elements.newFilename.addEventListener("input", updateNewDocPathPreview);
  elements.newMini.addEventListener("change", updateNewDocPathPreview);
  elements.newKursSlug.addEventListener("input", updateNewDocPathPreview);
  elements.importAsset.addEventListener("click", importAsset);

  elements.drop.addEventListener("click", () => {
    elements.imageFileInput.click();
  });
  elements.imageFileInput.addEventListener("change", async () => {
    const file = elements.imageFileInput.files?.[0];
    if (file) await loadFile(file);
    elements.imageFileInput.value = "";
  });
  document.body.addEventListener("paste", async (event) => {
    const item = [...event.clipboardData.items].find((entry) => entry.type.startsWith("image/"));
    if (!item) return;
    if (!shouldHandleImagePaste(event.target)) return;
    event.preventDefault();
    const file = item.getAsFile();
    const choice = pluginControllers.taskImageImport ? await pluginControllers.taskImageImport.askPasteChoice() : "bild";
    if (choice === "bild") {
      openImageModal();
      await loadFile(file);
    } else if (choice === "code") {
      await pluginControllers.taskImageImport?.openTaskImageModal(file);
    }
  });
  const click = (id) => () => document.getElementById(id)?.click();
  const view = (name) => () => document.querySelector(`[data-workspace-view="${name}"]`)?.click();
  const theme = (name) => () => document.querySelector(`[data-theme-option="${name}"]`)?.click();
  const hasDocument = () => Boolean(state.qmdPath);
  registerCommands([
    { id: "new", label: "Neues Material anlegen", icon: "plus", keywords: "neu erstellen dokument arbeitsblatt", run: click("newDoc") },
    { id: "import", label: "Arbeitsblatt importieren", icon: "upload", keywords: "pdf docx office", available: () => !document.getElementById("officeImportBtn").hidden, run: click("officeImportBtn") },
    { id: "save", label: "Speichern", hint: "Strg+S", icon: "save", available: hasDocument, run: click("saveDoc") },
    { id: "render", label: "Rendern", hint: "Strg+Enter", icon: "play", keywords: "pdf bauen", available: hasDocument, run: click("renderDoc") },
    { id: "template", label: "Template ändern", icon: "template", keywords: "vorlage", available: hasDocument, run: click("changeTemplate") },
    { id: "history", label: "Versionen anzeigen", icon: "history", keywords: "verlauf", available: hasDocument, run: click("showHistory") },
    { id: "view-edit", label: "Ansicht: Nur Editor", keywords: "bearbeiten darstellung", run: view("edit") },
    { id: "view-split", label: "Ansicht: Editor und Vorschau", keywords: "geteilt darstellung", run: view("split") },
    { id: "view-preview", label: "Ansicht: Nur Vorschau", keywords: "darstellung pdf", run: view("preview") },
    { id: "focus", label: "Fokus-Modus umschalten", keywords: "seitenleiste", run: click("toggleFocusMode") },
    { id: "index", label: "Index ein- oder ausklappen", keywords: "seitenleiste navigation", run: click("toggleIndex") },
    { id: "chat", label: "Chat umschalten", icon: "chat", keywords: "wissensbasis", available: () => !document.getElementById("showChat").hidden, run: click("showChat") },
    { id: "theme-light", label: "Farbschema: Hell", icon: "sun", keywords: "design", run: theme("light") },
    { id: "theme-dark", label: "Farbschema: Dunkel", icon: "moon", keywords: "design", run: theme("dark") },
    { id: "theme-system", label: "Farbschema: System", icon: "monitor", keywords: "design", run: theme("system") },
    { id: "settings", label: "Einstellungen und Marketplace", icon: "settings", run: click("showSettings") },
    { id: "jobs", label: "Aufträge anzeigen", icon: "history", keywords: "hintergrund", run: click("showJobs") },
    { id: "help", label: "Hilfe und Tastenkürzel", icon: "help", run: click("showHelp") }
  ]);
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      focusSearch();
    }
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".document-picker")) closePicker();
    if (!event.target.closest(".header-menu")) closeHeaderMenu();
    if (!event.target.closest(".new-menu")) closeNewMenu();
  });
  // Klicks in iframes (PDF-Vorschau, Deck-Editor) erreichen das Document nicht
  // und loesen daher keinen click-Event aus: beim Fokusverlust des Fensters schliessen.
  window.addEventListener("blur", () => {
    closePicker();
    closeHeaderMenu();
    closeNewMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (document.getElementById("recoveryModal").classList.contains("open")) closeModal(document.getElementById("recoveryModal"));
      else if (document.getElementById("qmdImportModal").classList.contains("open")) cancelQmdImport();
      else if (document.getElementById("officeImportModal").classList.contains("open")) pluginControllers.officeImport?.cancelOfficeImport();
      else if (document.getElementById("taskImageImportModal").classList.contains("open")) pluginControllers.taskImageImport?.cancelTaskImageImport();
      else if (document.getElementById("imagePasteChoiceModal").classList.contains("open")) document.getElementById("imagePasteChoiceClose").click();
      else if (document.getElementById("fileActionModal").classList.contains("open")) closeFileActionModal();
      else if (document.getElementById("metadataModal").classList.contains("open")) closeMetadataModal();
      else if (elements.tagRenameModal.classList.contains("open")) closeTagRenameModal();
      else if (document.getElementById("gitModal").classList.contains("open")) closeGitModal();
      else if (elements.imageModal.classList.contains("open")) closeImageModal();
      else if (elements.templateModal.classList.contains("open")) closeTemplateModal();
      else if (elements.shortcutsModal.classList.contains("open")) closeShortcutsModal();
      else if (elements.newDocModal.classList.contains("open")) closeNewDocModal();
      else if (elements.moodleConfirmModal.classList.contains("open")) closeMoodleConfirmModal();
      else if (elements.deckModal.classList.contains("open")) event.preventDefault(); // Esc verlaesst die Folienansicht nie; Schliessen nur ueber den Schliessen-Knopf
      else if (elements.jobsModal.classList.contains("open")) closeJobsModal();
      else if (elements.settingsModal.classList.contains("open")) closeSettingsModal();
      else if (elements.helpModal.classList.contains("open")) closeHelpModal();
      else if (document.querySelector(".document-settings[open], .discussion-menu[open]")) {
        const menu = document.activeElement?.closest(".document-settings[open], .discussion-menu[open]")
          || document.querySelector(".document-settings[open], .discussion-menu[open]");
        event.preventDefault();
        menu.open = false;
        menu.querySelector(":scope > summary").focus();
      }
      else if (!elements.headerMenuPanel.hidden) closeHeaderMenu();
      else if (!elements.newMenuPanel.hidden) closeNewMenu();
      else if (elements.workspace.classList.contains("focus-mode")) setFocusModePersisted(false);
      else if (elements.workspace.classList.contains("chat-open")) setChatOpenPersisted(false);
      else if (!elements.searchOverlay.hidden) {
        // event.target ist bei gefuelltem Suchfeld ein <input type="search">: ohne
        // preventDefault loescht der Browser den Wert, das ausgeloeste input-Event
        // ruft openPicker() auf und macht das Schliessen sofort wieder rueckgaengig.
        event.preventDefault();
        closePicker();
      }
    }
    trapModalFocus(event);
  });

  elements.drop.addEventListener("dragover", (event) => {
    event.preventDefault();
    elements.drop.classList.add("active");
  });
  elements.drop.addEventListener("dragleave", () => elements.drop.classList.remove("active"));
  elements.drop.addEventListener("drop", async (event) => {
    event.preventDefault();
    elements.drop.classList.remove("active");
    const file = [...event.dataTransfer.files].find((entry) => entry.type.startsWith("image/"));
    if (file) await loadFile(file);
  });

  elements.grayscale.addEventListener("change", redraw);
  elements.removeGreen.addEventListener("change", redraw);
  elements.resetCrop.addEventListener("click", () => {
    resetCropBox();
    redraw();
  });
  elements.undoWhiteout.addEventListener("click", () => {
    state.image.whiteouts.pop();
    redraw();
  });
  elements.fitImage.addEventListener("click", fitImage);
  elements.actualSize.addEventListener("click", () => setImageZoom(1));
  elements.imageZoom.addEventListener("input", () => setImageZoom(Number(elements.imageZoom.value) / 100));

  elements.canvas.addEventListener("pointerdown", (event) => {
    if (!state.image.originalImage) return;
    event.preventDefault();
    elements.canvas.setPointerCapture(event.pointerId);
    state.image.dragStart = canvasPoint(event);
    state.image.dragCurrent = state.image.dragStart;
    redraw();
  });
  elements.canvas.addEventListener("pointermove", (event) => {
    if (!state.image.dragStart) return;
    state.image.dragCurrent = canvasPoint(event);
    redraw();
  });
  elements.canvas.addEventListener("pointerup", finishDrag);
  elements.canvas.addEventListener("pointercancel", finishDrag);
}


function openHeaderMenu() {
  closeNewMenu();
  elements.headerMenuPanel.hidden = false;
  elements.headerMenuToggle.setAttribute("aria-expanded", "true");
}

function closeHeaderMenu() {
  elements.headerMenuPanel.hidden = true;
  elements.headerMenuToggle.setAttribute("aria-expanded", "false");
}

function openNewMenu() {
  closeHeaderMenu();
  elements.newMenuPanel.hidden = false;
  elements.newMenuToggle.setAttribute("aria-expanded", "true");
}

function closeNewMenu() {
  elements.newMenuPanel.hidden = true;
  elements.newMenuToggle.setAttribute("aria-expanded", "false");
}

async function restartServer(options) {
  if (options?.confirmed !== true && !window.confirm("Material-UI-Server jetzt neu starten? Die Seite lädt danach neu; ungespeicherte Änderungen gehen verloren.")) return;
  let previousPid = null;
  try {
    previousPid = (await api("/api/desktop-status")).pid || null;
  } catch {
    previousPid = null;
  }
  setStatus("Server wird neu gestartet …", "rendering");
  try {
    await api("/api/server/restart", { method: "POST", timeout: 8000 });
  } catch {
    // Erwartbar: Der Server kann während des Neustarts nicht mehr antworten.
  }
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      const status = await api("/api/desktop-status", { timeout: 3000 });
      if (status.pid && status.pid !== previousPid) {
        window.location.reload();
        return;
      }
    } catch {
      // Server noch nicht wieder da: weiter warten.
    }
  }
  setStatus("Server-Neustart wurde nicht fertig. Bitte Seite neu laden.", "error");
}

function applyQmds(data) {
  state.repositoryRoot = data.root || state.repositoryRoot;
  const warnings = document.getElementById("indexWarnings");
  warnings.hidden = !data.warnings?.length;
  warnings.textContent = (data.warnings || []).map(item => `${item.path}: ${item.message}`).join("\n");
  state.qmds = (data.qmds || [])
    .filter((entry) => entry.area !== "wissen")
    .sort((a, b) => b.mtime - a.mtime);
  state.rootTags = data.rootTags || state.rootTags;
  state.tagParents = data.tagParents || state.tagParents;
  state.folderCache.clear();
  state.folderTreeLoaded = false;
  renderFilterChips();
  renderFacetFilters();
  if (state.navigationView === "tagTree") renderTagNavigation();
  else renderFolderNavigation();
  renderDocumentResults(false);
}


async function loadQmds() {
  // Nach einem Serverneustart ist der Index kalt und wird serverseitig im Hintergrund
  // vorgewarmt; der erste Aufruf kann daher laenger als die ueblichen 15 s dauern.
  setStatus("Index wird aufgebaut …", "rendering");
  let data;
  try {
    data = await api("/api/qmds", { timeout: 120000 });
  } catch (error) {
    if (!error.retryable) throw error;
    await new Promise((resolve) => setTimeout(resolve, 3000));
    data = await api("/api/qmds", { timeout: 120000 });
  }
  applyQmds(data);
  setStatus("Bereit.", "ready");
  if (new URLSearchParams(window.location.search).has("import")) return;
  restoreTabs(loadTabs().filter((path) => state.qmds.some((entry) => entry.path === path) || courseEntryForPath(path)));
  const requestedPath = new URLSearchParams(window.location.search).get("path");
  if (requestedPath) {
    await selectDocument(requestedPath);
    return;
  }
  const lastPath = loadLastDocumentPreference();
  const last = lastPath && state.qmds.find((entry) => entry.path === lastPath);
  const first = last || state.qmds.find((entry) => entry.path.includes("/arbeitsblaetter/")) || state.qmds[0];
  if (first) {
    await selectDocument(first.path);
  }
}

async function checkDocument() {
  await diagnostics.check({ explicit: true });
}

function openImageModal() {
  openModal(elements.imageModal, elements.drop);
}

function closeImageModal() {
  closeModal(elements.imageModal);
}

function openDeckModal(path, frame = "", worksheet = "") {
  if (!path) return;
  const url = `/present/?path=${encodeURIComponent(path)}${frame ? `&frame=${encodeURIComponent(frame)}` : ""}${worksheet ? `&worksheet=${encodeURIComponent(worksheet)}` : ""}`;
  elements.deckFrame.src = url;
  elements.deckModalNewTab.href = url;
  elements.deckModalNewTab.textContent = "In neuem Tab öffnen";
  openModal(elements.deckModal, elements.deckModalNewTab);
}

function closeDeckModal() {
  // iframe entladen: beendet Revisionsabgleich und beforeunload-Wächter der Present-App.
  elements.deckFrame.src = "about:blank";
  closeModal(elements.deckModal);
}

// Druckt das aktuelle PDF über einen unsichtbaren Frame (Druckdialog des Browsers).
// Meldet den Start als `material:print-started`, damit Plugins (z. B. ein Druckverlauf)
// mitlesen können, ohne dass der Kern sie kennt.
async function printCurrentPdf() {
  const source = elements.pdfPreview.getAttribute("src");
  if (!source) {
    setStatus("Noch kein PDF vorhanden.", "ready");
    return;
  }
  const url = new URL(source, window.location.href);
  url.hash = "";
  let objectUrl = "";
  try {
    const response = await fetch(url.href, { credentials: "same-origin" });
    if (!response.ok) throw new Error(`PDF nicht ladbar (${response.status})`);
    objectUrl = URL.createObjectURL(await response.blob());
    const frame = document.createElement("iframe");
    frame.className = "visually-hidden";
    frame.setAttribute("aria-hidden", "true");
    frame.src = objectUrl;
    await new Promise((resolve, reject) => {
      frame.onload = resolve;
      frame.onerror = () => reject(new Error("PDF konnte nicht geladen werden"));
      document.body.append(frame);
    });
    const cleanup = () => { frame.remove(); URL.revokeObjectURL(objectUrl); };
    frame.contentWindow.addEventListener("afterprint", cleanup, { once: true });
    setTimeout(cleanup, 10 * 60 * 1000);
    document.dispatchEvent(new CustomEvent("material:print-started", {
      detail: { path: state.qmdPath || "", pdf: url.searchParams.get("path") || "", at: Date.now() },
    }));
    frame.contentWindow.focus();
    frame.contentWindow.print();
  } catch (error) {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    setStatus(`Drucken fehlgeschlagen: ${error.message}`, "error");
    window.open(url.href, "_blank", "noopener");
  }
}

function setStatus(message, mode = "ready") {
  // Nur ein Icon anzeigen; die Meldung bleibt als Tooltip und Screenreader-Text erhalten.
  elements.renderStatus.innerHTML = `${uiIcon("log")}<span class="visually-hidden">${escapeHtml(message)}</span>`;
  elements.renderStatus.title = `${message} – Render-Ausgabe anzeigen`;
  elements.renderStatus.className = `status-badge ${mode}`;
}

function updateSaveIndicator() {
  const pending = state.dirty || Boolean(state.saveTimer) || Boolean(state.savePromise);
  elements.saveDoc.toggleAttribute("data-dirty", pending && !state.course.kursMode);
  elements.saveCourseActivity.toggleAttribute("data-dirty", pending && state.course.kursMode);
}

function shouldHandleImagePaste(target) {
  if (elements.imageModal.classList.contains("open")) return true;
  if (target.closest?.("#templateModal")) return false;
  if (target.closest?.("#newDocModal")) return false;
  if (target.matches?.("input, textarea, select")) return false;
  return Boolean(target.closest?.(".editor-shell, .editor-pane"));
}


// AB-Notiz anlegen (falls noch keine) und im Notiz-Editor oeffnen; die Einheiten-
// und Ordneransicht zeigen die Notiz danach gepaart unter dem AB wie eine Loesung.
async function openWorksheetNote(path) {
  try {
    const data = await api("/api/document/note", { method: "POST", body: JSON.stringify({ path }) });
    applyQmds(data);
    await unitsView.refresh();
    await selectDocument(data.path);
    setStatus(data.created ? `Notiz angelegt: ${data.path}` : `Notiz geöffnet: ${data.path}`, "ok");
  } catch (error) {
    setStatus(`Notiz fehlgeschlagen: ${error.message}`, "error");
  }
}

export { state, pollRender, renderDocument, scheduleRender, selectDocument, loadDocument, saveDocument, importAsset, openWorksheetNote };

createWorksheetTools({ state, api, openDeckModal, setStatus, flushPendingSave, openWorksheetNote, selectDocument });
