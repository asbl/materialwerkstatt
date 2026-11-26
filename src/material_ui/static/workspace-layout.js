export function createWorkspaceLayout({ elements, uiIcon, ensureChatProvidersLoaded }) {
  const INDEX_WIDTH_KEY = "material-ui:index-width";
  const INDEX_WIDTH_MIN = 240;
  const INDEX_WIDTH_MAX = 480;
  let indexWidth = loadIndexWidthPreference();

  function loadIndexWidthPreference() {
    try {
      const value = Number(localStorage.getItem(INDEX_WIDTH_KEY));
      if (Number.isFinite(value) && value >= INDEX_WIDTH_MIN && value <= INDEX_WIDTH_MAX) return value;
    } catch {
      return 300;
    }
    return 300;
  }

  function setIndexCollapsed(collapsed) {
    elements.workspace.classList.toggle("index-collapsed", collapsed);
    elements.indexContent.hidden = collapsed;
    elements.toggleIndex.innerHTML = uiIcon(collapsed ? "chevron-right" : "chevron-left");
    elements.toggleIndex.setAttribute("aria-expanded", String(!collapsed));
    elements.toggleIndex.setAttribute("aria-label", collapsed ? "Index ausklappen" : "Index einklappen");
    elements.toggleIndex.title = collapsed ? "Index ausklappen" : "Index einklappen";
    applyIndexWidth();
  }

  function setFocusMode(active) {
    elements.workspace.classList.toggle("focus-mode", active);
    const label = active ? "Fokus-Modus beenden (Esc)" : "Fokus-Modus (Seitenleiste ausblenden)";
    elements.toggleFocusMode.innerHTML = uiIcon(active ? "minimize" : "maximize");
    elements.toggleFocusMode.setAttribute("aria-pressed", String(active));
    elements.toggleFocusMode.setAttribute("aria-label", label);
    elements.toggleFocusMode.title = label;
  }

  function setFocusModePersisted(active) {
    setFocusMode(active);
    try {
      localStorage.setItem("material-ui:focus-mode", String(active));
    } catch {
      return;
    }
  }

  function setChatOpen(open) {
    elements.workspace.classList.toggle("chat-open", open);
    elements.showChat.setAttribute("aria-pressed", String(open));
    elements.showChat.setAttribute("aria-label", open ? "Chat schließen" : "Chat öffnen");
    elements.showChat.title = open ? "Chat schließen" : "Chat mit Wissensbasis öffnen";
    if (open) {
      ensureChatProvidersLoaded();
      setTimeout(() => elements.chatInput.focus(), 0);
    }
  }

  function setChatOpenPersisted(open) {
    setChatOpen(open);
    try {
      localStorage.setItem("material-ui:chat-open", String(open));
    } catch {
      return;
    }
  }

  function applyIndexWidth() {
    elements.workspace.style.setProperty("--index-width", `${indexWidth}px`);
  }

  function bindPreviewControls() {
    const viewButtons = [...document.querySelectorAll("[data-workspace-view]")];
    const narrow = matchMedia("(max-width: 1199px)");
    let preferredView = null;
    try { preferredView = localStorage.getItem("material-ui:workspace-view"); } catch {}
    const applyView = () => {
      const view = ["edit", "preview", "split"].includes(preferredView) ? preferredView : narrow.matches ? "edit" : "split";
      elements.workspace.dataset.view = view;
      for (const item of viewButtons) item.setAttribute("aria-pressed", String(item.dataset.workspaceView === view));
      window.dispatchEvent(new Event("resize"));
    };
    for (const item of viewButtons) item.addEventListener("click", () => {
      preferredView = item.dataset.workspaceView;
      try { localStorage.setItem("material-ui:workspace-view", preferredView); } catch {}
      applyView();
    });
    narrow.addEventListener("change", applyView);
    const navigation = document.getElementById("workspaceNavigation");
    const closeNavigation = () => {
      elements.workspace.classList.remove("navigation-open");
      navigation.setAttribute("aria-expanded", "false");
    };
    navigation.addEventListener("click", () => {
      const open = elements.workspace.classList.toggle("navigation-open");
      navigation.setAttribute("aria-expanded", String(open));
      if (open) setIndexCollapsed(false);
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") closeNavigation();
    });
    // Schmale Fenster: Die Navigation ist eine Schublade. Ein Klick daneben oder die Wahl
    // eines Dokuments schliesst sie, damit sie den Editor nicht dauerhaft verdeckt.
    document.addEventListener("click", event => {
      if (!elements.workspace.classList.contains("navigation-open") || !narrow.matches) return;
      if (event.target.closest(".workspace-index, #workspaceNavigation, .modal, dialog")) return;
      closeNavigation();
    });
    document.addEventListener("material-document-opened", event => {
      if (narrow.matches && event.detail?.path) closeNavigation();
    });
    applyView();
    const resizer = document.getElementById("previewResizer");
    const button = document.getElementById("togglePdfFullscreen");
    const editorPane = document.querySelector(".editor-pane");
    const preview = document.querySelector(".preview-pane");
    let previewShare = 50;
    const setShare = (share) => {
      previewShare = Math.min(80, Math.max(20, share));
      elements.workspace.style.setProperty("--editor-share", `${100 - previewShare}fr`);
      elements.workspace.style.setProperty("--preview-share", `${previewShare}fr`);
      resizer.setAttribute("aria-valuenow", String(Math.round(previewShare)));
    };
    resizer.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      resizer.setPointerCapture(event.pointerId);
      resizer.classList.add("active");
      document.body.classList.add("resizing-preview");
      const startX = event.clientX;
      const startShare = previewShare;
      const width = editorPane.getBoundingClientRect().width + preview.getBoundingClientRect().width;
      const move = (moveEvent) => setShare(startShare - (moveEvent.clientX - startX) / width * 100);
      const finish = () => {
        resizer.classList.remove("active");
        document.body.classList.remove("resizing-preview");
        resizer.removeEventListener("pointermove", move);
        resizer.removeEventListener("lostpointercapture", finish);
      };
      resizer.addEventListener("pointermove", move);
      resizer.addEventListener("lostpointercapture", finish);
    });
    resizer.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "Home") setShare(20);
      else if (event.key === "End") setShare(80);
      else setShare(previewShare + (event.key === "ArrowLeft" ? 5 : -5));
    });
    const setFullscreen = (active) => {
      document.body.classList.toggle("pdf-fullscreen", active);
      const label = active ? "PDF-Vollbild schließen (Esc)" : "PDF-Vollbild öffnen";
      button.setAttribute("aria-label", label);
      button.setAttribute("aria-pressed", String(active));
      button.title = label;
      button.innerHTML = uiIcon(active ? "minimize" : "maximize");
      for (const panel of document.querySelectorAll(".app-header, .workspace-view-controls, .workspace-index, .editor-pane")) {
        panel.inert = active;
      }
      button.focus();
    };
    button.addEventListener("click", async () => {
      const active = !document.body.classList.contains("pdf-fullscreen");
      try {
        if (active && preview.requestFullscreen) await preview.requestFullscreen();
        else if (!active && document.fullscreenElement === preview) await document.exitFullscreen();
      } catch {
        setFullscreen(active);
        return;
      }
      setFullscreen(active);
    });
    document.addEventListener("fullscreenchange", () => {
      setFullscreen(document.fullscreenElement === preview);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && document.body.classList.contains("pdf-fullscreen")) {
        event.preventDefault();
        setFullscreen(false);
        if (document.fullscreenElement === preview) document.exitFullscreen().catch(() => {});
      }
    });
  }

  function bindIndexResizer() {
    const resizer = elements.indexResizer;
    resizer.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      resizer.setPointerCapture(event.pointerId);
      resizer.classList.add("active");
      const startX = event.clientX;
      const startWidth = indexWidth;
      const move = (moveEvent) => {
        indexWidth = Math.min(INDEX_WIDTH_MAX, Math.max(INDEX_WIDTH_MIN, startWidth + moveEvent.clientX - startX));
        applyIndexWidth();
      };
      const finish = () => {
        resizer.classList.remove("active");
        resizer.removeEventListener("pointermove", move);
        resizer.removeEventListener("pointerup", finish);
        resizer.removeEventListener("pointercancel", finish);
        try {
          localStorage.setItem(INDEX_WIDTH_KEY, String(indexWidth));
        } catch {
          return;
        }
      };
      resizer.addEventListener("pointermove", move);
      resizer.addEventListener("pointerup", finish);
      resizer.addEventListener("pointercancel", finish);
    });
  }


  return { setIndexCollapsed, setFocusMode, setFocusModePersisted, setChatOpen, setChatOpenPersisted, applyIndexWidth, bindPreviewControls, bindIndexResizer };
}

// Plugins declare which host slots their mode uses; only the host changes visibility.
export function createWorkspaceChrome(elements) {
  let previous = null;
  return function setChrome(chrome = null) {
    if (previous) {
      if (previous.className) elements.workspace.classList.remove(previous.className);
      for (const key of previous.hide || []) elements[key].hidden = false;
      for (const key of previous.show || []) elements[key].hidden = true;
    }
    if (chrome) {
      elements.workspace.classList.remove("note-mode");
      document.body.classList.remove("note-document");
      if (chrome.className) elements.workspace.classList.add(chrome.className);
      for (const key of chrome.hide || []) elements[key].hidden = true;
      for (const key of chrome.show || []) elements[key].hidden = false;
    }
    previous = chrome;
  };
}
