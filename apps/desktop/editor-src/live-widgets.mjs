import { documentLineLayout } from "./document-line-layout.mjs";
import { visualMetadataFields, updateVisualMetadata } from "./markdown-frontmatter.mjs";
/**
 * Block widgets for live preview.
 *
 * Hiding syntax marks gets prose to read correctly, but a table written as
 * pipes still looks like pipes and `---` still looks like three hyphens. These
 * widgets replace whole blocks with the thing they describe, which is the step
 * that makes the editor read as a document rather than as marked-up text.
 *
 * Block decorations must come from a `StateField`, not a `ViewPlugin`:
 * CodeMirror rejects them from plugins outright ("Block decorations may not be
 * specified via plugins"). A field has no viewport to narrow the work to, so
 * this walk covers the whole document on every change — which is why only
 * blocks live here. The image and the task checkbox replace inline text and
 * are drawn by the viewport-scoped plugin in `live-preview.mjs`; their widget
 * classes stay here, beside the ones they resemble.
 *
 * With only blocks left to find, the walk descends into the five node kinds a
 * block can nest inside and treats everything else as a leaf. Its cost is then
 * set by how many blocks a document has, not by how long it is, which is what
 * removed the size bound that used to switch live preview off entirely on a
 * long document.
 *
 * A caret entering a block's source lines exposes its Markdown. A table click
 * instead opens a cell editor outside contentDOM and keeps the grid visible.
 * Painting never rewrites the document. Explicit controls such as table-cell
 * editing and task checkboxes dispatch bounded source edits through CodeMirror.
 */
import { Facet, RangeSetBuilder, StateField, Transaction } from "@codemirror/state";
import { isolateHistory } from "@codemirror/commands";
import { Decoration, EditorView, WidgetType } from "@codemirror/view";
import { onlineImageControl } from "../frontend/js/preview/online-images.mjs";
import { spriteIcon } from "../frontend/js/ui/icons.mjs";
import { ensureSyntaxTree, syntaxTree } from "@codemirror/language";
import { markdownLanguage } from "@codemirror/lang-markdown";
import { appendTableInline, tableInlineText } from "./table-inline.mjs";
import {
  autoCellAlignment,
  createTableActions,
  tableExtendButton,
  openTableCellEditor,
  resizeTableColumns,
  selectTableCell,
  tableCellAlignment,
  tableLabels,
  tableModel,
  tableCellMetadata,
  tableRowCells,
} from "./table-editing.mjs";
import { codeBodyText, codeWrapState, fencedCodeSpec } from "./code-block-tools.mjs";
import { diagramRenderer, DiagramWidget } from "./diagram-widget.mjs";
import { mathAndFootnotes } from "./markdown-extras.mjs";

const tableParser = markdownLanguage.parser.configure([mathAndFootnotes]);

/**
 * The only nodes that can hold another block, and so the only ones worth
 * walking into: a table inside a list item, a rule inside a quotation.
 */
const BLOCK_CONTAINERS = new Set([
  "Document",
  "Blockquote",
  "BulletList",
  "OrderedList",
  "ListItem",
]);

/** The table's column order belongs to its content, not the interface locale. */
export function tableContentDirection(markup) {
  const firstLetter = String(markup)
    .replace(/<!--folio-(?:align:(?:auto|left|center|right)|width:(?:[1-9][0-9]?|100))-->/g, "")
    .match(/\p{L}/u)?.[0];
  return firstLetter && /[\u0590-\u08ff\uFB1D-\uFDFF\uFE70-\uFEFF]/u.test(firstLetter)
    ? "rtl"
    : "ltr";
}

/**
 * Why every block widget below declares `estimatedHeight`.
 *
 * CodeMirror only draws the viewport. For everything outside it, the height
 * map is built from estimates, and a widget that does not declare one is
 * assumed to be a single line. A table replacing five lines with a widget
 * nine lines tall therefore left the map wrong by the difference for every
 * position after it — so a click below a table landed on a different line
 * than the one under the pointer, and the caret could not be put on it at
 * all. It only reproduced in documents long enough to scroll, because once a
 * widget has been drawn its real height replaces the estimate.
 *
 * The numbers are approximations on purpose: they only have to be close
 * enough that the map is not badly wrong before the widget is measured.
 */

/** Roughly one line of the editor's own type, in pixels. */
const LINE_HEIGHT = 26;
/* The vertical space these widgets carry, which is now inside the box
 * CodeMirror measures rather than a margin outside it. Declared here as well
 * as in the stylesheet because the estimate has to include what the drawn
 * widget will include; the two disagreeing is the whole failure this pair of
 * constants exists to prevent. */
const TABLE_BLOCK_PADDING = 27;
const FRONT_MATTER_BLOCK_PADDING = 16;

/** The host supplies its existing offline renderer; the bundle owns no URL. */
export const mathRenderer = Facet.define({
  combine: (values) => (values.length ? values[0] : null),
});

