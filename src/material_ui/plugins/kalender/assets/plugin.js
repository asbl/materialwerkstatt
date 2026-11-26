// Kalender-Plugin: Monatsansicht, Agenda, Heute-Seite, Einstellungs- und Termindialog.
// Kernmodule kommen über die Importmap herein; alle Zugriffe laufen über ctx.api.
// Die Teile liegen in eigenen Modulen (alle im Manifest unter "modules" gelistet):
// store (Zustand), format (Datum/Chips), sync (Abgleich/Status), settings (Einstellungen,
// Sichtbarkeit), event-form (Termin anzeigen/anlegen), views (Monat/Agenda), today (Heute).

import { attachCalendarToolbar } from "/static/plugins/calendar.js";
import { addCreateButton, openCreateEvent, openEventModal } from "./event-form.js";
import { firstOfMonth, isoDate } from "./format.js";
import { addVisibilityButton } from "./settings.js";
import { store, today, viewDay } from "./store.js";
import { findByKey, refreshStatus, renderStatusLine, syncNow } from "./sync.js";
import { changeTask, loadToday, setTodayMode } from "./today.js";
import { bindAgendaView, bindCalendarView, loadAgenda, loadMonth, refreshCalendarViews } from "./views.js";

// ------------------------------------------------------------- Registrierung

