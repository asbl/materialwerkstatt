import { createWorkspaceSettings } from "./workspace-settings.js";
import { createMarketplaceController } from "./marketplace.js";
import { createUpdateController } from "./app-update.js";

// Einstellungen-Dialog mit den Reitern „Ordner“, „Plugins“ (Marketplace) und „Version“.

export function createSettingsController({ elements, api, openModal, closeModal, setStatus, restartServer }) {
  const marketplace = createMarketplaceController({
    elements,
    api,
    setStatus,
    onChanged: () => { elements.marketplaceRestartBanner.hidden = false; }
  });

  const folders = createWorkspaceSettings({ api, restartServer });
  const updates = createUpdateController({ api, restartServer, openUpdateSettings: () => openSettingsModal("settingsTabVersion") });
  const tabs = [["settingsTabFolders", "settingsFolders", folders], ["settingsTabPlugins", "settingsPlugins", marketplace],
    ["settingsTabVersion", "settingsVersion", updates]]
    .map(([tab, panel, controller]) => ({ tab: document.getElementById(tab), panel: document.getElementById(panel), controller }));

  async function select(chosen) {
    for (const entry of tabs) {
      const active = entry === chosen;
      entry.tab.setAttribute("aria-selected", String(active));
      entry.tab.tabIndex = active ? 0 : -1;
      entry.panel.hidden = !active;
    }
    // Der Plugin-Katalog wird erst geladen, wenn sein Reiter geöffnet wird (git-Zugriff).
    await chosen.controller.load();
  }

  tabs.forEach((entry, index) => {
    entry.tab.addEventListener("click", () => select(entry));
    entry.tab.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      const step = event.key === "ArrowRight" ? 1 : -1;
      const next = tabs[(index + step + tabs.length) % tabs.length];
      next.tab.focus();
      select(next);
    });
  });

  // Als Klick-Handler bekommt die Funktion ein Event; nur eine Reiter-ID waehlt gezielt.
  async function openSettingsModal(tabId) {
    const current = tabs.find(entry => entry.tab.id === tabId) || tabs.find(entry => !entry.panel.hidden) || tabs[0];
    openModal(elements.settingsModal, current.tab);
    await select(current);
  }

  function closeSettingsModal() {
    closeModal(elements.settingsModal);
  }

  elements.closeSettingsModal.addEventListener("click", closeSettingsModal);
  elements.closeSettingsModalButton.addEventListener("click", closeSettingsModal);
  elements.marketplaceRefresh.addEventListener("click", () => marketplace.refresh());
  elements.marketplaceRestart.addEventListener("click", () => restartServer());

  updates.start();

  return { openSettingsModal, closeSettingsModal };
}
