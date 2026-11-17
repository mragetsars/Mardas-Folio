import test from "node:test";
import assert from "node:assert/strict";
import { sourceDocumentDirection } from "../../editor-src/source-direction.mjs";

test("source gutter direction follows document metadata, not interface language", () => {
  assert.equal(sourceDocumentDirection('---\ndir: rtl\n---\n# English'), "rtl");
  assert.equal(sourceDocumentDirection('---\ndirection: "ltr"\nlang: fa-IR\n---\nمتن فارسی'), "ltr");
  assert.equal(sourceDocumentDirection('---\nlang: fa-IR\n---\n# English'), "rtl");
  assert.equal(sourceDocumentDirection('---\nlanguage: en-US\n---\nمتن فارسی'), "ltr");
  assert.equal(sourceDocumentDirection('---\ndocument_direction: rtl\n---\nEnglish'), "rtl");
  assert.equal(sourceDocumentDirection('---\ndir: right_to_left\n---\nEnglish'), "rtl");
  assert.equal(sourceDocumentDirection('---\nlang: fa_IR\n---\nEnglish'), "rtl");
});

test("source gutter uses dominant prose while code and URL spelling cannot pull it away", () => {
  assert.equal(sourceDocumentDirection('# AdaptiveCruiseTest\n\n' + 'این متن فارسی برای بررسی جهت سند است. '.repeat(6)), "rtl");
  assert.equal(sourceDocumentDirection('متن فارسی\n```javascript\n' + 'const veryLongIdentifier = 10;'.repeat(100) + '\n```'), "rtl");
  assert.equal(sourceDocumentDirection('متن فارسی `AdaptiveCruiseTestController` https://example.com/very/long/english/path'), "rtl");
  assert.equal(sourceDocumentDirection('English\n\n> ```python\n> ' + 'متن فارسی '.repeat(200) + '\n> ```'), "ltr");
  assert.equal(sourceDocumentDirection('English\n\n    ' + 'متن فارسی '.repeat(200)), "ltr");
  assert.equal(sourceDocumentDirection('123 | --- |'), "ltr");
});

test("direction sampling is bounded and incomplete metadata stays ordinary source", () => {
  assert.equal(sourceDocumentDirection('English '.repeat(5000) + 'متن فارسی '.repeat(10000)), "ltr");
  assert.equal(sourceDocumentDirection('---\ndir: rtl\nEnglish text without a closing fence'), "ltr");
  assert.equal(sourceDocumentDirection(null), "ltr");
});
