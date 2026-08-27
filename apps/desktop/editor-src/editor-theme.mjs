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
 * Prose is not syntax. A heading in the document being written is a heading,
 * not a keyword, so it carries weight and size and nothing else; the
 * punctuation that makes Markdown Markdown (`#`, `**`, backticks, brackets)
 * stays quiet but stays legible. The only hues left in a Markdown document are
 * on a link, where the colour is the affordance, and inside a fenced block,
 * where they encode a different language's syntax and stop at the fence.
 */
export const mardasHighlightStyle = HighlightStyle.define([
  // Markdown structure.
  { tag: tags.heading1, color: token("heading", "#111111"), fontWeight: "700", fontSize: "1.45em" },
  { tag: tags.heading2, color: token("heading", "#111111"), fontWeight: "700", fontSize: "1.25em" },
  { tag: tags.heading3, color: token("heading", "#111111"), fontWeight: "650", fontSize: "1.1em" },
  { tag: tags.heading4, color: token("heading", "#111111"), fontWeight: "650" },
  { tag: tags.heading5, color: token("heading", "#111111"), fontWeight: "650" },
  { tag: tags.heading6, color: token("heading", "#111111"), fontWeight: "650" },
  { tag: tags.heading, color: token("heading", "#111111"), fontWeight: "650" },
  { tag: tags.strong, color: token("strong", "#000000"), fontWeight: "700" },
  { tag: tags.emphasis, color: token("emphasis", "#111111"), fontStyle: "italic" },
  { tag: tags.strikethrough, color: token("mark", "#6b6b6b"), textDecoration: "line-through" },
  { tag: tags.link, color: token("link", "#1d4ed8") },
  { tag: tags.url, color: token("url", "#6b6b6b") },
  // `tags.monospace` is inline code and the body of a fence whose language has
  // no parser here — Python, Rust, shell, most of what gets written. Tinting it
  // painted a whole block in one hue that encoded nothing: the monospace face
  // and the panel around it are what say "code". The colours below stay,
  // because inside a parsed language they do encode syntax.
  { tag: tags.monospace, color: token("text", "#111111") },
  { tag: tags.quote, color: token("quote", "#525252"), fontStyle: "italic" },
  // The grammar tags every descendant of a list with `tags.list`, not just the
  // bullet, so colouring this painted whole paragraphs of prose in the accent
  // and made a feature list unreadable next to the plain text above it. List
  // text is text; the marker in front of it is what carries the accent, and it
  // is tagged separately.
  { tag: tags.list, color: token("text", "#111111") },
  { tag: tags.contentSeparator, color: token("mark", "#6b6b6b"), fontWeight: "650" },
  // The marker characters: present, never shouting.
  { tag: tags.processingInstruction, color: token("mark", "#6b6b6b") },
  { tag: tags.meta, color: token("meta", "#6b6b6b") },
  { tag: tags.separator, color: token("mark", "#6b6b6b") },

  // Fenced code blocks.
  { tag: tags.comment, color: token("comment", "#6b6b6b"), fontStyle: "italic" },
  { tag: tags.lineComment, color: token("comment", "#6b6b6b"), fontStyle: "italic" },
  { tag: tags.blockComment, color: token("comment", "#6b6b6b"), fontStyle: "italic" },
  { tag: tags.docComment, color: token("comment", "#6b6b6b"), fontStyle: "italic" },
  { tag: [tags.keyword, tags.modifier, tags.self, tags.null], color: token("keyword", "#6d28d9") },
  {
    tag: [tags.controlKeyword, tags.definitionKeyword, tags.moduleKeyword, tags.operatorKeyword],
    color: token("keyword", "#6d28d9"),
  },
  { tag: [tags.atom, tags.bool, tags.special(tags.variableName)], color: token("number", "#6d28d9") },
  { tag: [tags.number, tags.integer, tags.float, tags.unit], color: token("number", "#6d28d9") },
  { tag: [tags.string, tags.character, tags.docString], color: token("string", "#15803d") },
  { tag: [tags.regexp, tags.escape], color: token("code", "#9a3412") },
  { tag: [tags.typeName, tags.className, tags.namespace], color: token("type", "#0f766e") },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName), tags.macroName],
    color: token("function", "#1d4ed8") },
  { tag: [tags.propertyName, tags.attributeName], color: token("key", "#a16207") },
  { tag: tags.attributeValue, color: token("string", "#15803d") },
  { tag: tags.tagName, color: token("keyword", "#6d28d9") },
  { tag: [tags.variableName, tags.labelName], color: token("variable", "#111111") },
  { tag: [tags.operator, tags.punctuation, tags.bracket, tags.derefOperator],
    color: token("mark", "#6b6b6b") },
  { tag: [tags.definition(tags.variableName), tags.definition(tags.propertyName)],
    color: token("variable", "#111111") },
  { tag: tags.invalid, color: token("invalid", "#b91c1c") },
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
        color: token("text", "#111111"),
        height: "100%",
      },
      ".cm-content": {
        caretColor: token("cursor", "#c2410c"),
        fontFamily: EDITOR_FONT_FAMILY,
        tabSize: "4",
      },
      ".cm-scroller": { fontFamily: EDITOR_FONT_FAMILY },

      "&.cm-focused": { outline: "none" },
      ".cm-cursor, .cm-dropCursor": {
        borderLeftColor: token("cursor", "#c2410c"),
        borderLeftWidth: "2px",
      },
      "&.cm-focused .cm-cursor": { borderLeftColor: token("cursor", "#c2410c") },
      "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
        backgroundColor: token("selection", "rgba(194, 65, 12, 0.16)"),
      },
      ".cm-selectionMatch": {
        backgroundColor: token("selection-match", "rgba(17, 17, 17, 0.1)"),
      },
      ".cm-activeLine": { backgroundColor: token("active-line", "rgba(17, 17, 17, 0.035)") },

      ".cm-gutters": {
        backgroundColor: "transparent",
        borderRight: `1px solid ${token("gutter-border", "#e5e5e5")}`,
        color: token("gutter-text", "#6b6b6b"),
        fontFamily: EDITOR_FONT_FAMILY,
      },
      ".cm-activeLineGutter": {
        backgroundColor: token("active-line", "rgba(17, 17, 17, 0.035)"),
        color: token("gutter-active", "#111111"),
      },
      ".cm-foldPlaceholder": {
        backgroundColor: token("active-line", "rgba(17, 17, 17, 0.035)"),
        border: `1px solid ${token("gutter-border", "#e5e5e5")}`,
        color: token("mark", "#6b6b6b"),
      },

      "&.cm-focused .cm-matchingBracket": {
        backgroundColor: token("selection-match", "rgba(17, 17, 17, 0.1)"),
        outline: `1px solid ${token("mark", "#6b6b6b")}`,
      },
      "&.cm-focused .cm-nonmatchingBracket": { color: token("invalid", "#b91c1c") },

      ".cm-searchMatch": {
        backgroundColor: token("search", "rgba(161, 98, 7, 0.22)"),
        outline: `1px solid ${token("search-border", "rgba(161, 98, 7, 0.55)")}`,
      },
      ".cm-searchMatch.cm-searchMatch-selected": {
        backgroundColor: token("search-active", "rgba(161, 98, 7, 0.42)"),
      },

      ".cm-tooltip": {
        backgroundColor: token("panel", "#ffffff"),
        border: `1px solid ${token("panel-border", "#e5e5e5")}`,
        borderRadius: "8px",
        color: token("text", "#111111"),
        boxShadow: token("panel-shadow", "0 8px 24px rgba(0, 0, 0, 0.14)"),
      },
      ".cm-tooltip .cm-tooltip-arrow:before": {
        borderTopColor: token("panel-border", "#e5e5e5"),
        borderBottomColor: token("panel-border", "#e5e5e5"),
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
        backgroundColor: token("accent-soft", "#fff7ed"),
        color: token("text", "#111111"),
      },
      ".cm-completionLabel": { color: token("text", "#111111") },
      ".cm-completionDetail": { color: token("mark", "#6b6b6b"), fontStyle: "normal" },
      ".cm-completionMatchedText": {
        color: token("link", "#1d4ed8"),
        textDecoration: "none",
        fontWeight: "700",
      },

      ".cm-panels": {
        backgroundColor: token("panel", "#ffffff"),
        color: token("text", "#111111"),
      },
      ".cm-panels.cm-panels-top": {
        borderBottom: `1px solid ${token("panel-border", "#e5e5e5")}`,
      },
      ".cm-panels.cm-panels-bottom": {
        borderTop: `1px solid ${token("panel-border", "#e5e5e5")}`,
      },

      ".cm-diagnostic": { borderRadius: "6px", padding: "4px 8px" },
      ".cm-diagnostic-error": { borderLeftColor: token("invalid", "#b91c1c") },
      ".cm-diagnostic-warning": { borderLeftColor: token("warning", "#a16207") },
      ".cm-diagnostic-info": { borderLeftColor: token("link", "#1d4ed8") },
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
