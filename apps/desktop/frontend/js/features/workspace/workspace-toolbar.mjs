/** Move existing controls into one overflow surface, preserving their state,
 * handlers and DOM identity. No duplicate command can drift out of sync. */
export function createWorkspaceToolbar({ toolbar, menu, trigger, onLayout }) {
  if (!toolbar || !menu || !trigger) return null;
  const selectors = [
    ".document-view-controls",
    "#document-mode-help",
    ".document-edit-controls",
    "#format-find",
  ];
  const controls = selectors
    .map((selector) => {
      const node = toolbar.querySelector(selector);
      if (!node) return null;
      const home = document.createComment(`toolbar ${selector}`);
      node.before(home);
      return { node, home };
    })
    .filter(Boolean);
  let frame = 0;
  let disposed = false;
  function close({ focus = false } = {}) {
    menu.classList.add("hidden");
    trigger.setAttribute("aria-expanded", "false");
    if (focus) trigger.focus({ preventScroll: true });
  }
  function position() {
    const box = trigger.getBoundingClientRect();
    menu.style.position = "fixed";
    menu.style.top = `${box.bottom + 6}px`;
    // Clear logical offsets first: a later inset-inline:auto would override
    // physical left in LTR (and RTL), detaching the menu from its trigger.
    menu.style.removeProperty("inset-inline-start");
    menu.style.removeProperty("inset-inline-end");
    menu.style.right = "auto";
    menu.style.left = `${Math.max(8, Math.min(box.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 8))}px`;
    menu.style.maxHeight = `${Math.max(100, innerHeight - box.bottom - 14)}px`;
    menu.style.overflowY = "auto";
  }
  function sync() {
    if (disposed || !toolbar.offsetWidth) return;
    const focused = document.activeElement;
    const wasInMenu = menu.contains(focused);
    for (const { node, home } of controls) home.after(node);
    trigger.hidden = true;
    // Fixed groups reserve their intrinsic width; the format strip may shrink
    // only to its explicit minimum. Its own overflow handles individual tools.
    for (const { node } of controls) {
      if (toolbar.scrollWidth <= toolbar.clientWidth + 1) break;
      if (!node.getClientRects().length) continue;
      trigger.hidden = false;
      menu.append(node);
    }
    if (!menu.children.length) {
      trigger.hidden = true;
      close();
    }
    if (wasInMenu && focused?.isConnected) {
      if (menu.contains(focused) && !menu.classList.contains("hidden"))
        focused.focus({ preventScroll: true });
      else if (focused.getClientRects().length) focused.focus({ preventScroll: true });
      else trigger.focus({ preventScroll: true });
    } else if (controls.some(({ node }) => node.contains(focused)) && menu.contains(focused)) {
      trigger.focus({ preventScroll: true });
    }
    if (!menu.classList.contains("hidden")) position();
    onLayout?.();
  }
  function schedule() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(sync);
  }
  function toggle() {
    if (!menu.children.length) return;
    const open = menu.classList.contains("hidden");
    close();
    if (open) {
      menu.classList.remove("hidden");
      trigger.setAttribute("aria-expanded", "true");
      position();
      menu.querySelector("button:not(:disabled),select:not(:disabled)")?.focus();
    }
  }
  const click = (event) => {
    if (!menu.contains(event.target) && !trigger.contains(event.target)) close();
  };
  const key = (event) => {
    if (event.key === "Escape" && !menu.classList.contains("hidden")) {
      event.preventDefault();
      event.stopPropagation();
      close({ focus: true });
    }
  };
  const invoke = (event) => {
    const button = event.target.closest("button");
    if (
      button?.matches(
        "#writing-appearance-button,#insert-menu-button,#document-mode-help,#format-find",
      )
    ) {
      // Child popovers measure their actual trigger before their parent is
      // dismissed. Returning focus later uses the visible overflow trigger.
      queueMicrotask(() => close());
    }
  };
  trigger.addEventListener("click", toggle);
  menu.addEventListener("keydown", key);
  menu.addEventListener("click", invoke, true);
  document.addEventListener("click", click);
  const resize = new ResizeObserver(schedule);
  resize.observe(toolbar);
  const mutations = new MutationObserver(schedule);
  // Mode, language and formatting visibility can change required width while
  // leaving the outer toolbar's dimensions unchanged.
  mutations.observe(document.querySelector("#workspace-view"), {
    attributes: true,
    attributeFilter: ["data-formatting-open", "data-view-mode", "class"],
  });
  mutations.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["lang", "dir"],
  });
  schedule();
  return {
    sync: schedule,
    close,
    destroy() {
      disposed = true;
      cancelAnimationFrame(frame);
      resize.disconnect();
      mutations.disconnect();
      trigger.removeEventListener("click", toggle);
      menu.removeEventListener("keydown", key);
      menu.removeEventListener("click", invoke, true);
      document.removeEventListener("click", click);
    },
  };
}