export class MathWidget extends WidgetType {
  constructor(markup, from, to, display, renderMath) {
    super();
    this.markup = markup;
    this.from = from;
    this.to = to;
    this.display = display;
    this.renderMath = renderMath;
  }

  eq(other) {
    return (
      other.markup === this.markup &&
      other.from === this.from &&
      other.to === this.to &&
      other.display === this.display &&
      other.renderMath === this.renderMath
    );
  }

  get estimatedHeight() {
    return this.display ? 64 : -1;
  }

  toDOM(view) {
    const wrapper = document.createElement(this.display ? "div" : "span");
    wrapper.className = `cm-md-math-preview${this.display ? " cm-md-math-block-preview" : ""}`;
    const formula = document.createElement("span");
    formula.className = `math ${this.display ? "display" : "inline"}`;
    formula.textContent = this.markup;
    formula.dir = "ltr";
    wrapper.append(formula);
    const isCurrent = () =>
      wrapper.isConnected &&
      wrapper.dataset.disposed !== "true" &&
      view.dom.contains(wrapper) &&
      view.state.doc.sliceString(this.from, this.to) === this.markup;
    wrapper.addEventListener("mousedown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      const contentStart = this.display ? Math.max(2, this.markup.indexOf("\n") + 1) : 1;
      view.dispatch({
        selection: { anchor: Math.min(this.to, this.from + contentStart) },
        scrollIntoView: true,
      });
      view.focus();
    });
    // A widget is only created when CodeMirror actually draws it. Wait until
    // that draw has attached it, then use the shared renderer's bounded queue
    // and cache. A removed/edited widget cannot accept a late typeset result.
    requestAnimationFrame(() => {
      if (!isCurrent()) return;
      Promise.resolve()
        .then(() => this.renderMath(wrapper, { isCurrent }))
        .catch(() => {
          if (isCurrent()) formula.dataset.mathError = "true";
        })
        .finally(() => {
          if (!isCurrent()) return;
          // MathJax's error SVG can be an empty coloured rectangle. The
          // editable source is a useful fallback; a broken drawing is not.
          if (formula.dataset.mathError === "true") {
            formula.textContent = this.markup;
            formula.removeAttribute("data-math-rendered");
          }
          view.requestMeasure();
        });
    });
    return wrapper;
  }

  destroy(dom) {
    dom.dataset.disposed = "true";
  }

  ignoreEvent() {
    return false;
  }
}

function columnResizeHandle(view, model, table, colgroup, column) {
  const handle = document.createElement("span");
  handle.className = "cm-table-column-resize";
  handle.dataset.tableResize = "";
  handle.tabIndex = 0;
  handle.setAttribute("role", "separator");
  handle.setAttribute("aria-orientation", "vertical");
  handle.setAttribute("aria-label", tableLabels().resizeColumn + " " + (column + 1));
  handle.setAttribute("aria-valuemin", "1");
  handle.setAttribute("aria-valuemax", "100");
  handle.setAttribute(
    "aria-valuenow",
    String(
      tableCellMetadata(model.rows[0].cells[column]?.raw).width || Math.round(100 / model.columns),
    ),
  );
  const sizes = () =>
    [...table.rows[0].cells].map((cell) =>
      Math.max(1, Math.round((cell.getBoundingClientRect().width * 100) / table.offsetWidth)),
    );
  const fromDelta = (base, delta) => {
    const result = [...base];
    const sum = base[column] + base[column + 1];
    const min = Math.min(8, Math.floor(sum / 2));
    result[column] = Math.max(min, Math.min(sum - min, base[column] + delta));
    result[column + 1] = sum - result[column];
    return result;
  };
  const commit = (widths) =>
    resizeTableColumns(
      view,
      model.from,
      widths.map((width, index) => [index, width]),
    );
  handle.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    const sign = (event.key === "ArrowRight" ? 1 : -1) * (table.dir === "rtl" ? -1 : 1);
    commit(fromDelta(sizes(), sign * (event.shiftKey ? 5 : 1)));
    requestAnimationFrame(() =>
      view.dom
        .querySelector(
          `.cm-md-table[data-table-from="${model.from}"] [data-table-column="${column}"] [data-table-resize]`,
        )
        ?.focus({ preventScroll: true }),
    );
  });
  let drag = null;
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    drag = {
      id: event.pointerId,
      x: event.clientX,
      base: sizes(),
      original: [...colgroup.children].map((item) => item.style.width),
      originallySized: table.classList.contains("cm-table-sized"),
    };
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    const sign = table.dir === "rtl" ? -1 : 1;
    drag.next = fromDelta(
      drag.base,
      Math.round((sign * (event.clientX - drag.x) * 100) / table.offsetWidth),
    );
    table.classList.add("cm-table-sized");
    drag.next.forEach((width, index) => {
      colgroup.children[index].style.width = width + "%";
    });
    handle.setAttribute("aria-valuenow", String(drag.next[column]));
    view.requestMeasure();
  });
  const endDrag = (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    const current = drag;
    drag = null;
    table.classList.toggle("cm-table-sized", current.originallySized);
    current.original.forEach((width, index) => {
      colgroup.children[index].style.width = width;
    });
    if (
      event.type === "pointerup" &&
      current.next &&
      current.next[column] !== current.base[column]
    ) {
      commit(current.next);
    }
    view.requestMeasure();
  };
  handle.addEventListener("pointerup", endDrag);
  handle.addEventListener("pointercancel", endDrag);
  handle.addEventListener("lostpointercapture", endDrag);
  handle.addEventListener("click", (event) => event.stopPropagation());
  return handle;
}

