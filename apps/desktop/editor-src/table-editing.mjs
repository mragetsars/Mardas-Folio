import { spriteIcon } from "../frontend/js/ui/icons.mjs";
/** Table controls edit cell drafts while CodeMirror owns the Markdown source. */
import { syntaxTree } from "@codemirror/language";
import { Transaction } from "@codemirror/state";
import { isolateHistory } from "@codemirror/commands";
import { ViewPlugin } from "@codemirror/view";
import { markdownLanguage } from "@codemirror/lang-markdown";
import { mathAndFootnotes } from "./markdown-extras.mjs";

const cellParser = markdownLanguage.parser.configure([mathAndFootnotes]);
import { appendTableInline, tableInlineText, tableInlineSource } from "./table-inline.mjs";
import { authoringShortcutKey } from "../frontend/js/core/keyboard-shortcuts.mjs";

const sessions = new WeakMap();
const cellFormats = new Set(["bold", "italic", "code"]);
const documentActions =
  "[data-editor-command], #heading-menu-button, #insert-menu-button, #insert-image, #workspace-import-asset, #import-asset, #citation-list button, #asset-list button";
// Lezer omits empty TableCell nodes. Physical pipe boundaries preserve their
// column positions, including an empty header and a newly inserted column.
export function tableRowCells(raw, from = 0) {
  const separators = [];
  let slashes = 0;
  for (let index = 0; index < raw.length; index += 1) {
    const char = raw[index];
    if (char === "|" && slashes % 2 === 0) separators.push(index);
    slashes = char === "\\" ? slashes + 1 : 0;
  }
  const boundaries = [-1, ...separators, raw.length];
  const result = [];
  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const start = boundaries[index] + 1,
      end = boundaries[index + 1];
    if (
      (index === 0 && separators[0] === raw.search(/\S/)) ||
      (index === boundaries.length - 2 && separators.at(-1) === raw.trimEnd().length - 1)
    )
      continue;
    const value = raw.slice(start, end),
      text = value.trim();
    const leading = text ? value.length - value.trimStart().length : Math.floor(value.length / 2);
    result.push({
      from: from + start + leading,
      to: from + start + leading + text.length,
      raw: text,
    });
  }
  return result;
}

export function tableModel(markup, from, syntax) {
  const offset = syntax.from;
  const model = { from, to: from + markup.length, rows: [], delimiter: null };
  for (let row = syntax.firstChild; row; row = row.nextSibling) {
    if (!["TableHeader", "TableRow", "TableDelimiter"].includes(row.name)) continue;
    const record = {
      from: from + row.from - offset,
      to: from + row.to - offset,
      raw: markup.slice(row.from - offset, row.to - offset),
      cells: tableRowCells(
        markup.slice(row.from - offset, row.to - offset),
        from + row.from - offset,
      ),
    };
    if (row.name === "TableDelimiter") model.delimiter = record;
    else model.rows.push(record);
  }
  model.columns = model.rows[0]?.cells.length || 0;
  return model;
}

/** Preserve existing escapes; a newly typed pipe must remain inside its cell. */
export function tableCellSource(value) {
  let result = "",
    slashes = 0;
  for (const char of String(value).replace(/\r?\n/g, "<br>")) {
    if (char === "|" && slashes % 2 === 0) result += "\\";
    result += char;
    slashes = char === "\\" ? slashes + 1 : 0;
  }
  return result;
}

function delimiterCells(raw) {
  return raw
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((value) => value.trim());
}

const alignments = ["auto", "left", "center", "right"];
const metadataMarker =
  /^(?:<!--folio-(align:(auto|left|center|right)|width:([1-9][0-9]?|100))-->)\s*/;

export function tableCellMetadata(raw = "") {
  let alignment = null;
  let width = null;
  let prefix = 0;
  for (
    let match = metadataMarker.exec(raw);
    match;
    match = metadataMarker.exec(raw.slice(prefix))
  ) {
    if (match[2] && alignment === null) alignment = match[2];
    if (match[3] && width === null) width = Number(match[3]);
    prefix += match[0].length;
  }
  return { alignment, width, prefix };
}

export function tableCellAlignment(model, row, column) {
  const info = tableCellMetadata(model?.rows[row]?.cells[column]?.raw);
  return { ...info, alignment: info.alignment || "auto" };
}

function writeCellMetadata(text, { alignment, width }) {
  const marks = [];
  if (alignment) marks.push("<!--folio-align:" + alignment + "-->");
  if (width) marks.push("<!--folio-width:" + width + "-->");
  return [...marks, text].filter(Boolean).join(" ");
}

export function autoCellAlignment(text) {
  const words = text.trim().split(/\s+/u);
  return words.length === 1 && words[0] ? "center" : "start";
}

function selectedCells(model, row, column, selection) {
  if (selection.kind === "row") return Array.from({ length: model.columns }, (_, c) => [row, c]);
  if (selection.kind === "column") return model.rows.map((_, r) => [r, column]);
  return selection.cells || [[row, column]];
}

