import { optionalLocalStorage } from "./storage.mjs";

export const WORKSPACE_LAYOUT_STORAGE_KEY = "mardas.desktop.workspace-layout.v2";

export const DEFAULT_WORKSPACE_LAYOUT = Object.freeze({
  filesOpen: true,
  filesWidth: 248,
  sidebarOpen: false,
  previewOpen: false,
  formattingOpen: true,
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
