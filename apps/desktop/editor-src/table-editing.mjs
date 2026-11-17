/** Cell editing is portaled outside contentDOM: CodeMirror remains the source of truth. */
import { syntaxTree } from "@codemirror/language";
import { Transaction } from "@codemirror/state";
import { isolateHistory } from "@codemirror/commands";
import { ViewPlugin } from "@codemirror/view";
import { markdownLanguage } from "@codemirror/lang-markdown";
import { appendTableInline } from "./table-inline.mjs";
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
  constructor(view, model, row, column) {
    this.view = view;
    this.model = model;
    this.labels = tableLabels();
    this.panel = document.createElement("section");
    this.panel.className = "cm-table-cell-editor";
    this.panel.setAttribute("role", "dialog");
    this.panel.setAttribute("aria-modal", "false");
    this.panel.setAttribute("aria-label", this.labels.title);
    this.panel.dir = document.documentElement.dir;
    const heading = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = this.labels.title;
    this.positionLabel = document.createElement("small");
    heading.append(title, this.positionLabel);
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
    const label = document.createElement("label");
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
    const help = document.createElement("p");
    help.textContent = this.labels.help;
    this.error = document.createElement("p");
    this.error.className = "cm-table-cell-error";
    this.error.setAttribute("role", "alert");
    this.error.hidden = true;
    this.panel.append(help, this.error);
    const structure = document.createElement("div");
    structure.className = "cm-table-cell-structure";
    this.button(this.labels.addRow, () => this.structure("add-row"), structure);
    this.deleteRow = this.button(
      this.labels.deleteRow,
      () => this.structure("delete-row"),
      structure,
    );
    this.button(this.labels.addColumn, () => this.structure("add-column"), structure);
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
      if (action && !cellFormats.has(action.dataset.editorCommand)) {
        event.preventDefault();
        event.stopImmediatePropagation();
        this.input.focus();
        return;
      }
      const command = event.target.closest?.("[data-editor-command]")?.dataset.editorCommand;
      if (["bold", "italic", "code"].includes(command)) return;
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
      if (cellFormats.has(element.dataset.editorCommand)) return;
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
    this.cell = this.model.rows[row]?.cells[column];
    this.original = this.cell?.raw || "";
    this.input.value = this.original;
    this.paintPreview();
    this.error.hidden = true;
    this.apply.disabled = false;
    this.positionLabel.textContent = `${this.labels.row} ${row + 1} · ${this.labels.column} ${column + 1}`;
    this.deleteRow.disabled = row === 0;
    this.deleteColumn.disabled = this.model.columns <= 1;
    this.reposition();
    this.input.focus();
    this.input.select();
    // A deferred focus would steal a fast Alt+F10 action back from its button.
    requestAnimationFrame(() => this.reposition());
  }

  anchor() {
    return [...this.view.dom.querySelectorAll(".cm-md-table")]
      .find((element) => Number(element.dataset.tableFrom) === this.model.from)
      ?.querySelector(`[data-table-row="${this.row}"][data-table-column="${this.column}"]`);
  }

  reposition() {
    if (!this.panel.isConnected) return;
    const anchor = this.anchor();
    if (!anchor) return;
    for (const current of this.view.dom.querySelectorAll(".cm-table-cell-active"))
      current.classList.remove("cm-table-cell-active");
    anchor.classList.add("cm-table-cell-active");
    const rect = anchor.getBoundingClientRect(),
      panel = this.panel.getBoundingClientRect();
    this.panel.style.left = `${Math.max(8, Math.min(rect.left, innerWidth - panel.width - 8))}px`;
    const below = rect.bottom + 6;
    this.panel.style.top = `${Math.max(8, Math.min(below, innerHeight - panel.height - 8))}px`;
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
  }

  commit() {
    if (this.view.state.readOnly || this.apply.disabled) return false;
    const value = tableCellSource(this.input.value);
    if (value === this.original) return true;
    if (
      this.cell &&
      this.view.state.doc.sliceString(this.cell.from, this.cell.to) !== this.original
    ) {
      this.error.textContent = this.labels.conflict;
      this.error.hidden = false;
      this.apply.disabled = true;
      return false;
    }
    let changes;
    if (this.cell) changes = [{ from: this.cell.from, to: this.cell.to, insert: value }];
    else {
      const row = this.model.rows[this.row];
      const values = Array.from(
        { length: this.model.columns },
        (_, index) => row.cells[index]?.raw || "",
      );
      values[this.column] = value;
      changes = [{ from: row.from, to: row.to, insert: serializeRow(values) }];
    }
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
    this.cell = this.model.rows[this.row]?.cells[this.column];
    this.original = this.cell?.raw || "";
    this.input.value = this.original;
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
    return [...this.panel.querySelectorAll("button:not(:disabled)")];
  }

  actionKey(event) {
    if (event.isComposing || event.keyCode === 229 || !event.target.closest("button")) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      this.input.focus();
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
    anchor?.classList.remove("cm-table-cell-active");
    document.removeEventListener("click", this.outside, true);
    document.removeEventListener("click", this.toolbarClick, true);
    document.removeEventListener("keydown", this.saveKey, true);
    window.removeEventListener("blur", this.windowBlur);
    sessions.delete(this.view);
    if (focus) anchor?.closest(".cm-md-table")?.focus();
  }
}

export function openTableCellEditor(view, model, row, column) {
  if (view.state.readOnly || !model.columns) return;
  const previous = sessions.get(view);
  const beforeLength = view.state.doc.length;
  if (previous && !previous.commit()) return;
  const delta = view.state.doc.length - beforeLength;
  const position = previous && previous.model.from < model.from ? model.from + delta : model.from;
  previous?.close(false, false);
  // A previous commit may have replaced this widget and shifted source offsets.
  const current = modelAt(view, position) || model;
  const editor = new CellEditor(view, current, row, column);
  sessions.set(view, editor);
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
