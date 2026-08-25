/**
 * How much of a single-row toolbar fits, and what has to move out of it.
 *
 * The format bar holds nineteen controls in seven groups. It was laid out
 * `flex-wrap: nowrap` inside `overflow-x: auto` with `scrollbar-width: none`,
 * so when the editor pane was narrow the controls past the edge were simply
 * gone: no scrollbar, no chevron, nothing to say they existed. Measured in
 * split view, eight of the nineteen were unreachable at 720x620 and five at
 * 1280x900 — quote, callout, table, code block, rule, undo and redo among
 * them.
 *
 * Groups that do not fit are moved into a menu instead. Deciding how many fit
 * is measured rather than computed: the strip carries its own padding, a
 * sticky group pinned to its trailing edge and a trigger that exists only
 * when it is needed, and an arithmetic model of those widths is a second
 * source of truth. When that model disagreed with the browser by 33px the
 * last control was left sitting underneath the sticky group — inside the
 * strip's box, so not clipped, and painted over, so not visible either.
 */

/**
 * Park trailing groups until the strip stops overflowing.
 *
 * Every group goes back first. A plan computed from the current layout only
 * ever loses groups: the bar would ratchet down and never recover when the
 * window grew again.
 *
 * @param {object} io
 * @param {() => void} io.restore put every group back on the strip.
 * @param {() => boolean} io.overflows does the strip overflow right now?
 * @param {() => void} [io.onOverflow] called once, before the first move, so
 *   the caller can reveal the trigger — which takes room of its own.
 * @param {(index: number) => void} io.park move group `index` off the strip.
 * @param {number} io.count how many groups are allowed to move.
 * @returns {number[]} the parked group indices, in strip order.
 */
export function fitToolbarGroups(io) {
  const count = Math.max(0, Number(io?.count) || 0);
  io.restore();
  if (!count || !io.overflows()) return [];
  io.onOverflow?.();

  // Groups move from the end and never split: half a group reads as a
  // rendering fault, and the groups are the units already drawn on the bar.
  const parked = [];
  for (let index = count - 1; index >= 0; index -= 1) {
    if (!io.overflows()) break;
    io.park(index);
    parked.unshift(index);
  }
  return parked;
}
