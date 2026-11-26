import { escapeHtml } from "./ui-utils.js";

// Marketplace/Paketmanager: Liste der installierten und im Katalog verfügbaren Plugins
// mit Installieren, Deinstallieren, Aktivieren/Deaktivieren und Aktualisieren.

const STATUS_LABELS = {
  loaded: "aktiv",
  enabled: "aktiv · Neustart ausstehend",
  disabled: "deaktiviert",
  error: "Fehler",
  incompatible: "inkompatibel",
  "missing-dependency": "Abhängigkeit fehlt",
  blocked: "blockiert",
  "restart-pending": "Neustart ausstehend"
};

const CATALOG_TIMEOUT = 180000; // erster git-Clone kann länger dauern

function icon(name) {
  return `<svg class="icon" aria-hidden="true" focusable="false"><use href="/static/icons.svg#${name}"></use></svg>`;
}

export function createMarketplaceController({ elements, api, setStatus, onChanged }) {
  let plugins = [];
  let filter = "";

  function setLocalStatus(message) {
    elements.marketplaceStatus.textContent = message;
  }

  function matches(entry) {
    if (!filter) return true;
    const needle = filter.toLowerCase();
    return entry.id.toLowerCase().includes(needle) || (entry.name || "").toLowerCase().includes(needle);
  }

  function render() {
    const installed = plugins.filter(entry => entry.installed && matches(entry));
    const available = plugins.filter(entry => !entry.installed && matches(entry));
    elements.marketplaceInstalled.replaceChildren(...installed.map(installedCard));
    elements.marketplaceAvailable.replaceChildren(...available.map(availableCard));
    if (!installed.length) elements.marketplaceInstalled.append(emptyNote("Keine Plugins installiert."));
    if (!available.length) elements.marketplaceAvailable.append(emptyNote("Keine weiteren Plugins im Katalog."));
  }

  function emptyNote(text) {
    const li = document.createElement("li");
    li.className = "plugin-empty muted";
    li.textContent = text;
    return li;
  }

  function depsHtml(entry) {
    if (!entry.dependsOn?.length) return "";
    const items = entry.dependsOn
      .map(dep => `<li>${escapeHtml(dep.target)} <code>${escapeHtml(dep.constraint)}</code></li>`)
      .join("");
    return `<div class="plugin-deps">hängt ab von:<ul>${items}</ul></div>`;
  }

  function capsHtml(entry) {
    if (!entry.capabilities?.length) return "";
    const chips = entry.capabilities.map(cap => `<span class="cap-chip">${escapeHtml(cap)}</span>`).join("");
    return `<p class="plugin-caps">${chips}</p>`;
  }

  function providesHtml(entry) {
    if (!entry.provides?.length) return "";
    const chips = entry.provides.map(name => `<span class="cap-chip cap-provides">@${escapeHtml(name)}</span>`).join("");
    return `<p class="plugin-caps">stellt bereit: ${chips}</p>`;
  }

  function headHtml(entry, version) {
    const status = entry.status ? `<span class="plugin-badge plugin-status-${escapeHtml(entry.status)}">${escapeHtml(STATUS_LABELS[entry.status] || entry.status)}</span>` : "";
    const source = entry.source ? `<span class="plugin-badge">${escapeHtml(entry.source)}</span>` : "";
    return `<div class="plugin-card-head"><span class="plugin-name">${escapeHtml(entry.name)}</span>` +
      `<span class="plugin-version">${escapeHtml(version || "")}</span>${status}${source}</div>` +
      (entry.description ? `<p class="plugin-description muted">${escapeHtml(entry.description)}</p>` : "") +
      (entry.message ? `<p class="plugin-message">${escapeHtml(entry.message)}</p>` : "") +
      (entry.loadedVersion && entry.loadedVersion !== entry.installedVersion
        ? `<p class="muted">Aktuell geladen: ${escapeHtml(entry.loadedVersion)}. Nach Neustart: ${escapeHtml(entry.installedVersion)}.</p>` : "") +
      depsHtml(entry) + capsHtml(entry) + providesHtml(entry);
  }

  function installedCard(entry) {
    const li = document.createElement("li");
    li.className = "plugin-card";
    const update = entry.updateAvailable
      ? `<button type="button" class="plugin-update">${icon("refresh")} Aktualisieren auf ${escapeHtml(entry.availableVersion)}</button>`
      : "";
    const deinstall = entry.source === "user"
      ? `<label><input type="checkbox" class="plugin-purge"> Gespeicherte Daten ebenfalls löschen</label>` +
        `<button type="button" class="plugin-deinstall danger">${icon("trash")} Deinstallieren</button>`
      : "";
    li.innerHTML = headHtml(entry, entry.installedVersion) +
      `<div class="plugin-actions">` +
      `<label class="toolbar-toggle"><input type="checkbox" class="plugin-toggle" ${entry.enabled ? "checked" : ""}> aktiviert</label>` +
      update + deinstall + `</div>`;

    li.querySelector(".plugin-toggle").addEventListener("change", async (event) => {
      const enabled = event.target.checked;
      try {
        await api(`/api/plugins/${encodeURIComponent(entry.id)}/enabled`, { method: "POST", body: JSON.stringify({ enabled }) });
        onChanged();
        await load();
      } catch (error) {
        event.target.checked = !enabled;
        setLocalStatus(error.message);
      }
    });
    const updateButton = li.querySelector(".plugin-update");
    if (updateButton) updateButton.addEventListener("click", async () => {
      updateButton.disabled = true;
      try {
        await api("/api/marketplace/update", { method: "POST", body: JSON.stringify({ id: entry.id }) });
        onChanged();
        await load();
      } catch (error) {
        updateButton.disabled = false;
        setLocalStatus(error.message);
      }
    });
    const deinstallButton = li.querySelector(".plugin-deinstall");
    if (deinstallButton) deinstallButton.addEventListener("click", async () => {
      if (!window.confirm(`Plugin „${entry.name}“ deinstallieren?`)) return;
      const purge = li.querySelector(".plugin-purge").checked;
      try {
        await api("/api/marketplace/uninstall", { method: "POST", body: JSON.stringify({ id: entry.id, purge }) });
      } catch (error) {
        if (error.status === 409 && window.confirm(`${error.message}\n\nTrotzdem deinstallieren (abhängige Plugins verlieren die Abhängigkeit)?`)) {
          try {
            await api("/api/marketplace/uninstall", { method: "POST", body: JSON.stringify({ id: entry.id, purge, force: true }) });
          } catch (retryError) {
            setLocalStatus(retryError.message);
            return;
          }
        } else {
          setLocalStatus(error.message);
          return;
        }
      }
      onChanged();
      await load();
    });
    return li;
  }

  function availableCard(entry) {
    const li = document.createElement("li");
    li.className = "plugin-card";
    li.innerHTML = headHtml(entry, entry.availableVersion) +
      `<div class="plugin-actions"><button type="button" class="plugin-install">${icon("plus")} Installieren</button></div>`;
    li.querySelector(".plugin-install").addEventListener("click", async (event) => {
      event.target.disabled = true;
      try {
        const result = await api("/api/marketplace/install", {
          method: "POST", timeout: CATALOG_TIMEOUT, body: JSON.stringify({ id: entry.id })
        });
        const installed = (result.actions || []).filter(a => a.action !== "keep")
          .map(a => `${a.id} ${a.version}`).join(", ");
        setLocalStatus(installed ? `Installiert: ${installed}` : "Bereits aktuell installiert.");
        onChanged();
        await load();
      } catch (error) {
        event.target.disabled = false;
        setLocalStatus(error.message);
      }
    });
    return li;
  }

  async function load() {
    setLocalStatus("Marketplace wird geladen …");
    try {
      const data = await api("/api/marketplace", { timeout: CATALOG_TIMEOUT });
      plugins = data.plugins || [];
      render();
      const commit = (data.catalog?.commit || "").slice(0, 12);
      setLocalStatus(data.catalog?.warning
        ? data.catalog.warning
        : `${plugins.length} Plugins (Katalog ${data.catalog?.repo || ""} @ ${commit || "?"})`);
    } catch (error) {
      setLocalStatus(`Marketplace nicht erreichbar: ${error.message}`);
      setStatus(`Marketplace nicht erreichbar: ${error.message}`, "error");
    }
  }

  async function refresh() {
    setLocalStatus("Katalog wird aktualisiert …");
    try {
      await api("/api/marketplace/refresh", { method: "POST", timeout: CATALOG_TIMEOUT });
    } catch (error) {
      setLocalStatus(`Katalog-Refresh fehlgeschlagen: ${error.message}`);
    }
    await load();
  }

  elements.marketplaceSearch.addEventListener("input", (event) => {
    filter = event.target.value.trim();
    render();
  });

  return { load, refresh };
}
