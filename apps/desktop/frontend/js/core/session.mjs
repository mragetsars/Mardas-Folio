export const SESSION_STORAGE_KEY = "mardas.desktop.authoring-session.v1";
export const MAX_SESSION_PATHS = 10;

export function normalizeSession(value) {
  const rawPaths = Array.isArray(value?.paths) ? value.paths : [];
  const seen = new Set();
  const paths = [];
  for (const path of rawPaths) {
    if (typeof path !== "string" || !path.trim()) continue;
    const normalized = path.trim();
    const key = normalized.replaceAll("\\", "/").toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    paths.push(normalized);
    if (paths.length >= MAX_SESSION_PATHS) break;
  }
  const activePath = typeof value?.activePath === "string" && value.activePath.trim() ? value.activePath.trim() : null;
  const projectPath = typeof value?.projectPath === "string" && value.projectPath.trim()
    ? value.projectPath.trim()
    : null;
  return { paths, activePath, projectPath };
}

export function readSession(storage = globalThis.localStorage) {
  try {
    return normalizeSession(JSON.parse(storage.getItem(SESSION_STORAGE_KEY) || "{}"));
  } catch {
    return { paths: [], activePath: null, projectPath: null };
  }
}

export function writeSession(
  documents,
  activeDocument,
  projectPath = null,
  storage = globalThis.localStorage,
) {
  const session = normalizeSession({
    paths: (Array.isArray(documents) ? documents : []).map((document) => document.path).filter(Boolean),
    activePath: activeDocument?.path ?? null,
    projectPath,
  });
  try {
    storage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Session persistence is optional; document recovery remains independent.
  }
  return session;
}
