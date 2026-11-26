// Gemeinsame Registry: Aktionen funktionieren auch bei später geladenen Plugins.
const toolbars = new Map();
const actions = new Map();

function mount(toolbar, id, action) {
  if (toolbar.cleanups.has(id)) return;
  const container = document.createElement('span');
  container.dataset.pluginCalendarAction = id;
  toolbar.container.append(container);
  try {
    const cleanup = action.mount({ container, refresh: toolbar.refresh });
    toolbar.cleanups.set(id, () => { cleanup?.(); container.remove(); });
  } catch (error) {
    container.remove();
    console.error(`Kalenderaktion ${id} ist fehlgeschlagen:`, error);
  }
}

export function registerCalendarAction(id, action) {
  if (!action?.id || typeof action.mount !== 'function') throw new Error('Kalenderaktion benötigt id und mount.');
  if (actions.has(id)) throw new Error(`Kalenderaktion ${id} ist bereits registriert.`);
  actions.set(id, action);
  for (const toolbar of toolbars.values()) mount(toolbar, id, action);
  return () => {
    actions.delete(id);
    for (const toolbar of toolbars.values()) {
      toolbar.cleanups.get(id)?.();
      toolbar.cleanups.delete(id);
    }
  };
}

export function attachCalendarToolbar(section, refresh) {
  if (toolbars.has(section)) return;
  const toolbar = { container: section.querySelector('.kal-actions'), refresh, cleanups: new Map() };
  toolbars.set(section, toolbar);
  for (const [id, action] of actions) mount(toolbar, id, action);
}
