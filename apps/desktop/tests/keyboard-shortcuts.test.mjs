import test from "node:test";
import assert from "node:assert/strict";
import { authoringShortcutKey } from "../frontend/js/core/keyboard-shortcuts.mjs";

test("app shortcuts work with Persian, Arabic and Cyrillic input layouts", () => {
  for (const [key, code, expected] of [
    ["س", "KeyS", "s"], ["ح", "KeyP", "p"], ["آ", "KeyN", "n"],
    ["ش", "KeyS", "s"], ["ы", "KeyS", "s"], ["ش", "KeyA", "a"],
    ["۰", "Digit0", "0"], ["−", "Minus", "-"], ["ریال", "KeyR", "ریال"],
  ]) assert.equal(authoringShortcutKey({ key, code, ctrlKey: true }), expected);
  assert.equal(authoringShortcutKey({ key: "س", code: "KeyS", metaKey: true }), "s");
});

test("Latin shortcuts retain logical letters and shifted command intent", () => {
  assert.equal(authoringShortcutKey({ key: "z", code: "KeyY", ctrlKey: true }), "z");
  assert.equal(authoringShortcutKey({ key: "a", code: "KeyQ", ctrlKey: true }), "a");
  assert.equal(authoringShortcutKey({ key: "P", code: "KeyP", metaKey: true, shiftKey: true }), "p");
  assert.equal(authoringShortcutKey({ key: "+", code: "Equal", ctrlKey: true, shiftKey: true }), "+");
  assert.equal(authoringShortcutKey({ key: "\\", code: "Backslash", ctrlKey: true }), "\\");
});

test("typing, AltGraph and IME composition cannot invoke app commands", () => {
  for (const extra of [
    { ctrlKey: false }, { altKey: true }, { isComposing: true }, { keyCode: 229 },
    { getModifierState: (name) => name === "AltGraph" },
    { key: "Dead" }, { key: "Process" }, { key: "Unidentified" },
  ]) assert.equal(authoringShortcutKey({ key: "س", code: "KeyS", ctrlKey: true, ...extra }), null);
});
