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
