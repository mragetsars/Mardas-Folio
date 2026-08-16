/**
 * Build-time corrections to CodeMirror on lines that change writing direction.
 *
 * ## The shared mistake
 *
 * Two places in `@codemirror/view` need the logical bounds of the visual row a
 * position sits on, and both find them the same way: hit-test the editor's far
 * left edge and its far right edge with `posAtCoords`, and take what comes
 * back as the row's two ends.
 *
 * On a line running one way throughout, the outermost pixels do belong to its
 * first and last characters, so the hit test is right. On a line whose
 * direction changes, they do not.  The rightmost glyph of `value = مقدار` is
 * the *start* of the Persian run, not the end of the line; the leftmost glyph
 * of `متن فارسی with English` is the start of the Latin run, not the end.  So
 * the row is reported as ending in the middle of the line, at a run boundary.
 *
 * Both call sites are reached only when line wrapping is on — which it always
 * is here, because prose has to wrap — and both then misbehave on lines that
 * do not wrap at all.
 *
 * ## What it broke
 *
 * `wrappedLine` feeds those bounds to `drawSelection`, which decides which
 * side of an offset to measure from by comparing it against them.  With the
 * row ending early, the run past the boundary had both its edges resolve to
 * the same x and was drawn as a rectangle of zero width: selecting
 * `- [x] یک کار انجام‌شده` painted 34px of the 135px it had selected.
 *
 * `moveToLineBoundary` is what the Home and End keys run through.  With the
 * row ending early, End stopped at the run boundary in the middle of the line:
 * on `متن فارسی with English inside it` it landed on offset 10 of 32.  That
 * one is not merely cosmetic — the caret really is in the wrong place, so what
 * is typed next goes there.  It is also self-inconsistent: the same line with
 * wrapping switched off takes the function's fallback path and lands correctly
 * on the line's end, which is what its own documentation promises.
 *
 * ## The correction
 *
 * A row is found by *vertical* position.  Reordering moves text sideways and
 * never between rows, so which offsets share a row with a position is a
 * question it cannot corrupt.  Row membership only turns on once as the offset
 * grows, so each end is a binary search, and a line that does not wrap answers
 * both immediately.
 *
 * That is also cheaper than what it replaces: two `posAtCoords` hit tests, each
 * of which searches the document, become two `coordsAtPos` lookups on the
 * common path.  Measured over 400 calls on a 120k-character document, one
 * whole-line selection went from 0.393ms to 0.193ms.
 *
 * ## Why it is patched here
 *
 * The defect is upstream, in functions `@codemirror/view` does not export and
 * that no extension can displace — the editor would have to fork both
 * `drawSelection` and the cursor commands to route around them.  Rewriting
 * them as the bundle is built keeps the correction to its actual size.
 * `@codemirror/view` is pinned to an exact version and every replacement
 * asserts the text it replaces, so an upgrade that touches either function
 * fails the build rather than silently dropping the fix.  Reported upstream;
 * remove this once a release carries it.
 */
import { readFile } from "node:fs/promises";

/**
 * The row search both call sites need, and the corrected `moveToLineBoundary`.
 *
 * The helper is declared here rather than in its own replacement because
 * function declarations hoist across the module, so `wrappedLine` — which
 * appears several thousand lines later — can call it too.
 */
const BOUNDARY_ORIGINAL = `function moveToLineBoundary(view, start, forward, includeWrap) {
    let line = blockAt(view, start.head, start.assoc || -1);
    let coords = !includeWrap || line.type != BlockType.Text || !(view.lineWrapping || line.widgetLineBreaks) ? null
        : view.coordsAtPos(start.assoc < 0 && start.head > line.from ? start.head - 1 : start.head);
    if (coords) {
        let editorRect = view.dom.getBoundingClientRect();
        let direction = view.textDirectionAt(line.from);
        let pos = view.posAtCoords({ x: forward == (direction == Direction.LTR) ? editorRect.right - 1 : editorRect.left + 1,
            y: (coords.top + coords.bottom) / 2 });
        if (pos != null)
            return EditorSelection.cursor(pos, forward ? -1 : 1);
    }
    return EditorSelection.cursor(forward ? line.to : line.from, forward ? -1 : 1);
}`;

