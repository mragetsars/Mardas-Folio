/** Decode Markdown image destinations once, before native containment checks. */
export function localImageDestination(source) {
  let value = String(source || "").trim();
  if (value.startsWith("<") && value.endsWith(">")) value = value.slice(1, -1);
  value = value.replace(/\\([!"#$%&'()*+,\-./:;<=>?@[\]^_`{|}~])/g, "$1");
  value = value.split(/[?#]/, 1)[0];
  try {
    value = decodeURIComponent(value);
  } catch {
    return null;
  }
  value = value.replaceAll("\\", "/");
  if (
    !value ||
    /^[a-z][a-z0-9+.-]*:/i.test(value) ||
    value.startsWith("/") ||
    value.split("/").includes("..") ||
    /[\u0000-\u001f\u007f]/.test(value)
  )
    return null;
  return value;
}

/** Image widgets only need the files named in the buffer, not a directory walk. */
export function documentImageSources(content, { limit = 4096 } = {}) {
  const text = String(content || "");
  const sources = new Set();
  const add = (source) => {
    const value = localImageDestination(source);
    if (value && sources.size < limit) sources.add(value);
  };
  // Inline links with balanced parentheses, escaped punctuation and <paths>.
  const inline =
    /!\[(?:\\.|[^\]\\])*\]\(\s*(<[^>\r\n]+>|(?:\\.|[^\s()\\]|\((?:\\.|[^()\\])*\))+)\s*(?:["'][^\r\n]*?["']\s*)?\)/g;
  for (const match of text.matchAll(inline)) add(match[1]);
  // A definition is harmless to grant even if its image reference is outside
  // the current viewport. Native code still validates every canonical path.
  const definitions = /^ {0,3}\[[^\]\r\n]+\]:\s*(<[^>\r\n]+>|\S+)/gm;
  for (const match of text.matchAll(definitions)) add(match[1]);
  return [...sources];
}

/** Preserve inline Markdown alt text when the engine emits a blocked image card. */
export function documentImageAlts(content, { limit = 4096 } = {}) {
  const result = new Map();
  const inline =
    /!\[((?:\\.|[^\]\\])*)\]\(\s*(<[^>\r\n]+>|(?:\\.|[^\s()\\]|\((?:\\.|[^()\\])*\))+)\s*(?:["'][^\r\n]*?["']\s*)?\)/g;
  for (const match of String(content || "").matchAll(inline)) {
    if (result.size >= limit) break;
    const source = match[2].replace(/^<|>$/g, "");
    result.set(source, match[1].replace(/\\([!"#$%&'()*+,\-./:;<=>?@[\]^_`{|}~\\])/g, "$1"));
  }
  return result;
}
