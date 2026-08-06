import test from "node:test";
import assert from "node:assert/strict";
import { readSession, writeSession } from "../frontend/js/core/session.mjs";

function storage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}

test("authoring session stores unique saved paths and active path", () => {
  const store = storage();
  writeSession(
    [{ path: "C:\\A.md" }, { path: "c:/a.md" }, { path: null }, { path: "/b.md" }],
    { path: "/b.md" },
    "C:\\Project",
    store,
  );
  assert.deepEqual(readSession(store), {
    paths: ["C:\\A.md", "/b.md"],
    activePath: "/b.md",
    projectPath: "C:\\Project",
  });
});
