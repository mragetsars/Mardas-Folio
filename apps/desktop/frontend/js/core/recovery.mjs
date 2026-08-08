import { pathIdentity } from "./path-identity.mjs";

export const RECOVERY_STORAGE_KEY = "mardas.desktop.authoring-recovery.v1";
export const MAX_RECOVERY_DOCUMENTS = 12;
export const MAX_RECOVERY_CHARS = 1_000_000;
export const MAX_RECOVERY_TOTAL_CHARS = 3_000_000;

function safeEntries(value) {
  if (!Array.isArray(value)) return [];
  const unique = new Map();
  for (const item of value) {
    if (!item || typeof item.key !== "string" || typeof item.content !== "string") continue;
    if (item.content.length > MAX_RECOVERY_CHARS) continue;
    const updatedAt = Number(item.updatedAt);
    unique.set(item.key, {
      key: item.key,
      path: typeof item.path === "string" ? item.path : null,
      title: typeof item.title === "string" && item.title ? item.title : "Untitled",
      content: item.content,
      revision: typeof item.revision === "string" ? item.revision : null,
      updatedAt: Number.isFinite(updatedAt) ? updatedAt : Date.now(),
    });
  }
  const sorted = [...unique.values()].sort((a, b) => b.updatedAt - a.updatedAt);
  const bounded = [];
  let total = 0;
  for (const item of sorted) {
    if (bounded.length >= MAX_RECOVERY_DOCUMENTS) break;
    if (total + item.content.length > MAX_RECOVERY_TOTAL_CHARS) continue;
    total += item.content.length;
    bounded.push(item);
  }
  return bounded;
}

export function recoveryKey(document) {
  return document.path ? `path:${pathIdentity(document.path)}` : `draft:${document.id}`;
}

export function readRecoveries(storage = globalThis.localStorage) {
  try {
    return safeEntries(JSON.parse(storage.getItem(RECOVERY_STORAGE_KEY) || "[]"));
  } catch {
    return [];
  }
}

export function writeRecoveries(entries, storage = globalThis.localStorage) {
  const normalized = safeEntries(entries);
  try {
    storage.setItem(RECOVERY_STORAGE_KEY, JSON.stringify(normalized));
    return { ok: true, entries: normalized };
  } catch (error) {
    return { ok: false, entries: normalized, error };
  }
}

export function saveRecovery(document, storage = globalThis.localStorage, now = Date.now()) {
  if (document.content.length > MAX_RECOVERY_CHARS) {
    return { ok: false, reason: "too_large", entries: readRecoveries(storage) };
  }
  const key = recoveryKey(document);
  const next = [
    {
      key,
      path: document.path,
      title: document.title,
      content: document.content,
      revision: document.revision,
      updatedAt: now,
    },
    ...readRecoveries(storage).filter((item) => item.key !== key),
  ];
  return writeRecoveries(next, storage);
}

export function removeRecovery(documentOrKey, storage = globalThis.localStorage) {
  const key = typeof documentOrKey === "string" ? documentOrKey : recoveryKey(documentOrKey);
  return writeRecoveries(readRecoveries(storage).filter((item) => item.key !== key), storage);
}

export function recoveryForPath(path, storage = globalThis.localStorage) {
  if (typeof path !== "string" || !path.trim()) return null;
  const key = `path:${pathIdentity(path)}`;
  return readRecoveries(storage).find((item) => item.key === key) ?? null;
}
