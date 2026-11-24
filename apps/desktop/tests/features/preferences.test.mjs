import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_PREFERENCES,
  applyPreferences,
  normalizePreferences,
  nextDocumentZoom,
  editorModeForView,
  previewVisibleForView,
  readPreferences,
  writePreferences,
} from "../../frontend/js/features/settings/preferences.mjs";

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
}

test("preferences normalize invalid values and persist safely", () => {
  assert.deepEqual(
    normalizePreferences({ theme: "neon", contentScale: "huge" }),
    DEFAULT_PREFERENCES,
  );
  const store = storage();
  const value = writePreferences(
    {
      theme: "dark",
      contentScale: "large",
      reducedMotion: "reduce",
      autoPreview: false,
      onboardingComplete: true,
    },
    store,
  );
  assert.equal(value.theme, "dark");
  assert.deepEqual(readPreferences(store), value);
});

test("preferences resolve system appearance without network state", () => {
  const dataset = {};
  applyPreferences(
    { dataset },
    {
      theme: "system",
      contentScale: "extra-large",
      reducedMotion: "system",
      autoPreview: true,
      onboardingComplete: false,
    },
    (query) => ({ matches: query.includes("dark") || query.includes("reduced-motion") }),
  );
  assert.equal(dataset.theme, "dark");
  assert.equal(dataset.themePreference, "system");
  assert.equal(dataset.contentScale, "extra-large");
  assert.equal(dataset.reducedMotion, "reduce");
});

test("accent settings migrate, validate and survive a restart", () => {
  assert.equal(normalizePreferences({ theme: "dark" }).accent, "monochrome");
  assert.equal(normalizePreferences({ accent: "unknown" }).accent, "monochrome");
  assert.equal(normalizePreferences({ accent: "gray" }).accent, "monochrome");
  for (const accent of ["monochrome", "blue", "red", "amber", "green", "teal", "purple", "pink"]) {
    const store = storage();
    writePreferences({ accent, theme: "dark" }, store);
    const dataset = {};
    applyPreferences({ dataset }, readPreferences(store));
    assert.equal(dataset.accent, accent);
    assert.equal(dataset.theme, "dark");
  }
});

test("existing width presets migrate and arbitrary width values persist", () => {
  assert.equal(normalizePreferences().writingWidth, 45);
  for (const [writingWidth, percent] of Object.entries({
    comfortable: 100,
    full: 100,
    readable: 45,
    wide: 65,
  }))
    assert.equal(normalizePreferences({ writingWidth }).writingWidth, percent);
  assert.equal(normalizePreferences({ writingWidth: 12 }).writingWidth, 25);
  assert.equal(normalizePreferences({ writingWidth: 140 }).writingWidth, 100);
  const store = storage();
  writePreferences({ writingWidth: 73 }, store);
  assert.equal(readPreferences(store).writingWidth, 73);
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
  applyPreferences(
    { dataset, style: { setProperty: (key, value) => properties.set(key, value) } },
    {
      documentZoom: 150,
      writingWidth: "full",
    },
  );
  assert.equal(dataset.documentZoom, "150");
  assert.equal(dataset.contentScale, "comfortable");
  assert.equal(properties.get("--writing-column"), "100%");
  assert.equal(properties.get("--document-text-scale"), "1.5");
  assert.equal(properties.get("--writing-line-height"), "1.65");
  assert.equal(properties.get("--writing-paragraph-gap"), "8px");
  assert.equal(properties.get("--writing-font-family"), "var(--prose-font, var(--app-font))");
});

test("legacy Split migrates to editable Source with an independent side preview", () => {
  const store = storage({
    "mardas.desktop.preferences.v1": JSON.stringify({
      viewMode: "split",
      documentZoom: 125,
      autoPreview: false,
    }),
  });
  const migrated = readPreferences(store);
  assert.equal(migrated.viewMode, "source");
  assert.equal(migrated.sidePreview, true);
  assert.equal(migrated.documentZoom, 125);
  assert.equal(migrated.autoPreview, false);
  writePreferences(migrated, store);
  assert.deepEqual(readPreferences(store), migrated);
});

test("side preview is a remembered layout choice for either editing representation", () => {
  const store = storage();
  for (const viewMode of ["write", "source", "write"]) {
    const current = writePreferences(
      { ...readPreferences(store), viewMode, sidePreview: true },
      store,
    );
    assert.equal(current.sidePreview, true);
    assert.equal(previewVisibleForView(current.viewMode, current.sidePreview), true);
    assert.equal(editorModeForView(current.viewMode), viewMode === "write" ? "live" : "source");
  }
  assert.equal(
    writePreferences({ viewMode: "source", sidePreview: false }, store).sidePreview,
    false,
  );
  assert.equal(readPreferences(store).viewMode, "source");
  assert.equal(normalizePreferences({ viewMode: "read" }).viewMode, "write");
  for (const sidePreview of [null, "true", 1, {}]) {
    assert.equal(normalizePreferences({ viewMode: "write", sidePreview }).sidePreview, false);
  }
});
