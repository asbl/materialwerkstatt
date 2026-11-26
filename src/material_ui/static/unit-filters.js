import { escapeHtml as esc } from './ui-utils.js';
import { unitMatchesTags } from './unit-data.js';

// Filterleiste der Einheitenansicht (Schuljahr, Fach, Lerngruppe, Termin, Bearbeitungsstatus, Tags).
// Reine Funktionen ohne Zugriff auf Zustand von units.js; hier ist auch der Ort für weitere Filter.

const COMPLETION_VALUES = ['open', 'done'];

// Gespeicherten Statusfilter prüfen (beschädigte Werte werden zu „Alle“).
export const normalizeCompletion = value => (COMPLETION_VALUES.includes(value) ? value : '');

export const filtersActive = ({ schoolYear, tagFilter, completionFilter, subjectFilter, groupFilter, onlyUndated }) => Boolean(schoolYear || tagFilter || completionFilter || subjectFilter || groupFilter || onlyUndated);

// Passt die Einheit zum Statusfilter? Leerer Filter lässt alles durch.
export const matchesCompletion = (unit, completionFilter) => !completionFilter || (unit.data.fertig === true) === (completionFilter === 'done');

// Lerngruppen folgen derselben automatischen Schuljahreszuordnung wie der Kalender.
const schoolYearOf = date => {
  const first = Number(date.slice(0, 4)) - (date.slice(5, 7) < '08' ? 1 : 0);
  return `${first}/${first + 1}`;
};
export function unitGroups(unit, defaults = [], schoolYear = '') {
  const uses = unit.data.einsatz || [];
  const rows = defaults.filter(row => `klasse-${row.grade}` === unit.klasse);
  return uses.length ? uses.filter(use => !schoolYear || schoolYearOf(use.datum) === schoolYear)
    .map(use => use.lerngruppe || rows.find(row => row.year === schoolYearOf(use.datum))?.group).filter(Boolean)
    : rows.filter(row => !schoolYear || row.year === schoolYear).map(row => row.group);
}
const groupKey = value => value.toUpperCase().replaceAll(' ', '').replace(/^0+(?=[1-9])/, '');
export const passesFilters = (unit, { completionFilter, tagFilter, subjectFilter, groupFilter, onlyUndated, groupDefaults = [], schoolYear = '' }) =>
  matchesCompletion(unit, completionFilter) && unitMatchesTags(unit, tagFilter || '')
  && (!subjectFilter || unit.fach === subjectFilter)
  && (!groupFilter || unitGroups(unit, groupDefaults, schoolYear).some(group => groupKey(group) === groupKey(groupFilter)))
  && (!onlyUndated || !(unit.data.einsatz || []).length);

// Menü der Filterleiste als HTML; `years` und `tags` sind die wählbaren Werte.
export function filterMenuHtml({ years, tags, subjects = [], groups = [], schoolYear, tagFilter, completionFilter, subjectFilter, groupFilter, onlyUndated }) {
  const active = filtersActive({ schoolYear, tagFilter, completionFilter, subjectFilter, groupFilter, onlyUndated });
  return `<details class="unit-filters unit-menu${active ? ' is-active' : ''}"><summary>Filter${active ? ' · aktiv' : ''}</summary><div class="unit-menu-panel"><label>Schuljahr <select data-year><option value="">Alle Schuljahre</option>${years.map(value => `<option ${value === schoolYear ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select></label>
          <label>Fach<select data-subject-filter><option value="">Alle Fächer</option>${subjects.map(value => `<option value="${esc(value)}" ${value === subjectFilter ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select></label>
          <label>Lerngruppe<select data-group-filter><option value="">Alle Lerngruppen</option>${groups.map(value => `<option value="${esc(value)}" ${value === groupFilter ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select></label>
          <label><input type="checkbox" data-only-undated ${onlyUndated ? 'checked' : ''}> Nur ohne Termin</label>
          <label>Bearbeitungsstatus<select data-completion-filter><option value="">Alle</option><option value="open" ${completionFilter === 'open' ? 'selected' : ''}>In Bearbeitung</option><option value="done" ${completionFilter === 'done' ? 'selected' : ''}>Fertig</option></select></label>
          <label>Tags filtern<input data-tag-filter list="unit-tags" value="${esc(tagFilter)}" placeholder="z. B. vertretung, multiplikation"></label>
          <datalist id="unit-tags">${tags.map(tag => `<option value="${esc(tag)}"></option>`).join('')}</datalist></div></details>`;
}

// Bindet die Bedienelemente des Menüs; jeder Callback bekommt den neuen Wert.
export function bindFilterMenu(section, { onYear, onCompletion, onTags, onSubject, onGroup, onOnlyUndated }) {
  section.querySelector('[data-completion-filter]').onchange = event => onCompletion(event.target.value);
  section.querySelector('[data-tag-filter]').onchange = event => onTags(event.target.value);
  section.querySelector('[data-subject-filter]').onchange = event => onSubject(event.target.value);
  section.querySelector('[data-group-filter]').onchange = event => onGroup(event.target.value);
  section.querySelector('[data-only-undated]').onchange = event => onOnlyUndated(event.target.checked);
  section.querySelector('[data-year]').onchange = event => onYear(event.target.value);
}
