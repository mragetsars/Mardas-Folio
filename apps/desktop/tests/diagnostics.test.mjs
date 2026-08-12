import test from "node:test";
import assert from "node:assert/strict";
import {
  diagnosticLines,
  inlineDiagnosticsForDocument,
} from "../frontend/js/core/diagnostics.mjs";

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

test("a validation failure explains itself instead of only saying it failed", () => {
  const payload = {
    code: "MARDAS-VALIDATION-FAILED",
    message: "Document validation failed.",
    details: {
      diagnostics: [
        {
          code: "MARDAS-E704",
          severity: "error",
          message: "Citation key is not defined: nosuchkey",
          line: 42,
          column: 7,
          hint: "Add the key to a configured .bib or CSL .json bibliography source.",
        },
        { code: "MARDAS-E999", severity: "warning", message: "cosmetic" },
        { code: "MARDAS-E705", severity: "error", message: "Malformed citation marker" },
      ],
    },
  };

  assert.deepEqual(diagnosticLines(payload), [
    "Citation key is not defined: nosuchkey (42:7) — Add the key to a configured"
      + " .bib or CSL .json bibliography source.",
    "Malformed citation marker",
  ]);
});

test("diagnostic lines stay bounded and tolerate errors that carry none", () => {
  const many = {
    details: {
      diagnostics: Array.from({ length: 20 }, (_, index) => ({
        severity: "error",
        message: `problem ${index}`,
      })),
    },
  };

  assert.equal(diagnosticLines(many).length, 8);
  assert.equal(diagnosticLines(many, 3).length, 3);
  assert.deepEqual(diagnosticLines({ message: "engine stopped" }), []);
  assert.deepEqual(diagnosticLines(undefined), []);
  assert.deepEqual(diagnosticLines({ details: { diagnostics: "not a list" } }), []);
});
