import { invoke } from "./tauri.mjs";

function request(method, params) {
  return invoke("sidecar_request", {
    request_id: `shelf-${globalThis.crypto.randomUUID()}`,
    method,
    params,
  });
}

export const readLibrary = () => request("library.read", {});
export const writeLibrary = (expectedRevision, items) =>
  request("library.write", { expected_revision: expectedRevision, items });
