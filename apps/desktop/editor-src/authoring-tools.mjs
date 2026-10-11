/**
 * Tools that belong beside the words being written: block insertion on an
 * empty line and formatting on the current selection.
 */
import { pickedCompletion } from "@codemirror/autocomplete";
import { isolateHistory } from "@codemirror/commands";
import { syntaxTree } from "@codemirror/language";
import { EditorSelection, EditorState, Prec, StateEffect, StateField, Transaction } from "@codemirror/state";
import { EditorView, getTooltip, keymap, showTooltip } from "@codemirror/view";
import { runMarkdownCommand } from "./markdown-commands.mjs";

const BLOCKS = Object.freeze([
  { id: "heading-1", en: "Heading 1", fa: "عنوان ۱", aliases: "h1 heading title عنوان تیتر", text: "# ", caret: 2 },
  { id: "heading-2", en: "Heading 2", fa: "عنوان ۲", aliases: "h2 heading subtitle عنوان تیتر", text: "## ", caret: 3 },
  { id: "heading-3", en: "Heading 3", fa: "عنوان ۳", aliases: "h3 heading عنوان تیتر", text: "### ", caret: 4 },
  { id: "bullet-list", en: "Bulleted list", fa: "فهرست نشانه‌دار", aliases: "list bullet unordered فهرست لیست", text: "- ", caret: 2 },
  { id: "ordered-list", en: "Numbered list", fa: "فهرست شماره‌دار", aliases: "list ordered numbered فهرست شماره", text: "1. ", caret: 3 },
  { id: "task-list", en: "Task list", fa: "فهرست کارها", aliases: "task todo checkbox check کار وظیفه", text: "- [ ] ", caret: 6 },
  { id: "quote", en: "Quote", fa: "نقل‌قول", aliases: "quote blockquote نقل قول", text: "> ", caret: 2 },
  { id: "code-block", en: "Code block", fa: "بلوک کد", aliases: "code fence کد", text: "```\n\n```", caret: 4 },
  { id: "table", en: "Table", fa: "جدول", aliases: "table columns جدول", text: "| Column | Column |\n| --- | --- |\n|  |  |", faText: "| ستون | ستون |\n| --- | --- |\n|  |  |", caret: 2, select: 6 },
  { id: "callout", en: "Callout", fa: "یادداشت برجسته", aliases: "callout note tip alert یادداشت نکته", text: "> [!NOTE]\n> ", caret: 12 },
  { id: "math-block", en: "Math block", fa: "فرمول ریاضی", aliases: "math equation formula فرمول ریاضی", text: "$$\n\n$$", caret: 3 },
  { id: "rule", en: "Divider", fa: "خط جداکننده", aliases: "divider rule horizontal separator خط جداکننده", text: "---\n\n", caret: 5 },
]);

const EXCLUDED_NODES = new Set([
  "FencedCode", "CodeBlock", "InlineCode", "Frontmatter", "HTMLBlock", "BlockMath", "InlineMath",
]);

/** Protect custom commands and widgets as well as the native input surface. */
export const readOnlyDocumentGuard = EditorState.transactionFilter.of((transaction) =>
  transaction.startState.readOnly && transaction.docChanged ? [] : transaction,
);

function normalizedQuery(value) {
  return String(value || "").toLowerCase().replace(/ي/g, "ی").replace(/ك/g, "ک");
}

/** A Markdown construct can only be inserted into prose, never into its data. */
export function inAuthoringProse(state, position) {
  for (let node = syntaxTree(state).resolveInner(position, -1); node; node = node.parent) {
    if (EXCLUDED_NODES.has(node.name) || node.name.startsWith("Frontmatter")) return false;
  }
  return true;
}

/**
 * Return the slash and its query only when the whole line is an insertion
 * request. A URL, division, a list item or text after the caret remains text.
 */
export function slashRequest(state, position) {
  if (state.readOnly || state.selection.ranges.length !== 1 || !state.selection.main.empty) return null;
  const line = state.doc.lineAt(position);
  const before = state.sliceDoc(line.from, position);
  const match = /^([ \t]{0,3})\/([\p{L}\p{N}_\u200c-]*)$/u.exec(before);
  if (!match || !/^[\p{L}\p{N}_\u200c-]*[ \t]*$/u.test(state.sliceDoc(position, line.to))) return null;
  if (!inAuthoringProse(state, position)) return null;
  return { from: line.from + match[1].length, to: line.to, query: match[2] };
}

