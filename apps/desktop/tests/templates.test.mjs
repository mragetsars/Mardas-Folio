import test from "node:test";
import assert from "node:assert/strict";
import { templateContent, templateList } from "../frontend/js/core/templates.mjs";

test("document templates are local, bounded, and bilingual", () => {
  const templates = templateList();
  assert.deepEqual(templates.map((item) => item.id), ["blank", "report", "academic", "technical"]);
  for (const template of templates) {
    assert.equal("content" in template, false);
    const fa = templateContent(template.id, "fa");
    const en = templateContent(template.id, "en");
    assert.match(fa, /^---\n/);
    assert.match(en, /^---\n/);
    assert.ok(fa.length < 4096);
    assert.ok(en.length < 4096);
  }
  assert.match(templateContent("academic", "fa"), /citations: true/);
  assert.match(templateContent("missing", "en"), /# New document/);
});
