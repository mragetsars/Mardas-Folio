import test from "node:test";
import assert from "node:assert/strict";
import { buildOutlineTree, OutlineNavigatorModel } from "../frontend/js/core/outline-navigator.mjs";

const sample = [
  { level: 1, title: "Book", line: 1 },
  { level: 2, title: "First chapter", line: 5 },
  { level: 3, title: "Detail", line: 8 },
  { level: 2, title: "Second chapter", line: 20 },
  { level: 1, title: "Appendix", line: 40 },
];

test("outline hierarchy follows document structure, including skipped levels", () => {
  const tree = buildOutlineTree([{ level: 2, title: "Section", line: 2 },
    { level: 6, title: "Detail", line: 4 }, { level: 2, title: "Next", line: 8 }]);
  assert.equal(tree.roots.length, 2);
  assert.equal(tree.roots[0].children[0].depth, 1);
  assert.equal(tree.roots[0].children[0].parentId, tree.roots[0].id);
});

test("outline ignores malformed source locations and levels", () => {
  const tree = buildOutlineTree([{ level: 7, title: "Invalid", line: 1 },
    { level: 2, title: "Invalid", line: 0 }, { level: 1, title: "Valid", line: 2 }]);
  assert.deepEqual(tree.flat.map((node) => node.title), ["Valid"]);
});

test("duplicate heading titles have separate stable identities", () => {
  const items = [{ level: 1, title: "Repeat", line: 1 }, { level: 1, title: "Repeat", line: 8 }];
  const first = buildOutlineTree(items).flat;
  const moved = buildOutlineTree(items.map((item) => ({ ...item, line: item.line + 3 }))).flat;
  assert.notEqual(first[0].id, first[1].id);
  assert.deepEqual(first.map((node) => node.id), moved.map((node) => node.id));
});

test("a transient malformed UTF-16 heading cannot break outline updates", () => {
  const tree = buildOutlineTree([{ level: 1, title: "Draft \ud800", line: 1 }]);
  assert.equal(tree.flat.length, 1);
  assert.equal(tree.flat[0].title, "Draft \ud800");
});

test("fold state survives paragraph insertion and body-only updates skip rebuild", () => {
  const model = new OutlineNavigatorModel();
  assert.equal(model.setDocument("book", sample), true);
  model.toggle(model.current.flat[1].id, false);
  assert.equal(model.setDocument("book", sample), false);
  model.setDocument("book", sample.map((item) => ({ ...item, line: item.line + 2 })));
  assert.deepEqual(model.visibleNodes().map((node) => node.title), ["Book", "First chapter", "Second chapter", "Appendix"]);
});

test("fold state and active position belong to each document", () => {
  const model = new OutlineNavigatorModel();
  model.setDocument("a", sample);
  model.collapseAll();
  model.setActiveLine(25);
  model.setDocument("b", sample);
  assert.equal(model.visibleNodes().length, 5);
  assert.equal(model.activeNode().title, "Book");
  model.setDocument("a", sample);
  assert.deepEqual(model.visibleNodes().map((node) => node.title), ["Book", "Appendix"]);
  assert.equal(model.activeNode().title, "Second chapter");
});

test("search reveals matching descendants and their context without changing folds", () => {
  const model = new OutlineNavigatorModel();
  model.setDocument("book", sample);
  model.collapseAll();
  model.setQuery("detail");
  assert.deepEqual(model.visibleNodes().map((node) => node.title), ["Book", "First chapter", "Detail"]);
  assert.equal(model.visibleNodes().at(-1).match, true);
  model.setQuery("");
  assert.deepEqual(model.visibleNodes().map((node) => node.title), ["Book", "Appendix"]);
});

test("Persian outline filtering accepts Arabic letter variants and spaced joiners", () => {
  const model = new OutlineNavigatorModel();
  model.setDocument("book", [{ level: 1, title: "پیش‌نمایش کتاب", line: 1 }]);
  model.setQuery("پيش نمايش كتاب");
  assert.equal(model.visibleNodes().length, 1);
  model.setQuery("missing");
  assert.equal(model.visibleNodes().length, 0);
});

test("current heading is the preceding source heading, with collapsed ancestor fallback", () => {
  const model = new OutlineNavigatorModel();
  model.setDocument("book", sample.map((node) => ({ ...node, line: node.line + 4 })));
  model.setActiveLine(1);
  assert.equal(model.activeNode(), null);
  model.setActiveLine(15);
  assert.equal(model.activeNode().title, "Detail");
  model.toggle(model.current.flat[1].id, false);
  assert.equal(model.visibleActiveNode().title, "First chapter");
  model.collapseAll();
  assert.equal(model.visibleActiveNode().title, "Book");
});

test("deleted heading folds are pruned and retained document state is bounded", () => {
  const model = new OutlineNavigatorModel({ documentLimit: 2 });
  model.setDocument("a", sample);
  model.collapseAll();
  model.setDocument("a", [sample.at(-1)]);
  assert.equal(model.current.collapsed.size, 0);
  model.setDocument("b", sample);
  model.setDocument("c", sample);
  assert.deepEqual([...model.documents.keys()], ["b", "c"]);
  model.forgetDocument("c");
  assert.equal(model.documents.has("c"), false);
});