/** One replacement, one undo step; no leftover slash or English filler text. */
export function slashBlockTransaction(state, id, locale = "en") {
  const request = slashRequest(state, state.selection.main.head);
  const block = BLOCKS.find((item) => item.id === id);
  if (!request || !block) return null;
  const insert = locale === "fa" && block.faText ? block.faText : block.text;
  const from = request.from;
  const line = state.doc.lineAt(from);
  const needsSeparation = ["table", "rule", "math-block", "callout"].includes(id);
  const lead = needsSeparation && line.number > 1 && state.doc.line(line.number - 1).text.trim() ? "\n" : "";
  const tail = needsSeparation && !insert.endsWith("\n")
    && line.number < state.doc.lines && state.doc.line(line.number + 1).text.trim() ? "\n" : "";
  const caret = from + lead.length + block.caret;
  const to = block.select ? caret + (locale === "fa" ? 4 : block.select) : caret;
  return {
    changes: { from, to: request.to, insert: `${lead}${insert}${tail}` },
    selection: EditorSelection.single(caret, to),
    annotations: [Transaction.userEvent.of("input.complete"), isolateHistory.of("full")],
    scrollIntoView: true,
  };
}

/** Search either language, display the interface language. */
export function slashBlockOptions(query = "", locale = "en") {
  const wanted = normalizedQuery(query);
  return BLOCKS.filter((block) =>
    normalizedQuery(`${block.en} ${block.fa} ${block.aliases}`).includes(wanted),
  ).map((block) => ({
    label: locale === "fa" ? block.fa : block.en,
    detail: locale === "fa" ? "درج بلوک" : "Insert block",
    type: "keyword",
    blockId: block.id,
    apply(view, completion) {
      const transaction = slashBlockTransaction(view.state, block.id, locale);
      if (!transaction) return;
      transaction.annotations.push(pickedCompletion.of(completion));
      view.dispatch(transaction);
      view.focus();
    },
  }));
}

export function slashCompletionSource(getLocale) {
  return (context) => {
    const request = slashRequest(context.state, context.pos);
    if (!request) return null;
    const options = slashBlockOptions(request.query, getLocale?.());
    if (!options.length) return null;
    // Labels are translated and aliases are bilingual. Filtering here lets
    // `/table` still find «جدول» in a Persian interface.
    return { from: request.from + 1, to: context.pos, options, filter: false };
  };
}

const FORMATS = Object.freeze([
  { command: "bold", text: "B", en: "Bold", fa: "پررنگ", shortcut: "Ctrl/Cmd+B" },
  { command: "italic", text: "I", en: "Italic", fa: "مورب", shortcut: "Ctrl/Cmd+I" },
  { command: "link", text: "↗", en: "Link", fa: "پیوند", shortcut: "Ctrl/Cmd+K" },
  { command: "code", text: "</>", en: "Inline code", fa: "کد درون متن", shortcut: "Ctrl/Cmd+E" },
]);

export function selectionToolbarEligible(state) {
  const { main, ranges } = state.selection;
  if (state.readOnly || ranges.length !== 1 || main.empty
    || !inAuthoringProse(state, main.from) || !inAuthoringProse(state, main.to)) return false;
  let prose = true;
  syntaxTree(state).iterate({
    from: main.from, to: main.to,
    enter(node) {
      if (EXCLUDED_NODES.has(node.name)) prose = false;
      return prose;
    },
  });
  return prose;
}

const dismissToolbar = StateEffect.define();
const revealToolbar = StateEffect.define();

