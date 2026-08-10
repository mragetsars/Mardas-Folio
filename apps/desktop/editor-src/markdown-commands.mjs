/**
 * Markdown editing commands, written against the document rather than the DOM.
 *
 * Every formatting action in the application ends up here: the toolbar, the
 * keyboard, the command palette and the context menu all run the same command
 * by name. That matters for more than tidiness — before this, the toolbar
 * rewrote the whole buffer through a textarea helper while the keyboard went
 * through CodeMirror, so the two disagreed about selections, undo history and
 * what "already bold" meant.
 *
 * Each command is `(state) => transaction | null`: pure with respect to the
 * document, so `apps/desktop/tests/markdown-commands.test.mjs` can drive them
 * on a headless `EditorState` with no browser involved.
 *
 * Toggling is the rule, not insertion. Pressing bold on bold text removes the
 * emphasis; pressing "bulleted list" on a bulleted list turns it back into
 * paragraphs. An editor whose formatting buttons only ever add markup makes the
 * user delete characters by hand to undo a click.
 */

import { EditorSelection } from "@codemirror/state";

/** Line prefixes that identify each block command, for toggling off. */
const BLOCK_PATTERNS = Object.freeze({
  quote: /^(\s*)>\s?/,
  "bullet-list": /^(\s*)[-*+]\s+/,
  "ordered-list": /^(\s*)\d+[.)]\s+/,
  "task-list": /^(\s*)[-*+]\s+\[[ xX]\]\s+/,
});

const BLOCK_PREFIXES = Object.freeze({
  quote: () => "> ",
  "bullet-list": () => "- ",
  "ordered-list": (index) => `${index + 1}. `,
  "task-list": () => "- [ ] ",
});