export class TableWidget extends WidgetType {
  constructor(markup, from, to, renderMath = null, syntax = null) {
    super();
    this.markup = markup;
    this.from = from;
    this.to = to;
    this.renderMath = renderMath;
    this.syntax = syntax;
  }

  eq(other) {
    return (
      other.markup === this.markup &&
      other.from === this.from &&
      other.renderMath === this.renderMath
    );
  }

  rows() {
    return this.markup
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => tableRowCells(line).map(({ raw }) => raw.replaceAll("\\|", "|")));
  }

  /** Header, body rows, cell padding, the wrapper's border and its padding. */
  get estimatedHeight() {
    const rows = this.markup.split("\n").filter((line) => line.trim()).length;
    // The delimiter row (`| --- |`) is markup, not a row that gets drawn.
    return Math.max(1, rows - 1) * (LINE_HEIGHT + 8) + 16 + TABLE_BLOCK_PADDING;
  }

  toDOM(view) {
    const wrapper = document.createElement("div");
    wrapper.className = "cm-md-table";
    const table = document.createElement("table");
    wrapper.dir = table.dir = tableContentDirection(this.markup);
    let body = null;

    // Keep the real tree for tables inside lists and blockquotes: parsing the
    // sliced text again would mistake their continuation prefixes for cells.
    const parsed = this.syntax || tableParser.parse(this.markup).topNode.firstChild;
    const offset = this.syntax ? this.from : 0;
    const model = parsed ? tableModel(this.markup, this.from, parsed) : null;
    const colgroup = document.createElement("colgroup");
    if (view || model?.rows[0]?.cells.some((cell) => tableCellMetadata(cell.raw).width)) {
      for (let column = 0; column < (model?.columns || 0); column += 1) {
        const col = document.createElement("col");
        const width = tableCellMetadata(model.rows[0].cells[column]?.raw).width;
        if (width) {
          col.style.width = width + "%";
          table.classList.add("cm-table-sized");
        }
        colgroup.append(col);
      }
      table.append(colgroup);
    }
    wrapper.setAttribute("data-table-from", String(this.from));
    if (view && model) {
      wrapper.classList.toggle("cm-md-table--editable", !view.state.readOnly);
      wrapper.tabIndex = 0;
      wrapper.setAttribute("aria-label", tableLabels().table);
      wrapper.addEventListener("keydown", (event) => {
        if (event.target !== wrapper || event.key !== "Enter" || event.isComposing) return;
        event.preventDefault();
        event.stopPropagation();
        openTableCellEditor(view, model, 0, 0);
      });
    }
    const rows = [];
    for (let child = parsed?.firstChild; child; child = child.nextSibling) {
      if (child.name === "TableHeader" || child.name === "TableRow") rows.push(child);
    }
    let columns = 0;
    rows.forEach((sourceRow, index) => {
      const cells = [];
      for (let cell = sourceRow.firstChild; cell; cell = cell.nextSibling) {
        if (cell.name === "TableCell") cells.push(cell);
      }
      const head = index === 0;
      if (head) columns = model?.columns || cells.length;
      const row = document.createElement("tr");
      for (let column = 0; column < columns; column += 1) {
        const physical = model?.rows[index]?.cells[column];
        const cell = physical
          ? cells.find((candidate) => candidate.from + this.from - offset === physical.from)
          : null;
        const element = document.createElement(head ? "th" : "td");
        const editable = view && model && !view.state.readOnly;
        const content = editable ? document.createElement("div") : element;
        const rendered = editable ? document.createElement("div") : element;
        if (editable) {
          content.className = "cm-table-cell-content";
          rendered.className = "cm-table-cell-rendered";
          content.append(rendered);
          element.append(content);
        }
        const { alignment, prefix } = tableCellAlignment(model, index, column);
        if (cell)
          appendTableInline(rendered, cell, this.markup, {
            offset,
            contentFrom: cell.from + prefix,
            renderMathNode:
              this.renderMath && view
                ? (node) =>
                    new MathWidget(
                      this.markup.slice(node.from - offset, node.to - offset),
                      this.from + node.from - offset,
                      this.from + node.to - offset,
                      false,
                      this.renderMath,
                    ).toDOM(view)
                : null,
          });
        element.style.textAlign =
          alignment === "auto" ? autoCellAlignment(tableInlineText(element)) : alignment;
        element.dir = "auto";
        element.setAttribute("data-table-row", String(index));
        element.setAttribute("data-table-column", String(column));
        if (editable) {
          const scopeButton = (scope, index, targetRow, targetColumn) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "cm-table-selection-handle";
            button.dataset.tableSelect = scope;
            button.title =
              (scope === "row" ? tableLabels().selectRow : tableLabels().selectColumn) +
              " " +
              (index + 1);
            button.setAttribute("aria-label", button.title);
            button.setAttribute("aria-haspopup", "menu");
            button.setAttribute("aria-expanded", "false");
            button.addEventListener("click", (event) => {
              event.preventDefault();
              event.stopPropagation();
              openTableCellEditor(view, model, targetRow, targetColumn, { kind: scope });
            });
            element.append(button);
          };
          if (head) {
            scopeButton("column", column, 0, column);
            if (column + 1 < columns)
              element.append(columnResizeHandle(view, model, table, colgroup, column));
          }
          if (!column) scopeButton("row", index, index, 0);
          element.addEventListener(
            "mousedown",
            (event) => {
              if (
                event.button !== 0 ||
                event.target.closest("[data-table-select], [data-table-resize], textarea")
              )
                return;
              event.preventDefault();
              event.stopPropagation();
            },
            { capture: true },
          );
          element.addEventListener("click", (event) => {
            if (event.button !== 0 || event.target.closest("textarea")) return;
            event.preventDefault();
            event.stopPropagation();
            // Mount the input after the click so its DOM does not replace the
            // target before the pointer sequence finishes.
            selectTableCell(view, model, index, column, event);
          });
        }
        row.append(element);
      }
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
    if (view && model && !view.state.readOnly) {
      const frame = document.createElement("div");
      frame.className = "cm-table-frame";
      const scroller = document.createElement("div");
      scroller.className = "cm-table-scroll";
      scroller.append(table);
      frame.append(
        scroller,
        createTableActions(view, model),
        tableExtendButton(view, model, "column"),
      );
      wrapper.append(frame, tableExtendButton(view, model, "row"));
    } else wrapper.append(table);
    return wrapper;
  }

  ignoreEvent(event) {
    // Mouse input belongs to the visual cell editor. Keyboard history and
    // navigation return to CodeMirror after the grid regains focus.
    return (
      event.type !== "keydown" || !!event.target.closest?.("button, summary, .cm-table-cell-input")
    );
  }
}

