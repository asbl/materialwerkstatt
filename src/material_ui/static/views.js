// Ansichts-Registry: Rail-Knöpfe und Ansichtswechsel unter einem Dach.
// Kernansichten adoptieren ihre vorhandenen Knöpfe aus index.html;
// Plugin-Ansichten bekommen Knopf und eigenes <section> erzeugt.

export const ACTIVE_VIEW_KEY = "material-ui:active-view";

export function loadActiveViewPreference() {
  try {
    return localStorage.getItem(ACTIVE_VIEW_KEY) || "";
  } catch {
    return "";
  }
}

// Kurzbeschriftung unter dem Rail-Icon, ausfuehrlicher Titel im Kopf des Index, Gruppe fuer die Trennlinien.
const VIEW_LABELS = {
  folder: { label: "Ordner", heading: "Ordner und Dateien", group: "material" },
  tagTree: { label: "Material", heading: "Material finden", group: "material" },
  units: { label: "Einheiten", heading: "Unterrichtseinheiten", group: "planung" },
  heute: { label: "Heute", heading: "Heute", group: "planung" },
  agenda: { label: "Agenda", heading: "Agenda", group: "planung" },
  kurse: { label: "Kurse", heading: "Kurse", group: "kurse" },
  "kurse-sync": { label: "Sync", heading: "Kurs-Sync", group: "kurse" },
  wissen: { label: "Wissen", heading: "Wissen", group: "wissen" },
};

function shortLabel(view) {
  if (view.label) return view.label;
  if (VIEW_LABELS[view.id]) return VIEW_LABELS[view.id].label;
  const word = String(view.title || view.id).split(/\s+/)[0];
  return word.length > 9 ? `${word.slice(0, 8)}…` : word;
}

function buttonHtml(view) {
  const href = view.iconHref || `/static/icons.svg#${view.icon}`;
  return `<svg class="icon" aria-hidden="true" focusable="false"><use href="${href}"></use></svg><span class="rail-label">${shortLabel(view).replace(/[<&]/g, "")}</span>`;
}

export function createViewRegistry({ state, rail, sections, onLeaveActive, saveActiveView = () => {} }) {
  const views = new Map();
  const aliases = new Map(); // frühere View-IDs (gespeicherte Auswahl) -> aktuelle ID

  function groupOf(view) {
    return view.group || VIEW_LABELS[view.id]?.group || view.id;
  }

  function syncRail() {
    for (const view of views.values()) {
      view.button?.classList.toggle("active", view.id === state.navigationView);
      view.button?.setAttribute("aria-pressed", String(view.id === state.navigationView));
    }
    // Index-Kopf nennt die aktive Ansicht; Trennlinien gliedern die Rail in Gruppen.
    const active = views.get(state.navigationView);
    const heading = rail?.closest(".workspace-index")?.querySelector("#indexTitle");
    if (heading && active) heading.textContent = active.heading || VIEW_LABELS[active.id]?.heading || active.title || "Index";
    const byButton = new Map([...views.values()].filter(view => view.button).map(view => [view.button, view]));
    let previousGroup = null;
    for (const button of rail?.querySelectorAll(".index-rail-button") || []) {
      const view = byButton.get(button);
      const group = view ? groupOf(view) : null;
      button.classList.toggle("rail-group-start", previousGroup !== null && group !== previousGroup);
      previousGroup = group;
    }
  }

  function registerView(view) {
    if (!view?.id || views.has(view.id)) return views.get(view.id) || null;
    const handle = { ...view };
    if (!handle.button) {
      handle.button = document.createElement("button");
      handle.button.type = "button";
      handle.button.id = `viewButton-${view.id}`;
      handle.button.className = "index-rail-button";
      handle.button.title = view.title || view.id;
      handle.button.setAttribute("aria-label", view.title || view.id);
      handle.button.innerHTML = buttonHtml(handle);
      handle.button.addEventListener("click", () => { switchTo(handle.id); });
      rail?.appendChild(handle.button);
    } else {
      handle.button.addEventListener("click", () => { switchTo(handle.id); });
    }
    if (handle.mount && !handle.section) {
      handle.section = document.createElement("section");
      handle.section.id = `viewSection-${handle.id}`;
      handle.section.className = "plugin-view";
      handle.section.hidden = state.navigationView !== handle.id;
      handle.section.setAttribute("aria-label", view.title || view.id);
      sections?.appendChild(handle.section);
    }
    views.set(handle.id, handle);
    for (const alias of view.aliases || []) aliases.set(alias, handle.id);
    syncRail();
    return handle;
  }

  async function switchTo(id, { persistChoice = true, skipGuard = false } = {}) {
    const view = views.get(id);
    if (!view) return false;
    // Der Wächter läuft vor dem Gleichheitsvergleich: Auch ein Klick auf die
    // bereits aktive Ansicht verlässt einen offenen Kursmodus (bisheriges Verhalten).
    // skipGuard überspringt ihn für das initiale Nachziehen gespeicherter
    // Plugin-Ansichten beim Start (kein Benutzerwechsel).
    if (onLeaveActive && !skipGuard && !(await onLeaveActive())) return false;
    if (state.navigationView === id) return true;
    // Prepare data while the previous view remains visible.
    if (view.section && !view.mounted) {
      view.mounted = true;
      view.mount?.(view.section);
    }
    await view.onPrepare?.();
    const previous = views.get(state.navigationView);
    if (previous) {
      previous.onDeactivate?.();
      if (previous.section) previous.section.hidden = true;
    }
    state.navigationView = id;
    syncRail();
    // Persistieren, bevor die Aktivierung läuft: onActivate darf awaiten, ohne dass
    // die gespeicherte Ansicht des Wechsels hinten nachhaengt.
    if (persistChoice) saveActiveView(id);
    if (view.section) {
      view.section.hidden = false;
      if (!view.mounted) {
        view.mounted = true;
        view.mount?.(view.section);
      }
    }
    await view.onActivate?.();
    return true;
  }

  // Ansicht einhängen und Daten laden, ohne sie zu aktivieren (z. B. wenn Heute die Einheitenauswahl braucht).
  async function prepare(id) {
    const view = views.get(id);
    if (!view) return false;
    if (view.section && !view.mounted) { view.mounted = true; view.mount?.(view.section); }
    await view.onPrepare?.();
    return true;
  }

  function activateInitial() {
    syncRail();
    return views.get(state.navigationView);
  }

  return {
    registerView,
    switchTo,
    prepare,
    activateInitial,
    has: (id) => views.has(id),
    // Löst eine gespeicherte oder frühere View-ID (siehe `aliases` der Ansicht) auf.
    resolve: (id) => (views.has(id) ? id : aliases.get(id) || id),
    view: (id) => views.get(id),
    activeId: () => state.navigationView,
  };
}
