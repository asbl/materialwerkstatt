// Termin-Detaildialog und Dialog zum Anlegen von Terminen und TODOs.

import { dayLabel, isoDate, lessonHint, parseIsoDate, weekdayHeadingLabel } from "./format.js";
import { setVisibility } from "./settings.js";
import { modeLabel, store, today, viewDay } from "./store.js";
import { refreshCalendarViews } from "./views.js";

export function openEventModal(ctx, event) {
  if (!event) return;
  const range = event.kind === "todo" ? `${event.startDate ? weekdayHeadingLabel(event.startDate) : 'Ohne Frist'} · TODO` : event.allDay
    ? (event.endDate > event.startDate
      ? `${dayLabel(parseIsoDate(event.startDate))} – ${dayLabel(parseIsoDate(event.endDate))} (ganztägig)`
      : `${dayLabel(parseIsoDate(event.startDate))} (ganztägig)`)
    : `${weekdayHeadingLabel(event.startDate)}, ${event.start.slice(11, 16)}${event.end && event.end !== event.start ? ` – ${event.end.slice(11, 16)}` : ""} Uhr`;
  const detail = eventModal(ctx);
  detail.querySelector("[data-kal-detail-title]").textContent = event.title;
  detail.querySelector("[data-kal-detail-time]").textContent = range;
  if (!event.location) detail.querySelector("[data-kal-detail-location]").setAttribute("hidden", "");
  else {
    detail.querySelector("[data-kal-detail-location]").removeAttribute("hidden");
    detail.querySelector("[data-kal-detail-location]").textContent = event.location;
  }
  const description = detail.querySelector("[data-kal-detail-description]");
  description.textContent = event.description || "";
  description.hidden = !event.description;
  const units = detail.querySelector('[data-kal-detail-units]');
  units.replaceChildren();
  for (const unit of event.units || []) {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = unit.title; button.className = 'kal-quiet';
    button.onclick = () => {
      ctx.ui.closeModal(detail);
      if (store.calendarModal) ctx.ui.closeModal(store.calendarModal);
      document.dispatchEvent(new CustomEvent('material-ui:open-unit', { detail: unit.path }));
    };
    units.append(button);
  }
  const lessonLine = detail.querySelector('[data-kal-detail-lesson]');
  const lessonText = lessonHint(event.lesson);
  lessonLine.hidden = !lessonText;
  lessonLine.textContent = lessonText ? `Unterrichtsstunde: ${lessonText}` : '';
  let edit = detail.querySelector('[data-edit-entry]');
  if (!edit) {
    edit = document.createElement('button'); edit.type = 'button'; edit.dataset.editEntry = '';
    edit.textContent = 'Bearbeiten'; detail.querySelector('.template-body').append(edit);
  }
  edit.hidden = !event.account && !event.key?.startsWith('local:');
  edit.onclick = () => {
    ctx.ui.closeModal(detail);
    openCreateEvent(ctx, event.startDate, event.kind || 'event', event.unitPath || '', event);
  };
  let hide = detail.querySelector('[data-hide-entry]');
  if (!hide) {
    hide = document.createElement('button'); hide.type = 'button'; hide.dataset.hideEntry = '';
    hide.textContent = 'Eintrag ausblenden'; detail.querySelector('.template-body').append(hide);
  }
  hide.disabled = !event.visibilityId && !event.id;
  hide.onclick = async () => {
    hide.disabled = true;
    try { await setVisibility(ctx, 'entries', event.visibilityId || event.id, true, event.title); ctx.ui.closeModal(detail); }
    catch (error) { ctx.ui.setStatus(error.message, 'error'); }
    finally { hide.disabled = false; }
  };
  const calendar = detail.querySelector("[data-kal-detail-calendar]");
  calendar.textContent = [event.account, event.calendar].filter((part) => part).join(" · ");
  const link = detail.querySelector("[data-kal-detail-link]");
  link.hidden = !event.url;
  link.href = event.url || "#";
  ctx.ui.openModal(detail, detail.querySelector("[data-kal-detail-close]"));
}

function eventModal(ctx) {
  const existing = document.getElementById("kalEventModal");
  if (existing) return existing;
  const modal = document.createElement("div");
  modal.id = "kalEventModal";
  modal.className = "modal";
  modal.setAttribute("aria-hidden", "true");
  modal.innerHTML = `
    <div class="modal-backdrop" data-kal-detail-close></div>
    <section class="modal-panel small-modal" role="dialog" aria-modal="true" aria-labelledby="kalEventTitle">
      <header class="modal-header">
        <strong id="kalEventTitle" data-kal-detail-title></strong>
        <button type="button" data-kal-detail-close>Schließen</button>
      </header>
      <div class="template-body">
        <p class="muted" data-kal-detail-time></p>
        <p><span data-kal-detail-calendar></span></p>
        <p data-kal-detail-location></p>
        <p><a data-kal-detail-link target="_blank" rel="noopener">Öffnen</a></p>
        <div data-kal-detail-units></div><p class="muted" data-kal-detail-lesson hidden></p><pre class="kal-description" data-kal-detail-description></pre>
      </div>
    </section>`;
  modal.addEventListener("click", (event) => {
    if (event.target.closest("[data-kal-detail-close]")) ctx.ui.closeModal(modal);
  });
  document.body.appendChild(modal);
  return modal;
}

