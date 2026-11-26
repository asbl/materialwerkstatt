const TABS_KEY = "material-ui:open-tabs";
const MAX_TABS = 12;

export function createTabsController({ state, elements, escapeHtml, uiIcon, tabLabel, selectDocument, closeDocument, flushPendingSave, setStatus }) {
  let contextMenu = null;

  function hideContextMenu() {
    contextMenu?.remove();
    contextMenu = null;
  }

  async function prepareClose(path) {
    if (path !== state.qmdPath) return true;
    const pending = state.dirty || state.saveTimer || state.savePromise;
    if (pending && !state.autoSave && !window.confirm(`Änderungen an „${tabLabel(path)}“ speichern und schließen?`)) return false;
    await flushPendingSave();
    return path === state.qmdPath;
  }

  async function runTabAction(action) {
    try {
      await action();
    } catch (error) {
      setStatus(`Tabs konnten nicht geschlossen werden: ${error.message}`, "error");
    }
  }

  function loadTabs() {
    try {
      const value = JSON.parse(localStorage.getItem(TABS_KEY) || "[]");
      if (Array.isArray(value)) return value.filter((item) => typeof item === "string");
    } catch {
      return [];
    }
    return [];
  }

  function persistTabs() {
    try {
      localStorage.setItem(TABS_KEY, JSON.stringify(state.tabs));
    } catch {
      return;
    }
  }

  function restoreTabs(paths) {
    state.tabs = paths.filter((path) => typeof path === "string").slice(0, MAX_TABS);
    persistTabs();
    renderTabs();
  }

  function registerTab(path) {
    if (!path) return;
    if (state.tabs.includes(path)) {
      renderTabs();
      return;
    }
    state.tabs.push(path);
    if (state.tabs.length > MAX_TABS) state.tabs = state.tabs.slice(-MAX_TABS);
    persistTabs();
    renderTabs();
  }

  function removeTab(path) {
    state.tabs = state.tabs.filter((item) => item !== path);
    persistTabs();
    renderTabs();
  }

  function renameTab(oldPath, newPath) {
    if (oldPath === newPath) return;
    state.tabs = state.tabs.map((item) => (item === oldPath ? newPath : item));
    persistTabs();
    renderTabs();
  }

  async function closeTab(path) {
    const index = state.tabs.indexOf(path);
    if (index === -1) return;
    if (!(await prepareClose(path))) return;
    if (path === state.qmdPath) {
      const neighbor = state.tabs[index + 1] || state.tabs[index - 1];
      if (neighbor) {
        await selectDocument(neighbor);
        if (state.qmdPath !== neighbor) return;
      } else await closeDocument();
    }
    removeTab(path);
  }

  async function closeOtherTabs(path) {
    if (!state.tabs.includes(path)) return;
    if (state.qmdPath && state.qmdPath !== path) {
      if (!(await prepareClose(state.qmdPath))) return;
      await selectDocument(path);
      if (state.qmdPath !== path) return;
    }
    state.tabs = state.tabs.filter((item) => item === path);
    persistTabs();
    renderTabs();
  }

  function renderTabs() {
    hideContextMenu();
    const container = elements.documentTabs;
    if (!container) return;
    container.hidden = state.tabs.length === 0;
    container.innerHTML = state.tabs.map((path) => {
      const active = path === state.qmdPath;
      return `<div class="document-tab${active ? " active" : ""}" data-tab-path="${escapeHtml(path)}">`
        + `<button type="button" class="document-tab-button" data-tab="${escapeHtml(path)}" title="${escapeHtml(path)}" aria-current="${active}">${escapeHtml(tabLabel(path))}</button>`
        + `<button type="button" class="document-tab-close" data-tab-close="${escapeHtml(path)}" aria-label="${escapeHtml(tabLabel(path))} schließen">${uiIcon("close")}</button>`
        + `</div>`;
    }).join("");
  }

  function bindTabs() {
    const container = elements.documentTabs;
    if (!container) return;
    container.addEventListener("click", (event) => {
      const close = event.target.closest("[data-tab-close]");
      if (close) {
        runTabAction(() => closeTab(close.dataset.tabClose));
        return;
      }
      const tab = event.target.closest("[data-tab]");
      if (tab) selectDocument(tab.dataset.tab);
    });
    container.addEventListener("auxclick", (event) => {
      if (event.button !== 1) return;
      const tab = event.target.closest("[data-tab-path]");
      if (tab) {
        event.preventDefault();
        runTabAction(() => closeTab(tab.dataset.tabPath));
      }
    });
    container.addEventListener("contextmenu", (event) => {
      const tab = event.target.closest("[data-tab-path]");
      if (!tab) return;
      event.preventDefault();
      hideContextMenu();
      const menu = document.createElement("div");
      menu.className = "header-menu-panel document-tab-menu";
      menu.setAttribute("role", "menu");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Andere Tabs schließen";
      button.setAttribute("role", "menuitem");
      button.disabled = state.tabs.length < 2;
      button.addEventListener("click", () => {
        hideContextMenu();
        runTabAction(() => closeOtherTabs(tab.dataset.tabPath));
      });
      menu.append(button);
      document.body.append(menu);
      contextMenu = menu;
      const bounds = menu.getBoundingClientRect();
      menu.style.left = `${Math.max(0, Math.min(event.clientX, window.innerWidth - bounds.width))}px`;
      menu.style.top = `${Math.max(0, Math.min(event.clientY, window.innerHeight - bounds.height))}px`;
      button.focus();
    });
    document.addEventListener("pointerdown", (event) => {
      if (contextMenu && !contextMenu.contains(event.target)) hideContextMenu();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !contextMenu) return;
      hideContextMenu();
      container.querySelector('[aria-current="true"]')?.focus();
      event.preventDefault();
    });
    container.addEventListener("scroll", hideContextMenu);
    window.addEventListener("resize", hideContextMenu);
  }

  return { loadTabs, restoreTabs, registerTab, removeTab, renameTab, closeTab, closeOtherTabs, renderTabs, bindTabs };
}
