import test from "node:test";
import assert from "node:assert/strict";
import { EditorState } from "@codemirror/state";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { sourceBlockDirections } from "../editor-src/live-preview.mjs";

const stateFor = (doc) => EditorState.create({
  doc,
  extensions: [markdown({ base: markdownLanguage })],
});
const directionsFor = (state, ranges = [{ from: 0, to: state.doc.length }]) =>
  sourceBlockDirections(state, ranges);
const directionAt = (state, directions, number) => directions.get(state.doc.line(number).from);

test("source fences and code stay LTR, including blank and Persian-comment lines", () => {
  const state = stateFor("نثر فارسی\n\n```javascript\n// توضیح فارسی\nconst count = 1;\n\n```\n\nEnglish prose.");
  const directions = directionsFor(state);
  assert.equal(directionAt(state, directions, 1), undefined, "prose still resolves per line");
  assert.equal(directionAt(state, directions, 9), undefined);
  for (let number = 3; number <= 7; number += 1) {
    assert.equal(directionAt(state, directions, number), "ltr", `code line ${number}`);
  }
  assert.equal(state.doc.toString(), "نثر فارسی\n\n```javascript\n// توضیح فارسی\nconst count = 1;\n\n```\n\nEnglish prose.");
});

test("table separator and numeric rows share the header's content direction", () => {
  const state = stateFor("| Name | Count |\n| --- | ---: |\n| 1 | 2 |\n\n| نام | تعداد |\n| --- | ---: |\n| ۱ | ۲ |\n\nنثر فارسی");
  const directions = directionsFor(state);
  for (const number of [1, 2, 3]) assert.equal(directionAt(state, directions, number), "ltr");
  for (const number of [5, 6, 7]) assert.equal(directionAt(state, directions, number), "rtl");
  assert.equal(directionAt(state, directions, 9), undefined);
});

test("changing a table's first strong content recalculates its neutral rows", () => {
  let state = stateFor("| نام | 2 |\n| --- | --- |\n| 1 | 2 |");
  assert.equal(directionAt(state, directionsFor(state), 2), "rtl");
  state = state.update({ changes: { from: 2, to: 5, insert: "Name" } }).state;
  assert.equal(directionAt(state, directionsFor(state), 2), "ltr");
});

test("a partial viewport decorates only its visible portion of a large code block", () => {
  const state = stateFor("```\n" + "x\n".repeat(2000) + "```\n\nAfter.");
  const first = state.doc.line(700);
  const last = state.doc.line(702);
  const directions = directionsFor(state, [{ from: first.from + 1, to: last.to }]);
  assert.deepEqual([...directions.keys()], [first.from, state.doc.line(701).from, last.from]);
  assert.ok([...directions.values()].every((direction) => direction === "ltr"));
});

test("literal inline backticks and a standalone rule acquire no block direction", () => {
  const state = stateFor("Persian inline `نام` and punctuation.\n\n---\n\nنثر فارسی.");
  assert.equal(directionsFor(state).size, 0);
});
