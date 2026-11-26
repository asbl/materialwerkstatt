import { startPointerDrag } from './pointer-drag.js';

// Zuweisen einer bestehenden Einheit zu einer freien Unterrichtsstunde.
// Eigenständiges Modul ohne Zugriff auf den Zustand von units.js: Abhängigkeiten
// (api, Einheitenliste, Reload- und Status-Callback) kommen als Argumente.

const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const lower = value => String(value || '').toLocaleLowerCase('de');
const dayLabel = value => value.split('-').reverse().join('.');

// Lerngruppen werden wie im Kalender verglichen: ohne Leerzeichen, Groß-/Kleinschreibung egal.
const groupKey = value => String(value || '').toUpperCase().replace(/\s+/g, '');

// Steht die Einheit am Tag der Stunde schon für diese Lerngruppe im Plan? (Einsatz ohne Lerngruppe gilt für alle.)
export function isAssigned(unit, event) {
  const group = event.teaching?.lerngruppe;
  return (unit.data.einsatz || []).some(use => use.datum === event.startDate
    && (!use.lerngruppe || groupKey(use.lerngruppe) === groupKey(group)));
}

// Einheiten, die für die Stunde in Frage kommen: gleiche Klasse und (falls bekannt) gleiches Fach.
// Reihenfolge: noch nie eingesetzte Einheiten zuerst, dann nach Thema und Titel.
export function assignCandidates(units, event) {
  const teaching = event.teaching || {};
  const subject = lower(teaching.fach);
  return units
    .filter(unit => unit.klasse === teaching.klasse && (!subject || lower(unit.fach) === subject))
    .map(unit => {
      return { unit, used: (unit.data.einsatz || []).length, already: isAssigned(unit, event) };
    })
    .sort((a, b) => (a.used > 0) - (b.used > 0)
      || lower(a.unit.data.thema).localeCompare(lower(b.unit.data.thema), 'de')
      || lower(a.unit.data.titel).localeCompare(lower(b.unit.data.titel), 'de'));
}

// Einsatz anhängen; liefert die gespeicherte Einheit und eine Funktion, die genau diesen Einsatz entfernt.
// Fügt der Server nichts hinzu (Einsatz existierte schon), ist `undo` null: Rückgängig darf
// einen vorher vorhandenen Eintrag nie löschen.
export async function assignUnit(api, unit, event) {
  const group = event.teaching?.lerngruppe || '';
  const saved = await api('/api/units/dates', { method: 'POST', body: JSON.stringify({
    path: unit.path, revision: unit.revision, dates: [event.startDate], lerngruppe: group,
  }) });
  let current = saved;
  const added = (saved.data.einsatz || []).length > (unit.data.einsatz || []).length;
  const undo = !added ? null : async () => {
    current = await api('/api/units/dates', { method: 'POST', body: JSON.stringify({
      path: unit.path, revision: current.revision, remove: [{ datum: event.startDate, lerngruppe: group }],
    }) });
    return current;
  };
  return { saved, undo };
}

// Zuweisen samt Rückmeldung: lädt die Ansicht neu und bietet Rückgängig an.
// Gemeinsamer Weg für die Auswahl und das Ziehen auf eine Stunde.
export async function assignAndReport({ api, unit, event, reload, notify }) {
  const { saved, undo } = await assignUnit(api, unit, event);
  await reload();
  notify(`„${saved.data.titel}“ am ${dayLabel(event.startDate)} ${undo ? 'eingetragen' : 'war schon eingetragen'}.`, undo && (async () => {
    await undo(); await reload(); notify('Eintrag zurückgenommen.', null);
  }));
}

// Einsätze der Einheit, die an der Stunde stehen (gleicher Tag, passende Lerngruppe); Index in data.einsatz.
export function usesAt(unit, event) {
  const group = event.teaching?.lerngruppe;
  return (unit.data.einsatz || []).map((use, index) => ({ use, index })).filter(({ use }) => use.datum === event.startDate
    && (!use.lerngruppe || groupKey(use.lerngruppe) === groupKey(group)));
}

