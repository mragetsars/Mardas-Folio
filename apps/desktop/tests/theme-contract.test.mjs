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

/**
 * Read a custom property out of a declaration block.
 *
 * These assertions deliberately resolve the palette that is actually declared
 * instead of pinning hex literals. Pinning values meant a palette change failed
 * the suite for changing colour rather than for breaking a contract, which told
 * nobody anything useful; what has to hold is that the tokens exist and that
 * the resulting text clears WCAG AA.
 */
function tokens(css, selector) {
  const start = css.indexOf(selector);
  assert.notEqual(start, -1, `expected a ${selector} block`);
  const block = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries(
    [...block.matchAll(/(--[a-z-]+):\s*(#[0-9a-fA-F]{3,8})\s*;/g)].map((m) => [m[1], m[2]]),
  );
}

test("dark authoring controls and preview headings have explicit theme overrides", () => {
  for (const selector of [
    'html[data-theme="dark"] .formatting{',
    'html[data-theme="dark"] .formatting button{',
    'html[data-theme="dark"] .preview-source-link.source-active{',
  ]) {
    assert.ok(styles.includes(selector), `missing dark override for ${selector}`);
  }
  assert.match(styles, /html\[data-theme="dark"\] \.preview-document h6,/);
});

test("workspace surface tokens keep small UI text above AA contrast", () => {
  const light = tokens(workspaceStyles, ":root {");
  const dark = tokens(workspaceStyles, 'html[data-theme="dark"] {');

  const pairs = [
    ["light muted on soft panel", light["--ui-muted"], light["--ui-panel-soft"]],
    ["light muted on panel", light["--ui-muted"], light["--ui-panel"]],
    ["light accent on panel", light["--ui-accent"], light["--ui-panel"]],
    ["light text on panel", light["--ui-text"], light["--ui-panel"]],
    ["dark muted on soft panel", dark["--ui-muted"], dark["--ui-panel-soft"]],
    ["dark muted on panel", dark["--ui-muted"], dark["--ui-panel"]],
    ["dark accent on panel", dark["--ui-accent"], dark["--ui-panel"]],
    ["dark text on panel", dark["--ui-text"], dark["--ui-panel"]],
  ];

  for (const [label, foreground, background] of pairs) {
    assert.ok(foreground && background, `${label}: token missing`);
    const ratio = contrast(foreground, background);
    assert.ok(ratio >= 4.5, `${label}: ${foreground} on ${background} is ${ratio.toFixed(2)}:1`);
  }
});

test("text drawn on the accent fill stays legible in both themes", () => {
  // The light accent is dark and takes white; the dark accent is a light orange
  // where white would fall to 2.2:1, so it takes ink instead.
  for (const selector of [":root {", 'html[data-theme="dark"] {']) {
    const palette = tokens(workspaceStyles, selector);
    const ratio = contrast(palette["--ui-on-accent"], palette["--ui-accent"]);
    assert.ok(ratio >= 4.5, `${selector} on-accent contrast is ${ratio.toFixed(2)}:1`);
  }
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

test("narrow book chapter rows preserve titles and reveal actions on intent", () => {
  assert.match(workspaceStyles, /\.book-chapter-row \{[\s\S]*?grid-template-columns: 18px minmax\(0, 1fr\);/);
  assert.match(workspaceStyles, /\.book-chapter-actions \{[\s\S]*?position: absolute;/);
  assert.match(workspaceStyles, /\.book-chapter-row:focus-within \.book-chapter-actions/);
  assert.match(workspaceStyles, /\.book-actions-primary \{[\s\S]*?grid-template-columns: 1fr;/);
});

test("every stylesheet is brace-balanced", () => {
  // A single unmatched brace silently disables every rule after it, and a
  // minified stylesheet gives no visual clue that it happened.
  for (const name of ["styles.css", "workspace.css"]) {
    const css = readFileSync(new URL(`../frontend/${name}`, import.meta.url), "utf8");
    let depth = 0;
    for (const character of css) {
      if (character === "{") depth += 1;
      else if (character === "}") depth -= 1;
      assert.ok(depth >= 0, `${name} closes a block that was never opened`);
    }
    assert.equal(depth, 0, `${name} leaves ${depth} block(s) open`);
  }
});
