import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_WORKSPACE_LAYOUT,
  clampWorkspaceWidth,
  fitWorkspaceWidths,
  normalizeWorkspaceLayout,
  readWorkspaceLayout,
  writeWorkspaceLayout,
} from "../../frontend/js/features/workspace/workspace-layout.mjs";

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
}

test("workspace layout normalizes visibility and bounded pane widths", () => {
  assert.deepEqual(normalizeWorkspaceLayout({}), DEFAULT_WORKSPACE_LAYOUT);
  assert.equal(clampWorkspaceWidth("sidebar", 10), 248);
  assert.equal(clampWorkspaceWidth("sidebar", 9999), 420);
  assert.equal(clampWorkspaceWidth("preview", 10), 340);
  assert.equal(clampWorkspaceWidth("preview", 9999), 760);
  assert.equal(clampWorkspaceWidth("files", 10), 208);
  assert.equal(clampWorkspaceWidth("files", 9999), 360);
  assert.throws(() => clampWorkspaceWidth("unknown", 300), /Unknown workspace pane/);
});

test("workspace layout persists safely without making editing depend on storage", () => {
  const store = storage();
  const written = writeWorkspaceLayout({
    sidebarOpen: false,
    previewOpen: true,
    sidebarWidth: 320,
    previewWidth: 620,
  }, store);
  assert.deepEqual(readWorkspaceLayout(store), written);

  const broken = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
  };
  assert.deepEqual(readWorkspaceLayout(broken), DEFAULT_WORKSPACE_LAYOUT);
  assert.equal(writeWorkspaceLayout({ sidebarWidth: 280 }, broken).sidebarWidth, 280);
});

test("four panes fit the viewport without destroying preferred widths", () => {
  const preferred = { ...DEFAULT_WORKSPACE_LAYOUT, filesOpen: true, sidebarOpen: true, previewOpen: true,
    filesWidth: 360, sidebarWidth: 420, previewWidth: 760 };
  for (const width of [1280, 1440, 1920]) {
    const fitted = fitWorkspaceWidths(preferred, width);
    assert.ok(width - fitted.filesWidth - fitted.sidebarWidth - fitted.previewWidth - 3 >= 320);
    assert.ok(fitted.filesWidth >= 208 && fitted.sidebarWidth >= 248 && fitted.previewWidth >= 340);
  }
  assert.equal(preferred.previewWidth, 760);
  assert.deepEqual(fitWorkspaceWidths(preferred, 2200), preferred);
  assert.equal(fitWorkspaceWidths(preferred, 768).previewWidth, 447);
});
