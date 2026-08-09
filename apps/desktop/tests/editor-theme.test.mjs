import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { tags } from "@lezer/highlight";

import {
  EDITOR_FONT_FAMILY,
  mardasHighlightStyle,
  mardasEditorAppearance,
} from "../editor-src/editor-theme.mjs";

const themeSource = readFileSync(new URL("../editor-src/editor-theme.mjs", import.meta.url), "utf8");
const workspaceCss = readFileSync(new URL("../frontend/workspace.css", import.meta.url), "utf8");

/**
 * Every `--cm-` property the highlight style and theme read, whether written
 * through the `token()` helper or as a literal `var(--cm-…)`.
 */
function referencedTokens(source) {
  return new Set([
    ...[...source.matchAll(/\btoken\("([a-z-]+)"/g)].map((match) => match[1]),
    ...[...source.matchAll(/var\(--cm-([a-z-]+)/g)].map((match) => match[1]),
  ]);
}

/** Custom properties declared for a given selector block in workspace.css. */
function declaredTokens(css, selector) {
  const start = css.indexOf(selector);
  assert.notEqual(start, -1, `expected a ${selector} block in workspace.css`);
  const block = css.slice(start, css.indexOf("}", start));
  return new Set([...block.matchAll(/--cm-([a-z-]+)\s*:/g)].map((match) => match[1]));
}

test("no Markdown token is underlined", () => {
  // CodeMirror's defaultHighlightStyle underlines every heading and link, which
  // reads as noise in a document you are writing rather than reading.
  for (const rule of mardasHighlightStyle.specs) {
    const decoration = String(rule.textDecoration || "");
    assert.ok(
      !decoration.includes("underline"),
      `${String(rule.tag)} must not be underlined, got ${decoration}`,
    );
  }
});

test("every colour resolves through a --cm- custom property", () => {
  for (const rule of mardasHighlightStyle.specs) {
    if (!rule.color) continue;
    assert.match(
      rule.color,
      /^var\(--cm-[a-z-]+, *#|^var\(--cm-[a-z-]+, *rgba?\(/,
      `${String(rule.tag)} must read a --cm- property with a literal fallback, got ${rule.color}`,
    );
  }
});

test("the tokens the editor reads are declared for both themes", () => {
  const referenced = referencedTokens(themeSource);
  assert.ok(referenced.size > 20, "expected the theme to reference a real palette");

  const light = declaredTokens(workspaceCss, ":root {");
  const dark = declaredTokens(workspaceCss, 'html[data-theme="dark"] {');

  const missingLight = [...referenced].filter((name) => !light.has(name));
  assert.deepEqual(missingLight, [], "light theme is missing --cm- declarations");

  // Dark inherits the structural tokens it does not need to override; the
  // syntax colours must all be restated so no light-only value leaks through.
  const syntax = [
    "text", "strong", "emphasis", "mark", "meta", "comment", "heading", "list",
    "link", "url", "quote", "code", "number", "string", "key", "function",
    "keyword", "type", "variable", "invalid",
  ];
  const missingDark = syntax.filter((name) => !dark.has(name));
  assert.deepEqual(missingDark, [], "dark theme is missing syntax --cm- declarations");
});

test("headings are distinguished by weight and size rather than decoration", () => {
  const headings = mardasHighlightStyle.specs.filter((rule) =>
    [tags.heading1, tags.heading2, tags.heading3].includes(rule.tag),
  );
  assert.equal(headings.length, 3);
  for (const rule of headings) {
    assert.ok(Number(rule.fontWeight) >= 600, "headings carry weight");
    assert.match(String(rule.fontSize), /em$/, "headings carry a relative size");
  }
});

test("the editor font stack names Persian faces before the generic fallback", () => {
  const persian = EDITOR_FONT_FAMILY.indexOf("Vazirmatn");
  const generic = EDITOR_FONT_FAMILY.lastIndexOf("monospace");
  assert.ok(persian !== -1, "a Persian face must be present for bilingual documents");
  assert.ok(persian < generic, "Persian faces must precede the generic monospace fallback");
});

test("the appearance extension reports its light/dark side to CodeMirror", () => {
  // CodeMirror's own base rules and floating panels key off this flag.
  assert.notDeepEqual(mardasEditorAppearance(true), mardasEditorAppearance(false));
});
