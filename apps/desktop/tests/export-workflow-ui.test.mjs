import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const index = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
const panel = readFileSync(new URL("../frontend/js/ui/export-options-panel.mjs", import.meta.url), "utf8");
const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");

test("PDF creation submits the export form from the separate action bar", () => {
  assert.match(index, /stylesheet" href="\.\/export-workflow\.css"/);
  assert.match(index, /<\/form>[\s\S]*?<footer class="export-dock panel">[\s\S]*?<button[^>]+id="export-button"[^>]+type="submit"[^>]+form="export-form"/);
});

test("dependent export controls are disabled, and changing a value keeps keyboard focus", () => {
  assert.match(panel, /if \(!active\) \{[\s\S]*row\.querySelectorAll\("input, select, textarea, button"\)\.forEach\(\(control\) => \{\s*control\.disabled = true;/);
  assert.match(panel, /function setOptionValue\(key, value\) \{[\s\S]*const focusIndex = controls\.indexOf\(active\);[\s\S]*nextControl\?\.focus\(\{ preventScroll: true \}\)/);
});

test("page preview reports ready only after the paper deck finishes laying out", () => {
  assert.match(main, /await deck\.render\(result,[^\n]+\);[\s\S]*setExportPreviewState\(""\)/);
});

test("setup starts with a labelled preset and advanced settings collapsed", () => {
  assert.match(index, /<label for="export-preset"/);
  assert.match(index, /id="export-open-settings"[^>]*aria-controls="export-settings"[^>]*aria-expanded="false"/);
  assert.match(index, /id="export-settings" hidden/);
});

test("the empty paper preview explains how to start and disables page controls until a source is loaded", () => {
  assert.match(index, /id="export-preview-empty"[\s\S]*data-i18n="exportPreviewEmptyHelp"[\s\S]*id="preview-choose-source"/);
  for (const id of ["preview-zoom-in", "preview-fit-page", "preview-next-page", "export-button"]) {
    assert.match(index, new RegExp(`<button[^>]+id="${id}"[^>]+disabled`));
  }
});
