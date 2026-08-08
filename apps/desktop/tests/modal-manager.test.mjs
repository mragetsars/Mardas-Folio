import test from "node:test";
import assert from "node:assert/strict";
import { createModalManager } from "../frontend/js/core/modal-manager.mjs";

class ClassList {
  constructor(...values) { this.values = new Set(values); }
  add(value) { this.values.add(value); }
  remove(value) { this.values.delete(value); }
  contains(value) { return this.values.has(value); }
}
class Element {
  constructor(name, focusables = []) {
    this.name = name;
    this.classList = new ClassList("hidden");
    this.attributes = new Map();
    this.focusables = focusables;
    this.hidden = false;
    this.inert = false;
  }
  querySelectorAll() { return this.focusables; }
  querySelector() { return null; }
  closest(selector) { return selector === ".hidden" && this.classList.contains("hidden") ? this : null; }
  focus() { this.document.activeElement = this; }
  setAttribute(key, value) { this.attributes.set(key, value); }
  removeAttribute(key) { this.attributes.delete(key); }
  hasAttribute(key) { return this.attributes.has(key); }
  dispatchEvent() {}
}
class Document {
  constructor() {
    this.listeners = new Map();
    this.shell = new Element("shell");
    this.activeElement = null;
  }
  querySelector(selector) { return selector === ".shell" ? this.shell : null; }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  removeEventListener(name) { this.listeners.delete(name); }
}

test("modal manager makes background inert and restores focus", async () => {
  globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
  const documentRef = new Document();
  const opener = new Element("opener");
  opener.document = documentRef;
  const first = new Element("first");
  const second = new Element("second");
  first.document = second.document = documentRef;
  first.closest = second.closest = () => null;
  const modal = new Element("modal", [first, second]);
  modal.document = documentRef;
  documentRef.activeElement = opener;
  const manager = createModalManager(documentRef);
  manager.open(modal);
  await new Promise((resolve) => queueMicrotask(resolve));
  assert.equal(documentRef.shell.inert, true);
  assert.equal(documentRef.activeElement, first);
  manager.close(modal);
  await new Promise((resolve) => queueMicrotask(resolve));
  assert.equal(documentRef.shell.inert, false);
  assert.equal(documentRef.activeElement, opener);
  manager.destroy();
  delete globalThis.CustomEvent;
});

test("Escape uses the modal close callback for control-specific ARIA cleanup", async () => {
  globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
  const documentRef = new Document();
  const modal = new Element("modal");
  modal.document = documentRef;
  const reasons = [];
  const manager = createModalManager(documentRef);
  manager.open(modal, { onClose: (reason) => reasons.push(reason) });
  await new Promise((resolve) => queueMicrotask(resolve));

  let prevented = false;
  documentRef.listeners.get("keydown")({
    key: "Escape",
    preventDefault: () => { prevented = true; },
  });
  assert.equal(prevented, true);
  assert.deepEqual(reasons, ["escape"]);
  assert.equal(manager.hasOpenModal(), false);
  manager.destroy();
  delete globalThis.CustomEvent;
});
