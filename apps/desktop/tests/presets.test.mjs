import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createTranslator } from "../frontend/js/core/i18n.mjs";
import {
  PRESETS,
  SUPPORTED_EXPORT_MODES,
  SUPPORTED_EXPORT_PALETTES,
  SUPPORTED_EXPORT_STYLES,
  mergePresetOptions,
  presetById,
} from "../frontend/js/core/presets.mjs";

test("presets expose stable user choices", () => {
  assert.deepEqual(Object.keys(PRESETS), ["general", "academic", "technical", "minimal"]);
  assert.equal(PRESETS.academic.options.quality_profile, "strict-publication");
});

test("every preset uses renderer-supported appearance enums", () => {
  for (const preset of Object.values(PRESETS)) {
    assert.ok(SUPPORTED_EXPORT_STYLES.includes(preset.options.style), `${preset.id} style`);
    assert.ok(SUPPORTED_EXPORT_PALETTES.includes(preset.options.palette), `${preset.id} palette`);
    assert.ok(SUPPORTED_EXPORT_MODES.includes(preset.options.mode), `${preset.id} mode`);
  }
  assert.equal(PRESETS.academic.options.style, "academic");
  assert.equal(PRESETS.technical.options.palette, "emerald");
  assert.deepEqual(
    { style: PRESETS.minimal.options.style, palette: PRESETS.minimal.options.palette },
    { style: "modern", palette: "neutral" },
  );
});

test("Quick Export style choices mirror the renderer style enum", () => {
  const html = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
  const select = /<select id="appearance-style">([\s\S]*?)<\/select>/.exec(html)?.[1] ?? "";
  const values = [...select.matchAll(/<option value="([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(values, [...SUPPORTED_EXPORT_STYLES]);
});

test("Quick Export style choices have Persian and English labels", () => {
  for (const locale of ["fa", "en"]) {
    const translator = createTranslator(locale);
    for (const style of SUPPORTED_EXPORT_STYLES) {
      assert.notEqual(translator.t(style), style, `${locale} ${style}`);
    }
  }
});

test("fallback and override are safe", () => {
  assert.equal(presetById("x").id, "general");
  const options = mergePresetOptions("academic", { toc: false, page_size: "Letter" });
  assert.equal(options.quality_profile, "strict-publication");
  assert.equal(options.toc, false);
  assert.equal(options.page_size, "Letter");
});
