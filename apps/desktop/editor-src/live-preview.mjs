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
import { Facet, RangeSetBuilder } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin } from "@codemirror/view";

import {
  BulletWidget,
  EntityWidget,
  ImageWidget,
  TaskWidget,
  blockWidgetRanges,
  createBlockWidgetField,
  parseImage,
} from "./live-widgets.mjs";

/**
 * How a Markdown image path becomes a URL the webview may load.
 *
 * Only the host knows this, and only this plugin needs it. It travels as a
 * facet rather than a closure because the plugin is created once for the
 * module while the resolver belongs to a particular editor.
 */
export const assetResolver = Facet.define({
  combine: (values) => (values.length ? values[0] : () => null),
});

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
  // `$` around a formula and `[^ ]` around a footnote label: the delimiters
  // say "this is math" and "this is a footnote", which the styling now says.
  "MathMark",
  "FootnoteMark",
]);

/** The link forms whose target is hidden because their text is shown instead. */
export const LINKS_WITH_TEXT = new Set(["Link", "Image"]);

const hidden = Decoration.replace({});
/* The language of a fenced block is worth reading; its backticks are not. */
const codeInfoMark = Decoration.mark({ class: "cm-md-code-info" });
/* Everything after the language on a fence line: real configuration, but not
   part of the label, so it is set quietly rather than shouted in the chip. */
const codeAttrMark = Decoration.mark({ class: "cm-md-code-attrs" });
/* A formula is set in the maths face, not in the prose face. */
const mathText = Decoration.mark({ class: "cm-md-math" });
const inlineCode = Decoration.mark({ class: "cm-md-inline-code" });
/* A reference is a superscript marker; the label is what identifies it. */
const footnoteLabel = Decoration.mark({ class: "cm-md-footnote" });
/* `[^id]: body` is a definition — the label stays legible on its own line. */
const footnoteDefLine = Decoration.line({ class: "cm-md-footnote-def" });
/* `[ref]: url "title"` likewise. */
const linkReferenceLine = Decoration.line({ class: "cm-md-link-reference" });
const mathBlockLine = Decoration.line({ class: "cm-md-math-block" });

/**
 * The named character references Markdown documents actually use, plus the
 * numeric forms. This is deliberately not an exhaustive HTML entity table:
 * the engine resolves every entity when it publishes, and the editor only has
 * to stop the common ones reading as literal source while they are written.
 */
const NAMED_ENTITIES = new Map(Object.entries({
  amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: "\u00a0",
  copy: "\u00a9", reg: "\u00ae", trade: "\u2122", deg: "\u00b0",
  hellip: "\u2026", mdash: "\u2014", ndash: "\u2013", minus: "\u2212",
  times: "\u00d7", divide: "\u00f7", plusmn: "\u00b1", ne: "\u2260",
  le: "\u2264", ge: "\u2265", laquo: "\u00ab", raquo: "\u00bb",
  ldquo: "\u201c", rdquo: "\u201d", lsquo: "\u2018", rsquo: "\u2019",
  larr: "\u2190", uarr: "\u2191", rarr: "\u2192", darr: "\u2193",
  harr: "\u2194", check: "\u2713", cross: "\u2717", bull: "\u2022",
  sect: "\u00a7", para: "\u00b6", dagger: "\u2020", euro: "\u20ac",
  pound: "\u00a3", yen: "\u00a5", cent: "\u00a2", alpha: "\u03b1",
  beta: "\u03b2", gamma: "\u03b3", delta: "\u03b4", pi: "\u03c0",
  sigma: "\u03c3", omega: "\u03c9", infin: "\u221e", sum: "\u2211",
  prod: "\u220f", radic: "\u221a", int: "\u222b", asymp: "\u2248",
  equiv: "\u2261", isin: "\u2208", notin: "\u2209", cap: "\u2229",
  cup: "\u222a", sub: "\u2282", sup: "\u2283", forall: "\u2200",
  exist: "\u2203", empty: "\u2205", nabla: "\u2207", part: "\u2202",
}));

