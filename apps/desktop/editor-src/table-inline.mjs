/** Render parsed inline Markdown using DOM nodes, never user HTML. */
const tags = { StrongEmphasis: 'strong', Emphasis: 'em', Strikethrough: 's', Subscript: 'sub', Superscript: 'sup' };
const marks = new Set(['EmphasisMark', 'StrikethroughMark', 'SubscriptMark', 'SuperscriptMark', 'CodeMark', 'LinkMark', 'LinkTitle']);

function text(parent, value) { if (value) parent.append(document.createTextNode(value)); }

export function appendTableInline(parent, node, source, options = {}) {
  const slice = (from, to) => source.slice(from - (options.offset || 0), to - (options.offset || 0));
  if (!node.firstChild) { parent.textContent = slice(node.from, node.to); return; }
  let cursor = node.from;
  for (let child = node.firstChild; child; child = child.nextSibling) {
    text(parent, slice(cursor, child.from));
    const raw = slice(child.from, child.to);
    if (tags[child.name]) {
      const element = document.createElement(tags[child.name]);
      appendTableInline(element, child, source, options);
      parent.append(element);
    } else if (child.name === 'InlineCode') {
      const code = document.createElement('code');
      code.className = 'cm-md-inline-code';
      const first = child.firstChild, last = child.lastChild;
      let value = slice(first.to, last.from).replace(/\r?\n/g, ' ');
      if (/^ .* $/.test(value) && /[^ ]/.test(value)) value = value.slice(1, -1);
      code.textContent = value.replace(/\\\|/g, '|');
      parent.append(code);
    } else if (child.name === 'Link' || child.name === 'Image' || child.name === 'Autolink') {
      // A writing surface must not launch an external app when clicked.
      const label = document.createElement('span');
      label.className = child.name === 'Image' ? 'cm-md-table-image-label' : 'cm-md-live-link';
      appendTableInline(label, child, source, options);
      parent.append(label);
    } else if (child.name === 'InlineMath' && options.renderMathNode && raw.length <= 16 * 1024) {
      parent.append(options.renderMathNode(child));
    } else if (child.name === 'URL') {
      if (node.name !== 'Link' && node.name !== 'Image') text(parent, raw);
    } else if (child.name === 'Escape') text(parent, raw.slice(1));
    else if (child.name === 'Entity' && /^&(?:#\d+|#x[\da-f]+|[a-z][\da-z]+);$/i.test(raw)) {
      // The grammar guarantees a single entity; this cannot contain a tag.
      const decoder = document.createElement('textarea');
      decoder.innerHTML = raw;
      text(parent, decoder.value);
    } else if (!marks.has(child.name)) text(parent, raw);
    cursor = child.to;
  }
  text(parent, slice(cursor, node.to));
}
