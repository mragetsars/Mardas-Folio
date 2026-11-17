import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const main = readFileSync(new URL("../../frontend/js/main.mjs", import.meta.url), "utf8");
const sanitizerSource = readFileSync(new URL("../../frontend/js/preview/sanitize.mjs", import.meta.url), "utf8");
const index = readFileSync(new URL("../../frontend/index.html", import.meta.url), "utf8");
const tauri = JSON.parse(readFileSync(
  new URL("../../src-tauri/tauri.conf.json", import.meta.url),
  "utf8",
));

test("full-book preview sanitizes body content without injecting renderer head styles", () => {
  const start = main.indexOf("function renderFullBookPreview");
  const end = main.indexOf("async function previewActiveBook", start);
  const implementation = main.slice(start, end);
  assert.match(implementation, /safePreviewHtml\((?:parsed\.body|content)\.innerHTML, "book-review-"\)/);
  assert.match(implementation, /#book-review-document/);
  assert.doesNotMatch(implementation, /setViewMode|#preview-document/);
  assert.doesNotMatch(implementation, /parsed\.head|querySelectorAll\(["']style|createElement\(["']style/);

  const sanitizerStart = sanitizerSource.indexOf("function safePreviewHtml");
  const sanitizerEnd = sanitizerSource.length;
  const sanitizer = sanitizerSource.slice(sanitizerStart, sanitizerEnd);
  assert.match(sanitizer, /script,style,iframe,object,embed/);
});

test("command palette delegates every close path to shared ARIA cleanup", () => {
  const palette = readFileSync(new URL("../../frontend/js/ui/command-palette.mjs", import.meta.url), "utf8");
  const start = palette.indexOf("function openCommandPalette");
  const end = palette.indexOf("async function runCommand", start);
  const implementation = palette.slice(start, end);
  assert.match(implementation, /onClose: resetCommandPaletteA11y/);
  assert.match(implementation, /aria-expanded["'], ["']false/);
  assert.match(implementation, /removeAttribute\(["']aria-activedescendant/);
});

test("CSP permits runtime editor CSS without weakening script execution", () => {
  const meta = /http-equiv="Content-Security-Policy" content="([^"]+)"/.exec(index)?.[1];
  assert.equal(meta, tauri.app.security.csp);
  assert.match(meta, /style-src 'self' 'unsafe-inline'/);
  assert.match(meta, /script-src 'self';/);
  assert.doesNotMatch(meta, /script-src[^;]*unsafe-inline/);
  assert.doesNotMatch(meta, /frame-ancestors/);
  assert.match(sanitizerSource, /script,style,iframe,object,embed/);
  assert.match(sanitizerSource, /"style",/);
});

test("prefixing preview ids also prefixes what points at them", () => {
  // A Mermaid arrowhead is a `<marker id=…>` referenced by
  // `marker-end="url(#…)"`. Rewriting the id without the reference left every
  // diagram in the preview without arrows.
  const start = sanitizerSource.indexOf("function safePreviewHtml");
  const end = sanitizerSource.length;
  const sanitizer = sanitizerSource.slice(start, end);
  assert.match(sanitizer, /const localReference =/);
  assert.match(sanitizer, /idMap\.get\(id\)/);
  assert.match(sanitizer, /removeAttribute\("href"\);[\s\S]*?continue;/);
  assert.match(sanitizer, /"marker-start", "marker-mid", "marker-end"/);
});

test("find navigation never asks the editor adapter for a computed style", () => {
  // `currentEditor()` returns an adapter object, not an element. Passing it to
  // getComputedStyle throws, which took find-and-replace navigation with it.
  const start = main.indexOf("function selectFindMatch");
  const end = main.indexOf("function openFind", start);
  const implementation = main.slice(start, end);
  assert.match(implementation, /editorAdapter\?\.kind !== "codemirror"/);
  assert.match(implementation, /getComputedStyle\(element\)/);
  assert.doesNotMatch(implementation, /getComputedStyle\(editor\)/);
});
