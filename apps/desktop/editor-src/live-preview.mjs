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

import { blockWidgetRanges, createBlockWidgetField } from "./live-widgets.mjs";

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
/* The language of a fenced block is worth reading; its backticks are not. */
const codeInfoMark = Decoration.mark({ class: "cm-md-code-info" });

/**
 * Per-line automatic direction.
 *
 * A Persian document mixes RTL prose with LTR code and identifiers, and
 * `EditorView.textDirectionAt` reads each line's computed direction. This has
 * to be applied by whichever plugin owns the line decorations, because a line
 * replaced by a block widget has no tile to measure and asking for its
 * direction throws.
 */
const autoDirection = Decoration.line({ attributes: { dir: "auto" } });
const codeLine = Decoration.line({ class: "cm-code-line" });
const quoteLine = Decoration.line({ class: "cm-quote-line" });
const codeOpenLine = Decoration.line({ class: "cm-code-line cm-code-open" });
const codeCloseLine = Decoration.line({ class: "cm-code-line cm-code-close" });

/**
 * Block-level line classes.
 *
 * A rendered document needs vertical rhythm — space above a heading, a rule
 * beside a quotation — and that is a property of the whole line, not of the
 * inline text. Hiding `#` and `>` removes the only cue CSS could otherwise
 * have keyed on, so the block type is carried here instead.
 */
const headingLines = new Map(
  [1, 2, 3, 4, 5, 6].map((level) => [
    `ATXHeading${level}`,
    Decoration.line({ class: `cm-md-heading cm-md-h${level}` }),
  ]),
);

/**
 * Callout kinds the publishing engine renders as cards.
 *
 * Mirrored from `_localized_labels` in `src/mardas_folio/markdown.py`. A
 * callout the engine will turn into a coloured admonition should not look like
 * an ordinary quotation while it is being written.
 */
const CALLOUT_KINDS = new Set([
  "note", "tip", "important", "warning", "caution", "info", "success",
  "question", "failure", "danger", "bug", "example", "quote", "abstract",
]);

/** `> [!NOTE] optional title` — the marker the engine looks for. */
const CALLOUT_MARKER = /^(\s*>\s*)(\[!([A-Za-z][A-Za-z0-9_-]*)\][+-]?)\s?/;

const calloutLines = new Map();

function calloutLine(kind, first) {
  const key = `${kind}:${first}`;
  if (!calloutLines.has(key)) {
    calloutLines.set(
      key,
      Decoration.line({
        class: `cm-md-callout cm-md-callout-${kind}${first ? " cm-md-callout-head" : ""}`,
      }),
    );
  }
  return calloutLines.get(key);
}

/** Whether the caret sits anywhere inside a multi-line node. */
function nodeIsActive(state, active, node) {
  const first = state.doc.lineAt(node.from).number;
  const last = state.doc.lineAt(node.to).number;
  for (let line = first; line <= last; line += 1) if (active.has(line)) return true;
  return false;
}

