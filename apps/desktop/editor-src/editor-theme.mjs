/**
 * Syntax highlighting and chrome for the Markdown editor.
 *
 * `basicSetup` ships CodeMirror's `defaultHighlightStyle`, which is a
 * light-only palette: on the dark workspace its link and code-fence tokens fell
 * to 1.61:1 contrast and its Markdown punctuation to 2.19:1, well under the
 * 4.5:1 floor the rest of the interface holds.  It also underlines every
 * heading and link, which reads as noise in a document you are writing rather
 * than reading.
 *
 * Every colour here resolves through a `--cm-*` custom property declared in
 * `workspace.css`, so light and dark are one code path and the palette can be
 * retuned without rebuilding the committed bundle.  The literal fallbacks keep
 * the editor legible if the stylesheet ever fails to load.
 */
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";

/**
 * A Latin monospace stack with Persian fallbacks.
 *
 * Most monospace faces have no usable Persian glyphs, so a bilingual document
 * needs the Persian faces named before the generic `monospace` fallback.
 */
export const EDITOR_FONT_FAMILY = [
  "ui-monospace",
  '"Cascadia Mono"',
  '"JetBrains Mono"',
  '"SFMono-Regular"',
  "Menlo",
  "Consolas",
  '"Vazirmatn"',
  '"Noto Sans Arabic"',
  "monospace",
].join(", ");

const token = (name, fallback) => `var(--cm-${name}, ${fallback})`;

/**
 * Markdown structure first, then the tags fenced code blocks contribute.
 *
 * Headings carry weight and size rather than an underline; the punctuation that
 * makes Markdown Markdown (`#`, `**`, backticks, brackets) stays quiet but
 * stays legible.
 */
export const mardasHighlightStyle = HighlightStyle.define([
  // Markdown structure.
  { tag: tags.heading1, color: token("heading", "#10635b"), fontWeight: "700", fontSize: "1.45em" },
  { tag: tags.heading2, color: token("heading", "#10635b"), fontWeight: "700", fontSize: "1.25em" },
  { tag: tags.heading3, color: token("heading", "#10635b"), fontWeight: "650", fontSize: "1.1em" },
  { tag: tags.heading4, color: token("heading", "#10635b"), fontWeight: "650" },
  { tag: tags.heading5, color: token("heading", "#10635b"), fontWeight: "650" },
  { tag: tags.heading6, color: token("heading", "#10635b"), fontWeight: "650" },
  { tag: tags.heading, color: token("heading", "#10635b"), fontWeight: "650" },
  { tag: tags.strong, color: token("strong", "#24211d"), fontWeight: "700" },
  { tag: tags.emphasis, color: token("emphasis", "#24211d"), fontStyle: "italic" },
  { tag: tags.strikethrough, color: token("mark", "#7a736a"), textDecoration: "line-through" },
  { tag: tags.link, color: token("link", "#0d6d80") },
  { tag: tags.url, color: token("url", "#6d665c") },
  { tag: tags.monospace, color: token("code", "#9c3b1b") },
  { tag: tags.quote, color: token("quote", "#63605a"), fontStyle: "italic" },
  { tag: tags.list, color: token("list", "#10635b") },
  { tag: tags.contentSeparator, color: token("mark", "#7a736a"), fontWeight: "650" },
  // The marker characters: present, never shouting.
  { tag: tags.processingInstruction, color: token("mark", "#7a736a") },
  { tag: tags.meta, color: token("meta", "#7a736a") },
  { tag: tags.separator, color: token("mark", "#7a736a") },

  // Fenced code blocks.
  { tag: tags.comment, color: token("comment", "#7a736a"), fontStyle: "italic" },
  { tag: tags.lineComment, color: token("comment", "#7a736a"), fontStyle: "italic" },
  { tag: tags.blockComment, color: token("comment", "#7a736a"), fontStyle: "italic" },
  { tag: tags.docComment, color: token("comment", "#7a736a"), fontStyle: "italic" },
  { tag: [tags.keyword, tags.modifier, tags.self, tags.null], color: token("keyword", "#8a3f6b") },
  {
    tag: [tags.controlKeyword, tags.definitionKeyword, tags.moduleKeyword, tags.operatorKeyword],
    color: token("keyword", "#8a3f6b"),
  },
  { tag: [tags.atom, tags.bool, tags.special(tags.variableName)], color: token("number", "#9c3b1b") },
  { tag: [tags.number, tags.integer, tags.float, tags.unit], color: token("number", "#9c3b1b") },
  { tag: [tags.string, tags.character, tags.docString], color: token("string", "#1f6b45") },
  { tag: [tags.regexp, tags.escape], color: token("code", "#9c3b1b") },
  { tag: [tags.typeName, tags.className, tags.namespace], color: token("type", "#0d6d80") },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName), tags.macroName],
    color: token("function", "#8a5320") },
  { tag: [tags.propertyName, tags.attributeName], color: token("key", "#8a5320") },
  { tag: tags.attributeValue, color: token("string", "#1f6b45") },
  { tag: tags.tagName, color: token("keyword", "#8a3f6b") },
  { tag: [tags.variableName, tags.labelName], color: token("variable", "#24211d") },
  { tag: [tags.operator, tags.punctuation, tags.bracket, tags.derefOperator],
    color: token("mark", "#7a736a") },
  { tag: [tags.definition(tags.variableName), tags.definition(tags.propertyName)],
    color: token("variable", "#24211d") },
  { tag: tags.invalid, color: token("invalid", "#b42318") },
]);

