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

export function cancelSidecarRequest(requestId) {
  if (!requestId) return Promise.resolve({ cancel_requested: false });
  return invoke("sidecar_cancel", { request_id: requestId });
}

export function openProject(path) {
  return result("project.open", { path });
}

export function refreshProject(path) {
  return result("project.refresh", { path });
}

export function readProjectFile(projectPath, relativePath) {
  return result("project.read", {
    project_path: projectPath,
    relative_path: relativePath,
  });
}

export function saveProjectFile({ projectPath, relativePath, content, expectedSha256 }) {
  return result("project.save", {
    project_path: projectPath,
    relative_path: relativePath,
    content,
    expected_sha256: expectedSha256,
  });
}

export function startProjectSearch({
  projectPath,
  query,
  regex = false,
  caseSensitive = false,
  maxResults = 200,
}) {
  return request("project.search", {
    project_path: projectPath,
    query,
    regex,
    case_sensitive: caseSensitive,
    max_results: maxResults,
  });
}

export function bibliographyIndex({
  projectPath,
  query = "",
  citedKeys = [],
  maxResults = 500,
}) {
  return result("bibliography.index", {
    project_path: projectPath,
    query,
    cited_keys: citedKeys,
    max_results: maxResults,
  });
}