// Kann der Einsatz von `from` auf die freie Stunde `to` wandern? Liefert eine Meldung oder '' wenn ja.
export function moveProblem(unit, from, to) {
  if (!fitsLesson(unit, to)) return 'Diese Einheit passt nicht zu Klasse oder Fach der Stunde.';
  if (from.startDate === to.startDate) return 'Die Einheit steht schon an diesem Tag.';
  if (isAssigned(unit, to)) return 'Die Einheit ist an diesem Tag schon eingetragen.';
  const group = groupKey(to.teaching?.lerngruppe);
  if (usesAt(unit, from).some(({ use }) => use.lerngruppe && groupKey(use.lerngruppe) !== group)) return 'Die Stunde gehört zu einer anderen Lerngruppe.';
  return '';
}

// Einsatz auf einen anderen Tag verschieben (Datum wird an Ort und Stelle geändert, nichts wird doppelt angelegt).
// Liefert die gespeicherte Einheit und eine Funktion, die das Datum zurücksetzt.
export async function moveUse(api, unit, from, to) {
  const indices = usesAt(unit, from).map(({ index }) => index);
  if (!indices.length) throw new Error('Der Einsatz wurde nicht gefunden. Bitte die Ansicht aktualisieren.');
  const saved = await api('/api/units/dates', { method: 'POST', body: JSON.stringify({
    path: unit.path, revision: unit.revision, updates: indices.map(index => ({ index, datum: to.startDate })),
  }) });
  let current = saved;
  const undo = async () => {
    current = await api('/api/units/dates', { method: 'POST', body: JSON.stringify({
      path: unit.path, revision: current.revision, updates: indices.map(index => ({ index, datum: from.startDate })),
    }) });
    return current;
  };
  return { saved, undo };
}

export async function moveAndReport({ api, unit, from, to, reload, notify }) {
  const { saved, undo } = await moveUse(api, unit, from, to);
  await reload();
  notify(`„${saved.data.titel}“ von ${dayLabel(from.startDate)} auf ${dayLabel(to.startDate)} verschoben.`, async () => {
    await undo(); await reload(); notify('Verschiebung zurückgenommen.', null);
  });
}

const conflictText = 'Die Einheit wurde zwischenzeitlich geändert. Bitte die Ansicht aktualisieren und erneut versuchen.';

