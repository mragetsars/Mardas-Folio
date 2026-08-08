import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_PREFERENCES,
  applyPreferences,
  normalizePreferences,
  readPreferences,
  writePreferences,
} from "../frontend/js/core/preferences.mjs";

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
}

test("preferences normalize invalid values and persist safely", () => {
  assert.deepEqual(normalizePreferences({ theme: "neon", contentScale: "huge" }), DEFAULT_PREFERENCES);
  const store = storage();
  const value = writePreferences({
    theme: "dark",
    contentScale: "large",
    reducedMotion: "reduce",
    autoPreview: false,
    onboardingComplete: true,
  }, store);
  assert.equal(value.theme, "dark");
  assert.deepEqual(readPreferences(store), value);
});

test("preferences resolve system appearance without network state", () => {
  const dataset = {};
  applyPreferences({ dataset }, {
    theme: "system",
    contentScale: "extra-large",
    reducedMotion: "system",
    autoPreview: true,
    onboardingComplete: false,
  }, (query) => ({ matches: query.includes("dark") || query.includes("reduced-motion") }));
  assert.equal(dataset.theme, "dark");
  assert.equal(dataset.themePreference, "system");
  assert.equal(dataset.contentScale, "extra-large");
  assert.equal(dataset.reducedMotion, "reduce");
});
