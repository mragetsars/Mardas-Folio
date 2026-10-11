import { optionalLocalStorage } from "./storage.mjs";

export const PREFERENCES_STORAGE_KEY = "mardas.desktop.preferences.v1";

export const DEFAULT_PREFERENCES = Object.freeze({
  theme: "system",
  contentScale: "comfortable",
  writingWidth: "comfortable",
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
    writingWidth: value?.writingWidth === "wide" ? "wide" : DEFAULT_PREFERENCES.writingWidth,
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
