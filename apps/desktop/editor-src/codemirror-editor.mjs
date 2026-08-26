import { autocompletion, snippetCompletion } from "@codemirror/autocomplete";
import { indentLess, indentMore, redo, undo } from "@codemirror/commands";
import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { javascript } from "@codemirror/lang-javascript";
import {
  markdown,
  markdownKeymap,
  markdownLanguage,
  pasteURLAsLink,
} from "@codemirror/lang-markdown";
import { LanguageDescription } from "@codemirror/language";
import { setDiagnostics } from "@codemirror/lint";
import {
  Compartment,
  EditorSelection,
  EditorState,
  Prec,
  Transaction,
} from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { basicSetup } from "codemirror";

import { mardasEditorAppearance } from "./editor-theme.mjs";
import { editorModeExtension, normalizeEditorMode } from "./live-preview.mjs";
import {
  exitEmptyBlock,
  markdownCommandKeymap,
  runMarkdownCommand,
} from "./markdown-commands.mjs";
import { mathAndFootnotes } from "./markdown-extras.mjs";
import { frontmatter } from "./markdown-frontmatter.mjs";
import { typewriterExtension } from "./typewriter.mjs";

const MAX_COMPLETIONS = 500;

/**
 * Languages available for fenced code blocks.
 *
 * These parsers already sit in the dependency tree beneath
 * `@codemirror/lang-markdown`, so wiring them up costs no new dependency.
 */
const CODE_LANGUAGES = [
  LanguageDescription.of({
    name: "javascript",
    alias: ["js", "jsx", "node", "mjs"],
    load: async () => javascript({ jsx: true }),
  }),
  LanguageDescription.of({
    name: "typescript",
    alias: ["ts", "tsx"],
    load: async () => javascript({ jsx: true, typescript: true }),
  }),
  LanguageDescription.of({ name: "json", load: async () => javascript() }),
  LanguageDescription.of({ name: "html", alias: ["htm"], load: async () => html() }),
  LanguageDescription.of({ name: "css", load: async () => css() }),
];

const MARKDOWN_SNIPPETS = Object.freeze([
  snippetCompletion("# ${Heading}", {
    label: "heading",
    detail: "Markdown heading / عنوان",
    type: "keyword",
  }),
  snippetCompletion("[${label}](${https://example.com})", {
    label: "link",
    detail: "Markdown link / پیوند",
    type: "keyword",
  }),
  snippetCompletion("![${alt text}](${assets/image.png})", {
    label: "image",
    detail: "Markdown image / تصویر",
    type: "keyword",
  }),
  snippetCompletion("```mermaid\n${flowchart TD\n  A --> B}\n```", {
    label: "mermaid",
    detail: "Mermaid diagram / نمودار",
    type: "keyword",
  }),
  snippetCompletion("---\ntitle: \"${Title}\"\nlang: ${auto}\n---\n", {
    label: "frontmatter",
    detail: "Document metadata / مشخصات سند",
    type: "keyword",
  }),
]);

function clampOffset(value, length) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(Math.trunc(number), length));
}

function normalizedCompletions(provider) {
  const provided = typeof provider === "function" ? provider() : [];
  const unique = new Map();
  for (const item of Array.isArray(provided) ? provided : []) {
    const key = String(item?.key ?? item?.id ?? item ?? "").trim();
    if (!key || unique.has(key)) continue;
    const detail = [item?.author, item?.year, item?.title]
      .map((value) => String(value ?? "").trim())
      .filter(Boolean)
      .join(" · ");
    unique.set(key, {
      apply: key,
      detail: detail || "Citation / ارجاع",
      label: key,
      type: "reference",
    });
    if (unique.size >= MAX_COMPLETIONS) break;
  }
  return [...unique.values()];
}

function completionSource(provider) {
  return (context) => {
    const citation = context.matchBefore(/@[\p{L}\p{N}_.:-]*/u);
    if (citation) {
      const options = normalizedCompletions(provider);
      if (!options.length) return null;
      return { from: citation.from + 1, options, validFor: /^[\p{L}\p{N}_.:-]*$/u };
    }

    const token = context.matchBefore(/[\p{L}\p{N}_-]*/u);
    if (!context.explicit && (!token || token.from === token.to)) return null;
    return {
      from: token?.from ?? context.pos,
      options: MARKDOWN_SNIPPETS,
      validFor: /^[\p{L}\p{N}_-]*$/u,
    };
  };
}

