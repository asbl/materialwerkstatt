// Monats- und Agendaansicht samt Bindung an die Kalender-Werkzeugleiste.

import { escapeHtml } from "/static/ui-utils.js";
import { attachCalendarToolbar } from "/static/plugins/calendar.js";
import { openCreateEvent, openEventModal } from "./event-form.js";
import { addMonths, dayLabel, eventChip, eventColor, firstOfMonth, isoDate, lessonHint, monthLabel, parseIsoDate, relativeTaskDate, timeLabel, unitHintsHtml, weekdayHeadingLabel } from "./format.js";
import { addVisibilityButton, openSettings } from "./settings.js";
import { WEEKDAYS, store, today } from "./store.js";
import { eventsOn, fetchEvents, findByKey, refreshStatus, renderSourceErrors, renderStatusLine, syncNow } from "./sync.js";
import { loadToday } from "./today.js";

// ------------------------------------------------------------- Monatsansicht

function renderMonth(section) {
  const cursor = store.monthCursor;
  const grid = section.querySelector("[data-kal=grid]");
  const month = firstOfMonth(cursor);
  section.querySelector("[data-kal=month]").textContent = monthLabel(month);
  const offset = (month.getDay() + 6) % 7;
  const start = new Date(month.getFullYear(), month.getMonth(), 1 - offset);
  const cells = [];
  for (let index = 0; index < 42; index += 1) {
    const day = new Date(start.getFullYear(), start.getMonth(), start.getDate() + index);
    const events = eventsOn(day);
    const inMonth = day.getMonth() === month.getMonth();
    const isToday = isoDate(day) === isoDate(today());
    const chips = events.slice(0, 3).map((event) => eventChip(event, { startDay: isoDate(day) })).join("");
    cells.push(`<button type="button" class="kal-cell${inMonth ? "" : " outside"}${isToday ? " today" : ""}"
      data-kal-day="${isoDate(day)}" aria-label="${dayLabel(day)}"><span class="kal-day-number">${day.getDate()}</span>
      <span class="kal-cell-events">${chips}${events.length > 3 ? `<span class="kal-more">+${events.length - 3}</span>` : ""}</span></button>`);
  }
  grid.innerHTML = `<div class="kal-weekdays">${WEEKDAYS.map((name) => `<span>${name}</span>`).join("")}</div>
    <div class="kal-days">${cells.join("")}</div>`;
}

function dayCreateActions(day) {
  return `<span class="kal-day-create-actions"><button type="button" class="kal-quiet" data-kal-create="${day}" aria-label="Termin an diesem Tag erstellen">+ Termin</button><button type="button" class="kal-quiet" data-kal-create-todo="${day}" aria-label="TODO an diesem Tag erstellen">+ TODO</button></span>`;
}

function renderDayList(section, day) {
  const list = section.querySelector("[data-kal=daylist]");
  const events = eventsOn(parseIsoDate(day));
  list.hidden = false;
  list.innerHTML = `<h4>${weekdayHeadingLabel(day)} ${dayCreateActions(day)}</h4>
    ${events.map((event) => `<div class="kal-agenda-entry" style="--kal-event: ${eventColor(event)}"
      data-event-key="${escapeHtml(event.key)}"><span class="kal-agenda-time">${escapeHtml(timeLabel(event))}</span>
      <span class="kal-agenda-title"><button type="button" class="kal-event-title">${escapeHtml(event.title)}</button>${event.kind === 'todo' ? `<small class="muted">${escapeHtml(event.startDate ? `${event.startDate < isoDate(today()) ? 'Überfällig seit' : 'Fällig:'} ${relativeTaskDate(event.startDate)}` : 'Ohne Frist')}${event.plannedDate ? ` · Geplant: ${escapeHtml(relativeTaskDate(event.plannedDate))}` : ''}${event.lesson && lessonHint(event.lesson) ? ` · ${escapeHtml(lessonHint(event.lesson))}` : ''}</small>` : ''}${unitHintsHtml(event.units)}</span>
      ${event.location ? `<span class="kal-agenda-where">${escapeHtml(event.location)}</span>` : ""}</div>`).join("")}`;
}

function mountCalendarMenu(section, actions) {
  const menu = document.createElement('details');
  menu.className = 'kal-tools';
  menu.innerHTML = '<summary aria-label="Weitere Kalenderaktionen">Mehr</summary>';
  actions.replaceWith(menu);
  menu.append(actions);
  const status = section.querySelector('[data-kal=status]');
  if (status) {
    status.classList.add('kal-menu-status');
    actions.append(status);
  }
  section.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.open) {
      event.stopPropagation();
      menu.open = false;
      menu.querySelector('summary').focus();
    }
  });
  menu.addEventListener('focusout', event => {
    if (event.relatedTarget && !menu.contains(event.relatedTarget)) menu.open = false;
  });
  actions.addEventListener('click', event => {
    if (event.target.closest('button')) menu.open = false;
  });
}

