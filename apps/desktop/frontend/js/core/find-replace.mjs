export function findLiteralMatches(text, query, { limit = 10_000 } = {}) {
  const source = String(text ?? "");
  const needle = String(query ?? "");
  if (!needle) return [];
  const haystack = source.toLocaleLowerCase();
  const normalizedNeedle = needle.toLocaleLowerCase();
  const matches = [];
  let offset = 0;
  while (offset <= haystack.length - normalizedNeedle.length && matches.length < limit) {
    const index = haystack.indexOf(normalizedNeedle, offset);
    if (index < 0) break;
    matches.push({ start: index, end: index + normalizedNeedle.length });
    offset = index + Math.max(1, normalizedNeedle.length);
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
