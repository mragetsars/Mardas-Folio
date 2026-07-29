import test from "node:test";
import assert from "node:assert/strict";
import { findLiteralMatches, replaceAllLiteral } from "../frontend/js/core/find-replace.mjs";

test("find and replace treats regular-expression characters literally", () => {
  assert.deepEqual(findLiteralMatches("a+b A+B", "a+b"), [{ start: 0, end: 3 }, { start: 4, end: 7 }]);
  assert.deepEqual(replaceAllLiteral("a+b A+B", "a+b", "x"), { text: "x x", count: 2 });
});