function decodeEntity(source) {
  const body = source.replace(/^&/, "").replace(/;$/, "");
  if (!body) return null;
  if (body[0] === "#") {
    const digits = body[1] === "x" || body[1] === "X" ? body.slice(2) : body.slice(1);
    const radix = body[1] === "x" || body[1] === "X" ? 16 : 10;
    const code = Number.parseInt(digits, radix);
    if (!Number.isFinite(code) || code <= 0 || code > 0x10ffff) return null;
    try {
      return String.fromCodePoint(code);
    } catch {
      return null;
    }
  }
  return NAMED_ENTITIES.get(body) ?? null;
}

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
/**
 * A line with no strong character has no direction of its own.
 *
 * `dir="auto"` resolves from the first strong character and falls back to
 * left-to-right when there is none — whatever the editor around it is doing.
 * In a mirrored workbench that puts a front matter fence, a horizontal rule
 * and a table's `| --- | --- |` separator on the opposite edge from every
 * line they belong with, which is how the Persian workspace came to show
 * `---` hard against the left margin above a right-aligned heading.
 *
 * Only those lines are given a direction; anything with a strong character
 * keeps `plaintext` and resolves itself, which is what makes a Persian
 * sentence containing `src/main.py` lay out correctly.
 */
const neutralDirection = Decoration.line({ class: "cm-line-neutral" });
const HAS_STRONG_CHARACTER = /[A-Za-zÀ-˿Ͱ-֏֑-߿יִ-﷽ﹰ-ﻼ]/;

/**
 * No `dir` attribute at all, so the line inherits the editor's direction.
 *
 * Asking `view.textDirection` and writing `dir="rtl"` looks equivalent and is
 * not: the editor's direction is read from a measurement, and the plugin
 * builds its decorations before the first one has been taken, so every
 * neutral line was decided against a direction of left-to-right and never
 * revisited — the plugin only rebuilds when the document or the viewport
 * changes.
 */
function lineDirection(text) {
  return HAS_STRONG_CHARACTER.test(text) ? autoDirection : neutralDirection;
}
const codeLine = Decoration.line({ class: "cm-code-line" });
const quoteLine = Decoration.line({ class: "cm-quote-line" });

/** How many `>` markers open a line, which is the quotation's nesting depth. */
const QUOTE_DEPTH = /^(?:\s*>)+/;
/** Past this the indent costs more than the nesting communicates. */
const MAX_QUOTE_DEPTH = 4;
const quoteLines = new Map();

function quoteLineAt(text) {
  const marker = QUOTE_DEPTH.exec(text);
  const depth = marker ? Math.min((marker[0].match(/>/g) || []).length, MAX_QUOTE_DEPTH) : 1;
  let deco = quoteLines.get(depth);
  if (!deco) {
    deco = Decoration.line({ class: `cm-quote-line cm-quote-depth-${depth}` });
    quoteLines.set(depth, deco);
  }
  return deco;
}

/**
 * A quotation's bar belongs to the quotation, not to each of its lines.
 *
 * Every line carries `dir="auto"`, which is right for the text and wrong for
 * the decoration: a Persian callout's marker line has no strong character left
 * once `[!NOTE]` is hidden, so it resolved left-to-right while the body
 * resolved right-to-left, and the block drew its accent bar down its left edge
 * on one line and its right edge on the next. The block's own direction is
 * decided once, from its whole text, and the bar follows that.
 */
const rtlBlock = Decoration.line({ class: "cm-md-block-rtl" });
const FIRST_STRONG_RTL = /[֑-߿יִ-﷽ﹰ-ﻼ]/;
const FIRST_STRONG_LTR = /[A-Za-zÀ-˿Ͱ-֏]/;

function blockIsRtl(text) {
  const rtl = FIRST_STRONG_RTL.exec(text);
  if (!rtl) return false;
  const ltr = FIRST_STRONG_LTR.exec(text);
  return !ltr || rtl.index < ltr.index;
}
/* An item's own line, so a wrapped one can hang under its text rather than
   restart under its bullet, and the bullet itself can be told from the text. */