/** Folio stores only explicit per-cell alignment as metadata. */
export function tableCellChanges(model, coordinates, alignment, content) {
  const rows = new Map();
  for (const [row, column] of coordinates) {
    const record = model.rows[row];
    if (!record || column < 0 || column >= model.columns) continue;
    const raw = record.cells[column]?.raw || "";
    const parsed = tableCellAlignment(model, row, column);
    const text = content ?? raw.slice(parsed.prefix);
    const insert =
      alignment == null
        ? raw.slice(0, parsed.prefix) + text
        : writeCellMetadata(text, {
            alignment: alignment === "auto" ? null : alignment,
            width: parsed.width,
          });
    if (insert === raw) continue;
    if (!rows.has(row)) rows.set(row, new Map());
    rows.get(row).set(column, insert);
  }
  const changes = [];
  for (const [row, updates] of rows) {
    const record = model.rows[row];
    if ([...updates.keys()].some((column) => !record.cells[column])) {
      const cells = Array.from(
        { length: Math.max(model.columns, record.cells.length) },
        (_, column) => updates.get(column) ?? record.cells[column]?.raw ?? "",
      );
      changes.push({ from: record.from, to: record.to, insert: serializeRow(cells) });
    } else {
      for (const [column, insert] of updates) {
        const { from, to } = record.cells[column];
        changes.push({ from, to, insert });
      }
    }
  }
  return changes.sort((a, b) => a.from - b.from);
}

const serializeRow = (cells) => `| ${cells.join(" | ")} |`;

/** Structural edits touch only table rows, preserving surrounding block/list prefixes. */
export function tableStructureChanges(model, document, action, rowIndex, columnIndex) {
  const rows = model.rows;
  if (!rows.length || !model.delimiter) return [];
  if (action === "add-row" || action === "add-row-before") {
    if (action === "add-row-before" && rowIndex === 0) return [];
    const preceding = action === "add-row-before" ? rowIndex - 1 : rowIndex;
    const row = preceding === 0 ? model.delimiter : rows[preceding];
    const reference = document.lineAt(model.delimiter.from);
    const prefix = reference.text.slice(0, model.delimiter.from - reference.from);
    return [{ from: row.to, insert: `\n${prefix}${serializeRow(Array(model.columns).fill(""))}` }];
  }
  if (action === "delete-row") {
    if (rowIndex === 0) return [];
    const line = document.lineAt(rows[rowIndex].from);
    return [{ from: line.from, to: Math.min(document.length, line.to + 1), insert: "" }];
  }
  if (action === "move-row-before" || action === "move-row-after") {
    const other = rowIndex + (action.endsWith("before") ? -1 : 1);
    if (rowIndex === 0 || other < 1 || other >= rows.length) return [];
    const row = rows[rowIndex];
    const target = rows[other];
    return [
      { from: row.from, to: row.to, insert: target.raw },
      { from: target.from, to: target.to, insert: row.raw },
    ].sort((left, right) => left.from - right.from);
  }
  if (action === "delete-column" && model.columns <= 1) return [];
  const moving = action === "move-column-before" || action === "move-column-after";
  const inserting = action === "add-column" || action === "add-column-before";
  if (!moving && !inserting && action !== "delete-column") return [];
  const target = columnIndex + (action.endsWith("before") ? -1 : 1);
  if (moving && (target < 0 || target >= model.columns)) return [];
  const change = (row, cells) => {
    const values = Array.from(
      { length: Math.max(model.columns, cells.length) },
      (_, index) => cells[index] || "",
    );
    if (moving) {
      [values[columnIndex], values[target]] = [values[target], values[columnIndex]];
    } else if (inserting) {
      const index = action === "add-column-before" ? columnIndex : columnIndex + 1;
      values.splice(index, 0, row === model.delimiter ? "---" : "");
    } else values.splice(columnIndex, 1);
    return { from: row.from, to: row.to, insert: serializeRow(values) };
  };
  return [
    ...rows.map((row) =>
      change(
        row,
        row.cells.map((cell) => cell.raw),
      ),
    ),
    change(model.delimiter, delimiterCells(model.delimiter.raw)),
  ].sort((a, b) => a.from - b.from);
}

export function columnWidthChanges(model, widths) {
  return widths
    .flatMap(([column, width]) => {
      const cell = model.rows[0]?.cells[column];
      if (!cell) return [];
      const metadata = tableCellMetadata(cell.raw);
      const insert = writeCellMetadata(cell.raw.slice(metadata.prefix), { ...metadata, width });
      return insert === cell.raw ? [] : [{ from: cell.from, to: cell.to, insert }];
    })
    .sort((a, b) => a.from - b.from);
}

function fitColumnWidth(wrapper, column) {
  const table = wrapper?.querySelector("table");
  if (!table?.offsetWidth) return null;
  const context = wrapper.ownerDocument.createElement("canvas").getContext("2d");
  if (!context) return null;
  let width = 0;
  for (const cell of table.querySelectorAll('[data-table-column="' + column + '"]')) {
    const style = getComputedStyle(cell);
    context.font = style.fontWeight + " " + style.fontSize + " " + style.fontFamily;
    const content = Math.max(
      ...tableInlineText(cell)
        .split("\n")
        .map((line) => context.measureText(line.trim()).width),
    );
    width = Math.max(
      width,
      content + parseFloat(style.paddingLeft) + parseFloat(style.paddingRight),
    );
  }
  return Math.max(8, Math.min(85, Math.ceil((width * 100) / table.offsetWidth)));
}

