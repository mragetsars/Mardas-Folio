import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  CSS_PX_PER_MM,
  clampZoom,
  currentPageNumber,
  fitPageZoom,
  fitWidthZoom,
  mmToPx,
  normalizePageGeometry,
  paginate,
  stepZoom,
  visiblePageRange,
} from "../frontend/js/core/page-preview.mjs";

const A4 = {
  width_mm: 210,
  height_mm: 297,
  margin_top_mm: 18,
  margin_bottom_mm: 20,
  margin_x_mm: 16,
  content_width_mm: 178,
  content_height_mm: 259,
};

test("the sheet arrives in both the units the preview needs", () => {
  const geometry = normalizePageGeometry(A4);
  assert.equal(geometry.widthMm, 210);
  assert.equal(geometry.orientation, "portrait");
  assert.equal(geometry.widthPx, mmToPx(210));
  assert.ok(Math.abs(geometry.contentHeightPx - 259 * CSS_PX_PER_MM) < 1e-9);
  assert.equal(normalizePageGeometry({ width_mm: 297, height_mm: 210 }).orientation, "landscape");
});

test("a payload without geometry still produces a usable page", () => {
  // An older engine, or a failed request, must not hand the preview a zero it
  // is about to divide the document by.
  const geometry = normalizePageGeometry();
  assert.equal(geometry.widthMm, 210);
  assert.ok(geometry.contentHeightPx > 0);

  const impossible = normalizePageGeometry({
    width_mm: 148,
    height_mm: 210,
    margin_x_mm: 200,
    content_width_mm: -50,
  });
  assert.ok(impossible.contentWidthPx > 0);
});

test("fit-width makes one sheet fill the panel", () => {
  const geometry = normalizePageGeometry(A4);
  const zoom = fitWidthZoom(500, geometry.widthPx, 40);
  assert.ok(Math.abs(zoom * geometry.widthPx - 460) < 1e-6);
  // A panel that has not been laid out yet must not collapse the preview.
  assert.equal(fitWidthZoom(0, geometry.widthPx), 1);
  assert.equal(fitWidthZoom(500, 0), 1);
});

test("fit-page never shows more than fit-width across", () => {
  const geometry = normalizePageGeometry(A4);
  const wide = fitPageZoom(2000, 300, geometry, 0);
  assert.ok(wide <= fitWidthZoom(2000, geometry.widthPx, 0) + 1e-9);
  assert.ok(wide * geometry.heightPx <= 300 + 1e-6);
});

test("zoom stays inside the offered range and steps predictably", () => {
  assert.equal(clampZoom(9), 3);
  assert.equal(clampZoom(0.01), 0.25);
  assert.equal(clampZoom("nonsense"), 1);
  assert.equal(stepZoom(1, 1), 1.25);
  assert.equal(stepZoom(1, -1), 0.75);
  assert.equal(stepZoom(3, 1), 3);
  assert.equal(stepZoom(0.25, -1), 0.25);
});

const block = (top, height, flags = {}) => ({ top, height, ...flags });

test("splittable content fills each page to the bottom", () => {
  // Plain paragraphs carry no break rules, so a printer runs them right to the
  // edge of the margin box and continues on the next page.
  const pages = paginate(
    [block(0, 100), block(100, 100), block(200, 100)],
    120,
    300,
  );
  assert.deepEqual(pages, [0, 120, 240]);
});

test("a block that will not fit moves to the next page rather than being cut", () => {
  // A table or a figure asks not to be split; a printer honours that by
  // starting it on the next page.
  const pages = paginate(
    [block(0, 80), block(80, 90, { breakInside: true }), block(170, 30)],
    120,
    200,
  );
  assert.deepEqual(pages, [0, 80]);
});

test("a block taller than the page is split instead of stranding the document", () => {
  const pages = paginate([block(0, 500, { breakInside: true })], 100, 500);
  assert.deepEqual(pages, [0, 100, 200, 300, 400]);
});

test("an explicit page break starts a page", () => {
  // This is how "start every H1 on a new page" reaches the preview: the engine
  // stylesheet says break-before, and the measured block reports it.
  const pages = paginate(
    [block(0, 40), block(40, 40, { breakBefore: true }), block(80, 40)],
    500,
    120,
  );
  assert.deepEqual(pages, [0, 40]);
});

