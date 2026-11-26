// Einstellungsdialog (Konten, Kalenderauswahl, Lerngruppen) und Sichtbarkeitsdialog.

import { escapeHtml } from "/static/ui-utils.js";
import { refreshCalendarViews } from "./views.js";

export async function setVisibility(ctx, scope, id, hidden, label = '') {
  await ctx.api('/api/plugins/kalender/visibility', {method: 'POST', body: JSON.stringify({scope, id, hidden, label})});
  await refreshCalendarViews(ctx);
}

async function openVisibility(ctx) {
  try {
    const data = await ctx.api('/api/plugins/kalender/visibility');
    document.getElementById('kalVisibilityModal')?.remove();
    const modal = document.createElement('div');
    modal.id = 'kalVisibilityModal'; modal.className = 'modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `<div class="modal-backdrop" data-close></div><section class="modal-panel small-modal" role="dialog" aria-modal="true" aria-label="Sichtbarkeit"><header class="modal-header"><strong>Kalender und ausgeblendete Einträge</strong><button type="button" data-close>Schließen</button></header><div class="template-body"><p>Die Auswahl gilt lokal für Heute, Agenda und Kalender. Ausgeblendete TODOs zählen nicht als überfällig. Bei Terminserien gilt die Auswahl für die ganze Serie.</p><div data-visibility-rows></div><p role="status"></p></div></section>`;
    const rows = modal.querySelector('[data-visibility-rows]');
    const add = (scope, id, label, hidden) => {
      const row = document.createElement('label');
      const input = document.createElement('input'); input.type = 'checkbox'; input.checked = !hidden;
      input.onchange = async () => {
        input.disabled = true;
        try { await setVisibility(ctx, scope, id, !input.checked, label); }
        catch (error) { input.checked = !input.checked; modal.querySelector('[role=status]').textContent = error.message; }
        finally { input.disabled = false; }
      };
      row.append(input, document.createTextNode(label)); rows.append(row);
    };
    const calendars = new Map(data.calendars.map(c => [c.id, c]));
    for (const [id, label] of Object.entries(data.hiddenCalendars)) if (!calendars.has(id)) calendars.set(id, {id, label, hidden: true});
    for (const c of calendars.values()) add('calendars', c.id, c.label, c.hidden);
    for (const [id, label] of Object.entries(data.hiddenEntries)) add('entries', id, label, true);
    if (!rows.children.length) rows.textContent = 'Keine Kalender oder ausgeblendeten Einträge vorhanden.';
    modal.addEventListener('click', event => { if (event.target.closest('[data-close]')) ctx.ui.closeModal(modal); });
    document.body.append(modal); ctx.ui.openModal(modal);
  } catch (error) { ctx.ui.setStatus(error.message, 'error'); }
}

export function addVisibilityButton(ctx, actions) {
  const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Sichtbarkeit';
  button.onclick = () => openVisibility(ctx); actions.append(button);
}

