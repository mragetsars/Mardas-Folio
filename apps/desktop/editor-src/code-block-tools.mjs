/** Fenced code stays in CodeMirror; only its Markdown scaffolding is a widget. */
import { EditorSelection, Transaction } from "@codemirror/state";
import { isolateHistory } from "@codemirror/commands";
import { WidgetType } from "@codemirror/view";
import { createCopyButton } from "../frontend/js/ui/copy-button.mjs";

const TEXT = {
  en: {
    block: "Code block",
    language: "Code language",
    plain: "Plain text",
    edit: "Edit code",
    copy: "Copy code",
    copied: "Copied",
    failed: "Copy failed",
  },
  fa: {
    block: "بلوک کد",
    language: "زبان کد",
    plain: "متن ساده",
    edit: "ویرایش کد",
    copy: "کپی کد",
    copied: "کپی شد",
    failed: "کپی نشد",
  },
};
const LANGUAGES = [
  "javascript",
  "typescript",
  "python",
  "bash",
  "json",
  "html",
  "css",
  "sql",
  "rust",
  "java",
  "c",
  "cpp",
  "markdown",
  "yaml",
];

function codeBodyPrefix(opener, opening) {
  // A fence may start on the list-marker row. Continuation code belongs under
  // the marker's content column, while blockquote marks remain structural.
  return opener.text
    .slice(0, opening.from - opener.from)
    .replace(/(?:[-+*]|\d+[.)])[ \t]+$/, (marker) => " ".repeat(marker.length));
}

function stripCodePrefix(line, prefix) {
  if (!prefix) return line;
  let content = line,
    rest = prefix;
  // Quote marks may independently include their optional following space on
  // each physical row (`>````, `> code`, `>> code`). They are still the same
  // structural prefix, rather than code indentation to copy or edit.
  for (;;) {
    const expected = /^[ \t]*> ?/.exec(rest);
    if (!expected) break;
    const actual = /^[ \t]*> ?/.exec(content);
    if (!actual) return line;
    rest = rest.slice(expected[0].length);
    content = content.slice(actual[0].length);
  }
  if (content.startsWith(rest)) return content.slice(rest.length);
  if (/^ *$/.test(rest)) return content.replace(new RegExp(`^ {0,${rest.length}}`), "");
  return content;
}

/** Copy semantic code, omitting list/quote/fence indentation scaffolding. */
export function codeBodyText(state, spec) {
  return state.doc
    .sliceString(spec.bodyFrom, spec.bodyTo)
    .split("\n")
    .map((line) => stripCodePrefix(line, spec.bodyPrefix))
    .join("\n");
}

/** Hide container/fence indentation, keeping every semantic code space. */
export function codeBodyPrefixRanges(state, spec) {
  const ranges = [];
  const first = state.doc.lineAt(spec.openerFrom).number + 1;
  const last = state.doc.lineAt(spec.to).number;
  for (let number = first; number <= last; number += 1) {
    const line = state.doc.line(number);
    const length = line.text.length - stripCodePrefix(line.text, spec.bodyPrefix).length;
    if (length) ranges.push([line.from, line.from + length]);
  }
  return ranges;
}

/** Positions come from the actual parsed node, including longer/tilde fences. */
export function fencedCodeSpec(state, value) {
  const node = value.node || value;
  if (node.name !== "FencedCode") return null;
  const opener = state.doc.lineAt(node.from);
  const marks = [];
  for (let child = node.firstChild; child; child = child.nextSibling) {
    if (child.name === "CodeMark") marks.push(child);
  }
  if (!marks.length) return null;
  const opening = marks[0];
  const closing =
    marks.length > 1 && state.doc.lineAt(marks.at(-1).from).number > opener.number
      ? marks.at(-1)
      : null;
  const rawInfo = state.doc.sliceString(opening.to, opener.to);
  const language = /^\s*(\S+)/.exec(rawInfo);
  const languageFrom = language ? opening.to + language[0].length - language[1].length : opening.to;
  const languageTo = language ? languageFrom + language[1].length : languageFrom;
  const bodyFrom = Math.min(opener.to + 1, state.doc.length);
  const bodyTo = closing ? state.doc.lineAt(closing.from).from : node.to;
  const bodyPrefix = codeBodyPrefix(opener, opening);
  return {
    from: node.from,
    to: node.to,
    openerFrom: opener.from,
    openerTo: opener.to,
    openerText: opener.text,
    languageFrom,
    languageTo,
    language: language?.[1] || "",
    attributes: state.doc.sliceString(languageTo, opener.to).trim(),
    bodyFrom,
    bodyTo,
    bodyPrefix,
    editFrom:
      bodyFrom < bodyTo
        ? bodyFrom +
          state.doc.lineAt(bodyFrom).text.length -
          stripCodePrefix(state.doc.lineAt(bodyFrom).text, bodyPrefix).length
        : bodyFrom,
    closeFrom: closing?.from ?? null,
    closeTo: closing?.to ?? null,
    closeText: closing ? state.doc.sliceString(closing.from, closing.to) : "",
  };
}

