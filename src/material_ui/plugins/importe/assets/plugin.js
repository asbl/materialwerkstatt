// Importe-Plugin (Frontend): Office-Import- und Aufgabenbild-Modal (HTML-Slots im
// Kern-Template) mit ihren Controllern verdrahten und beim Kern registrieren.

import { createOfficeImportController } from "./office-import.js";
import { createTaskImageImportController } from "./task-image-import.js";

export function register(ctx) {
  const deps = ctx.deps || {};
  const taskImageDeps = deps.taskImage || {};
  const office = createOfficeImportController({
    api: ctx.api,
    openModal: deps.openModal,
    closeModal: deps.closeModal,
    applyQmds: deps.applyQmds,
    loadDocument: deps.loadDocument,
    confirmDiscardOrSave: deps.confirmDiscardOrSave,
    setStatus: deps.setStatus,
  });
  const taskImage = createTaskImageImportController({
    state: taskImageDeps.state,
    api: ctx.api,
    openModal: deps.openModal,
    closeModal: deps.closeModal,
    setStatus: deps.setStatus,
    getEditorText: taskImageDeps.getEditorText,
    setEditorText: taskImageDeps.setEditorText,
    flushPendingSave: deps.flushPendingSave,
  });
  deps.registerController?.("officeImport", office);
  deps.registerController?.("taskImageImport", taskImage);

  const byId = (id) => document.getElementById(id);
  byId("officeImportFile")?.addEventListener("change", office.handleFileSelected);
  byId("officeImportForm")?.addEventListener("submit", office.confirmOfficeImport);
  byId("officeImportDraftBtn")?.addEventListener("click", office.requestAiDraft);
  for (const id of ["officeImportClose", "officeImportBackdrop"]) {
    byId(id)?.addEventListener("click", office.cancelOfficeImport);
  }
  byId("taskImageChatForm")?.addEventListener("submit", taskImage.sendCorrection);
  byId("taskImageRenderBtn")?.addEventListener("click", taskImage.refreshPreview);
  byId("taskImageCommitBtn")?.addEventListener("click", taskImage.commitTaskImageImport);
  for (const id of ["taskImageCancelBtn", "taskImageImportClose", "taskImageImportBackdrop"]) {
    byId(id)?.addEventListener("click", taskImage.cancelTaskImageImport);
  }
}