function settingsModal(ctx, onSave) {
  const existing = document.getElementById("kalSettingsModal");
  if (existing) return existing;
  const modal = document.createElement("div");
  modal.id = "kalSettingsModal";
  modal.className = "modal";
  modal.setAttribute("aria-hidden", "true");
  modal.innerHTML = `
    <div class="modal-backdrop" data-kal-settings-close></div>
    <section class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="kalSettingsTitle">
      <header class="modal-header">
        <strong id="kalSettingsTitle">Kalender-Einstellungen</strong>
        <button type="button" data-kal-settings-close>Schließen</button>
      </header>
      <div class="template-body">
        <p class="muted">Konten mit CalDAV-Zugang (Schule, Nextcloud). Passwörter bleiben lokal unter .material-ui und werden nie angezeigt.</p>
        <details><summary>Lerngruppen je Schuljahr</summary><p class="muted">Einheiten ohne eigene Lerngruppe verwenden diese Zuordnung. Explizite Einsatzangaben haben Vorrang.</p><div data-kal-groups></div><button type="button" data-kal-group-add>Zuordnung ergänzen</button></details>
        <div class="grid">
          <label>Standardkalender für Termine<select data-kal-field="defaultEventCalendar"><option value="">Lokale Termine</option></select></label>
          <label>Standardkalender für TODOs<select data-kal-field="defaultTodoCalendar"><option value="">Lokale Termine</option></select></label>
        </div>
        <label>Ferienkalender (CalDAV, ganztägige Termine werden als Ferien markiert)<select data-kal-field="holidayCalendar"><option value="">Automatisch erkennen</option></select></label>
        <div class="grid">
          <label>Ausgewählte Kalender<button type="button" data-kal-select="selectedEventCalendars">Alle Kalender</button></label>
          <label>Ausgewählte TODOs<button type="button" data-kal-select="selectedTodoCalendars">Alle TODO-Kalender</button></label>
        </div>
        <div class="kal-accounts" data-kal-accounts></div>
        <div class="button-row">
          <button type="button" data-kal-account-add>Konto hinzufügen</button>
        </div>
        <div class="grid">
          <label>Zeitzone <input data-kal-field="timezone"></label>
          <label>Abgleich alle (Minuten, 0 = aus) <input data-kal-field="syncIntervalMinutes" inputmode="numeric"></label>
        </div>
        <div class="grid">
          <label>Fenster zurück (Tage) <input data-kal-field="windowPastDays" inputmode="numeric"></label>
          <label>Fenster voraus (Tage) <input data-kal-field="windowFutureDays" inputmode="numeric"></label>
        </div>
        <p class="muted" data-kal-settings-hint role="status"></p>
        <div class="button-row">
          <button type="button" data-kal-save>Speichern</button>
          <button type="button" data-kal-settings-close>Abbrechen</button>
        </div>
      </div>
    </section>`;
  modal.addEventListener("click", async (event) => {
    if (event.target.closest("[data-kal-settings-close]")) {
      ctx.ui.closeModal(modal);
      return;
    }
    if (event.target.closest('[data-kal-select]')) {
      openCalendarSelection(modal, event.target.closest('[data-kal-select]').dataset.kalSelect);
      return;
    }
    if (event.target.closest('[data-kal-group-add]')) { addGroupRow(modal, {}); return; }
    if (event.target.closest('[data-group-remove]')) { event.target.closest('.kal-group-row').remove(); return; }
    if (event.target.closest("[data-kal-account-add]")) {
      addAccountRow(modal, {}, true);
      return;
    }
    if (event.target.closest("[data-kal-account-edit]")) {
      const button = event.target.closest("[data-kal-account-edit]");
      const row = button.closest(".kal-account");
      const editor = row.querySelector("[data-kal-account-editor]");
      editor.hidden = !editor.hidden;
      button.setAttribute("aria-expanded", String(!editor.hidden));
      button.textContent = editor.hidden ? "Bearbeiten" : "Fertig";
      row.querySelector("[data-kal-account-name]").textContent =
        row.querySelector('[data-kal-account="label"]').value.trim() || "Neues Konto";
      if (!editor.hidden) editor.querySelector("input").focus();
      return;
    }
    if (event.target.closest("[data-kal-account-remove]")) {
      event.target.closest(".kal-account").remove();
      return;
    }
    if (event.target.closest("[data-kal-save]")) {
      const hint = modal.querySelector("[data-kal-settings-hint]");
      const payload = collectSettings(modal);
      try {
        await ctx.api("/api/plugins/kalender/settings", { method: "POST", body: JSON.stringify(payload) });
        const rows = [...modal.querySelectorAll('.kal-group-row')].map(row => Object.fromEntries(
          ['year', 'grade', 'group'].map(key => [key, row.querySelector(`[data-group=${key}]`).value.trim()])));
        await ctx.api('/api/plugins/kalender/unit-groups', { method: 'POST', body: JSON.stringify(rows) });
        hint.textContent = "Gespeichert.";
        ctx.ui.closeModal(modal);
        if (onSave) await onSave();
      } catch (error) {
        hint.textContent = `Speichern fehlgeschlagen: ${error.message}`;
      }
    }
  });
  document.body.appendChild(modal);
  return modal;
}

function addGroupRow(modal, row) {
  modal.querySelector('[data-kal-groups]').insertAdjacentHTML('beforeend', `<div class="kal-group-row">
    <label>Schuljahr<input data-group="year" placeholder="2026/2027" value="${escapeHtml(row.year || '')}"></label>
    <label>Stufe<input data-group="grade" placeholder="05" value="${escapeHtml(row.grade || '')}"></label>
    <label>Lerngruppe<input data-group="group" placeholder="05C" value="${escapeHtml(row.group || '')}"></label>
    <button type="button" data-group-remove aria-label="Zuordnung entfernen">×</button></div>`);
}

