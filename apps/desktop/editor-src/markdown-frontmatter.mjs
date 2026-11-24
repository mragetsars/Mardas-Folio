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
import { yamlLanguage } from "@codemirror/lang-yaml";
import { parseFrontMatter } from "../frontend/js/core/markdown-analysis.mjs";

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

/** Editable YAML leaves with exact source ranges. Unknown YAML constructs stay intact. */
export function visualMetadataFields(markup) {
  const opening = /^---[ \t]*\r?\n/.exec(markup);
  const closing = /\r?\n---[ \t]*$/.exec(markup);
  if (!opening || !closing) return [];
  const offset = opening[0].length;
  const source = markup.slice(offset, closing.index);
  const root = yamlLanguage.parser
    .parse(source)
    .topNode.getChild("Document")
    ?.getChild("BlockMapping");
  if (!root) return [];
  const { fields: simple } = parseFrontMatter(markup);
  const fields = [];
  const slice = (node) => source.slice(node.from, node.to);
  function visit(node, path) {
    if (node.name === "Pair") {
      const key = node.getChild("Key");
      const value = node.lastChild;
      if (!key || !value || value === key || value.name === ":") return;
      const name = slice(key).replace(/^(['"])(.*)\1$/, "$2");
      visit(value, [...path, name]);
    } else if (node.name === "BlockMapping" || node.name === "FlowMapping") {
      for (const pair of node.getChildren("Pair")) visit(pair, path);
    } else if (node.name === "BlockSequence") {
      node.getChildren("Item").forEach((item, index) => {
        if (item.firstChild) visit(item.firstChild, [...path, String(index + 1)]);
      });
    } else if (node.name === "FlowSequence") {
      const parts = [];
      for (let child = node.firstChild; child; child = child.nextSibling) {
        if (!["[", "]", ",", "LineComment"].includes(child.name)) parts.push(child);
      }
      parts.forEach((value, index) => visit(value, [...path, String(index + 1)]));
    } else {
      const raw = slice(node);
      let value;
      let kind = "text";
      if (node.name === "QuotedLiteral" && !raw.includes("\n")) {
        if (raw.startsWith("'")) value = raw.slice(1, -1).replaceAll("''", "'");
        else {
          try {
            value = JSON.parse(raw);
          } catch {
            return;
          }
        }
      } else if (node.name === "Literal" && !/[\r\n]/.test(raw) && !/^(null|~)$/i.test(raw)) {
        if (/^(true|false|yes|no|on|off)$/i.test(raw)) {
          kind = "checkbox";
          value = /^(true|yes|on)$/i.test(raw);
        } else if (/^[+-]?(?:\d+|\d+\.\d+)$/.test(raw)) {
          value = raw;
          kind = "number";
        } else {
          value = raw;
          if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) kind = "date";
        }
      } else if (
        node.name === "BlockLiteral" &&
        path.length === 1 &&
        typeof simple[path[0]] === "string"
      ) {
        value = simple[path[0]];
        kind = "multiline";
      }
      if (value === undefined) return;
      fields.push({ path, value, kind, from: offset + node.from, to: offset + node.to });
    }
  }
  visit(root, []);
  return fields;
}

export function updateVisualMetadata(markup, fields, values) {
  let result = markup;
  for (let index = fields.length - 1; index >= 0; index -= 1) {
    const { from, to, value, kind } = fields[index];
    const next = values[index];
    if (next === value) continue;
    const insert =
      kind === "checkbox" || (kind === "number" && next !== "") || (kind === "date" && next)
        ? String(next)
        : JSON.stringify(next);
    result = result.slice(0, from) + insert + result.slice(to);
  }
  return result;
}