export function bindCalendarView(ctx, section) {
  attachCalendarToolbar(section, () => refreshCalendarViews(ctx));
  document.dispatchEvent(new CustomEvent("material-ui:calendar-toolbar", {
    detail: { section, refresh: () => refreshCalendarViews(ctx) },
  }));
  const actions = section.querySelector('.kal-actions');
  addVisibilityButton(ctx, actions);
  mountCalendarMenu(section, actions);
  store.statusLine = section.querySelector("[data-kal=status]");
  section.querySelector("[data-kal=prev]").addEventListener("click", () => {
    store.monthCursor = addMonths(store.monthCursor, -1);
    loadMonth(ctx, section);
  });
  section.querySelector("[data-kal=next]").addEventListener("click", () => {
    store.monthCursor = addMonths(store.monthCursor, 1);
    loadMonth(ctx, section);
  });
  section.querySelector("[data-kal=today]").addEventListener("click", () => {
    store.monthCursor = firstOfMonth(today());
    loadMonth(ctx, section);
  });
  section.querySelector("[data-kal=sync]").addEventListener("click", () => syncNow(ctx, () => loadMonth(ctx, section)));
  section.querySelector("[data-kal=settings]").addEventListener("click", () => openSettings(ctx, () => {
    refreshStatus(ctx).then(renderStatusLine);
    loadMonth(ctx, section);
  }));
  section.querySelector("[data-kal=grid]").addEventListener("click", async (event) => {
    const chip = event.target.closest("[data-event-key]");
    if (chip) {
      await fetchEventsForMonth(ctx, store.monthCursor).catch(() => []);
      openEventModal(ctx, findByKey(chip.dataset.eventKey));
      return;
    }
    const cell = event.target.closest("[data-kal-day]");
    if (cell) renderDayList(section, cell.dataset.kalDay);
  });
  section.querySelector("[data-kal=daylist]").addEventListener("click", (event) => {
    const unit = event.target.closest('[data-kal-unit]');
    if (unit) {
      if (store.calendarModal?.classList.contains('open')) ctx.ui.closeModal(store.calendarModal);
      document.dispatchEvent(new CustomEvent('material-ui:open-unit', { detail: unit.dataset.kalUnit }));
      return;
    }
    const entry = event.target.closest("[data-event-key]");
    if (entry) openEventModal(ctx, findByKey(entry.dataset.eventKey));
    const create = event.target.closest('[data-kal-create]');
    if (create) openCreateEvent(ctx, create.dataset.kalCreate);
    const createTodo = event.target.closest('[data-kal-create-todo]');
    if (createTodo) openCreateEvent(ctx, createTodo.dataset.kalCreateTodo, 'todo');
  });
}

async function fetchEventsForMonth(ctx, cursor) {
  const month = firstOfMonth(cursor);
  const end = new Date(month.getFullYear(), month.getMonth() + 1, 0);
  return fetchEvents(ctx, isoDate(new Date(month.getFullYear(), month.getMonth(), month.getDate() - 7)),
    isoDate(new Date(end.getFullYear(), end.getMonth(), end.getDate() + 7)));
}

export async function loadMonth(ctx, section) {
  try {
    await fetchEventsForMonth(ctx, store.monthCursor);
  } catch (error) {
    ctx.ui.setStatus(`Termine konnten nicht geladen werden: ${error.message}`, "error");
    return;
  }
  renderSourceErrors(section);
  renderMonth(section);
}

// ---------------------------------------------------------------- Agenda

function agendaGroups() {
  const start = store.agendaStart;
  const days = [];
  for (let index = 0; index < store.agendaDays; index += 1) {
    days.push(new Date(start.getFullYear(), start.getMonth(), start.getDate() + index));
  }
  const taskKeys = new Set(store.agendaTasks.map(task => task.key));
  const groups = [];
  for (const day of days) {
    const dayKey = isoDate(day);
    const events = eventsOn(day).filter((event) => !taskKeys.has(event.key) && event.startDate === dayKey);
    for (const task of store.agendaTasks) {
      const assigned = task.plannedDate || task.startDate || isoDate(today());
      const displayDay = assigned < isoDate(today()) ? isoDate(today()) : assigned;
      if (displayDay === dayKey) events.push(task);
    }
    groups.push({ day, events });
  }
  return groups;
}

function agendaGroupHeading(day) {
  return isoDate(day) === isoDate(today()) ? "Heute"
    : isoDate(day) === isoDate(new Date(today().getFullYear(), today().getMonth(), today().getDate() + 1)) ? "Morgen"
      : day.toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "long" });
}