function accountRow(account, editing = false) {
  return `<div class="kal-account">
    <div class="kal-account-summary">
      <strong data-kal-account-name>${escapeHtml(account.label || "Neues Konto")}</strong>
      <div class="kal-account-actions">
        <button type="button" data-kal-account-edit aria-expanded="${editing}">${editing ? "Fertig" : "Bearbeiten"}</button>
        <button type="button" class="recovery-secondary" data-kal-account-remove>Löschen</button>
      </div>
    </div>
    <div class="kal-account-editor" data-kal-account-editor ${editing ? "" : "hidden"}>
    <label>Bezeichnung <input data-kal-account="label" value="${escapeHtml(account.label || "")}"></label>
    <label>CalDAV-URL <input data-kal-account="url" value="${escapeHtml(account.url || "")}"></label>
    <div class="grid">
      <label>Nutzer <input data-kal-account="username" value="${escapeHtml(account.username || "")}"></label>
      <label>App-Passwort <input data-kal-account="password" type="password" placeholder="${account.password ? "unverändert" : ""}"></label>
    </div>
    <label>Kalender (freilassen für alle; Komma für Auswahl) <input data-kal-account="calendars" value="${escapeHtml((account.calendars || []).join(", "))}"></label>
    </div>
  </div>`;
}

function addAccountRow(modal, account, editing = false) {
  modal.querySelector("[data-kal-accounts]").insertAdjacentHTML("beforeend", accountRow(account, editing));
}

function updateSelectionButtons(modal) {
  for (const field of ['selectedEventCalendars', 'selectedTodoCalendars']) {
    const selected = modal.calendarSelections[field];
    modal.querySelector(`[data-kal-select="${field}"]`).textContent = selected === null
      ? (field === 'selectedEventCalendars' ? 'Alle Kalender' : 'Alle TODO-Kalender')
      : selected.length ? selected.map(c => c.name).join(', ') : 'Keine Kalender';
  }
}

function openCalendarSelection(modal, field) {
  const popup = document.createElement('dialog');
  popup.className = 'kal-calendar-picker';
  const component = field === 'selectedTodoCalendars' ? 'VTODO' : 'VEVENT';
  const calendars = [{ account: '', name: 'Lokale Termine' },
    ...(modal.availableCalendars || []).filter(c => !c.components || c.components.includes(component))];
  const current = modal.calendarSelections[field];
  for (const target of current || []) {
    if (!calendars.some(c => c.account === target.account && c.name === target.name)) calendars.push(target);
  }
  popup.innerHTML = `<form method="dialog">
    <h3>${field === 'selectedTodoCalendars' ? 'TODO-Kalender auswählen' : 'Kalender auswählen'}</h3>
    <label><input type="checkbox" data-all ${current === null ? 'checked' : ''}> Alle Kalender</label>
    <div class="kal-calendar-options">${calendars.map((c, index) => `<label><input type="checkbox" data-index="${index}"
      ${current === null || current.some(t => t.account === c.account && t.name === c.name) ? 'checked' : ''}>
      ${escapeHtml(c.name)}${c.account ? ` (${escapeHtml(c.account)})` : ''}</label>`).join('')}</div>
    <p class="muted">${escapeHtml(modal.calendarLoadHint || '')}</p>
    <div class="kal-account-actions"><button value="cancel">Abbrechen</button><button value="save">Übernehmen</button></div>
  </form>`;
  popup.addEventListener('change', event => {
    if (event.target.matches('[data-all]')) {
      popup.querySelectorAll('[data-index]').forEach(input => { input.checked = event.target.checked; });
    } else popup.querySelector('[data-all]').checked = false;
  });
  popup.addEventListener('close', () => {
    if (popup.returnValue === 'save') {
      modal.calendarSelections[field] = popup.querySelector('[data-all]').checked ? null :
        [...popup.querySelectorAll('[data-index]:checked')].map(input => {
          const c = calendars[Number(input.dataset.index)];
          return { account: c.account, name: c.name };
        });
      updateSelectionButtons(modal);
    }
    popup.remove();
  });
  document.body.appendChild(popup);
  popup.showModal();
}