// Tastaturweg zum Verschieben: Auswahl der freien Stunden unter der Zeile (Ziehen ist nur die Abkürzung).
// `targets` sind die freien Stunden (Ereignisse); `isBlocked(unit)` meldet offene Entwürfe.
export function openMovePicker({ row, trigger, unit, from, targets, api, reload, notify, isBlocked = () => false }) {
  const existing = row.nextElementSibling?.matches?.('.unit-move-picker') ? row.nextElementSibling : null;
  if (existing) { existing.remove(); trigger?.setAttribute('aria-expanded', 'false'); return; }
  document.querySelectorAll('.unit-move-picker').forEach(node => node.remove());
  const options = targets.filter(target => !moveProblem(unit, from, target));
  const form = document.createElement('form');
  form.className = 'unit-move-picker';
  form.dataset.planningEntry = '';
  form.setAttribute('aria-label', `Einsatz vom ${dayLabel(from.startDate)} verschieben`);
  const time = event => (event.start && !event.allDay ? new Date(event.start).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }) : '');
  form.innerHTML = options.length
    ? `<label>Neuer Termin<select data-move-target>${options.map((target, index) => `<option value="${index}">${esc(new Date(`${target.startDate}T12:00:00`).toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit' }))} ${esc(time(target))} ${esc(target.title)}</option>`).join('')}</select></label>
       <button type="submit" class="unit-edit">Verschieben</button><button type="button" class="unit-edit" data-move-cancel>Abbrechen</button><p role="status" aria-live="polite" data-move-status></p>`
    : '<p class="unit-empty">Keine freie Stunde zum Verschieben. Freie Stunden erscheinen nur für kommende Termine ohne Einheit.</p>';
  const status = form.querySelector('[data-move-status]');
  const close = () => { form.remove(); trigger?.setAttribute('aria-expanded', 'false'); trigger?.focus(); };
  form.querySelector('[data-move-cancel]')?.addEventListener('click', close);
  form.addEventListener('keydown', key => { if (key.key === 'Escape') { key.preventDefault(); key.stopPropagation(); close(); } });
  form.onsubmit = async submit => {
    submit.preventDefault();
    const target = options[Number(form.querySelector('[data-move-target]')?.value)];
    if (!target) return;
    if (isBlocked(unit)) { status.textContent = 'Bitte zuerst die offenen Änderungen der Einheit speichern.'; return; }
    form.querySelector('[type=submit]').disabled = true; status.textContent = 'Einsatz wird verschoben …';
    try { await moveAndReport({ api, unit, from, to: target, reload: async () => { form.remove(); await reload(); }, notify }); }
    catch (error) { form.querySelector('[type=submit]').disabled = false; status.textContent = error.status === 409 ? conflictText : error.message; }
  };
  row.after(form);
  trigger?.setAttribute('aria-expanded', 'true');
  (form.querySelector('select') || form).focus?.();
}

// Passt die Einheit zu Klasse (und, falls bekannt, Fach) der Stunde?
export function fitsLesson(unit, event) {
  const teaching = event.teaching || {};
  return unit.klasse === teaching.klasse && (!teaching.fach || lower(unit.fach) === lower(teaching.fach));
}

// Öffnet die Auswahl unter der Stundenzeile; ein zweiter Aufruf für dieselbe Zeile schließt sie wieder.
// notify(message, undo|null) meldet das Ergebnis in der Statuszeile der Ansicht.
export function openAssignPicker({ row, trigger, event, units, api, reload, notify, isBlocked = () => false }) {
  const existing = row.nextElementSibling?.matches?.('.unit-assign-picker') ? row.nextElementSibling : null;
  if (existing) { existing.remove(); trigger?.setAttribute('aria-expanded', 'false'); return; }
  document.querySelectorAll('.unit-assign-picker').forEach(node => node.remove());
  const candidates = assignCandidates(units, event);
  const form = document.createElement('form');
  form.className = 'unit-assign-picker';
  form.dataset.planningEntry = '';
  form.setAttribute('aria-label', `Einheit am ${dayLabel(event.startDate)} zuweisen`);
  form.innerHTML = `<input type="search" data-assign-search placeholder="Einheit suchen" aria-label="Einheit suchen">
    <ul data-assign-list></ul><p role="status" aria-live="polite" data-assign-status></p>`;
  const list = form.querySelector('[data-assign-list]'), status = form.querySelector('[data-assign-status]');
  let busy = false;
  const close = () => { form.remove(); trigger?.setAttribute('aria-expanded', 'false'); trigger?.focus(); };
  function renderList() {
    const needle = lower(form.querySelector('[data-assign-search]').value).trim();
    const shown = candidates.filter(({ unit }) => !needle || lower(`${unit.data.titel} ${unit.data.thema}`).includes(needle));
    list.innerHTML = shown.map(({ unit, used, already }, index) => { const blocked = isBlocked(unit); return `<li><button type="button" data-assign-index="${index}"
      ${already || busy || blocked ? 'disabled' : ''}><strong>${esc(unit.data.titel)}</strong>
      <small>${esc(unit.data.thema)}${blocked ? ' · erst ungespeicherte Änderungen sichern' : already ? ' · an diesem Tag schon eingetragen' : used ? ` · ${used} Einsätze` : ' · noch nie eingesetzt'}</small></button></li>`; }).join('');
    if (!shown.length) list.innerHTML = `<li class="unit-empty">${candidates.length ? 'Keine Einheit passt zur Suche.'
      : 'Keine passende Einheit für diese Klasse und dieses Fach. Mit „+ Lerneinheit“ lässt sich eine neue anlegen.'}</li>`;
    list.querySelectorAll('[data-assign-index]').forEach(button => {
      button.onclick = async () => {
        if (busy) return;
        const { unit } = shown[Number(button.dataset.assignIndex)];
        busy = true; renderList(); status.textContent = 'Einheit wird eingetragen …';
        try {
          await assignAndReport({ api, unit, event, reload: async () => { form.remove(); await reload(); }, notify });
        } catch (error) {
          busy = false; renderList();
          status.textContent = error.status === 409
            ? 'Die Einheit wurde zwischenzeitlich geändert. Bitte die Ansicht aktualisieren und erneut versuchen.'
            : error.message;
        }
      };
    });
  }
  form.onsubmit = submit => submit.preventDefault();
  form.addEventListener('keydown', key => { if (key.key === 'Escape') { key.preventDefault(); key.stopPropagation(); close(); } });
  form.querySelector('[data-assign-search]').addEventListener('input', renderList);
  renderList();
  row.after(form);
  trigger?.setAttribute('aria-expanded', 'true');
  form.querySelector('[data-assign-search]').focus();
}

// Ziehen auf eine freie Stunde (Abkürzung zur Auswahl, nie der einzige Weg):
//  - Einheitenkarte am Griff (.unit-drag-handle): Einheit der Stunde zuweisen,
//  - eingetragene Stunde am Griff (.unit-move-handle): den Einsatz auf die freie Stunde verschieben.
// Freie, nicht ausgefallene Stunden tragen `data-free-slot`; jede Stundenzeile trägt ihr Ereignis in
// `_planningEvent` (gesetzt in unit-planning.js). Delegiert über `section`, damit Neurendern nichts neu bindet.
export function bindUnitDrag({ section, getUnits, api, reload, notify, isBlocked = () => false }) {
  let suppressClick = false;
  const HANDLES = '.unit-drag-handle, .unit-move-handle';
  section.addEventListener('click', event => {
    if (suppressClick && event.target.closest(HANDLES)) { event.preventDefault(); event.stopPropagation(); }
  }, true);
  section.addEventListener('pointerdown', down => {
    const handle = down.target.closest(HANDLES);
    if (!handle || down.button !== 0) return;
    const moving = handle.classList.contains('unit-move-handle');
    const holder = handle.closest(moving ? '.unit-plan-slot' : '.unit-card');
    const unit = getUnits().find(item => item.path === (moving ? handle.closest('.unit-plan-assigned')?.dataset.unitPath : holder?.dataset.unitPath));
    const from = moving ? holder?._planningEvent : null;
    if (!unit || (moving && !from)) return;
    const problem = slot => (moving ? moveProblem(unit, from, slot._planningEvent)
      : !fitsLesson(unit, slot._planningEvent) ? 'Diese Einheit passt nicht zu Klasse oder Fach der Stunde.'
        : isAssigned(unit, slot._planningEvent) ? 'Die Einheit ist an diesem Tag schon eingetragen.' : '');
    const clear = () => section.querySelectorAll('.unit-drop-target, .unit-drop-invalid').forEach(node => node.classList.remove('unit-drop-target', 'unit-drop-invalid'));
    const slotAt = event => document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-free-slot]');
    // Am oberen und unteren Rand der Ansicht automatisch scrollen, damit weit entfernte freie Stunden erreichbar sind.
    let pointer = null, frame = 0;
    const EDGE = 56, MAX_STEP = 18;
    const autoScroll = () => {
      frame = 0;
      if (!pointer) return;
      const rect = section.getBoundingClientRect();
      const step = pointer.y < rect.top + EDGE ? -MAX_STEP * Math.min(1, (rect.top + EDGE - pointer.y) / EDGE)
        : pointer.y > rect.bottom - EDGE ? MAX_STEP * Math.min(1, (pointer.y - (rect.bottom - EDGE)) / EDGE) : 0;
      if (step) { section.scrollTop += step; frame = requestAnimationFrame(autoScroll); }
    };
    startPointerDrag({
      event: down, handle,
      onStart: () => {
        suppressClick = true; holder.classList.add('unit-dragging'); section.classList.add('is-dragging-unit');
        // Zugeklappte freie Tage öffnen, damit ihre Stunden als Ziel erreichbar sind.
        section.querySelectorAll('.unit-plan-day:not([open])').forEach(day => { if (day.querySelector('[data-free-slot]')) day.open = true; });
      },
      onMove: move => {
        pointer = { x: move.clientX, y: move.clientY };
        if (!frame) frame = requestAnimationFrame(autoScroll);
        clear();
        const slot = slotAt(move);
        if (slot) slot.classList.add(problem(slot) ? 'unit-drop-invalid' : 'unit-drop-target');
      },
      onDrop: async up => {
        const slot = slotAt(up);
        if (!slot) return;
        const status = section.querySelector('[data-status]');
        const say = message => { if (status) status.textContent = message; };
        const issue = problem(slot);
        // Gleicher Tag beim Verschieben ist kein Fehler, nur eine Nicht-Aktion.
        if (issue) { say(issue); return; }
        if (isBlocked(unit)) { say('Bitte zuerst die offenen Änderungen der Einheit speichern.'); return; }
        try {
          if (moving) await moveAndReport({ api, unit, from, to: slot._planningEvent, reload, notify });
          else await assignAndReport({ api, unit, event: slot._planningEvent, reload, notify });
        } catch (error) { say(error.status === 409 ? conflictText : error.message); }
      },
      onEnd: () => {
        pointer = null; if (frame) cancelAnimationFrame(frame); frame = 0;
        clear(); holder.classList.remove('unit-dragging'); section.classList.remove('is-dragging-unit');
        setTimeout(() => { suppressClick = false; }, 0);
      },
    });
  });
}
