export function createModalController({ state, focusEditor }) {
  function uiIcon(name) {
    return `<svg class="icon" aria-hidden="true" focusable="false"><use href="/static/icons.svg#${name}"></use></svg>`;
  }

  function openModal(modal, focusTarget) {
    const active = document.activeElement;
    state.lastFocus = active?.closest(".document-settings, .discussion-menu")?.querySelector(":scope > summary") || active;
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    setTimeout(() => focusTarget?.focus?.(), 0);
  }

  function closeModal(modal) {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    const target = state.lastFocus;
    setTimeout(() => {
      if (target?.isConnected && target.getClientRects().length && !target.disabled) target.focus();
      else focusEditor?.();
    }, 0);
  }

  function trapModalFocus(event) {
    if (event.key !== "Tab") return;
    const modal = [...document.querySelectorAll('.modal.open')]
      .sort((a, b) => Number(getComputedStyle(a).zIndex) - Number(getComputedStyle(b).zIndex)).at(-1);
    if (!modal) return;
    const focusable = [...modal.querySelectorAll("button, input, select, textarea, [tabindex]:not([tabindex='-1'])")]
      .filter((element) => !element.disabled && element.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return { uiIcon, openModal, closeModal, trapModalFocus };
}
