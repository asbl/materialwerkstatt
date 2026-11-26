export function createQmdImportController({ state, elements, api, openModal, closeModal, updateDocumentUrl, applyQmds, loadDocument, confirmDiscardOrSave, setStatus }) {
  let qmdImportToken = "";
  let qmdImportBusy = false;

  async function openQmdImport(token) {
    const modal = document.getElementById("qmdImportModal");
    const target = document.getElementById("qmdImportTarget");
    qmdImportToken = token;
    openModal(modal, target);
    try {
      const data = await api(`/api/qmd-import/${encodeURIComponent(token)}`);
      document.getElementById("qmdImportSource").textContent = `Quelle: ${data.source}`;
      target.value = `unterricht/importiert/${data.name}`;
      document.getElementById("qmdImportStatus").textContent = "Zielpfad wählen und Import bestätigen.";
    } catch (error) {
      document.getElementById("qmdImportStatus").textContent = error.message;
      document.getElementById("qmdImportSubmit").disabled = true;
    }
  }

  async function cancelQmdImport() {
    if (qmdImportBusy) return;
    try {
      if (qmdImportToken) await api(`/api/qmd-import/${encodeURIComponent(qmdImportToken)}`, { method: "DELETE" });
    } finally {
      qmdImportToken = "";
      closeModal(document.getElementById("qmdImportModal"));
      updateDocumentUrl(state.qmdPath);
    }
  }

  async function confirmQmdImport(event) {
    event.preventDefault();
    const submit = document.getElementById("qmdImportSubmit");
    if (submit.disabled || !qmdImportToken) return;
    qmdImportBusy = true;
    submit.disabled = true;
    try {
      if (!(await confirmDiscardOrSave())) return;
      const data = await api(`/api/qmd-import/${encodeURIComponent(qmdImportToken)}`, {
        method: "POST",
        body: JSON.stringify({ path: document.getElementById("qmdImportTarget").value })
      });
      applyQmds(data);
      qmdImportToken = "";
      closeModal(document.getElementById("qmdImportModal"));
      await loadDocument(data.path);
    } catch (error) {
      document.getElementById("qmdImportStatus").textContent = `Import fehlgeschlagen: ${error.message}`;
      setStatus(`Import fehlgeschlagen: ${error.message}`, "error");
    } finally {
      qmdImportBusy = false;
      submit.disabled = false;
    }
  }

  return { openQmdImport, cancelQmdImport, confirmQmdImport };
}
