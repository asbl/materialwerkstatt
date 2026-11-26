import { materialIcon } from "./ui-utils.js";
export function createFileActionController({ state, elements, api, escapeHtml, uiIcon, openModal, closeModal, applyQmds, loadDocument, selectDocument, renameTab, closeTab, removeTab, flushPendingSave, setStatus, onDeleted = async () => {} }) {
  let fileAction = null;

  function fileActionButtons(entry) {
    return `<button type="button" class="icon-button" data-rename="${escapeHtml(entry.path)}" title="Umbenennen" aria-label="${escapeHtml(entry.name)} umbenennen">${uiIcon("rename")}</button>`
      + (["solution", "note"].includes(materialIcon(entry)) ? "" : `<button type="button" class="icon-button" data-delete="${escapeHtml(entry.path)}" title="Löschen" aria-label="${escapeHtml(entry.name)} löschen">${uiIcon("trash")}</button>`);
  }

  async function openFileAction(mode, path, position) {
    fileAction = { mode, path };
    const action = fileAction;
    const settings = document.getElementById("folderSettings");
    settings.hidden = true; settings.disabled = true;
    document.getElementById("fileActionConfirm").disabled = false;
    const renaming = mode === "rename" || mode === "rename-folder";
    const noun = mode === "rename-folder" ? "Ordner" : "Datei";
    const name = path.split("/").pop() || path;
    const modal = document.getElementById("fileActionModal");
    document.getElementById("fileActionTitle").textContent = renaming ? `${noun} umbenennen` : "Datei löschen";
    document.getElementById("fileActionText").textContent = renaming
      ? `Neuen ${noun}namen für "${name}" eingeben.`
      : `"${name}" wird unwiderruflich gelöscht.`;
    const nameField = document.getElementById("fileActionNameField");
    const nameInput = document.getElementById("fileActionName");
    nameField.textContent = `Neuer ${noun}name`;
    nameField.hidden = !renaming;
    nameInput.hidden = !renaming;
    nameInput.value = name;
    document.getElementById("fileActionConfirm").textContent = renaming ? "Umbenennen" : "Löschen";
    document.getElementById("fileActionStatus").textContent = "";
    if (mode === "reorder-folder") {
      document.getElementById("fileActionTitle").textContent = "Ordner umsortieren";
      document.getElementById("fileActionText").textContent = `Neue Position für "${name}" eingeben. Alle nummerierten Ordner auf dieser Ebene werden ab 1 neu nummeriert.`;
      nameField.textContent = "Neue Nummer";
      nameField.hidden = false;
      nameInput.hidden = false;
      nameInput.value = String(position);
      document.getElementById("fileActionConfirm").textContent = "Umsortieren";
    }
    openModal(modal, renaming || mode === "reorder-folder" ? nameInput : document.getElementById("fileActionCancel"));
    if (mode === "rename-folder") {
      document.getElementById("fileActionTitle").textContent = "Ordner bearbeiten";
      document.getElementById("fileActionText").textContent = "Ordnername, Einheit und Hinweise bearbeiten.";
      document.getElementById("fileActionConfirm").textContent = "Speichern";
      document.getElementById("fileActionConfirm").disabled = true;
      try {
        const data = await api(`/api/folder/settings?path=${encodeURIComponent(path)}`);
        if (fileAction !== action) return;
        action.settings = data;
        document.getElementById("folderNotes").value = data.notes.text;
        document.getElementById("folderUnitFields").hidden = !data.unit;
        for (const [id, key] of [["Title", "titel"], ["Topic", "thema"], ["Description", "kurzbeschreibung"]]) {
          document.getElementById(`folderUnit${id}`).value = data.unit?.data[key] || "";
        }
        settings.hidden = false; settings.disabled = false;
        document.getElementById("fileActionConfirm").disabled = false;
      } catch (error) {
        if (fileAction === action) document.getElementById("fileActionStatus").textContent = error.message;
      }
    }
  }

  function closeFileActionModal() {
    fileAction = null;
    closeModal(document.getElementById("fileActionModal"));
  }

  async function confirmFileAction(event) {
    event.preventDefault();
    if (!fileAction) return;
    const { mode, path } = fileAction;
    const folder = mode === "rename-folder";
    const renaming = mode === "rename" || folder;
    const remap = value => value === path || (folder && value?.startsWith(`${path}/`));
    const status = document.getElementById("fileActionStatus");
    const confirmButton = document.getElementById("fileActionConfirm");
    confirmButton.disabled = true;
    try {
      if (mode === "reorder-folder") {
        const value = document.getElementById("fileActionName").value.trim();
        if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value))) throw new Error("Bitte eine ganze Zahl als Position angeben.");
        await flushPendingSave();
        const data = await api("/api/folder/reorder", { method: "POST", body: JSON.stringify({ path, position: Number(value) }) });
        const mapPath = value => {
          const old = Object.keys(data.paths).find(key => value === key || value?.startsWith(`${key}/`));
          return old ? data.paths[old] + value.slice(old.length) : value;
        };
        const active = state.qmdPath;
        // Intermediate tab names prevent collisions when siblings exchange names.
        const changes = [...state.tabs].filter(value => mapPath(value) !== value);
        changes.forEach((value, i) => renameTab(value, `:reorder:${i}`));
        changes.forEach((value, i) => renameTab(`:reorder:${i}`, mapPath(value)));
        state.navigationFolder = mapPath(state.navigationFolder);
        applyQmds(data);
        if (mapPath(active) !== active) await selectDocument(mapPath(active));
        closeFileActionModal();
        setStatus("Ordner wurden umsortiert und neu nummeriert.", "ok");
        return;
      }
      if (remap(state.qmdPath)) await flushPendingSave();
      if (folder) {
        const settings = fileAction.settings;
        if (!settings) throw new Error("Ordnerangaben sind noch nicht geladen.");
        const unit = settings.unit ? structuredClone(settings.unit.data) : null;
        if (unit) for (const [id, key] of [["Title", "titel"], ["Topic", "thema"], ["Description", "kurzbeschreibung"]]) {
          unit[key] = document.getElementById(`folderUnit${id}`).value;
        }
        await api("/api/folder/settings", { method: "POST", body: JSON.stringify({ path, unit,
          unitRevision: settings.unit?.revision, notes: document.getElementById("folderNotes").value,
          notesRevision: settings.notes.revision }) });
        // Refresh revisions so a failed rename can safely be retried.
        fileAction.settings = await api(`/api/folder/settings?path=${encodeURIComponent(path)}`);
      }
      let data;
      if (renaming) {
        const name = document.getElementById("fileActionName").value.trim();
        if (!name) throw new Error(folder ? "Bitte einen Ordnernamen angeben." : "Bitte einen Dateinamen angeben.");
        data = folder && name === path.split("/").pop()
          ? { ...(await api("/api/qmds")), path }
          : await api(folder ? "/api/folder/rename" : "/api/file/rename", {
          method: "POST",
          body: JSON.stringify({ path, name })
        });
      } else {
        data = await api(`/api/file?path=${encodeURIComponent(path)}`, { method: "DELETE" });
      }
      if (renaming) {
        const activePath = state.qmdPath;
        const newPath = value => data.path + value.slice(path.length);
        const paths = folder ? [...state.tabs].filter(remap) : [path];
        for (const oldPath of paths) renameTab(oldPath, newPath(oldPath));
        if (folder && remap(state.navigationFolder)) state.navigationFolder = newPath(state.navigationFolder);
        applyQmds(data);
        if (remap(activePath)) {
          if (folder) await selectDocument(newPath(activePath));
          else await loadDocument(newPath(activePath));
        }
      } else applyQmds(data);
      if (mode === "delete") {
        if (path === state.qmdPath) await closeTab(path);
        else removeTab(path);
      }
      closeFileActionModal();
      if (mode === "delete") await onDeleted(path);
      setStatus(folder ? `Ordner gespeichert: ${data.path}` : renaming ? `Umbenannt: ${data.path}` : `Gelöscht: ${path}`, "ok");
    } catch (error) {
      status.textContent = error.message;
      setStatus(`Aktion fehlgeschlagen: ${error.message}`, "error");
    } finally {
      confirmButton.disabled = false;
    }
  }

  return { fileActionButtons, openFileAction, closeFileActionModal, confirmFileAction };
}
