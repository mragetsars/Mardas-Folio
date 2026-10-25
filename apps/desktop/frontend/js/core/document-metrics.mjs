import { textMetrics } from "./markdown-analysis.mjs";

/** Cursor movement must not rescan a book-sized buffer for its word count. */
export function createDocumentMetrics(analyze = textMetrics) {
  const cache = new WeakMap();
  return (model, position = { line: 1, column: 1 }) => {
    if (!model) return { words: 0, characters: 0, ...position };
    let entry = cache.get(model);
    if (!entry || entry.version !== model.contentVersion || entry.content !== model.content) {
      const value = analyze(model.content, 0);
      entry = { version: model.contentVersion, content: model.content,
        words: value.words, characters: value.characters };
      cache.set(model, entry);
    }
    return { words: entry.words, characters: entry.characters, ...position };
  };
}