test("a break-after rule pushes the following block to a new page", () => {
  // "Contents on its own page" is break-after on the table of contents.
  const pages = paginate(
    [block(0, 50, { breakAfter: true }), block(50, 50), block(100, 50)],
    400,
    150,
  );
  assert.deepEqual(pages, [0, 50]);
});

test("a heading is not left alone at the foot of a page", () => {
  // The heading ends exactly where the unsplittable block begins, and asks to
  // stay with it, so the break moves up to take the heading along.
  const pages = paginate(
    [
      block(0, 90),
      block(90, 20, { keepWithNext: true }),
      block(110, 60, { breakInside: true }),
    ],
    140,
    170,
  );
  assert.deepEqual(pages, [0, 90]);
});

test("pagination always terminates and always moves forward", () => {
  for (const pageHeight of [1, 7, 120]) {
    const pages = paginate(
      [block(0, 0, { breakBefore: true, breakAfter: true }), block(0, 1000)],
      pageHeight,
      1000,
    );
    for (let index = 1; index < pages.length; index += 1) {
      assert.ok(pages[index] > pages[index - 1], "page starts must increase");
    }
    assert.ok(pages.length < 10_001);
  }
  assert.deepEqual(paginate([], 0, 500), [0]);
  assert.deepEqual(paginate(null, 100, 0), [0]);
});

test("only the sheets near the viewport are materialised", () => {
  // A hundred-page document must not put a hundred copies of itself in the DOM.
  assert.deepEqual(visiblePageRange(0, 800, 300, 100), { first: 0, last: 3 });
  assert.deepEqual(visiblePageRange(3000, 800, 300, 100), { first: 9, last: 13 });
  const end = visiblePageRange(29_700, 800, 300, 100);
  assert.equal(end.last, 99);
  assert.deepEqual(visiblePageRange(0, 800, 300, 0), { first: 0, last: -1 });
});

test("the page counter follows the middle of the viewport", () => {
  assert.equal(currentPageNumber(0, 400, 300, 10), 1);
  assert.equal(currentPageNumber(300, 200, 300, 10), 2);
  assert.equal(currentPageNumber(100_000, 200, 300, 10), 10);
  assert.equal(currentPageNumber(0, 0, 0, 5), 1);
});

test("the deck renders inside a frame because engine CSS needs a real document", () => {
  // The engine declares its palette and type scale on `:root` and keys the
  // appearance, direction and break rules off `body.md2pdf-…`. Neither can
  // match inside a shadow tree, so a shadow-root preview loses exactly the
  // things the export screen exists to show.
  const deck = readFileSync(new URL("../frontend/js/preview/page-deck.mjs", import.meta.url), "utf8");
  assert.match(deck, /createElement\("iframe"\)/);
  assert.doesNotMatch(deck, /attachShadow/);
  // Break decisions come from the document's own computed style.
  assert.match(deck, /getComputedStyle/);
  assert.match(deck, /breakBefore/);
});

test("the export screen asks for the page, not just the body", () => {
  const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");
  assert.match(main, /previewDocumentPage/);
  const api = readFileSync(
    new URL("../frontend/js/core/authoring-api.mjs", import.meta.url),
    "utf8",
  );
  assert.match(api, /preview\.document_page/);
});

test("choosing a source file starts the preview", () => {
  // The document is the preview's only subject. Without this the panel stayed
  // on "choose a source file" until some unrelated option was touched.
  const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");
  const start = main.indexOf("function openExportSource");
  const end = main.indexOf("async function chooseExportSource", start);
  assert.match(main.slice(start, end), /schedulePdfPreview\(/);
});

test("the preview stands down gracefully on an engine that predates it", () => {
  // A desktop build carries a compiled engine, so a rebuilt interface on an
  // unrebuilt runtime is a normal state — and answering it with the raw string
  // "Unknown method: preview.document_page" in the panel is not.
  const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");
  assert.match(main, /async function engineCapabilities/);
  assert.match(main, /system\.capabilities/);
  assert.match(main, /function engineSupports/);
  assert.match(main, /engineSupports\("preview\.document_page"\)/);
  assert.match(main, /function pagePayloadFromBodyPreview/);
  // The fallback says what it is assuming rather than pretending to be exact.
  assert.match(main, /payload\?\.degraded/);
  assert.match(main, /previewEngineOutdated/);
});

test("an engine that cannot describe itself is not assumed to be broken", () => {
  const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");
  const start = main.indexOf("function engineSupports");
  assert.match(main.slice(start, start + 200), /!state\.engineMethods \|\| state\.engineMethods\.has/);
});
