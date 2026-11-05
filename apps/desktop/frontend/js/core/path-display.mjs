/** Presentation only. Keep original paths for opening, tooltips and identity. */
function normalizedPath(value) {
  if (typeof value !== "string") return "";
  return value.trim().replaceAll("\\", "/").replace(/^\/\/\?\/UNC\//i, "//").replace(/^\/\/\?\//, "").replace(/\/+$/, "");
}

function pathKey(value) {
  return /^[a-z]:\//i.test(value) || value.startsWith("//") ? value.toLowerCase() : value;
}

/** Show a project-relative parent or the final two folders, never the filename twice. */
export function compactDocumentLocation(path, { projectPath = "" } = {}) {
  const normalized = normalizedPath(path);
  if (!normalized) return "";
  const slash = normalized.lastIndexOf("/");
  if (slash < 0) return "";
  const parent = normalized.slice(0, slash);
  const project = normalizedPath(projectPath);
  if (project && (pathKey(parent) === pathKey(project) || pathKey(parent).startsWith(`${pathKey(project)}/`))) {
    return parent.length === project.length ? project.split("/").at(-1) || project : parent.slice(project.length + 1).split("/").join(" / ");
  }
  if (!parent) return "/";
  const folders = parent.split("/").filter(Boolean);
  if (folders.length === 1 && /^[a-z]:$/i.test(folders[0])) return `${folders[0]}/`;
  return folders.slice(-2).join(" / ");
}