export function applyCreateButtonLabel(button) {
  const noun = button.dataset.createKind === 'todo' ? 'TODO' : 'Termin';
  const actionLabel = `${noun} für ${modeLabel()} erstellen`;
  button.setAttribute('aria-label', actionLabel); button.title = actionLabel;
  button.textContent = `${button.dataset.createText} ${modeLabel()}`;
}

export function addCreateButton(ctx, section, forToday = false) {
  const group = document.createElement('div');
  group.className = 'kal-create-actions';
  section.querySelector('.kal-header').insertBefore(group, section.querySelector('.kal-tools'));
  for (const [kind, label, text] of [['event', 'Termin erstellen', '+ Termin'], ['todo', 'TODO erstellen', '+ TODO']]) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'kal-quiet';
    if (forToday) {
      button.dataset.createForToday = '';
      button.dataset.createKind = kind;
      button.dataset.createText = text;
      applyCreateButtonLabel(button);
    } else {
      button.setAttribute('aria-label', label); button.title = label;
      button.textContent = text;
    }
    button.onclick = () => openCreateEvent(ctx, forToday ? isoDate(viewDay()) : '', kind);
    group.append(button);
  }
}

export async function openCreateEvent(ctx, day = '', kind = 'event', unitPath = '', existing = null) {
  let modal = document.getElementById('kalCreateModal');
  if (!modal) {
    modal = document.createElement('div'); modal.id = 'kalCreateModal'; modal.className = 'modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `<div class="modal-backdrop" data-close></div><section class="modal-panel small-modal" role="dialog" aria-modal="true" aria-labelledby="kalCreateTitle"><header class="modal-header"><strong id="kalCreateTitle">Termin oder TODO erstellen</strong><button type="button" data-close>Schließen</button></header><form class="template-body"><p class="muted" data-calendar-hint>Dieser Termin wird lokal gespeichert.</p><label>Eintragstyp<select name="kind" aria-label="Eintragstyp"><option value="event">Termin</option><option value="todo">TODO</option></select></label><label>Kalender<select name="calendarTarget" aria-label="Kalender"><option value="">Lokale Termine</option></select></label><label>Titel<input name="title" required></label><label>Datum<input type="date" name="date" required></label><label data-lesson-row hidden>Unterrichtsstunde (optional)<select name="lesson" aria-label="Unterrichtsstunde"><option value="">Keine</option></select></label><label>Enddatum (optional)<input type="date" name="endDate"></label><label>Uhrzeit (optional)<input type="time" name="time"></label><label>Ende (optional)<input type="time" name="endTime"></label><label>Wiederholen<select name="recurrenceFreq" aria-label="Wiederholung"><option value="">Keine</option><option value="DAILY">Täglich</option><option value="WEEKLY">Wöchentlich</option><option value="MONTHLY">Monatlich</option></select></label><div class="grid" data-recurrence-options hidden><label>Alle (Tage/Wochen/Monate)<input name="recurrenceInterval" type="number" min="1" max="366" value="1" inputmode="numeric"></label><label>Bis (optional)<input type="date" name="recurrenceUntil"></label></div><label>Ort<input name="location"></label><label>Beschreibung<textarea name="description"></textarea></label><button type="submit">Speichern</button><p role="status"></p></form></section>`;
    document.body.append(modal);
    modal.querySelectorAll('[data-close]').forEach(button => button.onclick = () => ctx.ui.closeModal(modal));
    modal.querySelector('form').onsubmit = async event => {
      event.preventDefault(); const form = event.target; const button = form.querySelector('[type=submit]');
      if (button.disabled) return;
      button.disabled = true;
      try {
        const payload = Object.fromEntries(new FormData(form));
        payload.kind = form.elements.kind.value;
        const lessonStart = form.elements.lesson.value;
        payload.lesson = lessonStart
          ? (modal.lessonOptions?.get(lessonStart)
              || (modal.editingEvent?.lesson?.start === lessonStart ? modal.editingEvent.lesson : null))
          : null;
        const target = payload.calendarTarget ? JSON.parse(payload.calendarTarget) : { account: '', name: 'Lokale Termine' };
        delete payload.calendarTarget;
        const freq = form.elements.recurrenceFreq?.value || '';
        payload.recurrence = freq ? { freq, interval: Number(form.elements.recurrenceInterval?.value || 1), until: form.elements.recurrenceUntil?.value || '' } : null;
        delete payload.recurrenceFreq; delete payload.recurrenceInterval; delete payload.recurrenceUntil;
        const original = modal.editingEvent;
        await ctx.api('/api/plugins/kalender/events', { method: original ? 'PATCH' : 'POST', body: JSON.stringify({ ...payload, ...(original ? {key: original.key, originalAccount: original.account, originalCalendar: original.calendar} : {}), unitPath: form.dataset.unitPath || '', account: target.account, calendar: target.name }) });
        ctx.ui.closeModal(modal); await refreshCalendarViews(ctx);
      } catch (error) { form.querySelector('[role=status]').textContent = error.message; }
      finally { button.disabled = false; }
    };
    modal.querySelector('form').elements.recurrenceFreq.onchange = event => {
      modal.querySelector('[data-recurrence-options]').hidden = !event.target.value;
    };
  }
  const request = Symbol();
  modal.calendarRequest = request;
  const current = () => modal.calendarRequest === request && modal.classList.contains('open');
  let loading = true;
  const form = modal.querySelector('form'); form.reset(); form.elements.date.value = day || isoDate(today());
  form.elements.kind.value = kind;
  form.dataset.unitPath = unitPath;
  modal.editingEvent = existing;
  modal.lessonOptions = new Map();
  modal.lessonStart = existing?.lesson?.start || '';
  modal.querySelector('#kalCreateTitle').textContent = existing ? 'Eintrag bearbeiten' : 'Termin oder TODO erstellen';
  form.elements.kind.disabled = !!existing;
  if (existing) {
    for (const name of ['title', 'location', 'description']) form.elements[name].value = existing[name] || '';
    form.elements.date.value = existing.startDate || '';
    form.elements.endDate.value = existing.endDate || '';
    if (!existing.allDay && kind !== 'todo') {
      form.elements.time.value = existing.start?.slice(11, 16) || '';
      form.elements.endTime.value = existing.end?.slice(11, 16) || '';
    }
    // Serie bearbeiten: Wiederholung vorbelegen und änderbar; bei einem Vorkommen
    // (recurrenceId) gilt die Änderung für die ganze Serie.
    const recurrence = existing.recurrence || null;
    form.elements.recurrenceFreq.value = recurrence?.freq || '';
    form.elements.recurrenceFreq.disabled = false;
    form.elements.recurrenceInterval.value = recurrence?.interval ?? 1;
    form.elements.recurrenceUntil.value = recurrence?.until || '';
    modal.querySelector('[data-recurrence-options]').hidden = !recurrence?.freq;
    if (existing.recurrenceId) {
      form.querySelector('[role=status]').textContent = 'Serie: Änderungen gelten für die gesamte Serie.';
    }
  } else {
    form.elements.recurrenceFreq.disabled = false;
  }
  form.querySelector('[role=status]').textContent = '';
  const select = form.elements.calendarTarget;
  select.replaceChildren(new Option('Lokale Termine', ''));
  const hint = form.querySelector('[data-calendar-hint]');
  hint.textContent = 'Dieser Termin wird lokal gespeichert.';
  const updateKind = () => {
    const todo = form.elements.kind.value === 'todo';
    form.elements.date.required = !todo;
    form.elements.date.closest('label').firstChild.textContent = todo ? 'Fällig am (optional)' : 'Datum';
    for (const name of ['time', 'endTime', 'endDate']) {
      form.elements[name].disabled = todo;
      form.elements[name].closest('label').style.display = todo ? 'none' : '';
    }
    const lessonRow = form.querySelector('[data-lesson-row]');
    lessonRow.hidden = !todo;
    if (!todo) form.elements.lesson.disabled = true;
    const unresolved = select.value === '?';
    const target = select.value && !unresolved ? JSON.parse(select.value) : null;
    const supported = !target?.components || target.components.includes(todo ? 'VTODO' : 'VEVENT');
    hint.textContent = loading ? 'Kalender und Einstellungen werden geladen …'
      : unresolved ? 'Standardkalender nicht verfügbar oder Laden fehlgeschlagen. Bitte einen Kalender auswählen.'
      : !supported ? 'Dieser Kalender unterstützt diesen Eintragstyp nicht.'
      : `${todo ? 'Dieses TODO' : 'Dieser Termin'} wird ${target ? 'im ausgewählten Kalender' : 'lokal'} gespeichert.`;
    select.disabled = loading;
    form.querySelector('[type=submit]').disabled = loading || unresolved || !supported;
  };
  select.onchange = updateKind;
  // Unterrichtsstunden nur für den gewählten Tag laden; ohne Datum gibt es keine.
  const loadLessons = async () => {
    const row = form.querySelector('[data-lesson-row]');
    const lessonSelect = form.elements.lesson;
    const day = form.elements.date.value;
    const todo = form.elements.kind.value === 'todo';
    const lessonRequest = Symbol();
    modal.lessonRequest = lessonRequest;
    row.hidden = !todo;
    modal.lessonOptions = new Map();
    lessonSelect.replaceChildren(new Option('Keine', ''));
    lessonSelect.disabled = !todo || !day;
    if (!todo || !day) return;
    // Bereits vor der Anfrage erhalten: Speichern darf die Zuordnung auch
    // bei langsamer oder fehlgeschlagener Stundenabfrage nicht entfernen.
    const stored = modal.editingEvent?.lesson;
    if (modal.lessonStart && stored?.start === modal.lessonStart) {
      modal.lessonOptions.set(stored.start, stored);
      lessonSelect.add(new Option(`${stored.start.slice(11, 16)} · ${stored.title || 'Unterrichtsstunde'} (gespeichert)`, stored.start));
      lessonSelect.value = stored.start;
    }
    lessonSelect.disabled = true;
    try {
      const data = await ctx.api(`/api/plugins/kalender/lessons?date=${encodeURIComponent(day)}`);
      if (!current() || modal.lessonRequest !== lessonRequest
          || form.elements.date.value !== day || form.elements.kind.value !== 'todo') return;
      lessonSelect.replaceChildren(new Option('Keine', ''));
      modal.lessonOptions = new Map();
      for (const lesson of data.lessons || []) {
        modal.lessonOptions.set(lesson.start, lesson);
        lessonSelect.add(new Option(
          `${lesson.start.slice(11, 16)}–${(lesson.end || '').slice(11, 16)} · ${lesson.title}${lesson.location ? ` · ${lesson.location}` : ''}`,
          lesson.start));
      }
      // Gespeicherte Verknüpfung bleibt wählbar, auch wenn die Quelle sie gerade nicht liefert.
      if (modal.lessonStart && stored && stored.start === modal.lessonStart && !modal.lessonOptions.has(stored.start)) {
        modal.lessonOptions.set(stored.start, stored);
        lessonSelect.add(new Option(`${stored.start.slice(11, 16)} · ${stored.title || 'Unterrichtsstunde'} (gespeichert)`, stored.start));
      }
      lessonSelect.value = modal.lessonStart && modal.lessonOptions.has(modal.lessonStart) ? modal.lessonStart : '';
      lessonSelect.disabled = false;
    } catch (error) {
      if (current() && modal.lessonRequest === lessonRequest) {
        lessonSelect.disabled = false;
        form.querySelector('[role=status]').textContent = `Unterrichtsstunden konnten nicht geladen werden: ${error.message}`;
      }
    }
  };
  let defaults = {};
  const applyDefault = () => {
    const target = existing ? (existing.account ? {account: existing.account, name: existing.calendar} : null) : defaults[form.elements.kind.value === 'todo' ? 'defaultTodoCalendar' : 'defaultEventCalendar'];
    select.querySelector('[data-unresolved]')?.remove();
    const match = [...select.options].find(option => {
      if (!option.value || !target) return false;
      const calendar = JSON.parse(option.value);
      return calendar.account === target.account && calendar.name === target.name;
    });
    if (target && !match) {
      const option = new Option('Bitte Kalender auswählen', '?');
      option.disabled = true; option.dataset.unresolved = ''; select.add(option);
    }
    select.value = match?.value || (target ? '?' : '');
    updateKind();
  };
  form.elements.kind.onchange = () => { applyDefault(); loadLessons(); };
  form.elements.date.onchange = () => { modal.lessonStart = ''; loadLessons(); };
  updateKind();
  loadLessons();
  ctx.ui.openModal(modal, form.elements.title);
  try {
    const [data, settings] = await Promise.all([ctx.api('/api/plugins/kalender/calendars'), ctx.api('/api/plugins/kalender/settings')]);
    if (!current()) return;
    loading = false;
    defaults = settings;
    for (const calendar of data.calendars || []) {
      select.add(new Option(`${calendar.name} (${calendar.account})`, JSON.stringify(calendar)));
    }
    applyDefault();
    if (data.errors?.length) form.querySelector('[role=status]').textContent = data.errors.join('; ');
  } catch (error) {
    if (!current()) return;
    loading = false;
    const option = new Option('Bitte Kalender auswählen', '?');
    option.disabled = true; option.dataset.unresolved = ''; select.add(option); select.value = '?';
    // Auch ein Typwechsel darf die bewusste Auswahl nach einem Ladefehler nicht umgehen.
    form.elements.kind.onchange = () => { updateKind(); loadLessons(); };
    updateKind();
    form.querySelector('[role=status]').textContent = `Kalender konnten nicht geladen werden: ${error.message}`;
  }
}