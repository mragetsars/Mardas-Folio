import test from "node:test";
import assert from "node:assert/strict";
import {
  bodyStartOffset,
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

test("replacing a multiline value removes its complete YAML entry", () => {
  const source = '---\ntitle: >-\n  Old title\n  on two lines\ncustom:\n  nested: keep\n# Keep this comment\n---\n\n# Body\n';
  assert.equal(parseFrontMatter(source).fields.title, "Old title on two lines");
  const updated = upsertFrontMatter(source, "title", "New title");
  assert.equal(updated, '---\ntitle: "New title"\ncustom:\n  nested: keep\n# Keep this comment\n---\n\n# Body\n');
});

test("replacing bibliography removes block list items and preserves CRLF", () => {
  const source = '---\r\nbibliography:\r\n- old.bib\r\n- another.bib\r\nauthor: "Doe, Jane"\r\n---\r\n\r\nBody\r\n';
  const updated = upsertFrontMatter(source, "bibliography", ["new.bib"]);
  assert.equal(updated, '---\r\nbibliography: ["new.bib"]\r\nauthor: "Doe, Jane"\r\n---\r\n\r\nBody\r\n');
  assert.deepEqual(parseFrontMatter(source).fields.bibliography, ["old.bib", "another.bib"]);
});

test("quoted keys and scalars are read without exposing escapes or comments", () => {
  const source = `---\n"title": "A \\"quoted\\" title" # note\nauthor: 'O''Brien'\nsubtitle: Plain text # comment\n---\nBody`;
  const parsed = parseFrontMatter(source);
  assert.equal(parsed.fields.title, 'A "quoted" title');
  assert.equal(parsed.fields.author, "O'Brien");
  assert.equal(parsed.fields.subtitle, "Plain text");
  assert.equal(parseFrontMatter(upsertFrontMatter(source, "title", "Next")).fields.title, "Next");
});

test("unsupported complex form values stay unavailable instead of becoming empty strings", () => {
  const parsed = parseFrontMatter('---\ntitle: |+\n  First\n\nauthor:\n  name: Jane\n---\nBody');
  assert.equal(parsed.valid, false);
  assert.equal(Object.hasOwn(parsed.fields, "title"), false);
  assert.equal(Object.hasOwn(parsed.fields, "author"), false);
});

test("flow lists preserve quoted commas and complex YAML stays in source editing", () => {
  const parsed = parseFrontMatter(`---\nauthor: ["Doe, Jane", 'O''Brien']\nbibliography: [main.bib, extra.bib] # sources\npublisher: {name: Press}\nsubtitle: &shared Text\ncustom: "\\e"\n---\nBody`);
  assert.deepEqual(parsed.fields.author, ["Doe, Jane", "O'Brien"]);
  assert.deepEqual(parsed.fields.bibliography, ["main.bib", "extra.bib"]);
  assert.equal(parsed.valid, false);
  for (const key of ["publisher", "subtitle", "custom"]) assert.equal(Object.hasOwn(parsed.fields, key), false);
  assert.equal(parseFrontMatter('---\nauthor:\n- {name: Jane}\n---\nBody').fields.author, undefined);
});

test("outline ignores fenced headings and returns source lines", () => {
  const outline = extractOutline("# One\n\n```md\n## Fake\n```\n\n### Three\n");
  assert.deepEqual(outline, [
    { level: 1, title: "One", line: 1 },
    { level: 3, title: "Three", line: 7 },
  ]);
});

test("outline requires a matching fence character and sufficient closing length", () => {
  const outline = extractOutline([
    "# Before",
    "````markdown",
    "## Hidden one",
    "```",
    "## Hidden after short fence",
    "~~~~",
    "### Hidden after different fence",
    "````   ",
    "## After",
  ].join("\n"));
  assert.deepEqual(outline, [
    { level: 1, title: "Before", line: 1 },
    { level: 2, title: "After", line: 9 },
  ]);
});

test("outline accepts longer closers and rejects non-closing trailing content", () => {
  const outline = extractOutline([
    "   ~~~ language",
    "## Hidden",
    "   ~~~ not-a-closer",
    "### Still hidden",
    "  ~~~~\t",
    "# Visible",
    "    ```",
    "## Visible after indented code marker",
  ].join("\n"));
  assert.deepEqual(outline, [
    { level: 1, title: "Visible", line: 6 },
    { level: 2, title: "Visible after indented code marker", line: 8 },
  ]);
});

test("citation and cursor metrics are deterministic", () => {
  assert.deepEqual(extractCitationKeys("See [@doe2024; @smith]. mail@example.com"), ["doe2024", "smith"]);
  assert.deepEqual(textMetrics("one two\nthree", 10), { line: 2, column: 3, words: 3, characters: 13 });
});

test("the body of a document starts past its front matter", () => {
  const document = '---\ntitle: "Report"\nlang: en\n---\n\n# Executive Summary\n';
  assert.equal(document.slice(bodyStartOffset(document)), "# Executive Summary\n");
});

test("a document with no front matter starts at its first character", () => {
  assert.equal(bodyStartOffset("# Title\n\nBody.\n"), 0);
  assert.equal(bodyStartOffset(""), 0);
});

test("CRLF endings land in the same place as LF ones", () => {
  const crlf = '---\r\ntitle: "Report"\r\n---\r\n\r\n# Heading\r\n';
  assert.equal(crlf.slice(bodyStartOffset(crlf)), "# Heading\r\n");
});

test("an unterminated front matter block is not front matter", () => {
  // No closing delimiter: the whole file is body, and the caret must not be
  // sent past the end of it.
  const broken = '---\ntitle: "Report"\n\n# Heading\n';
  assert.equal(bodyStartOffset(broken), 0);
});

test("front matter with nothing after it puts the caret at the end", () => {
  const only = '---\ntitle: "Report"\n---\n';
  assert.equal(bodyStartOffset(only), only.length);
});