const HEADING = /^(\s*)(#{1,6})\s+/;

function lineRange(state, range) {
  const first = state.doc.lineAt(range.from);
  const last = state.doc.lineAt(range.to);
  return { first, last };
}

function eachSelectedLine(state, range, callback) {
  const { first, last } = lineRange(state, range);
  for (let number = first.number; number <= last.number; number += 1) {
    callback(state.doc.line(number), number - first.number);
  }
}

/**
 * Wrap or unwrap the selection with inline markers.
 *
 * With nothing selected the markers are inserted and the caret is put between
 * them, so typing continues inside the emphasis instead of after it.
 */
function inlineCommand(before, after = before, placeholderKey = "") {
  return (state) => {
    const changes = [];
    const ranges = [];
    let drift = 0;

    for (const range of state.selection.ranges) {
      const selected = state.sliceDoc(range.from, range.to);
      const outerFrom = Math.max(0, range.from - before.length);
      const outerTo = Math.min(state.doc.length, range.to + after.length);
      const wrappedOutside =
        state.sliceDoc(outerFrom, range.from) === before
        && state.sliceDoc(range.to, outerTo) === after;
      const wrappedInside =
        selected.length >= before.length + after.length
        && selected.startsWith(before)
        && selected.endsWith(after);

      if (wrappedOutside) {
        // The markers sit outside the selection: drop them and keep the text.
        changes.push(
          { from: outerFrom, to: range.from, insert: "" },
          { from: range.to, to: outerTo, insert: "" },
        );
        ranges.push(
          EditorSelection.range(
            outerFrom + drift,
            outerFrom + drift + selected.length,
          ),
        );
        drift -= before.length + after.length;
        continue;
      }
      if (wrappedInside) {
        const inner = selected.slice(before.length, selected.length - after.length);
        changes.push({ from: range.from, to: range.to, insert: inner });
        ranges.push(EditorSelection.range(range.from + drift, range.from + drift + inner.length));
        drift -= before.length + after.length;
        continue;
      }

      const body = selected || placeholderKey;
      changes.push({ from: range.from, to: range.to, insert: `${before}${body}${after}` });
      const start = range.from + drift + before.length;
      ranges.push(EditorSelection.range(start, start + body.length));
      drift += before.length + after.length + (body.length - selected.length);
    }

    if (!changes.length) return null;
    return { changes, selection: EditorSelection.create(ranges), scrollIntoView: true };
  };
}

/**
 * Apply, change or remove a line prefix across the selected lines.
 *
 * Applying a list to lines that are already that list removes it; applying a
 * different list converts it. That is what makes the toolbar buttons reversible
 * instead of a one-way trip into nested markup.
 */
function blockCommand(kind) {
  const pattern = BLOCK_PATTERNS[kind];
  const prefix = BLOCK_PREFIXES[kind];
  return (state) => {
    const changes = [];
    let allMatch = true;
    let touched = 0;

    for (const range of state.selection.ranges) {
      eachSelectedLine(state, range, (line) => {
        touched += 1;
        if (!pattern.test(line.text)) allMatch = false;
      });
    }
    if (!touched) return null;

    for (const range of state.selection.ranges) {
      eachSelectedLine(state, range, (line, offset) => {
        if (allMatch) {
          const match = pattern.exec(line.text);
          if (!match) return;
          changes.push({
            from: line.from,
            to: line.from + match[0].length,
            insert: match[1],
          });
          return;
        }
        // Replacing another list marker keeps the indentation it had.
        let from = line.from;
        let to = line.from;
        let indent = /^\s*/.exec(line.text)[0];
        for (const other of Object.values(BLOCK_PATTERNS)) {
          const match = other.exec(line.text);
          if (match && match[0].length > to - from) {
            to = line.from + match[0].length;
            indent = match[1];
          }
        }
        changes.push({ from, to, insert: `${indent}${prefix(offset)}` });
      });
    }
    if (!changes.length) return null;
    return { changes, scrollIntoView: true };
  };
}

/**
 * Set, change or clear the heading level of the selected lines.
 *
 * Level 0 means "make it a paragraph"; asking for the level a line already has
 * does the same, so the same key both applies and removes.
 */
export function setHeading(level) {
  return (state) => {
    const changes = [];
    const wanted = Math.max(0, Math.min(6, Math.trunc(Number(level) || 0)));
    let allAtLevel = wanted > 0;

    for (const range of state.selection.ranges) {
      eachSelectedLine(state, range, (line) => {
        const match = HEADING.exec(line.text);
        if (!match || match[2].length !== wanted) allAtLevel = false;
      });
    }

    for (const range of state.selection.ranges) {
      eachSelectedLine(state, range, (line) => {
        const match = HEADING.exec(line.text);
        const indent = match ? match[1] : /^\s*/.exec(line.text)[0];
        const to = line.from + (match ? match[0].length : indent.length);
        const insert = wanted === 0 || allAtLevel ? indent : `${indent}${"#".repeat(wanted)} `;
        if (to === line.from + indent.length && insert === indent) return;
        changes.push({ from: line.from, to, insert });
      });
    }
    if (!changes.length) return null;
    return { changes, scrollIntoView: true };
  };
}

/**
 * Insert a block after the caret's line, separated as Markdown requires.
 *
 * A table or a rule pasted onto the end of a paragraph is not a table or a
 * rule; block constructs need a blank line above them. The separator is added
 * only where one is missing, so pressing the button twice does not open a
 * growing gap.
 */
function insertBlock(text, { caretOffset = null } = {}) {
  return (state) => {
    const line = state.doc.lineAt(state.selection.main.from);
    const lead = line.text.trim() ? "\n\n" : "";
    const tail = line.to < state.doc.length ? "\n" : "";
    const insert = `${lead}${text}${tail}`;
    const at = line.to;
    const caret = caretOffset === null
      ? at + lead.length + text.length
      : at + lead.length + caretOffset;
    return {
      changes: { from: at, to: at, insert },
      selection: EditorSelection.cursor(caret),
      scrollIntoView: true,
    };
  };
}

/**
 * Toggle the checkbox of the task item the caret is in.
 *
 * This edits exactly the two characters between the brackets, which is a user
 * action through a control — not the preview layer reconciling the document
 * with what it drew.
 */
export function toggleTask(state) {
  const changes = [];
  for (const range of state.selection.ranges) {
    eachSelectedLine(state, range, (line) => {
      const match = /^(\s*[-*+]\s+\[)([ xX])(\])/.exec(line.text);
      if (!match) return;
      const at = line.from + match[1].length;
      changes.push({ from: at, to: at + 1, insert: match[2] === " " ? "x" : " " });
    });
  }
  return changes.length ? { changes } : null;
}

const TABLE_TEMPLATE = "| Column | Column |\n| --- | --- |\n|  |  |";

/**
 * The commands the application exposes, by name.
 *
 * Names are the vocabulary shared by the toolbar's `data-editor-command`, the
 * keymap below, the command palette and the context menu.
 */
export const MARKDOWN_COMMANDS = Object.freeze({
  bold: inlineCommand("**", "**", "bold text"),
  italic: inlineCommand("_", "_", "italic text"),
  strike: inlineCommand("~~", "~~", "struck text"),
  code: inlineCommand("`", "`", "code"),
  highlight: inlineCommand("==", "==", "highlight"),
  link: inlineCommand("[", "](https://)", "link text"),
  image: inlineCommand("![", "](assets/image.png)", "alt text"),
  citation: inlineCommand("[@", "]", "citation-key"),

  heading: setHeading(2),
  "heading-1": setHeading(1),
  "heading-2": setHeading(2),
  "heading-3": setHeading(3),
  "heading-4": setHeading(4),
  "heading-5": setHeading(5),
  "heading-6": setHeading(6),
  paragraph: setHeading(0),

  quote: blockCommand("quote"),
  "bullet-list": blockCommand("bullet-list"),
  "ordered-list": blockCommand("ordered-list"),
  "task-list": blockCommand("task-list"),
  "toggle-task": toggleTask,

  rule: insertBlock("---"),
  table: insertBlock(TABLE_TEMPLATE),
  "code-block": insertBlock("```\n\n```", { caretOffset: 4 }),
  callout: insertBlock("> [!NOTE]\n> ", { caretOffset: 12 }),
});

export function markdownCommandNames() {
  return Object.keys(MARKDOWN_COMMANDS);
}

/**
 * Run a named command against a view.
 *
 * Returns whether anything happened, so a key binding can fall through to the
 * next handler when the command had nothing to do.
 */
export function runMarkdownCommand(view, name) {
  const command = MARKDOWN_COMMANDS[name];
  if (!command || !view) return false;
  const transaction = command(view.state);
  if (!transaction) return false;
  view.dispatch(transaction);
  view.focus();
  return true;
}

/**
 * Keyboard bindings for the commands above.
 *
 * These are bound inside the editor rather than on the window. A window-level
 * handler cannot see that CodeMirror has already acted on the same key, which
 * is how Ctrl+I came to both expand the selection to its parent syntax node
 * *and* wrap the result in underscores.
 *
 * Ctrl/Cmd+S is deliberately absent: the platform meaning is Save, and the
 * application owns it.
 */
export const MARKDOWN_KEY_BINDINGS = Object.freeze([
  { key: "Mod-b", command: "bold" },
  { key: "Mod-i", command: "italic" },
  { key: "Mod-k", command: "link" },
  { key: "Mod-Shift-x", command: "strike" },
  { key: "Mod-e", command: "code" },
  { key: "Mod-Shift-8", command: "bullet-list" },
  { key: "Mod-Shift-7", command: "ordered-list" },
  { key: "Mod-Shift-9", command: "task-list" },
  { key: "Mod-Shift-.", command: "quote" },
  { key: "Mod-Shift-c", command: "code-block" },
  { key: "Mod-Shift-t", command: "table" },
  { key: "Mod-Shift-h", command: "rule" },
  { key: "Mod-Shift-Enter", command: "toggle-task" },
  { key: "Mod-Alt-0", command: "paragraph" },
  { key: "Mod-Alt-1", command: "heading-1" },
  { key: "Mod-Alt-2", command: "heading-2" },
  { key: "Mod-Alt-3", command: "heading-3" },
  { key: "Mod-Alt-4", command: "heading-4" },
  { key: "Mod-Alt-5", command: "heading-5" },
  { key: "Mod-Alt-6", command: "heading-6" },
]);

/** The bindings as CodeMirror expects them. */
export function markdownCommandKeymap() {
  return MARKDOWN_KEY_BINDINGS.map(({ key, command }) => ({
    key,
    preventDefault: true,
    run: (view) => runMarkdownCommand(view, command),
  }));
}
