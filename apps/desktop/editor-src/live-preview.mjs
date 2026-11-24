import { calloutMarkerAt, eachLine, headingLevel } from "./document-line-layout.mjs";
import { diagramRenderer } from "./diagram-widget.mjs";
import { blockDragExtension } from "./block-drag.mjs";
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
 * The visual markers stay hidden as the caret moves. Source is the
 * dedicated mode for editing Markdown punctuation and structure directly.
 */
import { foldable, foldedRanges, foldEffect, syntaxTree, unfoldEffect } from "@codemirror/language";
import { spriteIcon } from "../frontend/js/ui/icons.mjs";
import { Facet, RangeSetBuilder } from "@codemirror/state";
import { Decoration, Direction, EditorView, ViewPlugin, WidgetType } from "@codemirror/view";
import {
  CodeBlockHeaderWidget,
  codeBodyPrefixRanges,
  fencedCodeSpec,
  setCodeWrap,
  wrapsCode,
} from "./code-block-tools.mjs";
import { tableEditingExtension } from "./table-editing.mjs";
import { sourceGutterDirection } from "./source-direction.mjs";

import {
  BulletWidget,
  EntityWidget,
  ImageWidget,
  ImagePlaceholderWidget,
  OnlineImageWidget,
  TaskWidget,
  MathWidget,
  mathRenderer,
  blockWidgetRanges,
  createBlockWidgetField,
  parseImage,
  tableContentDirection,
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
export const onlineImageRequest = Facet.define({
  combine: (values) => values[0] || null,
});

/**
 * Text the editor draws that the application has to translate.
 *
 * The widgets are inside the bundled editor, which has no access to the
 * interface's own dictionary, so "Image not found" was English in a Persian
 * document. The host passes what it needs translated in, the way it already
 * passes in the asset resolver.
 */
export const editorStrings = Facet.define({
  combine: (values) =>
    Object.assign(
      { imageNotFound: "Image not found", remoteImageNotLoaded: "Remote image not loaded" },
      ...values,
    ),
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

const hidden = Decoration.replace({ mardasAtomic: true });
/* A formula is set in the maths face, not in the prose face. */
const mathText = Decoration.mark({ class: "cm-md-math" });
const inlineCode = Decoration.mark({ class: "cm-md-inline-code", bidiIsolate: Direction.LTR });
/* A reference is a superscript marker; the label is what identifies it. */
const footnoteLabel = Decoration.mark({ class: "cm-md-footnote" });
/* `[^id]: body` is a definition — the label stays legible on its own line. */
const footnoteDefLine = Decoration.line({ class: "cm-md-footnote-def" });
/* `[ref]: url "title"` likewise. */
const linkReferenceLine = Decoration.line({ class: "cm-md-link-reference" });
// A Markdown paragraph separator is still a real, navigable source line. It
// needs a little breathing room, not a second full row of prose. Keep this a
// line decoration (never a replacement) so typing, selection and undo use the
// original buffer and blank lines inside code/math retain their full height.

/**
 * The named character references Markdown documents actually use, plus the
 * numeric forms. This is deliberately not an exhaustive HTML entity table:
 * the engine resolves every entity when it publishes, and the editor only has
 * to stop the common ones reading as literal source while they are written.
 */
const NAMED_ENTITIES = new Map(
  Object.entries({
    amp: "&",
    lt: "<",
    gt: ">",
    quot: '"',
    apos: "'",
    nbsp: "\u00a0",
    copy: "\u00a9",
    reg: "\u00ae",
    trade: "\u2122",
    deg: "\u00b0",
    hellip: "\u2026",
    mdash: "\u2014",
    ndash: "\u2013",
    minus: "\u2212",
    times: "\u00d7",
    divide: "\u00f7",
    plusmn: "\u00b1",
    ne: "\u2260",
    le: "\u2264",
    ge: "\u2265",
    laquo: "\u00ab",
    raquo: "\u00bb",
    ldquo: "\u201c",
    rdquo: "\u201d",
    lsquo: "\u2018",
    rsquo: "\u2019",
    larr: "\u2190",
    uarr: "\u2191",
    rarr: "\u2192",
    darr: "\u2193",
    harr: "\u2194",
    check: "\u2713",
    cross: "\u2717",
    bull: "\u2022",
    sect: "\u00a7",
    para: "\u00b6",
    dagger: "\u2020",
    euro: "\u20ac",
    pound: "\u00a3",
    yen: "\u00a5",
    cent: "\u00a2",
    alpha: "\u03b1",
    beta: "\u03b2",
    gamma: "\u03b3",
    delta: "\u03b4",
    pi: "\u03c0",
    sigma: "\u03c3",
    omega: "\u03c9",
    infin: "\u221e",
    sum: "\u2211",
    prod: "\u220f",
    radic: "\u221a",
    int: "\u222b",
    asymp: "\u2248",
    equiv: "\u2261",
    isin: "\u2208",
    notin: "\u2209",
    cap: "\u2229",
    cup: "\u222a",
    sub: "\u2282",
    sup: "\u2283",
    forall: "\u2200",
    exist: "\u2203",
    empty: "\u2205",
    nabla: "\u2207",
    part: "\u2202",
  }),
);

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
const listMark = Decoration.mark({ class: "cm-md-list-mark" });
const documentTextRun = Decoration.mark({ class: "cm-document-text-run" });

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
class SectionFoldWidget extends WidgetType {
  constructor(range, folded, locale) {
    super();
    this.range = range;
    this.folded = folded;
    this.locale = locale;
  }

  eq(other) {
    return (
      this.range.from === other.range.from &&
      this.range.to === other.range.to &&
      this.folded === other.folded &&
      this.locale === other.locale
    );
  }

  toDOM(view) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "cm-section-toggle";
    button.contentEditable = "false";
    button.setAttribute("aria-expanded", String(!this.folded));
    const label =
      this.locale === "fa"
        ? this.folded
          ? "بازکردن بخش"
          : "جمع‌کردن بخش"
        : this.folded
          ? "Expand section"
          : "Collapse section";
    button.setAttribute("aria-label", label);
    button.title = label;
    button.append(spriteIcon(this.folded ? "chevron-right" : "chevron-down"));
    button.addEventListener("click", () => {
      const effect = this.folded ? unfoldEffect : foldEffect;
      view.dispatch({ effects: effect.of(this.range), selection: { anchor: this.range.from } });
      view.focus();
    });
    return button;
  }

  ignoreEvent() {
    return true;
  }
}

/** `[^id]:` at the start of a line — mirrors FOOTNOTE_DEF_RE in the engine. */
const FOOTNOTE_DEF = /^(\[\^[^\]]+\]:)/;

class CalloutBadge extends WidgetType {
  constructor(kind) {
    super();
    this.kind = kind;
  }

  eq(other) {
    return this.kind === other.kind;
  }

  toDOM() {
    const label = document.createElement("span");
    label.className = "cm-callout-badge";
    const icon =
      {
        tip: "check",
        success: "check",
        question: "help",
        warning: "help",
        caution: "help",
        danger: "close",
        failure: "close",
      }[this.kind] || "callout";
    label.append(spriteIcon(icon), this.kind.toUpperCase());
    return label;
  }
}

/** Whether the caret sits anywhere inside a multi-line node. */
function nodeIsActive(state, active, node) {
  const first = state.doc.lineAt(node.from).number;
  const last = state.doc.lineAt(node.to).number;
  for (let line = first; line <= last; line += 1) if (active.has(line)) return true;
  return false;
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
  const widgets = [];
  const lines = [];

  for (const { from, to } of view.visibleRanges) {
    syntaxTree(state).iterate({
      from,
      to,
      enter: (node) => {
        if (node.name === "Frontmatter" || node.name === "HTMLBlock") {
          return false;
        }
        // Keep fenced code monospaced even when the surrounding prose is not.
        if (node.name === "FencedCode" || node.name === "CodeBlock") {
          const fence = fencedCodeSpec(state, node);
          const wrapped = !fence || wrapsCode(state, fence.openerFrom);
          if (fence) {
            // The code body remains native editable text. Language, fences
            // and copy controls should not turn into Markdown when it gains
            // focus: Source is the explicit place to edit that scaffolding.
            marks.push([node.from, fence.openerTo]);
            if (fence.closeFrom != null) marks.push([fence.closeFrom, fence.closeTo]);
            // The fenced node owns continuation QuoteMark children. Its early
            // return below deliberately skips inline parsing, so hide their
            // complete container prefixes here, including closing-fence rows.
            // Reuse Copy's prefix rules to retain indentation that is code.
            marks.push(...codeBodyPrefixRanges(state, fence));
            const locale =
              typeof document !== "undefined" && document.documentElement.lang.startsWith("fa")
                ? "fa"
                : "en";
            widgets.push({
              from: fence.openerTo,
              to: fence.openerTo,
              deco: Decoration.widget({
                widget: new CodeBlockHeaderWidget(fence, locale, state.readOnly, wrapped),
                side: 1,
              }),
            });
          }
          return false;
        }
        if (node.name === "BlockMath") {
          if (nodeIsActive(state, active, node)) return false;
          return;
        }
        // A definition line is metadata the author still edits, so it is
        // quieted rather than hidden: nothing on the page stands in for it.
        if (node.name === "LinkReference") {
          eachLine(state, node, (at) => lines.push({ at, deco: linkReferenceLine }));
          return;
        }
        if (node.name === "Blockquote") {
          const first = state.doc.lineAt(node.from);
          const callout = calloutMarkerAt(first.text);
          if (!callout) return;
          const { kind, marker } = callout;
          const from = first.from + marker[1].length;
          marks.push([
            from,
            from + marker[2].length + (marker[0].endsWith(" ") ? 1 : 0),
            Decoration.replace({ widget: new CalloutBadge(kind) }),
          ]);
          return;
        }
        if (headingLevel(node.name)) {
          const header = state.doc.lineAt(node.to);
          let folded = null;
          foldedRanges(state).between(header.to, header.to, (from, to) => {
            if (from === header.to) folded = { from, to };
          });
          const range = folded || foldable(state, header.from, header.to);
          if (range) {
            const locale =
              typeof document !== "undefined" && document.documentElement.lang.startsWith("fa")
                ? "fa"
                : "en";
            widgets.push({
              from: node.from,
              to: node.from,
              deco: Decoration.widget({
                widget: new SectionFoldWidget(range, Boolean(folded), locale),
                side: -1,
              }),
            });
          }
          // The `===` rule under a setext heading is collapsed by the block
          // field in live-widgets.mjs: replacing it takes a line break with
          // it, and a view plugin is not allowed to do that.
          // fall through: the HeaderMark inside still needs hiding
        }

        if (
          node.name === "InlineMath" &&
          state.facet(mathRenderer) &&
          node.to - node.from <= 16 * 1024
        ) {
          const editing = state.selection.ranges.some((range) =>
            range.empty
              ? range.from >= node.from && range.from <= node.to
              : range.from < node.to && range.to > node.from,
          );
          if (editing) return false;
          marks.push([
            node.from,
            node.to,
            Decoration.replace({
              widget: new MathWidget(
                state.doc.sliceString(node.from, node.to),
                node.from,
                node.to,
                false,
                state.facet(mathRenderer),
              ),
            }),
          ]);
          return false;
        }

        if (node.from === node.to) return;
        let stableCodeMarker = false;
        if (node.name === "QuoteMark" || node.name === "ListMark") {
          // An opening quote mark can be outside the fenced node. Unlike
          // prose syntax it must not reappear when the stable code header
          // gains the caret or enters a selection.
          const line = state.doc.lineAt(node.from);
          let context = syntaxTree(state).resolveInner(line.to, -1);
          while (context && context.name !== "FencedCode" && context.name !== "CodeBlock")
            context = context.parent;
          stableCodeMarker = Boolean(context);
          if (stableCodeMarker && node.name === "QuoteMark") {
            marks.push([node.from, swallowSpace(state, node.to)]);
            return;
          }
        }

        // An image and a task checkbox replace inline text, not a block, so
        // they are drawn here — over the viewport — rather than in the block
        // field, which has to walk the whole document to find anything.
        if (node.name === "Image") {
          const parsed = parseImage(state.doc.sliceString(node.from, node.to));
          const url = parsed ? state.facet(assetResolver)(parsed.src) : null;
          if (parsed) {
            marks.push([
              node.from,
              node.to,
              Decoration.replace({
                widget: /^(?:https?:)?\/\//i.test(parsed.src)
                  ? new OnlineImageWidget(
                      parsed.src,
                      parsed.alt,
                      Boolean(url),
                      state.facet(onlineImageRequest),
                      state.facet(editorStrings),
                    )
                  : url
                    ? new ImageWidget(
                        url,
                        parsed.alt,
                        parsed.src,
                        state.facet(editorStrings).imageNotFound,
                      )
                    : new ImagePlaceholderWidget(
                        parsed.src,
                        parsed.alt,
                        /^(?:https?:)?\/\//i.test(parsed.src)
                          ? state.facet(editorStrings).remoteImageNotLoaded
                          : state.facet(editorStrings).imageNotFound,
                      ),
              }),
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
          const to =
            node.name === "HeaderMark" || node.name === "QuoteMark" || node.name === "URL"
              ? swallowSpace(state, node.to)
              : node.to;
          marks.push([node.from, to]);
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
              /^\s*$/.test(state.doc.sliceString(state.doc.lineAt(node.from).from, node.from))
                ? state.doc.lineAt(node.from).from
                : node.from,
              swallowSpace(state, node.to),
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
            marks.push([
              node.from,
              node.to,
              Decoration.replace({
                widget: new EntityWidget(decoded),
              }),
            ]);
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
    for (let pos = from; pos <= to;) {
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
    for (let pos = from; pos <= to;) {
      const line = state.doc.lineAt(pos);
      lines.push({ at: line.from, deco: lineDirection(line.text) });
      // CodeMirror uses short, plain ASCII lines as samples of the default
      // font. Document has larger headings and smaller code rows, so sample
      // the editor's default styling instead of resetting the height map
      // whenever a differently sized line scrolls into view.
      if (/^[ -~]{1,20}$/.test(line.text)) {
        marks.push([line.from, line.to, documentTextRun]);
      }
      pos = line.to + 1;
    }
  }

  // A block widget owns its whole range; a line class or a hidden mark inside
  // it would have no tile to attach to.
  const blocks = blockWidgetRanges(state);
  const insideBlock = (at) => blocks.some(([from, to]) => at >= from && at < to);

  const events = [
    ...widgets.filter(({ from }) => !insideBlock(from)),
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
  ].sort((a, b) => a.from - b.from || a.deco.startSide - b.deco.startSide);

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
      this.bidiIsolates = this.decorations.update({
        filter: (_from, _to, value) => value.spec.bidiIsolate !== undefined,
      });
      this.atomicRanges = this.decorations.update({
        filter: (_from, _to, value) => Boolean(value.spec.widget || value.spec.mardasAtomic),
      });
    }

    update(update) {
      if (
        update.docChanged ||
        update.viewportChanged ||
        update.selectionSet ||
        update.transactions.some((transaction) =>
          transaction.effects.some(
            (effect) => effect.is(setCodeWrap) || effect.is(foldEffect) || effect.is(unfoldEffect),
          ),
        ) ||
        update.startState.readOnly !== update.state.readOnly ||
        syntaxTree(update.startState) !== syntaxTree(update.state) ||
        update.startState.facet(assetResolver) !== update.state.facet(assetResolver) ||
        update.startState.facet(mathRenderer) !== update.state.facet(mathRenderer) ||
        update.startState.facet(editorStrings) !== update.state.facet(editorStrings)
      ) {
        this.decorations = buildDecorations(update.view);
        this.bidiIsolates = this.decorations.update({
          filter: (_from, _to, value) => value.spec.bidiIsolate !== undefined,
        });
        this.atomicRanges = this.decorations.update({
          filter: (_from, _to, value) => Boolean(value.spec.widget || value.spec.mardasAtomic),
        });
      }
    }
  },
  {
    decorations: (plugin) => plugin.decorations,
    // Hidden marks must not be enterable by the caret, or arrow keys appear to
    // stall on characters that are not on screen.
    provide: (plugin) => [
      EditorView.atomicRanges.of((view) => view.plugin(plugin)?.atomicRanges ?? Decoration.none),
      EditorView.bidiIsolatedRanges.of(
        (view) => view.plugin(plugin)?.bidiIsolates ?? Decoration.none,
      ),
    ],
  },
);

const sourceBlockLtr = Decoration.line({
  class: "cm-source-block-ltr",
  attributes: { dir: "ltr" },
});
const sourceBlockRtl = Decoration.line({
  class: "cm-source-block-rtl",
  attributes: { dir: "rtl" },
});

/**
 * Structural source lines belong to their block, not the interface language.
 *
 * An English table's neutral separator used to inherit a Persian workbench's
 * direction while its header and cells resolved themselves as LTR. Closing
 * code fences did the same. Decide table direction from its content once and
 * keep code syntax LTR, as the live editor already does. This changes only line
 * presentation: fences, whitespace and cursor offsets remain raw Markdown.
 * Only visible lines receive decorations, even when a code block is very long.
 */
export function sourceBlockDirections(state, visibleRanges) {
  const directions = new Map();
  for (const { from, to } of visibleRanges) {
    syntaxTree(state).iterate({
      from,
      to,
      enter(node) {
        const code = node.name === "FencedCode" || node.name === "CodeBlock";
        if (!code && node.name !== "Table") return;
        const direction = code
          ? "ltr"
          : tableContentDirection(state.doc.sliceString(node.from, node.to));
        const first = state.doc.lineAt(Math.max(from, node.from)).number;
        const last = state.doc.lineAt(Math.min(to, node.to)).number;
        for (let number = first; number <= last; number += 1) {
          directions.set(state.doc.line(number).from, direction);
        }
        return false;
      },
    });
  }
  return directions;
}

/** Source mode keeps raw text with line- and block-aware bidi measurement. */
const autoDirectionPlugin = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.decorations = this.build(view);
    }

    update(update) {
      if (
        update.docChanged ||
        update.viewportChanged ||
        syntaxTree(update.startState) !== syntaxTree(update.state)
      ) {
        this.decorations = this.build(update.view);
      }
    }

    build(view) {
      const builder = new RangeSetBuilder();
      const blocks = sourceBlockDirections(view.state, view.visibleRanges);
      for (const { from, to } of view.visibleRanges) {
        for (let pos = from; pos <= to;) {
          const line = view.state.doc.lineAt(pos);
          const direction = blocks.get(line.from);
          builder.add(
            line.from,
            line.from,
            direction === "ltr"
              ? sourceBlockLtr
              : direction === "rtl"
                ? sourceBlockRtl
                : lineDirection(line.text),
          );
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
export function editorModeExtension(
  mode,
  { resolveAsset, requestOnlineImage, strings, renderMath, renderDiagram } = {},
) {
  const perLineDirection = EditorView.perLineTextDirection.of(true);
  return normalizeEditorMode(mode) === "live"
    ? [
        createBlockWidgetField(),
        assetResolver.of(resolveAsset || (() => null)),
        onlineImageRequest.of(requestOnlineImage || null),
        editorStrings.of(strings || {}),
        mathRenderer.of(typeof renderMath === "function" ? renderMath : null),
        livePreviewPlugin,
        tableEditingExtension(),
        diagramRenderer.of(renderDiagram || null),
        blockDragExtension,
        perLineDirection,
      ]
    : [sourceGutterDirection, autoDirectionPlugin, perLineDirection];
}
