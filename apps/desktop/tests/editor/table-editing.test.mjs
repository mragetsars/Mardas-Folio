import test from "node:test";
import assert from "node:assert/strict";
import { EditorState } from "@codemirror/state";
import { markdownLanguage } from "@codemirror/lang-markdown";
import {
  tableCellSource,
  tableCellAlignment,
  tableCellChanges,
  tableModel,
  tableStructureChanges,
} from "../../editor-src/table-editing.mjs";

function model(source) {
  let table;
  markdownLanguage.parser.parse(source).iterate({
    enter(node) {
      if (node.name === "Table") table = node.node;
    },
  });
  assert.ok(table);
  return tableModel(source.slice(table.from, table.to), table.from, table);
}

const source =
  "Before\n\n| **Name** | `Value` |\n| :--- | ---: |\n| *first* | a\\|b |\n| last | ` x ` |\n\nAfter\n";
const apply = (source, changes) =>
  EditorState.create({ doc: source }).update({ changes }).newDoc.toString();

test("cell source escapes new pipes without changing existing escaped pipes", () => {
  assert.equal(tableCellSource("a|b"), "a\\|b");
  assert.equal(tableCellSource("a\\|b"), "a\\|b");
  assert.equal(tableCellSource("a\\\\|b"), "a\\\\\\|b");
  assert.equal(tableCellSource("**bold** and `code`\nnext"), "**bold** and `code`<br>next");
});

test("cell model preserves source formats and exact document offsets", () => {
  const table = model(source);
  assert.equal(table.columns, 2);
  assert.equal(table.rows[1].cells[1].raw, "a\\|b");
  for (const row of table.rows)
    for (const cell of row.cells) {
      assert.equal(source.slice(cell.from, cell.to), cell.raw);
    }
  const cell = table.rows[1].cells[1];
  assert.equal(
    apply(source, [{ from: cell.from, to: cell.to, insert: "new" }]),
    source.replace("a\\|b", "new"),
  );
});

test("adding and removing columns preserves inline Markdown and alignment", () => {
  const table = model(source),
    document = EditorState.create({ doc: source }).doc;
  const added = apply(source, tableStructureChanges(table, document, "add-column", 1, 0));
  assert.ok(added.includes("| **Name** |  | `Value` |"));
  assert.ok(added.includes("| :--- | --- | ---: |"));
  assert.ok(added.includes("| *first* |  | a\\|b |"));
  assert.ok(added.startsWith("Before\n\n") && added.endsWith("\n\nAfter\n"));
  const next = model(added);
  assert.equal(next.columns, 3);
  const removed = apply(
    added,
    tableStructureChanges(next, EditorState.create({ doc: added }).doc, "delete-column", 1, 1),
  );
  assert.equal(removed, source);
});

test("row actions preserve blockquote prefixes and cannot remove the header", () => {
  const quoted = "> | Name | Value |\n> | --- | ---: |\n> | **first** | `x` |\n\nAfter\n";
  const table = model(quoted),
    document = EditorState.create({ doc: quoted }).doc;
  const added = apply(quoted, tableStructureChanges(table, document, "add-row", 0, 0));
  assert.ok(added.includes("> | --- | ---: |\n> |  |  |\n> | **first** | `x` |"));
  assert.deepEqual(tableStructureChanges(table, document, "delete-row", 0, 0), []);
  const removed = apply(quoted, tableStructureChanges(table, document, "delete-row", 1, 0));
  assert.equal(removed, "> | Name | Value |\n> | --- | ---: |\n\nAfter\n");
});

test("a one-column table cannot lose its final column", () => {
  const one = "| A |\n| --- |\n| B |";
  assert.deepEqual(
    tableStructureChanges(model(one), EditorState.create({ doc: one }).doc, "delete-column", 1, 0),
    [],
  );
});

test("cell and bulk alignment preserve column defaults, content and ragged rows", () => {
  const source = "| A | B |\n| --- | ---: |\n| One | Two |\n| Short |\n";
  const first = model(source);
  const updated = apply(
    source,
    tableCellChanges(
      first,
      [
        [0, 1],
        [1, 1],
        [2, 1],
      ],
      "auto",
    ),
  );
  const table = model(updated);
  assert.equal(table.delimiter.cells[1].raw, "---:");
  assert.equal(tableCellAlignment(table, 1, 0).alignment, "auto");
  assert.equal(tableCellAlignment(table, 1, 1).alignment, "auto");
  assert.match(updated, /<!--folio-align:auto--> Two/);
  assert.match(updated, /Short \| <!--folio-align:auto-->/);
  const changed = apply(updated, tableCellChanges(table, [[1, 1]], "right", "**New**"));
  assert.match(changed, /<!--folio-align:right--> \*\*New\*\*/);
  assert.match(changed, /<!--folio-align:auto--> B/);
});
