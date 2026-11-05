/** A source gutter follows its document, never the workbench locale or caret. */
import { StateField } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { parseFrontMatter, frontMatterRange } from "../frontend/js/core/markdown-analysis.mjs";

// Direction is presentation metadata. A bounded sample prevents rescanning a
// book on every keystroke; code and URL spelling must not move prose's gutter.
const SAMPLE_LIMIT = 32768;
const RTL_LANGUAGE = /^(?:ar|fa|he|iw|ku|ps|sd|ug|ur|yi)(?:-|$)/i;
const RTL_LETTER = /[\p{Script=Arabic}\p{Script=Hebrew}\p{Script=Syriac}\p{Script=Thaana}\p{Script=Nko}\p{Script=Adlam}]/u;
const LETTER = /\p{Letter}/u;

export function sourceDocumentDirection(text) {
  const sample = String(text ?? "").slice(0, SAMPLE_LIMIT);
  const { fields } = parseFrontMatter(sample);
  const requested = fields.dir ?? fields.direction ?? fields.text_direction ?? fields.document_direction;
  const requestedDirection = String(requested).toLowerCase().replaceAll("_", "-");
  if (["rtl", "right-to-left"].includes(requestedDirection)) return "rtl";
  if (["ltr", "left-to-right"].includes(requestedDirection)) return "ltr";
  const language = fields.lang ?? fields.language;
  if (typeof language === "string" && language.trim() && language.toLowerCase() !== "auto") {
    return RTL_LANGUAGE.test(language.trim().replaceAll("_", "-")) ? "rtl" : "ltr";
  }
  const header = frontMatterRange(sample);
  const body = header ? sample.split("\n").slice(header.end + 1).join("\n") : sample;
  let fence = null, rtl = 0, ltr = 0;
  for (const line of body.split("\n")) {
    const mark = /^\s{0,3}(?:>\s*)*(?:[-+*]\s+)?(`{3,}|~{3,})/.exec(line)?.[1];
    if (mark) {
      if (!fence) fence = mark;
      else if (mark[0] === fence[0] && mark.length >= fence.length) fence = null;
      continue;
    }
    if (fence || /^(?: {4}|\t)/.test(line)) continue;
    const prose = line.replace(/`+[^`]*`+/g, "").replace(/https?:\/\/\S+/gi, "");
    for (const char of prose) {
      if (!LETTER.test(char)) continue;
      if (RTL_LETTER.test(char)) rtl += 1;
      else ltr += 1;
    }
  }
  return rtl > ltr ? "rtl" : "ltr";
}

const documentDirection = StateField.define({
  create: state => sourceDocumentDirection(state.doc.sliceString(0, SAMPLE_LIMIT)),
  update(value, transaction) {
    if (!transaction.docChanged) return value;
    let relevant = false;
    transaction.changes.iterChangedRanges(from => { if (from <= SAMPLE_LIMIT) relevant = true; });
    return relevant ? sourceDocumentDirection(transaction.newDoc.sliceString(0, SAMPLE_LIMIT)) : value;
  },
});

export const sourceGutterDirection = [
  documentDirection,
  EditorView.editorAttributes.from(documentDirection, direction => ({ "data-source-direction": direction })),
];
