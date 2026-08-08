import test from "node:test";
import assert from "node:assert/strict";
import { createSaveCoordinator } from "../frontend/js/core/save-coordinator.mjs";

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("saves for one document are serialized and a dirty follow-up uses the latest buffer", async () => {
  const document = { id: "a", content: "A", savedContent: "old" };
  const coordinator = createSaveCoordinator({ isDirty: (model) => model.content !== model.savedContent });
  const firstGate = deferred();
  const snapshots = [];
  const first = coordinator.save(document, async (model) => {
    const snapshot = model.content;
    snapshots.push(snapshot);
    await firstGate.promise;
    model.savedContent = snapshot;
    return true;
  });
  await Promise.resolve();
  document.content = "B";
  const second = coordinator.save(document, async (model) => {
    snapshots.push(model.content);
    model.savedContent = model.content;
    return true;
  });

  assert.deepEqual(snapshots, ["A"]);
  firstGate.resolve();
  assert.equal(await first, true);
  assert.equal(await second, true);
  assert.deepEqual(snapshots, ["A", "B"]);
  assert.equal(document.savedContent, "B");
});

test("different documents can save independently", async () => {
  const coordinator = createSaveCoordinator({ isDirty: () => true });
  const gate = deferred();
  const first = coordinator.save({ id: "a" }, () => gate.promise);
  const second = coordinator.save({ id: "b" }, async () => true);
  assert.equal(await second, true);
  gate.resolve(true);
  assert.equal(await first, true);
});

test("three queued saves keep one per-document tail and preserve snapshot order", async () => {
  const document = { id: "a", content: "A", savedContent: "old" };
  const coordinator = createSaveCoordinator({ isDirty: (model) => model.content !== model.savedContent });
  const firstGate = deferred();
  const secondGate = deferred();
  let active = 0;
  let maximumActive = 0;
  const snapshots = [];

  const operation = (gate = null) => async (model) => {
    const snapshot = model.content;
    snapshots.push(snapshot);
    active += 1;
    maximumActive = Math.max(maximumActive, active);
    if (gate) await gate.promise;
    model.savedContent = snapshot;
    active -= 1;
    return true;
  };

  const first = coordinator.save(document, operation(firstGate));
  await Promise.resolve();
  document.content = "B";
  const second = coordinator.save(document, operation(secondGate));
  const third = coordinator.save(document, operation());

  assert.deepEqual(snapshots, ["A"]);
  firstGate.resolve();
  await first;
  await Promise.resolve();
  assert.deepEqual(snapshots, ["A", "B"]);

  document.content = "C";
  secondGate.resolve();
  assert.equal(await second, true);
  assert.equal(await third, true);
  assert.deepEqual(snapshots, ["A", "B", "C"]);
  assert.equal(maximumActive, 1);
  assert.equal(document.savedContent, "C");
});
