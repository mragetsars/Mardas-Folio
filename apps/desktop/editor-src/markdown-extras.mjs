/**
 * Math and footnotes for the Markdown editor.
 *
 * `@lezer/markdown` parses CommonMark and GFM. The publishing engine accepts
 * more than that: `$x$` and `$$…$$` become MathJax, and `[^id]` becomes a
 * numbered footnote. Without a rule for either, the editor showed them as
 * literal source — `$E = mc^2$` sat in the middle of a sentence as six
 * characters of punctuation, and a footnote reference rendered as `^1` because
 * the surrounding brackets were hidden as link marks while the caret was
 * elsewhere, which is worse than leaving it alone.
 *
 * The recognition rules deliberately mirror `src/mardas_folio/markdown.py` so
 * the editor and the engine never disagree about what is math:
 *
 *   INLINE_MATH_RE       `(?<!\\)\$(?![\s$])(.+?)(?<!\\)\$(?!\d)`
 *   DISPLAY_MATH_FENCE_RE `^\s*\$\$\s*$`
 *   INLINE_FOOTNOTE_RE   `\[\^([^\]]+)\]`
 *   FOOTNOTE_DEF_RE      `^\[\^([^\]]+)\]:\s*(.*)$`
 *
 * In particular `$5 and $7` is not math — the engine's negative look-ahead on
 * a digit after the closing `$` exists so prices in prose survive, and the
 * same look-ahead is applied here.
 */
import { styleTags, tags } from "@lezer/highlight";

const DOLLAR = 36;
const BACKSLASH = 92;
const OPEN_BRACKET = 91;
const CARET = 94;
const CLOSE_BRACKET = 93;
const COLON = 58;

const DISPLAY_FENCE = /^\s*\$\$\s*$/;

/** Display math blocks are short; this bounds look-ahead on pathological input. */
const MAX_SCAN_LINES = 512;

function isSpace(code) {
  return code === 32 || code === 9 || code === 10 || code === 13;
}

function isDigit(code) {
  return code >= 48 && code <= 57;
}

/**
 * Report whether a closing `$$` fence exists without consuming any line.
 *
 * Block parsers cannot backtrack, so an unterminated `$$` has to stay an
 * ordinary paragraph rather than swallowing the rest of the document.
 */
function hasClosingFence(cx) {
  let position = cx.absoluteLineEnd + 1;
  for (let index = 0; index < MAX_SCAN_LINES && position <= cx.to; index += 1) {
    const scanned = cx.scanLine(position);
    if (DISPLAY_FENCE.test(scanned.text)) return true;
    position = scanned.end + 1;
  }
  return false;
}

/**
 * `$…$` inside a line.
 *
 * Runs before `Escape` so a `\$` inside the span is not consumed as an escape
 * before the closing delimiter is found, and the opening `$` of a span that
 * turns out to be unterminated is handed back untouched.
 */
const inlineMath = {
  name: "InlineMath",
  before: "Escape",
  parse(cx, next, pos) {
    if (next !== DOLLAR) return -1;
    // `$$` on its own is a display fence, not the start of an inline span.
    if (cx.char(pos + 1) === DOLLAR) return -1;
    // A backslash before the delimiter escapes it.
    if (pos > cx.offset && cx.char(pos - 1) === BACKSLASH) return -1;
    // `$ x$` is a dollar sign followed by prose, not a formula.
    const first = cx.char(pos + 1);
    if (first < 0 || isSpace(first) || first === DOLLAR) return -1;

    for (let at = pos + 1; at < cx.end; at += 1) {
      const code = cx.char(at);
      if (code === 10) break; // inline math never spans a line
      if (code !== DOLLAR) continue;
      if (cx.char(at - 1) === BACKSLASH) continue;
      // `$12 and $15` — a digit after the closing delimiter means these were
      // two amounts of money, not one formula.
      if (isDigit(cx.char(at + 1))) continue;
      if (at === pos + 1) return -1;
      return cx.addElement(
        cx.elt("InlineMath", pos, at + 1, [
          cx.elt("MathMark", pos, pos + 1),
          cx.elt("MathText", pos + 1, at),
          cx.elt("MathMark", at, at + 1),
        ]),
      );
    }
    return -1;
  },
};

/**
 * `[^id]` — a footnote reference.
 *
 * Runs before `Link` so the brackets are claimed here instead of being parsed
 * as a link label whose marks are then hidden, which is what left a bare `^1`
 * in the text.
 */
const footnoteReference = {
  name: "FootnoteReference",
  before: "Link",
  parse(cx, next, pos) {
    if (next !== OPEN_BRACKET || cx.char(pos + 1) !== CARET) return -1;
    for (let at = pos + 2; at < cx.end; at += 1) {
      const code = cx.char(at);
      if (code === 10 || code === OPEN_BRACKET) return -1;
      if (code !== CLOSE_BRACKET) continue;
      if (at === pos + 2) return -1;
      // `[^id]:` at the start of a line is a definition, not a reference; it
      // is styled as a whole line instead so its label stays legible.
      if (cx.char(at + 1) === COLON) return -1;
      return cx.addElement(
        cx.elt("FootnoteReference", pos, at + 1, [
          cx.elt("FootnoteMark", pos, pos + 2),
          cx.elt("FootnoteLabel", pos + 2, at),
          cx.elt("FootnoteMark", at, at + 1),
        ]),
      );
    }
    return -1;
  },
};

/** `$$` … `$$` on lines of their own. */
const blockMath = {
  name: "BlockMath",
  before: "HorizontalRule",
  parse(cx, line) {
    if (!DISPLAY_FENCE.test(line.text)) return false;
    if (!hasClosingFence(cx)) return false;

    const from = cx.lineStart;
    const open = from + line.text.length;
    const children = [cx.elt("MathMark", from + line.text.indexOf("$$"), open)];
    let to = open;

    while (cx.nextLine()) {
      const start = cx.lineStart;
      const { text } = line;
      if (DISPLAY_FENCE.test(text)) {
        const mark = start + text.indexOf("$$");
        children.push(cx.elt("MathMark", mark, mark + 2));
        to = start + text.length;
        cx.nextLine();
        break;
      }
      if (text.trim()) children.push(cx.elt("MathText", start, start + text.length));
      to = start + text.length;
    }

    cx.addElement(cx.elt("BlockMath", from, to, children));
    return true;
  },
};

/**
 * A `MarkdownConfig` adding the engine's math and footnote spellings.
 */
export const mathAndFootnotes = {
  defineNodes: [
    { name: "BlockMath", block: true },
    "InlineMath",
    "MathMark",
    "MathText",
    "FootnoteReference",
    "FootnoteMark",
    "FootnoteLabel",
  ],
  parseBlock: [blockMath],
  parseInline: [inlineMath, footnoteReference],
  props: [
    styleTags({
      MathMark: tags.processingInstruction,
      MathText: tags.special(tags.variableName),
      FootnoteMark: tags.processingInstruction,
      FootnoteLabel: tags.labelName,
    }),
  ],
};
