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
  const matches = findLiteralMatches(source, query);
  if (!matches.length) return { text: source, count: 0 };
  const value = String(replacement ?? "");
  let cursor = 0;
  let output = "";
  for (const match of matches) {
    output += source.slice(cursor, match.start) + value;
    cursor = match.end;
  }
  output += source.slice(cursor);
  return { text: output, count: matches.length };
}
