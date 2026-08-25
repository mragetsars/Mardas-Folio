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
 * The fix is to move what does not fit into a menu rather than off the edge,
 * and this is the part of that worth testing on its own: given the widths of
 * the groups and the room available, which groups stay.
 */

/**
 * Plan a toolbar's overflow.
 *
 * @param {number[]} widths  natural width of each movable group, in order.
 * @param {number} available room the movable groups may use, in px.
 * @param {object} [options]
 * @param {number} [options.gap] space between two adjacent groups.
 * @param {number} [options.triggerWidth] width of the overflow trigger, only
 *   charged when something actually overflows — a bar that fits exactly must
 *   not grow a menu it does not need.
 * @returns {{visible: number, overflow: number[]}} how many leading groups
 *   stay, and the indices of those that move.
 */
export function planToolbarOverflow(widths, available, options = {}) {
  const gap = Number(options.gap) || 0;
  const triggerWidth = Number(options.triggerWidth) || 0;
  const sizes = widths.map((width) => Math.max(0, Number(width) || 0));
  const room = Math.max(0, Number(available) || 0);

  const natural = sizes.reduce((total, width) => total + width, 0)
    + gap * Math.max(0, sizes.length - 1);
  if (natural <= room) return { visible: sizes.length, overflow: [] };

  // Groups are kept in order and never split: half a group reads as a bug,
  // and the groups are the units the user already sees on the bar.
  let used = triggerWidth;
  let visible = 0;
  for (const width of sizes) {
    const next = used + width + (visible > 0 ? gap : 0);
    if (next > room) break;
    used = next;
    visible += 1;
  }
  return {
    visible,
    overflow: sizes.map((_, index) => index).slice(visible),
  };
}
