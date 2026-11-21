import test from "node:test";
import assert from "node:assert/strict";
import {
  createCatalogue,
  describe,
  draftFor,
  moveVisible,
  packNotes,
  resumeData,
  searchKey,
  upsert,
} from "../../frontend/js/features/library/catalog.mjs";
import { updateBasics } from "../../frontend/js/features/library/resume.mjs";
import { readRecoveries, saveRecovery } from "../../frontend/js/features/documents/recovery.mjs";
import { createDocument } from "../../frontend/js/core/documents.mjs";
import { createTranslator } from "../../frontend/js/core/i18n.mjs";
import { templateContent } from "../../frontend/js/core/templates.mjs";

test("all single-file types have a concrete editor and a bilingual title", () => {
  for (const locale of ["fa", "en"]) {
    const { t } = createTranslator(locale);
    for (const [type, kind] of Object.entries({
      document: "markdown",
      article: "markdown",
      note: "text",
      resume: "json",
    })) {
      const seed = draftFor(type, t);
      assert.equal(seed.kind, kind);
      assert.notEqual(seed.title.slice(0, 5), "shelf");
      assert.equal(describe({ ...seed, path: null }).type, type);
    }
  }
});
test("academic manuscripts travel with type metadata and independent excerpts", () => {
  for (const locale of ["fa", "en"]) {
    const model = {
      kind: "markdown",
      path: "/renamed.md",
      content: templateContent("academic", locale)
        .replace('author: ""', 'author: "Amini"')
        .replace('journal: ""', 'journal: "Journal"'),
    };
    const summary = describe(model);
    assert.equal(summary.type, "article");
    assert.equal(summary.author, "Amini");
    assert.equal(summary.detail, "Journal");
  }
  assert.deepEqual(describe({ kind: "text", path: "/n.txt", content: "یک فکر\nخط دوم" }), {
    type: "note",
    title: "یک فکر",
    detail: "خط دوم",
    author: "",
  });
});
test("unrelated JSON is ignored and resume form preserves unedited keys", () => {
  assert.equal(resumeData('{"basics":{"version":42}}'), null);
  assert.equal(describe({ path: "/other.json", kind: "json", content: '{"other":true}' }), null);
  const source = JSON.stringify({
    basics: { name: "Sara", custom: 42 },
    work: [{ name: "Studio" }],
  });
  assert.equal(updateBasics(source, { name: "Sara" }), source);
  assert.equal(updateBasics("{", {}), null);
  assert.deepEqual(JSON.parse(updateBasics(source, { name: "سارا", unknown: "x" })), {
    basics: { name: "سارا", custom: 42 },
    work: [{ name: "Studio" }],
  });
});
test("Save As can index both files while reopening a Windows path keeps its ID and cover", () => {
  const row = {
    id: "original",
    path: "D:/Work/One.txt",
    type: "note",
    title: "One",
    appearance: { material: "cotton" },
  };
  const copy = upsert([row], { ...row, path: "D:/Work/Two.txt" });
  assert.equal(copy.length, 2);
  assert.notEqual(copy[1].id, copy[0].id);
  const updated = upsert(copy, {
    ...row,
    id: "other",
    path: "d:\\work\\ONE.txt",
    title: "Updated",
    appearance: {},
  });
  assert.equal(updated[0].id, "original");
  assert.equal(updated[0].appearance.material, "cotton");
});
test("filtered reordering preserves hidden positions; consecutive notes share one slot", () => {
  const items = ["note", "book", "note", "note"].map((type, id) => ({ id: String(id), type }));
  assert.deepEqual(
    moveVisible(items, "3", "0", ["0", "2", "3"]).map((i) => i.id),
    ["3", "1", "0", "2"],
  );
  assert.deepEqual(
    packNotes(items).map((group) => group.length),
    [1, 1, 2],
  );
  assert.equal(searchKey("كِتاب‌ ١۲۳"), searchKey("کتاب 123"));
});
test("competing sessions rebase semantic changes on the newest snapshot", async () => {
  let remote = { revision: 0, items: [] };
  const read = async () => structuredClone(remote);
  const write = async (rev, items) => {
    if (rev !== remote.revision)
      throw Object.assign(new Error(), { code: "MARDAS-LIBRARY-CONFLICT" });
    remote = { revision: rev + 1, items };
    return { revision: remote.revision };
  };
  const a = createCatalogue({ read, write, changed() {} }),
    b = createCatalogue({ read, write, changed() {} });
  await Promise.all([a.refresh(), b.refresh()]);
  await a.change((items) => [...items, { id: "one" }]);
  await b.change((items) => [...items, { id: "two" }]);
  assert.deepEqual(b.items, [{ id: "one" }, { id: "two" }]);
});
test("draft recovery retains the source kind and valid appearance in older storage", () => {
  const map = new Map(),
    storage = { getItem: (k) => map.get(k), setItem: (k, v) => map.set(k, v) };
  for (const type of ["note", "resume", "document", "article"]) {
    const seed = draftFor(type, (s) => s),
      model = Object.assign(createDocument(seed), seed);
    model.libraryAppearance = { material: "cotton", picture: "javascript:bad" };
    assert.equal(saveRecovery(model, storage).ok, true);
    const entry = readRecoveries(storage).find((e) => e.libraryType === type);
    assert.equal(entry.kind || "markdown", seed.kind);
    assert.deepEqual(entry.libraryAppearance, { material: "cotton" });
  }
});
