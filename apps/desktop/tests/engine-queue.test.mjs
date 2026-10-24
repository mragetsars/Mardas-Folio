import test from "node:test";
import assert from "node:assert/strict";
import { createEngineQueue } from "../frontend/js/core/engine-queue.mjs";
import { invoke } from "../frontend/js/core/tauri.mjs";

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("a save waits for the active preview and takes priority over queued previews", async () => {
  const queue = createEngineQueue();
  const gate = deferred();
  const started = [];
  const first = queue.run("p1", () => { started.push("p1"); return gate.promise; }, { speculative: true });
  const second = queue.run("p2", () => started.push("p2"), { speculative: true });
  const save = queue.run("save", () => started.push("save"));
  assert.deepEqual(started, ["p1"]);
  gate.resolve();
  await Promise.all([first, second, save]);
  assert.deepEqual(started, ["p1", "save", "p2"]);
});

test("queued cancellation never sends the cancelled operation to the sidecar", async () => {
  const queue = createEngineQueue();
  const gate = deferred();
  const first = queue.run("active", () => gate.promise);
  let ran = false;
  const waiting = queue.run("search", () => { ran = true; });
  assert.equal(queue.cancel("search"), true);
  await assert.rejects(waiting, (error) => JSON.parse(error).data.application_code === "MARDAS-JOB-CANCELLED");
  gate.resolve();
  await first;
  assert.equal(ran, false);
});

test("a failed task releases the slot for the next file operation", async () => {
  const queue = createEngineQueue();
  const first = queue.run("bad", () => { throw new Error("disk full"); });
  const second = queue.run("save", () => "saved");
  await assert.rejects(first, /disk full/);
  assert.equal(await second, "saved");
});

test("native cancellation and health bypass active work while queued cancellation stays local", async () => {
  const gate = deferred();
  const calls = [];
  const globalObject = { __TAURI__: { core: { invoke: (command, args) => {
    calls.push([command, args.method || args.request_id]);
    return args.request_id === "active" && command === "sidecar_request" ? gate.promise : Promise.resolve({ ok: true });
  } } } };
  const active = invoke("sidecar_request", { request_id: "active", method: "preview.document_text" }, globalObject);
  const waiting = invoke("sidecar_request", { request_id: "waiting", method: "document.save" }, globalObject);
  await invoke("sidecar_request", { request_id: "health", method: "system.health" }, globalObject);
  assert.equal((await invoke("sidecar_cancel", { request_id: "waiting" }, globalObject)).cancel_requested, true);
  await assert.rejects(waiting, (error) => JSON.parse(error).data.application_code === "MARDAS-JOB-CANCELLED");
  await invoke("sidecar_cancel", { request_id: "active" }, globalObject);
  assert.deepEqual(calls, [["sidecar_request", "preview.document_text"], ["sidecar_request", "system.health"], ["sidecar_cancel", "active"]]);
  gate.resolve();
  await active;
});
