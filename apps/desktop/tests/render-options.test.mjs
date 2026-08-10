import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  OPTION_FIELDS,
  OPTION_GROUPS,
  collectRenderOptions,
  fieldIsActive,
  modifiedCountsByGroup,
  modifiedKeys,
  optionKeys,
  searchOptions,
  validateOptionValue,
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
  // screen exists to answer, so the deck mounts the same style sheet, palette,
  // page layout and body classes the PDF is built with.
  const deck = readFileSync(
    new URL("../frontend/js/preview/page-deck.mjs", import.meta.url),
    "utf8",
  );
  for (const key of ["style", "palette", "layout", "pygments", "fonts"]) {
    assert.match(deck, new RegExp(`css\\?\\.${key}`), `the deck must mount css.${key}`);
  }
  assert.match(deck, /body_classes/);
  // Those sheets style a whole printed page, so they are kept in a document of
  // their own rather than loosed on the application around the preview.
  assert.match(deck, /createElement\("iframe"\)/);
});

test("speculative preview work yields to a job the user asked for", () => {
  // The engine runs one job at a time and answers a second with SERVER_BUSY.
  const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");
  assert.match(main, /async function releaseEngineForJob/);
  assert.match(main, /sidecar_cancel/);
  assert.match(main, /if \(state\.activeRequestId\) return;/);
});

test("every option says what it decides, in one sentence", () => {
  // Fifty-three controls named after engine identifiers is a specification.
  // The help line is what turns it into something a person can decide.
  const missing = Object.values(OPTION_FIELDS)
    .filter((field) => !field.helpKey)
    .map((field) => field.key);
  assert.deepEqual(missing, [], "these options have no help text");
});

test("bad lengths and numbers are caught before the render is started", () => {
  assert.equal(validateOptionValue("margin_top", "18mm"), null);
  assert.equal(validateOptionValue("margin_top", "0.5in"), null);
  assert.equal(validateOptionValue("margin_top", ""), null);
  assert.equal(validateOptionValue("margin_top", "18"), "invalidLength");
  assert.equal(validateOptionValue("margin_top", "wide"), "invalidLength");
  // Only the watermark takes a percentage; a page margin in percent is not a
  // length the engine accepts.
  assert.equal(validateOptionValue("watermark_width", "60%"), null);
  assert.equal(validateOptionValue("margin_x", "60%"), "invalidLength");
  assert.equal(validateOptionValue("toc_depth", "3"), null);
  assert.equal(validateOptionValue("toc_depth", "9"), "outOfRange");
  assert.equal(validateOptionValue("toc_depth", "x"), "invalidNumber");
  assert.equal(validateOptionValue("not_an_option", "x"), null);
});

test("an option that depends on another is reported as inert, not wrong", () => {
  const depth = OPTION_FIELDS.toc_depth;
  assert.equal(fieldIsActive(depth, { toc: true }), true);
  assert.equal(fieldIsActive(depth, { toc: false }), false);
  // Falling back to the preset matters: the preset is what is in force when
  // the user has not touched the option themselves.
  assert.equal(fieldIsActive(depth, {}, { toc: true }), true);
  assert.equal(fieldIsActive(depth, {}, { toc: false }), false);
  assert.equal(fieldIsActive(OPTION_FIELDS.style, {}), true);
});

test("changes away from the preset are counted per category", () => {
  const preset = { style: "modern", toc: true, page_size: "A4" };
  assert.deepEqual(modifiedKeys({ style: "modern", toc: true }, preset), []);
  assert.deepEqual(modifiedKeys({ style: "academic" }, preset), ["style"]);
  // An option the preset says nothing about is a change by definition.
  assert.deepEqual(modifiedKeys({ watermark_text: "DRAFT" }, preset), ["watermark_text"]);
  const counts = modifiedCountsByGroup(
    { style: "academic", watermark_text: "DRAFT", watermark_opacity: 0.2 },
    preset,
  );
  assert.equal(counts.appearance, 1);
  assert.equal(counts.watermark, 2);
});

test("options are findable by engine name and by plain language", () => {
  const translate = (key) => (key === "opt.margin_x" ? "Side margins" : key);
  const byKey = searchOptions("margin_x", translate).map(({ field }) => field.key);
  assert.ok(byKey.includes("margin_x"));
  const byWords = searchOptions("side margins", translate).map(({ field }) => field.key);
  assert.deepEqual(byWords, ["margin_x"]);
  assert.equal(searchOptions("", translate), null);
  assert.deepEqual(searchOptions("zzzz", translate), []);
});

test("the group rail can name every group and every group has a description", () => {
  for (const group of OPTION_GROUPS) {
    assert.ok(group.id && group.labelKey && group.descriptionKey, `${group.id} is underspecified`);
    assert.ok(group.fields.length, `${group.id} has no fields`);
  }
  // Expert groups must only hold expert fields, or turning expert mode off
  // would hide an everyday option.
  for (const group of OPTION_GROUPS.filter((item) => item.expert)) {
    for (const field of group.fields) {
      assert.ok(field.expert, `${field.key} is hidden inside an expert group`);
    }
  }
});

test("a dependency always names a real option", () => {
  for (const field of Object.values(OPTION_FIELDS)) {
    if (!field.dependsOn) continue;
    assert.ok(field.dependsOn in OPTION_FIELDS, `${field.key} depends on an unknown option`);
  }
});
