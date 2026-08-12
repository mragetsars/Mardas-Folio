import { pathIdentity } from "./path-identity.mjs";

function documentDiagnosticPaths(document) {
  const candidates = [document?.path, document?.projectRelativePath];
  if (!document?.path) candidates.push("untitled.md");
  return new Set(candidates.map(pathIdentity).filter(Boolean));
}

/**
 * An engine error's diagnostics, as lines a reader can act on.
 *
 * A validation failure names the offending citation key, heading or reference
 * and where it is; the top-level message only says that validation failed. Both
 * travel in the same error payload, so showing the summary alone throws away
 * the half that answers "what do I fix?".
 */
export function diagnosticLines(payload, limit = 8) {
  const diagnostics = payload?.details?.diagnostics;
  if (!Array.isArray(diagnostics)) return [];
  const lines = [];
  for (const item of diagnostics) {
    if (lines.length >= limit) break;
    if (!item || typeof item !== "object") continue;
    if ((item.severity || "error") !== "error") continue;
    const location = Number(item.line) ? ` (${item.line}:${item.column || 1})` : "";
    const hint = item.hint ? ` — ${item.hint}` : "";
    const line = `${item.message || item.code || ""}${location}${hint}`.trim();
    if (line) lines.push(line);
  }
  return lines;
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
