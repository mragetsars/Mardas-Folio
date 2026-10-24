import { createEngineQueue } from "./engine-queue.mjs";

const queues = new WeakMap();
const IMMEDIATE_METHODS = new Set(["system.health", "system.capabilities", "system.shutdown", "job.cancel"]);

export function tauriApi(globalObject = globalThis) {
  const api = globalObject.__TAURI__;
  if (!api?.core?.invoke) throw new Error("TAURI_UNAVAILABLE");
  return api;
}

export async function invoke(command, args = {}, globalObject = globalThis) {
  const api = tauriApi(globalObject);
  let queue = queues.get(api.core);
  if (!queue) {
    queue = createEngineQueue();
    queues.set(api.core, queue);
  }
  const cancellation = command === "sidecar_cancel" ? args.request_id
    : command === "sidecar_request" && args.method === "job.cancel" ? args.params?.request_id : null;
  if (cancellation != null && queue.cancel(cancellation)) {
    return { request_id: cancellation, cancel_requested: true };
  }
  if (command === "sidecar_request" && !IMMEDIATE_METHODS.has(args.method)) {
    return queue.run(args.request_id, () => api.core.invoke(command, args), {
      speculative: args.method?.startsWith("preview."),
    });
  }
  return api.core.invoke(command, args);
}

export async function listen(event, callback, globalObject = globalThis) {
  return tauriApi(globalObject).event.listen(event, callback);
}
