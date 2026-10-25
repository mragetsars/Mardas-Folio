import test from "node:test";
import assert from "node:assert/strict";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { EditorSelection, EditorState } from "@codemirror/state";
import { markdownFormattingState } from "../editor-src/formatting-state.mjs";

function inspect(doc, text, offset = 0) {
  const from = doc.indexOf(text) + offset;
  assert.ok(from >= 0);
  const state = EditorState.create({ doc, selection: { anchor: from },
    extensions: [markdown({ base: markdownLanguage }), EditorState.allowMultipleSelections.of(true)] });
  const before = state.doc.toString();
  const result = markdownFormattingState(state);
  assert.equal(state.doc.toString(), before);
  assert.equal(state.selection.main.head, from);
  return result;
}

test("formatting follows parsed inline context rather than marker-like text", () => {
  const doc = "Plain **bold _and italic_** then ~~strike~~ and `**literal**`.";
  assert.equal(inspect(doc, "bold", 2).bold, true);
  const nested = inspect(doc, "italic", 2);
  assert.equal(nested.bold, true);
  assert.equal(nested.italic, true);
  assert.equal(inspect(doc, "strike", 2).strike, true);
  const code = inspect(doc, "literal", 2);
  assert.equal(code.code, true);
  assert.equal(code.bold, false);
  assert.equal(inspect(doc, "Plain", 2).bold, false);
});

test("mixed formatting selections do not claim a shared active format", () => {
  const doc = "**bold** plain";
  const state = EditorState.create({ doc, selection: { anchor: 2, head: doc.length },
    extensions: [markdown({ base: markdownLanguage }), EditorState.allowMultipleSelections.of(true)] });
  assert.equal(markdownFormattingState(state).bold, false);
  const multiple = state.update({ selection: EditorSelection.create([
    EditorSelection.cursor(3), EditorSelection.cursor(11),
  ]) }).state;
  assert.equal(markdownFormattingState(multiple).bold, false);
});

test("heading and list controls describe the current Markdown block", () => {
  const doc = "## Title\n\n- bullet\n- [x] task\n\n1. numbered\n\n> quoted\n\n```md\n# literal heading\n```";
  const heading = inspect(doc, "Title", 2);
  assert.equal(heading.heading, 2);
  assert.equal(heading["heading-2"], true);
  assert.equal(heading["heading-1"], false);
  assert.equal(inspect(doc, "bullet", 2)["bullet-list"], true);
  const task = inspect(doc, "task", 2);
  assert.equal(task["task-list"], true);
  assert.equal(task["bullet-list"], false);
  assert.equal(inspect(doc, "numbered", 2)["ordered-list"], true);
  assert.equal(inspect(doc, "quoted", 2).quote, true);
  const fenced = inspect(doc, "literal heading", 2);
  assert.equal(fenced.heading, 0);
  assert.equal(fenced["code-block"], true);
});