function imagePlaceholder(source, alt, labelText) {
  const missing = document.createElement("span");
  missing.className = "cm-md-image-missing";
  missing.title = source;
  const label = document.createElement("strong");
  label.textContent = labelText;
  missing.append(label);
  if (source) {
    const path = document.createElement("code");
    path.dir = "ltr";
    path.textContent = source;
    path.title = source;
    missing.append(path);
  }
  if (alt) {
    const caption = document.createElement("span");
    caption.textContent = alt;
    missing.append(caption);
  }
  return missing;
}

export class ImagePlaceholderWidget extends WidgetType {
  constructor(source, alt, label) {
    super();
    this.source = source;
    this.alt = alt;
    this.label = label;
  }
  eq(other) {
    return other.source === this.source && other.alt === this.alt && other.label === this.label;
  }
  toDOM() {
    return imagePlaceholder(this.source, this.alt, this.label);
  }
  ignoreEvent() {
    return false;
  }
}

/** Online images are actionable document resources, with session host grants. */
export class OnlineImageWidget extends WidgetType {
  constructor(source, alt, allowed, request, strings) {
    super();
    Object.assign(this, { source, alt, allowed, request, strings });
  }
  eq(other) {
    return (
      other.source === this.source &&
      other.alt === this.alt &&
      other.allowed === this.allowed &&
      other.request === this.request &&
      JSON.stringify(other.strings) === JSON.stringify(this.strings)
    );
  }
  toDOM(view) {
    const control = onlineImageControl(view.dom.ownerDocument, {
      source: this.source,
      alt: this.alt,
      allowed: this.allowed,
      onRequest: this.request,
      strings: this.strings,
    });
    const measure = () => {
      if (view.dom.contains(control)) view.requestMeasure();
    };
    control.addEventListener("load", measure, true);
    control.addEventListener("error", measure, true);
    return control;
  }
  ignoreEvent() {
    return true;
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
export class ImageWidget extends WidgetType {
  constructor(url, alt, source = "", label = "Image not found") {
    super();
    this.url = url;
    this.alt = alt;
    this.source = source;
    this.label = label;
  }

  eq(other) {
    return (
      other.url === this.url &&
      other.alt === this.alt &&
      other.source === this.source &&
      other.label === this.label
    );
  }

  toDOM() {
    const figure = document.createElement("span");
    figure.className = "cm-md-image";
    const image = document.createElement("img");
    image.src = this.url;
    image.alt = this.alt;
    image.loading = "lazy";
    // A path that resolves is not a file that loads: a moved or misspelled
    // image otherwise left the browser's own broken-image glyph sitting in the
    // document, which says nothing about which image or why. Name it instead,
    // in the same shape the exporter uses for an image it had to block.
    image.addEventListener("error", () => {
      figure.replaceChildren(imagePlaceholder(this.source, this.alt, this.label));
    });
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

  get estimatedHeight() {
    return LINE_HEIGHT;
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
/**
 * A character reference, shown as the character it references.
 *
 * `&mdash;` is an em dash in every rendering of the document except the one
 * the author is looking at while they write it. The widget is inert — no
 * events, no interaction — because it stands in for a single character; put
 * the caret on the line and the source comes back like every other mark.
 */
export class EntityWidget extends WidgetType {
  constructor(character) {
    super();
    this.character = character;
  }

  eq(other) {
    return other.character === this.character;
  }

  toDOM() {
    const span = document.createElement("span");
    span.className = "cm-md-entity";
    span.textContent = this.character;
    return span;
  }

  ignoreEvent() {
    return true;
  }
}

/**
 * An unordered list's marker, as the reader will see it.
 *
 * `-`, `*` and `+` are three spellings of one bullet: the engine emits a plain
 * `<ul>`, and every stylesheet it ships leaves the browser default in place,
 * so a published list steps through disc, circle and square as it nests. The
 * editor showed the literal hyphen instead, which read as a stray dash down
 * the left edge of the document rather than as a list.
 *
 * The marker stays *visible* — it is content, not scaffolding, which is why
 * `ListMark` is not simply hidden — it is only spelled the way it prints.
 */
export class BulletWidget extends WidgetType {
  constructor(depth) {
    super();
    this.depth = depth;
  }

  eq(other) {
    return other.depth === this.depth;
  }

  toDOM() {
    const span = document.createElement("span");
    span.className = "cm-md-bullet";
    span.dataset.bullet = ["disc", "ring", "square"][this.depth % 3];
    span.setAttribute("aria-hidden", "true");
    return span;
  }

  ignoreEvent() {
    return true;
  }
}

export class TaskWidget extends WidgetType {
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
    box.disabled = view.state.readOnly;
    box.setAttribute("aria-label", this.checked ? "Completed task" : "Task");
    box.addEventListener("mousedown", (event) => event.preventDefault());
    box.addEventListener("change", () => {
      if (view.state.readOnly) return;
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

/**
 * Front matter, collapsed to what it says.
 *
 * A document's first screenful should be the document. Four to fifteen lines of
 * YAML above the first heading is metadata the writer set once and then reads
 * past every time they open the file. Collapsed it stays visible as a summary —
 * title, language, whether a cover is on. The chip opens native fields for
 * common scalar metadata.
 */
function editVisualFields(view, source, from, fields, onApply) {
  const fa = document.documentElement.lang.startsWith("fa");
  const form = document.createElement("form");
  form.className = "cm-visual-fields";
  const groups = new Map();
  const values = fields.map(({ name, value, multiline, kind, group, key }) => {
    const label = document.createElement("label");
    label.textContent = name;
    const input = document.createElement(multiline ? "textarea" : "input");
    input.dir = "auto";
    if (kind && kind !== "multiline") input.type = kind;
    if (kind === "number") input.step = "any";
    if (kind === "checkbox") input.checked = value;
    else input.value = value;
    if (key) input.dataset.metadataKey = key;
    label.append(input);
    if (!group) form.append(label);
    else {
      if (!groups.has(group)) {
        const section = document.createElement("details");
        const title = document.createElement("summary");
        title.textContent = group;
        section.append(title);
        form.append(section);
        groups.set(group, section);
        section.addEventListener("toggle", () => view.requestMeasure());
      }
      groups.get(group).append(label);
    }
    return input;
  });
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = fa ? "اعمال" : "Apply";
  button.disabled = view.state.readOnly || !fields.length;
  form.append(button);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const to = from + source.length;
    if (view.state.readOnly || view.state.doc.sliceString(from, to) !== source) return;
    const insert = onApply(
      values.map((input) => (input.type === "checkbox" ? input.checked : input.value)),
    );
    if (insert !== source)
      view.dispatch({
        changes: { from, to, insert },
        annotations: [Transaction.userEvent.of("input.fields"), isolateHistory.of("full")],
      });
    else form.hidden = true;
    view.requestMeasure();
  });
  return form;
}

const simpleMetadataFields = {
  title: ["Title", "عنوان"],
  subtitle: ["Subtitle", "زیرعنوان"],
  author: ["Author", "نویسنده"],
  date: ["Date", "تاریخ"],
  lang: ["Language", "زبان"],
  version: ["Version", "نسخه"],
};

class FrontMatterWidget extends WidgetType {
  constructor(markup, from, readOnly) {
    super();
    this.markup = markup;
    this.from = from;
    this.readOnly = readOnly;
  }

  eq(other) {
    return (
      other.markup === this.markup && other.from === this.from && other.readOnly === this.readOnly
    );
  }

  /** Collapsed to one summary row whatever the metadata's length. */
  get estimatedHeight() {
    return LINE_HEIGHT + 18 + FRONT_MATTER_BLOCK_PADDING;
  }

  /** The handful of keys worth showing without opening the block. */
  summary() {
    const entries = [];
    for (const line of this.markup.split("\n")) {
      const match = /^([A-Za-z_$][\w.$-]*)\s*:\s*(.+?)\s*$/.exec(line);
      if (!match) continue;
      const [, key, rawValue] = match;
      if (!["title", "subtitle", "author", "lang", "date", "toc"].includes(key)) continue;
      const value = rawValue.replace(/^["']|["']$/g, "").trim();
      if (value) entries.push(value);
      if (entries.length >= 3) break;
    }
    return entries;
  }

  toDOM(view) {
    // Two elements, because the spacing around the chip has to be inside the
    // box CodeMirror measures and the chip has a border of its own.
    const block = document.createElement("div");
    block.className = "cm-md-frontmatter-block";
    const wrapper = document.createElement("button");
    wrapper.type = "button";
    const fa = document.documentElement.lang.startsWith("fa");
    const metadata = visualMetadataFields(this.markup);
    const labels = {
      ...simpleMetadataFields,
      authors: ["Authors", "نویسندگان"],
      summary: ["Summary", "خلاصه"],
      name: ["Name", "نام"],
      email: ["Email", "ایمیل"],
      role: ["Role", "نقش"],
      appearance: ["Appearance", "ظاهر"],
      references: ["References", "مراجع"],
      citations: ["Citations", "ارجاع‌ها"],
      branding: ["Branding", "برند"],
      keywords: ["Keywords", "کلیدواژه‌ها"],
      dir: ["Direction", "جهت"],
    };
    const labelFor = (key) =>
      Object.hasOwn(labels, key)
        ? labels[key][fa ? 1 : 0]
        : key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
    const fields = metadata.map((field) => ({
      ...field,
      key: field.path.join("."),
      name: field.path
        .slice(field.path.length > 1 ? 1 : 0)
        .map(labelFor)
        .join(" · "),
      group: field.path.length > 1 ? labelFor(field.path[0]) : null,
      multiline: field.kind === "multiline",
    }));
    const form = editVisualFields(view, this.markup, this.from, fields, (values) =>
      updateVisualMetadata(this.markup, metadata, values),
    );
    form.hidden = true;
    wrapper.disabled = this.readOnly || !fields.length;
    wrapper.setAttribute("aria-expanded", "false");
    wrapper.addEventListener("click", () => {
      form.hidden = !form.hidden;
      wrapper.setAttribute("aria-expanded", String(!form.hidden));
      if (!form.hidden) form.querySelector("input")?.focus();
      view.requestMeasure();
    });
    wrapper.className = "cm-md-frontmatter";
    block.append(wrapper, form);
    const label = document.createElement("span");
    label.className = "cm-md-frontmatter-label";
    label.textContent = document.documentElement.lang.startsWith("fa") ? "مشخصات سند" : "Metadata";
    wrapper.append(label);
    for (const entry of this.summary()) {
      const chip = document.createElement("span");
      chip.className = "cm-md-frontmatter-value";
      chip.textContent = entry;
      chip.dir = "auto";
      wrapper.append(chip);
    }
    return block;
  }

  ignoreEvent() {
    return true;
  }
}

const DISCLOSURE_TAGS = new Set([
  "DETAILS",
  "SUMMARY",
  "P",
  "DIV",
  "SPAN",
  "UL",
  "OL",
  "LI",
  "PRE",
  "CODE",
  "BR",
  "BLOCKQUOTE",
  "S",
  "EM",
  "I",
  "STRONG",
  "B",
  "MARK",
  "SUB",
  "SUP",
  "H1",
  "H2",
  "H3",
  "H4",
  "H5",
  "H6",
]);

function disclosureContent(markup) {
  if (
    typeof document === "undefined" ||
    !/^<details(?:\s[^>]*)?>[\s\S]*<\/details>\s*$/i.test(markup)
  )
    return null;
  const template = document.createElement("template");
  template.innerHTML = markup;
  const details = template.content.firstElementChild;
  if (
    details?.tagName !== "DETAILS" ||
    details.nextElementSibling ||
    details.firstElementChild?.tagName !== "SUMMARY"
  )
    return null;
  // Keep HTML outside this inert, local disclosure subset editable as source.
  for (const element of template.content.querySelectorAll("*")) {
    if (!DISCLOSURE_TAGS.has(element.tagName)) return null;
    for (const name of element.getAttributeNames()) {
      if (name === "open" && element.tagName === "DETAILS") continue;
      if (name === "lang") continue;
      if (name === "dir" && /^(ltr|rtl|auto)$/i.test(element.dir)) continue;
      return null;
    }
  }
  return details;
}

class DisclosureWidget extends WidgetType {
  constructor(markup, details, from, readOnly) {
    super();
    this.markup = markup;
    this.details = details;
    this.from = from;
    this.readOnly = readOnly;
  }
  eq(other) {
    return (
      other.markup === this.markup && other.from === this.from && other.readOnly === this.readOnly
    );
  }
  toDOM(view) {
    const group = document.createElement("div");
    group.className = "cm-document-disclosure";
    const details = this.details.cloneNode(true);
    details.addEventListener("toggle", () => view.requestMeasure());
    group.append(details);
    const editable =
      /^(<details(?:\s[^>]*)?>\s*<summary>)([^<]*)(<\/summary>\s*<p>)([^<]*)(<\/p>\s*<\/details>\s*)$/i.exec(
        this.markup,
      );
    if (!this.readOnly && editable) {
      const fa = document.documentElement.lang.startsWith("fa");
      const escape = (text) =>
        text.replace(
          /[&<>]/g,
          (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[character],
        );
      const paragraph = details.querySelector("p");
      const form = editVisualFields(
        view,
        this.markup,
        this.from,
        [
          {
            name: fa ? "عنوان بخش" : "Section title",
            value: details.querySelector("summary").textContent,
          },
          { name: fa ? "متن بخش" : "Section text", value: paragraph.textContent, multiline: true },
        ],
        ([title, body]) => editable[1] + escape(title) + editable[3] + escape(body) + editable[5],
      );
      form.hidden = true;
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "icon-button cm-disclosure-edit";
      edit.title = document.documentElement.lang.startsWith("fa")
        ? "ویرایش متن بخش"
        : "Edit disclosure";
      edit.setAttribute("aria-label", edit.title);
      edit.append(spriteIcon("pencil"));
      edit.addEventListener("click", () => {
        form.hidden = !form.hidden;
        edit.setAttribute("aria-expanded", String(!form.hidden));
        if (!form.hidden) form.querySelector("input")?.focus();
        view.requestMeasure();
      });
      edit.setAttribute("aria-expanded", "false");
      group.append(edit, form);
    }
    return group;
  }
  ignoreEvent() {
    return true;
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
export function parseImage(markup) {
  const match =
    /^!\[((?:\\.|[^\]\\])*)\]\(\s*(?:<([^>\r\n]+)>|((?:\\.|[^\s()\\]|\((?:\\.|[^()\\])*\))+))(?:\s+["'][^\r\n]*?["'])?\s*\)$/.exec(
      markup.trim(),
    );
  return match ? { alt: match[1], src: match[2] || match[3] } : null;
}

/** Time budget for forcing the parse; beyond it, use whatever is ready. */
/** Setext headings: a title line plus a `===` or `---` rule under it. */
const SETEXT_HEADINGS = new Set(["SetextHeading1", "SetextHeading2"]);

const PARSE_BUDGET_MS = 100;
const proseSpacerLine = Decoration.line({ class: "cm-md-prose-spacer" });

function buildBlockDecorations(state) {
  const active = activeLines(state);
  const items = [];
  const layout = new Map();
  const verbatim = [];
  const addLine = (at, decoration) => {
    if (!layout.has(at)) layout.set(at, new Set());
    layout.get(at).add(decoration);
  };

  // CodeMirror parses incrementally, so `syntaxTree` covers only what it has
  // reached — on a 60k-character guide that was 6% of the document, and every
  // table past the first few kilobytes stayed as raw pipes. A state field has
  // no viewport to narrow to, so the parse is forced within a budget and
  // whatever is ready is used if the budget runs out.
  const tree = ensureSyntaxTree(state, state.doc.length, PARSE_BUDGET_MS) || syntaxTree(state);

  tree.iterate({
    enter: (node) => {
      documentLineLayout(state, node, addLine);
      if (
        ["Frontmatter", "HTMLBlock", "FencedCode", "CodeBlock", "BlockMath", "Table"].includes(
          node.name,
        )
      ) {
        verbatim.push([node.from, node.to]);
      }
      if (node.name === "Frontmatter") {
        items.push([
          node.from,
          node.to,
          Decoration.replace({
            widget: new FrontMatterWidget(
              state.doc.sliceString(node.from, node.to),
              node.from,
              state.readOnly,
            ),
            block: true,
          }),
        ]);
        return false;
      }
      if (node.name === "HTMLBlock") {
        const markup = state.doc.sliceString(node.from, node.to);
        const details = disclosureContent(markup);
        if (details) {
          items.push([
            node.from,
            node.to,
            Decoration.replace({
              widget: new DisclosureWidget(markup, details, node.from, state.readOnly),
              block: true,
            }),
          ]);
        }
        return false;
      }
      if (node.name === "FencedCode") {
        const spec = fencedCodeSpec(state, node);
        if (spec?.language.toLowerCase() === "mermaid") {
          items.push([
            node.from,
            node.to,
            Decoration.replace({
              widget: new DiagramWidget(
                codeBodyText(state, spec),
                spec,
                state.facet(diagramRenderer),
                state.readOnly,
              ),
              block: true,
            }),
          ]);
        }
        return false;
      }
      if (node.name === "Table") {
        items.push([
          node.from,
          node.to,
          Decoration.replace({
            widget: new TableWidget(
              state.doc.sliceString(node.from, node.to),
              node.from,
              node.to,
              state.facet(mathRenderer),
              node.node,
            ),
            block: true,
          }),
        ]);
        return false;
      }
      if (
        node.name === "BlockMath" &&
        state.facet(mathRenderer) &&
        node.to - node.from <= 16 * 1024 &&
        !spansActiveLine(state, active, node)
      ) {
        items.push([
          node.from,
          node.to,
          Decoration.replace({
            widget: new MathWidget(
              state.doc.sliceString(node.from, node.to),
              node.from,
              node.to,
              true,
              state.facet(mathRenderer),
            ),
            block: true,
          }),
        ]);
        return false;
      }
      // `Title` over `=====` is one heading occupying two lines. The rule
      // underneath is scaffolding, and hiding only its characters leaves an
      // empty line holding the height of one. Replacing from the end of the
      // title through the end of the rule takes the line break with it — which
      // only a state field may do; attempted from the view plugin CodeMirror
      // rejects it with "decorations that replace line breaks may not be
      // specified via plugins" and drops every decoration in the batch.
      if (SETEXT_HEADINGS.has(node.name) && !spansActiveLine(state, active, node)) {
        const titleLine = state.doc.lineAt(node.from);
        if (titleLine.to < node.to) {
          items.push([titleLine.to, node.to, Decoration.replace({})]);
        }
        return false;
      }
      if (node.name === "HorizontalRule" && !spansActiveLine(state, active, node)) {
        items.push([
          node.from,
          node.to,
          Decoration.replace({ widget: new RuleWidget(), block: true }),
        ]);
        return false;
      }
      // Everything this field draws is a block, and a block can only be nested
      // inside another block. Anything else — a paragraph, a heading, the
      // inside of a fence, the cells of a table already left as source — is a
      // leaf as far as this walk is concerned. Descending into them anyway was
      // the cost of a keystroke on a long document, because a state field has
      // no viewport and walks the entire buffer every time.
      return BLOCK_CONTAINERS.has(node.name) ? undefined : false;
    },
  });

  // Height-affecting empty rows belong to the document's decoration set.
  // Viewport-only styling changes their heights when the scrolling window moves.
  let position = 0;
  let region = 0;
  for (const line of state.doc.iterLines()) {
    while (region < verbatim.length && verbatim[region][1] < position) region += 1;
    if (
      position + line.length < state.doc.length &&
      !line.trim() &&
      (region === verbatim.length || verbatim[region][0] > position)
    ) {
      items.push([position, position, proseSpacerLine]);
    }
    position += line.length + 1;
  }
  // Replaced widgets own their complete span, including any lines from a
  // surrounding list or quotation.
  const replaced = items.filter(([from, to]) => to > from);
  for (const [at, decorations] of layout) {
    if (replaced.some(([from, to]) => at >= from && at < to)) continue;
    for (const decoration of decorations) items.push([at, at, decoration]);
  }
  items.sort((a, b) => a[0] - b[0] || a[2].startSide - b[2].startSide);
  const builder = new RangeSetBuilder();
  for (const [from, to, decoration] of items) builder.add(from, to, decoration);
  return builder.finish();
}

// Keep one field for all document states. A mode change or a switch to a
// different tab must not change which field an existing state advertises.
const blockWidgetField = StateField.define({
  create: buildBlockDecorations,
  update(value, transaction) {
    const before = transaction.startState;
    const after = transaction.state;
    if (
      !transaction.docChanged &&
      syntaxTree(before) === syntaxTree(after) &&
      activeLineKey(before) === activeLineKey(after) &&
      before.readOnly === after.readOnly &&
      before.field(codeWrapState, false) === after.field(codeWrapState, false) &&
      before.facet(mathRenderer) === after.facet(mathRenderer) &&
      before.facet(diagramRenderer) === after.facet(diagramRenderer)
    )
      return value;
    return buildBlockDecorations(after);
  },
  provide: (field) => EditorView.decorations.from(field),
});

export function createBlockWidgetField() {
  return blockWidgetField;
}

/** The set of lines showing their source, as a value cheap to compare. */
function activeLineKey(state) {
  const parts = [];
  for (const range of state.selection.ranges) {
    parts.push(state.doc.lineAt(range.from).number, state.doc.lineAt(range.to).number);
  }
  return parts.join(",");
}

/** Ranges a block widget covers, so the inline layer can skip them. */
export function blockWidgetRanges(state) {
  const ranges = [];
  const set = state.field(blockWidgetField, false);
  if (!set) return ranges;
  const cursor = set.iter();
  while (cursor.value) {
    if (cursor.to > cursor.from) ranges.push([cursor.from, cursor.to]);
    cursor.next();
  }
  return ranges;
}
