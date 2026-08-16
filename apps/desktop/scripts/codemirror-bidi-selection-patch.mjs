/**
 * A build-time correction to CodeMirror's selection drawing on bidirectional
 * lines.
 *
 * ## What is wrong
 *
 * `drawSelection` builds one rectangle per bidi run.  For each run it asks
 * `coordsAtPos` for the run's two ends, and it decides which *side* of an
 * offset to measure by comparing that offset against the visual line's bounds:
 * a position sitting at the end of the visual line is measured from the text
 * before it, anything else from the text after it.  Those bounds come from
 * `wrappedLine`, which finds them by hit-testing the editor's far left and far
 * right edges with `posAtCoords`.
 *
 * On a line that is entirely one direction the outermost pixels do belong to
 * the line's first and last characters, so the hit test is right.  On a line
 * whose direction changes, they do not: the leftmost glyph of `value = مقدار`
 * is the start of the Latin run, but the *rightmost* glyph is the start of the
 * Persian one, not the end of the line.  `wrappedLine` therefore reported the
 * line as ending at the run boundary.  `addSpan` then measured the Persian
 * run's start from the wrong side, both of its edges resolved to the same x,
 * and the run was drawn as a rectangle of zero width.
 *
 * The visible result: selecting a line that changes direction once highlighted
 * only the first run.  Measured in Chromium on `- [x] یک کار انجام‌شده`, the
 * drawn highlight covered 34px of 135px of text — a quarter of what was
 * actually selected.  The selection itself was always correct; only the
 * painting of it was wrong.  This is the common shape for the documents this
 * application exists to write: a Persian sentence closing with an English
 * term, or an English one closing with a Persian term.
 *
 * ## What this does instead
 *
 * A wrapped row is found by *vertical* position.  Bidi reordering moves text
 * horizontally and never moves it between rows, so asking which offsets share
 * a row with `pos` is a question reordering cannot corrupt.  Row membership is
 * monotonic in the offset, so each end is a binary search, and the check for
 * the whole line short-circuits it on the lines that do not wrap at all.
 *
 * That is also cheaper than what it replaces: two `posAtCoords` hit tests, each
 * of which searches the document, become two `coordsAtPos` lookups on the
 * common path.  Measured over 400 calls on a 120k-character document, one
 * whole-line selection went from 0.393ms to 0.193ms.
 *
 * ## Why it is patched here
 *
 * The defect is upstream, in a function CodeMirror does not export, reached
 * through a code path no extension can displace — the editor would have to
 * fork `drawSelection` wholesale to route around it.  Rewriting the one
 * function as the bundle is built keeps the correction to its actual size.
 * `@codemirror/view` is pinned to an exact version and the replacement asserts
 * the text it is replacing, so an upgrade that touches this function fails the
 * build rather than silently dropping the fix.  Reported upstream; remove this
 * once a release carries the fix.
 */
import { readFile } from "node:fs/promises";

/** The upstream function, verbatim from @codemirror/view 6.43.8. */
const ORIGINAL = `function wrappedLine(view, pos, side, inside) {
    let coords = view.coordsAtPos(pos, side * 2);
    if (!coords)
        return inside;
    let editorRect = view.dom.getBoundingClientRect();
    let y = (coords.top + coords.bottom) / 2;
    let left = view.posAtCoords({ x: editorRect.left + 1, y });
    let right = view.posAtCoords({ x: editorRect.right - 1, y });
    if (left == null || right == null)
        return inside;
    return { from: Math.max(inside.from, Math.min(left, right)), to: Math.min(inside.to, Math.max(left, right)) };
}`;

/**
 * The same contract — the logical bounds of the visual row holding `pos`,
 * clipped to `inside` — decided vertically rather than by hit-testing the
 * editor's horizontal extremes.
 */
const REPLACEMENT = `function wrappedLine(view, pos, side, inside) {
    let coords = view.coordsAtPos(pos, side * 2);
    if (!coords)
        return inside;
    // Vertical overlap, not a horizontal hit test: on a line whose direction
    // changes, the outermost pixels belong to an interior run rather than to
    // the line's ends. Reordering never moves text between rows.
    let onRow = (at) => {
        let c = view.coordsAtPos(at, at == inside.to ? -1 : 1);
        return c ? c.bottom > coords.top && c.top < coords.bottom : false;
    };
    let from = inside.from, to = inside.to;
    // Row membership only ever turns on once as the offset grows, so each edge
    // is a binary search; a line that does not wrap answers both immediately.
    if (!onRow(from)) {
        let lo = from, hi = pos;
        while (lo < hi) {
            let mid = (lo + hi) >> 1;
            if (onRow(mid)) hi = mid; else lo = mid + 1;
        }
        from = lo;
    }
    if (!onRow(to)) {
        let lo = pos, hi = to;
        while (lo < hi) {
            let mid = (lo + hi + 1) >> 1;
            if (onRow(mid)) lo = mid; else hi = mid - 1;
        }
        to = lo;
    }
    return { from: Math.max(inside.from, from), to: Math.min(inside.to, to) };
}`;

const VIEW_MODULE = /@codemirror[/\\]view[/\\]dist[/\\]index\.js$/;

/**
 * Apply the rewrite to a copy of the upstream source.
 *
 * Exported so the test suite can prove the patch still matches the installed
 * dependency; minification renames the locals, so the built bundle cannot be
 * searched for the replacement text itself.
 */
export function applyPatch(source) {
  if (!source.includes(ORIGINAL)) return null;
  return source.replace(ORIGINAL, REPLACEMENT);
}

/** An esbuild plugin that rewrites `wrappedLine` as the bundle is built. */
export function codeMirrorBidiSelectionPatch() {
  let applied = false;
  return {
    name: "codemirror-bidi-selection",
    setup(build) {
      build.onLoad({ filter: VIEW_MODULE }, async (args) => {
        const patched = applyPatch(await readFile(args.path, "utf8"));
        if (patched === null) {
          throw new Error(
            "The bidi selection patch no longer matches @codemirror/view. Check whether " +
              "the upstream fix has landed; if it has, delete this patch, and otherwise " +
              "re-derive it against the new source.",
          );
        }
        applied = true;
        return { contents: patched, loader: "js" };
      });
      build.onEnd(() => {
        if (!applied) {
          throw new Error(
            "The bidi selection patch never ran; @codemirror/view was not loaded from " +
              "its expected path.",
          );
        }
      });
    },
  };
}
