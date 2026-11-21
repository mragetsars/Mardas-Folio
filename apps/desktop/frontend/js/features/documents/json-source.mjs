// Preserve all bytes outside a selected JSON value, including duplicate keys,
// insignificant whitespace and numeric literals beyond Number.MAX_SAFE_INTEGER.
export function jsonTree(source) {
  if (source.length > 4 * 1024 * 1024) throw new RangeError("size");
  JSON.parse(source);
  const tokens =
    /\s*(?:"(?:\\.|[^"\\])*"|[{}\[\],:]|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)/gy;
  let next,
    count = 0;
  function advance() {
    const match = tokens.exec(source);
    const raw = match?.[0].trimStart();
    next = match && { raw, from: tokens.lastIndex - raw.length, to: tokens.lastIndex };
  }
  function parse(depth) {
    if (depth > 120 || ++count > 120000) throw new RangeError("complexity");
    const first = next;
    advance();
    if (first.raw !== "{" && first.raw !== "[") {
      const type =
        first.raw[0] === '"'
          ? "string"
          : first.raw === "null"
            ? "null"
            : /^(true|false)$/.test(first.raw)
              ? "boolean"
              : "number";
      return { type, from: first.from, to: first.to };
    }
    const object = first.raw === "{",
      end = object ? "}" : "]";
    const children = [];
    while (next.raw !== end) {
      let key = String(children.length);
      if (object) {
        key = JSON.parse(next.raw);
        advance();
        advance();
      }
      children.push({ key, node: parse(depth + 1) });
      if (next.raw === ",") advance();
    }
    const to = next.to;
    advance();
    return { type: object ? "object" : "array", from: first.from, to, children };
  }
  advance();
  return parse(0);
}
export function replaceScalar(source, node, raw) {
  const replacement = jsonTree(raw);
  if (replacement.children || replacement.type !== node.type)
    throw new TypeError("Incompatible JSON field");
  return source.slice(0, node.from) + raw + source.slice(node.to);
}
export function updateResumeFields(source, fields) {
  let text = source;
  try {
    for (const [key, value] of Object.entries(fields)) {
      if (!["name", "label", "email", "summary"].includes(key) || typeof value !== "string")
        continue;
      const basics = jsonTree(text).children?.findLast((entry) => entry.key === "basics")?.node;
      if (basics?.type !== "object") return null;
      const old = basics.children.findLast((entry) => entry.key === key)?.node;
      if (old) {
        if (old.type === "string" && JSON.parse(text.slice(old.from, old.to)) === value) continue;
        text = replaceScalar(text, old, JSON.stringify(value));
      } else if (value) {
        const end = basics.children.at(-1)?.node.to ?? basics.from + 1;
        const insert =
          (basics.children.length ? ", " : "") + JSON.stringify(key) + ": " + JSON.stringify(value);
        text = text.slice(0, end) + insert + text.slice(end);
      }
    }
    return text;
  } catch {
    return null;
  }
}
