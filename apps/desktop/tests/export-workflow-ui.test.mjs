import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const index = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
const styles = readFileSync(new URL("../frontend/export-workflow.css", import.meta.url), "utf8");
const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");

test("export has a focused paper preview and keeps destination actions outside the settings scroll", () => {
  assert.match(index, /stylesheet" href="\.\/export-workflow\.css"/);
  assert.match(index, /id="export-preview"/);
  assert.match(index, /class="panel export-dock"/);
  assert.match(styles, /#export-view \.export-preview-panel\s*\{[^}]*height:\s*clamp\(/);
  assert.match(styles, /#export-view \.export-dock\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto/);
  assert.match(styles, /@media \(max-width: 1180px\)[\s\S]*#export-view \.export-layout \{ grid-template-columns: minmax\(0, 1fr\); \}[\s\S]*#export-view \.export-side \{ position: static; \}/);
});

test("idle export status is compact and the settings summary can be expanded", () => {
  assert.match(index, /<details class="summary-details">[\s\S]*id="preset-summary"/);
  assert.match(styles, /\.status-panel\[data-state="idle"\]/);
  assert.match(main, /\$\("\.status-panel"\)\.dataset\.state = kind/);
});

test("the empty paper preview explains how to start and disables page controls until a source is loaded", () => {
  assert.match(index, /id="export-preview-empty"[\s\S]*data-i18n="previewEmptyTitle"[\s\S]*data-i18n="previewChooseSourceHelp"/);
  assert.match(styles, /\.export-preview-empty\s*\{[^}]*position:\s*absolute[^}]*background:\s*var\(--ui-panel\)/);
  assert.match(main, /function setExportPreviewHasSource\(hasSource\)[\s\S]*emptyState\.hidden = Boolean\(hasSource\)/);
  assert.match(main, /for \(const id of \["#preview-zoom-out"[\s\S]*if \(button\) button\.disabled = !hasPages/);
  assert.match(main, /level\.textContent = hasPages \? `\$\{Math\.round\(\(deckState\.zoom \|\| 1\) \* 100\)\}%` : "—"/);
});
