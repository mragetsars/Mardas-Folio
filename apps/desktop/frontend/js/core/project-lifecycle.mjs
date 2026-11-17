import { pathKey } from "./documents.mjs";

/**
 * Detach a project workspace without closing or rewriting any open documents.
 *
 * Open chapters are still ordinary files after a project closes. Their buffers
 * (including unsaved edits), paths and recovery snapshots therefore survive;
 * only project-owned metadata and pending request generations are invalidated.
 */
export function resetProjectSession(state) {
  const project = state.project || null;
  state.project = null;
  state.projectGeneration = (Number(state.projectGeneration) || 0) + 1;
  state.projectRequestSequence = (Number(state.projectRequestSequence) || 0) + 1;
  state.projectSearchSequence = (Number(state.projectSearchSequence) || 0) + 1;
  state.activeProjectSearchRequestId = null;
  state.projectFileRequests?.clear?.();
  state.projectDiagnostics = [];
  state.bibliographyEntries = [];
  state.bibliographySequence = (Number(state.bibliographySequence) || 0) + 1;
  state.assetSequence = (Number(state.assetSequence) || 0) + 1;
  state.validationSequence = (Number(state.validationSequence) || 0) + 1;
  state.previewSequence = (Number(state.previewSequence) || 0) + 1;
  state.documentActivationSequence = (Number(state.documentActivationSequence) || 0) + 1;
  state.bookOutputPath = null;

  for (const document of state.documents || []) {
    delete document.projectPath;
    delete document.projectRelativePath;
    delete document.projectSha256;
  }

  return project;
}

export function attachProjectMembership(model, project) {
  delete model.projectPath;
  delete model.projectRelativePath;
  delete model.projectSha256;
  if (!model.path || !project?.path) return;
  const root = String(project.path).replace(/[\\/]+$/, "");
  const file = (project.files || []).find(
    (item) => pathKey(`${root}/${item.path}`) === pathKey(model.path),
  );
  if (!file) return;
  model.projectPath = project.path;
  model.projectRelativePath = file.path;
  // The standalone revision hashes the bytes originally read. Keep that
  // revision even when the user has edited the buffer or the disk has changed.
  model.projectSha256 = String(model.revision || "").match(/:([a-f0-9]{64})$/i)?.[1] || "";
}

/** Attach the loaded snapshot without replacing any document buffer or revision. */
export function applyProjectSession(state, project) {
  state.project = project;
  for (const model of state.documents) attachProjectMembership(model, project);
  state.projectGeneration += 1;
  state.bibliographySequence += 1;
  state.assetSequence += 1;
  state.validationSequence += 1;
  state.previewSequence += 1;
  state.projectDiagnostics = Array.isArray(project.diagnostics) ? project.diagnostics : [];
}
