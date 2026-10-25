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

/**
 * Locate leading YAML front matter.
 *
 * The closing fence can never be the line directly after the opening one, so
 * `---\n---` stays a pair of thematic breaks.  That matches `FRONTMATTER_RE` in
 * `src/mardas_folio/markdown.py` and the editor's own front matter parser, so
 * the metadata panel, the outline, and the published PDF agree on where a
 * document's body begins.
 */
const FIRST_CLOSING_LINE = 2;

export function frontMatterRange(text) {
  const lines = String(text ?? "").split(/\r?\n/);
  if (!FRONT_MATTER_BOUNDARY.test(lines[0] ?? "")) return null;
  for (let index = FIRST_CLOSING_LINE; index < lines.length; index += 1) {
    if (FRONT_MATTER_BOUNDARY.test(lines[index])) return { lines, start: 0, end: index };
  }
  return null;
}

/**
 * Where a document's body starts, past any front matter.
 *
 * Live preview reveals the raw source of whatever block the caret is in, and
 * the caret defaults to offset 0 — which, in every document this application
 * creates, is inside the metadata. Write mode therefore opened on seven lines
 * of YAML where the document's title should have been.
 *
 * Counted by walking line endings in the original string rather than by
 * summing split lengths, so a file with CRLF endings lands in the same place
 * as one without.
 */
export function bodyStartOffset(text) {
  const source = String(text ?? "");
  const range = frontMatterRange(source);
  if (!range) return 0;
  let offset = 0;
  for (let consumed = 0; consumed <= range.end; consumed += 1) {
    const next = source.indexOf("\n", offset);
    if (next < 0) return source.length;
    offset = next + 1;
  }
  // Templates leave a blank line between the metadata and the first heading.
  while (offset < source.length && (source[offset] === "\n" || source[offset] === "\r")) {
    offset += 1;
  }
  return Math.min(offset, source.length);
}

