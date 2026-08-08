import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { bookTaskBlocked, claimBookTask } from "../frontend/js/core/book-task-state.mjs";

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("double-click claims exactly one book task before invoking the sidecar factory", () => {
  const state = {
    activeBookRequestId: null,
    activeBookCompletion: null,
    bookCancellationHandoff: null,
  };
  const pending = deferred();
  let starts = 0;
  const start = () => {
    starts += 1;
    return { requestId: `book-${starts}`, promise: pending.promise };
  };

  const first = claimBookTask(state, start);
  const second = claimBookTask(state, start);
  assert.equal(first.requestId, "book-1");
  assert.equal(second, null);
  assert.equal(starts, 1);
  assert.equal(bookTaskBlocked(state), true);
  pending.resolve();
});

test("project cancellation handoff blocks a new book request factory", () => {
  const state = {
    activeBookRequestId: null,
    activeBookCompletion: null,
    bookCancellationHandoff: Promise.resolve(true),
  };
  let starts = 0;
  assert.equal(claimBookTask(state, () => { starts += 1; return { promise: null }; }), null);
  assert.equal(starts, 0);
});

test("main creates sidecar tasks lazily behind the exclusive guard", () => {
  const main = readFileSync(new URL("../frontend/js/main.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(main, /runBookTask\(startBook/);
  for (const factory of ["startBookValidation", "startBookPreview", "startBookExport"]) {
    assert.match(main, new RegExp(`runBookTask\\(\\(\\) => ${factory}`));
  }
  assert.match(main, /#book-add-chapter, #book-validate, #book-preview, #book-export/);
  assert.match(main, /bookDisabledBeforeLock/);
});