function currentSpec(view, spec) {
  return (
    spec.to <= view.state.doc.length &&
    view.state.doc.lineAt(spec.openerFrom).text === spec.openerText &&
    (spec.closeFrom == null ||
      view.state.doc.sliceString(spec.closeFrom, spec.closeTo) === spec.closeText)
  );
}

export function codeLanguageChange(state, spec, language) {
  if (!/^[A-Za-z0-9_+.#-]*$/.test(language)) return null;
  // Keeping attributes after a missing language would turn the first one into
  // the language. An explicit text language retains their exact spelling.
  const insert = language || (spec.attributes ? "text" : "");
  if (state.doc.sliceString(spec.languageFrom, spec.languageTo) === insert) return null;
  return { from: spec.languageFrom, to: spec.languageTo, insert };
}

export class CodeBlockHeaderWidget extends WidgetType {
  constructor(spec, locale = "en", readOnly = false) {
    super();
    this.spec = spec;
    this.locale = locale;
    this.readOnly = readOnly;
  }
  eq(other) {
    return (
      this.locale === other.locale &&
      this.readOnly === other.readOnly &&
      Object.keys(this.spec).every((key) => this.spec[key] === other.spec[key])
    );
  }
  ignoreEvent() {
    return true;
  }
  toDOM(view) {
    const spec = this.spec;
    const labels = TEXT[this.locale] || TEXT.en;
    const root = document.createElement("span");
    root.className = "cm-code-header";
    root.contentEditable = "false";
    root.setAttribute("role", "group");
    root.setAttribute("aria-label", labels.block);
    const language = document.createElement("select");
    language.className = "cm-code-language";
    language.setAttribute("aria-label", labels.language);
    const options = ["", ...LANGUAGES];
    if (spec.language && spec.language !== "text" && !options.includes(spec.language))
      options.push(spec.language);
    for (const value of options) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value || labels.plain;
      language.append(option);
    }
    language.value = spec.language === "text" ? "" : spec.language;
    language.disabled = view.state.readOnly;
    language.addEventListener("change", () => {
      if (view.state.readOnly || !currentSpec(view, spec)) return;
      const change = codeLanguageChange(view.state, spec, language.value);
      if (change)
        view.dispatch({
          changes: change,
          annotations: [isolateHistory.of("full"), Transaction.userEvent.of("input.code-language")],
        });
      view.focus();
    });
    language.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        view.focus();
      }
    });
    const actions = document.createElement("span");
    actions.className = "cm-code-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = labels.edit;
    edit.disabled = view.state.readOnly;
    edit.addEventListener("click", () => {
      if (view.state.readOnly || !currentSpec(view, spec)) return;
      let position = spec.editFrom;
      const transaction = { selection: EditorSelection.cursor(position), scrollIntoView: true };
      if (spec.bodyFrom === spec.bodyTo) {
        // Empty/unclosed fences still need a real editable body row. This is
        // one normal source transaction, so one Undo restores the original.
        const needsOpeningBreak = spec.bodyFrom === spec.openerTo;
        transaction.changes = {
          from: position,
          insert: needsOpeningBreak ? `\n${spec.bodyPrefix}\n` : `${spec.bodyPrefix}\n`,
        };
        position += spec.bodyPrefix.length + (needsOpeningBreak ? 1 : 0);
        transaction.selection = EditorSelection.cursor(position);
        transaction.annotations = [
          isolateHistory.of("full"),
          Transaction.userEvent.of("input.code-body"),
        ];
      }
      view.dispatch(transaction);
      view.focus();
    });
    const copy = createCopyButton(document, {
      read: () => (currentSpec(view, spec) ? codeBodyText(view.state, spec) : null),
      labels,
      className: "cm-code-copy",
    });
    actions.append(edit, copy);
    root.append(language, actions);
    return root;
  }
}
