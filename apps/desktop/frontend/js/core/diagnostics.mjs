import { pathIdentity } from "./path-identity.mjs";

function documentDiagnosticPaths(document) {
  const candidates = [document?.path, document?.projectRelativePath];
  if (!document?.path) candidates.push("untitled.md");
  return new Set(candidates.map(pathIdentity).filter(Boolean));
}

export function inlineDiagnosticsForDocument(items, document) {
  if (!document) return [];
  const currentPaths = documentDiagnosticPaths(document);
  const diagnostics = [];
  for (const item of Array.isArray(items) ? items : []) {
    if (!item || typeof item !== "object" || !Number(item.line)) continue;
    if (item.path && !currentPaths.has(pathIdentity(item.path))) continue;
    const { path: _path, ...inline } = item;
    diagnostics.push(inline);
  }
  return diagnostics;
}
