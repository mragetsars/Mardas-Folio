import test from "node:test";
import assert from "node:assert/strict";

import { ImageWidget } from "../editor-src/live-widgets.mjs";

/**
 * Enough of a document to build one widget and read it back.
 *
 * `toDOM` is where the missing-image message is written, and the message is
 * only written from an `error` handler — which no headless parse of the source
 * would ever reach. The shim keeps the handler so the test can fire it.
 */
function fakeDocument() {
  const handlers = new Map();
  const make = (tag) => {
    const node = {
      tag,
      children: [],
      attributes: {},
      textContent: "",
      className: "",
      append: (...items) => node.children.push(...items),
      replaceChildren: (...items) => { node.children = items; },
      addEventListener: (type, callback) => handlers.set(`${tag}:${type}`, callback),
      querySelector: (selector) => {
        const wanted = selector.replace(".", "");
        const walk = (current) => {
          for (const child of current.children) {
            if (child.tag === wanted || child.className === wanted) return child;
            const found = walk(child);
            if (found) return found;
          }
          return null;
        };
        return walk(node);
      },
    };
    return node;
  };
  return { createElement: make, handlers };
}

function renderMissing(widget) {
  const shim = fakeDocument();
  const previous = globalThis.document;
  globalThis.document = { createElement: shim.createElement };
  try {
    const figure = widget.toDOM();
    shim.handlers.get("img:error")();
    return figure.children[0];
  } finally {
    globalThis.document = previous;
  }
}

test("an image that will not load names the file that is missing", () => {
  // The browser's broken-image glyph says nothing about which image or why,
  // and alt text describes the picture rather than the file to go and find.
  const missing = renderMissing(
    new ImageWidget("asset://gone.png", "A missing picture", "images/gone.png", "Image not found"),
  );
  assert.equal(missing.className, "cm-md-image-missing");
  const [label, path, alt] = missing.children;
  assert.equal(label.textContent, "Image not found");
  assert.equal(path.tag, "code");
  assert.equal(path.textContent, "images/gone.png");
  assert.equal(path.title, "images/gone.png", "the whole path is reachable when it is cut short");
  assert.equal(alt.textContent, "A missing picture");
});

test("the message is the application's to translate", () => {
  // The bundled editor has no dictionary of its own, so a Persian document
  // showed an English sentence over the gap where its image should have been.
  const missing = renderMissing(
    new ImageWidget("asset://gone.png", "", "images/gone.png", "تصویر پیدا نشد"),
  );
  assert.equal(missing.children[0].textContent, "تصویر پیدا نشد");
});

test("an image with no path at all still says what happened", () => {
  const missing = renderMissing(new ImageWidget("asset://x.png", "", "", "Image not found"));
  assert.equal(missing.children.length, 1);
  assert.equal(missing.children[0].textContent, "Image not found");
});

test("two widgets differ when their path or their message does", () => {
  // `eq` decides whether CodeMirror reuses the DOM it already drew; leaving
  // the new fields out of it would keep an English label after the language
  // changed, and a stale path after the document was edited.
  const base = new ImageWidget("u", "a", "images/one.png", "Image not found");
  assert.ok(base.eq(new ImageWidget("u", "a", "images/one.png", "Image not found")));
  assert.ok(!base.eq(new ImageWidget("u", "a", "images/two.png", "Image not found")));
  assert.ok(!base.eq(new ImageWidget("u", "a", "images/one.png", "تصویر پیدا نشد")));
});