function toolbarDOM(view, locale) {
  const dom = document.createElement("div");
  dom.className = "cm-selection-toolbar";
  dom.setAttribute("role", "toolbar");
  dom.setAttribute("aria-label", locale === "fa" ? "قالب‌بندی متن انتخاب‌شده" : "Format selected text");
  dom.dir = locale === "fa" ? "rtl" : "ltr";
  const buttons = FORMATS.map((format, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.tabIndex = index === 0 ? 0 : -1;
    button.dataset.editorCommand = format.command;
    const label = locale === "fa" ? format.fa : format.en;
    button.textContent = format.text;
    button.setAttribute("aria-label", label);
    button.title = `${label} (${format.shortcut})`;
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("click", () => runMarkdownCommand(view, format.command));
    dom.append(button);
    return button;
  });
  dom.addEventListener("keydown", (event) => {
    const current = Math.max(0, buttons.indexOf(document.activeElement));
    let next = null;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      view.dispatch({ effects: dismissToolbar.of(true) });
      view.focus();
      return;
    }
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      const step = (event.key === "ArrowRight" ? 1 : -1) * (locale === "fa" ? -1 : 1);
      next = (current + step + buttons.length) % buttons.length;
    } else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = buttons.length - 1;
    if (next !== null) {
      event.preventDefault();
      buttons.forEach((button, index) => { button.tabIndex = index === next ? 0 : -1; });
      buttons[next].focus();
    }
  });
  const updateFocus = () => {
    const active = document.activeElement;
    dom.hidden = !view.dom.contains(active) && !dom.contains(active);
  };
  return {
    dom,
    mount() { document.addEventListener("focusin", updateFocus); updateFocus(); },
    update: updateFocus,
    destroy() { document.removeEventListener("focusin", updateFocus); },
  };
}

/** Reconfigured with the presentation; document, history and selection stay put. */
export function selectionToolbarExtension(locale = "en", enabled = true) {
  if (!enabled) return [];
  const create = (state) => selectionToolbarEligible(state) ? {
    pos: state.selection.main.from,
    end: state.selection.main.to,
    above: true,
    create: (view) => toolbarDOM(view, locale),
  } : null;
  const field = StateField.define({
    create,
    update(value, transaction) {
      if (transaction.effects.some((effect) => effect.is(dismissToolbar))) return null;
      if (transaction.effects.some((effect) => effect.is(revealToolbar))) return create(transaction.state);
      if (transaction.selection || transaction.docChanged || transaction.reconfigured) return create(transaction.state);
      return value;
    },
    provide: (field) => showTooltip.from(field),
  });
  return [field, Prec.highest(keymap.of([{
    key: "Alt-F10",
    preventDefault: true,
    run(view) {
      if (!selectionToolbarEligible(view.state)) return false;
      view.dispatch({ effects: revealToolbar.of(true) });
      const tooltip = view.state.field(field);
      const focus = () => {
        const dom = getTooltip(view, tooltip)?.dom;
        // The toolbar can mount synchronously. A key pressed before the next
        // frame may already have moved to another button; delayed mount focus
        // must not reset that user's roving focus to the first button.
        if (dom && !dom.contains(document.activeElement)) dom.querySelector("button")?.focus();
      };
      focus();
      // A new tooltip is positioned at the next measure when previously
      // dismissed. Focus follows the mounted DOM on that frame as well.
      requestAnimationFrame(focus);
      return true;
    },
  }]))];
}

export const authoringToolsTheme = EditorView.baseTheme({
  ".cm-selection-toolbar": {
    display: "flex", alignItems: "center", gap: "2px", padding: "4px",
    fontFamily: '"Segoe UI Variable", "Vazirmatn", "Noto Sans Arabic", system-ui, sans-serif',
  },
  ".cm-selection-toolbar[hidden]": { display: "none" },
  ".cm-selection-toolbar button": {
    display: "grid", placeItems: "center", minWidth: "32px", height: "32px",
    border: "0", borderRadius: "5px", background: "transparent",
    color: "var(--cm-text, #111111)", font: "inherit", cursor: "pointer",
  },
  '.cm-selection-toolbar button[data-editor-command="bold"]': { fontWeight: "750" },
  '.cm-selection-toolbar button[data-editor-command="italic"]': { fontStyle: "italic" },
  ".cm-selection-toolbar button:hover": { background: "var(--cm-accent-soft, #fff7ed)" },
  ".cm-selection-toolbar button:focus-visible": {
    outline: "2px solid var(--cm-link, #1d4ed8)", outlineOffset: "-2px",
  },
});
