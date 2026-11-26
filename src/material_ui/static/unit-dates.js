import { escapeHtml as esc } from './ui-utils.js';

// Termine einer Einheit direkt in der Karte bearbeiten und ergänzen („Termine“).
// Eigenständiges Modul: Zustand (quickDates, savingDates) und Hilfen kommen als Argumente,
// der Ansichtswechsel nach dem Speichern läuft über setView({ schoolClass, schoolTerm, schoolYear }).
export function createUnitDates({ api, quickDates, savingDates, persistWorkspace, load, groupSelect, labelDate, year,
  unitTerm, existingDateRows, setView, getSection }) {
  function renderQuickDates(unit, card) {
    const container = card.querySelector('[data-quick-date-form]');
    container.replaceChildren();
    const draft = quickDates.get(unit.path);
    if (!draft) return;
    if (!Array.isArray(draft.existing)) {
      draft.existing = existingDateRows(draft.unit);
      if (draft.existing.length && draft.dates.length === 1 && !draft.dates[0]) draft.dates = [];
    }
    const form = document.createElement('form');
    form.className = 'unit-quick-dates';
    form.innerHTML = `<strong>Termine</strong><div data-existing-date-rows></div><div data-date-rows></div>
      <button type="button" class="unit-edit" data-more-date>Weiteres Datum</button>
      <label data-new-date-group>Lerngruppe für neue Termine${groupSelect(draft.lerngruppe)}</label>
      <button type="submit">Termine speichern</button><button type="button" data-cancel-dates>Abbrechen</button><p role="status"></p>`;
    const rows = form.querySelector('[data-date-rows]');
    const existingRows = form.querySelector('[data-existing-date-rows]');
    function payloadOf(value) {
      return { dates: [...value.dates], lerngruppe: value.lerngruppe,
        updates: value.existing.filter(row => row.datum !== value.unit.data.einsatz[row.index]?.datum).map(row => ({ index: row.index, datum: row.datum })) };
    }
    function updateControls() {
      const payload = payloadOf(draft);
      form.querySelector('[type=submit]').disabled = (!payload.dates.length && !payload.updates.length) || savingDates.has(unit.path);
      form.querySelector('[data-new-date-group]').hidden = !draft.dates.length;
      form.elements.lerngruppe.disabled = !draft.dates.length;
    }
    function remember() {
      draft.existing = [...existingRows.querySelectorAll('input')].map(input => ({ index: Number(input.dataset.index), datum: input.value }));
      draft.dates = [...rows.querySelectorAll('input')].map(input => input.value);
      draft.lerngruppe = form.elements.lerngruppe.value;
      quickDates.set(unit.path, draft); persistWorkspace(); updateControls();
    }
    for (const row of draft.existing) {
      const use = draft.unit.data.einsatz[row.index];
      const context = [use?.lerngruppe, use?.material, use?.notiz].filter(Boolean).join(' · ');
      const label = document.createElement('label');
      label.innerHTML = `Gespeicherter Termin · ${labelDate(use.datum)}${context ? `<small class="unit-date-context">${esc(context)}</small>` : ''}<input type="date" required data-index="${row.index}" value="${esc(row.datum)}">`;
      existingRows.append(label);
    }
    function add(value = '') {
      const row = document.createElement('div'); row.className = 'unit-date-row';
      row.innerHTML = `<label>Neuer Termin<input type="date" required value="${esc(value)}"></label><button type="button" class="unit-edit" aria-label="Neuen Termin entfernen">Entfernen</button>`;
      row.querySelector('button').onclick = () => { row.remove(); remember(); };
      rows.append(row);
    }
    draft.dates.forEach(add);
    form.addEventListener('input', remember); form.addEventListener('change', remember);
    form.querySelector('[data-more-date]').onclick = () => { add(); remember(); rows.lastElementChild.querySelector('input').focus(); };
    form.querySelector('[data-cancel-dates]').onclick = () => {
      if (savingDates.has(unit.path)) return;
      quickDates.delete(unit.path); persistWorkspace(); container.replaceChildren();
    };
    updateControls();
    form.onsubmit = async event => {
      event.preventDefault(); if (savingDates.has(unit.path)) return;
      remember();
      const submitted = payloadOf(draft);
      if (!submitted.dates.length && !submitted.updates.length) return;
      savingDates.add(unit.path); updateControls();
      try {
        const saved = await api('/api/units/dates', { method: 'POST', body: JSON.stringify({ path: unit.path, revision: draft.unit.revision, ...submitted }) });
        const current = quickDates.get(unit.path);
        if (current && JSON.stringify(payloadOf(current)) === JSON.stringify(submitted)) quickDates.delete(unit.path);
        else if (current) current.unit = { ...current.unit, ...saved };
        // Die Ansicht springt auf Klasse, Halbjahr und Schuljahr der gespeicherten Termine.
        const years = [...new Set([...submitted.dates, ...submitted.updates.map(update => update.datum)].map(year))];
        setView({ schoolClass: unit.klasse, schoolTerm: unitTerm(saved), schoolYear: years.length === 1 ? years[0] : '' });
        persistWorkspace(); await load();
      } catch (error) {
        const status = form.querySelector('[role=status]'); status.textContent = `${error.message} Deine Termine bleiben erhalten.`;
        if (error.status === 409) {
          const reload = document.createElement('button'); reload.type = 'button'; reload.textContent = 'Aktuelle Einheit laden';
          reload.onclick = async () => {
            try {
              const data = await api('/api/units'); const latest = data.units.find(candidate => candidate.path === unit.path);
              if (!latest) throw new Error('Einheit konnte nicht geladen werden.');
              const edits = payloadOf(draft).updates;
              const mapped = [], occupied = new Set();
              for (const edit of edits) {
                const original = draft.unit.data.einsatz[edit.index];
                const index = latest.data.einsatz.findIndex((use, index) => !occupied.has(index) && JSON.stringify(use) === JSON.stringify(original));
                if (index < 0) {
                  status.textContent = 'Ein bearbeiteter Termin wurde ebenfalls geändert. Bitte beide Fassungen im vollständigen Editor prüfen. Deine Eingaben bleiben erhalten.';
                  return;
                }
                occupied.add(index); mapped.push({ index, datum: edit.datum });
              }
              draft.unit = latest; draft.existing = existingDateRows(latest);
              for (const edit of mapped) {
                const row = draft.existing.find(row => row.index === edit.index);
                if (row) row.datum = edit.datum; else draft.existing.push(edit);
              }
              persistWorkspace(); renderQuickDates(latest, card);
            } catch (error) { status.textContent = error.message; }
          };
          status.append(reload);
        }
      } finally {
        savingDates.delete(unit.path);
        const current = [...getSection().querySelectorAll('.unit-card')].find(card => card.dataset.unitPath === unit.path);
        if (current && quickDates.has(unit.path)) {
          const pending = payloadOf(quickDates.get(unit.path));
          const button = current.querySelector('.unit-quick-dates [type=submit]');
          if (button) button.disabled = !pending.dates.length && !pending.updates.length;
        }
      }
    };
    container.append(form);
  }
  return { renderQuickDates };
}
