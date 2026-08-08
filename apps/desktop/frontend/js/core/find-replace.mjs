function escapeRegularExpression(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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

  // Match against the original string so offsets always remain valid UTF-16
  // selection positions. Lowercasing a Unicode string first is unsafe because
  // characters such as U+0130 can expand into multiple code points.
  const expression = new RegExp(escapeRegularExpression(needle), "giu");
  const matches = [];
  for (const match of source.matchAll(expression)) {
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
