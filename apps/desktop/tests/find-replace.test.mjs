import test from "node:test";
import assert from "node:assert/strict";
import { findLiteralMatches, replaceAllLiteral } from "../frontend/js/core/find-replace.mjs";

test("find and replace treats regular-expression characters literally", () => {
  assert.deepEqual(findLiteralMatches("a+b A+B", "a+b"), [{ start: 0, end: 3 }, { start: 4, end: 7 }]);
  assert.deepEqual(replaceAllLiteral("a+b A+B", "a+b", "x"), { text: "x x", count: 2 });
});

test("Unicode case-insensitive matches keep offsets in the original string", () => {
  assert.deepEqual(findLiteralMatches("AİB b", "b"), [
    { start: 2, end: 3 },
    { start: 4, end: 5 },
  ]);
  assert.deepEqual(replaceAllLiteral("AİB b", "b", "!"), {
    text: "Aİ! !",
    count: 2,
  });
});

test("literal matching supports mixed Persian and Unicode simple case folds", () => {
  assert.deepEqual(findLiteralMatches("گزارش K و k", "k"), [
    { start: 6, end: 7 },
    { start: 10, end: 11 },
  ]);
  assert.deepEqual(findLiteralMatches("متن فارسی متن", "متن"), [
    { start: 0, end: 3 },
    { start: 10, end: 13 },
  ]);
  assert.equal(findLiteralMatches("aaaa", "a", { limit: 2 }).length, 2);
});
