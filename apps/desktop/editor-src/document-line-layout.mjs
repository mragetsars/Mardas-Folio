import { Decoration } from "@codemirror/view";
import { codeRowAttributes, fencedCodeSpec, wrapsCode } from "./code-block-tools.mjs";

const headings = new Map();
const callouts = new Map();
const quotes = new Map();
const lists = new Map();
const codeRows = new Map();
const paragraph = Decoration.line({ class: "cm-md-prose" });
const paragraphContinuation = Decoration.line({ class: "cm-md-prose cm-md-prose-continuation" });
const math = Decoration.line({ class: "cm-md-math-block" });
const rtlBlock = Decoration.line({ class: "cm-md-block-rtl" });

export const CALLOUT_KINDS = new Set([
  "note",
  "tip",
  "important",
  "warning",
  "caution",
  "info",
  "success",
  "question",
  "failure",
  "danger",
  "bug",
  "example",
  "quote",
  "abstract",
]);
const calloutMarker = /^(\s*>\s*)(\[!([A-Za-z][A-Za-z0-9_-]*)\][+-]?)\s?/;

export function calloutMarkerAt(text) {
  const marker = calloutMarker.exec(text);
  const kind = marker?.[3].toLowerCase();
  return CALLOUT_KINDS.has(kind) ? { marker, kind } : null;
}

export function headingLevel(nodeName) {
  return Number(/^(?:ATX|Setext)Heading([1-6])$/.exec(nodeName)?.[1]) || 0;
}

function layout(cache, key, spec) {
  if (!cache.has(key)) cache.set(key, Decoration.line(spec));
  return cache.get(key);
}

export function eachLine(state, node, callback) {
  const first = state.doc.lineAt(node.from).number;
  const last = state.doc.lineAt(node.to).number;
  for (let line = first; line <= last; line += 1)
    callback(state.doc.line(line).from, line === first, line === last);
}

function listDepth(node) {
  let depth = -1;
  for (let current = node.node; current; current = current.parent)
    if (current.name === "BulletList" || current.name === "OrderedList") depth += 1;
  return Math.max(depth, 0);
}

function codeRow(state, fence, at, first, last) {
  let cls = "cm-code-line";
  if (first) cls += fence ? " cm-code-open" : " cm-code-indented-open";
  if (last) {
    if (!fence) cls += " cm-code-indented-close";
    else if (fence.closeFrom == null) cls += " cm-code-unclosed-end";
    else if (!first) cls += " cm-code-close";
  }
  const info = fence && codeRowAttributes(state, fence, at);
  if (info?.number) cls += " cm-code-numbered";
  if (info?.highlighted) cls += " cm-code-highlighted";
  if (info?.added) cls += " cm-code-added";
  if (info?.removed) cls += " cm-code-removed";
  if (fence && at >= fence.bodyFrom && at < fence.bodyTo && !wrapsCode(state, fence.openerFrom))
    cls += " cm-code-nowrap";
  return info?.number
    ? Decoration.line({ class: cls, attributes: { "data-code-line": info.number } })
    : layout(codeRows, cls, { class: cls });
}

export function documentLineLayout(state, node, add) {
  const level = headingLevel(node.name);
  if (level) {
    add(
      state.doc.lineAt(node.from).from,
      layout(headings, level, { class: "cm-md-heading cm-md-h" + level }),
    );
  } else if (node.name === "Paragraph") {
    eachLine(state, node, (at, _first, last) => {
      const continuation = !last && !/(?: {2,}|\\)$/.test(state.doc.lineAt(at).text);
      add(at, continuation ? paragraphContinuation : paragraph);
    });
  } else if (node.name === "ListItem") {
    const depth = Math.min(6, listDepth(node));
    const first = state.doc.lineAt(node.from).from;
    const marker = state.doc.sliceString(node.from, Math.min(node.to, node.from + 24));
    const unordered = node.node.parent?.name === "BulletList";
    const task = /^[-+*]\s+\[[ xX]\]/.test(marker);
    const kind = unordered && !task ? "bullet" : task ? "task" : "ordered";
    eachLine(state, node, (at) => {
      const head = at === first;
      add(
        at,
        layout(lists, depth + ":" + kind + ":" + head, {
          class: "cm-md-list-line" + (head ? " cm-md-list-head cm-md-list-" + kind : ""),
          attributes: { "data-list-depth": String(depth), style: "--list-depth:" + depth },
        }),
      );
    });
  } else if (node.name === "FencedCode" || node.name === "CodeBlock") {
    const fence = fencedCodeSpec(state, node);
    eachLine(state, node, (at, first, last) => add(at, codeRow(state, fence, at, first, last)));
  } else if (node.name === "BlockMath") {
    eachLine(state, node, (at) => add(at, math));
  } else if (node.name === "Blockquote") {
    const first = state.doc.lineAt(node.from);
    const callout = calloutMarkerAt(first.text);
    const text = state.doc.sliceString(
      callout ? first.from + callout.marker[0].length : node.from,
      node.to,
    );
    const rtl = /[\u0591-\u08ff\uFB1D-\uFDFF\uFE70-\uFEFF]/.test(
      text.match(/[A-Za-zÀ-˿Ͱ-֏֑-ࣿיִ-﷽ﹰ-ﻼ]/)?.[0] || "",
    );
    eachLine(state, node, (at, head, tail) => {
      if (callout) {
        const cls =
          "cm-md-callout cm-md-callout-" +
          callout.kind +
          (head ? " cm-md-callout-head" : "") +
          (tail ? " cm-md-callout-tail" : "");
        add(at, layout(callouts, cls, { class: cls }));
      } else {
        const markers = /^(?:\s*>)+/.exec(state.doc.lineAt(at).text);
        const depth = Math.min(4, (markers?.[0].match(/>/g) || [">"]).length);
        add(at, layout(quotes, depth, { class: "cm-quote-line cm-quote-depth-" + depth }));
      }
      if (rtl) add(at, rtlBlock);
    });
  }
}
