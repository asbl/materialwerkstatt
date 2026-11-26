// Workspace-Modi: Plugins registrieren einen vollständigen Arbeitsmodus
// (z. B. "kurs"). Der Kern fragt den aktiven Modus statt fest verdrahteter
// Kurs-Zweige. Plugin-Zustand bleibt im jeweiligen Plugin.

export function createWorkspaceModeRegistry({ setChrome = () => {} } = {}) {
  const modes = new Map();
  let activeMode = null;

  function register(mode) {
    if (!mode?.id || modes.has(mode.id)) return modes.get(mode.id) || null;
    modes.set(mode.id, mode);
    return mode;
  }

  function modeForPath(path) {
    for (const mode of modes.values()) {
      if (mode.entryFor) {
        const entry = mode.entryFor(path);
        if (entry) return { mode, entry };
      }
    }
    return null;
  }

  function ownsDocument(path) {
    if (!activeMode) return false;
    if (activeMode.ownsDocument) return !!activeMode.ownsDocument(path);
    return activeMode.entryFor?.(path) != null;
  }

  let transition = Promise.resolve();
  function serialize(action) {
    const pending = transition.then(action);
    transition = pending.catch(() => {});
    return pending;
  }

  async function leaveActive() {
    const mode = activeMode;
    if (!mode) return;
    try {
      if (mode.leave) await mode.leave();
    } finally {
      activeMode = null;
      setChrome(null);
    }
  }

  function enter(mode, entry) {
    return serialize(async () => {
      if (activeMode && activeMode !== mode) await leaveActive();
      activeMode = mode;
      setChrome(mode.id);
      try {
        if (mode.enter) await mode.enter(entry);
      } catch (error) {
        await leaveActive();
        throw error;
      }
    });
  }

  function leave() {
    return serialize(leaveActive);
  }

  return {
    register,
    modeForPath,
    ownsDocument,
    enter,
    leave,
    active: () => activeMode,
    activeId: () => activeMode?.id || null,
    actions: () => activeMode?.actions || null,
    has: (id) => modes.has(id),
  };
}
