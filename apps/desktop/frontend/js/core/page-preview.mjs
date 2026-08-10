/**
 * Geometry and pagination for the export preview.
 *
 * The export screen exists to answer "what will the PDF look like", and a
 * scrolling column of HTML cannot answer it: it has no page, so it cannot show
 * a margin, a page break, a cover, or a page number. What it needs is paper —
 * a sheet of the configured size with the configured margins, filled with the
 * part of the document that lands on it.
 *
 * Everything here is arithmetic on numbers the browser measured, kept apart
 * from the DOM so the rule that decides where a page ends can be tested
 * directly. `page-deck.mjs` owns the drawing.
 */

/** CSS reference pixels per millimetre; the unit Chromium prints at. */
export const CSS_PX_PER_MM = 96 / 25.4;

/**
 * Zoom stops offered by the preview, as fractions of actual size.
 *
 * The range reaches down to a quarter because "fit whole page" has to work in
 * a side panel: an A4 sheet is 1122 CSS pixels tall, taller than most panels,
 * so a floor of 50% would silently refuse to fit the page it promised.
 */
export const ZOOM_STEPS = Object.freeze([0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3]);

export const MIN_ZOOM = ZOOM_STEPS[0];
export const MAX_ZOOM = ZOOM_STEPS[ZOOM_STEPS.length - 1];

function positiveNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}

function nonNegativeNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : fallback;
}

export function mmToPx(millimetres) {
  return positiveNumber(millimetres, 0) * CSS_PX_PER_MM;
}

/**
 * The sheet, in the two units the preview needs.
 *
 * The engine sends millimetres because that is what page sizes and margins are
 * written in; the browser lays out in CSS pixels. Converting once, here, keeps
 * the two from drifting apart in the drawing code.
 */
export function normalizePageGeometry(value = {}) {
  const widthMm = positiveNumber(value.width_mm, 210);
  const heightMm = positiveNumber(value.height_mm, 297);
  const marginTopMm = nonNegativeNumber(value.margin_top_mm, 18);
  const marginBottomMm = nonNegativeNumber(value.margin_bottom_mm, 20);
  const marginXMm = nonNegativeNumber(value.margin_x_mm, 16);
  // A margin box has to leave something to print in. The engine already
  // clamps this, but the preview divides by the content height and must never
  // be handed a zero by a payload from an older engine.
  const contentWidthMm = Math.max(
    positiveNumber(value.content_width_mm, widthMm - marginXMm * 2),
    10,
  );
  const contentHeightMm = Math.max(
    positiveNumber(value.content_height_mm, heightMm - marginTopMm - marginBottomMm),
    10,
  );
  return {
    widthMm,
    heightMm,
    marginTopMm,
    marginBottomMm,
    marginXMm,
    contentWidthMm,
    contentHeightMm,
    orientation: widthMm > heightMm ? "landscape" : "portrait",
    widthPx: mmToPx(widthMm),
    heightPx: mmToPx(heightMm),
    marginTopPx: mmToPx(marginTopMm),
    marginBottomPx: mmToPx(marginBottomMm),
    marginXPx: mmToPx(marginXMm),
    contentWidthPx: mmToPx(contentWidthMm),
    contentHeightPx: mmToPx(contentHeightMm),
  };
}

/** Clamp a zoom factor to the range the preview offers. */
export function clampZoom(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 1;
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, number));
}

/** The next zoom stop in a direction, so the buttons step predictably. */
export function stepZoom(current, direction) {
  const now = clampZoom(current);
  if (direction > 0) return clampZoom(ZOOM_STEPS.find((step) => step > now + 0.001) ?? MAX_ZOOM);
  const smaller = [...ZOOM_STEPS].reverse().find((step) => step < now - 0.001);
  return clampZoom(smaller ?? MIN_ZOOM);
}

/**
 * The zoom that makes one sheet fill the available width.
 *
 * This is the default because a preview that does not show a whole page across
 * is not showing a page.
 */
export function fitWidthZoom(availableWidthPx, pageWidthPx, gutterPx = 0) {
  const usable = Number(availableWidthPx) - Number(gutterPx || 0);
  const width = positiveNumber(pageWidthPx, 0);
  if (!width || !Number.isFinite(usable) || usable <= 0) return 1;
  return clampZoom(usable / width);
}

/** The zoom that makes one whole sheet visible at once. */
export function fitPageZoom(availableWidthPx, availableHeightPx, geometry, gutterPx = 0) {
  const byWidth = fitWidthZoom(availableWidthPx, geometry.widthPx, gutterPx);
  const usableHeight = Number(availableHeightPx) - Number(gutterPx || 0);
  if (!Number.isFinite(usableHeight) || usableHeight <= 0 || !geometry.heightPx) return byWidth;
  return clampZoom(Math.min(byWidth, usableHeight / geometry.heightPx));
}

/**
 * Where each page starts, as an offset into the measured content flow.
 *
 * `blocks` are the document's top-level boxes as the browser measured them,
 * each carrying the break rules its computed style asks for. Reading those
 * rules rather than guessing is what lets "start every H1 on a new page" and
 * "contents on its own page" show up in the preview without the preview
 * knowing those options exist.
 *
 * The rules applied, in the order a printer applies them:
 *
 *   - a block asking to break before it starts a page, and so does the block
 *     after one that asked to break after itself;
 *   - a block that will not fit on the rest of the page moves to the next one,
 *     if it asks not to be split and is small enough to fit on a page at all;
 *   - a block too tall for any page is split, page after page, rather than
 *     leaving the rest of the document unreachable;
 *   - a heading that would be left alone at the foot of a page goes with the
 *     block it introduces.
 *
 * `snap` is how a split lands between lines rather than through one. It is
 * given the offset a page would otherwise end at and returns the nearest line
 * boundary above it; the caller measures those, because only the browser knows
 * where a line of mixed Persian and English prose actually breaks.
 */
