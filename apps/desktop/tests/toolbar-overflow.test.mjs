import test from "node:test";
import assert from "node:assert/strict";

import { planToolbarOverflow } from "../frontend/js/core/toolbar-overflow.mjs";

test("a toolbar that fits keeps every group and no trigger", () => {
  const plan = planToolbarOverflow([100, 80, 60], 260, { gap: 0, triggerWidth: 30 });
  assert.equal(plan.visible, 3);
  assert.deepEqual(plan.overflow, []);
});

test("gaps count against the room, so an exact fit is not an overflow", () => {
  // 100 + 4 + 80 + 4 + 60 = 248.
  assert.equal(planToolbarOverflow([100, 80, 60], 248, { gap: 4 }).visible, 3);
  assert.equal(planToolbarOverflow([100, 80, 60], 247, { gap: 4 }).visible, 2);
});

test("the trigger is only charged once something overflows", () => {
  // Without the trigger the first two groups and their gap need 184px, which
  // fits in 200; with the 30px trigger they do not, so only one stays.
  const plan = planToolbarOverflow([100, 80, 60], 200, { gap: 4, triggerWidth: 30 });
  assert.equal(plan.visible, 1);
  assert.deepEqual(plan.overflow, [1, 2]);
});

test("groups move from the end, in order, and are never split", () => {
  const plan = planToolbarOverflow([40, 40, 40, 40], 100, { gap: 2, triggerWidth: 24 });
  assert.deepEqual(plan.overflow, [1, 2, 3]);
  assert.equal(plan.visible, 1);
});

test("a bar too narrow for even one group moves all of them", () => {
  const plan = planToolbarOverflow([120, 60], 40, { triggerWidth: 24 });
  assert.equal(plan.visible, 0);
  assert.deepEqual(plan.overflow, [0, 1]);
});

test("nothing to lay out is not an overflow", () => {
  assert.deepEqual(planToolbarOverflow([], 0, { triggerWidth: 24 }), {
    visible: 0,
    overflow: [],
  });
});

test("negative and non-numeric input cannot produce a negative plan", () => {
  const plan = planToolbarOverflow([-10, Number.NaN, 30], -5, { gap: -4 });
  assert.equal(plan.visible, 2);
  assert.deepEqual(plan.overflow, [2]);
});
