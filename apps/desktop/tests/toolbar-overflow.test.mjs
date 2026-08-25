import test from "node:test";
import assert from "node:assert/strict";

import { fitToolbarGroups } from "../frontend/js/core/toolbar-overflow.mjs";

/**
 * A strip of known width whose groups have known widths.
 *
 * `trigger` is charged only once something has overflowed, which is what the
 * real bar does: a strip that fits does not grow a menu it does not need.
 */
function strip({ widths, room, fixed = 0, trigger = 0 }) {
  const state = { parked: [], showing: false, measurements: 0 };
  const used = () =>
    fixed
    + (state.showing ? trigger : 0)
    + widths.reduce(
      (total, width, index) => (state.parked.includes(index) ? total : total + width),
      0,
    );
  return {
    state,
    restore: () => { state.parked = []; state.showing = false; },
    overflows: () => { state.measurements += 1; return used() > room; },
    onOverflow: () => { state.showing = true; },
    park: (index) => state.parked.push(index),
    count: widths.length,
  };
}

test("a strip that fits keeps every group and never reveals the trigger", () => {
  const bar = strip({ widths: [100, 80, 60], room: 260, trigger: 30 });
  assert.deepEqual(fitToolbarGroups(bar), []);
  assert.equal(bar.state.showing, false);
});

test("the trigger's own width is charged once something overflows", () => {
  // 100 + 80 = 180 fits in 200, but not once the 30px trigger is there too.
  const bar = strip({ widths: [100, 80, 60], room: 200, trigger: 30 });
  assert.deepEqual(fitToolbarGroups(bar), [1, 2]);
  assert.equal(bar.state.showing, true);
});

test("groups leave from the end and the result is in strip order", () => {
  // 4x40 plus the 24px trigger is 184 against 100px of room: three have to go
  // before the fourth and the trigger fit.
  const bar = strip({ widths: [40, 40, 40, 40], room: 100, trigger: 24 });
  assert.deepEqual(fitToolbarGroups(bar), [1, 2, 3]);
});

test("it stops as soon as the strip fits, not once per group", () => {
  const bar = strip({ widths: [40, 40, 40, 40], room: 150, trigger: 10 });
  assert.deepEqual(fitToolbarGroups(bar), [3]);
});

test("a strip too narrow for even one group parks all of them", () => {
  const bar = strip({ widths: [120, 60], room: 40, trigger: 24 });
  assert.deepEqual(fitToolbarGroups(bar), [0, 1]);
});

test("fixed furniture on the strip counts against the room", () => {
  // The heading group and the pinned Find group never move.
  const bar = strip({ widths: [60, 60], room: 200, fixed: 90, trigger: 20 });
  assert.deepEqual(fitToolbarGroups(bar), [1]);
});

test("every run starts from a full strip, so a widened window gets its groups back", () => {
  const bar = strip({ widths: [60, 60, 60], room: 120, trigger: 20 });
  assert.deepEqual(fitToolbarGroups(bar), [1, 2]);
  bar.state.room = 400;
  // Widen the strip and run again: restore() must undo the previous parking
  // before anything is measured, or the bar can only ever shrink.
  const wide = strip({ widths: [60, 60, 60], room: 400, trigger: 20 });
  wide.state.parked = [1, 2];
  assert.deepEqual(fitToolbarGroups(wide), []);
  assert.deepEqual(wide.state.parked, []);
});

test("a strip with nothing movable is not an overflow", () => {
  const bar = strip({ widths: [], room: 0, fixed: 40 });
  assert.deepEqual(fitToolbarGroups(bar), []);
  assert.equal(bar.state.measurements, 0);
});