export function paginate(blocks, pageHeightPx, totalHeightPx, { snap } = {}) {
  const pageHeight = positiveNumber(pageHeightPx, 0);
  const total = Math.max(0, Number(totalHeightPx) || 0);
  if (!pageHeight) return [0];

  const items = (Array.isArray(blocks) ? blocks : []).map((block) => ({
    top: Math.max(0, Number(block?.top) || 0),
    height: Math.max(0, Number(block?.height) || 0),
    breakBefore: Boolean(block?.breakBefore),
    breakAfter: Boolean(block?.breakAfter),
    breakInside: Boolean(block?.breakInside),
    keepWithNext: Boolean(block?.keepWithNext),
  }));

  const starts = [0];
  let start = 0;

  /** End a page at the last line boundary that still fits, if one is known. */
  const fill = () => {
    const edge = start + pageHeight;
    if (typeof snap !== "function") return edge;
    const snapped = Number(snap(edge, start));
    return Number.isFinite(snapped) && snapped > start && snapped <= edge ? snapped : edge;
  };

  const breakAt = (offset) => {
    // A page must always move forward, or a block taller than the sheet would
    // spin here forever.
    const next = Math.min(Math.max(offset, start + 1), Math.max(total, start + 1));
    if (next <= start) return false;
    starts.push(next);
    start = next;
    return true;
  };

  /** Pull a break back over headings that would otherwise be stranded. */
  const withKeptHeadings = (index, offset) => {
    let target = offset;
    for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
      const previous = items[cursor];
      if (!previous.keepWithNext) break;
      if (previous.top <= start) break;
      // Only worth moving if the heading is genuinely adjacent to the break.
      if (previous.top + previous.height < target - 1) break;
      target = previous.top;
    }
    return target;
  };

  let forceNext = false;
  for (let index = 0; index < items.length; index += 1) {
    const block = items[index];
    if ((forceNext || block.breakBefore) && block.top > start) breakAt(block.top);
    forceNext = false;

    const bottom = block.top + block.height;
    if (bottom > start + pageHeight) {
      const unsplittable = block.breakInside && block.height <= pageHeight;
      if (unsplittable && block.top > start) {
        breakAt(withKeptHeadings(index, block.top));
      } else {
        let guard = 0;
        while (bottom > start + pageHeight && guard < 10_000) {
          guard += 1;
          if (!breakAt(fill())) break;
        }
      }
    }
    if (block.breakAfter) forceNext = true;
  }

  let guard = 0;
  while (total > start + pageHeight && guard < 10_000) {
    guard += 1;
    if (!breakAt(fill())) break;
  }
  return starts;
}

/**
 * How far above a page edge a line boundary may be and still be used.
 *
 * Beyond this the "line" is really the far side of a gap — a margin above a
 * heading, a rule — and snapping to it would leave a visible band of empty
 * paper where the page should have been full.
 */
export const MAX_SNAP_DISTANCE_PX = 90;

/**
 * Build a `snap` function from measured line-box tops.
 *
 * `tops` need not be sorted or unique; it is the raw list of every line box the
 * browser laid out, which is the only honest source for where a paragraph of
 * mixed Persian and English can be cut.
 */
export function lineSnapper(tops, maxDistance = MAX_SNAP_DISTANCE_PX) {
  const sorted = (Array.isArray(tops) ? tops : [])
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => left - right);
  if (!sorted.length) return null;

  return (offset, start) => {
    // Greatest line top at or before the page edge.
    let low = 0;
    let high = sorted.length - 1;
    let found = -1;
    while (low <= high) {
      const middle = (low + high) >> 1;
      if (sorted[middle] <= offset) {
        found = middle;
        low = middle + 1;
      } else {
        high = middle - 1;
      }
    }
    if (found < 0) return offset;
    const candidate = sorted[found];
    if (candidate <= start) return offset;
    if (offset - candidate > maxDistance) return offset;
    return candidate;
  };
}

/** Which page indexes to materialise for a scroll position, plus one either side. */
export function visiblePageRange(scrollTop, viewportHeight, pitch, pageCount, overscan = 1) {
  const count = Math.max(0, Math.trunc(Number(pageCount) || 0));
  if (!count) return { first: 0, last: -1 };
  const step = positiveNumber(pitch, 0);
  if (!step) return { first: 0, last: count - 1 };
  const top = Math.max(0, Number(scrollTop) || 0);
  const height = Math.max(0, Number(viewportHeight) || 0);
  const first = Math.max(0, Math.floor(top / step) - overscan);
  const last = Math.min(count - 1, Math.ceil((top + height) / step) + overscan - 1);
  return { first, last: Math.max(first, last) };
}

/** Which page a scroll position is looking at, one-based, for the page counter. */
export function currentPageNumber(scrollTop, viewportHeight, pitch, pageCount) {
  const count = Math.max(1, Math.trunc(Number(pageCount) || 1));
  const step = positiveNumber(pitch, 0);
  if (!step) return 1;
  const centre = Math.max(0, Number(scrollTop) || 0) + Math.max(0, Number(viewportHeight) || 0) / 2;
  return Math.min(count, Math.max(1, Math.floor(centre / step) + 1));
}
