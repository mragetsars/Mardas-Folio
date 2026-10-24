import { foldPersianLetters } from "./persian.mjs";

function escapeRegularExpression(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Re-exported so document search keeps one import.
 *
 * The rule itself lives in `persian.mjs` because the command palette and the
 * settings search need the same reading of a Persian word, and a second copy
 * would be a second answer to "are these the same letter".
 */
export { foldPersianLetters };

export function findLiteralMatches(text, query, { limit = 10_000 } = {}) {
  const source = String(text ?? "");
  const needle = String(query ?? "");
  if (!needle) return [];

  const numericLimit = Number(limit);
  const maximum = Number.isFinite(numericLimit)
    ? Math.max(0, Math.floor(numericLimit))
    : 10_000;
  if (!maximum) return [];

  // Match against a fold of the original string so offsets always remain valid
  // UTF-16 selection positions. Lowercasing first would not be safe — U+0130
  // expands into two code points — but the Persian fold is one character for
  // one, so the folded string indexes exactly like the source.
  const expression = new RegExp(escapeRegularExpression(foldPersianLetters(needle)), "giu");
  const matches = [];
  for (const match of foldPersianLetters(source).matchAll(expression)) {
    const start = match.index ?? 0;
    matches.push({ start, end: start + match[0].length });
    if (matches.length >= maximum) break;
  }
  return matches;
}

export function replaceAllLiteral(text, query, replacement) {
  const source = String(text ?? "");
  const needle = String(query ?? "");
  if (!needle) return { text: source, count: 0 };
  // The navigation list is bounded, but Replace All must reach every match.
  // Iterate the expression directly rather than allocating an unbounded list
  // of selection objects for a large document with many one-letter matches.
  const expression = new RegExp(escapeRegularExpression(foldPersianLetters(needle)), "giu");
  const value = String(replacement ?? "");
  let cursor = 0;
  let count = 0;
  const parts = [];
  for (const match of foldPersianLetters(source).matchAll(expression)) {
    const start = match.index ?? 0;
    parts.push(source.slice(cursor, start), value);
    cursor = start + match[0].length;
    count += 1;
  }
  if (!count) return { text: source, count: 0 };
  parts.push(source.slice(cursor));
  return { text: parts.join(""), count };
}

/** Search offsets belong to one exact document, buffer and query. */
export function createFindSession() {
  let owner = null;
  let source = null;
  let needle = null;
  let matches = [];
  let index = -1;

  function refresh(snapshot, { reset = false, anchor = null } = {}) {
    const documentId = snapshot?.documentId ?? null;
    const text = String(snapshot?.text ?? "");
    const query = String(snapshot?.query ?? "");
    const changed = owner !== documentId || source !== text || needle !== query;
    if (changed) {
      const previous = owner === documentId && needle === query ? matches[index]?.start : null;
      owner = documentId;
      source = text;
      needle = query;
      matches = findLiteralMatches(text, query);
      const position = anchor ?? previous;
      const next = position == null ? 0 : matches.findIndex((match) => match.start >= position);
      index = matches.length ? (next < 0 ? 0 : next) : -1;
    }
    if (reset) index = matches.length ? 0 : -1;
    if (anchor !== null && matches.length) {
      const next = matches.findIndex((match) => match.start >= anchor);
      index = next < 0 ? 0 : next;
    }
    return { matches, index };
  }

  return {
    refresh,
    select(snapshot, next) {
      refresh(snapshot);
      index = matches.length ? ((next % matches.length) + matches.length) % matches.length : -1;
      return matches[index] ?? null;
    },
    move(snapshot, direction) {
      refresh(snapshot);
      return this.select(snapshot, index + direction);
    },
    current(snapshot) {
      refresh(snapshot);
      return matches[index] ?? null;
    },
    clear() {
      owner = source = needle = null;
      matches = [];
      index = -1;
    },
  };
}