/**
 * Editor chrome: surface, caret, selection, gutters, and every floating panel
 * CodeMirror can raise (autocomplete, lint, search).  The built-in styles for
 * those panels are light-only too, so each one is restated here.
 */
export function mardasEditorTheme(dark = false) {
  return EditorView.theme(
    {
      "&": {
        backgroundColor: "transparent",
        color: token("text", "#24211d"),
        height: "100%",
      },
      ".cm-content": {
        caretColor: token("cursor", "#0f766e"),
        fontFamily: EDITOR_FONT_FAMILY,
        tabSize: "4",
      },
      ".cm-scroller": { fontFamily: EDITOR_FONT_FAMILY },

      "&.cm-focused": { outline: "none" },
      ".cm-cursor, .cm-dropCursor": {
        borderLeftColor: token("cursor", "#0f766e"),
        borderLeftWidth: "2px",
      },
      "&.cm-focused .cm-cursor": { borderLeftColor: token("cursor", "#0f766e") },
      "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
        backgroundColor: token("selection", "rgba(15, 118, 110, 0.18)"),
      },
      ".cm-selectionMatch": {
        backgroundColor: token("selection-match", "rgba(15, 118, 110, 0.14)"),
      },
      ".cm-activeLine": { backgroundColor: token("active-line", "rgba(15, 118, 110, 0.05)") },

      ".cm-gutters": {
        backgroundColor: "transparent",
        borderRight: `1px solid ${token("gutter-border", "#e4e1db")}`,
        color: token("gutter-text", "#9a938a"),
        fontFamily: EDITOR_FONT_FAMILY,
      },
      ".cm-activeLineGutter": {
        backgroundColor: token("active-line", "rgba(15, 118, 110, 0.05)"),
        color: token("gutter-active", "#24211d"),
      },
      ".cm-foldPlaceholder": {
        backgroundColor: token("active-line", "rgba(15, 118, 110, 0.05)"),
        border: `1px solid ${token("gutter-border", "#e4e1db")}`,
        color: token("mark", "#7a736a"),
      },

      "&.cm-focused .cm-matchingBracket": {
        backgroundColor: token("selection-match", "rgba(15, 118, 110, 0.14)"),
        outline: `1px solid ${token("mark", "#7a736a")}`,
      },
      "&.cm-focused .cm-nonmatchingBracket": { color: token("invalid", "#b42318") },

      ".cm-searchMatch": {
        backgroundColor: token("search", "rgba(154, 103, 0, 0.22)"),
        outline: `1px solid ${token("search-border", "rgba(154, 103, 0, 0.45)")}`,
      },
      ".cm-searchMatch.cm-searchMatch-selected": {
        backgroundColor: token("search-active", "rgba(154, 103, 0, 0.42)"),
      },

      ".cm-tooltip": {
        backgroundColor: token("panel", "#ffffff"),
        border: `1px solid ${token("panel-border", "#d8e2e0")}`,
        borderRadius: "8px",
        color: token("text", "#24211d"),
        boxShadow: token("panel-shadow", "0 12px 32px rgba(20, 55, 53, 0.16)"),
      },
      ".cm-tooltip .cm-tooltip-arrow:before": {
        borderTopColor: token("panel-border", "#d8e2e0"),
        borderBottomColor: token("panel-border", "#d8e2e0"),
      },
      ".cm-tooltip .cm-tooltip-arrow:after": {
        borderTopColor: token("panel", "#ffffff"),
        borderBottomColor: token("panel", "#ffffff"),
      },
      ".cm-tooltip.cm-tooltip-autocomplete > ul": {
        fontFamily: EDITOR_FONT_FAMILY,
        maxHeight: "16em",
      },
      ".cm-tooltip.cm-tooltip-autocomplete > ul > li": { padding: "3px 8px" },
      ".cm-tooltip.cm-tooltip-autocomplete > ul > li[aria-selected]": {
        backgroundColor: token("accent-soft", "rgba(15, 118, 110, 0.12)"),
        color: token("text", "#24211d"),
      },
      ".cm-completionLabel": { color: token("text", "#24211d") },
      ".cm-completionDetail": { color: token("mark", "#7a736a"), fontStyle: "normal" },
      ".cm-completionMatchedText": {
        color: token("link", "#0d6d80"),
        textDecoration: "none",
        fontWeight: "700",
      },

      ".cm-panels": {
        backgroundColor: token("panel", "#ffffff"),
        color: token("text", "#24211d"),
      },
      ".cm-panels.cm-panels-top": {
        borderBottom: `1px solid ${token("panel-border", "#d8e2e0")}`,
      },
      ".cm-panels.cm-panels-bottom": {
        borderTop: `1px solid ${token("panel-border", "#d8e2e0")}`,
      },

      ".cm-diagnostic": { borderRadius: "6px", padding: "4px 8px" },
      ".cm-diagnostic-error": { borderLeftColor: token("invalid", "#b42318") },
      ".cm-diagnostic-warning": { borderLeftColor: token("warning", "#9a6700") },
      ".cm-diagnostic-info": { borderLeftColor: token("link", "#0d6d80") },
      ".cm-lintRange-error": { backgroundPosition: "left bottom" },
    },
    { dark },
  );
}

/** The editor's visual layer: chrome plus a non-fallback highlighter. */
export function mardasEditorAppearance(dark = false) {
  // `basicSetup` registers `defaultHighlightStyle` as a fallback highlighter, so
  // registering this one without `fallback` is enough to take precedence.
  return [mardasEditorTheme(dark), syntaxHighlighting(mardasHighlightStyle)];
}
