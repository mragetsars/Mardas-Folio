import { basename } from "./export-request.mjs";
import { pathIdentity } from "./path-identity.mjs";

let untitledSequence = 1;

function cleanPath(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function pathKey(path) {
  return pathIdentity(cleanPath(path));
}

export function createDocument({
  path = null,
  content = "",
  revision = null,
  readOnly = false,
  kind = "markdown",
  persisted = null,
} = {}) {
  const resolvedPath = cleanPath(path);
  const initialContent = String(content ?? "");
  const title = resolvedPath ? basename(resolvedPath) : `Untitled ${untitledSequence++}`;
  return {
    id: globalThis.crypto?.randomUUID?.() ?? `doc-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    path: resolvedPath,
    title,
    content: initialContent,
    savedContent: initialContent,
    contentVersion: 0,
    persisted: persisted === null ? Boolean(resolvedPath) : Boolean(persisted),
    kind: typeof kind === "string" && kind.trim() ? kind.trim().toLowerCase() : "text",
    revision: typeof revision === "string" ? revision : null,
    readOnly: Boolean(readOnly),
    diagnostics: [],
    bibliographyDiagnostics: [],
    preview: null,
    lastSavedAt: resolvedPath ? Date.now() : null,
  };
}

export function documentDirty(document) {
  return !document.persisted || document.content !== document.savedContent;
}

export function updateDocumentContent(document, content) {
  const next = String(content ?? "");
  if (next !== document.content) {
    document.content = next;
    document.contentVersion = (Number(document.contentVersion) || 0) + 1;
  }
  return document;
}

export function markDocumentSaved(document, result, content = document.content) {
  document.path = cleanPath(result?.path) ?? document.path;
  document.title = document.path ? basename(document.path) : document.title;
  document.revision = typeof result?.revision === "string" ? result.revision : document.revision;
  if (typeof result?.read_only === "boolean") document.readOnly = result.read_only;
  document.savedContent = String(content ?? "");
  document.persisted = true;
  document.lastSavedAt = Date.now();
  return document;
}

export function findDocumentByPath(documents, path) {
  const key = pathKey(path);
  if (!key) return null;
  return documents.find((document) => pathKey(document.path) === key) ?? null;
}

export function findSavePathCollision(documents, currentDocument, path) {
  const existing = findDocumentByPath(documents, path);
  return existing && existing !== currentDocument ? existing : null;
}

export function closeDocument(documents, id) {
  const index = documents.findIndex((document) => document.id === id);
  if (index < 0) return { documents: [...documents], nextId: documents[0]?.id ?? null };
  const remaining = documents.filter((document) => document.id !== id);
  const next = remaining[Math.min(index, Math.max(0, remaining.length - 1))] ?? null;
  return { documents: remaining, nextId: next?.id ?? null };
}
