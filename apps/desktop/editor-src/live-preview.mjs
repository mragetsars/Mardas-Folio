/**
 * Live preview: edit Markdown as it will read, not as it is stored.
 *
 * The buffer stays plain Markdown — nothing here changes the document — so
 * recovery snapshots, conflict-safe saving, find/replace and the publishing
 * engine all keep working on exactly the text the user typed. What changes is
 * presentation: the syntax marks that carry no meaning once the formatting is
 * visible (`#`, `**`, backticks, link brackets, `>`) are hidden, and the text
 * they governed is styled instead.
 *
 * The line the cursor is on always shows its raw marks. That is what makes the
 * mode editable rather than merely a preview: to change a link's target you put
 * the caret in it and the `[label](url)` scaffolding comes back.
 */
import { syntaxTree } from "@codemirror/language";
import { RangeSetBuilder } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin } from "@codemirror/view";

/**
 * Marks that are safe to hide once their effect is rendered.
 *
 * `ListMark` is deliberately absent: a bullet or number is content the reader
 * expects to see, not scaffolding. Fence markers are handled separately so a
 * code block keeps its visible boundary.
 */
const HIDDEN_MARKS = new Set([
  "HeaderMark",
  "EmphasisMark",
  "StrikethroughMark",
  "LinkMark",
  "URL",
  "LinkTitle",
  "QuoteMark",
]);

const hidden = Decoration.replace({});
const codeLine = Decoration.line({ class: "cm-code-line" });

/** Extend an offset past the spaces that separate a block marker from its text. */
function swallowSpace(state, at) {
  const line = state.doc.lineAt(at);
  let end = at;
  while (end < line.to && state.doc.sliceString(end, end + 1) === " ") end += 1;
  return end;
}

/** Line numbers covered by a cursor or selection; these stay in source form. */
function activeLines(state) {
  const lines = new Set();
  for (const range of state.selection.ranges) {
    const first = state.doc.lineAt(range.from).number;
    const last = state.doc.lineAt(range.to).number;
    for (let line = first; line <= last; line += 1) lines.add(line);
  }
  return lines;
}

function buildDecorations(view) {
  const { state } = view;
  const active = activeLines(state);
  const marks = [];
  const lines = [];

  for (const { from, to } of view.visibleRanges) {
    syntaxTree(state).iterate({
      from,
      to,
      enter: (node) => {
        // Keep fenced code monospaced even when the surrounding prose is not.
        if (node.name === "FencedCode" || node.name === "CodeBlock") {
          const first = state.doc.lineAt(node.from).number;
          const last = state.doc.lineAt(node.to).number;
          for (let line = first; line <= last; line += 1) {
            lines.push(state.doc.line(line).from);
          }
          return;
        }

        if (node.from === node.to) return;
        if (active.has(state.doc.lineAt(node.from).number)) return;

        if (HIDDEN_MARKS.has(node.name)) {
          // `# ` and `> ` are a marker plus its separating space. Hiding only
          // the marker would leave the text indented by one stray column.
          const to = node.name === "HeaderMark" || node.name === "QuoteMark"
            ? swallowSpace(state, node.to)
            : node.to;
          marks.push([node.from, to]);
          return;
        }
        // Only the backticks of an inline span; a fence keeps its marker.
        if (node.name === "CodeMark" && node.node.parent?.name === "InlineCode") {
          marks.push([node.from, node.to]);
        }
      },
    });
  }

  // A RangeSet has to be built in document order, and line decorations sort
  // before the inline replacements that start at the same offset.
  const builder = new RangeSetBuilder();
  const events = [
    ...lines.map((at) => ({ from: at, to: at, deco: codeLine, line: true })),
    ...marks.map(([from, to]) => ({ from, to, deco: hidden, line: false })),
  ].sort((a, b) => a.from - b.from || Number(b.line) - Number(a.line));

  let lastFrom = -1;
  let lastTo = -1;
  for (const event of events) {
    // Nested nodes can repeat a range; a RangeSetBuilder rejects duplicates.
    if (!event.line && event.from === lastFrom && event.to === lastTo) continue;
    builder.add(event.from, event.to, event.deco);
    if (!event.line) {
      lastFrom = event.from;
      lastTo = event.to;
    }
  }
  return builder.finish();
}

const livePreviewPlugin = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.decorations = buildDecorations(view);
    }

    update(update) {
      if (update.docChanged || update.viewportChanged || update.selectionSet) {
        this.decorations = buildDecorations(update.view);
      }
    }
  },
  {
    decorations: (plugin) => plugin.decorations,
    // Hidden marks must not be enterable by the caret, or arrow keys appear to
    // stall on characters that are not on screen.
    provide: (plugin) =>
      EditorView.atomicRanges.of((view) => view.plugin(plugin)?.decorations ?? Decoration.none),
  },
);

export const EDITOR_MODES = Object.freeze(["live", "source"]);

export function normalizeEditorMode(value) {
  return EDITOR_MODES.includes(value) ? value : "live";
}

/** The extension set for a mode; `source` renders the document verbatim. */
export function editorModeExtension(mode) {
  return normalizeEditorMode(mode) === "live" ? [livePreviewPlugin] : [];
}
