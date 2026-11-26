import { renderUnitPlanning, editPlanningMarker, clearUnitPlanningCache } from './unit-planning.js';
import { openAssignPicker, openMovePicker, bindUnitDrag } from './unit-assign.js';
import { startPointerDrag } from './pointer-drag.js';
import { escapeHtml as esc, materialIcon, pairMaterialEntries, materialDisplay, normalizeSearch } from './ui-utils.js';

export { mergeUnitData, unitMatchesTags } from "./unit-data.js";
import { createUnitEditor } from "./unit-editor.js";
import { createUnitDates } from './unit-dates.js';
import { createUnitNewForm } from './unit-new-form.js';
import { filterMenuHtml, bindFilterMenu, unitGroups, matchesCompletion, passesFilters, normalizeCompletion } from './unit-filters.js';

// Themen normalisieren (Gross-/Kleinschreibung, Whitespace), damit Dropdowns und
// Loeschdialog dasselbe Thema trotz abweichender Schreibweise wiedererkennen.
const normalizeThemeValue = value => normalizeSearch(value).trim().replace(/\s+/g, ' ');

export function registerUnitsView({ views, api, selectDocument, createWorksheet, createNote, deleteMaterial, openWorksheetNote = null, getDocumentPath = () => '', beforeMove = async () => true, onMoved = async () => {} }) {
  const unitActions = new Map(), actionSlots = new Map();
  function mountUnitAction(action, unit, host) {
    const slot = document.createElement('span'); slot.dataset.unitAction = action.id;
    // Slot zuerst einhaengen: Mounts koennen so die Einheiten-Karte im DOM finden.
    host.append(slot);
    try {
      if (action.matches && !action.matches(unit)) return;
      action.mount({ unit, container: slot });
    } catch (error) {
      slot.textContent = `Aktion nicht verfügbar: ${error.message}`;
    }
  }
  function renderUnitActions(unit, container) {
    const host = document.createElement('span');
    container.append(host); actionSlots.set(host, unit);
    for (const action of unitActions.values()) mountUnitAction(action, unit, host);
    const done = document.createElement('button');
    done.type = 'button';
    done.dataset.unitDone = '';
    done.textContent = unit.data.fertig ? '✓ Fertig' : 'Als fertig markieren';
    done.disabled = unit.data.fertig === true || saving.has(unit.path);
    done.addEventListener('click', async () => {
      if (saving.has(unit.path)) return;
      const status = section.querySelector('[data-status]');
      if (drafts.has(unit.path) || quickDates.has(unit.path)) {
        status.textContent = 'Bitte zuerst die offenen Änderungen der Einheit speichern.';
        return;
      }
      saving.add(unit.path); completionControls(unit.path, true);
      status.textContent = 'Fertig-Status wird gespeichert …';
      try {
        const saved = await api('/api/units', { method: 'POST', body: JSON.stringify({
          path: unit.path, revision: unit.revision, data: { ...unit.data, fertig: true },
        }) });
        saving.delete(unit.path);
        applyCompletion(saved);
      } catch (error) {
        status.textContent = error.message;
        completionControls(unit.path, false);
      } finally { saving.delete(unit.path); }
    });
    container.append(done);
  }
  // Arbeitsblätter und Präsentationen tragen einen eigenen Fertig-Status.
  const hasDoneToggle = entry => entry.worksheet === true || entry.presentation === true;
  function applyCompletion(saved) {
    const unit = units.find(item => item.path === saved.path);
    if (!unit) return;
    Object.assign(unit, saved);
    for (const entry of unit.materialEntries || []) {
      if (hasDoneToggle(entry)) entry.fertig = saved.data.arbeitsblaetter_fertig?.[entry.path] ?? saved.data.fertig === true;
    }
    for (const card of section.querySelectorAll('[data-unit-path]')) {
      if (card.dataset.unitPath !== unit.path) continue;
      const done = unit.data.fertig === true;
      const badge = card.querySelector('.unit-completion');
      if (badge) {
        badge.textContent = done ? 'Fertig' : 'In Bearbeitung';
        badge.classList.toggle('is-done', done);
      }
      for (const toggle of card.querySelectorAll('[data-worksheet-done]')) {
        toggle.checked = unit.materialEntries?.find(entry => entry.path === toggle.dataset.worksheetDone)?.fertig === true;
      }
      for (const button of card.querySelectorAll('[data-unit-done]')) button.textContent = done ? '✓ Fertig' : 'Als fertig markieren';
      if (!matchesCompletion({ data: { fertig: done } }, completionFilter)) card.remove();
    }
    completionControls(unit.path, false);
    section.querySelector('[data-status]').textContent = '';
  }
  function completionControls(path, disabled) {
    for (const card of section.querySelectorAll('[data-unit-path]')) {
      if (card.dataset.unitPath !== path) continue;
      for (const control of card.querySelectorAll('[data-worksheet-done], [data-unit-done]')) control.disabled = disabled || (control.hasAttribute('data-unit-done') && units.find(unit => unit.path === path)?.data.fertig === true);
    }
  }
  function registerAction(action) {
    if (!action?.id || typeof action.mount !== 'function' || unitActions.has(action.id)) throw new Error('Ungültige oder doppelte Einheitenaktion.');
    unitActions.set(action.id, action);
    for (const [host, unit] of actionSlots) {
      if (!host.isConnected) actionSlots.delete(host);
      else mountUnitAction(action, unit, host);
    }
    return () => {
      unitActions.delete(action.id);
      for (const host of actionSlots.keys()) for (const slot of [...host.children]) {
        if (slot.dataset.unitAction === action.id) slot.remove();
      }
    };
  }
  let groupDefaults = [];
  let section, units = [], schoolClass = '', schoolTerm = '', schoolYear = '', showUndated = false, tagFilter = '', completionFilter = '', subjectFilter = '', groupFilter = '', onlyUndated = false;
  let movingMaterial = false;
  const drafts = new Map();
  let draftKey = '';
  const saving = new Set();
  const justCreated = new Set();
  let newUnitDraft = null;
  let attachDraft = null, attaching = false;
  let themeDeleteDraft = null, deletingTheme = false;
  let pendingPlanning = null;
  let workspaceKey = '', active = false, skipCapture = true, scrollTimer;
  let selectedUnitPath = '', lastDocumentPath = '', pendingRevealPath = '';
  let navigationTarget = '';
  const expanded = new Map(), scrollPositions = new Map(), quickDates = new Map(), savingDates = new Set();
  function persistWorkspace() {
    if (!workspaceKey) return;
    try {
      sessionStorage.setItem(workspaceKey, JSON.stringify({ schoolClass, schoolTerm, schoolYear, showUndated, tagFilter, completionFilter, subjectFilter, groupFilter, onlyUndated,
        newUnitDraft, attachDraft, selectedUnitPath, lastDocumentPath, pendingRevealPath, expanded: [...expanded], scrollPositions: [...scrollPositions],
        quickDates: [...quickDates] }));
    } catch { /* In-memory drafts still survive view changes if storage is unavailable. */ }
  }
  function captureView() {
    if (!active || skipCapture || !section) return;
    for (const details of section.querySelectorAll('details[data-state-key]')) expanded.set(details.dataset.stateKey, details.open);
    if (section.dataset.positionKey) scrollPositions.set(section.dataset.positionKey, section.scrollTop);
  }
  function watchDetails(details, key, defaultOpen = false) {
    details.dataset.stateKey = key;
    details.open = expanded.get(key) ?? defaultOpen;
    details.addEventListener('toggle', () => {
      if (!details.isConnected) return;
      expanded.set(key, details.open); persistWorkspace();
    });
  }
  function bindMenu(selector) {
    const menu = section.querySelector(selector);
    menu.querySelectorAll('button').forEach(button => button.addEventListener('click', () => { menu.open = false; }));
  }
  function persistDrafts() {
    persistWorkspace();
    try { sessionStorage.setItem(draftKey, JSON.stringify([...drafts])); } catch { /* Memory drafts still survive view changes. */ }
  }
  function displayedUnits() {
    const merged = new Map(units.map(unit => [unit.path, unit]));
    for (const [path, draft] of [...drafts, ...quickDates]) if (!merged.has(path)) merged.set(path, draft.unit);
    return [...merged.values()];
  }
  const labelDate = value => value.split('-').reverse().join('.');
  const year = value => {
    const [y, m] = value.split('-').map(Number);
    return `${m >= 8 ? y : y - 1}/${m >= 8 ? y + 1 : y}`;
  };
  const currentYear = () => year(new Date().toLocaleDateString('sv-SE'));
  // Q1/Q3: August–January; Q2/Q4: February–July.
  const term = date => { const month = Number(date.slice(5, 7)); return month >= 2 && month <= 7 ? '2' : '1'; };
  function unitTerm(unit) {
    if (!['klasse-12', 'klasse-13'].includes(unit.klasse)) return '';
    const dates = (unit.data.einsatz || []).map(use => use.datum).sort();
    return term(dates.find(date => year(date) === (schoolYear || currentYear())) || dates[0]
      || new Date().toLocaleDateString('sv-SE'));
  }
  const uses = unit => (unit.data.einsatz || []).filter(use => (!schoolYear || year(use.datum) === schoolYear)
    && (!schoolTerm || term(use.datum) === schoolTerm));
  function classChoices() {
    const choices = new Map();
    for (const unit of displayedUnits()) {
      const grade = Number(unit.klasse.replace('klasse-', ''));
      const dates = (unit.data.einsatz || []).filter(use => year(use.datum) === (schoolYear || currentYear()));
      const editing = showUndated || drafts.has(unit.path) || quickDates.has(unit.path) || justCreated.has(unit.path) || pendingRevealPath === unit.path;
      if (!dates.length && !unit.data.datumsneutral && !editing) continue;
      const terms = grade >= 12 && grade <= 13 ? (editing || unit.data.datumsneutral ? ['1', '2'] : [...new Set(dates.map(use => term(use.datum)))]) : [''];
      for (const half of terms) {
        const label = grade === 11 ? 'E' : half ? `Q${(grade - 12) * 2 + Number(half)}` : String(grade);
        const key = `${unit.klasse}:${half}`;
        choices.set(key, { key, grade, schoolClass: unit.klasse, half, label });
      }
    }
    return [...choices.values()].sort((a, b) => a.grade - b.grade || a.half.localeCompare(b.half));
  }
  const dateSummary = unit => {
    const dates = [...new Set(uses(unit).map(use => use.datum))].sort();
    const multipleYears = new Set(dates.map(value => value.slice(0, 4))).size > 1;
    return dates.map(value => `<time datetime="${esc(value)}" title="${labelDate(value)}">${multipleYears ? labelDate(value) : labelDate(value).slice(0, 5)}</time>`).join(' · ')
      || (unit.data.datumsneutral ? 'wiederkehrend' : 'Ohne Datum');
  };
  const firstDate = unit => uses(unit).map(use => use.datum).sort()[0] || '9999';
  function typeIcon(type) {
    return `<svg class="icon" aria-hidden="true" focusable="false"><use href="/static/icons.svg#${type}"></use></svg>`;
  }
  function markSelection() {
    if (!section) return;
    const documentPath = getDocumentPath();
    for (const card of section.querySelectorAll('.unit-card')) {
      const selected = card.dataset.unitPath === selectedUnitPath;
      card.classList.toggle('unit-selected', selected);
      const summary = card.querySelector(':scope > summary');
      if (selected) summary.setAttribute('aria-current', 'location'); else summary.removeAttribute('aria-current');
      for (const link of card.querySelectorAll('.unit-material-link')) {
        if (selected && link.dataset.documentPath === documentPath) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      }
    }
  }
  function selectUnit(path, reveal = false) {
    selectedUnitPath = path; markSelection(); persistWorkspace();
    if (!active || !reveal) return;
    const card = [...section.querySelectorAll('.unit-card')].find(card => card.dataset.unitPath === path);
    if (!card) return;
    const topic = card.closest('.unit-topic'); if (topic) topic.open = true;
    card.open = true;
    card.querySelector(':scope > summary').scrollIntoView({ block: 'nearest' });
  }
  function unitForDocument(path) {
    const candidates = displayedUnits().filter(unit => path.startsWith(`${unit.path}/`)).sort((a, b) => b.path.length - a.path.length);
    return candidates.find(unit => section?.querySelector(`[data-unit-path="${CSS.escape(unit.path)}"]`)) || candidates[0];
  }
  function documentOpened(path) {
    const changed = path !== lastDocumentPath;
    lastDocumentPath = path;
    if (!path) { pendingRevealPath = ''; selectUnit(''); return; }
    if (!changed && displayedUnits().some(unit => unit.path === selectedUnitPath)) { markSelection(); return; }
    const owner = unitForDocument(path);
    if (!owner) return;
    const visibleCard = [...(section?.querySelectorAll('.unit-card') || [])]
      .find(card => card.dataset.unitPath === owner.path);
    if (visibleCard) {
      const reveal = selectedUnitPath !== owner.path || !visibleCard.open;
      pendingRevealPath = active ? '' : owner.path;
      selectUnit(owner.path, reveal);
      return;
    }
    selectedUnitPath = owner.path;
    if (changed) {
      pendingRevealPath = owner.path;
      schoolClass = owner.klasse; schoolTerm = unitTerm(owner);
      if (schoolYear && !uses(owner).length && !owner.data.datumsneutral) schoolYear = '';
      if (!passesFilters(owner, { tagFilter, completionFilter: '' })) tagFilter = '';
      if (!matchesCompletion(owner, completionFilter)) completionFilter = '';
      if (subjectFilter && owner.fach !== subjectFilter) subjectFilter = '';
      if (!passesFilters(owner, { groupFilter, onlyUndated, groupDefaults, schoolYear })) { groupFilter = ''; onlyUndated = false; }
      if (active) { render(); pendingRevealPath = ''; }
    }
    selectUnit(owner.path, changed);
  }
  function existingDateRows(unit) {
    return (unit.data.einsatz || []).map((use, index) => ({ index, datum: use.datum }))
      .filter(row => (!schoolYear || year(row.datum) === schoolYear) && (!schoolTerm || term(row.datum) === schoolTerm));
  }
  async function moveMaterial(material, unit) {
    if (movingMaterial || material.path === `${unit.path}/${material.path.split('/').pop()}`) return;
    movingMaterial = true;
    try {
      if (drafts.has(material.unit) || drafts.has(unit.path) || quickDates.has(material.unit) || quickDates.has(unit.path))
        throw new Error('Bitte zuerst die Änderungen der beteiligten Einheiten speichern.');
      if (!(await beforeMove(material.path))) return;
      const result = await api('/api/file/move', { method: 'POST', body: JSON.stringify({ path: material.path, destination: unit.path }) });
      expanded.set(`unit:${unit.path}`, true);
      await onMoved(material.path, result);
      await load(); selectUnit(unit.path, true);
      section.querySelector('[data-status]').textContent = `Material nach „${unit.data.titel}“ verschoben.`;
    } catch (error) { section.querySelector('[data-status]').textContent = error.message; }
    finally { movingMaterial = false; }
  }
  // Ein delegiertes Handlerpaar fuer alle Material-Links statt eigener Listener pro Link;
  // section bleibt bei Rebuilds erhalten, die Karten darunter nicht.
  let suppressMaterialClick = false;
  function bindMaterialDelegation() {
    section.addEventListener('pointerdown', event => {
      const anchor = event.target.closest('a.unit-material-link');
      if (!anchor || event.button !== 0 || movingMaterial || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const unitPath = anchor.closest('.unit-card')?.dataset.unitPath;
      const clearTargets = () => section.querySelectorAll('.unit-drop-target').forEach(card => card.classList.remove('unit-drop-target'));
      const targetAt = event => document.elementFromPoint(event.clientX, event.clientY)?.closest('.unit-card');
      // Die Geste gehört ab hier uns, bevor der Browser Link-/Bild-Ziehen oder Textauswahl starten kann.
      startPointerDrag({
        event, handle: anchor,
        onStart: () => { suppressMaterialClick = true; anchor.classList.add('unit-material-dragging'); },
        onMove: moveEvent => {
          clearTargets();
          const card = targetAt(moveEvent);
          if (card && card.dataset.unitPath !== unitPath) card.classList.add('unit-drop-target');
        },
        onDrop: upEvent => {
          const target = targetAt(upEvent);
          const destination = units.find(item => item.path === target?.dataset.unitPath);
          if (destination && destination.path !== unitPath) moveMaterial({ path: anchor.dataset.documentPath, unit: unitPath }, destination);
        },
        onEnd: () => {
          anchor.classList.remove('unit-material-dragging'); clearTargets();
          setTimeout(() => { suppressMaterialClick = false; }, 0);
        },
      });
    });
    section.addEventListener('dragstart', event => {
      if (event.target.closest('a.unit-material-link')) event.preventDefault();
    });
    section.addEventListener('click', async event => {
      const anchor = event.target.closest('a.unit-material-link');
      if (!anchor) return;
      if (suppressMaterialClick) { event.preventDefault(); return; }
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      const path = anchor.dataset.documentPath;
      await selectDocument(path);
      const unitPath = anchor.closest('.unit-card')?.dataset.unitPath;
      if (getDocumentPath() === path && unitPath) selectUnit(unitPath);
    });
  }
  // Tags und Notizen lassen sich ohne den großen Editor direkt auf der Karte bearbeiten:
  // Ein dezenter Stift öffnet ein Inline-Formular, das über dieselbe Speicherroute
  // schreibt wie das Bearbeitungsformular. Die Stift-Klicks laufen delegiert über die
  // Sicht, damit der Stift nach dem Abbrechen einer Eingabe erneut wirkt, ohne dass
  // Listener nach dem Wiedereinsetzen neu gebunden werden müssen.
  function bindInlineEditDelegation() {
    section.addEventListener('click', event => {
      const button = event.target.closest('[data-edit-tags], [data-edit-notes]');
      if (!button || event.button !== 0) return;
      const card = button.closest('.unit-card');
      const unit = units.find(candidate => candidate.path === card?.dataset.unitPath);
      if (!unit) return;
      // Der Notizen-Stift sitzt im summary; ohne preventDefault wuerde das
      // Auf- und Zuklappen der Notizen statt der Bearbeitung ausgeloest.
      event.preventDefault();
      event.stopPropagation();
      if (saving.has(unit.path)) return;
      if (drafts.has(unit.path) || quickDates.has(unit.path)) {
        section.querySelector('[data-status]').textContent = 'Bitte zuerst die offenen Änderungen der Einheit speichern.';
        return;
      }
      if (button.matches('[data-edit-notes]')) editNotesInline(unit, card);
      else editTagsInline(unit, card);
    });
  }
  const parseTags = value => [...new Set(value.split(',').map(tag => tag.trim()).filter(Boolean))];
  function discardInline(unchanged, restore) {
    // Unveränderte Eingaben verschwinden ohne Nachfrage, echte Änderungen nur nach Rückfrage.
    if (!unchanged() && !window.confirm('Ungespeicherte Änderung verwerfen?')) return;
    restore();
  }
  async function saveInline(unit, data, form) {
    const status = form.querySelector('[role=status]');
    const submit = form.querySelector('[type=submit]');
    const cancel = form.querySelector('[data-inline-cancel]');
    submit.disabled = true;
    cancel.disabled = true;
    saving.add(unit.path);
    try {
      await api('/api/units', { method: 'POST', body: JSON.stringify({ path: unit.path, revision: unit.revision, data }) });
      await load();
    } catch (error) {
      submit.disabled = false;
      cancel.disabled = false;
      status.textContent = `${error.message} Deine Eingabe bleibt geöffnet.`;
    } finally {
      saving.delete(unit.path);
    }
  }
  function editTagsInline(unit, card) {
    const row = card.querySelector('[data-tags-row]');
    if (!row || row.querySelector('form')) return;
    const previousHtml = row.innerHTML;
    const restore = () => {
      row.innerHTML = previousHtml;
      row.querySelector('[data-edit-tags]')?.focus();
    };
    const form = document.createElement('form');
    form.className = 'unit-inline-form unit-tags-form';
    form.innerHTML = `<input name="tags" list="unit-tags" value="${esc((unit.data.tags || []).join(', '))}" aria-label="Tags (kommagetrennt)" placeholder="z. B. vertretung, multiplikation">
      <button type="submit" class="unit-edit">Speichern</button><button type="button" class="unit-edit" data-inline-cancel>Abbrechen</button><span role="status" aria-live="polite"></span>`;
    const input = form.elements.tags;
    const unchanged = () => JSON.stringify(parseTags(input.value)) === JSON.stringify(unit.data.tags || []);
    input.addEventListener('keydown', event => { if (event.key === 'Escape') discardInline(unchanged, restore); });
    form.querySelector('[data-inline-cancel]').onclick = () => discardInline(unchanged, restore);
    form.onsubmit = event => { event.preventDefault(); saveInline(unit, { ...unit.data, tags: parseTags(input.value) }, form); };
    row.replaceChildren(form);
    input.focus();
  }
  function editNotesInline(unit, card) {
    const notes = card.querySelector('.unit-notes');
    if (!notes || notes.querySelector('form')) return;
    const text = notes.querySelector('[data-notes-text]');
    if (!text) return;
    notes.open = true;
    const restore = () => {
      form.replaceWith(text);
      notes.querySelector('[data-edit-notes]')?.focus();
    };
    const form = document.createElement('form');
    form.className = 'unit-inline-form';
    form.innerHTML = `<textarea name="kurzbeschreibung" aria-label="Notizen bearbeiten">${esc(unit.data.kurzbeschreibung)}</textarea>
      <button type="submit" class="unit-edit">Speichern</button><button type="button" class="unit-edit" data-inline-cancel>Abbrechen</button><span role="status" aria-live="polite"></span>`;
    const input = form.elements.kurzbeschreibung;
    const unchanged = () => input.value === (unit.data.kurzbeschreibung || '');
    input.addEventListener('keydown', event => { if (event.key === 'Escape') discardInline(unchanged, restore); });
    form.querySelector('[data-inline-cancel]').onclick = () => discardInline(unchanged, restore);
    form.onsubmit = event => { event.preventDefault(); saveInline(unit, { ...unit.data, kurzbeschreibung: input.value }, form); };
    text.replaceWith(form);
    input.focus();
  }
  function renderMaterials(unit, list) {
    const entries = unit.materialEntries || unit.materials.map(path => ({ path, title: path }));
    function link(entry, pairedKind = null) {
      const { type, kind: fullType, title: label } = materialDisplay(entry);
      const anchor = document.createElement('a');
      const path = `${unit.path}/${entry.path}`;
      anchor.dataset.documentPath = path;
      anchor.draggable = false;
      anchor.href = `?path=${encodeURIComponent(path)}`;
      anchor.className = pairedKind ? `unit-material-link unit-${pairedKind}-link` : 'unit-material-link';
      anchor.title = `${fullType}: ${label}\n${entry.path}`;
      anchor.setAttribute('aria-label', `${fullType}: ${label}`);
      const heading = type === 'mini-worksheet' ? 'Mini-Arbeitsblatt' : fullType;
      // Der Titel bleibt immer sichtbar (auch wenn er dem Einheitentitel gleicht);
      // nur wenn er nichts ueber den Typ hinaus sagt, entfaellt die zweite Zeile.
      const showTitle = label && normalizeSearch(label).trim() !== normalizeSearch(heading).trim();
      const pairedLabels = { solution: 'Lösung', note: 'Notizen' };
      anchor.innerHTML = typeIcon(type) + (pairedKind
        ? `<span class="unit-${pairedKind}-label">${pairedLabels[pairedKind]}</span>`
        : `<span class="unit-material-text">${showTitle ? `<span class="unit-material-title">${esc(label)}</span>` : ''}<span class="unit-material-kind">${esc(heading)}</span></span>`);
      return anchor;
    }
    function deleteButton(entry) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'icon-button unit-material-delete';
      button.dataset.deleteMaterial = entry.path;
      button.title = 'Datei löschen';
      button.setAttribute('aria-label', `${entry.title || entry.path} löschen`);
      button.innerHTML = typeIcon('trash');
      button.onclick = () => {
        if (saving.has(unit.path) || drafts.has(unit.path) || quickDates.has(unit.path)) {
          section.querySelector('[data-status]').textContent = 'Bitte zuerst die offenen Änderungen der Einheit speichern.';
          return;
        }
        deleteMaterial(`${unit.path}/${entry.path}`);
      };
      return button;
    }
    function noteButton(entry) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'unit-edit unit-material-notes unit-note-action';
      button.dataset.worksheetNote = `${unit.path}/${entry.path}`;
      button.title = 'Neue Notiz anlegen';
      button.setAttribute('aria-label', `Neue Notiz zu ${entry.title || entry.path} anlegen`);
      button.innerHTML = `${typeIcon('plus')}<span>Notiz</span>`;
      button.onclick = () => openWorksheetNote(`${unit.path}/${entry.path}`);
      return button;
    }
    for (const { entry, solutions, notes } of pairMaterialEntries(entries)) {
      const row = document.createElement('li');
      row.className = 'unit-material-row';
      row.append(link(entry));
      if (hasDoneToggle(entry)) {
        const label = document.createElement('label');
        label.className = 'unit-toggle';
        const toggle = document.createElement('input'); toggle.type = 'checkbox';
        toggle.checked = entry.fertig === true;
        toggle.disabled = saving.has(unit.path);
        toggle.dataset.worksheetDone = entry.path;
        toggle.setAttribute('aria-label', `${entry.title} fertig`);
        label.append(toggle, ' Fertig'); row.append(label);
        toggle.onchange = async () => {
          const status = section.querySelector('[data-status]');
          if (saving.has(unit.path) || drafts.has(unit.path) || quickDates.has(unit.path)) {
            toggle.checked = entry.fertig === true;
            status.textContent = 'Bitte zuerst die offenen Änderungen der Einheit speichern.';
            return;
          }
          saving.add(unit.path); completionControls(unit.path, true);
          status.textContent = 'Fertig-Status wird gespeichert …';
          try {
            const states = Object.fromEntries(entries.filter(hasDoneToggle).map(item => [item.path, item.fertig === true]));
            states[entry.path] = toggle.checked;
            const saved = await api('/api/units', { method: 'POST', body: JSON.stringify({
              path: unit.path, revision: unit.revision,
              data: { ...unit.data, arbeitsblaetter_fertig: states },
            }) });
            saving.delete(unit.path); applyCompletion(saved);
          } catch (error) {
            toggle.checked = entry.fertig === true; status.textContent = error.message;
          } finally { saving.delete(unit.path); completionControls(unit.path, false); }
        };
      }

      if (deleteMaterial && !['solution', 'note'].includes(materialIcon(entry))) row.append(deleteButton(entry));
      // Lösung, Notizen und „+ Notiz“ bilden eine zweite, ruhige Zeile unter dem Material.
      const extras = document.createElement('div');
      extras.className = 'unit-material-extras';
      for (const solution of solutions) extras.append(link(solution, 'solution'));
      for (const note of notes) extras.append(link(note, 'note'));
      if (hasDoneToggle(entry) && entry.worksheet && !notes.length && openWorksheetNote) extras.append(noteButton(entry));
      if (extras.childElementCount) row.append(extras);
      list.append(row);
    }
    if (!entries.length) list.innerHTML = '<li class="unit-empty">Keine Materialien vorhanden.</li>';
  }
  function renderLernstand(unit, card) {
    const data = unit.data.lernstand;
    if (!data) return;
    const panel = document.createElement('details');
    panel.className = 'unit-lernstand';
    panel.innerHTML = '<summary>Lernstand & Förderung</summary>';
    watchDetails(panel, `${unit.path}:lernstand`, true);
    const status = unit.lernstandStatus || { fehler: [], hinweise: [] };
    for (const text of [...status.fehler, ...status.hinweise]) {
      const note = document.createElement('p'); note.textContent = text; panel.append(note);
    }
    const appendLink = (parent, item, key, label) => {
      if (!item[key]) return;
      const a = document.createElement('a');
      const path = `${unit.path}/${item[key]}`;
      a.href = `?path=${encodeURIComponent(path)}`; a.textContent = label;
      a.addEventListener('click', async event => {
        if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault(); dialog.close(); await selectDocument(path); selectUnit(unit.path);
      });
      parent.append(a, document.createTextNode(' '));
    };
    const tests = document.createElement('ul');
    for (const item of data.materialien.filter(item => item.rolle !== 'foerdermaterial')) {
      const row = document.createElement('li'); row.append(document.createTextNode(`${item.titel || item.id}: `));
      appendLink(row, item, 'quelle', 'Öffnen'); appendLink(row, item, 'loesung', 'Lösung'); tests.append(row);
    }
    panel.append(tests);
    const table = document.createElement('table');
    table.innerHTML = '<caption>Förderwege nach Kompetenz und Stufe</caption><thead><tr><th>Kompetenz</th><th>Stufe</th><th>Materialien</th></tr></thead>';
    const tbody = document.createElement('tbody');
    for (const comp of data.kompetenzen) for (const stage of comp.stufen) {
      const row = document.createElement('tr');
      for (const text of [comp.titel, stage.id.replace('stufe-', 'Stufe ')]) { const cell = document.createElement('td'); cell.textContent = text; row.append(cell); }
      row.title = stage.beschreibung;
      const cell = document.createElement('td');
      for (const item of data.materialien.filter(item => item.kompetenz === comp.id && item.stufe === stage.id)) {
        const line = document.createElement('div'); appendLink(line, item, 'quelle', item.titel || item.id);
        appendLink(line, item, 'loesung', 'Lösung'); cell.append(line);
      }
      row.append(cell); tbody.append(row);
    }
    table.append(tbody); panel.append(table);
    const editButton = document.createElement('button'); editButton.type = 'button'; editButton.textContent = 'Förderzuordnungen bearbeiten';
    const editor = document.createElement('div');
    editButton.onclick = () => {
      if (editor.childElementCount) { editor.replaceChildren(); return; }
      const draft = structuredClone(data);
      const form = document.createElement('form');
      for (const item of draft.materialien) {
        const field = document.createElement('fieldset');
        const legend = document.createElement('legend'); legend.textContent = item.titel || item.id; field.append(legend);
        const toggle = (key, label) => {
          const wrap = document.createElement('label'), input = document.createElement('input');
          input.type = 'checkbox'; input.checked = item[key] === true;
          input.onchange = () => { item[key] = input.checked; };
          wrap.append(input, document.createTextNode(label)); field.append(wrap);
        };
        toggle('online', 'Blatt veröffentlichen');
        if (item.loesung) toggle('loesung_online', 'Lösung zur Veröffentlichung freigeben');
        if (item.rolle === 'foerdermaterial') {
          const select = document.createElement('select'); select.setAttribute('aria-label', `Stufe: ${item.titel || item.id}`);
          const comp = draft.kompetenzen.find(comp => comp.id === item.kompetenz);
          for (const stage of comp.stufen) {
            const option = document.createElement('option'); option.value = stage.id; option.textContent = `${stage.id}: ${stage.beschreibung}`; select.append(option);
          }
          select.value = item.stufe; select.onchange = () => { item.stufe = select.value; }; field.append(select);
        }
        form.append(field);
      }
      for (const task of draft.aufgaben || []) {
        const field = document.createElement('fieldset');
        const legend = document.createElement('legend'); legend.textContent = `${task.diagnose} · Aufgabe ${task.nummer || task.id}`; field.append(legend);
        for (const item of draft.materialien.filter(item => item.rolle === 'foerdermaterial' && item.kompetenz === task.kompetenz)) {
          const wrap = document.createElement('label'), input = document.createElement('input'); input.type = 'checkbox'; input.checked = task.empfehlung.includes(item.id);
          input.onchange = () => { task.empfehlung = input.checked ? [...task.empfehlung, item.id] : task.empfehlung.filter(id => id !== item.id); };
          wrap.append(input, document.createTextNode(item.titel || item.id)); field.append(wrap);
        }
        form.append(field);
      }
      const save = document.createElement('button'); save.type = 'submit'; save.textContent = 'Förderzuordnungen speichern';
      const result = document.createElement('p'); result.setAttribute('role', 'status'); form.append(save, result);
      form.onsubmit = async event => {
        event.preventDefault(); save.disabled = true;
        try {
          if (drafts.has(unit.path)) throw new Error('Bitte zuerst die offenen Änderungen der Einheit speichern.');
          await api('/api/units', { method: 'POST', body: JSON.stringify({ path: unit.path, revision: unit.revision, data: { ...unit.data, lernstand: draft } }) });
          await load();
        } catch (error) { result.textContent = error.message; save.disabled = false; }
      };
      editor.append(form);
    };
    panel.append(editButton, editor);
    // The units navigation is narrow; open the complete matrix in a wide dialog.
    const dialog = document.createElement('dialog'); dialog.className = 'unit-lernstand-dialog';
    const heading = document.createElement('h2'); heading.textContent = `Lernstand & Förderung · ${unit.data.titel}`;
    const close = document.createElement('button'); close.type = 'button'; close.textContent = 'Schließen'; close.onclick = () => dialog.close();
    const toolbar = document.createElement('div'); toolbar.className = 'unit-lernstand-toolbar';
    toolbar.append(editButton);
    renderUnitActions(unit, toolbar);
    dialog.append(close, heading, toolbar);
    for (const child of [...panel.children].slice(1)) dialog.append(child);
    const open = document.createElement('button'); open.type = 'button'; open.textContent = 'Kompetenzen und Förderwege öffnen';
    open.onclick = () => dialog.showModal();
    panel.append(open, dialog);
    const materials = card.querySelector('[data-materials]');
    materials.hidden = true;
    materials.before(panel);
  }
  function groupSelect(value = '') {
    const groups = [...new Set([...groupDefaults.filter(row => `klasse-${row.grade}` === schoolClass).map(row => row.group),
      ...units.filter(unit => unit.klasse === schoolClass).flatMap(unit => (unit.data.einsatz || []).map(use => use.lerngruppe)), value].filter(Boolean))].sort();
    return `<select name="lerngruppe"><option value="">Automatisch nach Schuljahr</option>${groups.map(group => `<option value="${esc(group)}" ${group === value ? 'selected' : ''}>${esc(group)}</option>`).join('')}</select>`;
  }
  function render() {
    actionSlots.clear();
    captureView();
    const optionsOpen = section.querySelector('[data-options-menu]')?.open || false;
    const years = [...new Set(units.flatMap(unit => (unit.data.einsatz || []).map(use => year(use.datum))))].sort().reverse();
    if (schoolYear && !years.includes(schoolYear)) schoolYear = '';
    const classes = classChoices();
    const selectedClass = classes.find(choice => choice.schoolClass === schoolClass && choice.half === schoolTerm)
      || classes.find(choice => choice.schoolClass === schoolClass) || classes[0];
    schoolClass = selectedClass?.schoolClass || ''; schoolTerm = selectedClass?.half || '';
    section.innerHTML = `<h2 class="visually-hidden">Unterrichtseinheiten</h2>
      <div class="unit-class-badges" role="group" aria-label="Klasse">${classes.map(choice => `<button type="button" data-class="${esc(choice.schoolClass)}" data-term="${choice.half}" aria-label="${choice.label === 'E' ? 'Einführungsphase' : choice.half ? choice.label : `Klasse ${choice.label}`}" aria-pressed="${choice.key === selectedClass?.key}">${esc(choice.label)}</button>`).join('')}</div>
      <div class="unit-toolbar">
        ${filterMenuHtml({ years, schoolYear, tagFilter, completionFilter, subjectFilter, groupFilter, onlyUndated,
          subjects: [...new Set([...displayedUnits().map(unit => unit.fach), subjectFilter].filter(Boolean))].sort(),
          groups: [...new Set([...displayedUnits().filter(unit => unit.klasse === schoolClass).flatMap(unit => unitGroups(unit, groupDefaults, schoolYear)), groupFilter].filter(Boolean))].sort(),
          tags: [...new Set(displayedUnits().filter(unit => unit.klasse === schoolClass).flatMap(unit => unit.data.tags || []))].sort() })}
        <details class="unit-menu" data-add-menu><summary>Hinzufügen</summary>
          <div class="unit-menu-panel">
            <button type="button" class="unit-edit" data-new-unit>${typeIcon('plus')} Neue Lerneinheit</button>
            <button type="button" class="unit-edit" data-new-marker>Trenner hinzufügen</button>
            <button type="button" class="unit-edit" data-attach-folder>${typeIcon('folder')} Vorhandenen Ordner einbinden</button>
          </div>
        </details>
        <details class="unit-menu" data-options-menu><summary title="Weitere Optionen">Mehr</summary>
          <div class="unit-menu-panel">
            <button type="button" class="unit-edit" data-refresh>${typeIcon('refresh')} Aktualisieren</button>
          </div>
        </details>
        <label class="unit-toggle"><input type="checkbox" data-show-undated ${showUndated ? 'checked' : ''}> Undatierte Einheiten bearbeiten</label>
      </div>
      <div data-new-unit-form></div><div data-attach-form></div><div data-theme-delete-form></div><p data-status role="status"></p><div data-groups></div>`;
    watchDetails(section.querySelector('.unit-filters'), 'filters');
    const groups = new Map();
    for (const unit of displayedUnits().filter(unit => unit.klasse === schoolClass && passesFilters(unit, { completionFilter, tagFilter, subjectFilter, groupFilter, onlyUndated, groupDefaults, schoolYear }) && (uses(unit).length || unit.data.datumsneutral || (showUndated && !(unit.data.einsatz || []).length) || drafts.has(unit.path) || quickDates.has(unit.path) || (justCreated.has(unit.path) && !(unit.data.einsatz || []).length)))) {
      const topic = unit.data.datumsneutral ? '' : unit.data.thema.split('/').map(part => part.trim()).filter(Boolean).join(' / ');
      if (!groups.has(topic)) groups.set(topic, { entries: [], first: '9999' });
      const group = groups.get(topic);
      group.entries.push(unit);
      if (firstDate(unit) < group.first) group.first = firstDate(unit);
    }
    const container = section.querySelector('[data-groups]');
    // Reveal the chronological tree only once calendar rows are in place.
    // Otherwise late dates split topics and move already visible unit cards.
    container.hidden = true;
    container.setAttribute('aria-busy', 'true');
    const planningLoading = document.createElement('p');
    planningLoading.className = 'unit-empty';
    planningLoading.setAttribute('role', 'status');
    planningLoading.textContent = 'Einheiten und Termine werden geladen …';
    container.before(planningLoading);
    function renderGroups(nodes, parent) {
      for (const [topic, node] of [...nodes].sort((a, b) => a[1].first.localeCompare(b[1].first) || a[0].localeCompare(b[0], 'de'))) {
        const group = document.createElement(topic ? 'details' : 'div');
        group.className = topic ? 'unit-topic' : 'unit-recurring';
        group.dataset.sortDate = node.first;
        group.dataset.topicKey = `topic:${schoolClass}:${topic}`;
        if (topic) { group.innerHTML = `<summary>${esc(topic)}</summary>`; group.open = true; }
        for (const unit of node.entries.sort((a, b) => firstDate(a).localeCompare(firstDate(b)) || a.data.titel.localeCompare(b.data.titel, 'de'))) {
          const card = document.createElement('details');
          card.className = `unit-card${unit.data.typ === 'klausur' ? ' unit-exam' : ''}`;
          card.dataset.sortDate = firstDate(unit);
          card.dataset.unitPath = unit.path;
          // Share a native accordion group across topics, including programmatic opens.
          card.setAttribute('name', 'material-ui-unit');
          watchDetails(card, `unit:${unit.path}`, justCreated.has(unit.path) || drafts.has(unit.path) || quickDates.has(unit.path));
          const description = unit.data.kurzbeschreibung.trim();
          const showDescription = description && !/^Materialien:/i.test(description) && description !== unit.data.titel;
          const tags = unit.data.tags || [];
          card.innerHTML = `<summary><span class="unit-drag-handle" aria-hidden="true" title="Auf eine freie Stunde ziehen"></span><span class="unit-title">${esc(unit.data.titel)}</span>${unit.data.typ === 'klausur' ? '<small class="unit-type">Klausur</small>' : ''}<small class="unit-completion ${unit.data.fertig ? 'is-done' : ''}">${unit.data.fertig ? 'Fertig' : 'In Bearbeitung'}</small><small class="unit-dates">${dateSummary(unit)}</small></summary>
            <p class="unit-tags"${tags.length ? ' aria-label="Tags"' : ''} data-tags-row>${tags.map(tag => `<span class="tag-chip">${esc(tag)}</span>`).join(' ')}<button type="button" class="icon-button unit-inline-edit" data-edit-tags aria-label="${tags.length ? 'Tags bearbeiten' : 'Tags hinzufügen'}" title="${tags.length ? 'Tags bearbeiten' : 'Tags hinzufügen'}">${typeIcon('rename')}</button></p>
            <div data-quick-date-form></div><ul class="unit-materials" data-materials aria-label="Materialien"></ul>
            ${showDescription ? `<details class="unit-notes"><summary>Notizen<button type="button" class="icon-button unit-inline-edit" data-edit-notes aria-label="Notizen bearbeiten" title="Notizen bearbeiten">${typeIcon('rename')}</button></summary><p data-notes-text>${esc(description)}</p></details>` : ''}
            <div class="unit-actions"><button type="button" class="unit-edit" data-quick-date aria-label="Termine anzeigen und bearbeiten" title="Vorhandene Termine anzeigen und bearbeiten">${typeIcon('history')} Termine</button><button type="button" class="unit-edit" data-new-worksheet title="Neues Arbeitsblatt anlegen">${typeIcon('plus')} AB</button><button type="button" class="unit-edit" data-new-note title="Neue Notiz zur Einheit anlegen">${typeIcon('plus')} Notiz</button><button type="button" class="unit-edit" data-edit aria-label="Einheit bearbeiten">${typeIcon('settings')}<span>Bearbeiten</span></button></div><div data-editor></div>`;
          card.querySelector(':scope > summary').addEventListener('click', () => selectUnit(unit.path));
          renderMaterials(unit, card.querySelector('[data-materials]'));
          renderLernstand(unit, card);
          if (!unit.data.lernstand) renderUnitActions(unit, card.querySelector('.unit-actions'));
          card.querySelector('[data-new-note]').addEventListener('click', () => createNote(unit));
          card.querySelector('[data-new-worksheet]').addEventListener('click', () => createWorksheet(unit));
          card.querySelector('[data-quick-date]').onclick = () => {
            if (!quickDates.has(unit.path)) {
              const existing = existingDateRows(unit);
              quickDates.set(unit.path, { unit: structuredClone(unit), existing, dates: existing.length ? [] : [''], lerngruppe: '' });
            }
            selectUnit(unit.path); persistWorkspace(); renderQuickDates(unit, card); card.querySelector('.unit-quick-dates input[type=date]')?.focus();
          };
          if (quickDates.has(unit.path)) renderQuickDates(unit, card);
          for (const details of card.querySelectorAll('.unit-notes')) watchDetails(details, `${unit.path}:${details.className}`);
          card.querySelector('[data-edit]').addEventListener('click', () => edit(unit, card));
          group.append(card);
          if (drafts.has(unit.path)) edit(unit, card);
        }
        parent.append(group);
      }
    }
    renderGroups(groups, container);
    if (!groups.size) container.textContent = classes.length
      ? 'Keine Einheiten für diese Auswahl. Über „Hinzufügen“ kannst du eine Lerneinheit anlegen oder einen Ordner einbinden.'
      : 'Noch keine Unterrichtseinheiten angelegt. Über „Auswählen“ oben lässt sich vorhandenes Material durchsuchen, über „Hinzufügen“ eine erste Lerneinheit anlegen.';
    const planningOptions = { host: container, api, schoolClass, schoolYear, schoolTerm, watchDetails,
      assign: (event, row, trigger) => assignToLesson(event, row, trigger),
      move: (event, row, trigger, unitPath) => moveLesson(event, row, trigger, unitPath),
      create: event => {
        if (newUnitDraft) {
          section.querySelector('[data-status]').textContent = 'Bitte zuerst die angefangene Lerneinheit speichern oder abbrechen.';
          return;
        }
        newUnitDraft = { fach: event.teaching.fach || 'mathematik', klasse: schoolClass.replace('klasse-', ''),
          titel: '', thema: '', datum: event.startDate, lerngruppe: event.teaching.lerngruppe, datumsneutral: false };
        persistWorkspace(); renderNewUnitForm(); section.querySelector(".unit-create-form [name=thema]")?.focus();
      }
    };
    // RevealNavigationTarget muss spaeteren Fokus anstaendig liefern koennen:
    // Die Gruppenliste bleibt versteckt, bis die Kalenderdaten da sind, und
    // focus() auf nicht dargestellte Elemente bleibt wirkungslos.
    pendingPlanning = renderUnitPlanning(planningOptions);
    pendingPlanning.finally(() => {
      container.hidden = false;
      container.removeAttribute('aria-busy');
      planningLoading.remove();
    });
    section.querySelector('[data-new-marker]').onclick = () => editPlanningMarker(planningOptions);
    bindFilterMenu(section, { onYear: value => { schoolYear = value; render(); }, onCompletion: value => { completionFilter = value; render(); },
      onTags: value => { tagFilter = value; render(); },
      onSubject: value => { subjectFilter = value; render(); }, onGroup: value => { groupFilter = value; render(); },
      onOnlyUndated: value => { onlyUndated = value; render(); } });
    section.querySelectorAll('[data-class]').forEach(button => { button.onclick = () => { schoolClass = button.dataset.class; schoolTerm = button.dataset.term; render(); }; });
    section.querySelector('[data-show-undated]').onchange = event => { showUndated = event.target.checked; render(); };
    section.querySelector('[data-refresh]').onclick = load;
    section.querySelector('[data-new-unit]').onclick = () => {
      if (!newUnitDraft) newUnitDraft = { fach: units.find(unit => unit.klasse === schoolClass)?.fach || 'mathematik', klasse: schoolClass.replace('klasse-', '') || '05', titel: '', thema: '', datum: '', datumsneutral: false };
      persistWorkspace(); renderNewUnitForm(); section.querySelector(".unit-create-form [name=thema]")?.focus();
    };
    section.querySelector('[data-attach-folder]').onclick = () => attachFolder();
    renderNewUnitForm();
    renderAttachForm();
    renderThemeDeleteForm();
    markSelection();
    bindMenu('[data-add-menu]');
    section.querySelector('[data-options-menu]').open = optionsOpen;
    section.querySelector('[data-options-menu] button').addEventListener('click', () => { section.querySelector('[data-options-menu]').open = false; });
    section.dataset.positionKey = `${schoolClass}:${schoolTerm}:${schoolYear}:${tagFilter}:${completionFilter}:${subjectFilter}:${groupFilter}:${onlyUndated}`;
    skipCapture = false;
    persistWorkspace();
    const position = scrollPositions.get(section.dataset.positionKey) || 0;
    if (active) section.scrollTop = position;
    // Solange die Kalenderdaten laden, ist die Liste verborgen und zu kurz: der Browser setzt die
    // Position dann auf 0 zurueck. Nach dem Aufbau wird sie wiederhergestellt.
    const restoreKey = section.dataset.positionKey;
    pendingPlanning.finally(() => {
      if (active && position && section.dataset.positionKey === restoreKey && section.scrollTop < position) section.scrollTop = position;
    });
  }
  function applyNavigationTarget() {
    const unit = units.find(item => item.path === navigationTarget);
    if (!unit) return;
    captureView(); skipCapture = true;
    selectedUnitPath = unit.path; pendingRevealPath = '';
    schoolClass = unit.klasse; schoolYear = ''; schoolTerm = unitTerm(unit); tagFilter = ''; completionFilter = ''; subjectFilter = ''; groupFilter = ''; onlyUndated = false; showUndated = true;
    const topic = unit.data.thema.split('/').map(part => part.trim()).filter(Boolean).join(' / ');
    expanded.set(`topic:${unit.klasse}:${topic}`, true);
    expanded.set(`unit:${unit.path}`, true);
  }
  function revealNavigationTarget() {
    if (!navigationTarget) return;
    selectUnit(navigationTarget, true);
    const summary = section.querySelector('.unit-selected > summary');
    navigationTarget = '';
    if (!summary) return;
    if (summary.getClientRects().length) {
      summary.focus({ preventScroll: true });
      return;
    }
    // Noch verdeckt: Erst wenn die Gruppenliste nach dem Laden der
    // Kalenderdaten erscheint, ist die Ueberschrift fokussierbar. Nur
    // nachziehen, wenn der Fokus nicht inzwischen woanders liegt.
    const focusWhenShown = () => {
      if (summary.isConnected && document.activeElement === document.body) summary.focus({ preventScroll: true });
    };
    const wait = (pendingPlanning || Promise.resolve()).then(() => new Promise(resolve => setTimeout(resolve, 0)));
    wait.then(focusWhenShown);
  }
  // Material eines Einsatzes direkt öffnen (z. B. aus Heute oder Agenda); detail ist der Dokumentpfad.
  document.addEventListener('material-ui:open-material', event => {
    if (typeof event.detail === 'string' && event.detail) selectDocument(event.detail);
  });
  document.addEventListener('material-ui:open-unit', async event => {
    navigationTarget = event.detail;
    if (active) {
      applyNavigationTarget(); render(); revealNavigationTarget();
    } else if (!(await views.switchTo('units'))) {
      navigationTarget = '';
    }
  });
  // Einheit einer Stunde zuweisen, angestoßen aus Heute (Plugin „kalender“): detail = { event, row, trigger, notify, reload }.
  // Die Auswahl öffnet unter der Stunde; die Einheitenliste wird bei Bedarf erst geladen.
  document.addEventListener('material-ui:assign-unit', async ({ detail }) => {
    if (!detail?.event?.teaching?.klasse) return;
    if (!section) await views.prepare('units');
    if (!section) return;
    if (!units.length) await load();
    openAssignPicker({ row: detail.row, trigger: detail.trigger, event: detail.event, units: displayedUnits(), api,
      reload: async () => { await load(); await detail.reload?.(); }, notify: detail.notify || notifyAssignment,
      isBlocked: unit => drafts.has(unit.path) || quickDates.has(unit.path) });
  });
  // Status mit optionalem Rückgängig-Knopf (die Statuszeile wird bei jedem Render neu aufgebaut).
  function notifyAssignment(message, undo) {
    const status = section.querySelector('[data-status]');
    if (!status) return;
    status.textContent = message;
    if (!undo) return;
    const button = document.createElement('button'); button.type = 'button'; button.dataset.assignUndo = '';
    button.textContent = 'Rückgängig';
    button.onclick = async () => {
      button.disabled = true;
      try { await undo(); } catch (error) { status.textContent = error.message; }
    };
    status.append(' ', button);
  }
  function assignToLesson(event, row, trigger) {
    if (!event.teaching?.klasse) return;
    openAssignPicker({ row, trigger, event, units: displayedUnits(), api, reload: load, notify: notifyAssignment,
      isBlocked: unit => drafts.has(unit.path) || quickDates.has(unit.path) });
  }
  // Einsatz auf eine andere freie Stunde verschieben (Tastaturweg zum Ziehen am Griff der Stundenzeile).
  function moveLesson(event, row, trigger, unitPath) {
    const unit = displayedUnits().find(item => item.path === unitPath);
    if (!unit) return;
    const targets = [...section.querySelectorAll('[data-free-slot]')].map(slot => slot._planningEvent).filter(Boolean);
    openMovePicker({ row, trigger, unit, from: event, targets, api, reload: load, notify: notifyAssignment,
      isBlocked: item => drafts.has(item.path) || quickDates.has(item.path) });
  }
  const { renderNewUnitForm } = createUnitNewForm({ api, getSection: () => section, getUnits: () => units,
    getDraft: () => newUnitDraft, setDraft: value => { newUnitDraft = value; }, persistWorkspace, watchDetails,
    normalizeThemeValue, isDeletingTheme: () => deletingTheme, openThemeDeleteDialog: seed => openThemeDeleteDialog(seed),
    onCreated: created => {
      justCreated.add(created.path); schoolClass = created.klasse; schoolYear = ''; schoolTerm = unitTerm(created); persistWorkspace();
      units = [...units.filter(unit => unit.path !== created.path), created];
      navigationTarget = created.path;
      const previousShowUndated = showUndated;
      applyNavigationTarget(); showUndated = previousShowUndated;
      render(); revealNavigationTarget();
      section.querySelector('[data-status]').textContent = 'Lerneinheit angelegt.';
    } });
  function openThemeDeleteDialog(seed = {}) {
    if (deletingTheme) return;
    const grade = /^(?:klasse-)?(\d{1,2})$/.exec((seed.klasse || schoolClass || '').trim());
    const klassen = [...new Set(units.map(unit => unit.klasse))].sort((a, b) => a.localeCompare(b, 'de', { numeric: true }));
    const klasse = grade ? `klasse-${grade[1].padStart(2, '0')}` : klassen[0] || '';
    themeDeleteDraft = { klasse, fach: (seed.fach || '').trim(), thema: seed.thema || '', ersatz: '', ersatzNew: '' };
    renderThemeDeleteForm();
    section.querySelector('[data-theme-delete-form] [name=thema]')?.focus();
  }
  function renderThemeDeleteForm() {
    const container = section.querySelector('[data-theme-delete-form]');
    if (!container) return;
    container.replaceChildren();
    if (!themeDeleteDraft) return;
    const form = document.createElement('form');
    form.className = 'unit-create-form unit-theme-delete-form';
    form.innerHTML = `<strong>Thema löschen</strong>
      <div class="grid"><label>Fach<select name="fach" required></select></label><label>Klasse<select name="klasse" required></select></label></div>
      <label>Zu löschendes Thema<select name="thema" required></select></label>
      <label>Einheiten übernehmen in<select name="ersatz" required></select></label>
      <div data-ersatz-new-wrap hidden><label>Neues Thema<input name="ersatz-new" placeholder="z. B. Potenzen"></label></div>
      <p class="muted" data-theme-count></p>
      <button type="submit" ${deletingTheme ? 'disabled' : ''}>Thema löschen</button><button type="button" data-cancel-theme-delete>Abbrechen</button><p role="status"></p>`;
    const NEW_THEME = '__new__';
    const themaSelect = form.elements['thema'];
    const ersatzSelect = form.elements['ersatz'];
    const ersatzWrap = form.querySelector('[data-ersatz-new-wrap]');
    function klassen() { return [...new Set(units.map(unit => unit.klasse))].sort((a, b) => a.localeCompare(b, 'de', { numeric: true })); }
    function faecher() {
      return [...new Set(units.filter(unit => unit.klasse === themeDeleteDraft.klasse).map(unit => unit.fach).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b, 'de'));
    }
    function themes() {
      const fach = themeDeleteDraft.fach.toLocaleLowerCase('de');
      return [...new Set(units.filter(unit => unit.klasse === themeDeleteDraft.klasse
        && (unit.fach || '').toLocaleLowerCase('de') === fach).map(unit => unit.data.thema))]
        .sort((a, b) => a.localeCompare(b, 'de'));
    }
    function affectedUnits(thema) {
      return units.filter(unit => unit.klasse === themeDeleteDraft.klasse
        && (unit.fach || '').toLocaleLowerCase('de') === themeDeleteDraft.fach.toLocaleLowerCase('de')
        && normalizeThemeValue(unit.data.thema) === normalizeThemeValue(thema));
    }
    function optionNode(value) {
      const option = document.createElement('option');
      option.value = value; option.textContent = value;
      return option;
    }
    function newOptionNode() {
      const option = document.createElement('option');
      option.value = NEW_THEME; option.textContent = '+ Neues Thema…'; option.dataset.new = '1';
      return option;
    }
    function refreshBase() {
      const list = klassen();
      form.elements.klasse.replaceChildren(...list.map(optionNode));
      form.elements.klasse.value = list.includes(themeDeleteDraft.klasse) ? themeDeleteDraft.klasse : list[0] || '';
      themeDeleteDraft.klasse = form.elements.klasse.value;
      const subjects = faecher();
      form.elements.fach.replaceChildren(...subjects.map(optionNode));
      const matchedFach = subjects.find(subject => subject.toLocaleLowerCase('de') === themeDeleteDraft.fach.toLocaleLowerCase('de'));
      form.elements.fach.value = matchedFach || subjects[0] || '';
      themeDeleteDraft.fach = form.elements.fach.value;
      refreshThemes();
    }
    function refreshThemes() {
      const list = themes();
      themaSelect.replaceChildren(...list.map(optionNode));
      const matched = list.find(theme => normalizeThemeValue(theme) === normalizeThemeValue(themeDeleteDraft.thema));
      themaSelect.value = matched || list[0] || '';
      themeDeleteDraft.thema = themaSelect.value;
      refreshErsatz();
    }
    function refreshErsatz() {
      const current = normalizeThemeValue(themeDeleteDraft.thema);
      const remaining = themes().filter(theme => normalizeThemeValue(theme) !== current);
      ersatzSelect.replaceChildren(...remaining.map(optionNode), newOptionNode());
      const matched = themeDeleteDraft.ersatz
        && remaining.find(theme => normalizeThemeValue(theme) === normalizeThemeValue(themeDeleteDraft.ersatz));
      if (matched) {
        ersatzSelect.value = matched;
        ersatzWrap.hidden = true;
        form.elements['ersatz-new'].required = false;
      } else {
        ersatzSelect.value = NEW_THEME;
        ersatzWrap.hidden = false;
        form.elements['ersatz-new'].required = true;
        form.elements['ersatz-new'].value = themeDeleteDraft.ersatz || '';
      }
      updateCount();
    }
    function currentErsatzValue() {
      return ersatzSelect.selectedOptions[0]?.dataset.new === '1'
        ? form.elements['ersatz-new'].value.trim() : ersatzSelect.value;
    }
    function updateCount() {
      const affected = affectedUnits(themeDeleteDraft.thema);
      form.querySelector('[data-theme-count]').textContent = affected.length
        ? `${affected.length} ${affected.length === 1 ? 'Einheit gehört' : 'Einheiten gehören'} zu diesem Thema.`
        : 'Keine Einheiten mit diesem Thema.';
    }
    form.elements.klasse.addEventListener('change', () => {
      themeDeleteDraft.klasse = form.elements.klasse.value;
      themeDeleteDraft.fach = ''; themeDeleteDraft.thema = ''; themeDeleteDraft.ersatz = '';
      refreshBase();
    });
    form.elements.fach.addEventListener('change', () => {
      themeDeleteDraft.fach = form.elements.fach.value;
      themeDeleteDraft.thema = ''; themeDeleteDraft.ersatz = '';
      refreshThemes();
    });
    themaSelect.addEventListener('change', () => { themeDeleteDraft.thema = themaSelect.value; refreshErsatz(); });
    ersatzSelect.addEventListener('change', () => {
      const isNew = ersatzSelect.selectedOptions[0]?.dataset.new === '1';
      themeDeleteDraft.ersatz = currentErsatzValue();
      ersatzWrap.hidden = !isNew;
      form.elements['ersatz-new'].required = isNew;
      if (isNew) form.elements['ersatz-new'].focus();
    });
    form.elements['ersatz-new'].addEventListener('input', () => { themeDeleteDraft.ersatz = currentErsatzValue(); });
    form.querySelector('[data-cancel-theme-delete]').onclick = () => {
      if (deletingTheme) return;
      themeDeleteDraft = null; renderThemeDeleteForm();
    };
    form.onsubmit = async event => {
      event.preventDefault();
      if (deletingTheme || !themeDeleteDraft) return;
      const thema = themaSelect.value;
      const ersatz = currentErsatzValue();
      if (!ersatz) { form.querySelector('[role=status]').textContent = 'Bitte ein Ersatzthema angeben.'; return; }
      const affected = affectedUnits(thema);
      if (!window.confirm(`Thema „${thema}" löschen? ${affected.length} ${affected.length === 1 ? 'Einheit wechselt' : 'Einheiten wechseln'} zum Thema „${ersatz}".`)) return;
      deletingTheme = true; form.querySelector('[type=submit]').disabled = true;
      try {
        const result = await api('/api/units/theme-delete', { method: 'POST',
          body: JSON.stringify({ fach: themeDeleteDraft.fach, klasse: themeDeleteDraft.klasse, thema, ersatz }) });
        const removed = normalizeThemeValue(result.removed || thema);
        // Angefangene Formulare sollen das gelöschte Thema nicht versehentlich neu anlegen.
        if (newUnitDraft && normalizeThemeValue(newUnitDraft.thema || '') === removed) { newUnitDraft.thema = result.ersatz; }
        if (attachDraft && normalizeThemeValue(attachDraft.thema || '') === removed) { attachDraft.thema = result.ersatz; }
        persistWorkspace();
        themeDeleteDraft = null; renderThemeDeleteForm();
        await load();
        section.querySelector('[data-status]').textContent = `Thema gelöscht. ${result.updated.length} ${result.updated.length === 1 ? 'Einheit gehört' : 'Einheiten gehören'} jetzt zu „${result.ersatz}".`;
      } catch (error) {
        form.querySelector('[role=status]').textContent = error.message;
        if (form.isConnected) form.querySelector('[type=submit]').disabled = false;
      } finally { deletingTheme = false; }
    };
    if (!klassen().length) form.querySelector('[role=status]').textContent = 'Keine Klassen mit Einheiten gefunden.';
    refreshBase();
    container.append(form);
  }
  async function attachFolder(path = null, reload = false) {
    if (!(await views.switchTo('units'))) return;
    if (attachDraft && !reload && (!path || path === attachDraft.path)) { renderAttachForm(); return; }
    section.querySelector('[data-status]').textContent = 'Ordner werden geladen…';
    try {
      const query = path ? `path=${encodeURIComponent(path)}` : `klasse=${encodeURIComponent(schoolClass)}`;
      const payload = await api(`/api/units/folders?${query}`);
      const today = new Date();
      const datum = attachDraft?.datum || `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
      attachDraft = { folders: payload.folders, path: path || '', search: '', datum, lerngruppe: attachDraft?.lerngruppe || '', titel: '', thema: '' };
      if (path && payload.folders[0]) {
        attachDraft.titel = payload.folders[0].data.titel;
        attachDraft.thema = payload.folders[0].data.thema;
      }
      persistWorkspace(); renderAttachForm();
      section.querySelector(attachDraft.path ? '.unit-attach-form [name=datum]' : '[data-folder-search]')?.focus();
      section.querySelector('[data-status]').textContent = payload.errors.join('\n');
    } catch (error) { section.querySelector('[data-status]').textContent = error.message; }
  }
  function renderAttachForm() {
    const container = section.querySelector('[data-attach-form]');
    container.replaceChildren();
    if (!attachDraft) return;
    const form = document.createElement('form');
    form.className = 'unit-attach-form unit-create-form';
    form.innerHTML = `<strong>Vorhandenen Ordner einbinden</strong>
      <label>Ordner suchen<input type="search" data-folder-search value="${esc(attachDraft.search)}" placeholder="Titel, Thema oder Ordnername"></label>
      <label>Ordner<select data-folder-picker size="6" required></select></label>
      <div data-attach-fields>
        <p data-selected-folder class="unit-empty"></p><p data-existing-uses class="unit-empty"></p>
        <label>Thema<select name="thema" required></select></label>
        <div data-attach-theme-new hidden><label>Neues Thema<input name="thema-new" placeholder="z. B. Potenzen"></label></div>
        <button type="button" data-theme-delete>Thema löschen…</button>
        <label>Titel der Lerneinheit<input name="titel" required value="${esc(attachDraft.titel)}"></label>
        <label>Datum<input name="datum" type="date" required value="${esc(attachDraft.datum)}"></label>
        <label>Lerngruppe${groupSelect(attachDraft.lerngruppe)}</label>
      </div>
      <button type="submit" ${attaching ? 'disabled' : ''}>Einbinden und Datum speichern</button>
      <button type="button" data-cancel-attach>Abbrechen</button><p role="status"></p>`;
    const picker = form.querySelector('[data-folder-picker]');
    const NEW_THEME = '__new__';
    const themaSelect = form.elements['thema'];
    const themaWrap = form.querySelector('[data-attach-theme-new]');
    function selected() { return attachDraft.folders.find(folder => folder.path === attachDraft.path); }
    function folderThemes(folder) {
      return [...new Set(attachDraft.folders.filter(item => item.klasse === folder.klasse
        && (item.fach || '').toLocaleLowerCase('de') === (folder.fach || '').toLocaleLowerCase('de'))
        .map(item => item.data.thema))].sort((a, b) => a.localeCompare(b, 'de'));
    }
    function isNewTheme() { return themaSelect.selectedOptions[0]?.dataset.new === '1'; }
    function currentThemaValue() { return isNewTheme() ? form.elements['thema-new'].value.trim() : themaSelect.value; }
    function refreshAttachThemeOptions(currentValue) {
      const folder = selected();
      const list = folder ? folderThemes(folder) : [];
      const normalized = currentValue ? normalizeThemeValue(currentValue) : '';
      const matchedIndex = normalized ? list.findIndex(theme => normalizeThemeValue(theme) === normalized) : -1;
      themaSelect.replaceChildren(...list.map(theme => {
        const option = document.createElement('option');
        option.value = theme; option.textContent = theme;
        return option;
      }));
      const newOption = document.createElement('option');
      newOption.value = NEW_THEME; newOption.textContent = '+ Neues Thema…'; newOption.dataset.new = '1';
      themaSelect.append(newOption);
      themaSelect.selectedIndex = matchedIndex === -1 ? list.length : matchedIndex;
      themaWrap.hidden = !isNewTheme();
      form.elements['thema-new'].required = isNewTheme();
      if (isNewTheme()) form.elements['thema-new'].value = currentValue || '';
      attachDraft.thema = currentThemaValue();
    }
    function updateSelection() {
      const folder = picker.value === attachDraft.path && !picker.disabled ? selected() : null;
      form.querySelector('[data-attach-fields]').hidden = !folder;
      form.querySelector('[type=submit]').disabled = !folder || attaching;
      form.querySelector('[data-selected-folder]').textContent = folder?.path || '';
      form.querySelector('[data-existing-uses]').textContent = folder?.data.einsatz?.length
        ? `Bisherige Einsätze bleiben erhalten: ${folder.data.einsatz.map(use => labelDate(use.datum)).join(' · ')}` : '';
    }
    function filterFolders() {
      const needle = attachDraft.search.trim().toLocaleLowerCase('de');
      const folders = attachDraft.folders.filter(folder => `${folder.path} ${folder.data.titel} ${folder.data.thema}`.toLocaleLowerCase('de').includes(needle));
      picker.replaceChildren();
      for (const folder of folders) {
        const option = document.createElement('option');
        option.value = folder.path;
        const parts = folder.path.split('/');
        const index = parts.findIndex(part => /^klasse-\d+$/.test(part));
        option.textContent = `${folder.fach} · ${parts.slice(index + 1).join(' / ') || folder.data.titel}${folder.gespeichert ? ' · Zusammenfassung vorhanden' : ''}`;
        option.title = folder.path;
        picker.append(option);
      }
      if (!folders.some(folder => folder.path === attachDraft.path)) { attachDraft.path = ''; attachDraft.titel = ''; attachDraft.thema = ''; }
      picker.value = attachDraft.path;
      picker.disabled = !folders.length;
      form.querySelector('[role=status]').textContent = folders.length ? '' : 'Keine passenden Ordner gefunden.';
      updateSelection(); persistWorkspace();
    }
    picker.onchange = () => {
      attachDraft.path = picker.value;
      const folder = selected();
      if (folder) {
        attachDraft.titel = folder.data.titel; attachDraft.thema = folder.data.thema;
        form.elements.titel.value = attachDraft.titel;
        refreshAttachThemeOptions(attachDraft.thema);
      }
      updateSelection(); persistWorkspace();
    };
    form.querySelector('[data-folder-search]').oninput = event => { attachDraft.search = event.target.value; filterFolders(); };
    for (const key of ['titel', 'datum', 'lerngruppe']) {
      form.elements[key].oninput = () => { attachDraft[key] = form.elements[key].value; persistWorkspace(); };
    }
    themaSelect.addEventListener('change', () => {
      themaWrap.hidden = !isNewTheme();
      form.elements['thema-new'].required = isNewTheme();
      if (isNewTheme()) form.elements['thema-new'].focus();
      attachDraft.thema = currentThemaValue();
      persistWorkspace();
    });
    form.elements['thema-new'].addEventListener('input', () => { attachDraft.thema = currentThemaValue(); persistWorkspace(); });
    form.querySelector('[data-theme-delete]').onclick = () => {
      if (deletingTheme) return;
      const folder = selected();
      openThemeDeleteDialog({ fach: folder?.fach || '', klasse: folder?.klasse || schoolClass, thema: currentThemaValue() });
    };
    form.querySelector('[data-cancel-attach]').onclick = () => { if (!attaching) { attachDraft = null; persistWorkspace(); container.replaceChildren(); } };
    form.onsubmit = async event => {
      event.preventDefault();
      const folder = selected();
      if (!folder || attaching || picker.disabled || picker.value !== folder.path) return;
      const payload = { path: folder.path, revision: folder.revision };
      for (const key of ['titel', 'datum', 'lerngruppe']) payload[key] = form.elements[key].value.trim();
      payload.thema = currentThemaValue();
      attaching = true; form.querySelector('[type=submit]').disabled = true;
      try {
        const saved = await api('/api/units/attach', { method: 'POST', body: JSON.stringify(payload) });
        schoolClass = saved.klasse; schoolYear = year(payload.datum); schoolTerm = unitTerm(saved); justCreated.add(saved.path); attachDraft = null; persistWorkspace();
        await load();
      } catch (error) {
        const status = form.querySelector('[role=status]');
        status.textContent = error.message;
        if (error.status === 409) {
          const reload = document.createElement('button');
          reload.type = 'button'; reload.textContent = 'Ordnerdaten neu laden';
          reload.onclick = () => attachFolder(folder.path, true);
          status.append(reload);
        }
      }
      finally { attaching = false; form.querySelector('[type=submit]').disabled = false; }
    };
    filterFolders(); updateSelection();
    if (selected()) refreshAttachThemeOptions(attachDraft.thema);
    container.append(form);

  }
  const { renderQuickDates } = createUnitDates({ api, quickDates, savingDates, persistWorkspace, load, groupSelect, labelDate, year,
    unitTerm, existingDateRows, getSection: () => section,
    setView: view => { ({ schoolClass, schoolTerm, schoolYear } = view); } });
  const { edit } = createUnitEditor({
    api, drafts, saving, persistDrafts, groupSelect, labelDate,
    getSection: () => section,
    updateUnits: value => { units = value; render(); },
    load,
    themeOptions: unit => units.filter(item => item.klasse === unit.klasse
      && (item.fach || '').toLocaleLowerCase('de') === (unit.fach || '').toLocaleLowerCase('de'))
      .map(item => item.data.thema),
    onDeleteTheme: seed => openThemeDeleteDialog(seed)
  });
  async function load() {
    if (!section) return;
    // Jeder explizite Reload holt frische Kalenderdaten; Filterwechsel innerhalb
    // der Ansicht nutzen den Cache in unit-planning.js.
    clearUnitPlanningCache();
    try {
      const data = await api('/api/units');
      const key = `material-ui:unit-drafts:${data.project}`;
      if (key !== draftKey) {
        draftKey = key; drafts.clear();
        workspaceKey = `material-ui:unit-workspace:${data.project}`;
        try {
          const stored = JSON.parse(sessionStorage.getItem(workspaceKey) || '{}');
          schoolClass = stored.schoolClass || ''; schoolTerm = stored.schoolTerm || ''; schoolYear = stored.schoolYear || '';
          showUndated = stored.showUndated === true; tagFilter = stored.tagFilter || '';
          completionFilter = normalizeCompletion(stored.completionFilter);
          subjectFilter = typeof stored.subjectFilter === 'string' ? stored.subjectFilter : '';
          groupFilter = typeof stored.groupFilter === 'string' ? stored.groupFilter : ''; onlyUndated = stored.onlyUndated === true;
          newUnitDraft = stored.newUnitDraft || null; attachDraft = stored.attachDraft || null;
          selectedUnitPath = stored.selectedUnitPath || ''; lastDocumentPath = stored.lastDocumentPath || ''; pendingRevealPath = stored.pendingRevealPath || '';
          for (const [map, entries] of [[expanded, stored.expanded], [scrollPositions, stored.scrollPositions], [quickDates, stored.quickDates]]) {
            map.clear(); for (const entry of entries || []) map.set(...entry);
          }
          justCreated.clear();
        } catch { /* Ignore damaged workspace storage; existing document drafts remain independent. */ }

        try { for (const [path, draft] of JSON.parse(sessionStorage.getItem(key) || '[]')) drafts.set(path, draft); } catch { /* Ignore damaged storage. */ }
      }
      groupDefaults = (await api('/api/plugins/kalender/unit-groups').catch(() => ({ rows: [] }))).rows;
      units = data.units;
      applyNavigationTarget(); render();
      const path = getDocumentPath();
      if (!navigationTarget && path && path !== lastDocumentPath) documentOpened(path);
      if (pendingRevealPath && active) { const target = pendingRevealPath; pendingRevealPath = ''; selectUnit(target, true); }
      section.querySelector('[data-status]').textContent = data.errors.join('\n');
    } catch (error) {
      let status = section.querySelector('[data-status]');
      if (!status) { status = document.createElement('p'); status.dataset.status = ''; section.prepend(status); }
      status.textContent = error.message;
    }
  }
  document.addEventListener('material-document-opened', event => documentOpened(event.detail?.path || ''));
  document.addEventListener('material-units-refresh', () => { load(); });
  views.registerView({ id: 'units', title: 'Unterrichtseinheiten', icon: 'lightbulb', order: 35,
    mount: target => {
      section = target; section.classList.add('units-view');
      bindMaterialDelegation();
      bindInlineEditDelegation();
      // Menues der Leiste sind Popover: ein Klick daneben schliesst sie.
      document.addEventListener('click', event => {
        for (const menu of section.querySelectorAll('.unit-toolbar > details[open]')) if (!menu.contains(event.target)) menu.open = false;
      });
      bindUnitDrag({ section, getUnits: displayedUnits, api, reload: load, notify: notifyAssignment,
        isBlocked: unit => drafts.has(unit.path) || quickDates.has(unit.path) });
      section.addEventListener('scroll', () => {
        if (!active || !section.dataset.positionKey) return;
        scrollPositions.set(section.dataset.positionKey, section.scrollTop);
        clearTimeout(scrollTimer); scrollTimer = setTimeout(persistWorkspace, 150);
      });
      window.addEventListener('pagehide', () => { captureView(); persistWorkspace(); });
    },
    onRefresh: load,
    onPrepare: load,
    onActivate: () => {
      active = true; skipCapture = true;
      if (navigationTarget) revealNavigationTarget();
      else if (pendingRevealPath) { const target = pendingRevealPath; pendingRevealPath = ''; selectUnit(target, true); }
      else section.scrollTop = scrollPositions.get(section.dataset.positionKey) || 0;
    },
    onDeactivate: () => { captureView(); persistWorkspace(); active = false; }
  });
  return { refresh: load, attachFolder, registerAction };
}
