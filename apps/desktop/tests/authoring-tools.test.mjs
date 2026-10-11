import test from "node:test";
import assert from "node:assert/strict";
import { CompletionContext } from "@codemirror/autocomplete";
import { history, redo, undo } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { Compartment, EditorSelection, EditorState } from "@codemirror/state";

import {
  readOnlyDocumentGuard,
  selectionToolbarEligible,
  selectionToolbarExtension,
  slashBlockOptions,
  slashBlockTransaction,
  slashCompletionSource,
  slashRequest,
} from "../editor-src/authoring-tools.mjs";
import { frontmatter } from "../editor-src/markdown-frontmatter.mjs";
import { mathAndFootnotes } from "../editor-src/markdown-extras.mjs";
import { exitEmptyBlock, runMarkdownCommand } from "../editor-src/markdown-commands.mjs";

function stateAt(text, position = text.length, extensions = []) {
  return EditorState.create({
    doc: text,
    selection: EditorSelection.cursor(position),
    extensions: [markdown({ base: markdownLanguage, extensions: [frontmatter, mathAndFootnotes] }), ...extensions],
  });
}

test("slash insertion is available only at a prose line's start", () => {
  for (const text of ["/", "\n/table", "  /table", "/جدول"]) {
    const state = stateAt(text);
    assert.ok(slashRequest(state, state.selection.main.head), text);
  }
  for (const text of [
    "https://", "text /", "1/", "- /", "> /", "    /", "/table existing text",
    "```\n/", "```js\n/table\n```", "    code\n    /", "---\ntitle: title\n/table\n---", "$$\n/table\n$$",
  ]) {
    const position = text.includes("/table\n") ? text.indexOf("/table") + 6 : text.length;
    const state = stateAt(text, position);
    assert.equal(slashRequest(state, position), null, text);
  }
  assert.equal(slashRequest(stateAt("/", 1, [EditorState.readOnly.of(true)]), 1), null);
});

test("block search works in either language while option labels follow the locale", () => {
  assert.equal(slashBlockOptions("table", "fa")[0].label, "جدول");
  assert.equal(slashBlockOptions("جدول", "en")[0].label, "Table");
  assert.equal(slashBlockOptions("رياضی", "fa")[0].blockId, "math-block");
  assert.equal(slashBlockOptions("نقل‌قول", "fa")[0].blockId, "quote");
  assert.equal(slashBlockOptions("does-not-exist", "en").length, 0);
  assert.deepEqual(slashBlockOptions("h2").map((option) => option.blockId), ["heading-2"]);
  const state = stateAt("/table");
  const result = slashCompletionSource(() => "fa")(new CompletionContext(state, state.doc.length, false));
  assert.equal(result.from, 1);
  assert.equal(result.filter, false);
  assert.equal(result.options[0].label, "جدول");
});

test("every slash block replaces the trigger and lands in its writable content", () => {
  for (const option of slashBlockOptions()) {
    const state = stateAt("/");
    const transaction = slashBlockTransaction(state, option.blockId);
    assert.ok(transaction, option.blockId);
    const next = state.update(transaction).state;
    assert.equal(next.doc.toString().includes("/"), false, option.blockId);
    assert.ok(next.selection.main.to <= next.doc.length, option.blockId);
  }
  const tableState = stateAt("/table");
  const table = tableState.update(slashBlockTransaction(tableState, "table", "fa")).state;
  assert.equal(table.sliceDoc(table.selection.main.from, table.selection.main.to), "ستون");
  assert.equal(slashBlockTransaction(stateAt("text /table"), "table"), null);
});

test("tables and dividers separate from surrounding prose so they render as blocks", () => {
  for (const id of ["table", "rule", "math-block", "callout"]) {
    const state = stateAt("Paragraph\n/\nNext paragraph", 11);
    const next = state.update(slashBlockTransaction(state, id)).state;
    assert.ok(next.doc.toString().startsWith("Paragraph\n\n"), id);
    assert.ok(next.doc.toString().includes("\n\nNext paragraph"), id);
  }
});

test("a slash insertion is a single undo step and redo restores the block", () => {
  let state = stateAt("/table", 6, [history()]);
  state = state.update(slashBlockTransaction(state, "table")).state;
  const inserted = state.doc.toString();
  const target = { get state() { return state; }, dispatch(transaction) { state = transaction.state; } };
  assert.equal(undo(target), true);
  assert.equal(state.doc.toString(), "/table");
  assert.equal(redo(target), true);
  assert.equal(state.doc.toString(), inserted);
  assert.ok(state.selection.main.head <= state.doc.length);
});

test("selection formatting appears only for an editable prose selection", () => {
  const select = (text, from, to, extensions = []) => stateAt(text, 0, extensions)
    .update({ selection: EditorSelection.single(from, to) }).state;
  assert.equal(selectionToolbarEligible(select("hello", 0, 5)), true);
  assert.equal(selectionToolbarEligible(stateAt("hello")), false);
  assert.equal(selectionToolbarEligible(select("hello", 0, 5, [EditorState.readOnly.of(true)])), false);
  assert.equal(selectionToolbarEligible(select("```\ncode\n```", 4, 8)), false);
  assert.equal(selectionToolbarEligible(select("before\n```\ncode\n```\nafter", 0, 25)), false);
  assert.equal(selectionToolbarEligible(select("---\ntitle: title\n---", 4, 9)), false);
  assert.deepEqual(selectionToolbarExtension("en", false), []);
});

test("read-only protects custom commands, replacements and history without losing history", () => {
  const access = new Compartment();
  let state = stateAt("word", 4, [history(), readOnlyDocumentGuard, access.of(EditorState.readOnly.of(false))]);
  const target = {
    get state() { return state; },
    dispatch(transaction) { state = transaction.state || state.update(transaction).state; },
    focus() {},
  };
  assert.equal(runMarkdownCommand(target, "bold"), true);
  const written = state.doc.toString();
  state = state.update({ effects: access.reconfigure(EditorState.readOnly.of(true)) }).state;
  assert.equal(runMarkdownCommand(target, "italic"), false);
  assert.equal(exitEmptyBlock(target), false);
  assert.equal(undo(target), false);
  state = state.update({ changes: { from: 0, to: state.doc.length, insert: "changed" } }).state;
  assert.equal(state.doc.toString(), written);
  state = state.update({ effects: access.reconfigure(EditorState.readOnly.of(false)) }).state;
  assert.equal(undo(target), true);
  assert.equal(state.doc.toString(), "word");
});
