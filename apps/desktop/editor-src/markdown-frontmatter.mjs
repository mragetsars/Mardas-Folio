/**
 * YAML front matter support for the Markdown editor.
 *
 * `@lezer/markdown` has no front matter rule, so a leading `---` fence is
 * parsed as a thematic break and every metadata line below it becomes a setext
 * heading.  That is why an ordinary document header rendered as bold underlined
 * text instead of metadata.
 *
 * The recognition rules below deliberately mirror `FRONTMATTER_RE` in
 * `src/mardas_folio/markdown.py` so the editor and the publishing engine never
 * disagree about what counts as front matter:
 *
 *   - the opening fence is `---` on the very first line of the document;
 *   - the closing fence is `---` on its own line, never `...`;
 *   - at least one line must sit between the fences, so `---\n---` stays two
 *     thematic breaks exactly as the engine treats it;
 *   - the first candidate closing fence wins, matching the engine's non-greedy
 *     match.
 *
 * An unterminated opening fence must stay a thematic break, so the closing
 * fence is located with a non-consuming look-ahead before any line is taken.
 */
import { styleTags, tags } from "@lezer/highlight";

const FENCE = /^---[ \t]*$/;
const ENTRY = /^([ \t]*)([A-Za-z_$][\w.$-]*)([ \t]*:)(.*)$/;
const COMMENT = /^[ \t]*#/;

/** Front matter blocks are small; this bounds look-ahead on pathological input. */
const MAX_SCAN_LINES = 512;

/** The closing fence can never be the line directly after the opening fence. */
const FIRST_CLOSING_LINE = 2;

/**
 * Report whether a closing fence exists without consuming any line.
 *
 * Block parsers cannot backtrack, so the scan runs over raw line text ahead of
 * the parse position and only then does the caller commit to the block.
 */
function hasClosingFence(cx) {
  let position = cx.absoluteLineEnd + 1;
  for (let index = 1; index <= MAX_SCAN_LINES && position <= cx.to; index += 1) {
    const scanned = cx.scanLine(position);
    if (index >= FIRST_CLOSING_LINE && FENCE.test(scanned.text)) return true;
    position = scanned.end + 1;
  }
  return false;
}

/** Emit `key: value`, comment, or bare-value children for one metadata line. */
function collectLine(cx, children, start, text) {
  if (!text.trim()) return;

  if (COMMENT.test(text)) {
    children.push(
      cx.elt("FrontmatterComment", start + text.indexOf("#"), start + text.trimEnd().length),
    );
    return;
  }

  const entry = ENTRY.exec(text);
  if (!entry) {
    const from = start + (text.length - text.trimStart().length);
    const to = start + text.trimEnd().length;
    if (to > from) children.push(cx.elt("FrontmatterValue", from, to));
    return;
  }

  const [, indent, key, separator, rest] = entry;
  let at = start + indent.length;
  children.push(cx.elt("FrontmatterKey", at, at + key.length));
  at += key.length;
  children.push(cx.elt("FrontmatterSeparator", at, at + separator.length));
  at += separator.length;

  const from = at + (rest.length - rest.trimStart().length);
  const to = start + text.trimEnd().length;
  if (to > from) children.push(cx.elt("FrontmatterValue", from, to));
}

/**
 * A `MarkdownConfig` that parses leading YAML front matter as its own block.
 *
 * It runs before `HorizontalRule` so the opening fence is claimed here first,
 * and falls through untouched when the document has no front matter.
 */
export const frontmatter = {
  defineNodes: [
    { name: "Frontmatter", block: true },
    "FrontmatterMark",
    "FrontmatterKey",
    "FrontmatterSeparator",
    "FrontmatterValue",
    "FrontmatterComment",
  ],
  parseBlock: [
    {
      name: "Frontmatter",
      before: "HorizontalRule",
      parse(cx, line) {
        if (cx.lineStart !== 0 || !FENCE.test(line.text)) return false;
        if (!hasClosingFence(cx)) return false;

        const from = cx.lineStart;
        const children = [cx.elt("FrontmatterMark", from, from + 3)];
        let to = from + 3;

        for (let index = 1; cx.nextLine(); index += 1) {
          const start = cx.lineStart;
          const { text } = line;
          if (index >= FIRST_CLOSING_LINE && FENCE.test(text)) {
            children.push(cx.elt("FrontmatterMark", start, start + 3));
            to = start + text.length;
            cx.nextLine();
            break;
          }
          collectLine(cx, children, start, text);
          to = start + text.length;
        }

        cx.addElement(cx.elt("Frontmatter", from, to, children));
        return true;
      },
    },
  ],
  props: [
    styleTags({
      FrontmatterMark: tags.processingInstruction,
      FrontmatterKey: tags.propertyName,
      FrontmatterSeparator: tags.separator,
      FrontmatterValue: tags.string,
      FrontmatterComment: tags.lineComment,
    }),
  ],
};
