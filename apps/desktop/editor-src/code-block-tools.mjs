/** Fenced code stays in CodeMirror; only its Markdown scaffolding is a widget. */
import { EditorSelection, MapMode, StateEffect, StateField, Transaction } from "@codemirror/state";
import { isolateHistory } from "@codemirror/commands";
import { WidgetType } from "@codemirror/view";
import { createCopyButton } from "../frontend/js/ui/copy-button.mjs";
import { createCodeWrapButton } from "../frontend/js/ui/code-wrap.mjs";

export const setCodeWrap = StateEffect.define();
export const codeWrapState = StateField.define({
  create: () => new Set(),
  update(value, transaction) {
    const effect = transaction.effects.find((item) => item.is(setCodeWrap));
    if (!effect && !transaction.docChanged) return value;
    const next = new Set();
    for (const position of value) {
      const mapped = transaction.changes.mapPos(position, 1, MapMode.TrackDel);
      if (mapped != null) next.add(mapped);
    }
    if (effect) {
      if (effect.value.wrapped) next.delete(effect.value.position);
      else next.add(effect.value.position);
    }
    return next;
  },
});

export function wrapsCode(state, position) {
  return !state.field(codeWrapState, false)?.has(position);
}

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
  "diff",
  "go",
  "csharp",
  "ruby",
  "lua",
  "powershell",
  "dockerfile",
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

const range = /^(\d+)(?:-(\d+))?$/;
const lineNumber = /^(?:linenos|line-?numbers|numberlines|numbered)$/i;

function lineRanges(value) {
  return value.split(/[,;\s]+/).flatMap((part) => {
    const match = range.exec(part);
    if (!match) return [];
    const first = Number(match[1]);
    const last = Number(match[2] || match[1]);
    return Number.isSafeInteger(last) && first > 0 && last >= first ? [[first, last]] : [];
  });
}

export function codePresentation(attributes) {
  const values = new Map();
  const bare = attributes.replace(
    /([a-z][\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s}]+))/gi,
    (_, key, double, single, plain) => {
      values.set(key.toLowerCase(), double ?? single ?? plain);
      return " ";
    },
  );
  const options = Array.from(values);
  const option = (keys) => options.find(([key]) => keys.test(key))?.[1] ?? "";
  const start = Number(option(/^(?:start|start-?line|line-start|lineno-?start|first-line)$/));
  const numbered =
    bare.split(/[{}\s]+/).some((word) => lineNumber.test(word.replace(/^\./, ""))) ||
    options.some(
      ([key, value]) => lineNumber.test(key) && /^(?:1|true|yes|on|table|inline)$/i.test(value),
    );
  const ranges = options
    .filter(([key]) => /^(?:hl[_-]lines|highlight|line-highlight|lines|emphasize-lines)$/.test(key))
    .flatMap(([, value]) => lineRanges(value));
  for (const brace of bare.matchAll(/\{([0-9,;\s-]+)\}/g)) ranges.push(...lineRanges(brace[1]));
  return {
    title: option(/^(?:title|filename|file|caption|name)$/),
    numbered,
    start: Number.isSafeInteger(start) && start > 0 ? start : 1,
    ranges,
    added: lineRanges(option(/^(?:added|added-lines)$/)),
    removed: lineRanges(option(/^(?:removed|removed-lines)$/)),
  };
}

export function codeRowAttributes(state, spec, at) {
  const { numbered, start, ranges, added, removed } = spec.presentation;
  const diff = /^(diff|patch)$/i.test(spec.language);
  if (!numbered && !ranges.length && !added.length && !removed.length && !diff) return null;
  if (at < spec.bodyFrom || at >= spec.bodyTo) return null;
  const line = state.doc.lineAt(at);
  const index = line.number - state.doc.lineAt(spec.openerFrom).number;
  const number = index + start - 1;
  // Follow the publisher: a range reaching below the first displayed
  // number uses snippet-relative numbering for that option.
  const inRanges = (list) => {
    const shouldUseSourceNumbers = start > 1 && list.every(([first]) => first >= start);
    const lineNumber = shouldUseSourceNumbers ? number : index;
    return list.some(([first, last]) => lineNumber >= first && lineNumber <= last);
  };
  const text = diff ? stripCodePrefix(line.text, spec.bodyPrefix) : "";
  return {
    number: numbered ? String(number) : "",
    highlighted: inRanges(ranges),
    added: inRanges(added) || (diff && /^\+(?!\+\+)/.test(text)),
    removed: inRanges(removed) || (diff && /^-(?!--)/.test(text)),
  };
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
  const firstToken = /^\s*(\S+)/.exec(rawInfo);
  const brace = /^\s*\{([^}]*)\}/.exec(rawInfo);
  const languageClass = brace && /(?:^|\s)\.([a-z_][\w.+#-]*)/i.exec(brace[1]);
  const language = brace ? languageClass?.[1] || "" : firstToken?.[1] || "";
  const infoStart = opening.to + rawInfo.length - rawInfo.trimStart().length;
  const languageFrom = languageClass
    ? opening.to +
      rawInfo.indexOf("{") +
      1 +
      languageClass.index +
      languageClass[0].length -
      language.length
    : infoStart;
  const languageTo = languageFrom + language.length;
  const attributes = (
    brace ? rawInfo.trimStart() : state.doc.sliceString(languageTo, opener.to)
  ).trim();
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
    language,
    hasBrace: Boolean(brace),
    attributes,
    presentation: codePresentation(attributes),
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
  const name = language || (spec.attributes ? "text" : "");
  const insert = spec.hasBrace && !spec.language ? name + " " : name;
  if (state.doc.sliceString(spec.languageFrom, spec.languageTo) === insert) return null;
  return { from: spec.languageFrom, to: spec.languageTo, insert };
}

export class CodeBlockHeaderWidget extends WidgetType {
  constructor(spec, locale = "en", readOnly = false, wrapped = true) {
    super();
    this.spec = spec;
    this.locale = locale;
    this.readOnly = readOnly;
    this.wrapped = wrapped;
  }
  eq(other) {
    return (
      this.locale === other.locale &&
      this.readOnly === other.readOnly &&
      this.wrapped === other.wrapped &&
      Object.keys(this.spec).every(
        (key) => key === "presentation" || this.spec[key] === other.spec[key],
      )
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
    const wrap = createCodeWrapButton(document, this.wrapped, (wrapped) => {
      if (!currentSpec(view, spec)) return;
      view.dispatch({ effects: setCodeWrap.of({ position: spec.openerFrom, wrapped }) });
      requestAnimationFrame(() => {
        const line = view.domAtPos(spec.openerFrom).node;
        (line.nodeType === 1 ? line : line.parentElement)
          ?.closest(".cm-line")
          ?.querySelector(".code-wrap-button")
          ?.focus({ preventScroll: true });
      });
    });
    actions.append(edit, wrap, copy);
    const identity = document.createElement("span");
    identity.className = "cm-code-identity";
    if (spec.presentation.title) {
      const title = document.createElement("span");
      title.className = "cm-code-filename";
      title.textContent = title.title = spec.presentation.title;
      title.dir = "auto";
      identity.append(title);
    }
    identity.append(language);
    root.append(identity, actions);
    return root;
  }
}