function parseScalar(raw) {
  const value = raw.trim();
  if (value.startsWith('"')) {
    const quoted = /^"(?:[^"\\]|\\.)*"(?=\s*(?:#.*)?$)/.exec(value)?.[0];
    if (quoted) {
      try { return JSON.parse(quoted); } catch { return undefined; }
    }
    return undefined;
  }
  if (value.startsWith("'")) {
    const quoted = /^'(?:[^']|'')*'(?=\s*(?:#.*)?$)/.exec(value)?.[0];
    if (quoted) return quoted.slice(1, -1).replace(/''/g, "'");
    return undefined;
  }
  const plain = value.replace(/\s+#.*$/, "").trim();
  if (plain.startsWith("[")) {
    // Only flat scalar sequences belong in the compact form. Tokenize quoted
    // items so a comma inside an author's name is not treated as a separator.
    if (!plain.endsWith("]")) return undefined;
    const items = [];
    let token = "";
    let quote = null;
    const inner = plain.slice(1, -1);
    for (let index = 0; index < inner.length; index += 1) {
      const character = inner[index];
      if (quote) {
        token += character;
        if (quote === '"' && character === "\\") {
          token += inner[++index] ?? "";
        } else if (character === quote) {
          if (quote === "'" && inner[index + 1] === "'") token += inner[++index];
          else quote = null;
        }
      } else if (character === '"' || character === "'") {
        quote = character;
        token += character;
      } else if (character === ",") {
        if (!token.trim()) return undefined;
        items.push(parseScalar(token));
        token = "";
      } else if ("[]{}".includes(character)) {
        return undefined;
      } else token += character;
    }
    if (quote) return undefined;
    if (token.trim()) items.push(parseScalar(token));
    return items.some((item) => item === undefined) ? undefined : items;
  }
  if (/^[{&*!|>]/.test(plain) || /:\s/.test(plain)) return undefined;
  if (plain === "true") return true;
  if (plain === "false") return false;
  if (plain === "null" || plain === "~") return null;
  if (/^-?\d+(?:\.\d+)?$/.test(plain)) return Number(plain);
  return plain;
}

const METADATA_KEY = /^(?:([A-Za-z0-9_-]+)|"([A-Za-z0-9_-]+)"|'([A-Za-z0-9_-]+)'):\s*(.*)$/;

// Editing one top-level value must replace its continuation as well. Preserve
// other keys verbatim: the form is deliberately not a YAML serializer.
function metadataEntries(range) {
  const entries = [];
  for (let start = 1; start < range.end; start += 1) {
    const match = METADATA_KEY.exec(range.lines[start]);
    if (!match) continue;
    let end = start + 1;
    while (end < range.end) {
      const line = range.lines[end];
      if (line.trim() && !/^[ \t]/.test(line) && !/^-\s/.test(line)) break;
      end += 1;
    }
    // Comments and blank separators after a value belong to the surrounding
    // document, not to the value being replaced.
    while (end > start + 1 && !range.lines[end - 1].trim()) end -= 1;
    entries.push({ key: match[1] || match[2] || match[3], raw: match[4], start, end });
    start = end - 1;
  }
  return entries;
}

function metadataValue(entry, lines) {
  const block = /^([|>])([+-]?)(\d?)(?:\s+#.*)?$/.exec(entry.raw.trim());
  const continuation = lines.slice(entry.start + 1, entry.end);
  if (block) {
    // The compact form cannot round-trip keep-chomp or folded paragraphs.
    // Leave those values to source editing instead of inventing their text.
    if (block[2] === "+" || (block[1] === ">" && continuation.some((line) => !line.trim()))) return undefined;
    const nonempty = continuation.filter((line) => line.trim());
    const indent = block[3] ? Number(block[3])
      : Math.min(...nonempty.map((line) => /^ */.exec(line)[0].length));
    const parts = continuation.map((line) => line.slice(Number.isFinite(indent) ? indent : 0));
    let value = parts.join("\n");
    if (block[1] === ">") {
      value = parts.reduce((result, part, index) => {
        if (!index) return part;
        const previous = parts[index - 1];
        const separator = !previous || !part || /^\s/.test(previous) || /^\s/.test(part) ? "\n" : " ";
        return result + separator + part;
      }, "");
    }
    if (block[2] === "-") return value.replace(/\n+$/, "");
    return value.replace(/\n+$/, "") + (parts.length ? "\n" : "");
  }
  if (!entry.raw.trim() && continuation.length && continuation.every((line) => /^\s*-\s/.test(line))) {
    const items = continuation.map((line) => parseScalar(line.replace(/^\s*-\s*/, "")));
    return items.some((item) => item === undefined) ? undefined : items;
  }
  if (continuation.some((line) => line.trim())) return undefined;
  if ((entry.raw.startsWith('"') && !/^"(?:[^"\\]|\\.)*"(?:\s+#.*)?\s*$/.test(entry.raw))
    || (entry.raw.startsWith("'") && !/^'(?:[^']|'')*'(?:\s+#.*)?\s*$/.test(entry.raw))) return undefined;
  return parseScalar(entry.raw);
}

export function parseFrontMatter(text) {
  const range = frontMatterRange(text);
  if (!range) return { fields: {}, rawLines: [], valid: true, present: false };
  const fields = {};
  let valid = true;
  const covered = new Set();
  for (const entry of metadataEntries(range)) {
    for (let index = entry.start; index < entry.end; index += 1) covered.add(index);
    const value = metadataValue(entry, range.lines);
    if (value === undefined) valid = false;
    else Object.defineProperty(fields, entry.key, { value, enumerable: true, configurable: true });
  }
  for (let index = 1; index < range.end; index += 1) {
    if (!covered.has(index) && range.lines[index].trim() && !/^\s*#/.test(range.lines[index])) valid = false;
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
  const matches = metadataEntries(range).filter((entry) => entry.key === key);
  for (const entry of [...matches].reverse()) {
    lines.splice(entry.start, entry.end - entry.start, `${key}: ${yamlValue(value)}`);
  }
  if (!matches.length) lines.splice(range.end, 0, `${key}: ${yamlValue(value)}`);
  return lines.join(source.includes("\r\n") ? "\r\n" : "\n");
}

export function extractOutline(text) {
  const outline = [];
  const lines = String(text ?? "").split(/\r?\n/);
  // A `#` comment inside YAML front matter is metadata, not a document
  // heading; without this the outline and preview navigation pick it up as H1.
  const bodyStart = (frontMatterRange(text)?.end ?? -1) + 1;
  let fence = null;
  let paragraph = [];
  let containerParagraph = false;
  let htmlBlock = null;
  const listStart = /^ {0,3}(?:[-+*]|\d{1,9}[.)])(?:[ \t]+|$)/;
  const interruptingList = /^ {0,3}(?:[-+*]|1[.)])(?:[ \t]+|$)/;
  lines.forEach((line, index) => {
    if (index < bodyStart) return;
    if (htmlBlock) {
      if (htmlBlock === "blank" ? !line.trim() : htmlBlock.test(line)) htmlBlock = null;
      return;
    }
    const marker = fenceMarker(line);
    if (!fence && marker) {
      // CommonMark does not allow a backtick in the info string of a backtick
      // fence. Tilde info strings have no equivalent restriction.
      if (marker.character !== "`" || !marker.trailing.includes("`")) {
        fence = marker;
        paragraph = [];
        containerParagraph = false;
        return;
      }
    }
    if (fence) {
      const closesFence = marker
        && marker.character === fence.character
        && marker.length >= fence.length
        && !marker.trailing.trim();
      if (closesFence) fence = null;
      return;
    }
    if (!line.trim()) {
      paragraph = [];
      containerParagraph = false;
      return;
    }
    const match = /^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
    if (match) {
      outline.push({ level: match[1].length, title: stripMarkdown(match[2]), line: index + 1 });
      paragraph = [];
      containerParagraph = false;
      return;
    }
    const underline = /^ {0,3}(=+|-+)[ \t]*$/.exec(line);
    if (underline && paragraph.length && !containerParagraph) {
      outline.push({
        level: underline[1][0] === "=" ? 1 : 2,
        title: stripMarkdown(paragraph.map((entry) => entry.text.trim()).join(" ")),
        line: paragraph[0].line,
      });
      paragraph = [];
      return;
    }
    // A dash underline takes precedence over a thematic break only when it
    // follows paragraph text. Separate rules and lazy list/quote continuations
    // must never manufacture headings from a divider.
    if (/^ {0,3}(?:(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|(?:-[ \t]*){3,})$/.test(line)) {
      paragraph = [];
      containerParagraph = false;
      return;
    }
    let htmlEnd = null;
    const rawTag = /^ {0,3}<(script|pre|style|textarea)(?=[\s>]|$)/i.exec(line);
    if (rawTag) htmlEnd = new RegExp(`</${rawTag[1]}\\s*>`, "i");
    else if (/^ {0,3}<!--/.test(line)) htmlEnd = /-->/;
    else if (/^ {0,3}<\?/.test(line)) htmlEnd = /\?>/;
    else if (/^ {0,3}<!\[CDATA\[/.test(line)) htmlEnd = /\]\]>/;
    else if (/^ {0,3}<![A-Z]/.test(line)) htmlEnd = />/;
    const blockTag = /^ {0,3}<\/?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)(?:[\s/>]|$)/i.test(line);
    const completeTag = !paragraph.length && !containerParagraph && /^ {0,3}<\/?[a-z][^>]*>[ \t]*$/i.test(line);
    if (htmlEnd || blockTag || completeTag) {
      paragraph = [];
      containerParagraph = false;
      htmlBlock = htmlEnd ? (htmlEnd.test(line) ? null : htmlEnd) : "blank";
      return;
    }
    const startsContainer = /^ {0,3}>/.test(line)
      || (paragraph.length ? interruptingList : listStart).test(line);
    if (startsContainer) {
      paragraph = [];
      containerParagraph = true;
      return;
    }
    if (containerParagraph) return;
    // Indented code cannot start a paragraph, but indentation on subsequent
    // lines can be a continuation of an existing Setext heading paragraph.
    if (!paragraph.length && /^(?: {4}|\t)/.test(line)) return;
    paragraph.push({ text: line, line: index + 1 });
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
