// Frontend-Such-Provider: Plugins registrieren lokale Trefferquellen fuer den Picker
// (ctx.search.registerProvider). Backend-Quellen laufen ueber /api/search; beide tragen
// am Treffer das Feld `source` mit der Quellen-ID.

export function createSearchProviderRegistry({ maxProviders = 16, maxResults = 50 } = {}) {
  const providers = new Map();

  function register(provider, sourceId = "", name = "") {
    if (typeof provider !== "function") throw new Error("Der Provider muss eine Funktion sein.");
    const id = String(sourceId || `provider-${providers.size + 1}`);
    if (providers.size >= maxProviders && !providers.has(id)) throw new Error("Zu viele Such-Quellen registriert.");
    providers.set(id, { name: String(name || id), provider });
    let active = true;
    return () => {
      if (!active) return;
      active = false;
      providers.delete(id);
    };
  }

  function run(query, filters = {}) {
    const results = [];
    const errors = [];
    for (const [id, { name, provider }] of providers) {
      try {
        const raw = provider(String(query ?? ""), filters) || [];
        if (!Array.isArray(raw)) throw new Error("Der Provider lieferte keine Liste.");
        for (const entry of raw.slice(0, maxResults)) {
          if (!entry || typeof entry !== "object" || typeof entry.path !== "string" || !entry.path) continue;
          const item = { ...entry, source: id };
          if (!item.title) item.title = item.path.split("/").pop();
          if (typeof item.score !== "number" || item.score < 0) item.score = 0;
          results.push(item);
        }
      } catch (error) {
        // Fehler einer Quelle isolieren; die uebrigen Treffer bleiben sichtbar.
        errors.push({ source: id, name, message: String(error?.message || error).slice(0, 240) });
      }
    }
    return { results, errors };
  }

  function sources() {
    return [...providers].map(([id, entry]) => ({ id, name: entry.name }));
  }

  return { register, run, sources, has: (id) => providers.has(id), size: () => providers.size };
}
