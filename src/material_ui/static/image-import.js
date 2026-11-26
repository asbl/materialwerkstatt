import { slug } from "./ui-utils.js";

const MAX_IMPORT_BYTES = 24 * 1024 * 1024;

export function createImageImportController({ state, elements, api, editor, flushPendingSave,
  canvasToBlob, dataUrlToBlob, edits, showPdf, setStatus, clearImageState, closeImageModal, scheduleRender }) {
  async function importAsset() {
    if (!state.image.originalImage) return;
    await flushPendingSave();
    const session = state.session;
    const path = state.qmdPath;
    const revision = state.revision;
    const insert = elements.insert.checked;
    const cleanBlob = await canvasToBlob(elements.canvas);
    const originalBlob = await dataUrlToBlob(state.image.originalDataUrl);
    if (cleanBlob.size + originalBlob.size > MAX_IMPORT_BYTES * 2) {
      setStatus("Bildimport ist zu groß. Bitte kleineren Ausschnitt verwenden.", "error");
      return;
    }
    const metadata = {
        qmdPath: path,
        revision,
        filename: elements.filename.value,
        width: elements.width.value,
        alt: elements.alt.value,
        source: elements.source.value,
        page: elements.page.value,
        kind: elements.kind.value,
        description: elements.description.value,
        klasse: elements.klasse.value,
        thema: elements.thema.value,
        tags: elements.tags.value,
        insert: false,
        taskBlock: elements.taskBlock.checked,
        edits: edits()
    };
    const formData = new FormData();
    formData.append("metadata", JSON.stringify(metadata));
    formData.append("original", originalBlob, `${slug(elements.filename.value || "material")}-original.png`);
    formData.append("clean", cleanBlob, `${slug(elements.filename.value || "material")}-clean.png`);
    const data = await api("/api/import", {
      method: "POST",
      body: formData
    });
    if (session !== state.session) return;
    if (insert) {
      const text = editor.getEditorText();
      const marker = "<!-- material-ui -->";
      editor.setEditorText(text.includes(marker)
        ? text.replace(marker, `${data.markdown.trimEnd()}\n\n${marker}`)
        : `${text.trimEnd()}\n${data.markdown}`);
      state.dirty = true;
      await flushPendingSave();
      // Dokumentwechsel während des abschließenden Speicherns: keine Import-Aktionen für die alte Quelle.
      if (session !== state.session) return;
    }
    showPdf(data.pdf);
    setStatus(`Importiert: ${data.assetPath}`, "ok");
    clearImageState();
    closeImageModal();
    scheduleRender();
  }

  return { importAsset };
}
