import { updatePresentationActions } from "./presentation-actions.js";
import { api } from "./api.js";

export function templatesForType(templates, type) {
  return templates.filter(template => (template.tags || []).includes(type));
}

export function templateTypes(templates) {
  return [...new Set(templates.flatMap(template => template.tags || []))];
}

export function createTemplateController({ state, elements, getEditorText, setEditorText, setStatus, scheduleAutoUpdate, populateTemplateSelect, renderTemplatePreview, openModal, closeModal }) {
  let opening = 0;
  let draft = null;
  let draftSession = null;
  const versionControls = document.createElement("section");
  versionControls.innerHTML = `
    <label>Version <select data-template-version></select></label>
    <button type="button" data-template-edit>Template bearbeiten</button>
    <fieldset data-template-draft hidden>
      <legend>Neue Version · Entwurf</legend>
      <label>Grundschrift (pt; leer = bisheriger Standard, mindestens 11)
        <input data-template-fontsize type="number" min="11" max="32" step="0.1">
      </label>
      <label>Änderungsnotiz <input data-template-note maxlength="2000"></label>
      <p>Die Schriftgröße gilt als Standard und liegt immer bei mindestens 11 pt. LaTeX-Vorlagen unterstützen 11 und 12 pt.</p>
      <label><input data-template-default type="checkbox" checked> Für neue ABs vorauswählen</label>
      <div class="button-row">
        <button type="button" data-template-save>Entwurf speichern</button>
        <button type="button" data-template-preview>PDF-Vorschau</button>
        <button type="button" data-template-publish>Version freigeben</button>
      </div>
      <a data-template-pdf hidden target="_blank" rel="noopener">Vorschau öffnen</a>
      <p data-template-draft-status role="status"></p>
    </fieldset>`;
  elements.templateStatus.before(versionControls);
  const control = name => versionControls.querySelector(`[data-template-${name}]`);

  function selectVersion(preferred) {
    draft = null;
    control("draft").hidden = true;
    const selected = state.templates.find(item => item.path === elements.templateSelect.value);
    const releases = selected?.releases || [];
    control("version").replaceChildren(...releases.map(item => new Option(
      `v${item.version} · ${item.fontsize || "bisherige Schriftgröße"}${item.note ? ` · ${item.note}` : ""}`, item.release)));
    control("version").disabled = !releases.length;
    control("edit").disabled = !releases.length;
    control("version").value = releases.some(item => item.release === preferred) ? preferred : selected?.release || "";
  }
  elements.templateSelect.addEventListener("change", () => selectVersion());
  control("version").addEventListener("change", () => { draft = null; control("draft").hidden = true; });
  async function draftAction(action) {
    const disabled = [...versionControls.querySelectorAll("input, select, button"), elements.templateSelect,
      elements.templateType, elements.applyTemplate].map(element => [element, element.disabled]);
    try {
      disabled.forEach(([element]) => { element.disabled = true; });
      control("draft-status").textContent = "Wird verarbeitet …";
      await action();
    } catch (error) {
      control("draft-status").textContent = error.message;
      setStatus(error.message, "error");
    } finally {
      disabled.forEach(([element, previous]) => { element.disabled = previous; });
    }
  }
  control("edit").addEventListener("click", () => draftAction(async () => {
    const release = control("version").value;
    const data = await api("/api/template-drafts", { method: "POST", body: JSON.stringify({ release }) });
    draft = data.draft;
    draftSession = state.session;
    control("fontsize").value = (data.settings.fontsize || "").replace(/pt$/, "");
    control("note").value = data.note || "";
    control("draft").hidden = false;
    control("pdf").hidden = true;
    control("draft-status").textContent = "Entwurf erstellt. Bestehende ABs behalten ihre Version.";
  }));
  async function saveDraft() {
    if (!draft || draftSession !== state.session) throw new Error("Bitte Entwurf für das aktuelle Dokument erneut öffnen.");
    const value = control("fontsize").value;
    await api("/api/template-drafts/save", { method: "POST", body: JSON.stringify({
      draft, fontsize: value ? `${value}pt` : "", note: control("note").value
    }) });
  }
  control("save").addEventListener("click", () => draftAction(async () => {
    await saveDraft();
    control("draft-status").textContent = "Entwurf gespeichert. Du kannst ihn später über „Template bearbeiten“ fortsetzen.";
  }));
  control("preview").addEventListener("click", () => draftAction(async () => {
    await saveDraft();
    const data = await api("/api/template-drafts/preview", { method: "POST", timeout: 120000,
      body: JSON.stringify({ draft, path: state.qmdPath, text: getEditorText() }) });
    control("pdf").href = `/api/pdf?path=${encodeURIComponent(data.pdf)}`;
    control("pdf").hidden = false;
    control("draft-status").textContent = "PDF-Vorschau fertig. Bitte Umbrüche und Antwortflächen prüfen.";
  }));
  control("publish").addEventListener("click", () => draftAction(async () => {
    await saveDraft();
    const data = await api("/api/template-drafts/publish", { method: "POST",
      body: JSON.stringify({ draft, makeDefault: control("default").checked }) });
    const catalog = await api("/api/templates");
    state.templates = [...catalog.templates, ...catalog.slideTemplates];
    selectVersion(data.release);
    elements.templateStatus.textContent = `v${data.version} freigegeben. Das aktuelle AB behält seine Version, bis du „Übernehmen“ wählst.`;
  }));

  function selectTemplateType(preferredPath) {
    const templates = state.templates;
    const filtered = templatesForType(templates, elements.templateType.value);
    populateTemplateSelect(elements.templateSelect, filtered);
    elements.templateSelect.disabled = filtered.length === 0;
    elements.applyTemplate.disabled = filtered.length === 0;
    if (!filtered.length) {
      elements.templateSelect.add(new Option("Bitte zuerst einen Typ auswählen", ""));
    } else if (filtered.some(template => template.path === preferredPath)) {
      elements.templateSelect.value = preferredPath;
    }
    renderTemplatePreview(elements.templateSelect, elements.templatePreview);
    selectVersion();
  }

  async function openTemplateModal() {
    const request = ++opening;
    const session = state.session;
    const text = getEditorText();
    elements.templateType.replaceChildren();
    elements.templateSelect.replaceChildren();
    elements.templatePreview.replaceChildren();
    elements.templateType.disabled = true;
    elements.templateSelect.disabled = true;
    elements.applyTemplate.disabled = true;
    elements.removeTemplate.disabled = true;
    versionControls.hidden = true;
    draft = null;
    elements.templateStatus.textContent = "Vorlagen werden geladen …";
    openModal(elements.templateModal, elements.templateModal.querySelector("button"));
    try {
      const [catalog, data] = await Promise.all([
        api("/api/templates", { timeout: 60000 }),
        api("/api/document/metadata", { method: "POST", body: JSON.stringify({ text }) })
      ]);
      if (request !== opening) return;
      if (session !== state.session) {
        closeTemplateModal();
        return;
      }
      if (text !== getEditorText()) throw new Error("Dokument wurde geändert. Bitte die Template-Auswahl erneut öffnen.");
      state.templates = [...catalog.templates, ...catalog.slideTemplates];
      const templates = state.templates;
      const current = data.template;
      const absoluteCurrent = current ? normalizeTemplatePath(current) : "";
      const selected = absoluteCurrent ? templates.find(template => template.path === absoluteCurrent) : null;
      elements.templateType.replaceChildren(new Option("Typ auswählen …", ""), ...templateTypes(templates).map(type => new Option(type, type)));
      elements.templateType.value = selected?.tags?.[0] || "";
      selectTemplateType(absoluteCurrent);
      selectVersion(data.metadata?.["template-release"]);
      elements.templateType.disabled = false;
      elements.removeTemplate.disabled = false;
      versionControls.hidden = false;
      elements.templateStatus.textContent = current
        ? `Aktuell: ${current}. Vorlagen mit Foliendesign erzeugen beim Rendern auch passende Slides.`
        : "Wähle eine Vorlage für PDF und passende Folien.";
    } catch (error) {
      if (request !== opening) return;
      if (session !== state.session) {
        closeTemplateModal();
        return;
      }
      elements.templateStatus.textContent = `Template-Auswahl konnte nicht geladen werden: ${error.message}`;
      setStatus(elements.templateStatus.textContent, "error");
    }
  }

  function closeTemplateModal() {
    opening += 1;
    closeModal(elements.templateModal);
  }

  async function updateTemplate(template) {
    const session = state.session;
    const text = getEditorText();
    const selected = state.templates.find(item => item.path === template);
    const engine = selected?.engine === "Typst" ? "typst" : selected?.engine === "Beamer" ? "beamer" : "pdf";
    const data = await api("/api/document/metadata", {
      method: "POST", body: JSON.stringify({ text, template: template ? relativeTemplatePath(template) : "", engine,
        release: template ? control("version").value : "", path: state.qmdPath })
    });
    if (session !== state.session || text !== getEditorText()) {
      setStatus("Dokument wurde während der Template-Auswahl geändert. Bitte erneut anwenden.", "ready");
      return;
    }
    setEditorText(data.text);
    state.hasSlides = data.hasSlides;
    updatePresentationActions(elements.slidesPlay, data);
    closeTemplateModal();
    scheduleAutoUpdate();
  }

  function applySelectedTemplate() {
    if (elements.applyTemplate.disabled || elements.templateSelect.disabled) return;
    return updateTemplate(elements.templateSelect.value);
  }

  function removeTemplate() {
    if (elements.removeTemplate.disabled) return;
    return updateTemplate("");
  }

  function normalizeTemplatePath(value) {
    const clean = value.replace(/^['"]|['"]$/g, "").replace(/\\/g, "/").replace(/^\.\//, "");
    if (!clean.includes("/")) {
      // Eingebaute Vorlagen duerfen im Frontmatter als blosser Dateiname stehen;
      // der Build loest sie unabhaengig von der Ordnertiefe der Quelle auf.
      const builtin = state.templates.find(template => template.path.split("/").pop() === clean);
      if (builtin) return builtin.path;
    }
    if (!state.qmdPath || clean.startsWith("src/")) return clean;
    const stack = state.qmdPath.split("/");
    stack.pop();
    for (const part of clean.split("/")) {
      if (part === "..") stack.pop();
      else if (part && part !== ".") stack.push(part);
    }
    return stack.join("/");
  }

  function relativeTemplatePath(templatePath) {
    if (templatePath.startsWith("src/quarto/templates/")) return templatePath.split("/").pop();
    if (!state.qmdPath) return templatePath;
    const qmdParts = state.qmdPath.split("/");
    qmdParts.pop();
    const targetParts = templatePath.split("/");
    while (qmdParts.length && targetParts.length && qmdParts[0] === targetParts[0]) {
      qmdParts.shift();
      targetParts.shift();
    }
    return [...qmdParts.map(() => ".."), ...targetParts].join("/") || ".";
  }

  return { openTemplateModal, closeTemplateModal, applySelectedTemplate, removeTemplate, selectTemplateType };
}
