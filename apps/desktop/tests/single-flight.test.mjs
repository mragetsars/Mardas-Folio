import test from "node:test";
import assert from "node:assert/strict";
import { createSingleFlight } from "../frontend/js/core/single-flight.mjs";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test("a second request during a run waits instead of reaching the engine", async () => {
  const gates = [deferred(), deferred()];
  let started = 0;
  const flight = createSingleFlight(() => gates[started++].promise);

  const first = flight.run();
  assert.equal(started, 1);
  assert.equal(flight.isRunning, true);

  // Three more option changes while the first render holds the engine.
  await flight.run();
  await flight.run();
  await flight.run();
  assert.equal(started, 1, "nothing else may be sent while a job is running");
  assert.equal(flight.hasQueuedRun, true);

  gates[0].resolve();
  await first;
  assert.equal(started, 2, "the queued requests collapse into one rerun");

  gates[1].resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(flight.isRunning, false);
});

test("a run left queued still happens once the engine is free", async () => {
  const gates = [deferred(), deferred()];
  const seen = [];
  let index = 0;
  const flight = createSingleFlight(() => {
    seen.push(index);
    return gates[index++].promise;
  });

  const first = flight.run();
  await flight.run();
  gates[0].resolve();
  await first;
  gates[1].resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.deepEqual(seen, [0, 1]);
});

test("draining waits for the engine and cancels the queued rerun", async () => {
  const gate = deferred();
  let started = 0;
  const flight = createSingleFlight(() => {
    started += 1;
    return gate.promise;
  });

  const first = flight.run();
  await flight.run();
  assert.equal(flight.hasQueuedRun, true);

  const drained = flight.drain();
  gate.resolve();
  await drained;
  await first;
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(started, 1, "the export must not be followed by a stale preview");
  assert.equal(flight.isRunning, false);
  assert.equal(flight.hasQueuedRun, false);
});

test("a failing run releases the engine and does not wedge the runner", async () => {
  let started = 0;
  const flight = createSingleFlight(() => {
    started += 1;
    return started === 1 ? Promise.reject(new Error("validation failed")) : Promise.resolve();
  });

  await assert.rejects(() => flight.run(), /validation failed/);
  assert.equal(flight.isRunning, false);

  await flight.run();
  assert.equal(started, 2, "the runner still accepts work after a failure");
});

test("draining an idle runner resolves immediately", async () => {
  const flight = createSingleFlight(() => Promise.resolve());
  await flight.drain();
  assert.equal(flight.isRunning, false);
});

test("a task that throws synchronously does not leave the runner locked", async () => {
  let started = 0;
  const flight = createSingleFlight(() => {
    started += 1;
    if (started === 1) throw new Error("bad options");
    return Promise.resolve();
  });

  await assert.rejects(() => flight.run(), /bad options/);
  assert.equal(flight.isRunning, false);

  await flight.run();
  assert.equal(started, 2);
});
