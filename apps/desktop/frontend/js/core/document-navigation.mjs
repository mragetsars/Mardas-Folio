import { foldForFilter } from "./persian.mjs";
import { documentDirty, pathKey } from "./documents.mjs";

/** Open buffers take precedence over their on-disk counterparts. */
export function documentNavigationEntries(documents = [], project = null, recents = []) {
  const knownPaths = new Set(documents.filter((item) => item.path).map((item) => pathKey(item.path)));
  const entries = documents.map((item) => ({
    id: `document:${item.id}`,
    documentId: item.id,
    label: item.title,
    detail: item.path || "",
    dirty: documentDirty(item),
  }));
  for (const file of project?.files || []) {
    if (!["markdown", "text", "config", "toml", "bibliography", "json"].includes(file.kind)) continue;
    const absolute = `${project.path.replace(/[\\/]$/, "")}/${file.path}`;
    const key = pathKey(absolute);
    if (knownPaths.has(key)) continue;
    knownPaths.add(key);
    entries.push({ id: `project:${file.path}`, relativePath: file.path,
      label: file.chapter_title || file.path.split(/[\\/]/).at(-1), detail: file.path });
  }
  for (const { path } of recents) {
    if (!path) continue;
    const key = pathKey(path);
    if (knownPaths.has(key)) continue;
    knownPaths.add(key);
    entries.push({ id: `recent:${key}`, recentPath: path, label: path.split(/[\\/]/).at(-1), detail: path });
  }
  return entries;
}

/** Multiword name/path search; no user regex is executed. */
export function filterNavigationEntries(entries, query, limit = 100) {
  const tokens = foldForFilter(query).split(/\s+/).filter(Boolean);
  return (entries || []).map((entry, index) => {
    const label = foldForFilter(entry.label);
    const detail = foldForFilter(entry.detail);
    const haystack = `${label} ${detail}`;
    if (!tokens.every((token) => haystack.includes(token))) return null;
    const score = tokens.reduce((value, token) => value + (label.startsWith(token) ? 4 : label.includes(token) ? 2 : 0), 0);
    return { entry, score, index };
  }).filter(Boolean).sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, limit).map((item) => item.entry);
}
