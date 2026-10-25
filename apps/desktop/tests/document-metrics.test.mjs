import test from "node:test";
import assert from "node:assert/strict";
import { createDocumentMetrics } from "../frontend/js/core/document-metrics.mjs";
import { textMetrics } from "../frontend/js/core/markdown-analysis.mjs";

test("moving through a long document analyzes words once and retains current cursor", () => {
  let scans = 0;
  const metrics = createDocumentMetrics((...args) => { scans++; return textMetrics(...args); });
  const model = { content: "متن فارسی and English\n".repeat(15000), contentVersion: 0 };
  for (let line = 1; line <= 100; line++) {
    const result = metrics(model, { line, column: 3 });
    assert.equal(result.words, 60000);
    assert.equal(result.line, line);
    assert.equal(result.column, 3);
  }
  assert.equal(scans, 1);
  model.content += " تازه";
  model.contentVersion++;
  assert.equal(metrics(model).words, 60001);
  assert.equal(scans, 2);
});

test("switching documents, undo and empty text keep independent counts", () => {
  const metrics = createDocumentMetrics();
  const first = { content: "one two", contentVersion: 0 };
  const second = { content: "سه", contentVersion: 0 };
  assert.equal(metrics(first).words, 2);
  assert.equal(metrics(second).words, 1);
  first.content = "";
  first.contentVersion++;
  assert.equal(metrics(first).words, 0);
  first.content = "one two";
  first.contentVersion++;
  assert.equal(metrics(first).words, 2);
  assert.equal(metrics(second).words, 1);
});
