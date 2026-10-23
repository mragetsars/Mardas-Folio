import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_PREFERENCES,
  applyPreferences,
  normalizePreferences,
  nextDocumentZoom,
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

test("existing narrow defaults migrate to a full canvas while explicit new widths persist", () => {
  assert.equal(normalizePreferences().writingWidth, "full");
  assert.equal(normalizePreferences({ writingWidth: "comfortable" }).writingWidth, "full");
  for (const writingWidth of ["full", "readable", "wide"]) {
    const store = storage();
    writePreferences({ writingWidth }, store);
    assert.equal(readPreferences(store).writingWidth, writingWidth);
  }
});

test("document text zoom preserves legacy accessibility sizes and bounds malformed stored values", () => {
  assert.equal(normalizePreferences({ contentScale: "large" }).documentZoom, 112);
  assert.equal(normalizePreferences({ contentScale: "extra-large" }).documentZoom, 124);
  assert.equal(normalizePreferences({ documentZoom: 10 }).documentZoom, 60);
  assert.equal(normalizePreferences({ documentZoom: 999 }).documentZoom, 200);
  for (const documentZoom of [NaN, Infinity, null, "180", {}]) {
    assert.equal(normalizePreferences({ documentZoom }).documentZoom, 100);
  }
  const store = storage();
  writePreferences({ documentZoom: 85 }, store);
  assert.equal(readPreferences(store).documentZoom, 85);
});

test("document text controls step cleanly from legacy percentages without exceeding limits", () => {
  assert.equal(nextDocumentZoom(112, 1), 120);
  assert.equal(nextDocumentZoom(124, -1), 120);
  assert.equal(nextDocumentZoom(60, -1), 60);
  assert.equal(nextDocumentZoom(200, 1), 200);
  assert.equal(nextDocumentZoom(100, -1), 90);
  assert.equal(nextDocumentZoom(100, 1), 110);
});

test("document text zoom exposes its own scale without altering the interface or legacy scale", () => {
  const dataset = {};
  const properties = new Map();
  applyPreferences({ dataset, style: { setProperty: (key, value) => properties.set(key, value) } }, {
    documentZoom: 150,
    writingWidth: "full",
  });
  assert.equal(dataset.documentZoom, "150");
  assert.equal(dataset.contentScale, "comfortable");
  assert.equal(dataset.writingWidth, "full");
  assert.deepEqual([...properties], [["--document-text-scale", "1.5"]]);
});