const BOUNDARY_REPLACEMENT = `function visualRowBounds(view, pos, coords, from, to) {
    // Vertical position, not a horizontal hit test: on a line whose direction
    // changes, the outermost pixels belong to an interior run rather than to
    // the line's ends. Reordering never moves text between rows.
    //
    // Each edge is measured from the side that faces into the row, so a soft
    // wrap belongs to the row it ends as well as the one it begins. Rows run
    // top to bottom while offsets only ever move downward, so both tests flip
    // exactly once across the line and each edge is a binary search; a line
    // that does not wrap answers both without searching.
    let y = (coords.top + coords.bottom) / 2;
    let atOrBelow = (at) => {
        let c = view.coordsAtPos(at, 1);
        return c ? c.bottom > y : false;
    };
    let atOrAbove = (at) => {
        let c = view.coordsAtPos(at, -1);
        return c ? c.top < y : false;
    };
    let start = from, end = to;
    if (!atOrBelow(start)) {
        let lo = from, hi = pos;
        while (lo < hi) {
            let mid = (lo + hi) >> 1;
            if (atOrBelow(mid)) hi = mid; else lo = mid + 1;
        }
        start = lo;
    }
    if (!atOrAbove(end)) {
        let lo = pos, hi = to;
        while (lo < hi) {
            let mid = (lo + hi + 1) >> 1;
            if (atOrAbove(mid)) lo = mid; else hi = mid - 1;
        }
        end = lo;
    }
    return { from: start, to: end };
}
function moveToLineBoundary(view, start, forward, includeWrap) {
    let line = blockAt(view, start.head, start.assoc || -1);
    let coords = !includeWrap || line.type != BlockType.Text || !(view.lineWrapping || line.widgetLineBreaks) ? null
        : view.coordsAtPos(start.assoc < 0 && start.head > line.from ? start.head - 1 : start.head);
    if (coords) {
        let row = visualRowBounds(view, start.head, coords, line.from, line.to);
        return EditorSelection.cursor(forward ? row.to : row.from, forward ? -1 : 1);
    }
    return EditorSelection.cursor(forward ? line.to : line.from, forward ? -1 : 1);
}`;

/** The visual row that `drawSelection` measures a range against. */
const WRAPPED_ORIGINAL = `function wrappedLine(view, pos, side, inside) {
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

const WRAPPED_REPLACEMENT = `function wrappedLine(view, pos, side, inside) {
    let coords = view.coordsAtPos(pos, side * 2);
    if (!coords)
        return inside;
    let row = visualRowBounds(view, pos, coords, inside.from, inside.to);
    return { from: Math.max(inside.from, row.from), to: Math.min(inside.to, row.to) };
}`;

const REPLACEMENTS = [
  ["moveToLineBoundary", BOUNDARY_ORIGINAL, BOUNDARY_REPLACEMENT],
  ["wrappedLine", WRAPPED_ORIGINAL, WRAPPED_REPLACEMENT],
];

const VIEW_MODULE = /@codemirror[/\\]view[/\\]dist[/\\]index\.js$/;

/**
 * Apply every rewrite to a copy of the upstream source.
 *
 * Returns `null` if any of them no longer matches. Exported so the test suite
 * can prove the patch still fits the installed dependency; minification
 * renames the locals, so the built bundle cannot be searched for the
 * replacement text itself.
 */
export function applyPatch(source) {
  let patched = source;
  for (const [, original, replacement] of REPLACEMENTS) {
    if (!patched.includes(original)) return null;
    patched = patched.replace(original, replacement);
  }
  return patched;
}

/** The functions this patch rewrites, for the test suite to name. */
export const PATCHED_FUNCTIONS = REPLACEMENTS.map(([name]) => name);

/** An esbuild plugin that rewrites them as the bundle is built. */
export function codeMirrorBidiPatch() {
  let applied = false;
  return {
    name: "codemirror-bidi",
    setup(build) {
      build.onLoad({ filter: VIEW_MODULE }, async (args) => {
        const patched = applyPatch(await readFile(args.path, "utf8"));
        if (patched === null) {
          throw new Error(
            "The bidi patch no longer matches @codemirror/view. Check whether the upstream " +
              "fix has landed; if it has, delete this patch, and otherwise re-derive it " +
              "against the new source.",
          );
        }
        applied = true;
        return { contents: patched, loader: "js" };
      });
      build.onEnd(() => {
        if (!applied) {
          throw new Error(
            "The bidi patch never ran; @codemirror/view was not loaded from its expected path.",
          );
        }
      });
    },
  };
}
