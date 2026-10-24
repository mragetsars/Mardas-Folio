import test from "node:test";
import assert from "node:assert/strict";
import { saveDocumentsBeforeUpdate } from "../frontend/js/core/update-preparation.mjs";
import { createSaveCoordinator } from "../frontend/js/core/save-coordinator.mjs";

test("an update waits for an existing save and persists edits newer than its snapshot", async () => {
  const model = { id: "a", content: "newer", saved: "disk" };
  const isDirty = (item) => item.content !== item.saved;
  const coordinator = createSaveCoordinator({ isDirty });
  let complete;
  const pendingSave = coordinator.save(model, () => new Promise((resolve) => {
    complete = () => { model.saved = "older snapshot"; resolve(true); };
  }));
  let saves = 0;
  let finished = false;
  const preparing = saveDocumentsBeforeUpdate({
    getDocuments: () => [model], isDirty, confirm: async () => true,
    save: (item) => coordinator.save(item, async () => {
      saves += 1;
      item.saved = item.content;
      return true;
    }),
  }).then((result) => { finished = true; return result; });
  await Promise.resolve();
  assert.equal(finished, false);
  complete();
  await pendingSave;
  assert.equal(await preparing, true);
  assert.equal(saves, 1);
  assert.equal(model.saved, "newer");
});

test("a cancelled picker or save conflict prevents installation with drafts intact", async () => {
  const models = [{ id: "a", dirty: true }, { id: "b", dirty: true }];
  const saved = [];
  assert.equal(await saveDocumentsBeforeUpdate({
    getDocuments: () => models, isDirty: (item) => item.dirty,
    confirm: async () => true,
    save: async (item) => { saved.push(item.id); return false; },
  }), false);
  assert.deepEqual(saved, ["a"]);
  assert.ok(models.every((item) => item.dirty));
});

test("saving all dirty documents is independent of browser recovery quotas", async () => {
  const models = Array.from({ length: 14 }, (_, index) => ({ id: index, dirty: true }));
  assert.equal(await saveDocumentsBeforeUpdate({
    getDocuments: () => models, isDirty: (item) => item.dirty,
    confirm: async () => true,
    save: async (item) => { item.dirty = false; return true; },
  }), true);
  assert.ok(models.every((item) => !item.dirty));
});

test("a new dirty buffer arriving during preparation cancels installation", async () => {
  const models = [{ id: "a", dirty: true }];
  assert.equal(await saveDocumentsBeforeUpdate({
    getDocuments: () => models, isDirty: (item) => item.dirty,
    confirm: async () => true,
    save: async (item) => { item.dirty = false; models.push({ id: "b", dirty: true }); return true; },
  }), false);
});
