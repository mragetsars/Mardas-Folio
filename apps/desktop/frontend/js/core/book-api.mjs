import { invoke } from "./tauri.mjs";

function requestId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function request(method, params, explicitRequestId = null) {
  const id = explicitRequestId || requestId(method.replace(".", "-"));
  return {
    requestId: id,
    promise: invoke("sidecar_request", {
      request_id: id,
      method,
      params,
    }),
  };
}

function result(method, params) {
  return request(method, params).promise;
}

export function createBookProject({
  parentPath,
  folderName,
  title,
  language = "fa-IR",
  direction = "auto",
}) {
  return result("book.create", {
    parent_path: parentPath,
    folder_name: folderName,
    title,
    language,
    direction,
  });
}

export function addBookChapter({
  projectPath,
  title,
  expectedConfigSha256,
  position = null,
  content = null,
}) {
  const params = {
    project_path: projectPath,
    title,
    expected_config_sha256: expectedConfigSha256,
  };
  if (position !== null && position !== undefined) params.position = position;
  if (content !== null && content !== undefined) params.content = content;
  return result("book.add_chapter", params);
}

export function duplicateBookChapter({
  projectPath,
  relativePath,
  title = null,
  expectedConfigSha256,
}) {
  return result("book.duplicate_chapter", {
    project_path: projectPath,
    relative_path: relativePath,
    title,
    expected_config_sha256: expectedConfigSha256,
  });
}

export function reorderBookChapters({
  projectPath,
  orderedPaths,
  expectedConfigSha256,
}) {
  return result("book.reorder_chapters", {
    project_path: projectPath,
    ordered_paths: orderedPaths,
    expected_config_sha256: expectedConfigSha256,
  });
}

export function removeBookChapter({
  projectPath,
  relativePath,
  expectedConfigSha256,
}) {
  return result("book.remove_chapter", {
    project_path: projectPath,
    relative_path: relativePath,
    expected_config_sha256: expectedConfigSha256,
  });
}

export function startBookValidation(projectPath) {
  return request("book.validate", { project_path: projectPath });
}

export function startBookPreview(projectPath) {
  return request("book.preview", { project_path: projectPath });
}

export function startBookExport({ projectPath, outputPath }) {
  return request("book.export", {
    project_path: projectPath,
    output_path: outputPath,
  });
}
