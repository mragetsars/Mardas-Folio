import { optionalLocalStorage } from "./storage.mjs";

export const PREFERENCES_STORAGE_KEY = "mardas.desktop.preferences.v1";

export const DEFAULT_PREFERENCES = Object.freeze({
  theme: "system",
  contentScale: "comfortable",
  writingWidth: "full",
  documentZoom: 100,
  reducedMotion: "system",
  autoPreview: true,
  viewMode: "write",
  /**
   * Keeps the caret's line at a fixed height while writing.
   *
   * Off by default: scroll position is something writers build a physical
   * habit around, and taking it over uninvited is disorienting.
   */
  typewriter: false,
  /** Hides everything but the document. */
  focusMode: false,
  onboardingComplete: false,
});

const THEMES = new Set(["system", "light", "dark"]);
const SCALES = new Set(["comfortable", "large", "extra-large"]);
const WRITING_WIDTHS = new Set(["full", "readable", "wide"]);
const LEGACY_ZOOM = { comfortable: 100, large: 112, "extra-large": 124 };
export const DOCUMENT_ZOOM_MIN = 60;
export const DOCUMENT_ZOOM_MAX = 200;

export function normalizeDocumentZoom(value, fallback = 100) {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(DOCUMENT_ZOOM_MIN, Math.min(DOCUMENT_ZOOM_MAX, Math.round(value)))
    : fallback;
}

export function nextDocumentZoom(value, direction) {
  const current = normalizeDocumentZoom(value);
  // Step to the next whole ten even when an older preference was 112/124%.
  const next = direction > 0 ? Math.floor(current / 10) * 10 + 10 : Math.ceil(current / 10) * 10 - 10;
  return normalizeDocumentZoom(next);
}
const MOTION = new Set(["system", "reduce", "full"]);
/**
 * Write formats the editable Markdown in place, Source exposes its syntax,
 * Read uses a separate noneditable article, and Split compares source/result.
 * The comparison pane follows this choice rather than an independent toggle.
 */
const VIEW_MODES = new Set(["write", "source", "read", "split"]);

function booleanValue(value, fallback) {
  return typeof value === "boolean" ? value : fallback;
}

export function normalizePreferences(value = {}) {
  return {
    theme: THEMES.has(value?.theme) ? value.theme : DEFAULT_PREFERENCES.theme,
    contentScale: SCALES.has(value?.contentScale) ? value.contentScale : DEFAULT_PREFERENCES.contentScale,
    // "comfortable" was the old implicit narrow default. Full width gives
    // existing installations the same new canvas as fresh ones; the optional
    // readable column has its own value so a new explicit choice is retained.
    writingWidth: WRITING_WIDTHS.has(value?.writingWidth) ? value.writingWidth : DEFAULT_PREFERENCES.writingWidth,
    documentZoom: normalizeDocumentZoom(value?.documentZoom, LEGACY_ZOOM[value?.contentScale] || DEFAULT_PREFERENCES.documentZoom),
    reducedMotion: MOTION.has(value?.reducedMotion) ? value.reducedMotion : DEFAULT_PREFERENCES.reducedMotion,
    autoPreview: booleanValue(value?.autoPreview, DEFAULT_PREFERENCES.autoPreview),
    viewMode: VIEW_MODES.has(value?.viewMode) ? value.viewMode : DEFAULT_PREFERENCES.viewMode,
    typewriter: booleanValue(value?.typewriter, DEFAULT_PREFERENCES.typewriter),
    focusMode: booleanValue(value?.focusMode, DEFAULT_PREFERENCES.focusMode),
    onboardingComplete: booleanValue(value?.onboardingComplete, DEFAULT_PREFERENCES.onboardingComplete),
  };
}

export function readPreferences(storage = undefined) {
  const localStorage = optionalLocalStorage(storage);
  try {
    return normalizePreferences(JSON.parse(localStorage?.getItem(PREFERENCES_STORAGE_KEY) || "{}"));
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

export function writePreferences(value, storage = undefined) {
  const normalized = normalizePreferences(value);
  const localStorage = optionalLocalStorage(storage);
  try {
    localStorage?.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    // Preferences are convenience state; failures must not block document workflows.
  }
  return normalized;
}

export function resolvedTheme(theme, matchMedia = globalThis.matchMedia) {
  if (theme !== "system") return theme;
  try {
    return matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function resolvedReducedMotion(value, matchMedia = globalThis.matchMedia) {
  if (value === "reduce") return true;
  if (value === "full") return false;
  try {
    return Boolean(matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
  } catch {
    return false;
  }
}

export function applyPreferences(documentElement, value, matchMedia = globalThis.matchMedia) {
  const normalized = normalizePreferences(value);
  documentElement.dataset.theme = resolvedTheme(normalized.theme, matchMedia);
  documentElement.dataset.themePreference = normalized.theme;
  documentElement.dataset.contentScale = normalized.contentScale;
  documentElement.dataset.writingWidth = normalized.writingWidth;
  documentElement.dataset.documentZoom = String(normalized.documentZoom);
  documentElement.style?.setProperty("--document-text-scale", String(normalized.documentZoom / 100));
  documentElement.dataset.reducedMotion = resolvedReducedMotion(normalized.reducedMotion, matchMedia) ? "reduce" : "full";
  documentElement.dataset.focusMode = String(normalized.focusMode);
  documentElement.dataset.typewriter = String(normalized.typewriter);
  return normalized;
}

/** The editor rendering a view mode implies. */
export function editorModeForView(viewMode) {
  return viewMode === "write" ? "live" : "source";
}

/** Whether a view mode shows the engine preview pane. */
export function previewVisibleForView(viewMode) {
  return viewMode === "split";
}
