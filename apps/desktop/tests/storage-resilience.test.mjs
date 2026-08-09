import test from "node:test";
import assert from "node:assert/strict";

import { readPreferences, writePreferences } from "../frontend/js/core/preferences.mjs";
import { readWorkspaceLayout, writeWorkspaceLayout } from "../frontend/js/core/workspace-layout.mjs";
import { readRecents, writeRecents } from "../frontend/js/core/recents.mjs";
import { readSession, writeSession } from "../frontend/js/core/session.mjs";
import {
  readRecoveries,
  recoveryForPath,
  removeRecovery,
  saveRecovery,
  writeRecoveries,
} from "../frontend/js/core/recovery.mjs";

function withThrowingLocalStorage(callback) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    get() {
      throw new Error("storage blocked");
    },
  });
  try {
    callback();
  } finally {
    if (descriptor) Object.defineProperty(globalThis, "localStorage", descriptor);
    else delete globalThis.localStorage;
  }
}

test("optional browser state survives a throwing localStorage getter", () => {
  withThrowingLocalStorage(() => {
    assert.equal(readPreferences().theme, "system");
    assert.equal(writePreferences({ theme: "dark" }).theme, "dark");

    assert.deepEqual(readRecents(), []);
    assert.equal(writeRecents([{ path: "/tmp/a.md", openedAt: 1 }]).length, 1);

    assert.deepEqual(readSession(), { paths: [], activePath: null, projectPath: null });
    assert.deepEqual(writeSession([], null), { paths: [], activePath: null, projectPath: null });

    assert.equal(readWorkspaceLayout().sidebarOpen, true);
    assert.equal(writeWorkspaceLayout({ sidebarOpen: false }).sidebarOpen, false);

    assert.deepEqual(readRecoveries(), []);
    assert.equal(writeRecoveries([]).ok, false);
    assert.equal(recoveryForPath("/tmp/a.md"), null);
    assert.equal(removeRecovery("path:/tmp/a.md").ok, false);
    assert.equal(saveRecovery({ id: "draft", path: null, title: "Draft", content: "x", revision: null }).ok, false);
  });
});
