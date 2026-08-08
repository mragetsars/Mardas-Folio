const FRONT_MATTER_BOUNDARY = /^---\s*$/;
const FENCE_MARKER = /^( {0,3})(`{3,}|~{3,})([^\r\n]*)$/;

function fenceMarker(line) {
  const match = FENCE_MARKER.exec(line);
  if (!match) return null;
  return {
    character: match[2][0],
    length: match[2].length,
    trailing: match[3],
  };
}

function stripMarkdown(value) {
  return String(value)
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_~]/g, "")
    .replace(/<[^>]+>/g, "")
    .trim();
}

export function frontMatterRange(text) {
  const lines = String(text ?? "").split(/\r?\n/);
  if (!FRONT_MATTER_BOUNDARY.test(lines[0] ?? "")) return null;
  for (let index = 1; index < lines.length; index += 1) {
    if (FRONT_MATTER_BOUNDARY.test(lines[index])) return { lines, start: 0, end: index };
  }
  return null;
}

function parseScalar(raw) {
  const value = raw.trim();
  if (value === "true") return true;
  if (value === "false") return false;
  if (value === "null" || value === "~") return null;
  if (/^-?\d+(?:\.\d+)?$/.test(value)) return Number(value);
  if (value.startsWith("[") && value.endsWith("]")) {
    return value.slice(1, -1).split(",").map((part) => part.trim().replace(/^['"]|['"]$/g, "")).filter(Boolean);
  }
  return value.replace(/^['"]|['"]$/g, "");
}

export function parseFrontMatter(text) {
  const range = frontMatterRange(text);
  if (!range) return { fields: {}, rawLines: [], valid: true, present: false };
  const fields = {};
  let valid = true;
  for (const line of range.lines.slice(1, range.end)) {
    if (!line.trim() || /^\s*#/.test(line)) continue;
    const match = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
    if (!match) {
      valid = false;
      continue;
    }
    fields[match[1]] = parseScalar(match[2]);
  }
  return { fields, rawLines: range.lines.slice(1, range.end), valid, present: true };
}

function yamlValue(value) {
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  if (value === null || value === undefined || value === "") return '""';
  if (Array.isArray(value)) return `[${value.map((item) => JSON.stringify(String(item))).join(", ")}]`;
  return JSON.stringify(String(value));
}

export function upsertFrontMatter(text, key, value) {
  if (!/^[A-Za-z0-9_-]+$/.test(key)) throw new Error("Invalid front-matter key");
  const source = String(text ?? "");
  const range = frontMatterRange(source);
  if (!range) return `---\n${key}: ${yamlValue(value)}\n---\n\n${source}`;
  const lines = [...range.lines];
  let replaced = false;
  for (let index = 1; index < range.end; index += 1) {
    if (new RegExp(`^${key}:`).test(lines[index])) {
      lines[index] = `${key}: ${yamlValue(value)}`;
      replaced = true;
      break;
    }
  }
  if (!replaced) lines.splice(range.end, 0, `${key}: ${yamlValue(value)}`);
  return lines.join("\n");
}

export function extractOutline(text) {
  const outline = [];
  const lines = String(text ?? "").split(/\r?\n/);
  let fence = null;
  lines.forEach((line, index) => {
    const marker = fenceMarker(line);
    if (!fence && marker) {
      // CommonMark does not allow a backtick in the info string of a backtick
      // fence. Tilde info strings have no equivalent restriction.
      if (marker.character !== "`" || !marker.trailing.includes("`")) {
        fence = marker;
      }
      return;
    }
    if (fence) {
      const closesFence = marker
        && marker.character === fence.character
        && marker.length >= fence.length
        && !marker.trailing.trim();
      if (closesFence) fence = null;
      return;
    }
    const match = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
    if (!match) return;
    outline.push({ level: match[1].length, title: stripMarkdown(match[2]), line: index + 1 });
  });
  return outline;
}

export function extractCitationKeys(text) {
  const keys = new Set();
  const expression = /(^|[\s[(;,])@([A-Za-z0-9_:.+\-]+)/gm;
  for (const match of String(text ?? "").matchAll(expression)) keys.add(match[2]);
  return [...keys].sort((a, b) => a.localeCompare(b));
}

export function textMetrics(text, cursor = 0) {
  const source = String(text ?? "");
  const safeCursor = Math.max(0, Math.min(source.length, Number(cursor) || 0));
  const before = source.slice(0, safeCursor);
  const line = before.split("\n").length;
  const lastBreak = before.lastIndexOf("\n");
  const column = safeCursor - lastBreak;
  const words = source.trim() ? source.trim().split(/\s+/u).length : 0;
  return { line, column, words, characters: source.length };
}
