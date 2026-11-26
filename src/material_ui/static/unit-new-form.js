import { unitTypeSelect } from './unit-data.js';
import { escapeHtml as esc } from './ui-utils.js';

// Formular „Neue Lerneinheit“ in der Einheitenansicht.
// Eigenständiges Modul: Entwurf (getDraft/setDraft), Einheitenliste und alle Folgen des Anlegens
// (onCreated) kommen als Argumente; das Formular liest keinen Zustand von units.js.
export function createUnitNewForm({ api, getSection, getUnits, getDraft, setDraft, persistWorkspace, watchDetails,
  normalizeThemeValue, isDeletingTheme, openThemeDeleteDialog, onCreated }) {
  let creatingUnit = false;
  function renderNewUnitForm() {
    const container = getSection().querySelector('[data-new-unit-form]');
    container.replaceChildren();
    const draft = getDraft();
    if (!draft) return;
    const form = document.createElement('form');
    form.className = 'unit-create-form';
    form.innerHTML = `<strong>Neue Lerneinheit</strong>${unitTypeSelect(draft.typ)}
      <label>Thema<select name="thema" required></select></label>
      <div data-theme-new-wrap hidden><label>Neues Thema<input name="thema-new" placeholder="z. B. Potenzen"></label></div>
      <button type="button" data-theme-delete>Thema löschen…</button>
      <p class="muted" data-theme-scope></p>
      <label>Titel der Lerneinheit<input name="titel" required value="${esc(draft.titel)}"></label>
      <details data-create-context><summary>Weitere Angaben</summary><div class="grid"><label>Fach<input name="fach" required value="${esc(draft.fach)}"></label><label>Klasse<input name="klasse" required inputmode="numeric" value="${esc(draft.klasse)}"></label></div></details>
      <label>Erstes Datum (optional)<input type="date" name="datum" value="${esc(draft.datum)}"></label>
      <label class="unit-toggle"><input type="checkbox" name="datumsneutral" ${draft.datumsneutral ? 'checked' : ''}> Datumsneutral / wiederkehrend</label>
      <button type="submit" ${creatingUnit ? 'disabled' : ''}>Lerneinheit anlegen</button><button type="button" data-cancel-new-unit>Abbrechen</button><p role="status"></p>`;
    const NEW_THEME = '__new__';
    const themeSelect = form.elements['thema'];
    function matchingThemes() {
      const klasseMatch = /^(?:klasse-)?(\d{1,2})$/.exec(form.elements.klasse.value.trim());
      const targetFach = form.elements.fach.value.trim().toLocaleLowerCase('de');
      if (!klasseMatch || !targetFach) return [];
      const targetKlasse = `klasse-${klasseMatch[1].padStart(2, '0')}`;
      return [...new Set(getUnits().filter(unit => unit.klasse === targetKlasse && unit.fach.toLocaleLowerCase('de') === targetFach).map(unit => unit.data.thema))].sort((a, b) => a.localeCompare(b, 'de'));
    }
    function toggleNewThemeField(show) {
      form.querySelector('[data-theme-new-wrap]').hidden = !show;
      form.elements['thema-new'].required = show;
    }
    function isNewThemeSelected() {
      return themeSelect.selectedOptions[0]?.dataset.new === '1';
    }
    function currentThemeValue() {
      return isNewThemeSelected() ? form.elements['thema-new'].value.trim() : themeSelect.value;
    }
    function updateThemeScopeHint() {
      const fach = form.elements.fach.value.trim();
      const klasse = form.elements.klasse.value.trim();
      form.querySelector('[data-theme-scope]').textContent = fach && klasse ? `Themen für Fach „${fach}“, Klasse ${klasse}` : '';
    }
    // Matching per normalisiertem Thema (nicht per String-Gleichheit), damit abweichende
    // Gross-/Kleinschreibung oder Whitespace kein Duplikat-Thema erzeugt; Auswahl erfolgt
    // über selectedIndex statt .value, weil ein echtes Thema zufällig "__new__" heißen könnte.
    function refreshThemeOptions(currentValue = currentThemeValue()) {
      const themes = matchingThemes();
      const normalizedCurrent = currentValue ? normalizeThemeValue(currentValue) : '';
      const matchedIndex = normalizedCurrent ? themes.findIndex(theme => normalizeThemeValue(theme) === normalizedCurrent) : -1;
      const useNew = matchedIndex === -1;
      themeSelect.replaceChildren(...themes.map(theme => {
        const option = document.createElement('option');
        option.value = theme; option.textContent = theme;
        return option;
      }));
      const newOption = document.createElement('option');
      newOption.value = NEW_THEME; newOption.textContent = '+ Neues Thema…'; newOption.dataset.new = '1';
      themeSelect.append(newOption);
      themeSelect.selectedIndex = useNew ? themes.length : matchedIndex;
      toggleNewThemeField(useNew);
      if (useNew) form.elements['thema-new'].value = currentValue || '';
      updateThemeScopeHint();
    }
    refreshThemeOptions(draft.thema);
    themeSelect.addEventListener('change', () => {
      const isNew = isNewThemeSelected();
      toggleNewThemeField(isNew);
      if (isNew) form.elements['thema-new'].focus();
      else form.elements['thema-new'].value = '';
    });
    form.elements.fach.addEventListener('input', () => refreshThemeOptions());
    form.elements.klasse.addEventListener('input', () => refreshThemeOptions());
    form.querySelector('[data-theme-delete]').onclick = () => {
      if (isDeletingTheme()) return;
      openThemeDeleteDialog({ fach: form.elements.fach.value.trim(), klasse: form.elements.klasse.value.trim(),
        thema: currentThemeValue() });
    };
    function readForm() {
      return { lerngruppe: getDraft().lerngruppe || '', thema: currentThemeValue(),
        ...Object.fromEntries(['titel', 'fach', 'klasse', 'datum', 'typ'].map(key => [key, form.elements[key].value.trim()]).concat([['datumsneutral', form.elements.datumsneutral.checked]])) };
    }
    form.addEventListener('input', () => { setDraft(readForm()); persistWorkspace(); });
    form.addEventListener('change', () => { setDraft(readForm()); persistWorkspace(); });
    form.querySelector('[data-cancel-new-unit]').onclick = () => {
      if (creatingUnit) return;
      setDraft(null); persistWorkspace(); container.replaceChildren();
    };
    form.onsubmit = async event => {
      event.preventDefault();
      if (creatingUnit) return;
      const submitted = readForm();
      setDraft(submitted);
      creatingUnit = true; form.querySelector('[type=submit]').disabled = true;
      form.querySelector('[role=status]').textContent = 'Lerneinheit wird angelegt…';
      try {
        const created = await api('/api/units/new', { method: 'POST', body: JSON.stringify(submitted) });
        setDraft(null);
        onCreated(created);
      } catch (error) { form.querySelector('[role=status]').textContent = error.message; }
      finally { creatingUnit = false; form.querySelector('[type=submit]').disabled = false; }
    };
    container.append(form);
    watchDetails(form.querySelector('[data-create-context]'), 'create-context');
    form.addEventListener('invalid', event => { const details = event.target.closest('[data-create-context]'); if (details) details.open = true; }, true);
  }
  return { renderNewUnitForm };
}
