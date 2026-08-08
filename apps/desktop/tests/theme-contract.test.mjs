import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const styles = readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");

function channel(value) {
  const normalized = value / 255;
  return normalized <= 0.04045
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4;
}

function luminance(hex) {
  const channels = hex.match(/[a-f\d]{2}/gi).map((value) => channel(Number.parseInt(value, 16)));
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(foreground, background) {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

test("dark authoring controls and preview headings have explicit theme overrides", () => {
  assert.match(styles, /html\[data-theme="dark"\] \.formatting\{background:#182628;border-color:#40585a\}/);
  assert.match(styles, /html\[data-theme="dark"\] \.formatting button\{color:#d9efec\}/);
  assert.match(styles, /html\[data-theme="dark"\] \.preview-document h6,[\s\S]*?\.preview-source-link\{color:var\(--brand2\)\}/);
  assert.match(styles, /html\[data-theme="dark"\] \.preview-source-link\.source-active\{background:rgba\(94,234,212,\.14\)\}/);
});

test("dark preview heading color exceeds WCAG AA contrast", () => {
  assert.ok(contrast("#99f6e4", "#1d2b2d") >= 4.5);
});
