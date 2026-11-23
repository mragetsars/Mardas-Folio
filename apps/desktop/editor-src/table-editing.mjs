/** Cell editing is portaled outside contentDOM: CodeMirror remains the source of truth. */
import { syntaxTree } from "@codemirror/language";
import { Transaction } from "@codemirror/state";
import { isolateHistory } from "@codemirror/commands";
import { ViewPlugin } from "@codemirror/view";
import { markdownLanguage } from "@codemirror/lang-markdown";
import { appendTableInline, tableInlineText } from "./table-inline.mjs";
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

export function columnAlignment(raw = "") {
  if (raw.startsWith(":")) return raw.endsWith(":") ? "center" : "left";
  return raw.endsWith(":") ? "right" : "auto";
}

const alignments = ["auto", "left", "center", "right"];
const alignmentMarker = /^<!--folio-align:(auto|left|center|right)-->\s*/;

export function tableCellAlignment(model, row, column) {
  const raw = model?.rows[row]?.cells[column]?.raw || "";
  const marker = alignmentMarker.exec(raw);
  const inherited = columnAlignment(model?.delimiter?.cells[column]?.raw);
  return { alignment: marker?.[1] || inherited, inherited, prefix: marker?.[0].length || 0 };
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

/** Existing GFM column marks remain defaults until a cell receives its own override. */
export function tableCellChanges(model, coordinates, alignment, content) {
  const rows = new Map();
  for (const [row, column] of coordinates) {
    const record = model.rows[row];
    if (!record || column < 0 || column >= model.columns) continue;
    const raw = record.cells[column]?.raw || "";
    const parsed = tableCellAlignment(model, row, column);
    const text = content ?? raw.slice(parsed.prefix);
    const prefix =
      alignment == null
        ? raw.slice(0, parsed.prefix)
        : alignment === "auto" && parsed.inherited === "auto"
          ? ""
          : "<!--folio-align:" + alignment + "-->" + (text ? " " : "");
    const insert = prefix + text;
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
  if (action === "add-row") {
    const row = rowIndex === 0 ? model.delimiter : rows[rowIndex];
    const reference = document.lineAt(model.delimiter.from);
    const prefix = reference.text.slice(0, model.delimiter.from - reference.from);
    return [{ from: row.to, insert: `\n${prefix}${serializeRow(Array(model.columns).fill(""))}` }];
  }
  if (action === "delete-row") {
    if (rowIndex === 0) return [];
    const line = document.lineAt(rows[rowIndex].from);
    return [{ from: line.from, to: Math.min(document.length, line.to + 1), insert: "" }];
  }
  if (action === "delete-column" && model.columns <= 1) return [];
  if (!["add-column", "delete-column"].includes(action)) return [];
  const change = (row, cells) => {
    const values = Array.from(
      { length: Math.max(model.columns, cells.length) },
      (_, index) => cells[index] || "",
    );
    if (action === "add-column")
      values.splice(columnIndex + 1, 0, row === model.delimiter ? "---" : "");
    else values.splice(columnIndex, 1);
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
    content: "Cell content (Markdown)",
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
    content: "محتوای سلول (Markdown)",
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
    this.panel.setAttribute("role", "dialog");
    this.panel.setAttribute("aria-modal", "false");
    this.panel.setAttribute("aria-label", this.labels.title);
    this.panel.dir = document.documentElement.dir;
    const heading = document.createElement("header");
    this.title = document.createElement("strong");
    this.positionLabel = document.createElement("small");
    heading.append(this.title, this.positionLabel);
    this.panel.append(heading);
    const tools = document.createElement("div");
    tools.className = "cm-table-cell-formats";
    for (const [name, text, marker] of [
      ["bold", "B", "**"],
      ["italic", "I", "*"],
      ["code", "</>", "`"],
    ]) {
      const button = this.button(text, () => this.format(marker), tools);
      button.title = button.ariaLabel = this.labels[name];
      button.dataset.cellFormat = name;
    }
    this.tools = tools;
    const label = (this.contentLabel = document.createElement("label"));
    label.textContent = this.labels.content;
    this.input = document.createElement("textarea");
    this.input.className = "cm-table-cell-input";
    this.input.rows = 2;
    this.input.dir = "auto";
    this.input.spellcheck = false;
    this.input.setAttribute("aria-keyshortcuts", "Alt+F10");
    label.append(this.input);
    this.panel.append(tools, label);
    this.preview = document.createElement("div");
    this.preview.className = "cm-table-cell-preview";
    this.preview.dir = "auto";
    this.panel.append(this.preview);
    this.input.addEventListener("input", () => this.paintPreview());
    const alignment = document.createElement("div");
    alignment.className = "cm-table-cell-alignment";
    alignment.setAttribute("role", "group");
    alignment.setAttribute("aria-label", this.labels.alignment);
    const alignmentLabel = document.createElement("span");
    alignmentLabel.textContent = this.labels.alignment;
    alignment.append(alignmentLabel);
    this.alignments = alignments.map((value) => {
      const control = this.button(
        this.labels[value],
        () => {
          this.pendingAlignment = value;
          this.updateAlignment();
        },
        alignment,
      );
      control.dataset.cellAlignment = value;
      return control;
    });
    this.panel.append(alignment);
    const help = (this.help = document.createElement("p"));
    help.textContent = this.labels.help;
    this.error = document.createElement("p");
    this.error.className = "cm-table-cell-error";
    this.error.setAttribute("role", "alert");
    this.error.hidden = true;
    this.panel.append(help, this.error);
    const structure = (this.structurePanel = document.createElement("div"));
    structure.className = "cm-table-cell-structure";
    this.addRow = this.button(this.labels.addRow, () => this.structure("add-row"), structure);
    this.deleteRow = this.button(
      this.labels.deleteRow,
      () => this.structure("delete-row"),
      structure,
    );
    this.addColumn = this.button(
      this.labels.addColumn,
      () => this.structure("add-column"),
      structure,
    );
    this.deleteColumn = this.button(
      this.labels.deleteColumn,
      () => this.structure("delete-column"),
      structure,
    );
    const actions = document.createElement("footer");
    this.button(this.labels.cancel, () => this.close(false), actions);
    this.apply = this.button(this.labels.apply, () => this.close(true), actions);
    this.apply.className = "cm-table-cell-apply";
    this.panel.append(structure, actions);
    document.body.append(this.panel);
    this.input.addEventListener("keydown", (event) => this.key(event));
    this.panel.addEventListener("keydown", (event) => this.actionKey(event));
    this.outside = (event) => {
      if (this.panel.contains(event.target)) return;
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
      if (this.panel.contains(event.target)) return;
      const command = event.target.closest?.("[data-editor-command]")?.dataset.editorCommand;
      const marker = { bold: "**", italic: "*", code: "`" }[command];
      if (!marker) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      this.format(marker);
    };
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
    this.input.value = this.original.slice(tableCellAlignment(this.model, row, column).prefix);
    const { kind } = this.selection;
    const single = kind === "cell";
    this.title.textContent = single ? this.labels.title : this.labels[kind + "Selection"];
    this.panel.setAttribute("aria-label", this.title.textContent);
    this.tools.hidden = this.contentLabel.hidden = this.preview.hidden = this.help.hidden = !single;
    this.structurePanel.hidden = kind !== "row" && kind !== "column";
    this.addRow.hidden = this.deleteRow.hidden = kind !== "row";
    this.addColumn.hidden = this.deleteColumn.hidden = kind !== "column";
    this.error.hidden = true;
    this.apply.disabled = false;
    this.positionLabel.textContent = {
      cell: `${this.labels.row} ${row + 1} · ${this.labels.column} ${column + 1}`,
      row: String(row + 1),
      column: String(column + 1),
      cells: String(this.coordinates().length),
    }[kind];
    this.deleteRow.disabled = row === 0;
    this.deleteColumn.disabled = this.model.columns <= 1;
    this.paintPreview();
    this.reposition();
    if (single) {
      this.input.focus();
      this.input.select();
    } else this.alignments[0].focus();
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
      const rendered = tableInlineText(this.preview);
      this.input.style.textAlign = this.preview.style.textAlign =
        alignment === "auto" ? autoCellAlignment(rendered) : alignment;
    }
  }

  reposition() {
    if (!this.panel.isConnected) return;
    const anchor = this.anchor();
    if (!anchor) return;
    const chosen = new Set(this.coordinates().map(([row, column]) => row + ":" + column));
    for (const cell of this.table().querySelectorAll("[data-table-row][data-table-column]")) {
      cell.classList.toggle(
        "cm-table-cell-active",
        chosen.has(cell.dataset.tableRow + ":" + cell.dataset.tableColumn),
      );
    }
    const rect = anchor.getBoundingClientRect();
    const table = this.table().getBoundingClientRect();
    const gap = 8;
    this.panel.style.maxBlockSize = "";
    const panel = this.panel.getBoundingClientRect();
    const clamp = (value, end) => Math.max(gap, Math.min(value, end));
    const below = innerHeight - table.bottom - gap * 2;
    const above = table.top - gap * 2;
    const fitsSide = (left) => left >= gap && left + panel.width <= innerWidth - gap;
    const right = table.right + gap;
    const left = table.left - panel.width - gap;
    let x = clamp(rect.left, innerWidth - panel.width - gap);
    let y;
    if (below >= panel.height) {
      y = table.bottom + gap;
    } else if (above >= panel.height) {
      y = table.top - panel.height - gap;
    } else if (fitsSide(right) || fitsSide(left)) {
      x = fitsSide(right) ? right : left;
      y = clamp(rect.top, innerHeight - panel.height - gap);
    } else {
      // A long table may fill the viewport. Use the larger outside region when
      // it can hold the controls, otherwise keep part of the table accessible.
      const space = Math.max(below, above);
      const height = Math.min(panel.height, Math.max(space, Math.min(200, panel.height)));
      this.panel.style.maxBlockSize = height + "px";
      y =
        below >= above
          ? clamp(table.bottom + gap, innerHeight - height - gap)
          : clamp(table.top - height - gap, innerHeight - height - gap);
    }
    this.panel.style.left = x + "px";
    this.panel.style.top = y + "px";
  }

  format(marker) {
    const input = this.input,
      from = input.selectionStart,
      to = input.selectionEnd;
    input.setRangeText(marker + input.value.slice(from, to) + marker, from, to, "select");
    input.setSelectionRange(from + marker.length, to + marker.length);
    input.focus();
    this.paintPreview();
  }

  paintPreview() {
    const markup = `| Cell |\n| --- |\n| ${tableCellSource(this.input.value)} |`;
    const tree = markdownLanguage.parser.parse(markup);
    let cell = null;
    tree.iterate({
      enter(node) {
        if (node.name === "TableCell") cell = node.node;
      },
    });
    this.preview.replaceChildren();
    if (cell) appendTableInline(this.preview, cell, markup);
    this.updateAlignment();
  }

  commit() {
    if (this.view.state.readOnly || this.apply.disabled) return false;
    const single = this.selection.kind === "cell";
    const value = single ? tableCellSource(this.input.value) : undefined;
    const originalText = this.original.slice(alignmentMarker.exec(this.original)?.[0].length || 0);
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
      this.apply.disabled = true;
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
    this.pendingAlignment = null;
    this.updateAlignment();
    requestAnimationFrame(() => this.reposition());
    return true;
  }

  structure(action) {
    if (!this.commit()) return;
    const changes = tableStructureChanges(
      this.model,
      this.view.state.doc,
      action,
      this.row,
      this.column,
    );
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
    const row =
      action === "add-row" ? this.row + 1 : Math.min(this.row, this.model.rows.length - 1);
    const column =
      action === "add-column" ? this.column + 1 : Math.min(this.column, this.model.columns - 1);
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
    const anchor = this.anchor();
    this.actionObserver.disconnect();
    for (const [button, disabled] of this.disabledActions)
      button.disabled = disabled || this.view.state.readOnly;
    this.panel.remove();
    this.view.dom
      .querySelectorAll(".cm-table-cell-active")
      .forEach((cell) => cell.classList.remove("cm-table-cell-active"));
    document.removeEventListener("click", this.outside, true);
    document.removeEventListener("click", this.toolbarClick, true);
    document.removeEventListener("keydown", this.saveKey, true);
    window.removeEventListener("blur", this.windowBlur);
    sessions.delete(this.view);
    if (focus) anchor?.closest(".cm-md-table")?.focus();
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