function diagnosticRange(document, diagnostic) {
  const requestedLine = Math.max(1, Math.trunc(Number(diagnostic?.line) || 1));
  const line = document.line(Math.min(requestedLine, document.lines));
  const column = Math.max(1, Math.trunc(Number(diagnostic?.column) || 1));
  const from = Math.min(line.to, line.from + column - 1);
  const requestedEndLine = Math.max(
    requestedLine,
    Math.trunc(Number(diagnostic?.end_line) || requestedLine),
  );
  const endLine = document.line(Math.min(requestedEndLine, document.lines));
  const endColumn = Math.max(
    requestedEndLine === requestedLine ? column + 1 : 1,
    Math.trunc(Number(diagnostic?.end_column) || 0),
  );
  const to = Math.max(from, Math.min(endLine.to, endLine.from + endColumn - 1));
  return { from, to };
}

function severity(value) {
  const normalized = String(value || "info").toLowerCase();
  return ["error", "warning", "info", "hint"].includes(normalized)
    ? normalized
    : "info";
}

/**
 * Keys the application answers, claimed here so CodeMirror does not answer too.
 *
 * `basicSetup` brings its own search panel bound to Ctrl/Cmd+F. The workspace
 * has a find bar of its own — styled, translated, and wired to the same
 * replace-all the command palette uses — so pressing the key opened both at
 * once, one of them entirely unstyled. Consuming the key here leaves the window
 * handler free to open the one the application owns.
 */
const APPLICATION_OWNED_KEYS = [
  { key: "Mod-f", run: () => true },
  { key: "Mod-h", run: () => true },
];

/**
 * A keyboard way out of the editor.
 *
 * Tab indents, which is what a document editor should do with it and is also
 * a keyboard trap. Chromium releases contenteditable on Escape-then-Tab, so
 * in the audits this looked handled, but the release is the browser's and not
 * this application's: it only ever goes forwards, it is not the same on the
 * three webviews the product ships against, and it never arms at all when
 * CodeMirror has already consumed the Escape. With a selection live —
 * `simplifySelection` claims Escape — the following Tab indented the document
 * instead of leaving it. The trap was still there and it edited the buffer on
 * the way past.
 *
 * Escape arms the next Tab to leave the editor. Where focus lands is the
 * application's business rather than the editor's, so the gesture is reported
 * to `onLeave` and answered in the workbench's own focus order. Any key that
 * is not Escape, Tab or Shift disarms it, so Escape followed by anything else
 * leaves Tab indenting as before.
 */
function tabEscapeHatch(onLeave) {
  let armed = false;
  const disarm = () => {
    armed = false;
    return false;
  };
  const leave = (backwards) => {
    armed = false;
    onLeave?.(backwards);
    return true;
  };
  // Arming and releasing both happen in one DOM handler at the highest
  // precedence, and neither goes through a keymap. Two reasons, both found by
  // measuring rather than by reading:
  //
  //   - A keymap binding for Escape is not reliably reached. Escape belongs to
  //     whichever of `closeCompletion` and `simplifySelection` has something
  //     to do with it, and the hatch armed only when neither did — which is
  //     why it appeared to work with a selection live and not without one.
  //   - A DOM handler below the keymap never sees the keys CodeMirror binds,
  //     because handlers stop at the first that returns true. An arrow key or
  //     a Home would have left the hatch armed, and the Tab after it would
  //     have left the editor when the user meant to indent.
  //
  // `preventDefault` on the armed Tab matters as much as the focus move: the
  // webview has a contenteditable release of its own that lands focus on the
  // document, and this is what stops that happening instead of the
  // workbench's focus order.
  return Prec.highest([
    EditorView.domEventHandlers({
      keydown: (event) => {
        if (event.key === "Tab" && armed) {
          event.preventDefault();
          return leave(event.shiftKey);
        }
        if (event.key === "Escape") {
          armed = true;
          // Unhandled on purpose: a completion popup still closes on this
          // press and a selection still collapses.
          return false;
        }
        return event.key === "Tab" || event.key === "Shift" ? false : disarm();
      },
      mousedown: disarm,
    }),
    keymap.of([{ key: "Tab", run: indentMore, shift: indentLess }]),
  ]);
}

