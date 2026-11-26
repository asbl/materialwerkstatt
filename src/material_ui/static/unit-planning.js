import { escapeHtml as esc } from './ui-utils.js';

// Evaluate the complete teaching year, independent of the selected Q semester.
export function teachingYearFinished(events, holidayDays, now = new Date()) {
  const today = now.toLocaleDateString('sv-SE');
  const first = Number(today.slice(0, 4)) - (today.slice(5, 7) < '08' ? 1 : 0);
  const lessons = events.filter(event => event.teaching && !event.cancelled && !event.holiday
    && !holidayDays.has(event.startDate) && event.startDate >= `${first}-08-01`
    && event.startDate <= `${first + 1}-07-31`);
  if (!lessons.length) return false;
  return lessons.every(event => {
    const end = new Date(event.allDay ? `${event.endDate || event.startDate}T23:59:59` : event.end);
    return Number.isFinite(end.getTime()) && end.getTime() < now.getTime();
  });
}

// Planungsdaten werden pro Ansicht gecacht: Filterwechsel in der Einheiten-Uebersicht
// feuern keine erneuten Kalender-Requests. load() leert den Cache (clearUnitPlanningCache).
const planningCache = new Map();
export function clearUnitPlanningCache() { planningCache.clear(); }
function cached(key, load) {
  if (!planningCache.has(key)) {
    // Fehlgeschlagene Requests nicht dauerhaft cachen: naechster render() versucht es erneut.
    const promise = load().catch(error => { planningCache.delete(key); throw error; });
    planningCache.set(key, promise);
  }
  return planningCache.get(key);
}

