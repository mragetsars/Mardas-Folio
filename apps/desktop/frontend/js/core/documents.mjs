import { basename } from "./export-request.mjs";

let untitledSequence = 1;

function cleanPath(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function pathKey(path) {
  return cleanPath(path)?.replaceAll("\\", "/").toLocaleLowerCase() ?? null;
}

export function createDocument({ path = null, content = "", revision = null, readOnly = false } = {}) {
  const resolvedPath = cleanPath(path);
  const title = resolvedPath ? basename(resolvedPath) : `Untitled ${untitledSequence++}`;
  return {
    id: globalThis.crypto?.randomUUID?.() ?? `doc-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    path: resolvedPath,
    title,
    content: String(content ?? ""),
    savedContent: String(content ?? ""),
    revision: typeof revision === "string" ? revision : null,
    readOnly: Boolean(readOnly),
    diagnostics: [],
    preview: null,
    lastSavedAt: resolvedPath ? Date.now() : null,
  };
}

export function documentDirty(document) {
  return document.content !== document.savedContent;
}

export function updateDocumentContent(document, content) {
  document.content = String(content ?? "");
  return document;
}

export function markDocumentSaved(document, result, content = document.content) {
  document.path = cleanPath(result?.path) ?? document.path;
  document.title = document.path ? basename(document.path) : document.title;
  document.revision = typeof result?.revision === "string" ? result.revision : document.revision;
  document.readOnly = Boolean(result?.read_only);
  document.content = String(content ?? "");
  document.savedContent = document.content;
  document.lastSavedAt = Date.now();
  return document;
}

export function findDocumentByPath(documents, path) {
  const key = pathKey(path);
  if (!key) return null;
  return documents.find((document) => pathKey(document.path) === key) ?? null;
}

export function closeDocument(documents, id) {
  const index = documents.findIndex((document) => document.id === id);
  if (index < 0) return { documents: [...documents], nextId: documents[0]?.id ?? null };
  const remaining = documents.filter((document) => document.id !== id);
  const next = remaining[Math.min(index, Math.max(0, remaining.length - 1))] ?? null;
  return { documents: remaining, nextId: next?.id ?? null };
}