/** Read the interface theme the workspace is currently showing. */
function documentTheme() {
  try {
    return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function createCodeMirrorEditorAdapter(
  textarea,
  {
    getCompletions,
    onChange,
    onContextMenu,
    onLeaveEditor,
    onScroll,
    onSelectionChange,
    resolveAsset,
    theme,
    mode,
    typewriter = false,
  } = {},
) {
  if (!(textarea instanceof HTMLTextAreaElement)) {
    throw new TypeError("CodeMirror editor requires a textarea fallback element.");
  }

  const mount = document.createElement("div");
  mount.className = "codemirror-mount";
  mount.dataset.editor = "codemirror";
  textarea.before(mount);
  textarea.hidden = true;
  textarea.setAttribute("aria-hidden", "true");
  textarea.tabIndex = -1;

  let suppressCallbacks = false;
  let disabled = Boolean(textarea.disabled);
  let appearanceMode = theme === "dark" || theme === "light" ? theme : documentTheme();
  let editorMode = normalizeEditorMode(mode);
  let typewriterEnabled = Boolean(typewriter);
  const readOnly = new Compartment();
  const appearance = new Compartment();
  const preview = new Compartment();
  const writingRhythm = new Compartment();

  const view = new EditorView({
    parent: mount,
    state: EditorState.create({
      doc: textarea.value,
      extensions: [
        basicSetup,
        // `markdown()` defaults to CommonMark, so tables, task lists and
        // strikethrough were never in the syntax tree even though the
        // publishing engine renders all three. GFM is the dialect this app
        // actually publishes.
        markdown({
          base: markdownLanguage,
          codeLanguages: CODE_LANGUAGES,
          extensions: [frontmatter, mathAndFootnotes],
        }),
        // Prose has to wrap. A horizontal scrollbar under a paragraph forces
        // the reader to pan back and forth for every line, which is unusable
        // for writing; only code fences keep their own horizontal overflow.
        EditorView.lineWrapping,
        appearance.of(mardasEditorAppearance(appearanceMode === "dark")),
        preview.of(editorModeExtension(editorMode, { resolveAsset })),
        writingRhythm.of(typewriterExtension(typewriterEnabled)),
        EditorState.allowMultipleSelections.of(true),
        // Formatting keys are bound above everything else. Bound on the window
        // instead, they could not see that CodeMirror had already acted on the
        // same key — which is how Ctrl+I came to expand the selection to its
        // parent syntax node *and* wrap the result in underscores.
        Prec.highest(keymap.of([
          ...markdownCommandKeymap(),
          ...APPLICATION_OWNED_KEYS,
          // Ahead of the continuation rule: an empty item is a request to
          // leave the list, not to carry it further down the page. It has to
          // sit in this keymap rather than beside `markdownKeymap` — a second
          // binding for the same key in the same keymap never got a turn.
          { key: "Enter", run: exitEmptyBlock },
        ])),
        // Enter continues the construct the caret is in, and Backspace at the
        // head of one removes its markup. Without this the editor had no
        // Enter binding at all: pressing it inside a list produced a bare
        // line, so every bullet after the first had to be typed by hand, and
        // an empty bullet had to be deleted character by character instead of
        // being dismissed by pressing Enter again. It is the one editing
        // behaviour every Markdown editor is expected to have, and it ships
        // with the language package.
        // Above `basicSetup`'s own Enter binding. At default precedence both
        // ran: pressing Enter on an empty bullet removed the marker *and*
        // then inserted a fresh one, so a list could not be left by pressing
        // Enter twice — it grew a blank line and another bullet.
        Prec.high(keymap.of(markdownKeymap)),
        // Pasting a URL over selected text makes a link out of it rather than
        // replacing the text with the address.
        pasteURLAsLink,
        tabEscapeHatch(onLeaveEditor),
        autocompletion({
          activateOnTyping: true,
          maxRenderedOptions: 80,
          override: [completionSource(getCompletions)],
        }),
        readOnly.of([
          EditorState.readOnly.of(disabled),
          EditorView.editable.of(!disabled),
        ]),
        // No `dir` on the content element.
        //
        // It carried `dir="auto"`, which cannot work here: every line inside
        // it declares a direction of its own, so the automatic resolution sees
        // a run of isolated objects with no strong character among them and
        // falls back to left-to-right. The content element was therefore
        // always left-to-right, whatever the workbench around it was doing,
        // and any line with nothing strong in it inherited that. Without the
        // attribute it inherits the editor's direction, which is the answer
        // the fallback was reaching for.
        EditorView.contentAttributes.of({
          "aria-label": textarea.getAttribute("aria-label") || "Markdown editor",
          spellcheck: textarea.spellcheck ? "true" : "false",
        }),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) textarea.value = update.state.doc.toString();
          if (suppressCallbacks) return;
          if (update.docChanged) onChange?.();
          if (update.selectionSet || update.docChanged) onSelectionChange?.();
        }),
      ],
    }),
  });

  const scroll = () => onScroll?.(view.scrollDOM.scrollTop);
  view.scrollDOM.addEventListener("scroll", scroll, { passive: true });

  /**
   * Hand the right-click to the application.
   *
   * A document editor is expected to offer document actions here — copy as
   * HTML, insert an image, export — not the webview's own menu, which offers
   * "Reload" and "View source".
   */
  const contextMenu = (event) => {
    if (!onContextMenu) return;
    event.preventDefault();
    onContextMenu(event);
  };
  view.dom.addEventListener("contextmenu", contextMenu);

  const adapter = {
    kind: "codemirror",
    usesNativeLineNumbers: true,
    get value() {
      return view.state.doc.toString();
    },
    set value(value) {
      const next = String(value ?? "");
      if (next === view.state.doc.toString()) return;
      suppressCallbacks = true;
      try {
        view.dispatch({
          annotations: Transaction.addToHistory.of(false),
          changes: { from: 0, to: view.state.doc.length, insert: next },
          selection: EditorSelection.cursor(Math.min(view.state.selection.main.head, next.length)),
        });
        textarea.value = next;
      } finally {
        suppressCallbacks = false;
      }
    },
    get selectionStart() {
      return view.state.selection.main.from;
    },
    get selectionEnd() {
      return view.state.selection.main.to;
    },
    get scrollTop() {
      return view.scrollDOM.scrollTop;
    },
    set scrollTop(value) {
      view.scrollDOM.scrollTop = Number(value) || 0;
    },
    get element() {
      return view.contentDOM;
    },
    get disabled() {
      return disabled;
    },
    set disabled(value) {
      const next = Boolean(value);
      if (disabled === next) return;
      disabled = next;
      textarea.disabled = next;
      view.dispatch({
        effects: readOnly.reconfigure([
          EditorState.readOnly.of(next),
          EditorView.editable.of(!next),
        ]),
      });
      mount.dataset.readOnly = String(next);
    },
    focus(options) {
      view.contentDOM.focus(options);
    },
    setSelectionRange(start, end = start, direction = "none") {
      const length = view.state.doc.length;
      const from = clampOffset(start, length);
      const to = clampOffset(end, length);
      const anchor = direction === "backward" ? to : from;
      const head = direction === "backward" ? from : to;
      view.dispatch({
        effects: EditorView.scrollIntoView(head, { y: "nearest" }),
        selection: EditorSelection.single(anchor, head),
      });
    },
    goToLine(line, column = 1, contextLines = 3) {
      const document = view.state.doc;
      const safeLine = Math.max(1, Math.min(Number(line) || 1, document.lines));
      const lineInfo = document.line(safeLine);
      const safeColumn = Math.max(1, Number(column) || 1);
      const offset = Math.min(lineInfo.to, lineInfo.from + safeColumn - 1);
      view.dispatch({
        effects: EditorView.scrollIntoView(offset, {
          y: "center",
          yMargin: Math.max(0, Number(contextLines) || 0) * 12,
        }),
        selection: EditorSelection.cursor(offset),
      });
      view.focus();
      return { line: safeLine, column: safeColumn, offset };
    },
    lineAtOffset(offset = view.state.selection.main.head) {
      const safeOffset = clampOffset(offset, view.state.doc.length);
      const line = view.state.doc.lineAt(safeOffset);
      return { line: line.number, column: safeOffset - line.from + 1 };
    },
    replaceRange(start, end, value, selectionStart, selectionEnd) {
      const documentLength = view.state.doc.length;
      const from = clampOffset(start, documentLength);
      const to = Math.max(from, clampOffset(end, documentLength));
      const replacement = String(value ?? "");
      const nextLength = documentLength - (to - from) + replacement.length;
      const selectionFrom = clampOffset(
        selectionStart ?? from + replacement.length,
        nextLength,
      );
      const selectionTo = clampOffset(selectionEnd ?? selectionFrom, nextLength);
      view.dispatch({
        changes: { from, to, insert: replacement },
        selection: EditorSelection.single(selectionFrom, selectionTo),
      });
      view.focus();
    },
    setAriaLabel(value) {
      view.contentDOM.setAttribute("aria-label", String(value || "Markdown editor"));
    },
    setLocale(locale) {
      view.contentDOM.lang = locale === "fa" ? "fa" : "en";
      view.contentDOM.removeAttribute("dir");
    },
    get mode() {
      return editorMode;
    },
    /**
     * Switch between live preview and raw source.
     *
     * Only presentation changes; the document is the same Markdown either way,
     * so nothing downstream needs to know which mode is active.
     */
    setMode(value) {
      const next = normalizeEditorMode(value);
      if (next === editorMode) return editorMode;
      editorMode = next;
      view.dispatch({ effects: preview.reconfigure(editorModeExtension(next, { resolveAsset })) });
      mount.dataset.mode = next;
      view.dom.dataset.editorMode = next;
      return editorMode;
    },
    get theme() {
      return appearanceMode;
    },
    /**
     * Follow the workspace theme.
     *
     * The palette itself lives in CSS custom properties, but CodeMirror still
     * needs to know which side it is on so its own light/dark base rules and
     * floating panels match.
     */
    setTheme(mode) {
      const next = mode === "dark" || mode === "light" ? mode : documentTheme();
      if (next === appearanceMode) return appearanceMode;
      appearanceMode = next;
      view.dispatch({
        effects: appearance.reconfigure(mardasEditorAppearance(next === "dark")),
      });
      return appearanceMode;
    },
    /**
     * Run a named Markdown command.
     *
     * The toolbar, the keyboard, the command palette and the context menu all
     * come through here, so a formatting action means the same thing however
     * it was asked for.
     */
    runCommand(name) {
      if (disabled) return false;
      if (name === "undo") return undo(view);
      if (name === "redo") return redo(view);
      return runMarkdownCommand(view, name);
    },
    get typewriter() {
      return typewriterEnabled;
    },
    setTypewriter(value) {
      const next = Boolean(value);
      if (next === typewriterEnabled) return typewriterEnabled;
      typewriterEnabled = next;
      view.dispatch({ effects: writingRhythm.reconfigure(typewriterExtension(next)) });
      return typewriterEnabled;
    },
    /** The word under the caret, used to seed find and link editing. */
    selectionText() {
      const { from, to } = view.state.selection.main;
      return view.state.sliceDoc(from, to);
    },
    setDiagnostics(items = []) {
      const mapped = [];
      for (const item of Array.isArray(items) ? items : []) {
        if (item?.path || !Number(item?.line)) continue;
        const range = diagnosticRange(view.state.doc, item);
        mapped.push({
          ...range,
          message: String(item?.message || item?.code || "Document issue"),
          severity: severity(item?.severity),
          source: item?.code ? String(item.code) : "Mardas Folio",
        });
      }
      view.dispatch(setDiagnostics(view.state, mapped));
    },
    destroy() {
      view.scrollDOM.removeEventListener("scroll", scroll);
      view.dom.removeEventListener("contextmenu", contextMenu);
      view.destroy();
      mount.remove();
      textarea.hidden = false;
      textarea.removeAttribute("aria-hidden");
      textarea.tabIndex = 0;
    },
  };

  mount.dataset.readOnly = String(disabled);
  mount.dataset.mode = editorMode;
  view.dom.dataset.editorMode = editorMode;
  return adapter;
}
