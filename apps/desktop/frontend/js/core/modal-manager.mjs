const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function isVisible(element) {
  if (!element) return false;
  if (element.hidden) return false;
  if (element.closest?.(".hidden")) return false;
  return true;
}

export function focusableElements(modal) {
  return [...(modal?.querySelectorAll?.(FOCUSABLE_SELECTOR) || [])].filter(isVisible);
}

export function createModalManager(documentRef = globalThis.document) {
  const openStack = [];
  const previousFocus = new WeakMap();
  const optionsByModal = new WeakMap();
  const shell = () => documentRef?.querySelector?.(".shell");

  function updateBackground() {
    const background = shell();
    if (!background) return;
    const active = openStack.length > 0;
    background.inert = active;
    if (active) background.setAttribute?.("aria-hidden", "true");
    else background.removeAttribute?.("aria-hidden");
  }

  /**
   * Focus the dialog without scrolling it away from its own beginning.
   *
   * Focusing a control scrolls its scrollable ancestors to reveal it, and a
   * dialog taller than the window is such an ancestor. The help dialog opened
   * 273px down its own card — past its title and its first two sections —
   * because the control it focused was the button at the far end of it.
   *
   * So: focus without scrolling, put the card back at the top, and only then
   * bring the focused control into view if it is genuinely out of it. A
   * dialog whose first control is in its heading, which is all of them, ends
   * up exactly where it should.
   */
  function focusInitial(modal, initialFocus) {
    const candidate = typeof initialFocus === "string"
      ? modal.querySelector?.(initialFocus)
      : initialFocus;
    const target = candidate || focusableElements(modal)[0] || modal;
    if (!target || typeof target.focus !== "function") return;
    target.focus({ preventScroll: true });
    for (const region of [modal, modal.querySelector?.(".modal-card")]) {
      if (region && typeof region.scrollTop === "number") region.scrollTop = 0;
    }
    if (target !== modal && typeof target.scrollIntoView === "function") {
      const card = modal.querySelector?.(".modal-card");
      const box = target.getBoundingClientRect?.();
      const frame = card?.getBoundingClientRect?.();
      if (box && frame && (box.top < frame.top || box.bottom > frame.bottom)) {
        target.scrollIntoView({ block: "nearest" });
      }
    }
  }

  function open(modal, { initialFocus = null, returnFocus = null, escape = true, onClose = null } = {}) {
    if (!modal || openStack.includes(modal)) return;
    previousFocus.set(modal, returnFocus || documentRef?.activeElement || null);
    optionsByModal.set(modal, { escape: escape !== false, onClose });
    modal.classList?.remove("hidden");
    modal.setAttribute?.("aria-hidden", "false");
    if (!modal.hasAttribute?.("tabindex")) modal.setAttribute?.("tabindex", "-1");
    openStack.push(modal);
    updateBackground();
    queueMicrotask(() => focusInitial(modal, initialFocus));
  }

  function close(modal, { restoreFocus = true, reason = "programmatic" } = {}) {
    if (!modal) return;
    const index = openStack.lastIndexOf(modal);
    if (index >= 0) openStack.splice(index, 1);
    modal.classList?.add("hidden");
    modal.setAttribute?.("aria-hidden", "true");
    updateBackground();
    const options = optionsByModal.get(modal);
    optionsByModal.delete(modal);
    if (typeof options?.onClose === "function") options.onClose(reason);
    if (restoreFocus) {
      const target = previousFocus.get(modal);
      if (target && typeof target.focus === "function") queueMicrotask(() => target.focus());
    }
  }

  function closeTop() {
    const modal = openStack.at(-1);
    if (modal) close(modal);
    return modal;
  }

  function handleKeydown(event) {
    const modal = openStack.at(-1);
    if (!modal) return false;
    if (event.key === "Escape") {
      if (optionsByModal.get(modal)?.escape === false) return false;
      event.preventDefault();
      close(modal, { reason: "escape" });
      modal.dispatchEvent?.(new CustomEvent("mardas-modal-close", { bubbles: false }));
      return true;
    }
    if (event.key !== "Tab") return false;
    const items = focusableElements(modal);
    if (!items.length) {
      event.preventDefault();
      modal.focus?.();
      return true;
    }
    const currentIndex = items.indexOf(documentRef.activeElement);
    const nextIndex = event.shiftKey
      ? (currentIndex <= 0 ? items.length - 1 : currentIndex - 1)
      : (currentIndex < 0 || currentIndex === items.length - 1 ? 0 : currentIndex + 1);
    event.preventDefault();
    items[nextIndex].focus?.();
    return true;
  }

  documentRef?.addEventListener?.("keydown", handleKeydown, true);

  return {
    open,
    close,
    closeTop,
    isOpen: (modal) => openStack.includes(modal),
    hasOpenModal: () => openStack.length > 0,
    destroy() {
      documentRef?.removeEventListener?.("keydown", handleKeydown, true);
      openStack.splice(0);
      updateBackground();
    },
  };
}
