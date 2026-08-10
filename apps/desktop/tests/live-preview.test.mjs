import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  EDITOR_MODES,
  editorModeExtension,
  normalizeEditorMode,
} from "../editor-src/live-preview.mjs";
import {
  DEFAULT_PREFERENCES,
  editorModeForView,
  normalizePreferences,
  previewVisibleForView,
} from "../frontend/js/core/preferences.mjs";

const source = readFileSync(new URL("../editor-src/live-preview.mjs", import.meta.url), "utf8");

test("live preview is the default and unknown modes fall back to it", () => {
  assert.deepEqual([...EDITOR_MODES], ["live", "source"]);
  assert.equal(normalizeEditorMode("live"), "live");
  assert.equal(normalizeEditorMode("source"), "source");
  for (const value of ["wysiwyg", "", null, undefined, 42, {}]) {
    assert.equal(normalizeEditorMode(value), "live");
  }
});

test("source mode renders the document verbatim but keeps bidi measurement", () => {
  // Source mode adds no rendering, only the per-line direction support that
  // live mode cannot use: `perLineTextDirection` measures each line, and a line
  // replaced by a block widget has no tile to measure.
  const live = editorModeExtension("live");
  const source = editorModeExtension("source");
  assert.equal(live.length, 2, "live mode is the block field plus the preview plugin");
  assert.equal(source.length, 2, "source mode is direction support only");
  assert.notDeepEqual(live, source);
});

test("per-line direction is scoped to source mode", () => {
  assert.match(source, /perLineTextDirection/);
  assert.match(source, /normalizeEditorMode\(mode\) === "live"/);
});

test("live preview never edits the document", () => {
  // The whole design rests on the buffer staying plain Markdown: recovery
  // snapshots, conflict-safe saving and the publishing engine all read it
  // directly. A dispatch with `changes` here would silently rewrite the user's
  // file to match what is displayed.
  assert.doesNotMatch(source, /changes\s*:/);
  assert.doesNotMatch(source, /\.dispatch\(/);
  assert.doesNotMatch(source, /replaceRange|insertText/);
});

test("list markers stay visible because they are content, not scaffolding", () => {
  const hidden = source.slice(source.indexOf("const HIDDEN_MARKS"), source.indexOf("const hidden"));
  for (const mark of ["HeaderMark", "EmphasisMark", "LinkMark", "URL", "QuoteMark"]) {
    assert.ok(hidden.includes(mark), `${mark} should be hidden in live preview`);
  }
  assert.ok(!hidden.includes("ListMark"), "a bullet or number is content the reader expects");
});

test("hidden ranges are atomic so the caret cannot stall inside them", () => {
  assert.match(source, /EditorView\.atomicRanges\.of/);
});

test("the caret's own line is always shown as source", () => {
  assert.match(source, /activeLines/);
  assert.match(source, /if \(active\.has\(state\.doc\.lineAt\(node\.from\)\.number\)\) return;/);
});

test("one view mode decides both the rendering and the preview pane", () => {
  // Two independent toggles allowed states nobody wants, such as a rendered
  // editor beside a rendered preview showing the same thing twice.
  assert.equal(DEFAULT_PREFERENCES.viewMode, "write");
  assert.equal(normalizePreferences({ viewMode: "split" }).viewMode, "split");
  assert.equal(normalizePreferences({ viewMode: "nonsense" }).viewMode, "write");
  assert.equal(normalizePreferences({}).viewMode, "write");

  assert.equal(editorModeForView("write"), "live");
  assert.equal(editorModeForView("source"), "source");
  assert.equal(editorModeForView("split"), "source");

  assert.equal(previewVisibleForView("write"), false);
  assert.equal(previewVisibleForView("source"), false);
  assert.equal(previewVisibleForView("split"), true);
});

test("block widgets come from a state field, never from a view plugin", () => {
  // CodeMirror rejects block decorations supplied by plugins outright, and the
  // symptom is an unrelated "No tile at position" during measurement.
  const widgets = readFileSync(new URL("../editor-src/live-widgets.mjs", import.meta.url), "utf8");
  assert.match(widgets, /StateField\.define/);
  assert.match(widgets, /EditorView\.decorations\.from/);
  assert.match(widgets, /block: true/);
  // The prose above mentions ViewPlugin deliberately; what must not exist is a
  // plugin actually being declared or imported here.
  assert.doesNotMatch(widgets, /ViewPlugin\.fromClass/);
  assert.doesNotMatch(widgets, /import\s*\{[^}]*\bViewPlugin\b/);
});

test("line decorations never add box spacing that desynchronises the caret", () => {
  // CodeMirror maps a click to a document position through its own height map,
  // which is built from text layout. Margin sits outside the measured box and
  // padding proved to desynchronise the map as well: every line below a spaced
  // heading was offset, so the caret landed a line away from the click.
  const css = readFileSync(new URL("../frontend/workspace.css", import.meta.url), "utf8");
  const live = css.slice(css.indexOf("Live preview: a document"));
  const headingRules = [...live.matchAll(/\.cm-md-h(?:eading|\d)\s*\{([^}]*)\}/g)].map((m) => m[1]);
  assert.ok(headingRules.length >= 3, "expected the heading line rules");
  for (const rule of headingRules) {
    assert.ok(!/margin/.test(rule), `heading line rule uses margin: ${rule.trim()}`);
    assert.ok(!/padding-block|padding-top|padding-bottom/.test(rule),
      `heading line rule uses vertical padding: ${rule.trim()}`);
  }
  assert.ok(headingRules.some((rule) => /line-height/.test(rule)),
    "heading spacing should come from line-height");
});
