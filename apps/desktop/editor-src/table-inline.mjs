/** Render parsed inline Markdown using DOM nodes, never user HTML. */
const tags = {
  StrongEmphasis: "strong",
  Emphasis: "em",
  Strikethrough: "s",
  Subscript: "sub",
  Superscript: "sup",
};
const marks = new Set([
  "EmphasisMark",
  "StrikethroughMark",
  "SubscriptMark",
  "SuperscriptMark",
  "CodeMark",
  "LinkMark",
  "LinkTitle",
]);

function text(parent, value) {
  if (value) parent.append(document.createTextNode(value));
}

export function appendTableInline(parent, node, source, options = {}) {
  const slice = (from, to) =>
    source.slice(from - (options.offset || 0), to - (options.offset || 0));
  const start = Math.max(node.from, options.contentFrom ?? node.from);
  if (!node.firstChild) {
    parent.textContent = slice(start, node.to);
    return;
  }
  let cursor = start;
  for (let child = node.firstChild; child; child = child.nextSibling) {
    if (child.to <= start) continue;
    text(parent, slice(cursor, child.from));
    const raw = slice(child.from, child.to);
    if (tags[child.name]) {
      const element = document.createElement(tags[child.name]);
      appendTableInline(element, child, source, options);
      parent.append(element);
    } else if (child.name === "InlineCode") {
      const code = document.createElement("code");
      code.className = "cm-md-inline-code";
      const first = child.firstChild,
        last = child.lastChild;
      let value = slice(first.to, last.from).replace(/\r?\n/g, " ");
      if (/^ .* $/.test(value) && /[^ ]/.test(value)) value = value.slice(1, -1);
      code.textContent = value.replace(/\\\|/g, "|");
      parent.append(code);
    } else if (child.name === "Link" || child.name === "Image" || child.name === "Autolink") {
      // A writing surface must not launch an external app when clicked.
      const label = document.createElement("span");
      label.className = child.name === "Image" ? "cm-md-table-image-label" : "cm-md-live-link";
      appendTableInline(label, child, source, options);
      parent.append(label);
    } else if (child.name === "InlineMath" && options.renderMathNode && raw.length <= 16 * 1024) {
      parent.append(options.renderMathNode(child));
    } else if (
      options.preserveSource &&
      (child.name === "InlineMath" || (child.name === "HTMLTag" && !/^<br\s*\/?>$/i.test(raw)))
    ) {
      const element = document.createElement("span");
      element.className = "cm-md-inline-code";
      element.textContent =
        child.name === "InlineMath"
          ? raw.replace(/^\$|\$$/g, "")
          : document.documentElement.lang === "fa"
            ? "عنصر HTML"
            : "HTML element";
      parent.append(element);
    } else if (child.name === "URL") {
      if (node.name !== "Link" && node.name !== "Image") text(parent, raw);
    } else if (child.name === "HTMLTag" && /^<br\s*\/?>$/i.test(raw))
      parent.append(document.createElement("br"));
    else if (child.name === "Escape") text(parent, raw.slice(1));
    else if (child.name === "Entity" && /^&(?:#\d+|#x[\da-f]+|[a-z][\da-z]+);$/i.test(raw)) {
      // The grammar guarantees a single entity; this cannot contain a tag.
      const decoder = document.createElement("textarea");
      decoder.innerHTML = raw;
      text(parent, decoder.value);
    } else if (!marks.has(child.name)) text(parent, raw);
    if (
      options.preserveSource &&
      ["Link", "Image", "Autolink", "InlineMath", "HTMLTag"].includes(child.name)
    ) {
      const element = parent.lastChild;
      if (element?.nodeType === 1 && element.localName !== "br") {
        element.dataset.tableSource = raw;
        element.contentEditable = "false";
      }
    }
    cursor = child.to;
  }
  text(parent, slice(cursor, node.to));
}

export function tableInlineText(node) {
  if (node.nodeType === 3) return node.nodeValue;
  if (node.localName === "br") return "\n";
  return Array.from(node.childNodes, tableInlineText).join("");
}

/** Serialize only the inline formatting the visual cell editor supports. */
export function tableInlineSource(node) {
  if (node.nodeType === 3) {
    return node.nodeValue.replace(/\u00a0/g, " ").replace(/[\\*_`[\]~<>$&]/g, "\\$&");
  }
  if (node.nodeType !== 1) return "";
  if (node.dataset.tableSource) return node.dataset.tableSource;
  if (node.localName === "br") return "\n";
  if (node.localName === "code") {
    const value = node.textContent;
    if (!value) return "";
    const ticks = "`".repeat(
      Math.max(0, ...(value.match(/`+/g) || []).map((part) => part.length)) + 1,
    );
    const padding = /^`|`$|^ .* $/.test(value) ? " " : "";
    return ticks + padding + value + padding + ticks;
  }
  const value = Array.from(node.childNodes, tableInlineSource).join("");
  if (node.localName === "div" && !node.classList.contains("cm-table-cell-input")) {
    return (node.previousSibling ? "\n" : "") + value;
  }
  const marker = {
    b: "**",
    strong: "**",
    i: "*",
    em: "*",
    s: "~~",
    strike: "~~",
    sub: "~",
    sup: "^",
  }[node.localName];
  return marker && value ? marker + value + marker : value;
}
