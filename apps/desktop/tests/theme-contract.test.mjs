import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const styles = readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");
const workspaceStyles = readFileSync(new URL("../frontend/workspace.css", import.meta.url), "utf8");

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

test("workspace surface tokens keep small UI text above AA contrast", () => {
  assert.match(workspaceStyles, /--ui-muted: #5f7375;/);
  assert.ok(contrast("#5f7375", "#f7f9f9") >= 4.5);
  assert.ok(contrast("#8fa3a4", "#162124") >= 4.5);
  assert.ok(contrast("#47d7c2", "#121a1c") >= 4.5);
});

test("publishing and recent-document cards keep explicit layout hooks", () => {
  const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");
  assert.match(main, /row\.className = "summary-row"/);
  assert.match(main, /class="recent-copy"/);
  assert.match(main, /class="recent-arrow"/);
  assert.match(workspaceStyles, /#export-view \.preset-card \{/);
  assert.match(workspaceStyles, /#preset-summary \.summary-row \{/);
  assert.match(workspaceStyles, /#start-view \.recent-copy \{/);
});

test("settings scrolling and preview anchors are deliberately constrained", () => {
  assert.match(workspaceStyles, /\.settings-card \{[\s\S]*?grid-template-rows: auto auto minmax\(0, 1fr\) auto auto;[\s\S]*?overflow: hidden;/);
  assert.match(workspaceStyles, /\.settings-card \.settings-sections \{[\s\S]*?overflow: auto;/);
  assert.match(workspaceStyles, /\.preview-document \.heading-anchor \{[\s\S]*?opacity: 0;/);
  assert.match(workspaceStyles, /\.preview-document :is\(h1, h2, h3, h4, h5, h6\):hover \.heading-anchor/);
});


test("final workspace polish keeps sticky export status and stronger chrome affordances", () => {
  assert.match(workspaceStyles, /#export-view \.status-panel \{[\s\S]*?position: sticky;/);
  assert.match(workspaceStyles, /\.document-tab\.active \{[\s\S]*?box-shadow:/);
  assert.match(workspaceStyles, /\.sidebar-tabs button\.active \.sidebar-tab-icon,/);
  assert.match(workspaceStyles, /\.command-card \.command-search input \{/);
});

test("book and export workflows expose durable result and active-chapter affordances", () => {
  const index = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
  const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");
  assert.match(index, /id="export-result"/);
  assert.match(index, /id="book-output-result"/);
  assert.match(index, /id="book-current-chapter"/);
  assert.match(main, /state\.bookOutputPath = result\?\.output_path \|\| outputPath/);
  assert.match(main, /aria-current", "page"/);
  assert.match(workspaceStyles, /\.book-chapter-row\.active \{/);
  assert.match(workspaceStyles, /\.export-result \{/);
});

test("onboarding and light theme use the same native surface tokens", () => {
  const index = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
  assert.match(index, /id="onboarding-intent-summary"/);
  assert.match(workspaceStyles, /\.onboarding-intent-summary \{/);
  assert.match(workspaceStyles, /html\[data-theme="light"\] \.panel,/);
  assert.match(workspaceStyles, /\.choice-card,[\s\S]*?\.shortcut-hints span \{/);
});