function fillSettings(modal, settings) {
  modal.availableCalendars = [];
  modal.calendarLoadHint = 'Kalender werden geladen …';
  modal.calendarSelections = Object.fromEntries(['selectedEventCalendars', 'selectedTodoCalendars']
    .map(field => [field, settings[field] ?? null]));
  updateSelectionButtons(modal);
  const accounts = modal.querySelector("[data-kal-accounts]");
  accounts.innerHTML = "";
  for (const account of settings.accounts || []) addAccountRow(modal, account);
  for (const field of ["timezone", "syncIntervalMinutes", "windowPastDays", "windowFutureDays"]) {
    modal.querySelector(`[data-kal-field="${field}"]`).value = String(settings[field]);
  }
}

function collectSettings(modal) {
  return {
    ...Object.fromEntries(['defaultEventCalendar', 'defaultTodoCalendar', 'holidayCalendar'].map(field => {
      const value = modal.querySelector(`[data-kal-field="${field}"]`).value;
      return [field, value ? JSON.parse(value) : null];
    })),
    ...modal.calendarSelections,
    accounts: [...modal.querySelectorAll(".kal-account")].map((row) => ({
      label: row.querySelector('[data-kal-account="label"]').value.trim(),
      url: row.querySelector('[data-kal-account="url"]').value.trim(),
      username: row.querySelector('[data-kal-account="username"]').value.trim(),
      password: row.querySelector('[data-kal-account="password"]').value.trim() || "••••",
      calendars: row.querySelector('[data-kal-account="calendars"]').value,
    })),
    timezone: modal.querySelector('[data-kal-field="timezone"]').value.trim(),
    syncIntervalMinutes: Number(modal.querySelector('[data-kal-field="syncIntervalMinutes"]').value) || 0,
    windowPastDays: Number(modal.querySelector('[data-kal-field="windowPastDays"]').value) || 0,
    windowFutureDays: Number(modal.querySelector('[data-kal-field="windowFutureDays"]').value) || 0,
  };
}

export async function openSettings(ctx, onSave) {
  const modal = settingsModal(ctx, onSave);
  const request = Symbol();
  modal.calendarRequest = request;
  const settings = await ctx.api('/api/plugins/kalender/settings');
  if (modal.calendarRequest !== request) return;
  fillSettings(modal, { accounts: [], ...settings });
  for (const field of ['defaultEventCalendar', 'defaultTodoCalendar', 'holidayCalendar']) {
    const select = modal.querySelector(`[data-kal-field="${field}"]`);
    select.replaceChildren(new Option(field === 'holidayCalendar' ? 'Automatisch erkennen' : 'Lokale Termine', ''));
    const target = settings[field];
    if (target) select.add(new Option(`${target.name} (${target.account})`, JSON.stringify(target)));
    select.value = target ? JSON.stringify(target) : '';
  }
  const groups = await ctx.api('/api/plugins/kalender/unit-groups');
  if (modal.calendarRequest !== request) return;
  modal.querySelector('[data-kal-groups]').replaceChildren();
  for (const row of groups.rows) addGroupRow(modal, row);
  const hint = modal.querySelector('[data-kal-settings-hint]');
  hint.textContent = 'Kalender werden geladen …';
  ctx.ui.openModal(modal, modal.querySelector('[data-kal-settings-close]'));
  try {
    const data = await ctx.api('/api/plugins/kalender/calendars');
    if (modal.calendarRequest !== request || !modal.classList.contains('open')) return;
    modal.availableCalendars = data.calendars || [];
    modal.calendarLoadHint = (data.errors || []).join('; ');
    for (const field of ['defaultEventCalendar', 'defaultTodoCalendar', 'holidayCalendar']) {
      const select = modal.querySelector(`[data-kal-field="${field}"]`);
      for (const calendar of data.calendars || []) {
        if (field !== 'holidayCalendar' && calendar.components && !calendar.components.includes(field === 'defaultTodoCalendar' ? 'VTODO' : 'VEVENT')) continue;
        const value = JSON.stringify({ account: calendar.account, name: calendar.name });
        if (![...select.options].some(option => option.value === value)) {
          select.add(new Option(`${calendar.name} (${calendar.account})`, value));
        }
      }
    }
    modal.querySelector('[data-kal-settings-hint]').textContent = (data.errors || []).join('; ');
  } catch (error) {
    if (modal.calendarRequest !== request || !modal.classList.contains('open')) return;
    modal.calendarLoadHint = 'Kalender konnten nicht geladen werden.';
    hint.textContent = `Kalender konnten nicht geladen werden: ${error.message}`;
  }
}