/** Run a callback for the start offset of every line a node spans. */
function eachLine(state, node, callback) {
  const first = state.doc.lineAt(node.from).number;
  const last = state.doc.lineAt(node.to).number;
  for (let line = first; line <= last; line += 1) callback(state.doc.line(line).from);
}

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
          const opener = state.doc.lineAt(node.from).from;
          const closer = state.doc.lineAt(node.to).from;
          eachLine(state, node, (at) => {
            const deco = at === opener ? codeOpenLine : at === closer ? codeCloseLine : codeLine;
            lines.push({ at, deco });
          });
          return;
        }
        if (node.name === "Blockquote") {
          // A quotation whose first line names a callout kind is not a
          // quotation: the engine publishes it as a coloured admonition, and
          // the editor should say so while it is being written.
          const first = state.doc.lineAt(node.from);
          const marker = CALLOUT_MARKER.exec(first.text);
          const kind = marker && CALLOUT_KINDS.has(marker[3].toLowerCase())
            ? marker[3].toLowerCase()
            : null;
          if (!kind) {
            eachLine(state, node, (at) => lines.push({ at, deco: quoteLine }));
            return;
          }
          eachLine(state, node, (at) => {
            lines.push({ at, deco: calloutLine(kind, at === first.from) });
          });
          if (!active.has(first.number)) {
            const from = first.from + marker[1].length;
            marks.push([from, from + marker[2].length + (marker[0].endsWith(" ") ? 1 : 0)]);
          }
          return;
        }
        const heading = headingLines.get(node.name);
        if (heading) {
          lines.push({ at: state.doc.lineAt(node.from).from, deco: heading });
          // fall through: the HeaderMark inside still needs hiding
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
        // A fence is scaffolding; the language it names is a label. Hiding the
        // backticks and styling the language turns ```` ```python ```` into a
        // chip on the panel the block already draws.
        if (node.name === "CodeMark" && node.node.parent?.name === "FencedCode") {
          marks.push([node.from, node.to]);
          return;
        }
        if (node.name === "CodeInfo") {
          marks.push([node.from, node.to, codeInfoMark]);
          return;
        }
        // A task item is introduced by its checkbox; the list bullet in front
        // of it is redundant once the checkbox is drawn.
        if (node.name === "ListMark") {
          const after = state.doc.sliceString(node.to, Math.min(node.to + 5, state.doc.length));
          if (/^\s*\[[ xX]\]/.test(after)) {
            marks.push([node.from, swallowSpace(state, node.to)]);
          }
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
  // Every visible line gets automatic direction unless a block widget replaced it.
  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos <= to; ) {
      const line = state.doc.lineAt(pos);
      lines.push({ at: line.from, deco: autoDirection });
      pos = line.to + 1;
    }
  }

  // A block widget owns its whole range; a line class or a hidden mark inside
  // it would have no tile to attach to.
  const blocks = blockWidgetRanges(state);
  const insideBlock = (at) => blocks.some(([from, to]) => at >= from && at < to);

  const events = [
    ...lines
      .filter(({ at }) => !insideBlock(at))
      .map(({ at, deco }) => ({ from: at, to: at, deco, line: true })),
    ...marks
      .filter(([from]) => !insideBlock(from))
      .map(([from, to, deco]) => ({ from, to, deco: deco || hidden, line: false })),
  ].sort((a, b) => a.from - b.from || Number(b.line) - Number(a.line));

  let lastFrom = -1;
  let lastTo = -1;
  let lastDeco = null;
  for (const event of events) {
    // Nested nodes can repeat a range; a RangeSetBuilder rejects duplicates.
    if (!event.line && event.from === lastFrom && event.to === lastTo && event.deco === lastDeco) {
      continue;
    }
    builder.add(event.from, event.to, event.deco);
    if (!event.line) {
      lastFrom = event.from;
      lastTo = event.to;
      lastDeco = event.deco;
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
        // Heading lines carry vertical padding, which changes their box height.
        // CodeMirror maps a click to a position through its height map, so the
        // map has to be refreshed when those decorations change — otherwise
        // every line below a heading is offset and the caret lands one line
        // away from the click.
        update.view.requestMeasure();
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

/** Source mode needs the same per-line direction, without any of the rendering. */
const autoDirectionPlugin = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.decorations = this.build(view);
    }

    update(update) {
      if (update.docChanged || update.viewportChanged) this.decorations = this.build(update.view);
    }

    build(view) {
      const builder = new RangeSetBuilder();
      for (const { from, to } of view.visibleRanges) {
        for (let pos = from; pos <= to; ) {
          const line = view.state.doc.lineAt(pos);
          builder.add(line.from, line.from, autoDirection);
          pos = line.to + 1;
        }
      }
      return builder.finish();
    }
  },
  { decorations: (plugin) => plugin.decorations },
);

export const EDITOR_MODES = Object.freeze(["live", "source"]);

export function normalizeEditorMode(value) {
  return EDITOR_MODES.includes(value) ? value : "live";
}

/**
 * The extension set for a mode; `source` renders the document verbatim.
 *
 * `perLineTextDirection` belongs in both modes. Without it CodeMirror assumes
 * one direction for the whole editor and measures every line against it, while
 * `dir="auto"` lets the browser lay each line out on its own. On any line whose
 * real direction differs from the editor's, the two models disagree, and
 * everything derived from the bidi model — the drawn selection, caret motion,
 * Home/End — is computed against text that is not where it is. A selected
 * Persian sentence containing a Latin word came out as a few misplaced bands of
 * highlight covering roughly three quarters of the characters.
 *
 * Live mode was left out because a line replaced by a block widget was thought
 * to have no tile to measure. It resolves to the widget's own element, which
 * answers a direction like any other, so the exclusion cost correctness for a
 * risk that was not there.
 */
export function editorModeExtension(mode, { resolveAsset } = {}) {
  const perLineDirection = EditorView.perLineTextDirection.of(true);
  return normalizeEditorMode(mode) === "live"
    ? [createBlockWidgetField(resolveAsset), livePreviewPlugin, perLineDirection]
    : [autoDirectionPlugin, perLineDirection];
}
