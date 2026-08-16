/**
 * Guards for the bidi selection-drawing patch.
 *
 * The defect it corrects is a layout one — a selection rectangle collapsing to
 * zero width on a line whose direction changes once — so it can only be
 * observed in a browser, not here.  What these tests can hold is everything
 * around it: that the patch still matches the pinned dependency, that it
 * changes the function it claims to, and that the committed bundle is the
 * patched one rather than a stale unpatched build.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

import {
  applyPatch,
  codeMirrorBidiSelectionPatch,
} from "../scripts/codemirror-bidi-selection-patch.mjs";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const viewModule = resolve(desktopRoot, "node_modules/@codemirror/view/dist/index.js");
const entryPoint = resolve(desktopRoot, "editor-src/codemirror-editor.mjs");
const bundlePath = resolve(desktopRoot, "frontend/js/vendor/codemirror-editor.bundle.mjs");

test("the patch still matches the pinned @codemirror/view", async () => {
  const source = await readFile(viewModule, "utf8");
  const patched = applyPatch(source);

  assert.notEqual(
    patched,
    null,
    "wrappedLine no longer matches; re-derive the patch or drop it if fixed upstream.",
  );
  assert.notEqual(patched, source);

  // The horizontal hit test is the defect; it must be gone from that function.
  const wrapped = patched.slice(
    patched.indexOf("function wrappedLine("),
    patched.indexOf("function rectanglesForRange("),
  );
  assert.doesNotMatch(wrapped, /editorRect\.right - 1/);
  assert.doesNotMatch(wrapped, /editorRect\.left \+ 1/);
  assert.match(wrapped, /c\.bottom > coords\.top && c\.top < coords\.bottom/);
});

test("the patch refuses to apply to source it does not recognise", () => {
  assert.equal(applyPatch("function wrappedLine() { return null; }"), null);
});

const bundleFor = async (plugins) => {
  const result = await build({
    absWorkingDir: desktopRoot,
    bundle: true,
    charset: "utf8",
    entryPoints: [entryPoint],
    format: "esm",
    minify: true,
    platform: "browser",
    plugins,
    target: ["es2020"],
    treeShaking: true,
    write: false,
  });
  return Buffer.from(result.outputFiles[0].contents);
};

test("the committed bundle carries the patch", async () => {
  const [committed, patched, unpatched] = await Promise.all([
    readFile(bundlePath),
    bundleFor([codeMirrorBidiSelectionPatch()]),
    bundleFor([]),
  ]);

  assert.notEqual(
    patched.equals(unpatched),
    true,
    "the plugin produced an unchanged bundle, so it is not reaching the build",
  );
  assert.equal(
    committed.equals(unpatched),
    false,
    "the committed bundle is an unpatched build; run `npm run build:editor`",
  );
});
