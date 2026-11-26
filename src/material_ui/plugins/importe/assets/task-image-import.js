import { consumeSseStream } from "../../../static/sse.js";

function csrfToken() {
  return document.querySelector('meta[name="material-token"]')?.content || "";
}

export function createTaskImageImportController({ state, api, openModal, closeModal, setStatus, getEditorText, setEditorText, flushPendingSave }) {
  let token = "";
  let sessionId = "";
  let busy = false;
  let originalUrl = "";
  let previewUrl = "";

  function modal() {
    return document.getElementById("taskImageImportModal");
  }

  function choiceModal() {
    return document.getElementById("imagePasteChoiceModal");
  }

  function revokeUrls() {
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    originalUrl = "";
    previewUrl = "";
  }

  async function askPasteChoice() {
    return new Promise((resolve) => {
      const dialog = choiceModal();
      const onPick = (choice) => {
        cleanup();
        resolve(choice);
      };
      const imageBtn = document.getElementById("pasteChoiceImage");
      const codeBtn = document.getElementById("pasteChoiceCode");
      const cancelHandlers = ["imagePasteChoiceClose", "imagePasteChoiceBackdrop"].map((id) => document.getElementById(id));
      function cleanup() {
        closeModal(dialog);
        imageBtn.removeEventListener("click", onImage);
        codeBtn.removeEventListener("click", onCode);
        for (const el of cancelHandlers) el.removeEventListener("click", onCancel);
      }
      function onImage() { onPick("bild"); }
      function onCode() { onPick("code"); }
      function onCancel() { onPick(""); }
      imageBtn.addEventListener("click", onImage);
      codeBtn.addEventListener("click", onCode);
      for (const el of cancelHandlers) el.addEventListener("click", onCancel);
      openModal(dialog, imageBtn);
    });
  }

  function appendChatLine(role, text) {
    const item = document.createElement("li");
    item.className = `chat-message chat-message-${role}`;
    item.textContent = text;
    const list = document.getElementById("taskImageChatMessages");
    list.append(item);
    list.scrollTop = list.scrollHeight;
  }

  async function ensureClaudeAvailable() {
    const data = await api("/api/chat/providers");
    const claude = (data.providers || []).find((provider) => provider.id === "claude");
    if (!claude || !claude.available) {
      throw new Error("Die Claude-CLI ist nicht verfügbar. Der Code-Import aus Bildern braucht sie für die Bilderkennung.");
    }
  }

  async function openTaskImageModal(file) {
    const status = document.getElementById("taskImageStatus");
    const codeField = document.getElementById("taskImageCode");
    const originalImg = document.getElementById("taskImageOriginal");
    const previewImg = document.getElementById("taskImagePreview");
    revokeUrls();
    token = "";
    sessionId = "";
    codeField.value = "";
    previewImg.removeAttribute("src");
    document.getElementById("taskImageChatMessages").replaceChildren();
    document.getElementById("taskImageCommitBtn").disabled = true;
    originalUrl = URL.createObjectURL(file);
    originalImg.src = originalUrl;
    status.textContent = "Bild wird hochgeladen …";
    openModal(modal(), document.getElementById("taskImageChatInput"));
    try {
      await ensureClaudeAvailable();
      const formData = new FormData();
      formData.append("file", file, "aufgabe.png");
      formData.append("documentPath", state.qmdPath);
      const staged = await api("/api/document/import/task-image", { method: "POST", body: formData, timeout: 60000 });
      token = staged.token;
      document.getElementById("taskImageWissenField").value = staged.wissenZiel || "";
      sessionId = (await api("/api/chat/sessions", { method: "POST", body: JSON.stringify({ provider: "claude" }) })).session_id;
      status.textContent = "KI erkennt die Aufgabe …";
      await streamIntoCode(staged.prompt);
      status.textContent = "Entwurf übernommen. Vorschau prüfen oder per Chat korrigieren.";
      document.getElementById("taskImageCommitBtn").disabled = !codeField.value.trim();
    } catch (error) {
      status.textContent = `Fehlgeschlagen: ${error.message}`;
    }
  }

  async function streamIntoCode(text) {
    const codeField = document.getElementById("taskImageCode");
    codeField.value = "";
    let failure = "";
    const response = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Material-Token": csrfToken() },
      body: JSON.stringify({ text })
    });
    await consumeSseStream(response, (event) => {
      if (event.type === "text" && event.text) codeField.value += event.text;
      else if (event.type === "error") failure = event.message || "Unbekannter Fehler.";
    });
    if (failure) throw new Error(failure);
  }

  async function sendCorrection(event) {
    event.preventDefault();
    const input = document.getElementById("taskImageChatInput");
    const text = input.value.trim();
    if (!text || busy || !token) return;
    busy = true;
    const status = document.getElementById("taskImageStatus");
    const send = document.getElementById("taskImageChatSend");
    send.disabled = true;
    appendChatLine("user", text);
    input.value = "";
    status.textContent = "KI überarbeitet den Code …";
    try {
      await streamIntoCode(text);
      appendChatLine("assistant", "Code aktualisiert.");
      status.textContent = "Code aktualisiert. Vorschau bei Bedarf neu rendern.";
      document.getElementById("taskImageCommitBtn").disabled = !document.getElementById("taskImageCode").value.trim();
    } catch (error) {
      appendChatLine("error", error.message);
      status.textContent = `Korrektur fehlgeschlagen: ${error.message}`;
    } finally {
      busy = false;
      send.disabled = false;
      input.focus();
    }
  }

  async function refreshPreview() {
    if (!token) return;
    const button = document.getElementById("taskImageRenderBtn");
    const status = document.getElementById("taskImageStatus");
    const code = document.getElementById("taskImageCode").value;
    button.disabled = true;
    status.textContent = "Vorschau wird gerendert …";
    try {
      const response = await fetch(`/api/document/import/task-image/${encodeURIComponent(token)}/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Material-Token": csrfToken() },
        body: JSON.stringify({ code })
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.error?.message || "Render fehlgeschlagen.");
      }
      const blob = await response.blob();
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = URL.createObjectURL(blob);
      document.getElementById("taskImagePreview").src = previewUrl;
      status.textContent = "Vorschau aktualisiert.";
    } catch (error) {
      status.textContent = `Vorschau fehlgeschlagen: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  }

  async function cancelTaskImageImport() {
    if (busy) return;
    const closingSession = sessionId;
    const closingToken = token;
    sessionId = "";
    token = "";
    if (closingSession) await api(`/api/chat/sessions/${closingSession}`, { method: "DELETE" }).catch(() => {});
    if (closingToken) await api(`/api/document/import/task-image/${encodeURIComponent(closingToken)}`, { method: "DELETE" }).catch(() => {});
    revokeUrls();
    closeModal(modal());
  }

  async function commitTaskImageImport() {
    if (busy || !token) return;
    const code = document.getElementById("taskImageCode").value;
    const wissenZiel = document.getElementById("taskImageWissenField").value;
    const status = document.getElementById("taskImageStatus");
    busy = true;
    document.getElementById("taskImageCommitBtn").disabled = true;
    try {
      await flushPendingSave();
      const session = state.session;
      const data = await api(`/api/document/import/task-image/${encodeURIComponent(token)}`, {
        method: "POST",
        body: JSON.stringify({ code, wissenZiel })
      });
      if (session === state.session) {
        const text = getEditorText();
        const marker = "<!-- material-ui -->";
        setEditorText(
          text.includes(marker)
            ? text.replace(marker, `${data.markdown.trimEnd()}\n\n${marker}`)
            : `${text.trimEnd()}\n${data.markdown}`
        );
        state.dirty = true;
        await flushPendingSave();
      }
      const closingSession = sessionId;
      sessionId = "";
      token = "";
      if (closingSession) await api(`/api/chat/sessions/${closingSession}`, { method: "DELETE" }).catch(() => {});
      revokeUrls();
      closeModal(modal());
      setStatus(`Aufgabe importiert (Original erschlossen unter wissen/${data.wissenPath}).`, "ok");
    } catch (error) {
      status.textContent = `Import fehlgeschlagen: ${error.message}`;
      setStatus(`Import fehlgeschlagen: ${error.message}`, "error");
    } finally {
      busy = false;
      document.getElementById("taskImageCommitBtn").disabled = false;
    }
  }

  return { askPasteChoice, openTaskImageModal, sendCorrection, refreshPreview, cancelTaskImageImport, commitTaskImageImport };
}
