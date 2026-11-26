import { consumeSseStream } from "../../../static/sse.js";

function csrfToken() {
  return document.querySelector('meta[name="material-token"]')?.content || "";
}

export function createOfficeImportController({ api, openModal, closeModal, applyQmds, loadDocument, confirmDiscardOrSave, setStatus }) {
  let token = "";
  let busy = false;
  let draftBusy = false;
  let providersLoaded = false;

  function modal() {
    return document.getElementById("officeImportModal");
  }

  function resetFields() {
    document.getElementById("officeImportFields").hidden = true;
    document.getElementById("officeImportDuplicate").hidden = true;
    document.getElementById("officeImportSubmit").disabled = true;
  }

  async function loadProviders() {
    if (providersLoaded) return;
    const select = document.getElementById("officeImportProvider");
    try {
      const data = await api("/api/chat/providers");
      select.replaceChildren(...(data.providers || []).map((provider) => {
        const option = document.createElement("option");
        option.value = provider.id;
        option.textContent = provider.available ? provider.id : `${provider.id} (nicht verfügbar)`;
        option.disabled = !provider.available;
        return option;
      }));
      const firstAvailable = (data.providers || []).find((provider) => provider.available);
      if (firstAvailable) select.value = firstAvailable.id;
      providersLoaded = true;
    } catch {
      /* KI-Umbau ist optional - ohne Provider-Liste bleibt nur die manuelle Bearbeitung der Vorschau */
    }
  }

  function openOfficeImportModal() {
    token = "";
    const fileInput = document.getElementById("officeImportFile");
    fileInput.value = "";
    resetFields();
    document.getElementById("officeImportStatus").textContent = "Datei wählen, um Metadaten vorzuschlagen.";
    openModal(modal(), fileInput);
    loadProviders();
  }

  function applySuggestion(data) {
    const suggested = data.suggested || {};
    document.getElementById("officeImportTitleField").value = suggested.title || "";
    document.getElementById("officeImportSubject").value = suggested.subject || "";
    document.getElementById("officeImportGrade").value = suggested.grade || "";
    document.getElementById("officeImportThema").value = suggested.thema || "";
    document.getElementById("officeImportKind").value = suggested.kind || "Arbeitsblatt";
    document.getElementById("officeImportTags").value = (suggested.tags || []).join(", ");
    document.getElementById("officeImportTargetField").value = data.projectTarget || "";
    document.getElementById("officeImportWissenField").value = data.wissenZiel || "";
    document.getElementById("officeImportPreview").value = data.preview || "";
    const duplicateEl = document.getElementById("officeImportDuplicate");
    if (data.duplicateOf) {
      duplicateEl.hidden = false;
      duplicateEl.textContent =
        `Hinweis: Diese Datei ist inhaltlich bereits unter wissen/${data.duplicateOf} erschlossen. ` +
        "Es wird trotzdem ein neues Arbeitsblatt angelegt, das auf diese Quelle verweist.";
    } else {
      duplicateEl.hidden = true;
    }
  }

  async function discardStaged() {
    if (!token) return;
    const discarding = token;
    token = "";
    try {
      await api(`/api/document/import/office/${encodeURIComponent(discarding)}`, { method: "DELETE" });
    } catch {
      /* bestmoeglich: ein abgelaufener Importauftrag raeumt sich selbst auf */
    }
  }

  async function handleFileSelected() {
    const fileInput = document.getElementById("officeImportFile");
    const file = fileInput.files?.[0];
    if (!file) return;
    await discardStaged();
    const status = document.getElementById("officeImportStatus");
    resetFields();
    status.textContent = "Datei wird hochgeladen und ausgewertet …";
    const formData = new FormData();
    formData.append("file", file, file.name);
    try {
      const data = await api("/api/document/import/office", { method: "POST", body: formData, timeout: 120000 });
      token = data.token;
      applySuggestion(data);
      status.textContent = `${data.pages} Seite(n) erkannt. Metadaten prüfen und Zielpfade bestätigen.`;
      document.getElementById("officeImportFields").hidden = false;
      document.getElementById("officeImportSubmit").disabled = false;
    } catch (error) {
      status.textContent = `Import fehlgeschlagen: ${error.message}`;
    }
  }

  function currentFields() {
    return {
      title: document.getElementById("officeImportTitleField").value,
      subject: document.getElementById("officeImportSubject").value,
      grade: document.getElementById("officeImportGrade").value,
      thema: document.getElementById("officeImportThema").value,
      kind: document.getElementById("officeImportKind").value
    };
  }

  async function requestAiDraft() {
    if (!token || draftBusy) return;
    const providerId = document.getElementById("officeImportProvider").value;
    if (!providerId) return;
    const button = document.getElementById("officeImportDraftBtn");
    const preview = document.getElementById("officeImportPreview");
    const status = document.getElementById("officeImportStatus");
    draftBusy = true;
    button.disabled = true;
    status.textContent = "KI baut den Entwurf um …";
    preview.value = "";
    let failure = "";
    try {
      const response = await fetch(`/api/document/import/office/${encodeURIComponent(token)}/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Material-Token": csrfToken() },
        body: JSON.stringify({ provider: providerId, fields: currentFields() })
      });
      await consumeSseStream(response, (event) => {
        if (event.type === "text" && event.text) preview.value += event.text;
        else if (event.type === "error") failure = event.message || "Unbekannter Fehler.";
      });
      status.textContent = failure
        ? `KI-Umbau fehlgeschlagen: ${failure}`
        : "KI-Entwurf übernommen. Vor dem Import prüfen und bei Bedarf anpassen.";
    } catch (error) {
      status.textContent = `KI-Umbau fehlgeschlagen: ${error.message}`;
    } finally {
      draftBusy = false;
      button.disabled = false;
    }
  }

  async function cancelOfficeImport() {
    if (busy) return;
    await discardStaged();
    closeModal(modal());
  }

  async function confirmOfficeImport(event) {
    event.preventDefault();
    const submit = document.getElementById("officeImportSubmit");
    if (submit.disabled || !token || busy) return;
    busy = true;
    submit.disabled = true;
    const status = document.getElementById("officeImportStatus");
    try {
      if (!(await confirmDiscardOrSave())) return;
      const fields = {
        ...currentFields(),
        tags: document.getElementById("officeImportTags").value.split(",").map((item) => item.trim()).filter(Boolean)
      };
      const data = await api(`/api/document/import/office/${encodeURIComponent(token)}`, {
        method: "POST",
        body: JSON.stringify({
          projectTarget: document.getElementById("officeImportTargetField").value,
          wissenZiel: document.getElementById("officeImportWissenField").value,
          fields,
          body: document.getElementById("officeImportPreview").value
        })
      });
      applyQmds(data);
      token = "";
      closeModal(modal());
      await loadDocument(data.path);
      setStatus(`Importiert: ${data.path} (Original erschlossen unter wissen/${data.wissenPath})`, "ok");
    } catch (error) {
      status.textContent = `Import fehlgeschlagen: ${error.message}`;
      setStatus(`Import fehlgeschlagen: ${error.message}`, "error");
    } finally {
      busy = false;
      submit.disabled = false;
    }
  }

  return { openOfficeImportModal, cancelOfficeImport, confirmOfficeImport, handleFileSelected, requestAiDraft };
}
