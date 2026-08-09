export const WORKSPACE_LAYOUT_STORAGE_KEY = "mardas.desktop.workspace-layout.v1";

export const DEFAULT_WORKSPACE_LAYOUT = Object.freeze({
  sidebarOpen: true,
  previewOpen: true,
  sidebarWidth: 296,
  previewWidth: 500,
});

const LIMITS = Object.freeze({
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
  const fallback = kind === "sidebar"
    ? DEFAULT_WORKSPACE_LAYOUT.sidebarWidth
    : DEFAULT_WORKSPACE_LAYOUT.previewWidth;
  return Math.max(limits.min, Math.min(limits.max, finiteInteger(value, fallback)));
}

export function normalizeWorkspaceLayout(value = {}) {
  return {
    sidebarOpen: booleanValue(value?.sidebarOpen, DEFAULT_WORKSPACE_LAYOUT.sidebarOpen),
    previewOpen: booleanValue(value?.previewOpen, DEFAULT_WORKSPACE_LAYOUT.previewOpen),
    sidebarWidth: clampWorkspaceWidth("sidebar", value?.sidebarWidth),
    previewWidth: clampWorkspaceWidth("preview", value?.previewWidth),
  };
}

export function readWorkspaceLayout(storage = globalThis.localStorage) {
  try {
    return normalizeWorkspaceLayout(
      JSON.parse(storage?.getItem(WORKSPACE_LAYOUT_STORAGE_KEY) || "{}"),
    );
  } catch {
    return { ...DEFAULT_WORKSPACE_LAYOUT };
  }
}

export function writeWorkspaceLayout(value, storage = globalThis.localStorage) {
  const normalized = normalizeWorkspaceLayout(value);
  try {
    storage?.setItem(WORKSPACE_LAYOUT_STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    // Workspace geometry is convenience state; persistence must never block editing.
  }
  return normalized;
}
