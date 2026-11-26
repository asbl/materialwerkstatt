// Heute-Seite: Stunden, Termine, TODOs und Umschalter heute/morgen.

import { escapeHtml } from "/static/ui-utils.js";
import { applyCreateButtonLabel } from "./event-form.js";
import { eventColor, isoDate, lessonHint, relativeTaskDate, timeLabel, unitHintsHtml, weekdayHeadingLabel } from "./format.js";
import { setVisibility } from "./settings.js";
import { TODAY_MODE_KEY, modeLabel, modeTitle, store, today, viewDay } from "./store.js";
import { refreshCalendarViews } from "./views.js";

// Heute liest alle offenen Aufgaben unabhängig vom Kalenderzeitfenster.
let todayLoading = false;
let todayReloadRequested = false;
function taskRow(task, day) {
  const completed = task.status === 'COMPLETED';
  const overdue = !completed && task.startDate && task.startDate < day;
  const deadline = task.startDate ? (overdue ? `Überfällig seit ${relativeTaskDate(task.startDate)}` : `Fällig: ${relativeTaskDate(task.startDate)}`) : 'Ohne Frist';
  const lesson = lessonHint(task.lesson);
  return `<div class="kal-task${completed ? ' kal-task-completed' : ''}${overdue ? ' kal-task-overdue' : ''}" data-task-id="${escapeHtml(task.id)}">
    <input type="checkbox" class="kal-task-complete" data-task-action="complete" ${completed ? 'checked disabled' : ''} title="${completed ? 'Erledigt' : 'Erledigen'}" aria-label="${escapeHtml(task.title)} erledigen">
    <div class="kal-task-content"><button type="button" class="kal-event-title" data-event-key="${escapeHtml(task.key)}">${escapeHtml(task.title)}</button>
    <small><span class="kal-task-deadline" title="${escapeHtml(task.startDate || '')}">${escapeHtml(deadline)}</span>${task.plannedDate ? ` · Geplant: ${escapeHtml(relativeTaskDate(task.plannedDate))}` : ''} · ${escapeHtml(task.calendar)}${lesson ? ` · ${escapeHtml(lesson)}` : ''}</small>
    ${task.unitPath ? `<button type="button" class="kal-unit-hint" data-kal-unit="${escapeHtml(task.unitPath)}">Unterrichtseinheit öffnen ↗</button>` : ''}
    ${completed ? '<small>Erledigt</small>' : `<div class="kal-task-actions">${task.plannedDate !== day ? `<button type="button" data-task-action="today">${modeTitle()} einplanen</button>` : `<span class="kal-task-planned">${modeTitle()} eingeplant</span>`}
    <details class="kal-task-plan"><summary aria-label="${escapeHtml(task.title)} einplanen">Anderen Tag planen</summary><label>TODO einplanen am <input type="date" data-task-plan value="${escapeHtml(task.plannedDate || '')}" aria-label="${escapeHtml(task.title)} einplanen"></label></details><button type="button" class="kal-quiet" data-task-action="hide">Ausblenden</button></div>`}</div>
    </div>`;
}
// Kompakter Stundenplan des angezeigten Tages; Ausfall und Einheiten-Verknüpfung
// kommen aus dem Terminabgleich (events) und werden per Schluessel zusammengeführt.
function renderTodayLessons(section, lessons) {
  const block = section.querySelector('[data-today-lessons-section]');
  const wrap = section.querySelector('[data-today-lessons]');
  block.hidden = !lessons.length;
  if (!lessons.length) { wrap.replaceChildren(); return; }
  const eventsByKey = new Map(store.todayEvents.map(event => [event.key, event]));
  wrap.innerHTML = lessons.map((lesson) => {
    const event = eventsByKey.get(lesson.key);
    const cancelled = Boolean(event && event.cancelled);
    const start = lesson.start.slice(11, 16);
    const end = (lesson.end || '').slice(11, 16);
    const teaching = event?.teaching
      ? [event.teaching.lerngruppe, event.teaching.fach].filter(Boolean).join(' · ') : '';
    return `<div class="kal-lesson${cancelled ? ' kal-lesson-cancelled' : ''}" data-event-key="${escapeHtml(lesson.key)}">
      <span class="kal-lesson-time">${escapeHtml(start)}${end ? `–${escapeHtml(end)}` : ''}</span>
      <button type="button" class="kal-event-title">${escapeHtml(lesson.title)}</button>
      ${teaching ? `<span class="kal-lesson-meta">${escapeHtml(teaching)}</span>` : ''}
      ${lesson.location ? `<span class="kal-lesson-meta">${escapeHtml(lesson.location)}</span>` : ''}
      ${cancelled ? '<span class="kal-lesson-cancelled-tag">Ausfall</span>' : ''}
      ${unitHintsHtml(event?.units)}
      ${store.canAssignUnit && event?.teaching?.klasse && !cancelled && !(event.units || []).length
        ? '<button type="button" class="kal-unit-hint kal-assign-hint" data-kal-assign aria-expanded="false" title="Bestehende Einheit dieser Stunde zuweisen">Einheit zuweisen</button>' : ''}
    </div>`;
  }).join('');
}

