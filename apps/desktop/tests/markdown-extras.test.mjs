import test from "node:test";
import assert from "node:assert/strict";

import { parser } from "@lezer/markdown";
import { GFM } from "@lezer/markdown";

import { mathAndFootnotes } from "../editor-src/markdown-extras.mjs";

const markdown = parser.configure([GFM, mathAndFootnotes]);

/** Every node name the parser produced, in document order. */
function nodes(text) {
  const found = [];
  markdown.parse(text).iterate({ enter: (node) => void found.push(node.name) });
  return found;
}

/** The source text a named node covers, or undefined if there is no such node. */
function textOf(text, name) {
  let slice;
  markdown.parse(text).iterate({
    enter: (node) => {
      if (slice === undefined && node.name === name) slice = text.slice(node.from, node.to);
    },
  });
  return slice;
}

test("inline math is recognised the way the engine recognises it", () => {
  assert.ok(nodes("Energy is $E = mc^2$ exactly.").includes("InlineMath"));
  assert.equal(textOf("Energy is $E = mc^2$ exactly.", "InlineMath"), "$E = mc^2$");
  assert.equal(textOf("Energy is $E = mc^2$ exactly.", "MathText"), "E = mc^2");
});

test("prices are not math", () => {
  // INLINE_MATH_RE in src/mardas_folio/markdown.py ends with a negative
  // look-ahead on a digit for exactly this sentence. Without it, everything
  // between two amounts of money is typeset as a formula.
  assert.ok(!nodes("It cost $5 and $7 total.").includes("InlineMath"));
});

test("a dollar followed by a space is not an opening delimiter", () => {
  assert.ok(!nodes("Costs $ 5 to run.").includes("InlineMath"));
});

test("an unterminated dollar is left as text", () => {
  assert.ok(!nodes("A lone $ sign in prose.").includes("InlineMath"));
  assert.ok(!nodes("Opens $here but never closes.").includes("InlineMath"));
});

test("inline math does not span a line break", () => {
  assert.ok(!nodes("Opens $here\nand closes$ on the next line.").includes("InlineMath"));
});

test("display math is a block", () => {
  const text = "Before\n\n$$\n\\int_0^1 x\\,dx\n$$\n\nAfter\n";
  assert.ok(nodes(text).includes("BlockMath"));
  assert.equal(textOf(text, "MathText"), "\\int_0^1 x\\,dx");
});

test("an unterminated display fence stays a paragraph", () => {
  // A block parser cannot backtrack, so a `$$` with no partner must not
  // swallow the rest of the document.
  assert.ok(!nodes("$$\n\\alpha\n\nStill prose.\n").includes("BlockMath"));
});

test("footnote references are their own node, not link labels", () => {
  const text = "A claim[^1] worth citing.\n";
  assert.ok(nodes(text).includes("FootnoteReference"));
  assert.equal(textOf(text, "FootnoteLabel"), "1");
});

test("a footnote definition is not parsed as a reference", () => {
  // `[^1]:` opens a definition. Claiming it as a reference would superscript
  // the label at the start of its own body line.
  assert.ok(!nodes("[^1]: The body of the note.\n").includes("FootnoteReference"));
});

test("an ordinary link is still a link", () => {
  const text = "See [the guide](https://example.com).\n";
  const names = nodes(text);
  assert.ok(names.includes("Link"));
  assert.ok(!names.includes("FootnoteReference"));
});

test("GFM survives the extension", () => {
  // The extension adds inline rules ahead of Link and Escape; a table, a task
  // list and a strikethrough still have to parse.
  const names = nodes("| a | b |\n| - | - |\n| 1 | 2 |\n\n- [x] done\n\n~~gone~~\n");
  for (const expected of ["Table", "TaskMarker", "Strikethrough"]) {
    assert.ok(names.includes(expected), `${expected} disappeared`);
  }
});