// Enrich the existing unit tree; never render a second calendar alongside it.
export async function renderUnitPlanning({ host, api, schoolClass, schoolYear, schoolTerm, create, assign = null, move = null, watchDetails }) {
  const today = new Date().toLocaleDateString('sv-SE');
  const startYear = Number(schoolYear.split('/')[0]) || Number(today.slice(0, 4)) - (today.slice(5, 7) < '08' ? 1 : 0);
  const from = schoolYear ? `${startYear}-08-01` : today;
  let to = schoolYear ? `${startYear + 1}-08-01` : `${startYear + 1}-07-31`;
  const queryFrom = schoolYear ? from : `${startYear}-08-01`;
  try {
    const results = await Promise.allSettled([
      cached(`events:${queryFrom}:${to}`, () => api(`/api/plugins/kalender/events?from=${queryFrom}&to=${to}`)),
      cached(`holidays:${queryFrom}:${to}`, () => api(`/api/plugins/kalender/holidays?from=${queryFrom}&to=${to}`)),
      // Trenner sind lokaler Plugin-Speicher und muessen externe Aenderungen
      // (anderes Fenster, direkter Dateizugriff) ohne Cache-Leerung zeigen.
      api('/api/plugins/kalender/planning-markers'),
    ]);
    let nextUnavailable = false;
    // Lokal mergen, damit gecachte Antworten nicht mutiert werden.
    let payload = results[0].status === 'fulfilled' ? results[0].value : { events: [] };
    let holidays = results[1].status === 'fulfilled' ? results[1].value : { days: [] };
    if (!schoolYear && results[0].status === 'fulfilled' && results[1].status === 'fulfilled'
      && !results[0].value.sourceErrors?.length
      && teachingYearFinished(results[0].value.events, new Set(results[1].value.days))) {
      // Unlock the following year only after the final actual lesson has ended.
      to = `${startYear + 2}-07-31`;
      const nextFrom = `${startYear + 1}-08-01`;
      const next = await Promise.allSettled([
        cached(`events:${nextFrom}:${to}`, () => api(`/api/plugins/kalender/events?from=${nextFrom}&to=${to}`)),
        cached(`holidays:${nextFrom}:${to}`, () => api(`/api/plugins/kalender/holidays?from=${nextFrom}&to=${to}`)),
      ]);
      for (const [index, field] of [[0, 'events'], [1, 'days']]) {
        if (next[index].status === 'fulfilled') {
          const base = index === 0 ? payload : holidays;
          const merged = { ...base, [field]: [...(base[field] || []), ...next[index].value[field]] };
          if (index === 0) merged.sourceErrors = [...(base.sourceErrors || []), ...(next[0].value.sourceErrors || [])];
          if (index === 0) payload = merged; else holidays = merged;
        } else nextUnavailable = true;
      }
    }
    if (!host.isConnected) return;
    const markers = results[2].status === 'fulfilled' ? results[2].value : { rows: [] };
    const unavailable = nextUnavailable || results.some(result => result.status === 'rejected');
    const openDays = new Set(host._planningOpen || []);
    for (const node of host.querySelectorAll('.unit-plan-day[open]')) openDays.add(node.dataset.planKey);
    host._planningOpen = openDays;
    host.querySelectorAll('[data-planning-entry]').forEach(node => node.remove());
    const holidayDays = new Set(holidays.days);
    const events = payload.events.filter(event => event.startDate >= from && event.startDate <= to && !event.holiday && !holidayDays.has(event.startDate)
      && event.teaching?.klasse === schoolClass && (!schoolTerm ||
      (Number(event.startDate.slice(5, 7)) >= 2 && Number(event.startDate.slice(5, 7)) <= 7 ? '2' : '1') === schoolTerm));
    const label = (day, withYear = false) => new Date(`${day}T12:00:00`).toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit', ...(withYear ? { year: 'numeric' } : {}) });
    const status = document.createElement('p'); status.dataset.planningEntry = ''; status.className = 'unit-empty'; status.setAttribute('role', 'status');
    function slots(entries, parent, free = false, unitPath = '') {
      for (const event of entries) {
        const row = document.createElement('div');
        row.className = `unit-plan-slot${event.cancelled ? ' is-cancelled' : ''}`;
        const time = event.start && !event.allDay ? new Date(event.start).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }) : '';
        row.innerHTML = `<span>${esc(time)} ${esc(event.title)}${event.cancelled ? ' · Ausfall' : ''}</span>
          <span class="unit-plan-actions">${!free && move && unitPath && !event.cancelled ? '<span class="unit-move-handle" aria-hidden="true" title="Auf eine freie Stunde ziehen"></span><button type="button" class="unit-edit" data-move aria-expanded="false">Verschieben</button>' : ''}${free && assign ? `<button type="button" class="unit-edit" data-assign aria-expanded="false" ${event.cancelled ? 'disabled' : ''}>Einheit zuweisen</button>` : ''}<button type="button" class="unit-edit" data-create ${event.cancelled ? 'disabled' : ''}>+ Lerneinheit</button>
          <button type="button" class="unit-edit" data-cancel aria-pressed="${event.cancelled}">${event.cancelled ? 'Ausfall aufheben' : 'Ausfall'}</button></span>`;
        row.querySelector('[data-create]').onclick = () => create(event);
        if (free && !event.cancelled && assign) { row._planningEvent = event; row.dataset.freeSlot = ''; }
        if (!free && move && unitPath && !event.cancelled) row._planningEvent = event;
        const moveButton = row.querySelector('[data-move]');
        if (moveButton) moveButton.onclick = () => move(event, row, moveButton, unitPath);
        const assignButton = row.querySelector('[data-assign]');
        if (assignButton) assignButton.onclick = () => assign(event, row, assignButton);
        const cancel = row.querySelector('[data-cancel]');
        cancel.onclick = async () => {
          cancel.disabled = true;
          try {
            await api('/api/plugins/kalender/lesson-cancellation', { method: 'POST', body: JSON.stringify({ id: event.lessonId, datum: event.startDate, cancelled: !event.cancelled }) });
            event.cancelled = !event.cancelled;
            // Preserve the open tree and update every appearance of this occurrence.
            planningCache.clear();
            await renderUnitPlanning({ host, api, schoolClass, schoolYear, schoolTerm, create, assign, move, watchDetails });
          } catch (error) { status.textContent = error.message; cancel.disabled = false; }
        };
        parent.append(row);
      }
    }
    function days(entries, parent, free = false) {
      const grouped = new Map();
      for (const event of entries) {
        if (!grouped.has(event.startDate)) grouped.set(event.startDate, []);
        grouped.get(event.startDate).push(event);
      }
      for (const [day, lessons] of grouped) {
        const details = document.createElement('details');
        details.className = 'unit-plan-day'; details.dataset.planningEntry = ''; details.dataset.planKey = `${parent.dataset.unitPath || 'free'}:${day}`;
        details.dataset.sortDate = day;
        const cancelled = lessons.filter(event => event.cancelled).length;
        const allCancelled = cancelled === lessons.length;
        details.innerHTML = `<summary><time datetime="${esc(day)}">${esc(label(day))}</time><small>${allCancelled ? 'Ausfall' : free ? 'Noch offen' : 'Unterricht'} · ${lessons.length} Std.${cancelled && !allCancelled ? ` · ${cancelled} Ausfall` : ''}</small></summary>`;
        details.open = openDays.has(details.dataset.planKey);
        details.ontoggle = () => { if (details.isConnected) { if (details.open) openDays.add(details.dataset.planKey); else openDays.delete(details.dataset.planKey); } };
        slots(lessons, details, free, parent.dataset.unitPath || ''); parent.append(details);
      }
    }
    // Assigned occurrences live only inside their existing unit card.
    for (const card of host.querySelectorAll('.unit-card')) {
      const assigned = events.filter(event => (event.units || []).some(unit => unit.path === card.dataset.unitPath));
      if (!assigned.length) continue;
      const panel = document.createElement('div'); panel.dataset.planningEntry = ''; panel.className = 'unit-plan-assigned';
      panel.dataset.unitPath = card.dataset.unitPath;
      days(assigned, panel); card.querySelector(':scope > summary').after(panel);
      const cancelled = assigned.filter(event => event.cancelled).length;
      if (cancelled) {
        const badge = document.createElement('small'); badge.dataset.planningEntry = ''; badge.className = 'unit-plan-cancelled';
        badge.textContent = `${cancelled} Ausfall`; card.querySelector(':scope > summary').append(badge);
      }
    }
    // Only future, unassigned days need their own place in the existing list.
    const free = events.filter(event => event.startDate >= today && !(event.units || []).length);
    days(free, host, true);
    for (let y = Number(from.slice(0, 4)); y <= Number(to.slice(0, 4)); y++) {
      for (const [suffix, title] of [['02-01', '2. Halbjahr'], ['08-01', `Schuljahr ${y}/${y + 1}`]]) {
        const day = `${y}-${suffix}`;
        if (day < from || day > to) continue;
        const line = document.createElement('div'); line.dataset.planningEntry = ''; line.dataset.sortDate = day;
        line.className = 'unit-plan-boundary'; line.textContent = `${label(day)} · ${title}`; host.append(line);
      }
    }
    for (const marker of markers.rows) {
      if ((schoolYear && marker.datum < from) || marker.datum > to || (marker.klasse && marker.klasse !== schoolClass)
        || (schoolTerm && (Number(marker.datum.slice(5, 7)) >= 2 && Number(marker.datum.slice(5, 7)) <= 7 ? '2' : '1') !== schoolTerm)) continue;
      const line = document.createElement('div'); line.dataset.planningEntry = ''; line.dataset.sortDate = marker.datum;
      line.className = 'unit-plan-boundary unit-plan-marker'; line.style.setProperty('--marker-color', marker.farbe);
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = `${label(marker.datum, true)} · ${marker.titel}`; button.title = 'Trenner bearbeiten';
      button.onclick = () => editPlanningMarker({ host, api, schoolClass, schoolYear, schoolTerm, create }, marker);
      line.append(button); host.append(line);
    }
    // Rebuild runs from stable topic identities, including previously split topics.
    const previousFocus = document.activeElement;
    const entries = [], owners = new Map(), templates = new Map();
    for (const node of [...host.children]) {
      if (node.matches('.unit-topic, .unit-recurring')) {
        const key = node.dataset.topicKey;
        if (!templates.has(key)) templates.set(key, node);
        for (const card of node.querySelectorAll(':scope > .unit-card')) {
          owners.set(card, key); entries.push(card);
        }
        node.remove();
      } else entries.push(node);
    }
    entries.sort((a, b) => (a.dataset.sortDate || '9999').localeCompare(b.dataset.sortDate || '9999'));
    let previousOwner = null, run = null;
    for (const node of entries) {
      if (!owners.has(node)) { host.append(node); previousOwner = null; continue; }
      const key = owners.get(node);
      if (key !== previousOwner) {
        const template = templates.get(key);
        run = template.cloneNode(false);
        run.removeAttribute('data-state-key');
        run.dataset.sortDate = node.dataset.sortDate;
        const summary = template.querySelector(':scope > summary');
        if (summary) {
          run.append(summary.cloneNode(true));
          watchDetails?.(run, `section:${key}:${node.dataset.unitPath}`, true);
        }
        host.append(run); previousOwner = key;
      }
      run.append(node);
    }
    collapseFreeTail(host, openDays);
    host.append(status);
    // Karten werden beim Neuaufbau kurz aus- und wieder eingehaengt; der
    // Browser verwirft dabei den Fokus auf den Body. Nur in diesem Fall
    // zuruecksetzen, damit nie in laufende Eingaben eingegriffen wird.
    if (previousFocus && previousFocus !== document.body && previousFocus.isConnected
      && document.activeElement === document.body) {
      previousFocus.focus({ preventScroll: true });
    }
    if (unavailable || payload.sourceErrors?.length) status.textContent = 'Kalendertermine teilweise nicht verfügbar.';
  } catch (error) {
    if (host.isConnected) {
      const note = document.createElement('p'); note.className = 'unit-empty'; note.dataset.planningEntry = '';
      note.textContent = `Kalendertermine nicht verfügbar: ${error.message}`; host.append(note);
    }
  }
}