function refreshTable(view, from) {
  const editor = sessions.get(view);
  const before = view.state.doc.length;
  if (editor && !editor.commit()) return null;
  const position =
    editor && editor.model.from < from ? from + view.state.doc.length - before : from;
  return modelAt(view, position);
}

export function resizeTableColumns(view, from, widths) {
  const current = refreshTable(view, from);
  if (current) dispatchEdit(view, columnWidthChanges(current, widths));
}

export function tableExtendButton(view, model, kind) {
  const row = kind === "row";
  const fa = document.documentElement.lang.startsWith("fa");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "cm-table-extend";
  button.dataset.tableExtend = kind;
  button.textContent = "+";
  button.title = row
    ? fa
      ? "افزودن ردیف با کلیک یا کشیدن"
      : "Click or drag to add rows"
    : fa
      ? "افزودن ستون با کلیک یا کشیدن"
      : "Click or drag to add columns";
  button.ariaLabel = button.title;
  const append = (count) => {
    const current = refreshTable(view, model.from);
    if (!current?.delimiter || view.state.readOnly) return;
    sessions.get(view)?.close(false, false);
    if (row) {
      const line = view.state.doc.lineAt(current.delimiter.from);
      const prefix = line.text.slice(0, current.delimiter.from - line.from);
      const insert = ("\n" + prefix + serializeRow(Array(current.columns).fill(""))).repeat(count);
      dispatchEdit(view, [
        { from: (current.rows[1] ? current.rows.at(-1) : current.delimiter).to, insert },
      ]);
    } else {
      const changes = [...current.rows, current.delimiter]
        .map((record) => {
          const filler = record === current.delimiter ? "---" : "";
          const cells = record.cells.map(({ raw }) => raw);
          while (cells.length < current.columns) cells.push(filler);
          cells.splice(current.columns, 0, ...Array(count).fill(filler));
          return { from: record.from, to: record.to, insert: serializeRow(cells) };
        })
        .sort((a, b) => a.from - b.from);
      dispatchEdit(view, changes);
    }
    view.focus();
  };
  let gesture;
  button.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const direction = row || button.closest("table, .cm-md-table")?.dir !== "rtl" ? 1 : -1;
    gesture = { start: row ? event.clientY : event.clientX, direction, count: 1 };
    button.setPointerCapture(event.pointerId);
  });
  button.addEventListener("pointermove", (event) => {
    if (!gesture) return;
    const position = row ? event.clientY : event.clientX;
    gesture.count = Math.min(
      20,
      1 +
        Math.max(0, Math.floor(((position - gesture.start) * gesture.direction) / (row ? 26 : 42))),
    );
    button.textContent = "+" + gesture.count;
  });
  button.addEventListener("pointerup", () => {
    if (!gesture) return;
    const { count } = gesture;
    gesture = null;
    button.textContent = "+";
    append(count);
  });
  button.addEventListener("pointercancel", () => {
    gesture = null;
    button.textContent = "+";
  });
  button.addEventListener("click", (event) => {
    if (event.detail === 0) append(1);
  });
  return button;
}

export function createTableActions(view, model) {
  const labels = tableLabels();
  const options = document.createElement("div");
  options.className = "cm-table-actions";
  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "cm-table-actions-trigger";
  trigger.ariaLabel = trigger.title = labels.tableOptions;
  trigger.setAttribute("aria-expanded", "false");
  trigger.append(spriteIcon("table"));
  const actions = document.createElement("div");
  actions.className = "cm-table-actions-menu";
  actions.popover = "auto";
  trigger.addEventListener("click", () => {
    if (actions.matches(":popover-open")) actions.hidePopover();
    else {
      actions.showPopover();
      const anchor = trigger.getBoundingClientRect();
      const menu = actions.getBoundingClientRect();
      actions.style.left =
        Math.max(8, Math.min(anchor.right + 6, innerWidth - menu.width - 8)) + "px";
      actions.style.top = Math.max(8, Math.min(anchor.top, innerHeight - menu.height - 8)) + "px";
      copy.focus({ preventScroll: true });
    }
  });
  actions.addEventListener("toggle", () =>
    trigger.setAttribute("aria-expanded", String(actions.matches(":popover-open"))),
  );
  options.append(trigger);
  const copy = document.createElement("button");
  copy.type = "button";
  copy.textContent = labels.tableCopy;
  const status = document.createElement("span");
  status.setAttribute("role", "status");
  copy.addEventListener("click", async () => {
    const current = refreshTable(view, model.from);
    if (!current) return;
    try {
      await navigator.clipboard.writeText(view.state.doc.sliceString(current.from, current.to));
      status.textContent = labels.tableCopied;
    } catch {
      status.textContent = labels.tableCopyFailed;
    }
  });
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = labels.tableRemove;
  remove.addEventListener("click", () => {
    const current = refreshTable(view, model.from);
    if (!current || view.state.readOnly) return;
    sessions.get(view)?.close(false, false);
    dispatchEdit(view, [{ from: current.from, to: current.to, insert: "" }]);
    view.focus();
  });
  actions.append(copy, remove, status);
  options.append(actions);
  return options;
}

function modelAt(view, position) {
  let node = syntaxTree(view.state).resolveInner(position, 1);
  while (node && node.name !== "Table") node = node.parent;
  return node ? tableModel(view.state.doc.sliceString(node.from, node.to), node.from, node) : null;
}

