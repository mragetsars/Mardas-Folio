import test from "node:test";
import assert from "node:assert/strict";
import { prefixSelectedLines, replaceSelection, wrapSelection } from "../frontend/js/core/editor-commands.mjs";

test("editor commands preserve selection positions", () => {
  assert.deepEqual(wrapSelection("abc", 0, 3, "**"), { text: "**abc**", start: 2, end: 5 });
  assert.deepEqual(replaceSelection("abc", 1, 2, "X"), { text: "aXc", start: 2, end: 2 });
  assert.deepEqual(prefixSelectedLines("a\nb", 0, 3, "## "), { text: "## a\n## b", start: 0, end: 9 });
});
