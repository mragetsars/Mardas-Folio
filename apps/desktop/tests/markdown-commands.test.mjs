import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { EditorSelection, EditorState } from "@codemirror/state";

import {
  MARKDOWN_COMMANDS,
  MARKDOWN_KEY_BINDINGS,
  markdownCommandNames,
  setHeading,
  toggleTask,
} from "../editor-src/markdown-commands.mjs";

/** Apply a command to a document and return the text and selected slice. */
function apply(name, text, from = 0, to = from) {
  const state = EditorState.create({
    doc: text,
    selection: EditorSelection.single(from, to),
  });
  const command = typeof name === "function" ? name : MARKDOWN_COMMANDS[name];
  const transaction = command(state);
  if (!transaction) return { text, selected: "", changed: false };
  const next = state.update(transaction).state;
  const selection = next.selection.main;
  return {
    text: next.doc.toString(),
    selected: next.sliceDoc(selection.from, selection.to),
    changed: true,
  };
}

const at = (text, needle) => [text.indexOf(needle), text.indexOf(needle) + needle.length];

test("emphasis wraps the selection and puts the caret inside", () => {
  const [from, to] = at("hello world", "world");
  assert.equal(apply("bold", "hello world", from, to).text, "hello **world**");
  assert.equal(apply("italic", "hello world", from, to).text, "hello _world_");
  assert.equal(apply("strike", "hello world", from, to).text, "hello ~~world~~");
  assert.equal(apply("code", "hello world", from, to).text, "hello `world`");
  // With nothing selected the placeholder is inserted and selected, so typing
  // replaces it instead of landing after the markers.
  const empty = apply("bold", "");
  assert.equal(empty.text, "**bold text**");
  assert.equal(empty.selected, "bold text");
});

test("pressing bold on bold text removes the emphasis", () => {
  // A formatting button that only ever adds markup makes the user delete
  // characters by hand to undo a click.
  const outside = "hello **world**";
  const [from, to] = at(outside, "world");
  assert.equal(apply("bold", outside, from, to).text, "hello world");

  const inside = "hello **world**";
  const start = inside.indexOf("**");
  assert.equal(apply("bold", inside, start, inside.length).text, "hello world");
});

test("a list applies, converts and clears across every selected line", () => {
  const text = "one\ntwo\nthree";
  const bulleted = apply("bullet-list", text, 0, text.length).text;
  assert.equal(bulleted, "- one\n- two\n- three");

  // Applying the same list again is how it is removed.
  assert.equal(apply("bullet-list", bulleted, 0, bulleted.length).text, "one\ntwo\nthree");

  // A different list converts rather than nesting.
  const numbered = apply("ordered-list", bulleted, 0, bulleted.length).text;
  assert.equal(numbered, "1. one\n2. two\n3. three");
  const tasks = apply("task-list", numbered, 0, numbered.length).text;
  assert.equal(tasks, "- [ ] one\n- [ ] two\n- [ ] three");
});

test("indentation survives changing the kind of list", () => {
  const text = "  - one\n  - two";
  assert.equal(apply("ordered-list", text, 0, text.length).text, "  1. one\n  2. two");
});

test("quoting toggles, and keeps working on already-quoted lines", () => {
  const text = "one\ntwo";
  const quoted = apply("quote", text, 0, text.length).text;
  assert.equal(quoted, "> one\n> two");
  assert.equal(apply("quote", quoted, 0, quoted.length).text, "one\ntwo");
});

test("headings set, change and clear at one keystroke", () => {
  assert.equal(apply("heading-2", "Title").text, "## Title");
  assert.equal(apply("heading-3", "## Title").text, "### Title");
  // Asking for the level a line already has removes it, so one key does both.
  assert.equal(apply("heading-2", "## Title").text, "Title");
  assert.equal(apply("paragraph", "#### Title").text, "Title");
  assert.equal(apply(setHeading(1), "  ## Title").text, "  # Title");
  // A paragraph asked to become a paragraph is already there.
  assert.equal(apply("paragraph", "Title").changed, false);
});

test("headings apply to every line the selection touches", () => {
  const text = "one\ntwo";
  assert.equal(apply("heading-1", text, 0, text.length).text, "# one\n# two");
});

test("a task checkbox toggles the two characters between its brackets", () => {
  assert.equal(apply(toggleTask, "- [ ] write").text, "- [x] write");
  assert.equal(apply(toggleTask, "- [x] write").text, "- [ ] write");
  assert.equal(apply(toggleTask, "- [X] write").text, "- [ ] write");
  assert.equal(apply(toggleTask, "not a task").changed, false);
});

test("block insertions land on their own lines, separated as Markdown needs", () => {
  // A rule pasted onto the end of a paragraph is not a rule; block constructs
  // need a blank line above them.
  assert.equal(apply("rule", "text").text, "text\n\n---");
  const table = apply("table", "text").text;
  assert.ok(table.startsWith("text\n\n"));
  assert.ok(table.includes("| Column | Column |"));
  assert.ok(table.includes("| --- | --- |"));
  // A fence puts the caret inside itself, ready for code.
  assert.ok(apply("code-block", "text").text.includes("```\n\n```"));
  // Content below is separated too, so the block is a block at both ends.
  assert.equal(apply("rule", "one\ntwo", 0).text, "one\n\n---\n\ntwo");
});

test("a blank line takes the block without opening a gap", () => {
  assert.equal(apply("rule", "").text, "---");
  assert.equal(apply("rule", "text\n\n", 6).text, "text\n\n---");
});

test("every command name resolves to a command", () => {
  for (const name of markdownCommandNames()) {
    assert.equal(typeof MARKDOWN_COMMANDS[name], "function", `${name} is not a command`);
  }
});

test("every key binding names a real command and leaves Save alone", () => {
  for (const binding of MARKDOWN_KEY_BINDINGS) {
    assert.ok(binding.command in MARKDOWN_COMMANDS, `${binding.key} names an unknown command`);
    // Ctrl/Cmd+S means Save on every platform this ships to; the editor must
    // not take it for strikethrough the way the upstream keymap does.
    assert.notEqual(binding.key.toLowerCase(), "mod-s");
  }
  const keys = MARKDOWN_KEY_BINDINGS.map((binding) => binding.key.toLowerCase());
  assert.equal(new Set(keys).size, keys.length, "two commands claim the same key");
});

test("formatting keys are bound inside the editor, above everything else", () => {
  // A window-level handler cannot see that CodeMirror already acted on the same
  // key, which is how Ctrl+I both expanded the selection and italicised it.
  const editor = readFileSync(
    new URL("../editor-src/codemirror-editor.mjs", import.meta.url),
    "utf8",
  );
  assert.match(editor, /Prec\.highest\(keymap\.of\(markdownCommandKeymap\(\)\)\)/);
  assert.match(editor, /runCommand\(name\)/);
});

test("typewriter scrolling is opt-in and reconfigurable", () => {
  const source = readFileSync(new URL("../editor-src/typewriter.mjs", import.meta.url), "utf8");
  assert.match(source, /export function typewriterExtension/);
  const editor = readFileSync(
    new URL("../editor-src/codemirror-editor.mjs", import.meta.url),
    "utf8",
  );
  assert.match(editor, /writingRhythm\.reconfigure/);
  assert.match(editor, /typewriter = false/);
});
