import { templatesForType } from "./templates.js";
import { loadLastMaterialContext, saveLastMaterialContext } from "./ui-utils.js";

const PREVIEW_DEBOUNCE_MS = 250;

export function createNewDocumentController({ state, elements, api, normalizeSearch, slug, openModal, closeModal, applyQmds, loadDocument, openKursView, confirmDiscardOrSave, setStatus, renderTemplatePreview, populateTemplateSelect, scheduleRender, playSlides, onCreated = () => {} }) {
  let previewTimer = null;
  let previewGeneration = 0;

  function isKursKind() {
    return elements.newKind.value === "Kurs (H5P)";
  }

  function isSlidesKind() {
    return elements.newKind.value === "Excalidraw-Folien";
  }

  function isWorksheetKind() {
    return elements.newKind.value === "Mini-AB" || normalizeSearch(elements.newKind.value).includes("arbeitsblatt");
  }

  function openNewDocModal(folder = null, defaults = {}) {
    elements.newTargetFolderField.hidden = folder === null;
    elements.newTargetFolder.value = folder ?? "";
    elements.newKind.querySelector('option:last-child').disabled = folder !== null;
    if (folder !== null && isKursKind()) elements.newKind.value = "Arbeitsblatt";
    // Vorbelegung mit zuletzt verwendetem Fach/Klasse/Thema spart Tipparbeit bei
    // mehreren Dateien zum selben Material in Folge.
    const lastContext = loadLastMaterialContext();
    if (lastContext.subject) elements.newSubject.value = lastContext.subject;
    if (lastContext.grade) elements.newGrade.value = lastContext.grade;
    if (lastContext.topic) elements.newTopic.value = lastContext.topic;
    for (const [key, element] of Object.entries({ kind: elements.newKind, subject: elements.newSubject, grade: elements.newGrade, topic: elements.newTopic, title: elements.newTitle, filename: elements.newFilename })) {
      if (Object.hasOwn(defaults, key)) element.value = defaults[key];
    }
    if (Object.keys(defaults).length) elements.newMini.checked = false;
    updateNewDocMode();
    applyTemplateSuggestion();
    updateNewDocPathPreview();
    openModal(elements.newDocModal, elements.newTitle);
  }

  function closeNewDocModal() {
    closeModal(elements.newDocModal);
  }

  function updateNewDocMode() {
    const kursMode = isKursKind();
    elements.newDocQuartoFields.hidden = kursMode;
    elements.newKursFields.hidden = !kursMode;
    const note = elements.newKind.value === "Notiz";
    elements.newTitle.placeholder = note ? "Notiz" : "Arbeitsblatt";
    elements.newTemplate.closest("label").hidden = note;
    elements.newTemplatePreview.hidden = note;
    if (note) elements.newTemplate.value = "";
    elements.newMiniField.hidden = kursMode || !isWorksheetKind() || elements.newKind.value === "Mini-AB";
  }

  function applyTemplateSuggestion() {
    updateNewDocMode();
    if (isKursKind() || elements.newKind.value === "Notiz") {
      updateNewDocPathPreview();
      return;
    }
    const kind = elements.newKind.value === "Praesentation" ? "Präsentation" : elements.newKind.value;
    const templates = isSlidesKind() ? state.slideTemplates : state.templates;
    const filtered = templatesForType(templates, kind);
    populateTemplateSelect(elements.newTemplate, filtered);
    if (!filtered.length) elements.newTemplate.add(new Option("Standardausgabe (ohne Vorlage)", ""));
    const preferred = filtered[0];
    if (preferred) elements.newTemplate.value = preferred.path;
    renderTemplatePreview(elements.newTemplate, elements.newTemplatePreview);
    updateNewDocPathPreview();
  }

  // Serverseitig berechnet (DocumentService.resolve_target), damit Vorschau und
  // tatsaechlicher Zielpfad (Praefix-/Nummerierungsregeln aus CLAUDE.md) nie auseinanderlaufen.
  function updateNewDocPathPreview() {
    if (isKursKind()) {
      const kursSlug = slug(elements.newKursSlug.value || elements.newTitle.value || "mein-kurs");
      elements.newDocStatus.textContent = `unterricht/kurse/${kursSlug}/`;
      elements.newDocStatus.classList.remove("exists");
      elements.createNewDoc.disabled = false;
      return;
    }
    clearTimeout(previewTimer);
    previewTimer = setTimeout(fetchPathPreview, PREVIEW_DEBOUNCE_MS);
  }

  async function fetchPathPreview() {
    const generation = ++previewGeneration;
    const params = new URLSearchParams({
      subject: elements.newSubject.value,
      grade: elements.newGrade.value,
      topic: elements.newTopic.value,
      title: elements.newTitle.value,
      kind: elements.newKind.value,
      filename: elements.newFilename.value,
      template: elements.newTemplate.value,
      mini: (elements.newKind.value === "Mini-AB" || elements.newMini.checked) ? "1" : "0"
    });
    if (!elements.newTargetFolderField.hidden) params.set("folder", elements.newTargetFolder.value);
    try {
      const data = await api(`/api/document/new-preview?${params}`);
      if (generation !== previewGeneration) return;
      elements.newDocStatus.textContent = data.exists ? `${data.path} (Datei existiert bereits)` : data.path;
      elements.newDocStatus.classList.toggle("exists", data.exists);
      if (data.exists) elements.newDocStatus.closest("details").open = true;
      elements.createNewDoc.disabled = data.exists;
    } catch (error) {
      if (generation !== previewGeneration) return;
      elements.newDocStatus.closest("details").open = true;
      elements.newDocStatus.textContent = `Vorschau fehlgeschlagen: ${error.message}`;
      elements.newDocStatus.classList.remove("exists");
      elements.createNewDoc.disabled = false;
    }
  }

  async function createNewDocument() {
    if (isKursKind()) {
      await createNewKurs();
      return;
    }
    try {
      if (!(await confirmDiscardOrSave())) return;
      const payload = {
        subject: elements.newSubject.value,
        grade: elements.newGrade.value,
        topic: elements.newTopic.value,
        title: elements.newTitle.value,
        kind: elements.newKind.value,
        filename: elements.newFilename.value,
        template: elements.newTemplate.value,
        mini: isWorksheetKind() && (elements.newKind.value === "Mini-AB" || elements.newMini.checked)
      };
      if (!elements.newTargetFolderField.hidden) payload.folder = elements.newTargetFolder.value;
      const data = await api("/api/document/new", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      saveLastMaterialContext({ subject: elements.newSubject.value, grade: elements.newGrade.value, topic: elements.newTopic.value });
      applyQmds(data);
      closeNewDocModal();
      await onCreated(data);
      await loadDocument(data.path);
      setStatus(`Angelegt: ${data.path}`, "ok");
      if (isSlidesKind()) await playSlides();
      else if (elements.newKind.value !== "Notiz" && state.autoRender) scheduleRender();
    } catch (error) {
      elements.newDocStatus.closest("details").open = true;
      elements.newDocStatus.textContent = `Anlegen fehlgeschlagen: ${error.message}`;
      setStatus(`Anlegen fehlgeschlagen: ${error.message}`, "error");
    }
  }

  async function createNewKurs() {
    try {
      if (!(await confirmDiscardOrSave())) return;
      const payload = {
        slug: elements.newKursSlug.value,
        title: elements.newTitle.value,
        language: elements.newKursLanguage.value
      };
      const data = await api("/api/kurse/new", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      applyQmds(data);
      closeNewDocModal();
      openKursView(data.kurs);
      setStatus(`Kurs angelegt: ${data.kurs.slug}`, "ok");
    } catch (error) {
      elements.newDocStatus.closest("details").open = true;
      elements.newDocStatus.textContent = `Anlegen fehlgeschlagen: ${error.message}`;
      setStatus(`Anlegen fehlgeschlagen: ${error.message}`, "error");
    }
  }

  return { isKursKind, openNewDocModal, closeNewDocModal, updateNewDocMode, applyTemplateSuggestion, updateNewDocPathPreview, createNewDocument };
}
