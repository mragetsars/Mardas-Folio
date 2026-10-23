import test from "node:test";
import assert from "node:assert/strict";
import { mathSource } from "../frontend/js/preview/math.mjs";

test("math wrappers unwrap without altering TeX commands or code-like dollars", () => {
  assert.equal(mathSource(String.raw`\(E = mc^2\)`), "E = mc^2");
  assert.equal(mathSource(String.raw`\\(\frac{a}{b}\\)`), String.raw`\frac{a}{b}`);
  assert.equal(mathSource("$$\n\\int_0^1 x^2\\,dx\n$$", true), String.raw`\int_0^1 x^2\,dx`);
  assert.equal(mathSource(String.raw`\[\sqrt{x}\]`, true), String.raw`\sqrt{x}`);
  assert.equal(mathSource("$x + y$"), "x + y");
  assert.equal(mathSource("cost $5 and $10"), "cost $5 and $10");
});
