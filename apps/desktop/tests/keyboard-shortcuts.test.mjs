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

test("native Windows virtual keys cover missing code without overriding explicit codes", () => {
  // Observed through real Windows input with a Persian keyboard layout.
  const native = { key: "س", code: "", keyCode: 83, ctrlKey: true,
    shiftKey: false, altKey: false, metaKey: false, isComposing: false };
  assert.equal(authoringShortcutKey(native), "s");
  assert.equal(authoringShortcutKey({ ...native, code: "KeyP" }), "p");
  assert.equal(authoringShortcutKey({ ...native, code: "UnknownCode" }), "س");
  assert.equal(authoringShortcutKey({ ...native, key: "p" }), "p");
  const palette = { ...native, key: "\\", keyCode: 80, shiftKey: true };
  assert.equal(authoringShortcutKey(palette), "p");
  assert.equal(authoringShortcutKey({ ...palette, code: "KeyP" }), "p");
  assert.equal(authoringShortcutKey({ ...palette, code: "Backslash" }), "\\");
  assert.equal(authoringShortcutKey({ ...palette, keyCode: 220 }), "\\");
  assert.equal(authoringShortcutKey({ ...palette, key: "+", keyCode: 187 }), "+");
  for (const keyCode of [0, 64, 91, 229, 999, 83.5, "83"]) {
    assert.equal(authoringShortcutKey({ ...native, keyCode }), keyCode === 229 ? null : "س");
  }
  for (const [keyCode, expected] of [[48, "0"], [189, "-"], [187, "="], [220, "\\"]]) {
    assert.equal(authoringShortcutKey({ ...native, key: "۰", keyCode }), expected);
  }
  assert.equal(authoringShortcutKey({ ...native, isComposing: true }), null);
  assert.equal(authoringShortcutKey({ ...native, altKey: true }), null);
  assert.equal(authoringShortcutKey({ ...native, getModifierState: () => true }), null);
});

test("typing, AltGraph and IME composition cannot invoke app commands", () => {
  for (const extra of [
    { ctrlKey: false }, { altKey: true }, { isComposing: true }, { keyCode: 229 },
    { getModifierState: (name) => name === "AltGraph" },
    { key: "Dead" }, { key: "Process" }, { key: "Unidentified" },
  ]) assert.equal(authoringShortcutKey({ key: "س", code: "KeyS", ctrlKey: true, ...extra }), null);
});
