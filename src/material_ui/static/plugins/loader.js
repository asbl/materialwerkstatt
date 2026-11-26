import { writeDraft } from "../drafts.js";
import { registerCalendarAction } from "./calendar.js";
import { waitForJob } from "../job-client.js";
import { loadActiveViewPreference } from "../views.js";

// Plugin-Frontend laden: CSS verknüpfen, JS-Modul dynamisch importieren, register(ctx)
// aufrufen. Lade- und Laufzeitfehler eines Plugins lassen die restliche UI unberührt.

// Das Manifest nennt unter `hostApis`, welche Schnittstellen des Kerns ein Plugin braucht;
// der Kern stellt sie als Fabriken bereit. Unbekannte Namen lassen nur dieses Plugin scheitern.
function hostDependencies(plugin, hostApis) {
  const deps = {};
  for (const name of plugin.hostApis || []) {
    const factory = hostApis[name];
    if (typeof factory !== "function") throw new Error(`Host-Schnittstelle „${name}“ ist unbekannt.`);
    Object.assign(deps, factory());
  }
  return deps;
}

function pluginContext({ plugin, api, views, ui, state, units, workspace, documents, documentPreview, search, openDocument, saveCurrentDocument, newDocument, shortcuts, hostApis }) {
  const pluginState = state.plugins[plugin.id] || (state.plugins[plugin.id] = {});
  return {
    plugin,
    apiVersion: 1,
    api,
    state: pluginState,
    ui,
    calendar: { registerAction: action => registerCalendarAction(`${plugin.id}:${action.id}`, action) },
    units: { registerAction: action => units.registerAction({ ...action, id: `${plugin.id}:${action.id}` }) },
    events: { waitForJob: (identifier, options) => waitForJob(api, identifier, options) },
    search: search ? {
      registerProvider: (provider, sourceId, name) => search.register(provider, `${plugin.id}:${sourceId || "quelle"}`, name),
      sources: () => search.sources(),
    } : null,
    workspace: workspace ? { registerMode: mode => workspace.register(mode) } : null,
    documents: documents ? {
      registerPathResolver: fn => documents.register(fn),
      resolve: path => documents.resolve(path),
      // Öffnet ein Dokument im Arbeitsbereich (mit der üblichen Sicherung ungespeicherter Änderungen).
      open: path => openDocument?.(path),
      saveCurrent: () => saveCurrentDocument?.(),
      isDirty: () => Boolean(state.dirty),
      registerPreviewResolver: resolve => documentPreview?.registerResolver(resolve),
      importDraft: (path, draft) => typeof draft?.text === "string" && typeof draft?.revision === "string"
        && writeDraft(state.repositoryRoot, path, draft.text, draft.revision),
    } : null,
    newDocument: newDocument || null,
    shortcuts: shortcuts || null,
    deps: hostDependencies(plugin, hostApis),
    views: {
      register(view) {
        if (!view?.id) return null;
        const entry = { ...view };
        if (!view.iconHref && view.icon && plugin.iconsHref) entry.iconHref = `${plugin.iconsHref}#${view.icon}`;
        return views.registerView(entry);
      },
    },
  };
}

export async function loadPlugins({ api, views, ui, state, units, workspace, documents, documentPreview, search, openDocument, saveCurrentDocument, newDocument, shortcuts, hostApis = {}, onStatus = () => {} }) {
  let plugins = [];
  try {
    plugins = (await api("/api/plugins")).plugins || [];
  } catch (error) {
    onStatus(`Plugins konnten nicht geladen werden: ${error.message}`, "error");
    return [];
  }
  for (const plugin of plugins) {
    if (plugin.status !== "loaded") continue;
    for (const cssUrl of plugin.cssUrls || []) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = cssUrl;
      document.head.appendChild(link);
    }
    if (!plugin.jsUrl) continue;
    try {
      const module = await import(plugin.jsUrl);
      const context = pluginContext({ plugin, api, views, ui, state, units, workspace, documents, documentPreview, search, openDocument, saveCurrentDocument, newDocument, shortcuts, hostApis });
      await module.register?.(context);
    } catch (error) {
      console.error(`Plugin ${plugin.id} ist fehlgeschlagen:`, error);
      onStatus(`Plugin „${plugin.name}“ ist fehlgeschlagen: ${error.message}`, "error");
    }
  }
  // Eine gespeicherte Plugin-Ansicht wird erst jetzt registriert gehabt haben; nachziehen.
  // Ohne gespeicherte Auswahl bleibt die vom Kern gewählte Startansicht bestehen.
  const preference = loadActiveViewPreference();
  const savedView = preference ? views.resolve(preference) : "";
  if (savedView && savedView !== views.activeId() && views.has(savedView)) {
    await views.switchTo(savedView, { persistChoice: false, skipGuard: true });
  }
  return plugins;
}
