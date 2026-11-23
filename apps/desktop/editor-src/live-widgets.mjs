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
import { Facet, RangeSetBuilder, StateField } from "@codemirror/state";
import { Decoration, EditorView, WidgetType } from "@codemirror/view";
import { onlineImageControl } from "../frontend/js/preview/online-images.mjs";
import { spriteIcon } from "../frontend/js/ui/icons.mjs";
import { ensureSyntaxTree, syntaxTree } from "@codemirror/language";
import { markdownLanguage } from "@codemirror/lang-markdown";
import { appendTableInline, tableInlineText } from "./table-inline.mjs";
import {
  autoCellAlignment,
  openTableCellEditor,
  selectTableCell,
  tableCellAlignment,
  tableLabels,
  tableModel,
  tableRowCells,
} from "./table-editing.mjs";
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
    .replace(/<!--folio-align:(?:auto|left|center|right)-->/g, "")
    .match(/\p{L}/u)?.[0];
  return firstLetter && /[\u0590-\u08ff\uFB1D-\uFDFF\uFE70-\uFEFF]/u.test(firstLetter)
    ? "rtl"
    : "ltr";
}

/**
 * A rendered GitHub table.
 *
 * The cells are deliberately not `contenteditable`. Nesting an editable element
 * inside CodeMirror's own editable host makes its DOM observer reconcile those
 * keystrokes back into the document, which rewrote the whole file in testing.
 * Editing a cell in place needs an editor mounted outside `contentDOM`. The
 * cell editor is a portaled panel over the grid and changes only that cell.
 */
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
        const { alignment, prefix } = tableCellAlignment(model, index, column);
        if (cell)
          appendTableInline(element, cell, this.markup, {
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
        if (view && model && !view.state.readOnly) {
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
            button.addEventListener("click", (event) => {
              event.preventDefault();
              event.stopPropagation();
              openTableCellEditor(view, model, targetRow, targetColumn, { kind: scope });
            });
            element.append(button);
          };
          if (head) scopeButton("column", column, 0, column);
          if (!column) scopeButton("row", index, index, 0);
          element.addEventListener(
            "mousedown",
            (event) => {
              if (event.button !== 0 || event.target.closest("[data-table-select]")) return;
              event.preventDefault();
              event.stopPropagation();
            },
            { capture: true },
          );
          element.addEventListener("click", (event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            event.stopPropagation();
            // Open after the pointer sequence completes. A popup positioned
            // above a low cell can cover its own mouseup target; opening on
            // mousedown retargeted that click to body and immediately closed
            // the editor through the outside-click handler.
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
    wrapper.append(table);
    return wrapper;
  }

  ignoreEvent(event) {
    // Mouse input belongs to the visual cell editor. Keyboard history and
    // navigation still belong to CodeMirror after the grid regains focus.
    return event.type !== "keydown";
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
    // disc, circle, square — the sequence a browser walks as `<ul>` nests.
    span.textContent = ["\u2022", "\u25e6", "\u25aa"][this.depth % 3];
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
 * title, language, whether a cover is on — and clicking it, or moving the caret
 * into it, brings the YAML straight back for editing.
 */
class FrontMatterWidget extends WidgetType {
  constructor(markup, from) {
    super();
    this.markup = markup;
    this.from = from;
  }

  eq(other) {
    return other.markup === this.markup && other.from === this.from;
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
    wrapper.addEventListener("click", () => {
      view.dispatch({ selection: { anchor: this.from }, scrollIntoView: true });
      view.focus();
    });
    wrapper.className = "cm-md-frontmatter";
    block.append(wrapper);
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
    if (!this.readOnly) {
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "icon-button cm-disclosure-edit";
      edit.title = document.documentElement.lang.startsWith("fa")
        ? "ویرایش متن بخش"
        : "Edit disclosure source";
      edit.setAttribute("aria-label", edit.title);
      edit.append(spriteIcon("pencil"));
      edit.addEventListener("click", () => {
        view.dispatch({ selection: { anchor: this.from }, scrollIntoView: true });
        view.focus();
      });
      group.append(edit);
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

function buildBlockDecorations(state) {
  const active = activeLines(state);
  const items = [];

  // CodeMirror parses incrementally, so `syntaxTree` covers only what it has
  // reached — on a 60k-character guide that was 6% of the document, and every
  // table past the first few kilobytes stayed as raw pipes. A state field has
  // no viewport to narrow to, so the parse is forced within a budget and
  // whatever is ready is used if the budget runs out.
  const tree = ensureSyntaxTree(state, state.doc.length, PARSE_BUDGET_MS) || syntaxTree(state);

  tree.iterate({
    enter: (node) => {
      if (node.name === "Frontmatter" && !spansActiveLine(state, active, node)) {
        items.push([
          node.from,
          node.to,
          Decoration.replace({
            widget: new FrontMatterWidget(state.doc.sliceString(node.from, node.to), node.from),
            block: true,
          }),
        ]);
        return false;
      }
      if (node.name === "HTMLBlock" && !spansActiveLine(state, active, node)) {
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
      if (node.name === "Table" && !spansActiveLine(state, active, node)) {
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

  items.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const builder = new RangeSetBuilder();
  for (const [from, to, decoration] of items) builder.add(from, to, decoration);
  return builder.finish();
}

let blockWidgetFieldInstance = null;

/**
 * The block decoration field.
 *
 * It walks only the containers a block can nest in, so its cost is set by how
 * many blocks a document has rather than by how long it is. That is what let
 * the old size bound go: a document is no longer too big to render.
 */
export function createBlockWidgetField() {
  let renderedFor = "";
  blockWidgetFieldInstance = StateField.define({
    create(state) {
      renderedFor = activeLineKey(state);
      return buildBlockDecorations(state);
    },
    update(value, transaction) {
      // A selection only changes what is drawn when it changes *which lines*
      // are being edited: those show their source, the rest stay rendered.
      // Rebuilding on every selection meant walking the whole syntax tree to
      // move the caret one character — 17ms per arrow key on a 195,000
      // character document, for a result identical to the one discarded.
      if (!transaction.docChanged) {
        const key = activeLineKey(transaction.state);
        if (
          key === renderedFor &&
          transaction.startState.facet(mathRenderer) === transaction.state.facet(mathRenderer)
        )
          return value;
        renderedFor = key;
      } else {
        renderedFor = activeLineKey(transaction.state);
      }
      return buildBlockDecorations(transaction.state);
    },
    provide: (field) => EditorView.decorations.from(field),
  });
  return blockWidgetFieldInstance;
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
  const set = blockWidgetFieldInstance ? state.field(blockWidgetFieldInstance, false) : null;
  if (!set) return ranges;
  const cursor = set.iter();
  while (cursor.value) {
    ranges.push([cursor.from, cursor.to]);
    cursor.next();
  }
  return ranges;
}