function renderAgenda(section) {
  const list = section.querySelector("[data-kal=agenda]");
  const groups = agendaGroups();
  const html = groups.map((group) => {
    const heading = `<h4 class="kal-agenda-day${isoDate(group.day) === isoDate(today()) ? " today" : ""}">${agendaGroupHeading(group.day)} ${dayCreateActions(isoDate(group.day))}${group.events.length === 0 ? "" : ` <span class="tag-count">${group.events.length}</span>`}</h4>`;
    const entries = group.events.map((event) => `<div class="kal-agenda-entry"
      style="--kal-event: ${eventColor(event)}"
      data-event-key="${escapeHtml(event.key)}">
      <span class="kal-agenda-time">${escapeHtml(timeLabel(event))}${event.endDate > event.startDate ? ` – bis ${dayLabel(parseIsoDate(event.endDate))}` : ""}</span>
      <span class="kal-agenda-title"><button type="button" class="kal-event-title">${escapeHtml(event.title)}</button>${event.kind === 'todo' ? `<small class="muted">${escapeHtml(event.startDate ? `${event.startDate < isoDate(today()) ? 'Überfällig seit' : 'Fällig:'} ${relativeTaskDate(event.startDate)}` : 'Ohne Frist')}${event.plannedDate ? ` · Geplant: ${escapeHtml(relativeTaskDate(event.plannedDate))}` : ''}${event.lesson && lessonHint(event.lesson) ? ` · ${escapeHtml(lessonHint(event.lesson))}` : ''}</small>` : ''}${unitHintsHtml(event.units)}</span>
      ${event.location ? `<span class="kal-agenda-where">${escapeHtml(event.location)}</span>` : ""}</div>`).join("");
    return `${heading}<div class="kal-agenda-events${group.events.length ? "" : " empty"}">${entries || ""}</div>`;
  }).join("");
  list.innerHTML = html;
}

export async function loadAgenda(ctx, section) {
  const start = store.agendaStart;
  const end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + store.agendaDays - 1);
  section.querySelector('[data-kal=agenda-jump]').value = isoDate(start);
  section.querySelector('[data-kal=agenda-days]').value = String(store.agendaDays);
  try {
    const [, tasks] = await Promise.all([
      fetchEvents(ctx, isoDate(start), isoDate(end)),
      ctx.api('/api/plugins/kalender/tasks'),
    ]);
    store.agendaTasks = tasks.tasks || [];
  } catch (error) {
    ctx.ui.setStatus(`Termine konnten nicht geladen werden: ${error.message}`, "error");
    return;
  }
  renderSourceErrors(section);
  renderAgenda(section);
}

export function bindAgendaView(ctx, section) {
  attachCalendarToolbar(section, () => refreshCalendarViews(ctx));
  document.dispatchEvent(new CustomEvent("material-ui:calendar-toolbar", {
    detail: { section, refresh: () => refreshCalendarViews(ctx) },
  }));
  const actions = section.querySelector('.kal-actions');
  addVisibilityButton(ctx, actions);
  mountCalendarMenu(section, actions);
  store.statusLine = section.querySelector("[data-kal=status]");
  section.querySelector("[data-kal=agenda-days]").addEventListener("change", (event) => {
    store.agendaDays = Number(event.target.value) || 14;
    loadAgenda(ctx, section);
  });
  section.querySelector("[data-kal=agenda-jump]").addEventListener("change", (event) => {
    const value = event.target.value;
    if (value) store.agendaStart = parseIsoDate(value);
    loadAgenda(ctx, section);
  });
  section.querySelector("[data-kal=sync]").addEventListener("click", () => syncNow(ctx, () => loadAgenda(ctx, section)));
  section.querySelector("[data-kal=settings]").addEventListener("click", () => openSettings(ctx, () => {
    refreshStatus(ctx).then(renderStatusLine);
    loadAgenda(ctx, section);
  }));
  section.querySelector("[data-kal=agenda-today]").addEventListener("click", () => {
    store.agendaStart = today();
    loadAgenda(ctx, section);
  });
  section.querySelector("[data-kal=agenda]").addEventListener("click", (event) => {
    const unit = event.target.closest('[data-kal-unit]');
    if (unit) {
      if (store.calendarModal?.classList.contains('open')) ctx.ui.closeModal(store.calendarModal);
      document.dispatchEvent(new CustomEvent('material-ui:open-unit', { detail: unit.dataset.kalUnit }));
      return;
    }
    const entry = event.target.closest("[data-event-key]");
    if (entry) openEventModal(ctx, findByKey(entry.dataset.eventKey));
    const create = event.target.closest('[data-kal-create]');
    if (create) openCreateEvent(ctx, create.dataset.kalCreate);
    const createTodo = event.target.closest('[data-kal-create-todo]');
    if (createTodo) openCreateEvent(ctx, createTodo.dataset.kalCreateTodo, 'todo');
  });
}

export async function refreshCalendarViews(ctx) {
  if (store.kalenderSection) await loadMonth(ctx, store.kalenderSection);
  if (store.agendaSection) await loadAgenda(ctx, store.agendaSection);
  await loadToday(ctx);
}