// Nach der letzten Einheit stehen alle freien Stunden bis zum Schuljahresende. Davon bleiben
// die naechsten Termine sichtbar, der Rest klappt hinter einen Knopf: Die Liste bleibt
// kurz, ohne dass Stunden verschwinden (der Knopf nennt die Anzahl).
const FREE_TAIL_VISIBLE = 5;
const FREE_TAIL_THRESHOLD = 8;
function collapseFreeTail(host, openDays) {
  const children = [...host.children];
  let lastRun = -1;
  // Wiederkehrende Gruppen haben kein Datum und stehen ohnehin am Ende der Liste.
  children.forEach((node, index) => { if (node.matches('.unit-topic')) lastRun = index; });
  const days = children.slice(lastRun + 1).filter(node => node.matches('.unit-plan-day'));
  if (days.length <= FREE_TAIL_THRESHOLD) return;
  const hideable = days.slice(FREE_TAIL_VISIBLE).filter(node => !openDays.has(node.dataset.planKey));
  if (!hideable.length) return;
  const expanded = Boolean(host._planningTailExpanded);
  const button = document.createElement('button');
  button.type = 'button'; button.dataset.planningEntry = ''; button.className = 'unit-edit unit-plan-more';
  button.setAttribute('aria-expanded', String(expanded));
  const apply = open => {
    host._planningTailExpanded = open;
    for (const node of hideable) node.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    button.textContent = open ? 'Weniger offene Stunden anzeigen' : `${hideable.length} weitere offene Stunden anzeigen`;
  };
  button.onclick = () => apply(!host._planningTailExpanded);
  apply(expanded);
  // Der Knopf steht hinter der letzten sichtbaren Stunde, nach dem Aufklappen am Ende der Liste.
  days[Math.min(FREE_TAIL_VISIBLE, days.length) - 1].after(button);
}

