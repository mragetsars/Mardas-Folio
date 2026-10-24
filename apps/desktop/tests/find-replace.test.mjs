import test from "node:test";
import assert from "node:assert/strict";
import { createFindSession, findLiteralMatches, replaceAllLiteral } from "../frontend/js/core/find-replace.mjs";

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

test("a Persian word is found however its letters were typed", () => {
  // ی U+06CC and ک U+06A9 come from a Persian keyboard; ي U+064A and ك U+0643
  // come from an Arabic layout, older Windows keyboards, and most text pasted
  // from the web. They are indistinguishable on screen, so a document mixing
  // them looks uniform and searching it for the other spelling found nothing —
  // which reads as "the text is not there".
  const arabicSpelling = "متن فارسي با كلمه عربي.";
  const persianSpelling = "متن فارسی با کلمه";

  assert.equal(findLiteralMatches(arabicSpelling, "فارسی").length, 1);
  assert.equal(findLiteralMatches(arabicSpelling, "کلمه").length, 1);
  assert.equal(findLiteralMatches(persianSpelling, "فارسي").length, 1);
  assert.equal(findLiteralMatches(persianSpelling, "كلمه").length, 1);

  // The fold is one character for one, so a match still indexes the source and
  // stays a valid selection range over the text as the user stored it.
  const [match] = findLiteralMatches(arabicSpelling, "فارسی");
  assert.equal(arabicSpelling.slice(match.start, match.end), "فارسي");

  assert.deepEqual(replaceAllLiteral(arabicSpelling, "فارسی", "انگلیسی"), {
    text: "متن انگلیسی با كلمه عربي.",
    count: 1,
  });
});

test("letters that only look alike are left alone", () => {
  // آ and ا are different letters in Persian, and Persian and Latin digits mean
  // different things. Folding those would find words nobody searched for.
  assert.equal(findLiteralMatches("آب", "اب").length, 0);
  assert.equal(findLiteralMatches("۱۲۳", "123").length, 0);
  assert.equal(findLiteralMatches("123", "۱۲۳").length, 0);
  // And the fold must not disturb anything outside the Persian block.
  assert.equal(findLiteralMatches("Throughput", "THROUGHPUT").length, 1);
  assert.deepEqual(findLiteralMatches("x🎉y", "🎉"), [{ start: 1, end: 3 }]);
});

test("Replace All reaches matches beyond the bounded navigation list", () => {
  const source = "فارسي ".repeat(10_025);
  assert.equal(findLiteralMatches(source, "فارسی").length, 10_000);
  assert.deepEqual(replaceAllLiteral(source, "فارسی", "$&"), {
    text: "$& ".repeat(10_025), count: 10_025,
  });
});

test("a find session retires offsets from edited buffers and other documents", () => {
  const session = createFindSession();
  const snapshot = { documentId: "a", text: "first cat and cat", query: "cat" };
  assert.deepEqual(session.select(snapshot, 1), { start: 14, end: 17 });
  assert.deepEqual(session.current({ ...snapshot, text: "prefix first cat and cat" }), { start: 21, end: 24 });
  assert.deepEqual(session.current({ ...snapshot, documentId: "b", text: "cat at start" }), { start: 0, end: 3 });
  assert.equal(session.current({ ...snapshot, documentId: "b", text: "unrelated document" }), null);
});

test("replacement advances past its inserted text and wraps predictably", () => {
  const session = createFindSession();
  const before = { documentId: "a", text: "cat cat cat", query: "cat" };
  session.select(before, 1);
  const after = { ...before, text: "cat catapult cat" };
  assert.equal(session.refresh(after, { anchor: 12 }).index, 2);
  assert.deepEqual(session.current(after), { start: 13, end: 16 });
  assert.deepEqual(session.move(after, 1), { start: 0, end: 3 });
  assert.deepEqual(session.move(after, -1), { start: 13, end: 16 });
  session.clear();
  assert.equal(session.refresh(after).index, 0);
});
