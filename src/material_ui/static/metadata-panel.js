const METADATA_FIELDS = [
  ["metadataTitle", "title"],
  ["metadataSubtitle", "subtitle"],
  ["metadataAuthor", "author"],
  ["metadataDate", "date"],
  ["metadataDeck", "deck"]
];

const TAGS_INPUT = "metadataTags";
const TAGS_DATALIST = "metadataTagsList";

export function parseTagInput(value) {
  const seen = [];
  for (const item of String(value || "").split(",")) {
    const cleaned = item.trim();
    if (cleaned && !seen.includes(cleaned)) seen.push(cleaned);
  }
  return seen;
}

export function createMetadataController({ state, elements, api, getEditorText, setEditorText, scheduleAutoUpdate, openModal, closeModal, setStatus }) {
  let tagSuggestions = null;

  function loadTagSuggestions() {
    if (tagSuggestions) return;
    api("/api/tags")
      .then((data) => {
        tagSuggestions = (data.tags || []).map((item) => item.tag);
        document.getElementById(TAGS_DATALIST).innerHTML = tagSuggestions
          .map((tag) => `<option value="${tag}"></option>`)
          .join("");
      })
      .catch(() => {});
  }

  function openMetadataModal() {
    if (state.course.kursMode || !state.qmdPath) return;
    const status = document.getElementById("metadataStatus");
    status.textContent = "Metadaten werden gelesen …";
    for (const [input] of METADATA_FIELDS) document.getElementById(input).value = "";
    document.getElementById(TAGS_INPUT).value = "";
    loadTagSuggestions();
    openModal(document.getElementById("metadataModal"), document.getElementById("metadataTitle"));
    api("/api/document/metadata", { method: "POST", body: JSON.stringify({ text: getEditorText() }) })
      .then((data) => {
        const metadata = data.metadata || {};
        for (const [input, key] of METADATA_FIELDS) {
          document.getElementById(input).value = metadata[key] == null ? "" : String(metadata[key]);
        }
        const tagsValue = metadata.tags == null
          ? ""
          : Array.isArray(metadata.tags)
            ? metadata.tags.join(", ")
            : String(metadata.tags);
        document.getElementById(TAGS_INPUT).value = tagsValue;
        status.textContent = "Einträge aus dem YAML-Header des aktuellen Textes.";
      })
      .catch((error) => {
        status.textContent = `Metadaten konnten nicht gelesen werden: ${error.message}`;
      });
  }

  function closeMetadataModal() {
    closeModal(document.getElementById("metadataModal"));
  }

  async function applyMetadata() {
    const fields = {};
    for (const [input, key] of METADATA_FIELDS) {
      fields[key] = document.getElementById(input).value;
    }
    fields.tags = parseTagInput(document.getElementById(TAGS_INPUT).value);
    const status = document.getElementById("metadataStatus");
    const button = document.getElementById("applyMetadata");
    button.disabled = true;
    try {
      const data = await api("/api/document/metadata", {
        method: "POST",
        body: JSON.stringify({ text: getEditorText(), fields })
      });
      setEditorText(data.text);
      scheduleAutoUpdate();
      tagSuggestions = null;
      closeMetadataModal();
      setStatus("Metadaten übernommen. Beim nächsten Speichern wird der Header geschrieben.", "ok");
    } catch (error) {
      status.textContent = `Übernehmen fehlgeschlagen: ${error.message}`;
      setStatus(`Metadaten fehlgeschlagen: ${error.message}`, "error");
    } finally {
      button.disabled = false;
    }
  }

  return { openMetadataModal, closeMetadataModal, applyMetadata };
}
