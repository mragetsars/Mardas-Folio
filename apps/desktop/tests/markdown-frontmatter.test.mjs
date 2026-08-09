import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { parser } from "@lezer/markdown";

import { frontmatter } from "../editor-src/markdown-frontmatter.mjs";
import {
  extractOutline,
  frontMatterRange,
  parseFrontMatter,
} from "../frontend/js/core/markdown-analysis.mjs";

const fixture = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/frontmatter_cases.json", import.meta.url), "utf8"),
);

const markdown = parser.configure([frontmatter]);

function parsesFrontmatter(text) {
  let found = false;
  markdown.parse(text).iterate({
    enter: (node) => {
      if (node.name === "Frontmatter") found = true;
    },
  });
  return found;
}

test("the editor parser recognises front matter exactly like the publishing engine", () => {
  for (const { name, text, frontmatter: expected } of fixture.cases) {
    assert.equal(parsesFrontmatter(text), expected, `editor parser disagrees on "${name}"`);
  }
});

test("the outline helper recognises front matter exactly like the publishing engine", () => {
  for (const { name, text, frontmatter: expected } of fixture.cases) {
    assert.equal(frontMatterRange(text) !== null, expected, `frontMatterRange disagrees on "${name}"`);
  }
});

test("front matter is not parsed as setext headings", () => {
  const document = '---\ntitle: "Report"\nlang: en\n---\n\n# Real heading\n';
  const names = [];
  markdown.parse(document).iterate({ enter: (node) => names.push(node.name) });

  assert.ok(names.includes("Frontmatter"), "expected a Frontmatter node");
  assert.ok(names.includes("ATXHeading1"), "expected the body heading to survive");
  assert.ok(
    !names.some((name) => name.startsWith("SetextHeading")),
    `metadata lines must not become setext headings, saw: ${names.join(" ")}`,
  );
});

test("front matter contents are tagged as metadata rather than prose", () => {
  const document = '---\ntitle: "Report"\n# a note\n---\n\nbody\n';
  const names = new Set();
  markdown.parse(document).iterate({ enter: (node) => names.add(node.name) });

  for (const expected of [
    "FrontmatterMark",
    "FrontmatterKey",
    "FrontmatterSeparator",
    "FrontmatterValue",
    "FrontmatterComment",
  ]) {
    assert.ok(names.has(expected), `expected a ${expected} node`);
  }
});

test("an unterminated fence stays a thematic break and consumes no lines", () => {
  const document = "---\nnot metadata\n\n# Heading\n";
  const names = [];
  markdown.parse(document).iterate({ enter: (node) => names.push(node.name) });

  assert.ok(!names.includes("Frontmatter"), "an unterminated fence is not front matter");
  assert.ok(names.includes("ATXHeading1"), "the rest of the document must still parse");
});

test("a YAML comment inside front matter is metadata, not a document heading", () => {
  const document = "---\ntitle: Report\n# a note in the metadata\n---\n\n# Real heading\n\n## Second\n";

  assert.deepEqual(
    extractOutline(document).map((entry) => entry.title),
    ["Real heading", "Second"],
  );
});

test("outline line numbers stay absolute so preview navigation lands correctly", () => {
  const document = "---\ntitle: Report\n---\n\n# Real heading\n";

  assert.deepEqual(extractOutline(document), [{ level: 1, title: "Real heading", line: 5 }]);
});

test("a document with no front matter keeps every heading in its outline", () => {
  assert.deepEqual(
    extractOutline("# One\n\n## Two\n").map((entry) => entry.title),
    ["One", "Two"],
  );
});

test("two consecutive rules are thematic breaks, not empty metadata", () => {
  const parsed = parseFrontMatter("---\n---\n\n# Heading\n");

  assert.equal(parsed.present, false);
  assert.deepEqual(extractOutline("---\n---\n\n# Heading\n").map((entry) => entry.title), ["Heading"]);
});
