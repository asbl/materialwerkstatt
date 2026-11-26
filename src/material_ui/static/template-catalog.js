import { templateLayoutPreview } from "./template-preview.js";

export function createTemplateCatalog({ state, elements, api, escapeHtml }) {
  async function loadTemplates() {
    const data = await api("/api/templates");
    state.templates = [...(data.templates || []), ...(data.slideTemplates || [])];
    state.slideTemplates = data.slideTemplates || [];
    populateTemplateSelect(elements.templateSelect);
    populateTemplateSelect(elements.newTemplate);
  }

  function populateTemplateSelect(select, templates = state.templates) {
    select.innerHTML = templates.map((template) => (
      `<option value="${escapeHtml(template.path)}">${escapeHtml(template.label)}</option>`
    )).join("");
  }

  function renderTemplatePreview(select, target) {
    if (select.disabled) {
      target.innerHTML = `<span>Wähle zuerst einen Typ, anschließend eine passende Vorlage.</span>`;
      return;
    }
    const template = [...state.templates, ...state.slideTemplates].find((item) => item.path === select.value);
    if (!template || !template.path) {
      target.innerHTML = `<strong>Ohne Template</strong><span>Quarto nutzt die Standardausgabe.</span>`;
      return;
    }
    target.innerHTML = `
      ${templateLayoutPreview(template.path, template.design, template.target)}
      <div class="template-preview-details">
      <strong>${escapeHtml(template.label)}</strong>
      <div class="template-type-tags">${(template.tags || []).map(tag => `<span class="template-type-tag">${escapeHtml(tag)}</span>`).join("")}</div>
      <p>${escapeHtml(template.description || "")}</p>
      <p>${escapeHtml(template.preview || "")}</p>
      </div>
    `;
  }


  return { loadTemplates, populateTemplateSelect, renderTemplatePreview };
}
