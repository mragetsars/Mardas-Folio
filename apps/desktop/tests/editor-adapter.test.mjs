import test from "node:test";
import assert from "node:assert/strict";
import { createEditorAdapter } from "../frontend/js/core/editor-adapter.mjs";

class FakeTextArea {
  constructor() {
    this.value = "";
    this.selectionStart = 0;
    this.selectionEnd = 0;
    this.scrollTop = 0;
    this.disabled = false;
    this.listeners = new Map();
    this.focused = false;
  }
  addEventListener(name, callback) {
    const callbacks = this.listeners.get(name) || [];
    callbacks.push(callback);
    this.listeners.set(name, callbacks);
  }
  removeEventListener(name, callback) {
    this.listeners.set(name, (this.listeners.get(name) || []).filter((item) => item !== callback));
  }
  dispatch(name) {
    for (const callback of this.listeners.get(name) || []) callback({ target: this });
  }
  focus() { this.focused = true; }
  setSelectionRange(start, end) {
    this.selectionStart = start;
    this.selectionEnd = end;
  }
}

test("editor adapter preserves a stable document boundary", () => {
  globalThis.HTMLTextAreaElement = FakeTextArea;
  globalThis.getComputedStyle = () => ({ lineHeight: "20" });
  const element = new FakeTextArea();
  let changes = 0;
  let selections = 0;
  let lastScroll = null;
  const editor = createEditorAdapter(element, {
    onChange: () => { changes += 1; },
    onSelectionChange: () => { selections += 1; },
    onScroll: (value) => { lastScroll = value; },
  });

  editor.value = "first\nsecond\nthird";
  const position = editor.goToLine(2, 3);
  assert.equal(position.line, 2);
  assert.equal(editor.selectionStart, 8);
  assert.deepEqual(editor.lineAtOffset(), { line: 2, column: 3 });

  editor.replaceRange(6, 12, "SECOND");
  assert.equal(editor.value, "first\nSECOND\nthird");
  assert.equal(changes, 1);

  element.dispatch("select");
  element.scrollTop = 42;
  element.dispatch("scroll");
  assert.equal(selections, 1);
  assert.equal(lastScroll, 42);

  editor.disabled = true;
  assert.equal(element.disabled, true);
  editor.destroy();
  delete globalThis.HTMLTextAreaElement;
  delete globalThis.getComputedStyle;
});
