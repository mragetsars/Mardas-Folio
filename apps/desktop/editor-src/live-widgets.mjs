/**
 * Block widgets for live preview.
 *
 * Hiding syntax marks gets prose to read correctly, but a table written as
 * pipes still looks like pipes and `---` still looks like three hyphens. These
 * widgets replace whole blocks with the thing they describe, which is the step
 * that makes the editor read as a document rather than as marked-up text.
 *
 * They are provided from a `StateField`, not a `ViewPlugin`: CodeMirror rejects
 * block decorations from plugins outright ("Block decorations may not be
 * specified via plugins"). A field has no viewport to narrow the work to, so
 * the scan covers the whole document and is skipped past a size bound.
 *
 * Every widget disappears the moment the caret enters its lines, handing the
 * raw Markdown back for editing. The document is never rewritten to match what
 * is drawn; the one exception is the task checkbox, which is a control the user
 * clicks, and which edits exactly the characters between its brackets.
 */
import { RangeSetBuilder, StateField } from "@codemirror/state";
import { Decoration, EditorView, WidgetType } from "@codemirror/view";
import { syntaxTree } from "@codemirror/language";

/**
 * Documents past this size skip block rendering.
 *
 * A state field cannot limit itself to the viewport, so the cost is
 * proportional to the whole document on every edit. Prose documents are far
 * below this; a generated file that is not really being read stays responsive.
 */
const MAX_SCANNED_CHARS = 200_000;

/** Split a table row into cells, honouring escaped pipes. */
function splitRow(line) {
  const trimmed = line.replace(/^\s*\|/, "").replace(/\|\s*$/, "");
  const cells = [];
  let current = "";
  for (let index = 0; index < trimmed.length; index += 1) {
    const character = trimmed[index];
    if (character === "\\" && trimmed[index + 1] === "|") {
      current += "|";
      index += 1;
      continue;
    }
    if (character === "|") {
      cells.push(current);
      current = "";
      continue;
    }
    current += character;
  }
  cells.push(current);
  return cells.map((cell) => cell.trim());
}

const isAlignmentRow = (cells) => cells.every((cell) => /^:?-{1,}:?$/.test(cell.trim()));

/**
 * A rendered GitHub table.
 *
 * The cells are deliberately not `contenteditable`. Nesting an editable element
 * inside CodeMirror's own editable host makes its DOM observer reconcile those
 * keystrokes back into the document, which rewrote the whole file in testing.
 * Editing a cell in place needs an editor mounted outside `contentDOM` — a
 * tooltip or panel over the cell — rather than an editable inside it. Clicking
 * the table still opens its Markdown for editing.
 */
class TableWidget extends WidgetType {
  constructor(markup, from, to) {
    super();
    this.markup = markup;
    this.from = from;
    this.to = to;
  }

  eq(other) {
    return other.markup === this.markup && other.from === this.from;
  }

  rows() {
    return this.markup.split("\n").filter((line) => line.trim()).map(splitRow);
  }

  toDOM() {
    const wrapper = document.createElement("div");
    wrapper.className = "cm-md-table";
    const table = document.createElement("table");
    let body = null;

    const rows = this.rows();
    let rendered = 0;
    rows.forEach((cells, index) => {
      if (index === 1 && isAlignmentRow(cells)) return;
      const head = rendered === 0;
      const row = document.createElement("tr");
      for (const cell of cells) {
        const element = document.createElement(head ? "th" : "td");
        element.textContent = cell;
        element.dir = "auto";
        row.append(element);
      }
      rendered += 1;
      if (head) {
        const header = document.createElement("thead");
        header.append(row);
        table.append(header);
        return;
      }
      if (!body) {
        body = document.createElement("tbody");
        table.append(body);
      }
      body.append(row);
    });
    wrapper.append(table);
    return wrapper;
  }

  ignoreEvent() {
    // Let clicks through so the caret lands in the source and the table opens.
    return false;
  }
}

/**
 * A rendered image.
 *
 * The source is resolved by the host, which is the only layer that knows how a
 * relative path maps to a URL the webview may load. If it declines — a remote
 * URL, or a path outside the document's own directory — the Markdown is left
 * as written rather than silently showing a broken image.
 */
class ImageWidget extends WidgetType {
  constructor(url, alt) {
    super();
    this.url = url;
    this.alt = alt;
  }

  eq(other) {
    return other.url === this.url && other.alt === this.alt;
  }

  toDOM() {
    const figure = document.createElement("span");
    figure.className = "cm-md-image";
    const image = document.createElement("img");
    image.src = this.url;
    image.alt = this.alt;
    image.loading = "lazy";
    figure.append(image);
    return figure;
  }

  ignoreEvent() {
    return false;
  }
}

class RuleWidget extends WidgetType {
  eq() {
    return true;
  }

