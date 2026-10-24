import test from "node:test";
import assert from "node:assert/strict";
import { createConfirmationQueue } from "../frontend/js/core/confirmation-queue.mjs";

test("a late save conflict cannot replace or answer an open close decision", async () => {
  const shown = [];
  const answers = [];
  const ask = createConfirmationQueue((details) => new Promise((resolve) => {
    shown.push(details);
    answers.push(resolve);
  }));
  const closing = ask({ operation: "close", document: "b" });
  const conflict = ask({ operation: "overwrite", document: "a" });
  await Promise.resolve();
  assert.deepEqual(shown, [{ operation: "close", document: "b" }]);
  answers[0](false);
  assert.equal(await closing, false);
  await Promise.resolve();
  assert.deepEqual(shown, [
    { operation: "close", document: "b" },
    { operation: "overwrite", document: "a" },
  ]);
  answers[1](true);
  assert.equal(await conflict, true);
});

test("a rejected presenter does not strand later confirmations", async () => {
  const ask = createConfirmationQueue(async (details) => {
    if (details === "fail") throw new Error("presentation failed");
    return details === "accept";
  });
  const first = ask("fail");
  const second = ask("accept");
  await assert.rejects(first, /presentation failed/);
  assert.equal(await second, true);
});
