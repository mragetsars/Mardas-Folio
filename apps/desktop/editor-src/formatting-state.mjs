/** The formatting represented by a real Markdown selection, never DOM styles. */
import { syntaxTree } from "@codemirror/language";

const INLINE_NODES = Object.freeze({
  StrongEmphasis: "bold",
  Emphasis: "italic",
  Strikethrough: "strike",
  InlineCode: "code",
  Link: "link",
});

function rangeFormatting(state, range) {
  const result = {
    bold: false, italic: false, strike: false, code: false, link: false,
    heading: 0, "bullet-list": false, "ordered-list": false,
    "task-list": false, quote: false, "code-block": false,
  };
  let listItem = null;
  let listSeen = false;
  for (let node = syntaxTree(state).resolveInner(range.from, 1); node; node = node.parent) {
    const contains = node.from <= range.from && node.to >= range.to;
    const inside = range.empty ? node.from < range.from && range.from < node.to : contains;
    if (!contains) continue;
    const inline = INLINE_NODES[node.name];
    if (inline && inside) result[inline] = true;
    const heading = /^(?:ATXHeading|SetextHeading)([1-6])$/.exec(node.name);
    if (heading) result.heading = Number(heading[1]);
    if (node.name === "ListItem" && !listItem) listItem = node;
    if (!listSeen && (node.name === "BulletList" || node.name === "OrderedList")) {
      result["task-list"] = Boolean(listItem?.getChild("Task"));
      result["bullet-list"] = node.name === "BulletList" && !result["task-list"];
      result["ordered-list"] = node.name === "OrderedList";
      listSeen = true;
    }
    if (node.name === "Blockquote") result.quote = true;
    if (node.name === "FencedCode" || node.name === "CodeBlock") result["code-block"] = true;
  }
  return result;
}

export function markdownFormattingState(state) {
  const states = state.selection.ranges.map((range) => rangeFormatting(state, range));
  const result = { ...states[0] };
  for (const key of Object.keys(result)) {
    if (!states.every((value) => value[key] === result[key])) result[key] = key === "heading" ? 0 : false;
  }
  for (let level = 1; level <= 6; level += 1) result[`heading-${level}`] = result.heading === level;
  return result;
}
