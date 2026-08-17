import { foldForFilter } from "./persian.mjs";

/**
 * Both sides of the comparison are read the same way, so a command spelled
 * with ی and a joiner is found by someone typing ي and a space.
 */
function normalize(value) {
  return foldForFilter(value);
}

export function filterCommands(commands, query, limit = 12) {
  const needle = normalize(query);
  const scored = [];
  for (const command of commands || []) {
    if (!command || command.enabled === false) continue;
    const label = normalize(command.label);
    const keywords = normalize(command.keywords);
    if (!needle) {
      scored.push({ command, score: Number(command.priority) || 0 });
      continue;
    }
    const labelIndex = label.indexOf(needle);
    const keywordIndex = keywords.indexOf(needle);
    if (labelIndex < 0 && keywordIndex < 0) continue;
    let score = Number(command.priority) || 0;
    if (labelIndex === 0) score += 100;
    else if (labelIndex > 0) score += 60 - Math.min(labelIndex, 40);
    if (keywordIndex >= 0) score += 20 - Math.min(keywordIndex, 15);
    scored.push({ command, score });
  }
  return scored
    .sort((a, b) => b.score - a.score || String(a.command.label).localeCompare(String(b.command.label)))
    .slice(0, Math.max(1, Number(limit) || 12))
    .map(({ command }) => command);
}