  toDOM() {
    const wrapper = document.createElement("div");
    wrapper.className = "cm-md-rule";
    wrapper.append(document.createElement("hr"));
    return wrapper;
  }

  ignoreEvent() {
    return false;
  }
}

/**
 * A task-list checkbox.
 *
 * Clicking it rewrites only the characters between the brackets. That is a user
 * edit through a control, not the preview layer reconciling the document with
 * what it painted.
 */
class TaskWidget extends WidgetType {
  constructor(checked, from, to) {
    super();
    this.checked = checked;
    this.from = from;
    this.to = to;
  }

  eq(other) {
    return other.checked === this.checked && other.from === this.from;
  }

  toDOM(view) {
    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "cm-md-task";
    box.checked = this.checked;
    box.setAttribute("aria-label", this.checked ? "Completed task" : "Task");
    box.addEventListener("mousedown", (event) => event.preventDefault());
    box.addEventListener("change", () => {
      view.dispatch({
        changes: { from: this.from, to: this.to, insert: this.checked ? "[ ]" : "[x]" },
      });
    });
    return box;
  }

  ignoreEvent() {
    return false;
  }
}

/** Line numbers covered by a cursor or selection. */
function activeLines(state) {
  const lines = new Set();
  for (const range of state.selection.ranges) {
    const first = state.doc.lineAt(range.from).number;
    const last = state.doc.lineAt(range.to).number;
    for (let line = first; line <= last; line += 1) lines.add(line);
  }
  return lines;
}

function spansActiveLine(state, active, node) {
  const first = state.doc.lineAt(node.from).number;
  const last = state.doc.lineAt(node.to).number;
  for (let line = first; line <= last; line += 1) if (active.has(line)) return true;
  return false;
}

/** Read `![alt](src)` out of the source text of an Image node. */
function parseImage(markup) {
  const match = /^!\[([^\]]*)\]\(\s*<?([^\s)>]+)>?(?:\s+"[^"]*")?\s*\)$/.exec(markup.trim());
  return match ? { alt: match[1], src: match[2] } : null;
}

function buildBlockDecorations(state, resolveAsset) {
  if (state.doc.length > MAX_SCANNED_CHARS) return Decoration.none;
  const active = activeLines(state);
  const items = [];

  syntaxTree(state).iterate({
    enter: (node) => {
      if (node.name === "Table" && !spansActiveLine(state, active, node)) {
        items.push([
          node.from,
          node.to,
          Decoration.replace({
            widget: new TableWidget(
              state.doc.sliceString(node.from, node.to),
              node.from,
              node.to,
            ),
            block: true,
          }),
        ]);
        return false;
      }
      if (node.name === "HorizontalRule" && !spansActiveLine(state, active, node)) {
        items.push([node.from, node.to, Decoration.replace({ widget: new RuleWidget(), block: true })]);
        return false;
      }
      if (node.name === "Image" && !spansActiveLine(state, active, node)) {
        const parsed = parseImage(state.doc.sliceString(node.from, node.to));
        const url = parsed && resolveAsset ? resolveAsset(parsed.src) : null;
        if (url) {
          items.push([
            node.from,
            node.to,
            Decoration.replace({ widget: new ImageWidget(url, parsed.alt) }),
          ]);
        }
        return false;
      }
      if (node.name === "TaskMarker" && !active.has(state.doc.lineAt(node.from).number)) {
        const text = state.doc.sliceString(node.from, node.to);
        items.push([
          node.from,
          node.to,
          Decoration.replace({ widget: new TaskWidget(/x/i.test(text), node.from, node.to) }),
        ]);
      }
      return undefined;
    },
  });

  items.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const builder = new RangeSetBuilder();
  for (const [from, to, decoration] of items) builder.add(from, to, decoration);
  return builder.finish();
}

let blockWidgetFieldInstance = null;

/**
 * The block decoration field.
 *
 * `resolveAsset` is captured once when the editor is created; it maps a
 * Markdown image path to a URL the webview is allowed to load, or null.
 */
export function createBlockWidgetField(resolveAsset) {
  blockWidgetFieldInstance = StateField.define({
    create: (state) => buildBlockDecorations(state, resolveAsset),
    update(value, transaction) {
      if (!transaction.docChanged && !transaction.selection) return value;
      return buildBlockDecorations(transaction.state, resolveAsset);
    },
    provide: (field) => EditorView.decorations.from(field),
  });
  return blockWidgetFieldInstance;
}

/** Ranges a block widget covers, so the inline layer can skip them. */
export function blockWidgetRanges(state) {
  const ranges = [];
  const set = blockWidgetFieldInstance ? state.field(blockWidgetFieldInstance, false) : null;
  if (!set) return ranges;
  const cursor = set.iter();
  while (cursor.value) {
    ranges.push([cursor.from, cursor.to]);
    cursor.next();
  }
  return ranges;
}
