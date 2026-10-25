import test from "node:test";
import assert from "node:assert/strict";
import { documentBelongsToProject, prepareBookFiles } from "../frontend/js/core/book-preparation.mjs";
import { createSaveCoordinator } from "../frontend/js/core/save-coordinator.mjs";

const dirty = (model) => model.content !== model.saved;
const chapter = (name, content = "edited") => ({ id: name, path: `/book/chapters/${name}.md`, content, saved: "disk" });

test("project scope includes directly opened resources but excludes sibling folders", () => {
  assert.equal(documentBelongsToProject({ path: "/book/references.bib" }, "/book"), true);
  assert.equal(documentBelongsToProject({ path: "/bookish/chapter.md" }, "/book"), false);
  assert.equal(documentBelongsToProject({ path: "C:\\BOOK\\chapters\\a.md" }, "c:/book/"), true);
  assert.equal(documentBelongsToProject({ path: "\\\\?\\C:\\BOOK\\chapters\\a.md" }, "c:/book"), true);
  assert.equal(documentBelongsToProject({ path: "\\\\?\\UNC\\server\\share\\book\\a.md" }, "//server/share/book"), true);
  assert.equal(documentBelongsToProject({ projectPath: "/book", path: null }, "/book"), true);
});

test("book review saves changed chapters and project resources before consuming disk", async () => {
  const models = [chapter("one"), chapter("two"), { id: "config", path: "/book/mardas.toml", content: "new config", saved: "old" }, chapter("unrelated")];
  models[3].path = "/other/book.md";
  const writes = [];
  assert.equal(await prepareBookFiles({
    projectPath: "/book", getDocuments: () => models, isDirty: dirty,
    confirm: async (pending) => { assert.equal(pending.length, 3); return true; },
    save: async (model) => { writes.push(model.id); model.saved = model.content; return true; },
  }), true);
  assert.deepEqual(writes, ["one", "two", "config"]);
  assert.ok(models.slice(0, 3).every((model) => !dirty(model)));
  assert.equal(dirty(models[3]), true);
});

test("cancelled confirmation, picker or conflict never consumes unsaved input", async () => {
  for (const accepted of [false, true]) {
    const models = [chapter("one"), chapter("two")];
    let writes = 0;
    assert.equal(await prepareBookFiles({
      projectPath: "/book", getDocuments: () => models, isDirty: dirty,
      confirm: async () => accepted, save: async () => { writes += 1; return false; },
    }), false);
    assert.equal(writes, accepted ? 1 : 0);
    assert.ok(models.every(dirty));
  }
});

test("preparation waits for an earlier save and persists the newer buffer", async () => {
  const model = chapter("one", "newer edit");
  const coordinator = createSaveCoordinator({ isDirty: dirty });
  let complete;
  const earlier = coordinator.save(model, () => new Promise((resolve) => {
    complete = () => { model.saved = "earlier snapshot"; resolve(true); };
  }));
  const preparing = prepareBookFiles({
    projectPath: "/book", getDocuments: () => [model], isDirty: dirty,
    confirm: async () => true,
    save: (item) => coordinator.save(item, async () => { item.saved = item.content; return true; }),
  });
  complete();
  await earlier;
  assert.equal(await preparing, true);
  assert.equal(model.saved, "newer edit");
});

test("project changes, newly dirty buffers and moved manifest paths abort preparation", async () => {
  for (const change of ["project", "new", "move"]) {
    const models = [chapter("one")];
    let current = true;
    assert.equal(await prepareBookFiles({
      projectPath: "/book", getDocuments: () => models, isDirty: dirty,
      confirm: async () => true, isCurrent: () => current,
      save: async (model) => {
        model.saved = model.content;
        if (change === "project") current = false;
        else if (change === "new") models.push(chapter("two"));
        else model.path = "/elsewhere/moved.md";
        return true;
      },
    }), false);
  }
});
