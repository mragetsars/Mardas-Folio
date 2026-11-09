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
