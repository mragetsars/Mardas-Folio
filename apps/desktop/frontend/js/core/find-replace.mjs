function escapeRegularExpression(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * One Persian letter, typed two ways.
 *
 * A Persian keyboard produces ی U+06CC and ک U+06A9; an Arabic layout, older
 * Windows keyboards, and most text pasted from the web produce ي U+064A and
 * ك U+0643. The pairs are indistinguishable on screen, so a document mixing
 * them looks uniform — and searching it for a word spelled the other way found
 * nothing, which reads as "the text is not there" rather than "you typed a
 * different code point".
 *
 * Each mapping is one character to one character, so folding leaves every
 * offset where it was and the match positions stay valid selection ranges.
 * Letters that merely look similar are left alone: آ and ا are different
 * letters in Persian, and Persian and Latin digits mean different things.
 */
const PERSIAN_LETTER_FOLD = /[يىك]/g;
const PERSIAN_FOLDED = { "ي": "ی", "ى": "ی", "ك": "ک" };

export function foldPersianLetters(value) {
  return String(value ?? "").replace(PERSIAN_LETTER_FOLD, (ch) => PERSIAN_FOLDED[ch]);
}

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
