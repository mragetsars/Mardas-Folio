import { pathIdentity } from "./path-identity.mjs";

function fileIdentity(value) {
  return pathIdentity(value)
    ?.replace(/^\/\/\?\/unc\//i, "//")
    .replace(/^\/\/\?\/(?=[a-z]:\/)/i, "");
}

/** Include resources and chapters, including files opened outside the tree. */
export function documentBelongsToProject(model, projectPath) {
  const project = fileIdentity(projectPath)?.replace(/\/+$/, "");
  if (!project || !model) return false;
  if (fileIdentity(model.projectPath)?.replace(/\/+$/, "") === project) return true;
  const path = fileIdentity(model.path);
  return Boolean(path && path.startsWith(`${project}/`));
}

/** Book operations consume disk files; first persist all of their open inputs. */
export async function prepareBookFiles({
  projectPath, getDocuments, isDirty, confirm, save, isCurrent = () => true,
}) {
  const affected = () => getDocuments().filter((model) => documentBelongsToProject(model, projectPath));
  const pending = affected().filter(isDirty);
  if (!isCurrent() || (pending.length && !await confirm(pending))) return false;
  for (const model of pending) {
    if (!isCurrent() || !getDocuments().includes(model)) return false;
    if (!isDirty(model)) continue;
    const originalPath = fileIdentity(model.path);
    if (!await save(model) || !isCurrent() || isDirty(model)) return false;
    // Save As must not silently move a chapter away from its manifest path.
    if (originalPath && fileIdentity(model.path) !== originalPath) return false;
  }
  return isCurrent() && !affected().some(isDirty);
}
