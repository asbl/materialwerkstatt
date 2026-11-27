import { escapeHtml as esc, normalizeSearch } from "./ui-utils.js";
import { mergeUnitData, unitTypeSelect } from "./unit-data.js";

export function createUnitEditor({ api, drafts, saving, persistDrafts, groupSelect, labelDate,
  getSection, updateUnits, load, themeOptions, onDeleteTheme }) {
  function edit(unit, card) {
    const editor = card.querySelector('[data-editor]');
    if (editor.childElementCount) return;
    const draft = drafts.get(unit.path) || { unit: structuredClone(unit), data: structuredClone(unit.data) };
    const form = document.createElement('form');
    const initial = draft.data;
    form.innerHTML = `<label>Thema<select name="thema" required></select></label>
      <div data-theme-new-wrap hidden><label>Neues Thema<input name="thema-new" placeholder="z. B. Potenzen"></label></div>
      <button type="button" data-theme-delete>Thema löschen…</button>
      <label>Titel der Lerneinheit<input name="titel" required value="${esc(initial.titel)}"></label>
      ${unitTypeSelect(initial.typ)}
      <label>Kurzbeschreibung<textarea name="kurzbeschreibung">${esc(initial.kurzbeschreibung)}</textarea></label>
      <label>Tags (kommagetrennt)<input name="tags" list="unit-tags" value="${esc((initial.tags || []).join(', '))}"></label>
      <label class="unit-toggle"><input type="checkbox" name="datumsneutral" ${initial.datumsneutral ? 'checked' : ''}> Datumsneutral / wiederkehrend</label>
      <label class="unit-toggle"><input type="checkbox" name="fertig" ${initial.fertig ? 'checked' : ''}> Fertig – Bearbeitung abgeschlossen</label>
      <div data-uses></div><button type="button" data-add>Einsatz hinzufügen</button>
      <button type="submit">Speichern</button><button type="button" data-cancel>Abbrechen</button>
      <button type="button" data-merge hidden>Mit aktueller Fassung zusammenführen</button><div data-conflicts></div><p role="status"></p>`;
    const NEW_THEME = '__new__';
    const themeSelect = form.elements['thema'];
    const themeWrap = form.querySelector('[data-theme-new-wrap]');
    const normalizeThema = value => normalizeSearch(value).trim().replace(/\s+/g, ' ');
    function isNewTheme() { return themeSelect.selectedOptions[0]?.dataset.new === '1'; }
    function currentThemaValue() { return isNewTheme() ? form.elements['thema-new'].value.trim() : themeSelect.value; }
    function refreshThemeOptions(currentValue) {
      const list = [...new Set(themeOptions ? themeOptions(unit) : [])].sort((a, b) => a.localeCompare(b, 'de'));
      const normalized = currentValue ? normalizeThema(currentValue) : '';
      const matchedIndex = normalized ? list.findIndex(theme => normalizeThema(theme) === normalized) : -1;
      themeSelect.replaceChildren(...list.map(theme => {
        const option = document.createElement('option');
        option.value = theme; option.textContent = theme;
        return option;
      }));
      const newOption = document.createElement('option');
      newOption.value = NEW_THEME; newOption.textContent = '+ Neues Thema…'; newOption.dataset.new = '1';
      themeSelect.append(newOption);
      const isNew = matchedIndex === -1;
      themeSelect.selectedIndex = isNew ? list.length : matchedIndex;
      themeWrap.hidden = !isNew;
      form.elements['thema-new'].required = isNew;
      if (isNew) form.elements['thema-new'].value = currentValue || '';
    }
    refreshThemeOptions(initial.thema);
    themeSelect.addEventListener('change', () => {
      const isNew = isNewTheme();
      themeWrap.hidden = !isNew;
      form.elements['thema-new'].required = isNew;
      if (isNew) form.elements['thema-new'].focus();
      else form.elements['thema-new'].value = '';
    });
    form.querySelector('[data-theme-delete]').onclick = () => {
      if (saving.has(unit.path)) return;
      onDeleteTheme?.({ fach: unit.fach, klasse: unit.klasse, thema: currentThemaValue() });
    };
    const rows = form.querySelector('[data-uses]');
    function add(use = {}) {
      const row = document.createElement('fieldset');
      row.innerHTML = `<legend>Einsatz</legend><label>Datum<input type="date" name="datum" required value="${esc(use.datum || '')}"></label>
        <label>Lerngruppe${groupSelect(use.lerngruppe || '')}</label>
        <label>Material<select name="material"><option value="">Gesamte Einheit</option>${[...new Set([...unit.materials, ...(use.material ? [use.material] : [])])].map(material => {
          const entry = unit.materialEntries?.find(item => item.path === material);
          const label = entry?.sourcePath ? `${entry.title} (verknüpft)` : material;
          return `<option value="${esc(material)}" ${material === use.material ? 'selected' : ''}>${esc(label)}</option>`;
        }).join('')}</select></label>
        <label>Notiz<input name="notiz" value="${esc(use.notiz || '')}"></label><button type="button">Einsatz entfernen</button>`;
      row.querySelector('button').onclick = () => { row.remove(); remember(); };
      rows.append(row);
    }
    function formData() {
      const data = { ...draft.data };
      data.thema = currentThemaValue();
      for (const key of ['titel', 'kurzbeschreibung', 'typ']) data[key] = form.elements[key].value;
      data.tags = [...new Set(form.elements.tags.value.split(',').map(tag => tag.trim()).filter(Boolean))];
      data.fertig = form.elements.fertig.checked;
      data.datumsneutral = form.elements.datumsneutral.checked;
      data.einsatz = [...rows.children].map(row => Object.fromEntries(['datum', 'lerngruppe', 'material', 'notiz'].map(key => [key, row.querySelector(`[name=${key}]`).value])));
      return data;
    }
    function remember() {
      draft.data = formData(); drafts.set(unit.path, draft); persistDrafts();
    }
    (initial.einsatz || []).forEach(add);
    form.addEventListener('input', remember);
    form.addEventListener('change', remember);
    form.querySelector('[data-add]').onclick = () => { add(); remember(); };
    form.querySelector('[data-cancel]').onclick = () => {
      if (drafts.has(unit.path) && !window.confirm('Ungespeicherte Änderungen dieser Einheit verwerfen?')) return;
      drafts.delete(unit.path); persistDrafts(); editor.replaceChildren();
    };
    if (drafts.has(unit.path)) form.querySelector('[role=status]').textContent = 'Ungespeicherter Entwurf bleibt beim Ansichtswechsel erhalten.';
    const mergeButton = form.querySelector('[data-merge]');
    mergeButton.hidden = unit.revision === draft.unit.revision;
    mergeButton.onclick = async () => {
      mergeButton.disabled = true;
      const status = form.querySelector('[role=status]');
      try {
        const payload = await api('/api/units');
        const latest = payload.units.find(candidate => candidate.path === unit.path);
        if (!latest) throw new Error('Die aktuelle Einheit konnte nicht geladen werden. Bitte den Ordner und die Zusammenfassung prüfen.');
        remember();
        const local = structuredClone(draft.data);
        const { data, conflicts } = mergeUnitData(draft.unit.data, local, latest.data);
        function applyMerge() {
          draft.unit = structuredClone(latest);
          draft.data = data;
          drafts.set(unit.path, draft); persistDrafts();
          updateUnits(payload.units);
          const current = [...getSection().querySelectorAll('.unit-card')].find(card => card.dataset.unitPath === unit.path);
          if (current) current.querySelector('[role=status]').textContent = 'Fassungen zusammengeführt. Bitte prüfen und speichern.';
        }
        const panel = form.querySelector('[data-conflicts]');
        panel.replaceChildren();
        if (!conflicts.length) { applyMerge(); return; }
        status.textContent = 'Beide Fassungen haben dieselben Felder geändert. Bitte je Feld eine Fassung wählen; weitere Änderungen bleiben erhalten.';
        const comparisonText = (key, value) => {
          if (value === undefined) return '(entfernt)';
          if (key === 'einsatz' && Array.isArray(value)) {
            return value.length ? value.map(use => [
              use.datum ? labelDate(use.datum) : 'Ohne Datum',
              use.lerngruppe, use.material || 'Gesamte Einheit', use.notiz,
            ].filter(Boolean).join(' · ')).join('\n') : 'Keine Einsätze';
          }
          if (typeof value === 'boolean') return value ? 'Ja' : 'Nein';
          return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
        };
        for (const [index, key] of conflicts.entries()) {
          const field = document.createElement('fieldset');
          const label = { typ: 'Typ', fertig: 'Fertig', tags: 'Tags', titel: 'Titel', thema: 'Thema', kurzbeschreibung: 'Kurzbeschreibung', einsatz: 'Einsätze', datumsneutral: 'Datumsneutral / wiederkehrend' }[key] || key;
          field.innerHTML = `<legend>${esc(label)}</legend><p>Dein Entwurf</p><pre>${esc(comparisonText(key, local[key]))}</pre>
            <p>Aktuelle Datei</p><pre>${esc(comparisonText(key, latest.data[key]))}</pre>
            <label>Übernehmen<select data-choice="${index}"><option value="">Bitte wählen</option><option value="local">Deinen Entwurf</option><option value="remote">Aktuelle Datei</option></select></label>`;
          panel.append(field);
        }
        const apply = document.createElement('button');
        apply.type = 'button'; apply.textContent = 'Auswahl in Entwurf übernehmen';
        apply.dataset.applyMerge = '';
        apply.onclick = () => {
          const choices = [...panel.querySelectorAll('[data-choice]')];
          if (choices.some(choice => !choice.value)) { status.textContent = 'Bitte für jedes geänderte Feld eine Fassung wählen.'; return; }
          // Keep new form edits when the comparison has become stale.
          if (JSON.stringify(formData()) !== JSON.stringify(local)) {
            panel.replaceChildren(); status.textContent = 'Dein Entwurf wurde weiter bearbeitet. Bitte den Vergleich erneut starten.'; return;
          }
          for (const [index, key] of conflicts.entries()) data[key] = structuredClone(choices[index].value === 'local' ? local[key] : latest.data[key]);
          applyMerge();
        };
        panel.append(apply);
      } catch (error) { status.textContent = `${error.message} Dein Entwurf bleibt erhalten.`; }
      finally { mergeButton.disabled = false; }
    };
    form.querySelector('[type=submit]').disabled = saving.has(unit.path);
    form.onsubmit = async event => {
      event.preventDefault();
      if (saving.has(unit.path)) return;
      remember();
      const submitted = structuredClone(draft.data);
      const button = form.querySelector('[type=submit]'); button.disabled = true;
      saving.add(unit.path);
      try {
        const saved = await api('/api/units', { method: 'POST', body: JSON.stringify({ path: unit.path, revision: draft.unit.revision, data: submitted }) });
        if (JSON.stringify(drafts.get(unit.path)?.data) === JSON.stringify(submitted)) drafts.delete(unit.path);
        else if (drafts.has(unit.path)) drafts.get(unit.path).unit.revision = saved.revision;
        persistDrafts();
        await load();
      } catch (error) {
        form.querySelector('[role=status]').textContent = `${error.message} Dein Entwurf bleibt erhalten.`;
        if (error.status === 409) mergeButton.hidden = false;
      }
      finally {
        saving.delete(unit.path); button.disabled = false;
        getSection().querySelectorAll('.unit-card').forEach(card => {
          if (card.dataset.unitPath === unit.path) { const submit = card.querySelector('[type=submit]'); if (submit) submit.disabled = false; }
        });
      }
    };
    editor.append(form);
  }
  return { edit };
}
