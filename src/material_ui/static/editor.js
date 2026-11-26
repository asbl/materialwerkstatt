// Adapter zwischen der Anwendung und dem CodeMirror-6-Editor-Bundle
// (`static/editor.bundle.js`, gebaut aus `src/editor-app/`). Der Adapter hält
// die Anwendungsschnittstelle stabil: Text lesen/schreiben, Speichern und
// Rendern auslösen, Status pflegen. Faltung, Hervorhebung, Autovervoll-
//ständigung, Suche/Ersetzen und Undo liegen im Bundle.
export function resolveSaveAction(kursMode) {
  return kursMode ? "course" : "document";
}

export function createEditorController({
  state, elements, scheduleAutoUpdate,
  flushPendingSave, saveDocument, saveCourseActivity, setStatus, renderDocument,
  shortcuts, normalizeSearch, onSelectionChange = () => {}, onDocumentChange = () => {}, onShortcut,
  checkExternalChanges = async () => {}
}) {
  let editor = null;

  function checkOnFocus() {
    return checkExternalChanges().catch(error => setStatus(`Dateistand konnte nicht geprüft werden: ${error.message}`, "error"));
  }

  function initEditorExtensions() {
    if (!window.MaterialEditor) {
      setStatus("Editor-Bundle fehlt. Bitte `npm run build` in src/editor-app ausführen und neu laden.", "error");
      return;
    }
    editor = window.MaterialEditor.create(elements.editorHost, {
      shortcuts: shortcuts || [],
      onShortcut,
      onFocus: checkOnFocus,
      normalizeSearch: normalizeSearch || ((value) => value.toLowerCase()),
      onInput: () => { scheduleAutoUpdate(); onDocumentChange(); document.dispatchEvent(new Event("material-document-edited")); },
      onStats: renderEditorStatus,
      onSave: handleSaveRequest,
      onRender: () => renderDocument().catch((error) => setStatus(`Render-Start fehlgeschlagen: ${error.message}`, "error"))
    });
    // Test- und Debugzugriff für Playwright-Prüfungen und Support.
    window.materialEditor = { getText: getEditorText, setText: setEditorText };
    window.addEventListener("focus", () => {
      if (elements.editorHost.contains(document.activeElement)) checkOnFocus();
    });
  }

  function handleSaveRequest() {
    if (resolveSaveAction(state.course.kursMode) === "course") {
      saveCourseActivity().catch((error) => setStatus(`Speichern fehlgeschlagen: ${error.message}`, "error"));
    } else {
      flushPendingSave().then(saveDocument).catch((error) => setStatus(`Speichern fehlgeschlagen: ${error.message}`, "error"));
    }
  }

  function renderEditorStatus(stats) {
    const parts = [
      `${stats.lines} Zeilen`,
      `${stats.words.toLocaleString("de-DE")} Wörter`,
      `${stats.chars.toLocaleString("de-DE")} Zeichen`
    ];
    if (stats.selection > 0) parts.push(`${stats.selection.toLocaleString("de-DE")} markiert`);
    parts.push("Enter klappt Kommando auf", "Tab rückt ein", "Strg+S speichert", "Strg+F sucht");
    elements.editorStatus.textContent = parts.join(" · ");
    onSelectionChange();
  }

  function requireEditor() {
    if (!editor) throw new Error("Editor ist noch nicht bereit.");
    return editor;
  }

  function getEditorText() {
    return editor ? editor.getText() : "";
  }

  function setEditorText(text, options = {}) {
    if (!editor) return;
    const selection = options.preserveSelection ? { start: editor.getSelectionStart(), end: editor.getSelectionEnd() } : null;
    editor.setText(text, { documentKey: state.qmdPath, fold: options.keepExpanded ? false : options.fold });
    if (selection) editor.setSelectionRange(Math.min(selection.start, text.length), Math.min(selection.end, text.length));
    onDocumentChange();
  }

  return {
    initEditorExtensions,
    getEditorText,
    setEditorText,
    setDiagnostics: issues => editor?.setDiagnostics(issues),
    getSelection: () => editor ? { start: editor.getSelectionStart(), end: editor.getSelectionEnd() } : null,
    insertText: (value) => requireEditor().insertText(value),
    insertTemplate: (template) => requireEditor().insertTemplate(template),
    openSearch: () => requireEditor().openSearch(),
    focus: () => editor?.focus(),
    setReadOnly: (readOnly) => editor?.setReadOnly(readOnly),
    setAriaLabel: (label) => editor?.setAriaLabel(label),
    setSelectionRange: (start, end) => editor?.setSelectionRange(start, end),
    jumpToOffset: (offset, length) => requireEditor().jumpToOffset(offset, length),
    jumpToLine: (line) => requireEditor().jumpToLine(line),
    toggleFoldAtCursor: () => editor?.toggleFoldAtCursor()
  };
}
