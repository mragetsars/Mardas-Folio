import test from "node:test";
import assert from "node:assert/strict";
import {
  beginCancellationHandoff,
  waitForTaskSettlement,
} from "../frontend/js/core/task-handoff.mjs";

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("a project handoff waits for the previous task to settle after cancellation", async () => {
  const task = deferred();
  const events = [];
  const handoff = beginCancellationHandoff({
    completion: task.promise,
    cancel: () => { events.push("cancel"); },
  }).then(() => events.push("open"));

  await Promise.resolve();
  assert.deepEqual(events, ["cancel"]);
  task.resolve();
  await handoff;
  assert.deepEqual(events, ["cancel", "open"]);
});

test("a failed cancel is handled and a stuck task releases only at the bound", async () => {
  let releaseTimeout;
  const result = beginCancellationHandoff({
    completion: new Promise(() => {}),
    cancel: () => { throw new Error("transport stopped"); },
    timeoutMs: 10,
    setTimer: (callback) => { releaseTimeout = callback; return 1; },
    clearTimer: () => {},
  });
  releaseTimeout();
  assert.equal(await result, false);
});

test("task rejection counts as settlement and never rejects the transition", async () => {
  assert.equal(await waitForTaskSettlement(Promise.reject(new Error("cancelled"))), true);
});