const listLine = Decoration.line({ class: "cm-md-list-line" });
const listMark = Decoration.mark({ class: "cm-md-list-mark" });

/** The three spellings of one bullet. An ordered marker keeps its number. */
const BULLET_SPELLINGS = new Set(["-", "*", "+"]);

/** How deeply an item nests, which is what chooses its bullet glyph. */
function bulletDepth(node) {
  let depth = -1;
  for (let at = node.node; at; at = at.parent) {
    if (at.name === "BulletList") depth += 1;
  }
  return Math.max(depth, 0);
}
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
const headingLines = new Map([
  ...[1, 2, 3, 4, 5, 6].map((level) => [
    `ATXHeading${level}`,
    Decoration.line({ class: `cm-md-heading cm-md-h${level}` }),
  ]),
  // `Title` over `=====` is the same heading as `# Title`, and was being left
  // at body size with its underline showing: the block classes were keyed on
  // the ATX node names alone, so a setext heading picked up the inline
  // highlight style and none of the block rhythm.
  ["SetextHeading1", Decoration.line({ class: "cm-md-heading cm-md-h1" })],
  ["SetextHeading2", Decoration.line({ class: "cm-md-heading cm-md-h2" })],
]);


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

/** `[^id]:` at the start of a line — mirrors FOOTNOTE_DEF_RE in the engine. */
const FOOTNOTE_DEF = /^(\[\^[^\]]+\]:)/;

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
        if (node.name === "BlockMath") {
          eachLine(state, node, (at) => lines.push({ at, deco: mathBlockLine }));
          return;
        }
        // A definition line is metadata the author still edits, so it is
        // quieted rather than hidden: nothing on the page stands in for it.
        if (node.name === "LinkReference") {
          eachLine(state, node, (at) => lines.push({ at, deco: linkReferenceLine }));
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
          // One direction for the whole block, so its bar stays on one side.
          // A callout's kind is always spelled in Latin — `[!NOTE]` — so the
          // marker is skipped; otherwise every Persian callout would be read
          // as a left-to-right block on the strength of its own label.
          const bodyFrom = marker ? first.from + marker[0].length : node.from;
          const rtl = blockIsRtl(state.doc.sliceString(bodyFrom, node.to));
          if (!kind) {
            eachLine(state, node, (at) => {
              // The engine nests `<blockquote>` inside `<blockquote>`, so a
              // quote inside a quote has to look deeper here too. Depth comes
              // from the line's own `>` markers rather than from the node
              // tree: the outer Blockquote's walk already covers every line,
              // and the inner one then produces the identical decoration,
              // which is dropped as a duplicate — which is why a nested quote
              // used to render flush with the quote containing it.
              lines.push({ at, deco: quoteLineAt(state.doc.lineAt(at).text) });
              if (rtl) lines.push({ at, deco: rtlBlock });
            });
            return;
          }
          eachLine(state, node, (at) => {
            lines.push({ at, deco: calloutLine(kind, at === first.from) });
            if (rtl) lines.push({ at, deco: rtlBlock });
          });
          if (!active.has(first.number)) {
            const from = first.from + marker[1].length;
            marks.push([from, from + marker[2].length + (marker[0].endsWith(" ") ? 1 : 0)]);
          }
          return;
        }
        // Applied whether or not the caret is on the line: an item that
        // re-indented as the caret arrived would make the list jump while it
        // is being edited.
        if (node.name === "ListItem") {
          eachLine(state, node, (at) => lines.push({ at, deco: listLine }));
          // fall through: the ListMark inside still needs its own styling
        }

        const heading = headingLines.get(node.name);
        if (heading) {
          lines.push({ at: state.doc.lineAt(node.from).from, deco: heading });
          // The `===` rule under a setext heading is collapsed by the block
          // field in live-widgets.mjs: replacing it takes a line break with
          // it, and a view plugin is not allowed to do that.
          // fall through: the HeaderMark inside still needs hiding
        }

        if (node.from === node.to) return;
        if (active.has(state.doc.lineAt(node.from).number)) return;

        // An image and a task checkbox replace inline text, not a block, so
        // they are drawn here — over the viewport — rather than in the block
        // field, which has to walk the whole document to find anything.
        if (node.name === "Image") {
          const parsed = parseImage(state.doc.sliceString(node.from, node.to));
          const url = parsed ? state.facet(assetResolver)(parsed.src) : null;
          if (url) {
            marks.push([
              node.from,
              node.to,
              Decoration.replace({ widget: new ImageWidget(url, parsed.alt) }),
            ]);
          }
          return false;
        }
        if (node.name === "TaskMarker") {
          const text = state.doc.sliceString(node.from, node.to);
          marks.push([
            node.from,
            node.to,
            Decoration.replace({ widget: new TaskWidget(/x/i.test(text), node.from, node.to) }),
          ]);
          return false;
        }

        // `[text][ref]` shows "text"; the `[ref]` that points at the
        // definition is scaffolding, exactly as `(url)` is in an inline link.
        // Left visible it read as "reference[ref]" and "ref[]".
        if (node.name === "LinkLabel" && node.node.parent?.name === "Link") {
          marks.push([node.from, node.to]);
          return false;
        }
        if (HIDDEN_MARKS.has(node.name)) {
          // A URL is only scaffolding when something else is standing in for
          // it. `[text](url)` and `![alt](src)` show their text and keep the
          // target out of the way, but an autolink and a bare URL *are* their
          // own text — hiding those deleted the address from the page and left
          // "and an autolink ." with a gap where the link had been.
          if (node.name === "URL" && !LINKS_WITH_TEXT.has(node.node.parent?.name)) return;
          // `[ref]: https://…  "Title"` is a definition, not a link: nothing
          // else on the page stands in for it, so hiding its title deleted
          // text the author has to be able to edit.
          if (node.name === "LinkTitle" && node.node.parent?.name === "LinkReference") return;
          // `# ` and `> ` are a marker plus its separating space. Hiding only
          // the marker would leave the text indented by one stray column.
          // A URL inside `[text](url "Title")` has the same problem at the
          // other end: hiding the URL and the title separately leaves the
          // space that used to sit between them, and the sentence read
          // "and a link ." with a gap before the full stop.
          const to = node.name === "HeaderMark"
            || node.name === "QuoteMark"
            || node.name === "URL"
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
        // `code` is a chip in every rendered Markdown, and the backticks that
        // make it one are already hidden — without a mark of its own the span
        // was distinguishable from prose only by colour.
        if (node.name === "InlineCode") {
          // The chip covers the text between the backticks, not the whole
          // span: a mark starting at the same offset as the hidden opening
          // `CodeMark` gives the RangeSetBuilder two ranges at one position,
          // and it throws — which CodeMirror turns into a disabled plugin and
          // an editor with no decorations at all.
          const source = state.doc.sliceString(node.from, node.to);
          const ticks = /^`+/.exec(source)?.[0].length ?? 1;
          const from = node.from + ticks;
          const to = node.to - ticks;
          if (to > from) marks.push([from, to, inlineCode]);
          return;
        }
        // Math and footnotes read as content, not as punctuation.
        if (node.name === "MathText") {
          marks.push([node.from, node.to, mathText]);
          return false;
        }
        if (node.name === "FootnoteLabel") {
          marks.push([node.from, node.to, footnoteLabel]);
          return false;
        }
        if (node.name === "CodeInfo") {
          // ```` ```python title="listing.py" showLineNumbers ```` names one
          // language and then configures it. The chip is the language; the
          // attributes belong to the fence, not to the label, and setting the
          // whole string in a chip printed
          // `PYTHON TITLE="LISTING.PY" SHOWLINENUMBERS` across the block.
          const info = state.doc.sliceString(node.from, node.to);
          const language = /^\s*\S+/.exec(info);
          const end = language ? node.from + language[0].length : node.to;
          marks.push([node.from, end, codeInfoMark]);
          if (end < node.to) marks.push([end, node.to, codeAttrMark]);
          return;
        }
        // A task item is introduced by its checkbox; the list bullet in front
        // of it is redundant once the checkbox is drawn.
        if (node.name === "ListMark") {
          const after = state.doc.sliceString(node.to, Math.min(node.to + 5, state.doc.length));
          if (/^\s*\[[ xX]\]/.test(after)) {
            marks.push([node.from, swallowSpace(state, node.to)]);
            return;
          }
          const spelling = state.doc.sliceString(node.from, node.to);
          if (BULLET_SPELLINGS.has(spelling)) {
            marks.push([
              node.from,
              node.to,
              Decoration.replace({ widget: new BulletWidget(bulletDepth(node)) }),
            ]);
            return;
          }
          marks.push([node.from, node.to, listMark]);
          return;
        }
        // Only the backticks of an inline span; a fence keeps its marker.
        if (node.name === "CodeMark" && node.node.parent?.name === "InlineCode") {
          marks.push([node.from, node.to]);
          return;
        }
        // `\*` is one literal asterisk. The backslash is the instruction, not
        // the character, and it was being printed alongside it.
        if (node.name === "Escape") {
          marks.push([node.from, node.from + 1]);
          return;
        }
        // A hard break's trailing spaces or backslash are invisible in the
        // rendered document; the line break they cause is the content.
        if (node.name === "HardBreak") {
          marks.push([node.from, node.to]);
          return;
        }
        // `&mdash;` is an em dash everywhere except here, where it was seven
        // literal characters.
        if (node.name === "Entity") {
          const decoded = decodeEntity(state.doc.sliceString(node.from, node.to));
          if (decoded) {
            marks.push([node.from, node.to, Decoration.replace({
              widget: new EntityWidget(decoded),
            })]);
          }
          return;
        }
      },
    });
  }

  // `[^id]: body` has no node of its own — a block rule for it would have to
  // decide where the definition ends, and the engine allows indented
  // continuation lines. Matching the marker per line leaves that question to
  // the engine and still lets the label be styled.
  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos <= to; ) {
      const line = state.doc.lineAt(pos);
      const match = FOOTNOTE_DEF.exec(line.text);
      if (match && !active.has(line.number)) {
        lines.push({ at: line.from, deco: footnoteDefLine });
        // `[` and `]` are already hidden as link marks, which left the caret
        // stranded in front of the label: the definition read `^1:` where the
        // reference above it reads as a superscript 1. Hide the caret too and
        // style what remains as the same label.
        marks.push([line.from + 1, line.from + 2]);
        marks.push([line.from + 2, line.from + match[1].length - 2, footnoteLabel]);
      }
      pos = line.to + 1;
    }
  }

  // A RangeSet has to be built in document order, and line decorations sort
  // before the inline replacements that start at the same offset.
  const builder = new RangeSetBuilder();
  // Every visible line gets automatic direction unless a block widget replaced it.
  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos <= to; ) {
      const line = state.doc.lineAt(pos);
      lines.push({ at: line.from, deco: lineDirection(line.text) });
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
      // A view plugin may not replace a line break — CodeMirror rejects the
      // whole batch with "decorations that replace line breaks may not be
      // specified via plugins", so one node that happens to include its
      // trailing newline silently strips every decoration in the document.
      // `HardBreak` is exactly that node: it spans the two trailing spaces
      // *and* the newline they cause. Clamping here rather than at each call
      // site means a future node with the same shape cannot reintroduce it;
      // anything that genuinely needs to swallow a line break belongs in the
      // block field in live-widgets.mjs.
      .map(([from, to, deco]) => {
        const lineEnd = state.doc.lineAt(from).to;
        return { from, to: Math.min(to, lineEnd), deco: deco || hidden, line: false };
      })
      .filter(({ from, to }) => to > from),
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
          builder.add(line.from, line.from, lineDirection(line.text));
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
    ? [
        createBlockWidgetField(),
        assetResolver.of(resolveAsset || (() => null)),
        livePreviewPlugin,
        perLineDirection,
      ]
    : [autoDirectionPlugin, perLineDirection];
}
