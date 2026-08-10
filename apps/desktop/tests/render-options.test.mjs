import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  OPTION_FIELDS,
  OPTION_GROUPS,
  collectRenderOptions,
  optionKeys,
} from "../frontend/js/core/render-options.mjs";

const engine = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/render_options.json", import.meta.url), "utf8"),
).options;

test("the settings panel exposes every option the engine accepts", () => {
  // The point of the panel is that nothing is CLI-only. If the engine gains an
  // option, this fails until it is given a control.
  const missing = Object.keys(engine).filter((key) => !(key in OPTION_FIELDS)).sort();
  assert.deepEqual(missing, [], "these engine options have no control in the interface");
});

test("the panel never sends an option the engine would reject", () => {
  const unknown = optionKeys().filter((key) => !(key in engine));
  assert.deepEqual(unknown, [], "these controls map to options the engine does not accept");
});

test("every select offers exactly the values the engine validates", () => {
  for (const [key, field] of Object.entries(OPTION_FIELDS)) {
    const allowed = engine[key]?.choices ?? [];
    if (field.kind !== "select" || !allowed.length) continue;
    assert.deepEqual(
      [...field.choices].sort(),
      [...allowed].sort(),
      `choices for ${key} have drifted from the engine`,
    );
  }
});

test("untouched controls are omitted so project configuration survives", () => {
  // An empty control means "inherit", not "override with empty"; otherwise
  // opening the panel would wipe whatever mardas.toml had configured.
  assert.deepEqual(collectRenderOptions({}), {});
  assert.deepEqual(collectRenderOptions({ title: "" }), {});
  assert.deepEqual(collectRenderOptions({ title: "   " }), {});
  assert.deepEqual(collectRenderOptions({ margin_top: "" }), {});
});

test("negated engine options are shown positively and flipped on the way out", () => {
  // The engine says `no_mathjax`; the user decides "render maths".
  assert.deepEqual(collectRenderOptions({ no_mathjax: true }), { no_mathjax: false });
  assert.deepEqual(collectRenderOptions({ no_mathjax: false }), { no_mathjax: true });
  assert.deepEqual(collectRenderOptions({ no_header_footer: true }), { no_header_footer: false });
  // A plain boolean passes through unchanged.
  assert.deepEqual(collectRenderOptions({ toc: true }), { toc: true });
});

test("numbers and lists are converted to the shapes the engine expects", () => {
  assert.deepEqual(collectRenderOptions({ toc_depth: "3" }), { toc_depth: 3 });
  assert.deepEqual(collectRenderOptions({ watermark_opacity: "0.15" }), { watermark_opacity: 0.15 });
  assert.deepEqual(collectRenderOptions({ toc_depth: "abc" }), {});
  assert.deepEqual(
    collectRenderOptions({ required_fonts: "Vazirmatn, Cascadia Mono ,, " }),
    { required_fonts: ["Vazirmatn", "Cascadia Mono"] },
  );
  assert.deepEqual(collectRenderOptions({ required_fonts: " , " }), {});
});

test("every field sits in exactly one group and has a label key", () => {
  const seen = new Set();
  for (const group of OPTION_GROUPS) {
    assert.ok(group.labelKey, `group ${group.id} needs a label`);
    for (const field of group.fields) {
      assert.ok(!seen.has(field.key), `${field.key} appears in more than one group`);
      seen.add(field.key);
      assert.ok(
        ["select", "toggle", "text", "number", "length", "list", "path"].includes(field.kind),
        `${field.key} has an unknown control kind ${field.kind}`,
      );
    }
  }
  assert.equal(seen.size, Object.keys(engine).length);
});

test("the export preview is painted with the engine's own stylesheets", () => {
  // A preview that shows generic Markdown cannot answer the question the export
  // screen exists to answer, so the engine returns the same style sheet,
  // palette and body classes the PDF is built with.
  const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");
  assert.match(main, /appearance\.style_css/);
  assert.match(main, /appearance\.palette_css/);
  assert.match(main, /appearance\.body_classes/);
  // Those sheets style a whole printed page; a shadow root keeps them off the
  // application around the preview.
  assert.match(main, /attachShadow\(\{ mode: "open" \}\)/);
});

test("speculative preview work yields to a job the user asked for", () => {
  // The engine runs one job at a time and answers a second with SERVER_BUSY.
  const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");
  assert.match(main, /async function releaseEngineForJob/);
  assert.match(main, /sidecar_cancel/);
  assert.match(main, /if \(state\.activeRequestId\) return;/);
});
