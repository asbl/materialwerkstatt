// Erinnerungen-Plugin (Frontend): Aktion in Kalender/Agenda, die das Einstellungs-
// Modal fuer Desktop-Erinnerungen bei geschlossener UI oeffnet.

export function register(ctx) {
  ctx.calendar?.registerAction({
    id: "reminders",
    mount({ container }) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "kal-action erinnerungen-button";
      button.textContent = "Erinnerungen";
      button.title = "Desktop-Erinnerungen bei geschlossener UI einstellen";
      button.addEventListener("click", () => openSettings(ctx));
      container.append(button);
      return () => button.remove();
    },
  });
}

async function openSettings(ctx) {
  let modal = document.getElementById("erinnerungenModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "erinnerungenModal";
    modal.className = "modal";
    modal.setAttribute("aria-hidden", "true");
    modal.innerHTML = `<div class="modal-backdrop" data-close></div><section class="modal-panel small-modal" role="dialog" aria-modal="true" aria-labelledby="erinnerungenTitle"><header class="modal-header"><strong id="erinnerungenTitle">Desktop-Erinnerungen</strong><button type="button" data-close>Schließen</button></header><form class="template-body"><p class="muted">Benachrichtigungen (notify-send) bei geschlossener UI: Termine im Vorlauffenster und heute fällige TODOs, pro Tag einmal.</p><label><input type="checkbox" name="desktopReminders"> Desktop-Erinnerungen aktiv</label><label>Erinnern vor Termin (Minuten) <input name="reminderMinutes" type="number" min="1" max="120" value="15" inputmode="numeric"></label><button type="submit">Speichern</button><p role="status"></p></form></section>`;
    document.body.append(modal);
    modal.querySelectorAll("[data-close]").forEach((button) => { button.onclick = () => ctx.ui.closeModal(modal); });
    modal.querySelector("form").onsubmit = async (event) => {
      event.preventDefault();
      const form = event.target;
      const status = form.querySelector("[role=status]");
      status.textContent = "";
      try {
        const payload = {
          desktopReminders: form.elements.desktopReminders.checked,
          reminderMinutes: Number(form.elements.reminderMinutes.value) || 15,
        };
        await ctx.api("/api/plugins/erinnerungen/settings", { method: "POST", body: JSON.stringify(payload) });
        status.textContent = "Gespeichert.";
      } catch (error) {
        status.textContent = error.message;
      }
    };
  }
  try {
    const [settings, status] = await Promise.all([
      ctx.api("/api/plugins/erinnerungen/settings"),
      ctx.api("/api/plugins/erinnerungen/status"),
    ]);
    const form = modal.querySelector("form");
    form.elements.desktopReminders.checked = settings.desktopReminders !== false;
    form.elements.reminderMinutes.value = String(settings.reminderMinutes ?? 15);
    form.querySelector("[role=status]").textContent = status.sentToday?.length
      ? `Heute bereits ${status.sentToday.length} Erinnerung(en) gesendet.`
      : "";
  } catch (error) {
    ctx.ui.setStatus(`Erinnerungen konnten nicht geladen werden: ${error.message}`, "error");
  }
  ctx.ui.openModal(modal, modal.querySelector("input"));
}
