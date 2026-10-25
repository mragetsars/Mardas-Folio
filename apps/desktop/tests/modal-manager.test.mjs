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
    this.scrollTop = 0;
    this.child = null;
    this.scrolledIntoView = false;
    this.focusedWithScroll = null;
  }
  querySelectorAll() { return this.focusables; }
  querySelector(selector) { return selector === ".modal-card" ? this.child : null; }
  closest(selector) { return selector === ".hidden" && this.classList.contains("hidden") ? this : null; }
  focus(options) {
    this.focusedWithScroll = !options?.preventScroll;
    this.document.activeElement = this;
    // A real browser reveals the focused control by scrolling its scrollable
    // ancestors, which is the behaviour this manager has to hold back.
    if (this.focusedWithScroll && this.card) this.card.scrollTop = this.offsetTop || 0;
  }
  scrollIntoView() { this.scrolledIntoView = true; }
  getBoundingClientRect() {
    const top = (this.offsetTop || 0) - (this.card ? this.card.scrollTop : 0);
    return { top, bottom: top + 20 };
  }
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

test("an asynchronous dialog returns to its original action after intermediate confirmation", async () => {
  const documentRef = new Document();
  const opener = new Element("book-preview");
  const confirmation = new Element("confirmation-accept");
  const closeButton = new Element("close-review");
  opener.document = confirmation.document = closeButton.document = documentRef;
  closeButton.closest = () => null;
  const modal = new Element("book-review", [closeButton]);
  modal.document = documentRef;
  // Preparing the review included a save confirmation, so current focus no
  // longer identifies the action which owns the eventual review dialog.
  documentRef.activeElement = confirmation;
  const manager = createModalManager(documentRef);
  manager.open(modal, { returnFocus: opener });
  await new Promise((resolve) => queueMicrotask(resolve));
  assert.equal(documentRef.activeElement, closeButton);
  manager.close(modal);
  await new Promise((resolve) => queueMicrotask(resolve));
  assert.equal(documentRef.activeElement, opener);
  manager.destroy();
});

test("a dialog opens at its own beginning, not wherever focus lands", async () => {
  // The help dialog is taller than the window and its last control is a Close
  // button at the far end. Focusing that scrolled the card 273px down, past
  // the dialog's title and its first two sections, every time it was opened.
  globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
  const documentRef = new Document();
  const card = new Element("card");
  card.getBoundingClientRect = () => ({ top: 0, bottom: 400 });
  const heading = new Element("close-button");
  const far = new Element("done-button");
  heading.document = far.document = documentRef;
  heading.closest = far.closest = () => null;
  heading.card = far.card = card;
  heading.offsetTop = 8;
  far.offsetTop = 900;
  const modal = new Element("modal", [heading, far]);
  modal.document = documentRef;
  modal.child = card;

  const manager = createModalManager(documentRef);
  manager.open(modal);
  await new Promise((resolve) => queueMicrotask(resolve));

  assert.equal(documentRef.activeElement, heading, "the first control takes focus");
  assert.equal(card.scrollTop, 0, "the card is at the top of its content");
  assert.equal(heading.focusedWithScroll, false, "focus must not scroll the card");
  assert.equal(heading.scrolledIntoView, false, "a control already in view is left alone");
  manager.close(modal);
  manager.destroy();
  delete globalThis.CustomEvent;
});

test("a control genuinely out of view is still brought into it", async () => {
  globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
  const documentRef = new Document();
  const card = new Element("card");
  card.getBoundingClientRect = () => ({ top: 0, bottom: 400 });
  const far = new Element("far-control");
  far.document = documentRef;
  far.closest = () => null;
  far.card = card;
  far.offsetTop = 900;
  const modal = new Element("modal", [far]);
  modal.document = documentRef;
  modal.child = card;

  const manager = createModalManager(documentRef);
  manager.open(modal);
  await new Promise((resolve) => queueMicrotask(resolve));

  assert.equal(documentRef.activeElement, far);
  assert.equal(far.scrolledIntoView, true, "focus stays visible when it has to be far down");
  manager.close(modal);
  manager.destroy();
  delete globalThis.CustomEvent;
});
