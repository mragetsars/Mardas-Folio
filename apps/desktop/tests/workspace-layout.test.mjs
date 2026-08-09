import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_WORKSPACE_LAYOUT,
  clampWorkspaceWidth,
  normalizeWorkspaceLayout,
  readWorkspaceLayout,
  writeWorkspaceLayout,
} from "../frontend/js/core/workspace-layout.mjs";

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