export function editPlanningMarker(options, marker = null) {
  const { host, api, schoolClass } = options;
  const dialog = document.createElement('dialog');
  dialog.className = 'unit-marker-dialog';
  dialog.innerHTML = `<form><h3>${marker ? 'Trenner bearbeiten' : 'Trenner hinzufügen'}</h3>
    <label>Titel<input name="titel" required maxlength="120" list="unit-marker-titles" value="${esc(marker?.titel || '')}" placeholder="z. B. Notenschluss"></label>
    <datalist id="unit-marker-titles"><option>Notenschluss</option><option>Noteneintragung</option><option>Elternsprechtag</option></datalist>
    <label>Datum<input name="datum" type="date" required value="${esc(marker?.datum || new Date().toLocaleDateString('sv-SE'))}"></label>
    <label>Farbe<input name="farbe" type="color" value="${esc(marker?.farbe || '#d99a36')}"></label>
    <label>Gilt für<select name="klasse"><option value="">Alle Klassen</option>${schoolClass ? `<option value="${esc(schoolClass)}">Klasse ${esc(schoolClass.replace('klasse-', ''))}</option>` : ''}</select></label>
    <p role="status"></p><div class="unit-marker-actions"><button type="submit">Speichern</button>
    <button type="button" data-close>Abbrechen</button>${marker ? '<button type="button" data-delete>Trenner löschen</button>' : ''}</div></form>`;
  const form = dialog.querySelector('form');
  form.elements.klasse.value = marker?.klasse || '';
  dialog.querySelector('[data-close]').onclick = () => dialog.close();
  dialog.addEventListener('close', () => dialog.remove());
  let saving = false;
  async function save(deleting = false) {
    if (saving) return;
    saving = true; form.querySelectorAll('button').forEach(button => { button.disabled = true; });
    try {
      const fields = Object.fromEntries(new FormData(form));
      await api('/api/plugins/kalender/planning-markers', { method: 'POST', body: JSON.stringify({ ...fields, ...(marker ? { id: marker.id, revision: marker.revision } : {}), delete: deleting }) });
      dialog.close();
      document.dispatchEvent(new CustomEvent('material-calendar-refresh'));
      planningCache.clear();
      if (host.isConnected) await renderUnitPlanning(options);
    } catch (error) { form.querySelector('[role=status]').textContent = error.message; }
    finally { saving = false; form.querySelectorAll('button').forEach(button => { button.disabled = false; }); }
  }
  form.onsubmit = event => { event.preventDefault(); save(); };
  dialog.querySelector('[data-delete]')?.addEventListener('click', () => save(true));
  document.body.append(dialog); dialog.showModal(); form.elements.titel.focus();
}
