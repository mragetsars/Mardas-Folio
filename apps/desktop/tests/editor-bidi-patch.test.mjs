/**
 * Guards for the bidi patch applied to CodeMirror as the bundle is built.
 *
 * The defects it corrects are layout ones — a selection rectangle collapsing to
 * zero width, and End stopping in the middle of a line — so they can only be
 * observed in a browser, not here.  What these tests can hold is everything
 * around them: that the patch still matches the pinned dependency, that it
 * removes the hit test both defects came from, and that the committed bundle
 * is the patched one rather than a stale unpatched build.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

import {
  PATCHED_FUNCTIONS,
  applyPatch,
  codeMirrorBidiPatch,
} from "../scripts/codemirror-bidi-patch.mjs";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const viewModule = resolve(desktopRoot, "node_modules/@codemirror/view/dist/index.js");
const entryPoint = resolve(desktopRoot, "editor-src/codemirror-editor.mjs");
const bundlePath = resolve(desktopRoot, "frontend/js/vendor/codemirror-editor.bundle.mjs");

/** The body of a top-level function declaration, up to the next one. */
function functionBody(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} is missing from the patched source`);
  const end = source.indexOf("\nfunction ", start + 1);
  return source.slice(start, end === -1 ? undefined : end);
}

test("the patch still matches the pinned @codemirror/view", async () => {
  const source = await readFile(viewModule, "utf8");
  const patched = applyPatch(source);

  assert.notEqual(
    patched,
    null,
    "the patch no longer matches; re-derive it, or drop it if fixed upstream.",
  );
  assert.notEqual(patched, source);
  assert.deepEqual(PATCHED_FUNCTIONS, ["moveToLineBoundary", "wrappedLine"]);
});

test("neither patched function hit-tests the editor's horizontal edges", async () => {
  const patched = applyPatch(await readFile(viewModule, "utf8"));

  // Probing the far left and right edges is the defect both shared: on a line
  // whose direction changes, the outermost glyphs belong to an interior run.
  for (const name of PATCHED_FUNCTIONS) {
    const body = functionBody(patched, name);
    assert.doesNotMatch(body, /editorRect\.right - 1/, `${name} still probes the right edge`);
    assert.doesNotMatch(body, /editorRect\.left \+ 1/, `${name} still probes the left edge`);
    assert.match(body, /visualRowBounds\(/, `${name} does not use the row search`);
  }
  // The row search decides membership vertically, from a row midpoint.
  assert.match(functionBody(patched, "visualRowBounds"), /coords\.top \+ coords\.bottom\) \/ 2/);
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
    bundleFor([codeMirrorBidiPatch()]),
    bundleFor([]),
  ]);

  assert.equal(
    patched.equals(unpatched),
    false,
    "the plugin produced an unchanged bundle, so it is not reaching the build",
  );
  assert.equal(
    committed.equals(unpatched),
    false,
    "the committed bundle is an unpatched build; run `npm run build:editor`",
  );
});
