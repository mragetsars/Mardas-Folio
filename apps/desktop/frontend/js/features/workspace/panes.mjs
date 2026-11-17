import {
  DEFAULT_WORKSPACE_LAYOUT,
  clampWorkspaceWidth,
  fitWorkspaceWidths,
  writeWorkspaceLayout,
} from "./workspace-layout.mjs";
/** Owns this feature's DOM interactions; cross-feature actions are injected. */
export function createWorkspacePanes({
  state,
  query: $,
  queryAll: $$,
  compactSidePanes,
  activeDocument,
  isMarkdownModel,
  focusDocument,
}) {
  function applyWorkspaceLayout({ persist = false } = {}) {
    const grid = $(".authoring-grid");
    const workspace = $("#workspace-view");
    if (!grid || !workspace) return;
    if (persist) state.workspaceLayout = writeWorkspaceLayout(state.workspaceLayout);
    const layout = {
      ...state.workspaceLayout,
      filesOpen: workspacePaneOpen("files"),
      sidebarOpen: workspacePaneOpen("sidebar"),
    };
    const fitted = fitWorkspaceWidths(layout, grid.clientWidth || innerWidth);
    for (const element of [workspace, grid]) {
      element.dataset.filesOpen = String(layout.filesOpen);
      element.dataset.formattingOpen = String(layout.formattingOpen);
      element.dataset.sidebarOpen = String(layout.sidebarOpen);
      element.dataset.previewOpen = String(layout.previewOpen);
      element.style.setProperty("--sidebar-width", `${fitted.sidebarWidth}px`);
      element.style.setProperty("--files-width", `${fitted.filesWidth}px`);
      element.style.setProperty("--preview-width", `${fitted.previewWidth}px`);
    }
    const sidebarButton = $("#workspace-toggle-sidebar");
    const sidebarResizer = $("#sidebar-resizer");
    const previewResizer = $("#preview-resizer");
    $("#workspace-toggle-files")?.setAttribute("aria-pressed", String(layout.filesOpen));
    $("#workspace-toggle-formatting")?.setAttribute("aria-pressed", String(layout.formattingOpen));
    $("#workspace-toggle-formatting")?.setAttribute("aria-expanded", String(layout.formattingOpen));
    $("#file-resizer")?.setAttribute("aria-valuenow", String(fitted.filesWidth));
    $("#file-navigator").inert = !layout.filesOpen;
    $("#author-sidebar").inert = !layout.sidebarOpen;
    sidebarButton?.setAttribute("aria-pressed", String(layout.sidebarOpen));
    if (sidebarResizer) sidebarResizer.setAttribute("aria-valuenow", String(fitted.sidebarWidth));
    if (previewResizer) previewResizer.setAttribute("aria-valuenow", String(fitted.previewWidth));
    applyNavigatorContext();
  }

  function applyNavigatorContext() {
    const model = activeDocument();
    const markdown = Boolean(model && isMarkdownModel(model));
    const tab = markdown ? state.workspaceLayout.navigatorTab : "files";
    for (const button of $$("[data-navigator-tab]")) {
      const active = button.dataset.navigatorTab === tab;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      button.disabled = button.dataset.navigatorTab === "outline" && !markdown;
    }
    for (const [name, selector] of [
      ["files", "#navigator-panel-files"],
      ["outline", "#sidebar-panel-outline"],
    ]) {
      const panel = $(selector);
      if (panel) {
        panel.hidden = tab !== name;
        panel.inert = tab !== name;
      }
    }
    $(".navigator-footer")?.classList.toggle("hidden", tab === "outline");
  }

  function activateNavigator(name) {
    if (name === "outline" && (!activeDocument() || !isMarkdownModel(activeDocument()))) return;
    state.workspaceLayout.navigatorTab = name;
    setWorkspacePaneOpen("files", true);
    applyWorkspaceLayout({ persist: true });
  }

  function isCompactDrawer(name) {
    return compactSidePanes.matches && (name === "files" || name === "sidebar");
  }

  function workspacePaneOpen(name) {
    return isCompactDrawer(name)
      ? state.compactDrawer === name
      : state.workspaceLayout[`${name}Open`];
  }

  function setWorkspacePaneOpen(name, open) {
    if (isCompactDrawer(name)) {
      if (open || state.compactDrawer === name) state.compactDrawer = open ? name : null;
      return;
    }
    state.workspaceLayout[`${name}Open`] = open;
  }

  function toggleWorkspacePane(name, { keepFocus = false } = {}) {
    const open = !workspacePaneOpen(name);
    setWorkspacePaneOpen(name, open);
    applyWorkspaceLayout({ persist: !isCompactDrawer(name) });
    if (!open && !keepFocus) focusDocument();
  }

  function resetWorkspacePaneSizes() {
    for (const pane of ["files", "sidebar", "preview"]) {
      state.workspaceLayout[`${pane}Width`] = DEFAULT_WORKSPACE_LAYOUT[`${pane}Width`];
    }
    applyWorkspaceLayout({ persist: true });
  }

  function closeCompactDrawer(name = state.compactDrawer) {
    if (!name || state.compactDrawer !== name) return;
    state.compactDrawer = null;
    applyWorkspaceLayout();
  }

  function setWorkspacePaneWidth(name, value, { persist = false } = {}) {
    const key = `${name}Width`;
    state.workspaceLayout = {
      ...state.workspaceLayout,
      [key]: clampWorkspaceWidth(name, value),
    };
    applyWorkspaceLayout({ persist });
  }

  /**
   * Which way a pane grows when the pointer moves right.
   *
   * The side bar sits on the inline start of the workbench and the preview on
   * the inline end, so in a right-to-left interface both are on the opposite
   * physical edge and a drag that widened a pane now has to narrow it. Reading
   * the sign from the document's direction keeps the handle following the
   * pointer in either language instead of running away from it.
   */
  function paneResizeSign(name) {
    const mirrored = document.documentElement.dir === "rtl" ? -1 : 1;
    return (name === "files" ? 1 : -1) * mirrored;
  }

  let finishPaneResize = null;
  function beginPaneResize(event, name) {
    if (event.button !== 0 || isCompactDrawer(name) || (name === "preview" && innerWidth <= 760))
      return;
    finishPaneResize?.();
    event.preventDefault();
    const handle = event.currentTarget;
    const startX = event.clientX;
    const sign = paneResizeSign(name);
    const preferredWidth = state.workspaceLayout[`${name}Width`];
    const startWidth = Number(handle.getAttribute("aria-valuenow")) || preferredWidth;
    handle.classList.add("is-dragging");
    document.documentElement.dataset.paneResizing = name;
    handle.setPointerCapture?.(event.pointerId);
    const move = (moveEvent) => {
      if (moveEvent.pointerId !== event.pointerId) return;
      const delta = moveEvent.clientX - startX;
      setWorkspacePaneWidth(name, startWidth + sign * delta);
    };
    let finished = false;
    const finish = (revert = false) => {
      if (finished) return;
      finished = true;
      if (revert) setWorkspacePaneWidth(name, preferredWidth);
      handle.classList.remove("is-dragging");
      delete document.documentElement.dataset.paneResizing;
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      handle.removeEventListener("lostpointercapture", end);
      document.removeEventListener("keydown", keydown, true);
      window.removeEventListener("blur", end);
      if (handle.hasPointerCapture?.(event.pointerId))
        handle.releasePointerCapture(event.pointerId);
      state.workspaceLayout = writeWorkspaceLayout(state.workspaceLayout);
      finishPaneResize = null;
    };
    const end = () => finish();
    const keydown = (keyEvent) => {
      if (keyEvent.key !== "Escape") return;
      keyEvent.preventDefault();
      keyEvent.stopImmediatePropagation();
      finish(true);
    };
    finishPaneResize = end;
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    handle.addEventListener("lostpointercapture", end);
    document.addEventListener("keydown", keydown, true);
    window.addEventListener("blur", end);
  }

  function resizePaneWithKeyboard(event, name) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current =
      Number(event.currentTarget.getAttribute("aria-valuenow")) ||
      state.workspaceLayout[`${name}Width`];
    const sign = paneResizeSign(name);
    let next = current;
    if (event.key === "ArrowLeft") next -= sign * 16;
    if (event.key === "ArrowRight") next += sign * 16;
    if (event.key === "Home") next = clampWorkspaceWidth(name, 0);
    if (event.key === "End") next = clampWorkspaceWidth(name, 9999);
    setWorkspacePaneWidth(name, next, { persist: true });
  }
  return {
    applyWorkspaceLayout,
    applyNavigatorContext,
    activateNavigator,
    isCompactDrawer,
    workspacePaneOpen,
    setWorkspacePaneOpen,
    toggleWorkspacePane,
    resetWorkspacePaneSizes,
    closeCompactDrawer,
    beginPaneResize,
    resizePaneWithKeyboard,
  };
}
