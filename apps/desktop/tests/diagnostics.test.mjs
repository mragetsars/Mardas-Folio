import test from "node:test";
import assert from "node:assert/strict";
import { inlineDiagnosticsForDocument } from "../frontend/js/core/diagnostics.mjs";

test("inline diagnostics keep only locations belonging to the current document", () => {
  const document = {
    path: "C:\\Books\\chapters\\one.md",
    projectRelativePath: "chapters/one.md",
  };
  const source = [
    { code: "A", path: "c:/books/chapters/ONE.md", line: 2, message: "absolute" },
    { code: "B", path: "chapters/one.md", line: 3, message: "relative" },
    { code: "C", path: "chapters/two.md", line: 4, message: "other chapter" },
    { code: "D", line: 5, message: "pathless" },
    { code: "E", path: "chapters/one.md", message: "no source line" },
  ];

  assert.deepEqual(inlineDiagnosticsForDocument(source, document), [
    { code: "A", line: 2, message: "absolute" },
    { code: "B", line: 3, message: "relative" },
    { code: "D", line: 5, message: "pathless" },
  ]);
  assert.equal(source[0].path, "c:/books/chapters/ONE.md");
});

test("untitled editor diagnostics match the engine's synthetic input path", () => {
  assert.deepEqual(
    inlineDiagnosticsForDocument(
      [{ path: "untitled.md", line: 1, message: "draft" }],
      { path: null },
    ),
    [{ line: 1, message: "draft" }],
  );
});
