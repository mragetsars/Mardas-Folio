import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");
const index = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
const tauri = JSON.parse(readFileSync(
  new URL("../src-tauri/tauri.conf.json", import.meta.url),
  "utf8",
));

test("full-book preview sanitizes body content without injecting renderer head styles", () => {
  const start = main.indexOf("function renderFullBookPreview");
  const end = main.indexOf("async function previewActiveBook", start);
  const implementation = main.slice(start, end);
  assert.match(implementation, /safePreviewHtml\(parsed\.body\.innerHTML\)/);
  assert.doesNotMatch(implementation, /parsed\.head|querySelectorAll\(["']style|createElement\(["']style/);

  const sanitizerStart = main.indexOf("function safePreviewHtml");
  const sanitizerEnd = main.indexOf("function renderPreviewMessage", sanitizerStart);
  const sanitizer = main.slice(sanitizerStart, sanitizerEnd);
  assert.match(sanitizer, /script,style,iframe,object,embed/);
});

test("command palette delegates every close path to shared ARIA cleanup", () => {
  const start = main.indexOf("function openCommandPalette");
  const end = main.indexOf("async function runCommand", start);
  const implementation = main.slice(start, end);
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
  assert.match(main, /script,style,iframe,object,embed/);
  assert.match(main, /"style",/);
});
