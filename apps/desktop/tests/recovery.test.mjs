import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_RECOVERY_CHARS,
  readRecoveries,
  recoveryForPath,
  removeRecovery,
  saveRecovery,
} from "../frontend/js/core/recovery.mjs";

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
}

test("recovery snapshots are bounded and addressable by path", () => {
  const storage = memoryStorage();
  const document = { id: "1", path: "C:\\Docs\\a.md", title: "a.md", content: "dirty", revision: "r1" };
  assert.equal(saveRecovery(document, storage, 10).ok, true);
  assert.equal(recoveryForPath("c:/docs/a.md", storage).content, "dirty");
  assert.equal(readRecoveries(storage).length, 1);
  removeRecovery(document, storage);
  assert.equal(readRecoveries(storage).length, 0);
});

test("oversized browser recovery is rejected without throwing", () => {
  const storage = memoryStorage();
  const result = saveRecovery({ id: "1", path: null, title: "x", content: "x".repeat(MAX_RECOVERY_CHARS + 1) }, storage);
  assert.equal(result.ok, false);
  assert.equal(result.reason, "too_large");
});