const translations = {
  en: {
    title: "Edit table cell",
    row: "Row",
    column: "Column",
    content: "Cell content",
    alignment: "Alignment",
    rowSelection: "Selected row",
    columnSelection: "Selected column",
    cellsSelection: "Selected cells",
    selectRow: "Select row",
    selectColumn: "Select column",
    auto: "Auto",
    left: "Left",
    center: "Center",
    right: "Right",
    help: "Tab: next cell · Shift+Tab: previous · Enter: apply · Esc: cancel. Alt+F10: cell actions; use arrows or Home/End, Enter to run, Esc to return to the text. Inline Markdown stays in this cell.",
    apply: "Apply",
    cancel: "Cancel",
    addRow: "Add row below",
    addRowBefore: "Add row above",
    moveRowBefore: "Move row up",
    moveRowAfter: "Move row down",
    addColumnBefore: "Add column before",
    moveColumnBefore: "Move column before",
    moveColumnAfter: "Move column after",
    resizeColumn: "Resize column",
    fitColumn: "Fit to contents",
    tableOptions: "Table actions",
    tableCopy: "Copy as Markdown",
    tableCopied: "Table copied",
    tableCopyFailed: "Copy failed",
    tableRemove: "Remove table",
    deleteRow: "Delete row",
    addColumn: "Add column after",
    deleteColumn: "Delete column",
    bold: "Bold",
    italic: "Italic",
    code: "Code",
    table: "Table. Press Enter to edit a cell.",
    conflict: "This cell changed elsewhere. Copy your draft before reopening it.",
  },
  fa: {
    title: "ویرایش سلول جدول",
    row: "ردیف",
    column: "ستون",
    content: "محتوای سلول",
    alignment: "تراز",
    rowSelection: "ردیف انتخاب‌شده",
    columnSelection: "ستون انتخاب‌شده",
    cellsSelection: "سلول‌های انتخاب‌شده",
    selectRow: "انتخاب ردیف",
    selectColumn: "انتخاب ستون",
    auto: "خودکار",
    left: "چپ",
    center: "وسط",
    right: "راست",
    help: "Tab: سلول بعدی · Shift+Tab: قبلی · Enter: اعمال · Esc: لغو. Alt+F10: ابزارهای سلول؛ جهت‌نما یا Home/End برای انتخاب، Enter برای اجرا و Esc برای بازگشت به متن. قالب‌بندی Markdown فقط در همین سلول است.",
    apply: "اعمال",
    cancel: "لغو",
    addRow: "افزودن ردیف پایین",
    addRowBefore: "افزودن ردیف بالا",
    moveRowBefore: "انتقال ردیف به بالا",
    moveRowAfter: "انتقال ردیف به پایین",
    addColumnBefore: "افزودن ستون قبل",
    moveColumnBefore: "انتقال ستون به قبل",
    moveColumnAfter: "انتقال ستون به بعد",
    resizeColumn: "تغییر عرض ستون",
    fitColumn: "تنظیم عرض با محتوا",
    tableOptions: "عملیات جدول",
    tableCopy: "کپی به‌صورت Markdown",
    tableCopied: "جدول کپی شد",
    tableCopyFailed: "کپی ناموفق بود",
    tableRemove: "حذف جدول",
    deleteRow: "حذف ردیف",
    addColumn: "افزودن ستون بعدی",
    deleteColumn: "حذف ستون",
    bold: "پررنگ",
    italic: "ایتالیک",
    code: "کد",
    table: "جدول؛ برای ویرایش سلول Enter را بزن.",
    conflict: "این سلول در جای دیگری تغییر کرده است؛ پیش از بازکردن دوباره، متن خود را کپی کن.",
  },
};

export const tableLabels = () =>
  translations[document.documentElement.lang.startsWith("fa") ? "fa" : "en"];

function dispatchEdit(view, changes) {
  if (!changes.length || view.state.readOnly) return;
  view.dispatch({
    changes,
    annotations: [Transaction.userEvent.of("input.table"), isolateHistory.of("full")],
  });
}