function renderTodayEvents(events, day) {
  const now = new Date();
  const isToday = day === isoDate(today());
  const timed = events.filter(e => !e.allDay).sort((a, b) => a.start.localeCompare(b.start));
  const next = isToday ? timed.find(e => new Date(e.start) > now) : null;
  return [...events.filter(e => e.allDay), ...timed].map(event => {
    const running = isToday && !event.allDay && new Date(event.start) <= now && event.end && new Date(event.end) > now;
    const past = isToday && !event.allDay && new Date(event.end || event.start) <= now;
    const state = event.cancelled ? 'Ausfall' : running ? 'Läuft gerade' : event === next ? 'Als Nächstes' : '';
    const end = !event.allDay && event.end && event.end !== event.start ? `–${event.end.slice(11, 16)}` : '';
    return `<div class="kal-agenda-entry kal-today-event${event.cancelled ? ' kal-event-cancelled' : ''}${past ? ' kal-event-past' : ''}${state && !event.cancelled ? ' kal-event-current' : ''}" style="--kal-event: ${eventColor(event)}" data-event-key="${escapeHtml(event.key)}">
      <span class="kal-agenda-time">${escapeHtml(timeLabel(event))}${escapeHtml(end)}</span>
      <div class="kal-today-event-content">${state ? `<span class="kal-event-state">${state}</span>` : ''}<button type="button" class="kal-event-title">${escapeHtml(event.title)}</button>
      <small class="kal-today-event-meta">${escapeHtml([event.location, event.calendar].filter(Boolean).join(' · '))}</small>
      ${unitHintsHtml(event.units)}</div></div>`;
  }).join('') || '<p class="muted">Heute keine Termine.</p>';
}
export async function loadToday(ctx) {
  if (todayLoading) { todayReloadRequested = true; return; }
  todayLoading = true;
  try {
    // Das Rail-Badge zaehlt immer "heute"; die geoeffnete Seite rechnet relativ
    // zum umschaltbaren Ansichtstag (heute/morgen).
    const todayKey = isoDate(today());
    const day = isoDate(viewDay());
    // Aufgaben/Badge kommen guenstig aus dem lokalen CalDAV-Cache und laufen deshalb bei
    // jedem Takt mit, auch wenn "Heute" gerade nicht sichtbar ist. Termine ziehen
    // zusaetzlich externe Kalenderquellen live und den Einheiten-Abgleich; das lohnt sich
    // nur, waehrend die Ansicht tatsaechlich offen ist.
    const data = await ctx.api('/api/plugins/kalender/tasks');
    store.tasks = data.tasks || [];
    const badgeOverdue = store.tasks.filter(t => t.startDate && t.startDate < todayKey);
    const badgeDue = store.tasks.filter(t => t.startDate === todayKey || (t.plannedDate && t.plannedDate <= todayKey));
    const badgeCount = new Set([...badgeOverdue, ...badgeDue].map(t => t.id)).size;
    const label = `Heute: ${badgeCount} offen · ${badgeOverdue.length} überfällig`;
    if (store.todayHandle?.button) {
      store.todayHandle.button.title = label;
      store.todayHandle.button.setAttribute('aria-label', label);
      let badge = store.todayHandle.button.querySelector('.kal-today-badge');
      if (!badge) { badge = document.createElement('span'); badge.className = 'kal-today-badge'; store.todayHandle.button.append(badge); }
      badge.textContent = String(badgeCount); badge.hidden = !badgeCount;
    }
    const section = store.todaySection;
    if (!section || section.hidden) return;
    const [events, status, lessonsData] = await Promise.all([
      ctx.api(`/api/plugins/kalender/events?from=${day}&to=${day}`),
      ctx.api('/api/plugins/kalender/status'),
      ctx.api(`/api/plugins/kalender/lessons?date=${encodeURIComponent(day)}`),
    ]);
    store.todayEvents = events.events || [];
    store.todayLessons = lessonsData.lessons || [];
    const overdue = store.tasks.filter(t => t.startDate && t.startDate < day);
    const due = store.tasks.filter(t => t.startDate === day || (t.plannedDate && t.plannedDate <= day));
    const count = new Set([...overdue, ...due].map(t => t.id)).size;
    const groups = [
      ['Überfällig', overdue],
      [`${modeTitle()} fällig / eingeplant`, due.filter(t => !overdue.includes(t))],
      ['Eingang · ohne Datum', store.tasks.filter(t => !t.startDate && !t.plannedDate)],
      ['Heute erledigt', data.completedTasks || []],
      ['Später', store.tasks.filter(t => !overdue.includes(t) && !due.includes(t) && (t.startDate || t.plannedDate))],
    ];
    section.querySelector('[data-today-title]').textContent = modeTitle();
    section.querySelector('#kalTodayLessonsTitle').textContent = store.todayMode === 'morgen' ? 'Morgige Unterrichtsstunden' : 'Heutige Unterrichtsstunden';
    section.querySelector('#kalTodayEventsTitle').textContent = store.todayMode === 'morgen' ? 'Morgige Termine' : 'Heutige Termine';
    section.querySelector('[data-today-summary]').textContent = `${count} offene Aufgaben für ${modeLabel()} · ${overdue.length} überfällig`;
    section.querySelector('[data-today-date]').textContent = weekdayHeadingLabel(day);
    section.querySelector('[data-today-tasks]').setAttribute('aria-busy', 'false');
    const signature = JSON.stringify([day, store.tasks, data.completedTasks]);
    if (store.todayTaskSignature !== signature) {
      section.querySelector('[data-today-tasks]').innerHTML = groups.map(([title, tasks]) => {
        const heading = `${title} <span class="tag-count">${tasks.length}</span>`;
        const rows = tasks.map(task => taskRow(task, day)).join('') || '<p class="muted">Keine offenen Aufgaben.</p>';
        if (!tasks.length) return '';
        return title === 'Später' || title === 'Eingang · ohne Datum' ? `<details class="kal-task-group"><summary>${heading}</summary>${rows}</details>`
          : `<section class="kal-task-group"><h3>${heading}</h3>${rows}</section>`;
      }).join('') || '<p class="muted">Keine offenen Aufgaben.</p>';
      store.todayTaskSignature = signature;
    }
    renderTodayLessons(section, store.todayLessons);
    section.querySelector('[data-today-events]').innerHTML = renderTodayEvents(store.todayEvents.filter(e => e.kind !== 'todo'), day);
    section.querySelector('[data-today-sync]').textContent = status.syncRunning ? 'Kalender wird aktualisiert …' : status.lastSync?.ok === false ? status.lastSync.message : status.lastSuccessfulSync ? `Letzter erfolgreicher Abgleich: ${new Date(status.lastSuccessfulSync * 1000).toLocaleString('de-DE')}` : 'Noch kein Kalenderabgleich. Lokale Aufgaben sind verfügbar.';
    section.querySelector('[data-today-errors]').textContent = [...(events.sourceErrors || []), ...(lessonsData.sourceErrors || [])].map(e => `${e.name}: ${e.message}`).join(' ');
  } catch (error) {
    const section = store.todaySection;
    section?.querySelector('[data-today-tasks]').setAttribute('aria-busy', 'false');
    if (section) section.querySelector('[data-today-errors]').textContent = `Heute konnte nicht aktualisiert werden: ${error.message}`;
    ctx.ui.setStatus(`Heute konnte nicht aktualisiert werden: ${error.message}`, 'error');
  } finally {
    todayLoading = false;
    if (todayReloadRequested) { todayReloadRequested = false; loadToday(ctx); }
  }
}
export async function changeTask(ctx, element, action, plannedDate = '') {
  const row = element.closest('[data-task-id]');
  if (!row || row.dataset.busy) return;
  row.dataset.busy = 'true';
  row.querySelectorAll('button, input').forEach(el => { el.disabled = true; });
  try {
    if (action === 'hide') {
      const task = store.tasks.find(t => t.id === row.dataset.taskId);
      await setVisibility(ctx, 'entries', row.dataset.taskId, true, task?.title || 'TODO');
      return;
    }
    await ctx.api('/api/plugins/kalender/tasks', {method: 'POST', body: JSON.stringify({id: row.dataset.taskId, action, plannedDate})});
    await refreshCalendarViews(ctx);
  } catch (error) {
    if (element.type === 'checkbox') element.checked = false;
    // Fehlgeschlagenes Einplanen: Eingabefeld auf den bestätigten Stand zurücksetzen
    // und Neuzeichnen erzwingen, damit das abgelehnte Datum nicht stehen bleibt.
    if (element.matches('[data-task-plan]')) {
      const task = store.tasks.find(t => t.id === row.dataset.taskId);
      element.value = task?.plannedDate || '';
      store.todayTaskSignature = '';
    }
    ctx.ui.setStatus(error.message, 'error');
  }
  finally { delete row.dataset.busy; row.querySelectorAll('button, input').forEach(el => { el.disabled = false; }); }
}

export function setTodayMode(ctx, mode) {
  store.todayMode = mode === 'morgen' ? 'morgen' : 'heute';
  try { localStorage.setItem(TODAY_MODE_KEY, store.todayMode); } catch { /* ohne lokalen Speicher */ }
  const section = store.todaySection;
  if (section) {
    for (const button of section.querySelectorAll('[data-today-mode]')) {
      const active = button.dataset.todayMode === store.todayMode;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    }
    for (const button of section.querySelectorAll('[data-create-for-today]')) applyCreateButtonLabel(button);
  }
  loadToday(ctx);
}