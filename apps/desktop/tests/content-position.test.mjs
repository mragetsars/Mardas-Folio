import test from "node:test";
import assert from "node:assert/strict";
import { interpolatePosition } from "../frontend/js/core/content-position.mjs";

test("source positions survive different section lengths and reflow", () => {
  const anchors = [{ line: 1, top: 0 }, { line: 10, top: 400 }, { line: 50, top: 600 }, { line: 90, top: 2200 }];
  assert.equal(interpolatePosition(anchors, 30), 500);
  assert.equal(interpolatePosition(anchors, 70), 1400);
  for (const line of [1, 5, 10, 30, 50, 70, 90]) {
    const top = interpolatePosition(anchors, line);
    assert.equal(Math.round(interpolatePosition(anchors, top, "top", "line")), line);
  }
  assert.equal(interpolatePosition(anchors, -4), 0);
  assert.equal(interpolatePosition(anchors, 120), 2200);
  assert.equal(interpolatePosition([], 30), 0);
});
