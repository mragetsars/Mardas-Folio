import test from "node:test";
import assert from "node:assert/strict";
import {
  extractCitationKeys,
  extractOutline,
  parseFrontMatter,
  textMetrics,
  upsertFrontMatter,
} from "../frontend/js/core/markdown-analysis.mjs";

test("front matter is parsed and updated without dropping unknown keys", () => {
  const source = "---\ntitle: Old\ncustom: keep\ntoc: false\n---\n\n# Body\n";
  const updated = upsertFrontMatter(source, "title", "New");
  assert.match(updated, /title: "New"/);
  assert.match(updated, /custom: keep/);
  assert.equal(parseFrontMatter(updated).fields.title, "New");
});

test("outline ignores fenced headings and returns source lines", () => {
  const outline = extractOutline("# One\n\n```md\n## Fake\n```\n\n### Three\n");
  assert.deepEqual(outline, [
    { level: 1, title: "One", line: 1 },
    { level: 3, title: "Three", line: 7 },
  ]);
});

test("citation and cursor metrics are deterministic", () => {
  assert.deepEqual(extractCitationKeys("See [@doe2024; @smith]. mail@example.com"), ["doe2024", "smith"]);
  assert.deepEqual(textMetrics("one two\nthree", 10), { line: 2, column: 3, words: 3, characters: 13 });
});