class CellEditor {
  constructor(view, model, row, column, selection) {
    this.view = view;
    this.model = model;
    this.labels = tableLabels();
    this.selection = selection;
    this.panel = document.createElement("section");
    this.panel.className = "cm-table-cell-editor";
    this.panel.setAttribute("role", "group");
    this.panel.dir = document.documentElement.dir;
    this.input = document.createElement("div");
    this.input.className = "cm-table-cell-input";
    this.input.contentEditable = "true";
    this.input.setAttribute("role", "textbox");
    this.input.setAttribute("aria-multiline", "true");
    this.input.setAttribute("aria-label", this.labels.content);
    this.input.setAttribute("aria-keyshortcuts", "Alt+F10");
    this.input.dir = "auto";
    this.input.addEventListener("input", () => this.updateAlignment());
    this.input.addEventListener("paste", (event) => {
      event.preventDefault();
      document.execCommand("insertText", false, event.clipboardData.getData("text/plain"));
    });
    document.body.append(this.input);
    const alignment = document.createElement("div");
    alignment.className = "cm-table-cell-alignment";
    alignment.setAttribute("role", "group");
    alignment.setAttribute("aria-label", this.labels.alignment);
    this.alignments = alignments.map((value) => {
      const control = this.button(
        this.labels[value],
        () => {
          this.pendingAlignment = value;
          if (this.commit()) {
            if (this.selection.kind !== "cell") this.close(false);
            else this.input.focus({ preventScroll: true });
          }
        },
        alignment,
      );
      control.dataset.cellAlignment = value;
      control.title = control.ariaLabel = this.labels[value];
      control.replaceChildren(spriteIcon("align-" + value));
      return control;
    });
    this.panel.append(alignment);
    this.error = document.createElement("p");
    this.error.className = "cm-table-cell-error";
    this.error.setAttribute("role", "alert");
    this.error.hidden = true;
    this.panel.append(this.error);
    const structure = (this.structurePanel = document.createElement("div"));
    structure.className = "cm-table-cell-structure";
    this.structureButtons = [
      ["row", "add-row-before", "addRowBefore"],
      ["row", "add-row", "addRow"],
      ["row", "move-row-before", "moveRowBefore"],
      ["row", "move-row-after", "moveRowAfter"],
      ["row", "delete-row", "deleteRow"],
      ["column", "add-column-before", "addColumnBefore"],
      ["column", "add-column", "addColumn"],
      ["column", "move-column-before", "moveColumnBefore"],
      ["column", "move-column-after", "moveColumnAfter"],
      ["column", "fit-column", "fitColumn"],
      ["column", "delete-column", "deleteColumn"],
    ].map(([kind, action, label]) => {
      const button = this.button(this.labels[label], () => this.structure(action), structure);
      button.dataset.tableAction = action;
      return { kind, action, button };
    });
    this.panel.append(structure);
    document.body.append(this.panel);
    this.input.addEventListener("keydown", (event) => this.key(event));
    this.panel.addEventListener("keydown", (event) => this.actionKey(event));
    this.outside = (event) => {
      if (this.panel.contains(event.target) || this.input.contains(event.target)) return;
      // Keep an unsupported action from falling through to the editor's old
      // selection, including clicks dispatched while a host refresh is busy.
      const action = event.target.closest?.(documentActions);
      if (
        action &&
        (this.selection.kind !== "cell" || !cellFormats.has(action.dataset.editorCommand))
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
        this.input.focus();
        return;
      }
      const command = event.target.closest?.("[data-editor-command]")?.dataset.editorCommand;
      if (this.selection.kind === "cell" && cellFormats.has(command)) return;
      // Another cell handles committing and opening its own editor.
      if (event.target.closest?.(".cm-md-table")) return;
      // Commit before the target's click handler, once the browser has fixed
      // the event path. Committing on mousedown rebuilds the document tabs
      // and removes the target before mouseup, swallowing that first click.
      if (!this.commit()) {
        event.preventDefault();
        event.stopImmediatePropagation();
        this.input.focus();
        return;
      }
      this.close(false, false);
    };
    this.toolbarClick = (event) => {
      if (this.panel.contains(event.target) || this.input.contains(event.target)) return;
      const command = event.target.closest?.("[data-editor-command]")?.dataset.editorCommand;
      const marker = { bold: "**", italic: "*", code: "`" }[command];
      if (!marker) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      this.format(marker);
    };
    this.keepDraftFocus = (event) => {
      if (
        this.selection.kind === "cell" &&
        cellFormats.has(event.target.closest?.("[data-editor-command]")?.dataset.editorCommand)
      )
        event.preventDefault();
    };
    document.addEventListener("mousedown", this.keepDraftFocus, true);
    this.saveKey = (event) => {
      const key = authoringShortcutKey(event);
      if (!["s", "f", "h", "p", "o", "n", "\\", "+", "=", "-", "0"].includes(key)) return;
      if (!this.commit()) {
        event.preventDefault();
        event.stopImmediatePropagation();
        this.input.focus();
        return;
      }
      this.close(false, false);
    };
    this.windowBlur = () => this.commit();
    document.addEventListener("click", this.outside, true);
    document.addEventListener("click", this.toolbarClick, true);
    document.addEventListener("keydown", this.saveKey, true);
    window.addEventListener("blur", this.windowBlur);
    this.scroll = () => this.reposition();
    view.scrollDOM.addEventListener("scroll", this.scroll, { passive: true });
    this.guardDocumentActions();
    this.open(row, column);
  }

