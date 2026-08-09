import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  EDITOR_MODES,
  editorModeExtension,
  normalizeEditorMode,
} from "../editor-src/live-preview.mjs";
import { DEFAULT_PREFERENCES, normalizePreferences } from "../frontend/js/core/preferences.mjs";

const source = readFileSync(new URL("../editor-src/live-preview.mjs", import.meta.url), "utf8");

test("live preview is the default and unknown modes fall back to it", () => {
  assert.deepEqual([...EDITOR_MODES], ["live", "source"]);
  assert.equal(normalizeEditorMode("live"), "live");
  assert.equal(normalizeEditorMode("source"), "source");
  for (const value of ["wysiwyg", "", null, undefined, 42, {}]) {
    assert.equal(normalizeEditorMode(value), "live");
  }
});

test("source mode adds no decorations at all", () => {
  assert.deepEqual(editorModeExtension("source"), []);
  assert.equal(editorModeExtension("live").length, 1);
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

test("the editor mode is a persisted preference defaulting to live", () => {
  assert.equal(DEFAULT_PREFERENCES.editorMode, "live");
  assert.equal(normalizePreferences({ editorMode: "source" }).editorMode, "source");
  assert.equal(normalizePreferences({ editorMode: "nonsense" }).editorMode, "live");
  assert.equal(normalizePreferences({}).editorMode, "live");
});
