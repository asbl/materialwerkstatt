export function createUnitMaterialPicker({ dialog, api, normalizeSearch, onLinked }) {
  const form = dialog.querySelector("form");
  const filter = form.elements.filter;
  const select = form.elements.unit;
  const submit = form.querySelector('[type="submit"]');
  const cancel = form.querySelector('[data-cancel]');
  const status = form.querySelector('[role="status"]');
  let material, units = [], loading = false, saving = false;

  function render(preferred = select.value) {
    const terms = normalizeSearch(filter.value).trim().split(/\s+/).filter(Boolean);
    const options = [new Option("Einheit auswählen", "")];
    for (const unit of units) {
      const label = `${unit.data.titel} · ${unit.fach} · ${unit.klasse.replace("klasse-", "Klasse ")} · ${unit.data.thema}`;
      if (terms.every(term => normalizeSearch(label).includes(term))) options.push(new Option(label, unit.path));
    }
    select.replaceChildren(...options);
    select.value = options.some(option => option.value === preferred) ? preferred : "";
    select.disabled = loading || saving || options.length === 1;
    filter.disabled = loading || saving;
    submit.disabled = select.disabled || !select.value;
  }

  async function load(preferred = "") {
    loading = true;
    status.textContent = "Einheiten werden geladen …";
    render();
    try {
      const data = await api("/api/units");
      units = data.units.filter(unit => !material.path.startsWith(`${unit.path}/`) &&
        !(unit.materialEntries || []).some(entry => entry.sourcePath === material.path))
        .sort((a, b) => a.klasse.localeCompare(b.klasse) || a.data.titel.localeCompare(b.data.titel, "de"));
      status.textContent = units.length ? "" : "Keine weitere Einheit zur Auswahl.";
    } catch (error) {
      units = [];
      status.textContent = error.message;
    } finally {
      loading = false;
      render(preferred);
    }
  }

  filter.addEventListener("input", () => render());
  select.addEventListener("change", () => { submit.disabled = !select.value; });
  cancel.addEventListener("click", () => dialog.close());
  dialog.addEventListener("cancel", event => { if (saving) event.preventDefault(); });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const unit = units.find(unit => unit.path === select.value);
    if (!unit || saving || loading) return;
    saving = true;
    cancel.disabled = true;
    render();
    status.textContent = "Arbeitsblatt wird hinzugefügt …";
    try {
      await api("/api/units/material", { method: "POST", body: JSON.stringify({
        path: unit.path, revision: unit.revision, material: material.path,
      }) });
      dialog.close();
      onLinked(unit);
    } catch (error) {
      if (error.status === 409) await load(unit.path);
      status.textContent = error.message;
    } finally {
      saving = false;
      cancel.disabled = false;
      render();
    }
  });

  return async function open(entry) {
    if (dialog.open || loading || saving) return;
    material = entry;
    units = [];
    form.reset();
    dialog.querySelector('[data-worksheet-title]').textContent = entry.title || entry.path;
    dialog.showModal();
    await load();
    if (dialog.open) filter.focus();
  };
}
