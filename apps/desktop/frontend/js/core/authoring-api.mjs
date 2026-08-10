import { invoke } from "./tauri.mjs";

function requestId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function sidecar(method, params, id = undefined) {
  return invoke("sidecar_request", {
    request_id: id || requestId(method.replaceAll(".", "-")),
    method,
    params,
  });
}

export function readDocument(path) {
  return sidecar("document.read", { path });
}

export function readTextDocument(path) {
  return sidecar("document.read_text", { path });
}

export function saveDocument({ path, content, expectedRevision = null, force = false }) {
  return sidecar("document.save", {
    path,
    content,
    expected_revision: expectedRevision,
    force,
  });
}

export function saveTextDocument({ path, content, expectedRevision = null, force = false }) {
  return sidecar("document.save_text", {
    path,
    content,
    expected_revision: expectedRevision,
    force,
  });
}

export function validateDocumentText({ path, content, options = {} }) {
  return sidecar("validate.document_text", {
    input_path: path || "untitled.md",
    content,
    discover_config: Boolean(path),
    options,
  });
}

export function previewDocumentText({ path, content, options = {}, requestId: id } = {}) {
  return sidecar("preview.document_text", {
    input_path: path || "untitled.md",
    content,
    discover_config: Boolean(path),
    options,
  }, id);
}

export function listDocumentAssets(path) {
  return sidecar("document.list_assets", { path });
}

export function importDocumentAsset(documentPath, sourcePath) {
  return sidecar("document.import_asset", { document_path: documentPath, source_path: sourcePath });
}
