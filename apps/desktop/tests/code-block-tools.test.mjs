import test from "node:test";
import assert from "node:assert/strict";
import { EditorState } from "@codemirror/state";
import { markdown } from "@codemirror/lang-markdown";
import { syntaxTree } from "@codemirror/language";
import { codeBodyPrefixRanges, codeBodyText, codeLanguageChange, fencedCodeSpec } from "../editor-src/code-block-tools.mjs";

function fixture(doc) {
  const state = EditorState.create({ doc, extensions: [markdown()] });
  let spec;
  syntaxTree(state).iterate({ enter(node) { if (node.name === "FencedCode") { spec = fencedCodeSpec(state, node); return false; } } });
  return { state, spec };
}

test("fenced code controls copy only body and preserve long delimiters and attributes", () => {
  const source = '````javascript title="sample.js"\nconst code = "```";\n````';
  const { state, spec } = fixture(source);
  assert.equal(spec.language, "javascript");
  assert.equal(spec.attributes, 'title="sample.js"');
  assert.equal(state.doc.sliceString(spec.bodyFrom, spec.bodyTo), 'const code = "```";\n');
  const updated = state.update({ changes: codeLanguageChange(state, spec, "python") }).state.doc.toString();
  assert.equal(updated, source.replace("javascript", "python"));
});

test("tilde code fences retain indentation and unrecognised language labels", () => {
  const { state, spec } = fixture("  ~~~custom-lang  title=x\n  alpha\n  ~~~");
  assert.equal(spec.language, "custom-lang");
  assert.equal(spec.closeText, "~~~");
  assert.equal(state.doc.sliceString(spec.bodyFrom, spec.bodyTo), "  alpha\n");
  assert.equal(state.update({ changes: codeLanguageChange(state, spec, "javascript") }).state.doc.toString(),
    "  ~~~javascript  title=x\n  alpha\n  ~~~");
});

test("unclosed fences retain the final code line as content", () => {
  const { state, spec } = fixture("```python\nprint(1)");
  assert.equal(spec.closeFrom, null);
  assert.equal(spec.closeTo, null);
  assert.equal(state.doc.sliceString(spec.bodyFrom, spec.bodyTo), "print(1)");
});

test("plain text language keeps fence attributes and rejects source injection", () => {
  const { state, spec } = fixture("```js title=x\nalert(1)\n```");
  assert.equal(state.update({ changes: codeLanguageChange(state, spec, "") }).state.doc.toString(),
    "```text title=x\nalert(1)\n```");
  for (const language of ['python\n```', 'x y', '<img>', 'x"']) assert.equal(codeLanguageChange(state, spec, language), null);
  assert.equal(codeLanguageChange(state, spec, "js"), null);
});

test("empty language is inserted without rewriting delimiters or code", () => {
  const { state, spec } = fixture("```\n\n```");
  assert.equal(spec.language, "");
  assert.equal(state.update({ changes: codeLanguageChange(state, spec, "json") }).state.doc.toString(), "```json\n\n```");
});

test("Copy excludes quoted and list container prefixes while preserving code indentation", () => {
  for (const [source, expected] of [
    ["> ```js\n> console.log(1);\n>   nested();\n> ```", "console.log(1);\n  nested();\n"],
    [">```js\n> code\n>```", "code\n"],
    ["> > ```js\n>> code\n> > ```", "code\n"],
    ["- Item\n\n  ```js\n  console.log(1);\n    nested();\n  ```", "console.log(1);\n  nested();\n"],
    ["- ```js\n  console.log(1);\n  ```", "console.log(1);\n"],
    ["  ```js\n    nested();\n  ```", "  nested();\n"],
  ]) {
    const { state, spec } = fixture(source);
    assert.equal(codeBodyText(state, spec), expected, source);
  }
});

test("empty nested code keeps its continuation prefix and nonempty Edit skips that prefix", () => {
  for (const [source, prefix] of [["> ```\n> ```", "> "], ["- ```\n  ```", "  "], ["> - ```\n>   ```", ">   "]]) {
    const { spec } = fixture(source);
    assert.equal(spec.bodyPrefix, prefix);
    assert.equal(spec.bodyFrom, spec.bodyTo);
  }
  const { state, spec } = fixture("> ```\n> alpha\n> ```");
  assert.equal(state.doc.sliceString(spec.editFrom, spec.editFrom + 5), "alpha");
});

test("rendered code hides continuation scaffold but preserves semantic indentation and operators", () => {
  for (const [source, visible] of [
    ["> ```js\n> code > 1\n>   nested();\n> ```", ["code > 1", "  nested();", "```"]],
    [">```js\n> code\n>```", ["code", "```"]],
    ["> > ```js\n>> code\n> > ```", ["code", "```"]],
    ["- ```js\n  code\n    nested();\n  ```", ["code", "  nested();", "```"]],
    ["> - ```js\n>   code\n>     nested();\n>   ```", ["code", "  nested();", "```"]],
  ]) {
    const { state, spec } = fixture(source);
    const ranges = new Map(codeBodyPrefixRanges(state, spec));
    const rows = [];
    for (let number = 2; number <= state.doc.lines; number += 1) {
      const line = state.doc.line(number);
      rows.push(state.doc.sliceString(ranges.get(line.from) ?? line.from, line.to));
    }
    assert.deepEqual(rows, visible, source);
    assert.equal(state.doc.toString(), source);
  }
});
