// The catalogue remains authoritative for files. A draft is stored only as
// an ID and its neighbouring file IDs; document text never enters this key.
export function orderedShelf(saved, drafts, pins = []) {
  const remaining = new Map(drafts.map((d) => [d.id, d]));
  const positions = new Map(saved.map((s, i) => [s.id, i]));
  const slots = Array.from({ length: saved.length + 1 }, () => []);
  for (const pin of pins) {
    const item = remaining.get(pin?.id);
    if (!item) continue;
    const index =
      positions.get(pin.before) ??
      (positions.has(pin.after) ? positions.get(pin.after) + 1 : saved.length);
    slots[index].push(item);
    remaining.delete(item.id);
  }
  const result = [];
  for (let i = 0; i < saved.length; i++) result.push(...slots[i], saved[i]);
  return result.concat(slots.at(-1), [...remaining.values()]);
}
export function captureDrafts(rows, savedIds) {
  let before = null;
  const next = new Map();
  for (let i = rows.length - 1; i >= 0; i--) {
    const id = rows[i].id;
    if (savedIds.has(id)) before = id;
    else next.set(id, before);
  }
  let after = null;
  const pins = [];
  for (const row of rows) {
    if (savedIds.has(row.id)) after = row.id;
    else pins.push({ id: row.id, before: next.get(row.id), after });
  }
  return pins;
}
export function promoteDraft(saved, entry, pins) {
  const wasDraft = pins.some((p) => p.id === entry.id);
  if (!wasDraft) return { rows: saved.concat(entry), pins };
  const draftIds = pins.filter((p) => !saved.some((s) => s.id === p.id)).map((p) => p.id);
  const rows = orderedShelf(
    saved,
    draftIds.map((id) => (id === entry.id ? entry : { id })),
    pins,
  );
  const savedIds = new Set([...saved.map((s) => s.id), entry.id]);
  return { rows: rows.filter((s) => savedIds.has(s.id)), pins: captureDrafts(rows, savedIds) };
}
