import { optionalLocalStorage } from "../../adapters/storage.mjs";

export const WORKSPACE_LAYOUT_STORAGE_KEY = "mardas.desktop.workspace-layout.v2";

export const DEFAULT_WORKSPACE_LAYOUT = Object.freeze({
  filesOpen: false,
  filesWidth: 248,
  sidebarOpen: false,
  previewOpen: false,
  formattingOpen: false,
  navigatorTab: "files",
  sidebarWidth: 296,
  previewWidth: 500,
});

const LIMITS = Object.freeze({
  files: Object.freeze({ min: 208, max: 360 }),
  sidebar: Object.freeze({ min: 248, max: 420 }),
  preview: Object.freeze({ min: 340, max: 760 }),
});

function booleanValue(value, fallback) {
  return typeof value === "boolean" ? value : fallback;
}

function finiteInteger(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number) : fallback;
}

export function clampWorkspaceWidth(kind, value) {
  const limits = LIMITS[kind];
  if (!limits) throw new TypeError(`Unknown workspace pane: ${kind}`);
  const fallback = DEFAULT_WORKSPACE_LAYOUT[`${kind}Width`];
  return Math.max(limits.min, Math.min(limits.max, finiteInteger(value, fallback)));
}

export function normalizeWorkspaceLayout(value = {}) {
  return {
    filesOpen: booleanValue(value?.filesOpen, DEFAULT_WORKSPACE_LAYOUT.filesOpen),
    filesWidth: clampWorkspaceWidth("files", value?.filesWidth),
    formattingOpen: booleanValue(value?.formattingOpen, DEFAULT_WORKSPACE_LAYOUT.formattingOpen),
    navigatorTab: value?.navigatorTab === "outline" ? "outline" : "files",
    sidebarOpen: booleanValue(value?.sidebarOpen, DEFAULT_WORKSPACE_LAYOUT.sidebarOpen),
    previewOpen: booleanValue(value?.previewOpen, DEFAULT_WORKSPACE_LAYOUT.previewOpen),
    sidebarWidth: clampWorkspaceWidth("sidebar", value?.sidebarWidth),
    previewWidth: clampWorkspaceWidth("preview", value?.previewWidth),
  };
}

/** Fit visible columns while keeping preferred widths intact for a wider window. */
export function fitWorkspaceWidths(value, availableWidth) {
  const layout = normalizeWorkspaceLayout(value);
  const width = Math.max(0, Number(availableWidth) || 0);
  if (width <= 1100) {
    if (width > 760 && layout.previewOpen)
      layout.previewWidth = Math.min(layout.previewWidth, Math.max(340, width - 321));
    return layout;
  }
  const kinds = ["files", "preview", "sidebar"].filter((kind) => layout[`${kind}Open`]);
  const minimum = kinds.reduce((total, kind) => total + LIMITS[kind].min, 0);
  const desired = kinds.reduce((total, kind) => total + layout[`${kind}Width`], 0);
  const budget = Math.max(minimum, width - 320 - kinds.length);
  if (desired <= budget) return layout;
  const fraction = (budget - minimum) / (desired - minimum);
  for (const kind of kinds)
    layout[`${kind}Width`] = Math.floor(
      LIMITS[kind].min + (layout[`${kind}Width`] - LIMITS[kind].min) * fraction,
    );
  return layout;
}

export function readWorkspaceLayout(storage = undefined) {
  const localStorage = optionalLocalStorage(storage);
  try {
    return normalizeWorkspaceLayout(
      JSON.parse(localStorage?.getItem(WORKSPACE_LAYOUT_STORAGE_KEY) || "{}"),
    );
  } catch {
    return { ...DEFAULT_WORKSPACE_LAYOUT };
  }
}

export function writeWorkspaceLayout(value, storage = undefined) {
  const normalized = normalizeWorkspaceLayout(value);
  const localStorage = optionalLocalStorage(storage);
  try {
    localStorage?.setItem(WORKSPACE_LAYOUT_STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    // Workspace geometry is convenience state; persistence must never block editing.
  }
  return normalized;
}