  guardDocumentActions() {
    this.disabledActions = new Map();
    const guard = (element) => {
      if (this.selection.kind === "cell" && cellFormats.has(element.dataset.editorCommand)) return;
      if (!this.disabledActions.has(element)) this.disabledActions.set(element, element.disabled);
      if (!element.disabled) element.disabled = true;
    };
    const collect = (node) => {
      if (!(node instanceof Element)) return;
      if (node.matches(documentActions)) guard(node);
      node.querySelectorAll(documentActions).forEach(guard);
    };
    collect(document.body);
    // Workspace renders refresh disabled state and rebuild asset/citation rows.
    // Preserve the cell context across those refreshes instead of leaving a
    // briefly re-enabled button that can write at an unrelated document caret.
    this.actionObserver = new MutationObserver((records) => {
      for (const record of records) {
        if (record.type === "attributes") {
          if (this.disabledActions.has(record.target)) guard(record.target);
        } else record.addedNodes.forEach(collect);
      }
    });
    this.actionObserver.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["disabled"],
    });
  }

  button(text, action, parent) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("click", action);
    parent.append(button);
    return button;
  }

  open(row, column) {
    this.row = row;
    this.column = column;
    this.pendingAlignment = null;
    this.source = this.view.state.doc.sliceString(this.model.from, this.model.to);
    this.cell = this.model.rows[row]?.cells[column];
    this.original = this.cell?.raw || "";
    const source = this.original.slice(tableCellMetadata(this.original).prefix);
    this.input.replaceChildren();
    const markup = "| Cell |\n| --- |\n| " + source + " |";
    cellParser.parse(markup).iterate({
      enter: (node) => {
        if (node.name === "TableCell" && node.from > 15)
          appendTableInline(this.input, node.node, markup, { preserveSource: true });
      },
    });
    this.initialDraft = tableInlineSource(this.input);
    const { kind } = this.selection;
    const single = kind === "cell";
    this.panel.dataset.selection = kind;
    this.panel.setAttribute("role", kind === "row" || kind === "column" ? "menu" : "group");
    this.panel.setAttribute(
      "aria-label",
      single ? this.labels.alignment : this.labels[kind + "Selection"],
    );
    this.input.hidden = !single;
    this.structurePanel.hidden = kind !== "row" && kind !== "column";
    const unavailable = {
      "add-row-before": row === 0,
      "move-row-before": row < 2,
      "move-row-after": row === 0 || row + 1 >= this.model.rows.length,
      "delete-row": row === 0,
      "move-column-before": column === 0,
      "move-column-after": column + 1 >= this.model.columns,
      "delete-column": this.model.columns <= 1,
    };
    for (const control of this.structureButtons) {
      control.button.hidden = control.kind !== kind;
      control.button.disabled = Boolean(unavailable[control.action]);
      control.button.setAttribute("role", "menuitem");
    }
    this.error.hidden = true;
    this.updateAlignment();
    this.reposition();
    if (single) {
      this.input.focus({ preventScroll: true });
      const selection = document.getSelection();
      selection.selectAllChildren(this.input);
    } else this.actions()[0]?.focus({ preventScroll: true });
    requestAnimationFrame(() => this.reposition());
  }

  coordinates() {
    return selectedCells(this.model, this.row, this.column, this.selection);
  }

  table() {
    return [...this.view.dom.querySelectorAll(".cm-md-table")].find(
      (element) => Number(element.dataset.tableFrom) === this.model.from,
    );
  }

  anchor() {
    return this.table()?.querySelector(
      `[data-table-row="${this.row}"][data-table-column="${this.column}"]`,
    );
  }

  updateAlignment() {
    const current = new Set(
      this.coordinates().map(
        ([row, column]) => tableCellAlignment(this.model, row, column).alignment,
      ),
    );
    const alignment = this.pendingAlignment ?? (current.size === 1 ? [...current][0] : null);
    for (const button of this.alignments) {
      button.setAttribute("aria-pressed", String(button.dataset.cellAlignment === alignment));
    }
    if (this.selection.kind === "cell") {
      const rendered = tableInlineText(this.input);
      this.input.style.textAlign = alignment === "auto" ? autoCellAlignment(rendered) : alignment;
    }
  }

  reposition() {
    if (!this.panel.isConnected) return;
    const anchor = this.anchor();
    this.panel.hidden = !anchor;
    this.input.hidden = !anchor || this.selection.kind !== "cell";
    if (!anchor) return;
    const grid = this.table();
    grid.dataset.activeRow = this.row;
    grid.dataset.activeColumn = this.column;
    const chosen = new Set(this.coordinates().map(([row, column]) => row + ":" + column));
    for (const cell of grid.querySelectorAll("[data-table-row][data-table-column]")) {
      cell.classList.toggle(
        "cm-table-cell-active",
        chosen.has(cell.dataset.tableRow + ":" + cell.dataset.tableColumn),
      );
      cell.classList.toggle("cm-table-cell-drafting", cell === anchor && !this.input.hidden);
      cell.querySelectorAll("[data-table-select]").forEach((button) => {
        const scope = button.dataset.tableSelect;
        button.classList.toggle(
          "cm-table-handle-active",
          scope === "row"
            ? +cell.dataset.tableRow === this.row
            : +cell.dataset.tableColumn === this.column,
        );
        button.setAttribute(
          "aria-expanded",
          String(
            this.selection.kind === scope &&
              (scope === "row"
                ? +cell.dataset.tableRow === this.row
                : +cell.dataset.tableColumn === this.column),
          ),
        );
      });
    }
    const viewport = this.view.scrollDOM.getBoundingClientRect();
    const content = anchor.querySelector(".cm-table-cell-content");
    if (content && !this.input.hidden) {
      const rect = content.getBoundingClientRect();
      const style = getComputedStyle(anchor);
      Object.assign(this.input.style, {
        left: rect.left + "px",
        top: rect.top + "px",
        width: rect.width + "px",
        height: Math.max(rect.height, 22) + "px",
        font: style.font,
        clipPath:
          "inset(" +
          [
            Math.max(0, viewport.top - rect.top),
            Math.max(0, rect.right - viewport.right),
            Math.max(0, rect.bottom - viewport.bottom),
            Math.max(0, viewport.left - rect.left),
          ]
            .map((value) => value + "px")
            .join(" ") +
          ")",
      });
    }
    const handle = grid.querySelector(
      '[data-table-select="' + this.selection.kind + '"][aria-expanded="true"]',
    );
    const rect = (handle || anchor).getBoundingClientRect();
    const visible = rect.bottom >= viewport.top && rect.top < viewport.bottom;
    this.panel.hidden = !visible;
    if (!visible) return;
    const panel = this.panel.getBoundingClientRect();
    const above = this.selection.kind === "cell" && rect.top - panel.height - 6 >= viewport.top;
    const x = rect.left + (rect.width - panel.width) / 2;
    const y = above ? rect.top - panel.height - 6 : rect.bottom + 6;
    this.panel.style.left = Math.max(8, Math.min(x, innerWidth - panel.width - 8)) + "px";
    this.panel.style.top = Math.max(8, Math.min(y, innerHeight - panel.height - 8)) + "px";
  }

  format(marker) {
    if (this.selection.kind !== "cell") return;
    const selection = document.getSelection();
    if (!this.input.contains(selection.anchorNode) || !this.input.contains(selection.focusNode))
      this.input.focus();
    if (marker !== "`") {
      document.execCommand(marker === "**" ? "bold" : "italic");
    } else if (selection.rangeCount && this.input.contains(selection.anchorNode)) {
      const range = selection.getRangeAt(0);
      const existing = range.startContainer.parentElement?.closest("code");
      if (existing && this.input.contains(existing)) {
        existing.replaceWith(...existing.childNodes);
      } else if (!range.collapsed) {
        const code = document.createElement("code");
        code.textContent = range.toString();
        range.deleteContents();
        range.insertNode(code);
        selection.selectAllChildren(code);
      }
    }
    this.updateAlignment();
  }

  commit() {
    if (this.view.state.readOnly || !this.error.hidden) return false;
    const single = this.selection.kind === "cell";
    const originalText = this.original.slice(tableCellMetadata(this.original).prefix);
    const draft = single ? tableInlineSource(this.input) : null;
    const value = single
      ? draft === this.initialDraft
        ? originalText
        : tableCellSource(draft)
      : undefined;
    if (this.pendingAlignment == null && (!single || value === originalText)) return true;
    const doc = this.view.state.doc;
    const current = modelAt(this.view, this.model.from);
    if (
      !current ||
      (single && this.cell
        ? doc.sliceString(this.cell.from, this.cell.to) !== this.original
        : current && doc.sliceString(current.from, current.to) !== this.source)
    ) {
      this.error.textContent = this.labels.conflict;
      this.error.hidden = false;
      return false;
    }
    const changes = tableCellChanges(current, this.coordinates(), this.pendingAlignment, value);
    this.committing = true;
    try {
      dispatchEdit(this.view, changes);
    } finally {
      this.committing = false;
    }
    this.model = modelAt(this.view, this.model.from);
    if (!this.model) {
      this.close(false);
      return false;
    }
    this.source = this.view.state.doc.sliceString(this.model.from, this.model.to);
    this.cell = this.model.rows[this.row]?.cells[this.column];
    this.original = this.cell?.raw || "";
    this.initialDraft = draft;
    this.pendingAlignment = null;
    this.updateAlignment();
    requestAnimationFrame(() => this.reposition());
    return true;
  }

  structure(action) {
    if (!this.commit()) return;
    const changes =
      action === "fit-column"
        ? columnWidthChanges(this.model, [[this.column, fitColumnWidth(this.table(), this.column)]])
        : tableStructureChanges(this.model, this.view.state.doc, action, this.row, this.column);
    this.committing = true;
    try {
      dispatchEdit(this.view, changes);
    } finally {
      this.committing = false;
    }
    this.model = modelAt(this.view, this.model.from);
    if (!this.model) {
      this.close(false);
      return;
    }
    const rowOffset = { "add-row": 1, "move-row-before": -1, "move-row-after": 1 };
    const columnOffset = { "add-column": 1, "move-column-before": -1, "move-column-after": 1 };
    const row = Math.min(this.row + (rowOffset[action] || 0), this.model.rows.length - 1);
    const column = Math.min(this.column + (columnOffset[action] || 0), this.model.columns - 1);
    this.open(row, column);
  }

  key(event) {
    if (event.isComposing || event.keyCode === 229) return;
    const shortcut = authoringShortcutKey(event);
    if (event.key === "F10" && event.altKey && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      event.stopPropagation();
      this.actions()[0]?.focus();
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      this.close(false);
    } else if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.stopPropagation();
      this.close(true);
    } else if (event.key === "Tab") {
      event.preventDefault();
      event.stopPropagation();
      if (!this.commit()) return;
      const next = this.row * this.model.columns + this.column + (event.shiftKey ? -1 : 1);
      if (next < 0 || next >= this.model.rows.length * this.model.columns) this.close(false);
      else this.open(Math.floor(next / this.model.columns), next % this.model.columns);
    } else if (["b", "i", "e"].includes(shortcut)) {
      event.preventDefault();
      event.stopPropagation();
      this.format({ b: "**", i: "*", e: "`" }[shortcut]);
    } else if (["z", "y"].includes(shortcut)) event.stopPropagation();
  }

  actions() {
    return [...this.panel.querySelectorAll("button:not(:disabled)")].filter(
      (button) => !button.closest("[hidden]"),
    );
  }

  actionKey(event) {
    if (event.isComposing || event.keyCode === 229 || !event.target.closest("button")) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (this.selection.kind === "cell") this.input.focus();
      else this.close(false);
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const actions = this.actions(),
      at = actions.indexOf(document.activeElement);
    if (at < 0) return;
    let next;
    if (event.key === "Home") next = 0;
    else if (event.key === "End") next = actions.length - 1;
    else if (["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(event.key)) {
      const rtl = this.panel.dir === "rtl";
      const forward = event.key === "ArrowDown" || event.key === (rtl ? "ArrowLeft" : "ArrowRight");
      next = (at + (forward ? 1 : -1) + actions.length) % actions.length;
    } else return;
    event.preventDefault();
    event.stopPropagation();
    actions[next].focus();
  }

  update(update) {
    if (this.committing) return;
    if (update.docChanged) {
      // Map drafts across an unrelated edit, but detect concurrent edits to
      // their own source cell before applying them.
      for (const transaction of update.transactions) {
        this.model.from = transaction.changes.mapPos(this.model.from, 1);
        if (this.cell)
          this.cell = {
            ...this.cell,
            from: transaction.changes.mapPos(this.cell.from, 1),
            to: transaction.changes.mapPos(this.cell.to, -1),
          };
      }
      const fresh = modelAt(this.view, this.model.from);
      if (fresh) this.model = fresh;
    }
    if (update.geometryChanged || update.viewportChanged)
      requestAnimationFrame(() => this.reposition());
  }

  close(commit, focus = true) {
    if (!this.panel.isConnected) return;
    if (commit && !this.commit()) return;
    this.actionObserver.disconnect();
    for (const [button, disabled] of this.disabledActions)
      button.disabled = disabled || this.view.state.readOnly;
    this.input.remove();
    this.panel.remove();
    const grid = this.table();
    if (grid) {
      delete grid.dataset.activeRow;
      delete grid.dataset.activeColumn;
      grid
        .querySelectorAll(".cm-table-cell-drafting, .cm-table-handle-active")
        .forEach((node) =>
          node.classList.remove("cm-table-cell-drafting", "cm-table-handle-active"),
        );
      grid
        .querySelectorAll('[aria-expanded="true"][data-table-select]')
        .forEach((node) => node.setAttribute("aria-expanded", "false"));
    }
    this.view.dom
      .querySelectorAll(".cm-table-cell-active")
      .forEach((cell) => cell.classList.remove("cm-table-cell-active"));
    document.removeEventListener("click", this.outside, true);
    document.removeEventListener("click", this.toolbarClick, true);
    document.removeEventListener("keydown", this.saveKey, true);
    document.removeEventListener("mousedown", this.keepDraftFocus, true);
    window.removeEventListener("blur", this.windowBlur);
    this.view.scrollDOM.removeEventListener("scroll", this.scroll);
    sessions.delete(this.view);
    if (focus) this.view.focus();
  }
}

