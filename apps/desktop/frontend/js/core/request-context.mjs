import { pathIdentity } from "./path-identity.mjs";

export function captureDocumentContext(document, projectPath = null) {
  if (!document?.id) return null;
  return Object.freeze({
    documentId: document.id,
    contentVersion: Number(document.contentVersion) || 0,
    path: document.path ?? null,
    projectPath: projectPath ?? null,
  });
}

export function captureProjectContext(projectPath, projectGeneration = 0) {
  const projectIdentity = pathIdentity(projectPath);
  if (!projectIdentity) return null;
  return Object.freeze({
    projectIdentity,
    projectGeneration: Number(projectGeneration) || 0,
  });
}

export function projectContextCurrent(
  context,
  { projectPath = null, projectGeneration = 0 },
) {
  if (!context) return false;
  return context.projectIdentity === pathIdentity(projectPath)
    && context.projectGeneration === (Number(projectGeneration) || 0);
}

export function documentContextCurrent(
  context,
  { documents, activeDocumentId, projectPath = null },
  { requireActive = true, requireContent = true, requirePath = true } = {},
) {
  if (!context || !Array.isArray(documents)) return false;
  const document = documents.find((candidate) => candidate.id === context.documentId);
  if (!document) return false;
  if (requireActive && activeDocumentId !== context.documentId) return false;
  if (requireContent && (Number(document.contentVersion) || 0) !== context.contentVersion) return false;
  if (requirePath && (document.path ?? null) !== context.path) return false;
  return (projectPath ?? null) === context.projectPath;
}
