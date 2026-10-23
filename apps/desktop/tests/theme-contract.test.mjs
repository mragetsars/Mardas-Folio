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
 * Read a custom property out of a declaration block, following one hop.
 *
 * These assertions deliberately resolve the palette that is actually declared
 * instead of pinning hex literals. Pinning values meant a palette change failed
 * the suite for changing colour rather than for breaking a contract, which told
 * nobody anything useful; what has to hold is that the tokens exist and that
 * the resulting text clears WCAG AA.
 *
 * A role now usually names a step of the shared ramp — `--ui-panel-soft:
 * var(--neutral-50)` — rather than repeating its hex, which is the point of
 * having a ramp. The ramp itself is declared once, in `:root`, so a `var()`
 * is resolved against `:root` whichever block it was read from.
 */
function declarations(css, selector) {
  const start = css.indexOf(selector);
  assert.notEqual(start, -1, `expected a ${selector} block`);
  const block = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries(
    [...block.matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]),
  );
}

function tokens(css, selector) {
  const ramp = declarations(css, ":root {");
  const block = declarations(css, selector);
  const resolve = (value) => {
    const reference = /^var\(\s*(--[a-z0-9-]+)\s*\)$/.exec(value);
    return reference ? ramp[reference[1]] : value;
  };
  return Object.fromEntries(
    Object.entries(block)
      .map(([name, value]) => [name, resolve(value)])
      .filter(([, value]) => /^#[0-9a-fA-F]{3,8}$/.test(value ?? "")),
  );
}

test("the theme is decided by the tokens, not by a second layer of rules", () => {
  // This assertion used to run the other way: it required a set of
  // `html[data-theme="dark"]` component overrides to exist, because the light
  // values they were undoing were written as literals that no token could
  // reach. Every base rule in this file now reads a `--ui-*` or `--cm-*`
  // custom property, and those switch on their own — so an override is no
  // longer a fix, it is a second opinion at a specificity no component rule
  // can answer. Twenty-eight of them were removed; three of the twenty-eight
  // had been styling a class (`.formatting`) that left the markup revisions
  // earlier, and one painted a key cap in the text colour and left its legend
  // on it at 1.3:1.
  for (const [name, css] of [["styles.css", styles], ["workspace.css", workspaceStyles]]) {
    const overrides = [...css.matchAll(/html\[data-theme="dark"\][^{,]*[,{]/g)]
      .map((match) => match[0].trim())
      .filter((selector) => !/^html\[data-theme="dark"\]\s*\{$/.test(selector));
    assert.deepEqual(
      overrides,
      [],
      `${name}: only the token block may be scoped to a theme`,
    );
  }
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
  assert.match(workspaceStyles, /:is\(\.preview-document, \.reading-document\) \.heading-anchor \{[\s\S]*?opacity: 0;/);
  assert.match(workspaceStyles, /:is\(\.preview-document, \.reading-document\) :is\(h1, h2, h3, h4, h5, h6\):hover \.heading-anchor/);
});


test("export reserves its destination row and keeps stronger chrome affordances", () => {
  assert.match(workspaceStyles, /#export-view\.active \{[\s\S]*?grid-template-rows: auto minmax\(0, 1fr\) auto;/);
  assert.match(workspaceStyles, /\.export-content \{[\s\S]*?overflow: auto;/);
  assert.match(workspaceStyles, /\.export-dock \{[\s\S]*?display: grid;/);
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
  // These surfaces used to be lifted by an `html[data-theme="light"]` rule
  // that restated a colour at a specificity no component rule could reach,
  // which is how the title bar kept reverting after the palette moved under
  // it. Elevation is the one thing that genuinely differs by theme, and it
  // lives on --ui-shadow, which switches with the theme on its own.
  assert.match(workspaceStyles, /\.panel,\n\.template-section,/);
  assert.doesNotMatch(
    workspaceStyles,
    /html\[data-theme="light"\][^{]*\{[^}]*(?:#fff|#ffffff)/i,
    "a theme-scoped rule is hard-coding a colour the tokens already switch",
  );
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

test("type is a scale of tokens, not two hundred literals", () => {
  // Surfaces, borders, accents, spacing, radii, control heights and pane
  // widths were all tokens; type was 207 literals in nineteen sizes, four of
  // them half a pixel off any other and three of them 8px, which is under any
  // size a badge can be read at.
  const sheets = [styles, workspaceStyles].join("\n");
  for (const token of [
    "--ui-text-3xs", "--ui-text-2xs", "--ui-text-xs", "--ui-text-sm",
    "--ui-text-md", "--ui-text-base", "--ui-text-lg", "--ui-text-xl",
    "--ui-text-2xl", "--ui-text-3xl",
  ]) {
    assert.match(workspaceStyles, new RegExp(`${token}:\\s*\\d+px`), `${token} is declared`);
    assert.ok(sheets.includes(`var(${token})`), `${token} is used`);
  }
  // Nothing sets a size outside the scale.
  const literals = [...sheets.matchAll(/font(?:-size)?:\s*(?:[\w-]+\s+)*?([0-9.]+)px/g)]
    .map((match) => match[1]);
  assert.deepEqual(literals, [], `font sizes are still written as literals: ${literals}`);
});

test("nothing in the editor puts vertical space outside the box that is measured", () => {
  // CodeMirror builds the height map from the boxes it measures, and a margin
  // is outside the box. A table with `margin-block: 0.9em` was 27px the map
  // never learned about; by the line below it the map ran 45px short of what
  // had been painted, and a click there resolved to the wrong line. The rule
  // is stated twice in this stylesheet for lines and had never been applied to
  // the widgets. Horizontal margins are fine — they change no height.
  const offenders = [];
  for (const [, selector, body] of workspaceStyles.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
    if (!/codemirror-mount|\.cm-/.test(selector)) continue;
    for (const [, property, value] of body.matchAll(/(margin(?:-block[\w-]*|-top|-bottom)?)\s*:\s*([^;]+)/g)) {
      if (property === "margin-inline" || property.startsWith("margin-inline")) continue;
      // A `margin` shorthand of zero moves nothing.
      if (/^\s*0(px|em|rem)?\s*$/.test(value)) continue;
      if (property === "margin" && /^\s*0\s+[^\s]+\s*$/.test(value)) continue;
      offenders.push(`${selector.trim().split("\n").pop().trim()} { ${property}: ${value.trim()} }`);
    }
  }
  assert.deepEqual(offenders, [], `vertical margins inside the editor: ${offenders.join(" | ")}`);
});
