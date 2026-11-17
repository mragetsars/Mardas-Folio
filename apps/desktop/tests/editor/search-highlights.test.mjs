import test from "node:test";
import assert from "node:assert/strict";
import { EditorState } from "@codemirror/state";
import { searchHighlights, searchMatchesEffect } from "../../editor-src/search-highlights.mjs";
import { findLiteralMatches } from "../../frontend/js/core/find-replace.mjs";

const ranges = state => {
  const found = [];
  state.field(searchHighlights).between(0, state.doc.length, (from, to, mark) => found.push({ from, to, className: mark.spec.class }));
  return found;
};

test("search paints the same folded Persian UTF-16 ranges it navigates", () => {
  const doc = "🙂 کتاب و كتاب، کتاب";
  let state = EditorState.create({ doc, extensions: [searchHighlights] });
  const matches = findLiteralMatches(doc, "کتاب");
  state = state.update({ effects: searchMatchesEffect.of({ matches, index: 1 }) }).state;
  assert.deepEqual(ranges(state).map(r => doc.slice(r.from, r.to)), ["کتاب", "كتاب", "کتاب"]);
  assert.equal(ranges(state).filter(r => r.className.endsWith("-current")).length, 1);
  assert.equal(ranges(state)[1].className, "cm-findMatch cm-findMatch-current");
});

test("highlight positions map with edits and clear without changing document or selection", () => {
  let state = EditorState.create({ doc: "alpha beta alpha", selection: { anchor: 6 }, extensions: [searchHighlights] });
  state = state.update({ effects: searchMatchesEffect.of({ matches: findLiteralMatches(state.doc.toString(), "alpha"), index: 0 }) }).state;
  state = state.update({ changes: { from: 0, insert: "🙂 " } }).state;
  assert.deepEqual(ranges(state).map(r => state.sliceDoc(r.from, r.to)), ["alpha", "alpha"]);
  const before = state.doc.toString(), caret = state.selection.main.head;
  state = state.update({ effects: searchMatchesEffect.of({ matches: [] }) }).state;
  assert.deepEqual(ranges(state), []);
  assert.equal(state.doc.toString(), before);
  assert.equal(state.selection.main.head, caret);
});
