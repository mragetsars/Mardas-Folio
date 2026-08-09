import { optionalLocalStorage } from "./storage.mjs";

export const PREFERENCES_STORAGE_KEY = "mardas.desktop.preferences.v1";

export const DEFAULT_PREFERENCES = Object.freeze({
  theme: "system",
  contentScale: "comfortable",
  reducedMotion: "system",
  autoPreview: true,
  editorMode: "live",
  onboardingComplete: false,
});

const THEMES = new Set(["system", "light", "dark"]);
const SCALES = new Set(["comfortable", "large", "extra-large"]);
const MOTION = new Set(["system", "reduce", "full"]);
// Live preview renders Markdown as it will read; source shows the raw text.
const EDITOR_MODES = new Set(["live", "source"]);

function booleanValue(value, fallback) {
  return typeof value === "boolean" ? value : fallback;
}

export function normalizePreferences(value = {}) {
  return {
    theme: THEMES.has(value?.theme) ? value.theme : DEFAULT_PREFERENCES.theme,
    contentScale: SCALES.has(value?.contentScale) ? value.contentScale : DEFAULT_PREFERENCES.contentScale,
    reducedMotion: MOTION.has(value?.reducedMotion) ? value.reducedMotion : DEFAULT_PREFERENCES.reducedMotion,
    autoPreview: booleanValue(value?.autoPreview, DEFAULT_PREFERENCES.autoPreview),
    editorMode: EDITOR_MODES.has(value?.editorMode) ? value.editorMode : DEFAULT_PREFERENCES.editorMode,
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
  documentElement.dataset.reducedMotion = resolvedReducedMotion(normalized.reducedMotion, matchMedia) ? "reduce" : "full";
  return normalized;
}
