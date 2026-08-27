import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { setDiagnostics } from "@codemirror/lint";
import { EditorState } from "@codemirror/state";

test("CodeMirror diagnostics use the state transaction contract", () => {
  const state = EditorState.create({ doc: "# Title" });
  const spec = setDiagnostics(state, [{ from: 0, to: 1, message: "Issue" }]);
  assert.doesNotThrow(() => state.update(spec));

  const source = readFileSync(
    new URL("../editor-src/codemirror-editor.mjs", import.meta.url),
    "utf8",
  );
  assert.match(source, /view\.dispatch\(setDiagnostics\(view\.state, mapped\)\)/);
  assert.doesNotMatch(source, /setDiagnostics\(view, mapped\)/);
});

test("Tab indents, and Escape gives the keyboard a way out of the editor", () => {
  const source = readFileSync(
    new URL("../editor-src/codemirror-editor.mjs", import.meta.url),
    "utf8",
  );
  // `indentWithTab` makes Tab indent, which is right for a document editor and
  // is also a keyboard trap: with it bound and nothing to release it, there is
  // no Tab from inside the document that reaches Save or Create PDF. The
  // release has to be in the same source as the binding, or removing one
  // silently leaves the other.
  assert.doesNotMatch(
    source,
    /import \{[^}]*indentWithTab/,
    "the trapping binding is no longer imported",
  );
  assert.match(source, /function tabEscapeHatch\(onLeave\)/);
  assert.match(
    source,
    /tabEscapeHatch\(onLeaveEditor\),/,
    "the hatch is installed, and the application decides where focus lands",
  );
  // Tab still does exactly what `indentWithTab` did when the hatch is not armed.
  assert.match(source, /key: "Tab", run: indentMore, shift: indentLess/);
  // Escape arms without claiming the key: an open completion popup still
  // closes on the same press and a selection still collapses.
  assert.match(source, /if \(event\.key === "Escape"\) \{\s*armed = true;/);
  assert.doesNotMatch(source, /key: "Escape"/, "Escape must not be a keymap binding");
  // The armed Tab has to stop the webview's own release, or focus lands on the
  // document instead of in the workbench's focus order.
  assert.match(source, /event\.preventDefault\(\);\s*return leave\(event\.shiftKey\)/);
  // Anything that is not Tab or Shift puts Tab back to indenting.
  assert.match(source, /event\.key === "Tab" \|\| event\.key === "Shift" \? false : disarm\(\)/);
  // An Escape nothing else wanted is claimed at the lowest precedence, so the
  // webview cannot answer it by blurring the document and taking the release
  // out of the workbench's hands. Higher precedence would take the key from
  // `closeCompletion` and `simplifySelection`, which is why it is last.
  assert.match(source, /Prec\.lowest\(\s*EditorView\.domEventHandlers/);
});
