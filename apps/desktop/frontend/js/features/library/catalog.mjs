import { basename, extension } from "../../core/path-names.mjs";
import { pathIdentity } from "../../core/path-identity.mjs";
import { parseFrontMatter, bodyStartOffset } from "../../core/markdown-analysis.mjs";

export const TYPES = ["book", "document", "note", "resume", "article"];
export const validType = (value) => TYPES.includes(value);
export const newId = () => globalThis.crypto.randomUUID();
const short = (value, max = 240) =>
  typeof value === "string" ? Array.from(value.trim()).slice(0, max).join("") : "";

export function resumeData(text) {
  try {
    const data = JSON.parse(text);
    return data &&
      typeof data === "object" &&
      !Array.isArray(data) &&
      data.basics &&
      typeof data.basics === "object" &&
      !Array.isArray(data.basics) &&
      ["name", "label", "summary", "email"].some((key) => typeof data.basics[key] === "string")
      ? data
      : null;
  } catch {
    return null;
  }
}

export function draftFor(type, t) {
  const kind = { document: "markdown", article: "markdown", note: "text", resume: "json" }[type];
  if (!kind) throw new Error("Invalid document type");
  const content =
    type === "resume"
      ? JSON.stringify({ basics: { name: "", label: "", summary: "" } }, null, 2) + "\n"
      : "";
  return {
    kind,
    content,
    title: t("shelfNew" + type[0].toUpperCase() + type.slice(1)),
    libraryType: type,
  };
}

export function describe(model, stored) {
  const ext = extension(model.path);
  const sample = (model.content || "").slice(0, 16000);
  const fields = model.kind === "markdown" ? parseFrontMatter(sample).fields : {};
  const type =
    stored?.type ||
    model.libraryType ||
    (model.kind === "markdown"
      ? fields.document_type === "article"
        ? "article"
        : "document"
      : ext === "txt"
        ? "note"
        : ext === "json" && resumeData(model.content)
          ? "resume"
          : null);
  if (!validType(type)) return null;
  let title = "",
    detail = "",
    author = "";
  // A thumbnail reads a bounded excerpt. The editor keeps the complete source.
  if (type === "resume") {
    const basics = resumeData(model.content)?.basics || {};
    title = short(basics.name);
    detail = short(basics.label, 110);
  } else if (type === "note") {
    const lines = sample
      .split(/\r?\n/)
      .map((v) => v.trim())
      .filter(Boolean);
    title = short(lines[0]);
    detail = short(lines.slice(1, 4).join(" "), 110);
  } else {
    const body = sample.slice(bodyStartOffset(sample));
    title = short(fields.title) || short(body.match(/^#\s+(.+)$/m)?.[1]);
    detail = short(
      type === "article"
        ? fields.journal
        : body.split(/\r?\n/).find((line) => line.trim() && !line.startsWith("#")),
      110,
    );
    author = short(
      [
        short(fields.author),
        typeof fields.year === "number" ? String(fields.year) : short(fields.year),
      ]
        .filter(Boolean)
        .join(" · "),
      110,
    );
  }
  return { type, title: title || short(basename(model.path) || model.title), detail, author };
}

export function upsert(items, record) {
  const key = pathIdentity(record.path);
  const prior = items.find((item) => pathIdentity(item.path) === key);
  if (!prior)
    return [
      ...items,
      items.some((item) => item.id === record.id) ? { ...record, id: newId() } : record,
    ];
  if (
    prior.type === record.type &&
    prior.title === record.title &&
    prior.detail === record.detail &&
    prior.author === record.author
  )
    return items;
  return items.map((item) =>
    item.id === prior.id
      ? {
          ...item,
          type: record.type,
          title: record.title,
          detail: record.detail,
          author: record.author,
        }
      : item,
  );
}

export function moveVisible(items, movingId, targetId, visibleIds) {
  const visible = new Set(visibleIds);
  const order = items.filter((item) => visible.has(item.id));
  const from = order.findIndex((item) => item.id === movingId);
  const to = order.findIndex((item) => item.id === targetId);
  if (from < 0 || to < 0 || from === to) return items;
  order.splice(to, 0, order.splice(from, 1)[0]);
  let cursor = 0;
  return items.map((item) => (visible.has(item.id) ? order[cursor++] : item));
}

export function packNotes(items) {
  const slots = [];
  for (const item of items) {
    const last = slots.at(-1);
    if (item.type === "note" && last?.length === 1 && last[0].type === "note") last.push(item);
    else slots.push([item]);
  }
  return slots;
}

export function searchKey(value) {
  return String(value || "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[يى]/gu, "ی")
    .replace(/ك/gu, "ک")
    .replace(/[\u064b-\u065f\u0670]/gu, "")
    .replace(/[۰-۹]/gu, (x) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(x)))
    .replace(/[٠-٩]/gu, (x) => String("٠١٢٣٤٥٦٧٨٩".indexOf(x)))
    .replace(/[\s\u200c]+/gu, " ")
    .trim();
}

export function createCatalogue({ read, write, changed }) {
  let snapshot = { items: [], revision: 0 };
  let ready = false;
  let pending = Promise.resolve();
  const serial = (run) => {
    const task = pending.then(run);
    pending = task.catch(() => {});
    return task;
  };
  async function load() {
    const data = await read();
    if (!Number.isSafeInteger(data?.revision) || !Array.isArray(data.items))
      throw new Error("Invalid shelf response");
    snapshot = data;
    ready = true;
  }
  function change(edit) {
    return serial(async () => {
      if (!ready) await load();
      for (let attempt = 0; ; attempt++) {
        const items = edit(snapshot.items);
        if (items === snapshot.items) {
          changed();
          return;
        }
        try {
          const { revision } = await write(snapshot.revision, items);
          snapshot = { items, revision };
          changed();
          return;
        } catch (error) {
          const code = error?.application_code || error?.data?.application_code || error?.code;
          if (attempt || code !== "MARDAS-LIBRARY-CONFLICT") throw error;
          await load();
        }
      }
    });
  }
  return {
    change,
    get items() {
      return snapshot.items;
    },
    get revision() {
      return snapshot.revision;
    },
    refresh: () =>
      serial(async () => {
        await load();
        changed();
      }),
  };
}
