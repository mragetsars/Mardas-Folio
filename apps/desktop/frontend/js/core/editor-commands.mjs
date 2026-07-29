export function replaceSelection(text, start, end, replacement, selectionOffset = replacement.length) {
  const source = String(text ?? "");
  const left = Math.max(0, Math.min(source.length, Number(start) || 0));
  const right = Math.max(left, Math.min(source.length, Number(end) || left));
  return {
    text: source.slice(0, left) + replacement + source.slice(right),
    start: left + selectionOffset,
    end: left + selectionOffset,
  };
}

export function wrapSelection(text, start, end, prefix, suffix = prefix, placeholder = "text") {
  const source = String(text ?? "");
  const left = Math.max(0, Math.min(source.length, Number(start) || 0));
  const right = Math.max(left, Math.min(source.length, Number(end) || left));
  const selected = source.slice(left, right) || placeholder;
  return {
    text: source.slice(0, left) + prefix + selected + suffix + source.slice(right),
    start: left + prefix.length,
    end: left + prefix.length + selected.length,
  };
}

export function prefixSelectedLines(text, start, end, prefix) {
  const source = String(text ?? "");
  const left = source.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
  const rightBreak = source.indexOf("\n", Math.max(end, start));
  const right = rightBreak < 0 ? source.length : rightBreak;
  const block = source.slice(left, right);
  const replaced = block.split("\n").map((line) => `${prefix}${line}`).join("\n");
  return {
    text: source.slice(0, left) + replaced + source.slice(right),
    start: left,
    end: left + replaced.length,
  };
}
