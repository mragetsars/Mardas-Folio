/**
 * Stable editor boundary used by the authoring workspace.
 *
 * The current implementation wraps the native textarea so document/session
 * logic stays independent from the rendering widget. A richer editor can
 * replace this adapter without changing recovery, save-conflict, preview, or
 * project workflows.
 */
export function createEditorAdapter(element, { onChange, onSelectionChange, onScroll } = {}) {
  if (!(element instanceof HTMLTextAreaElement)) {
    throw new TypeError("EditorAdapter requires a textarea element.");
  }

  const change = () => onChange?.();
  const selection = () => onSelectionChange?.();
  const scroll = () => onScroll?.(element.scrollTop);
  let activeDocumentId = null;
  let retainedDocuments = new Set();
  const documents = new Map();
  let readerMode = Boolean(element.readOnly);

  element.addEventListener("input", change);
  element.addEventListener("click", selection);
  element.addEventListener("keyup", selection);
  element.addEventListener("select", selection);
  element.addEventListener("scroll", scroll);

  const adapter = {
    get value() {
      return element.value;
    },
    set value(value) {
      element.value = String(value ?? "");
    },
    setDocument(id, content, { initialSelection = 0 } = {}) {
      const next = String(content ?? "");
      if (id === activeDocumentId) {
        if (element.value !== next) element.value = next;
        return;
      }
      if (activeDocumentId !== null && retainedDocuments.has(activeDocumentId)) {
        documents.set(activeDocumentId, {
          value: element.value,
          start: element.selectionStart,
          end: element.selectionEnd,
          direction: element.selectionDirection,
          scroll: element.scrollTop,
        });
      }
      const saved = documents.get(id);
      activeDocumentId = id;
      element.value = next;
      if (saved?.value === next) {
        element.setSelectionRange(saved.start, saved.end, saved.direction);
        element.scrollTop = saved.scroll;
      } else {
        const offset = Math.max(0, Math.min(next.length, Number(initialSelection) || 0));
        element.setSelectionRange(offset, offset);
        element.scrollTop = 0;
      }
    },
    retainDocuments(ids) {
      retainedDocuments = new Set(ids);
      for (const id of documents.keys()) {
        if (!retainedDocuments.has(id)) documents.delete(id);
      }
    },
    get selectionStart() {
      return element.selectionStart;
    },
    get selectionEnd() {
      return element.selectionEnd;
    },
    get scrollTop() {
      return element.scrollTop;
    },
    set scrollTop(value) {
      element.scrollTop = Number(value) || 0;
    },
    get element() {
      return element;
    },
    get disabled() {
      return element.disabled;
    },
    set disabled(value) {
      element.disabled = Boolean(value);
    },
    get readOnly() {
      return readerMode;
    },
    setReadOnly(value) {
      readerMode = Boolean(value);
      element.readOnly = readerMode;
      return readerMode;
    },
    focus(options) {
      element.focus(options);
    },
    setSelectionRange(start, end = start, direction) {
      element.setSelectionRange(start, end, direction);
    },
    scrollToLine(line) {
      const lines = element.value.split("\n");
      const number = Number(line);
      const safeLine = Math.max(1, Math.min(Number.isFinite(number) ? Math.trunc(number) : 1, lines.length));
      const lineHeight = Number.parseFloat(getComputedStyle(element).lineHeight) || 24;
      element.scrollTop = Math.max(0, (safeLine - 1) * lineHeight);
      const offset = lines.slice(0, safeLine - 1).reduce((total, value) => total + value.length + 1, 0);
      return { line: safeLine, offset };
    },
    goToLine(line, column = 1, contextLines = 3) {
      const lines = element.value.split("\n");
      const safeLine = Math.max(1, Math.min(Number(line) || 1, lines.length));
      const safeColumn = Math.max(1, Number(column) || 1);
      let offset = 0;
      for (let index = 0; index < safeLine - 1; index += 1) {
        offset += lines[index].length + 1;
      }
      offset += Math.min(lines[safeLine - 1]?.length || 0, safeColumn - 1);
      element.focus();
      element.setSelectionRange(offset, offset);
      const lineHeight = Number.parseFloat(getComputedStyle(element).lineHeight) || 24;
      element.scrollTop = Math.max(0, (safeLine - contextLines) * lineHeight);
      return { line: safeLine, column: safeColumn, offset };
    },
    lineAtOffset(offset = element.selectionStart) {
      const before = element.value.slice(0, Math.max(0, Number(offset) || 0));
      const parts = before.split("\n");
      return {
        line: parts.length,
        column: (parts.at(-1)?.length || 0) + 1,
      };
    },
    replaceRange(start, end, value, selectionStart, selectionEnd) {
      if (element.disabled || readerMode) return false;
      const text = element.value;
      const replacement = String(value ?? "");
      element.value = `${text.slice(0, start)}${replacement}${text.slice(end)}`;
      const from = selectionStart ?? start + replacement.length;
      const to = selectionEnd ?? from;
      element.setSelectionRange(from, to);
      change();
      return true;
    },
    destroy() {
      documents.clear();
      element.removeEventListener("input", change);
      element.removeEventListener("click", selection);
      element.removeEventListener("keyup", selection);
      element.removeEventListener("select", selection);
      element.removeEventListener("scroll", scroll);
    },
  };
  return adapter;
}