export function openTableCellEditor(view, model, row, column, selection = { kind: "cell" }) {
  if (view.state.readOnly || !model.columns) return;
  const previous = sessions.get(view);
  const beforeLength = view.state.doc.length;
  if (previous && !previous.commit()) return;
  const delta = view.state.doc.length - beforeLength;
  const position = previous && previous.model.from < model.from ? model.from + delta : model.from;
  previous?.close(false, false);
  const current = modelAt(view, position);
  if (!current || !current.rows[row] || column >= current.columns) return;
  const editor = new CellEditor(view, current, row, column, selection);
  sessions.set(view, editor);
}

export function selectTableCell(view, model, row, column, { shiftKey, ctrlKey, metaKey }) {
  const previous = sessions.get(view);
  const sameTable = previous?.model.from === model.from;
  if (shiftKey && sameTable) {
    const [startRow, startColumn] = previous.selection.start || [previous.row, previous.column];
    const cells = [];
    for (let r = Math.min(startRow, row); r <= Math.max(startRow, row); r++)
      for (let c = Math.min(startColumn, column); c <= Math.max(startColumn, column); c++)
        cells.push([r, c]);
    openTableCellEditor(view, model, row, column, {
      kind: "cells",
      cells,
      start: [startRow, startColumn],
    });
  } else if (ctrlKey || metaKey) {
    const cells = sameTable ? previous.coordinates() : [];
    const remaining = cells.filter(([r, c]) => r !== row || c !== column);
    if (remaining.length === cells.length) remaining.push([row, column]);
    if (remaining.length) {
      const [lastRow, lastColumn] = remaining.at(-1);
      openTableCellEditor(view, model, lastRow, lastColumn, { kind: "cells", cells: remaining });
    } else previous?.close(true);
  } else openTableCellEditor(view, model, row, column);
}

/** The host must flush a cell draft before saving or snapshotting recovery. */
export function commitTableCellDraft(view) {
  return sessions.get(view)?.commit() ?? true;
}

export function tableEditingExtension() {
  return ViewPlugin.fromClass(
    class {
      update(update) {
        sessions.get(update.view)?.update(update);
      }
      destroy() {
        sessions.get(this.view)?.close(false, false);
      }
      constructor(view) {
        this.view = view;
      }
    },
  );
}