export function register(ctx) {
  // Material-Knöpfe aus Heute, Monatsliste und Agenda: Im Capture-Schritt abfangen, damit
  // die darunterliegenden Zeilen-Handler (Termin-Dialog) nicht zusätzlich auslösen.
  document.addEventListener('click', event => {
    const material = event.target.closest?.('[data-kal-material]');
    if (!material) return;
    event.stopPropagation();
    if (store.calendarModal?.classList.contains('open')) ctx.ui.closeModal(store.calendarModal);
    document.dispatchEvent(new CustomEvent('material-ui:open-material', { detail: material.dataset.kalMaterial }));
  }, true);
  // Heute: „Einheit zuweisen“ bittet den Kern um die Auswahl unter der Stunde. Ohne Einheitenansicht
  // (ctx.units fehlt) wird der Knopf gar nicht erst gerendert.
  store.canAssignUnit = Boolean(ctx.units);
  document.addEventListener('click', event => {
    const trigger = event.target.closest?.('[data-kal-assign]');
    if (!trigger) return;
    event.stopPropagation();
    const row = trigger.closest('[data-event-key]');
    const lesson = findByKey(row?.dataset.eventKey);
    if (!lesson) return;
    const summary = store.todaySection?.querySelector('[data-today-summary]');
    document.dispatchEvent(new CustomEvent('material-ui:assign-unit', { detail: {
      event: lesson, row, trigger,
      // Statuszeile von Heute mit Rückgängig; Heute lädt nach dem Eintragen neu.
      notify: (message, undo) => {
        if (!summary) return;
        summary.textContent = message;
        if (!undo) return;
        const button = document.createElement('button'); button.type = 'button'; button.dataset.assignUndo = ''; button.textContent = 'Rückgängig';
        button.onclick = async () => { button.disabled = true; try { await undo(); } catch (error) { summary.textContent = error.message; } };
        summary.append(' ', button);
      },
      reload: () => refreshCalendarViews(ctx),
    } }));
  }, true);
  document.addEventListener('material-calendar-refresh', () => {
    refreshCalendarViews(ctx).catch(error => console.error('Kalender aktualisieren:', error));
  });
  store.todayHandle = ctx.views.register({
    id: 'heute', title: 'Heute', icon: 'agenda', order: 43,
    mount(section) {
      store.todaySection = section;
      section.classList.add('kal-today');
      section.innerHTML = `<header class="kal-header"><div><h2 data-today-title>Heute</h2><div class="kal-day-toggle" role="group" aria-label="Tag der Ansicht"><button type="button" data-today-mode="heute" aria-pressed="true">Heute</button><button type="button" data-today-mode="morgen" aria-pressed="false">Morgen</button></div><p class="muted" data-today-date></p></div><div class="kal-actions"><button type="button" data-today-refresh>Synchronisieren</button></div></header><p data-today-summary role="status"></p><p class="error" data-today-errors role="status"></p><section aria-labelledby="kalTodayLessonsTitle" data-today-lessons-section hidden><h3 id="kalTodayLessonsTitle">Unterrichtsstunden</h3><div class="kal-lessons" data-today-lessons></div></section><section aria-labelledby="kalTodayEventsTitle"><h3 id="kalTodayEventsTitle">Heutige Termine</h3><div class="kal-agenda-events" data-today-events><p class="muted">Termine werden geladen …</p></div></section><section aria-labelledby="kalTodayTasksTitle"><h3 id="kalTodayTasksTitle">Aufgaben</h3><div data-today-tasks aria-busy="true"><p class="muted">Aufgaben werden geladen …</p></div></section><p class="muted kal-today-sync" data-today-sync></p>`;
      addCreateButton(ctx, section, true);
      attachCalendarToolbar(section, () => refreshCalendarViews(ctx));
      addVisibilityButton(ctx, section.querySelector('.kal-actions'));
      for (const button of section.querySelectorAll('[data-today-mode]')) {
        const active = button.dataset.todayMode === store.todayMode;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
        button.addEventListener('click', () => setTodayMode(ctx, button.dataset.todayMode));
      }
      section.querySelector('[data-today-refresh]').onclick = async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        button.textContent = 'Synchronisiert …';
        try { await syncNow(ctx, () => refreshCalendarViews(ctx)); }
        finally { button.disabled = false; button.textContent = 'Synchronisieren'; }
      };
      section.addEventListener('click', event => {
        const action = event.target.closest('[data-task-action]');
        if (action) { changeTask(ctx, action, action.dataset.taskAction === 'today' ? 'plan' : action.dataset.taskAction, isoDate(viewDay())); return; }
        const unit = event.target.closest('[data-kal-unit]');
        if (unit) { document.dispatchEvent(new CustomEvent('material-ui:open-unit', {detail: unit.dataset.kalUnit})); return; }
        const entry = event.target.closest('[data-event-key]');
        if (entry) openEventModal(ctx, findByKey(entry.dataset.eventKey));
      });
      section.addEventListener('change', event => {
        if (event.target.matches('[data-task-plan]')) changeTask(ctx, event.target, 'plan', event.target.value);
      });
    },
    onActivate: () => loadToday(ctx),
  });
  ctx.units?.registerAction({ id: 'todo', mount({unit, container}) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'unit-edit'; button.textContent = '+ TODO';
    button.title = 'TODO zu dieser Einheit anlegen';
    button.onclick = () => openCreateEvent(ctx, '', 'todo', unit.path);
    container.append(button);
  }});
  loadToday(ctx);
  window.setInterval(() => { if (!document.hidden) loadToday(ctx); }, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) loadToday(ctx); });
  // Hintergrundabgleiche aktualisieren auch bereits geöffnete Ansichten.
  let polling = false;
  window.setInterval(async () => {
    if (polling || document.hidden || !store.agendaSection) return;
    polling = true;
    try {
      const before = store.status?.lastSync?.time;
      await refreshStatus(ctx);
      if (before !== store.status?.lastSync?.time) await refreshCalendarViews(ctx);
      renderStatusLine();
    } catch {
      // Ein nicht erreichbares lokales Backend wird beim nächsten Takt erneut geprüft.
    } finally {
      polling = false;
    }
  }, 2000);
  store.monthCursor = firstOfMonth(today());
  store.agendaStart = today();
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const modal = ['kalCreateModal', 'kalEventModal', 'kalSettingsModal']
      .map(id => document.getElementById(id)).find(item => item?.classList.contains('open'));
    if (modal) ctx.ui.closeModal(modal);
    else if (store.calendarModal?.classList.contains('open')) store.calendarModal.querySelector('button[data-calendar-close]').click();
    else return;
    event.preventDefault(); event.stopImmediatePropagation();
  }, true);

  function openCalendar() {
    if (!store.calendarModal) {
      const modal = document.createElement('div');
      modal.className = 'modal'; modal.setAttribute('aria-hidden', 'true');
      modal.innerHTML = `<div class="modal-backdrop" data-calendar-close></div><section class="modal-panel kal-fullscreen" role="dialog" aria-modal="true" aria-label="Kalender"><button class="kal-quiet" data-calendar-close>Zurück zur Agenda</button><div data-calendar-content></div></section>`;
      document.body.append(modal); store.calendarModal = modal;
      modal.querySelectorAll('[data-calendar-close]').forEach(button => button.onclick = () => {
        ctx.ui.closeModal(modal); loadAgenda(ctx, store.agendaSection);
      });
      const section = modal.querySelector('[data-calendar-content]');
      store.kalenderSection = section;
      section.innerHTML = `
        <header class="kal-header">
          <div class="kal-nav">
            <button type="button" class="icon-button" data-kal="prev" title="Vorheriger Monat" aria-label="Vorheriger Monat">‹</button>
            <strong class="kal-month" data-kal="month"></strong>
            <button type="button" class="icon-button" data-kal="next" title="Nächster Monat" aria-label="Nächster Monat">›</button>
            <button type="button" data-kal="today">Heute</button>
          </div>
          <div class="kal-actions">
            <button type="button" data-kal="sync">Synchronisieren</button>
            <button type="button" data-kal="settings">Einstellungen</button>
          </div>
        </header>
        <p class="kal-status" data-kal="status" role="status"></p>
        <p class="kal-status error" data-kal="source-errors" role="status" hidden></p>
        <div class="kal-grid" data-kal="grid"></div>
        <div class="kal-daylist" data-kal="daylist" hidden></div>`;
      bindCalendarView(ctx, section); addCreateButton(ctx, section);
    }
    ctx.ui.openModal(store.calendarModal, store.calendarModal.querySelector('[data-calendar-close]'));
    loadMonth(ctx, store.kalenderSection);
    refreshStatus(ctx).then(renderStatusLine);
  }

  ctx.views.register({
    id: "agenda",
    aliases: ["kalender"],
    title: "Agenda",
    icon: "agenda",
    order: 44,
    mount(section) {
      store.agendaSection = section;
      section.innerHTML = `
        <header class="kal-header">
          <div class="kal-agenda-range" role="group" aria-label="Zeitraum der Agenda">
            <label class="kal-range">Zeitraum
              <select data-kal="agenda-days">
                <option value="7">7 Tage</option>
                <option value="14" selected>14 Tage</option>
                <option value="30">30 Tage</option>
                <option value="90">90 Tage</option>
              </select>
            </label>
            <label class="kal-range">Ab
              <input type="date" data-kal="agenda-jump">
            </label>
            <button type="button" data-kal="agenda-today">Heute</button>
          </div>
          <div class="kal-actions">
            <button type="button" data-kal="sync">Synchronisieren</button>
            <button type="button" data-kal="settings">Einstellungen</button>
          </div>
        </header>
        <p class="kal-status" data-kal="status" role="status"></p>
        <p class="kal-status error" data-kal="source-errors" role="status" hidden></p>
        <div class="kal-agenda" data-kal="agenda"></div>`;
      bindAgendaView(ctx, section);
      addCreateButton(ctx, section);
      const calendar = document.createElement('button');
      calendar.type = 'button'; calendar.className = 'kal-quiet'; calendar.textContent = 'Kalender ↗';
      calendar.onclick = openCalendar;
      section.querySelector('.kal-header').prepend(calendar);
      loadAgenda(ctx, section).then(async () => {
        await refreshStatus(ctx);
        renderStatusLine();
      });
    },
    async onActivate() {
      store.agendaStart = today();
      await loadAgenda(ctx, store.agendaSection);
      await refreshStatus(ctx);
      renderStatusLine();
    },
  });
}