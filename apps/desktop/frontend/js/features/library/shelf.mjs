import { basename } from "../../core/path-names.mjs";
import { pathIdentity } from "../../core/path-identity.mjs";
import { readLibrary, writeLibrary } from "../../adapters/library-api.mjs";
import {
  createCatalogue,
  describe,
  moveVisible,
  newId,
  packNotes,
  searchKey,
  TYPES,
  upsert,
} from "./catalog.mjs";
import { editAppearance } from "./appearance.mjs";
import { createTypeMenu } from "./create-menu.mjs";
import { element, shelfObject } from "./objects.mjs";

export function createShelf({
  state,
  t,
  create,
  open,
  locate,
  editDraft,
  discardDraft,
  errorCode,
}) {
  const grid = document.getElementById("shelf-grid"),
    search = document.getElementById("shelf-search");
  const filter = document.getElementById("shelf-filter"),
    sort = document.getElementById("shelf-sort"),
    notice = document.getElementById("shelf-status");
  const menu = createTypeMenu({ t, create, boundary: document.getElementById("workspace-empty") });
  const catalogue = createCatalogue({
    read: readLibrary,
    write: async (rev, items) => {
      try {
        return await writeLibrary(rev, items);
      } catch (e) {
        throw Object.assign(new Error("Shelf write"), { code: errorCode(e) });
      }
    },
    changed: render,
  });
  let visible = [],
    moving = null,
    feedback = null,
    recentlyRemoved = null,
    currentKey = "";
  function say(key, action = null) {
    feedback = { key, action };
    drawNotice();
  }
  function drawNotice() {
    notice.replaceChildren();
    if (!feedback) return;
    notice.append(element("span", "", t(feedback.key)));
    if (feedback.action) {
      const b = element("button", "library-action", t(feedback.action.label));
      b.type = "button";
      b.addEventListener("click", feedback.action.run);
      notice.append(b);
    }
  }
  const guard = (task) => Promise.resolve(task).catch(() => say("shelfWriteError"));
  function record(model, existing) {
    const d = describe(model, existing);
    if (!d) return null;
    const appearance = existing?.appearance || model.libraryAppearance || {};
    const hidden = appearance.privacy === "hidden";
    return {
      id: existing?.id || model.id,
      path: model.path,
      type: d.type,
      title: hidden ? "" : d.title,
      detail: hidden ? "" : d.detail,
      author: hidden ? "" : d.author,
      appearance,
    };
  }
  function remember(model) {
    if (!model?.path) return;
    return guard(
      catalogue.change((items) => {
        const existing = items.find((i) => pathIdentity(i.path) === pathIdentity(model.path));
        // A chapter is represented by its project unless explicitly catalogued on its own.
        if (
          model.projectPath &&
          !existing &&
          state.project?.book?.chapters?.some((c) => c.path === model.projectRelativePath)
        )
          return items;
        const entry = record(model, existing);
        return entry ? upsert(items, entry) : items;
      }),
    );
  }
  function rememberBook(project) {
    if (!project?.book || !project.path) return;
    return guard(
      catalogue.change((items) => {
        const old = items.find((i) => pathIdentity(i.path) === pathIdentity(project.path));
        const a = old?.appearance || {};
        return upsert(items, {
          id: old?.id || newId(),
          path: project.path,
          type: "book",
          title:
            a.privacy === "hidden"
              ? ""
              : String(project.book.title || project.name || basename(project.path)).slice(0, 240),
          detail: "",
          author: "",
          appearance: a,
        });
      }),
    );
  }
  function listing() {
    const records = new Map(
      state.documents.filter((m) => m.path).map((m) => [pathIdentity(m.path), m]),
    );
    const saved = catalogue.items.map((item) => {
      const model = records.get(pathIdentity(item.path));
      return model && item.type !== "book" ? { ...item, ...record(model, item) } : item;
    });
    const drafts = state.documents
      .filter((m) => !m.path)
      .map((m) => record(m))
      .filter(Boolean);
    return [...saved, ...drafts];
  }
  function displayName(item) {
    return item.appearance.privacy === "hidden"
      ? t("shelfPrivate")
      : item.appearance.label || item.title || t("shelf" + item.type);
  }
  function focus(id) {
    [...grid.querySelectorAll(".library-item")]
      .find((n) => n.dataset.id === id)
      ?.querySelector(".library-open")
      ?.focus({ preventScroll: true });
  }
  function actionIcon(symbol, label, run) {
    const b = element("button", "", symbol);
    b.type = "button";
    b.title = label;
    b.setAttribute("aria-label", label);
    b.addEventListener("click", run);
    return b;
  }
  async function changeAppearance(item, appearance, type = item.type) {
    const model = state.documents.find((m) => m.id === item.id && !m.path);
    if (model) {
      editDraft({ ...model, libraryAppearance: appearance, libraryType: type });
      model.libraryType = type;
      model.libraryAppearance = appearance;
      render();
      return;
    }
    await catalogue.change((items) =>
      items.map((row) => {
        if (row.id !== item.id) return row;
        const updated = { ...row, appearance, type };
        const model = state.documents.find((m) => pathIdentity(m.path) === pathIdentity(row.path));
        if (row.type !== "book" && model) return record(model, updated);
        return appearance.privacy === "hidden"
          ? { ...updated, title: "", detail: "", author: "" }
          : updated;
      }),
    );
    const opened = state.documents.find((m) => pathIdentity(m.path) === pathIdentity(item.path));
    if (opened) opened.libraryType = type;
  }
  async function remove(item) {
    if (!item.path) {
      await discardDraft(item.id);
      render();
      return;
    }
    let index = -1,
      removed;
    await catalogue.change((items) => {
      index = items.findIndex((i) => i.id === item.id);
      if (index < 0) return items;
      removed = items[index];
      return items.filter((i) => i.id !== item.id);
    });
    if (!removed) return;
    recentlyRemoved = { removed, index };
    say("shelfRemoved", { label: "undo", run: () => void guard(undo()) });
    menu.trigger.focus({ preventScroll: true });
  }
  async function undo() {
    const original = recentlyRemoved;
    if (!original) return;
    await catalogue.change((items) => {
      if (
        items.some(
          (i) =>
            i.id === original.removed.id ||
            pathIdentity(i.path) === pathIdentity(original.removed.path),
        )
      )
        return items;
      const next = [...items];
      next.splice(Math.min(original.index, next.length), 0, original.removed);
      return next;
    });
    recentlyRemoved = null;
    feedback = null;
    drawNotice();
    focus(original.removed.id);
  }
  async function relink(item) {
    const replacement = await locate(item, catalogue.items);
    if (!replacement) return;
    await catalogue.change((items) => {
      if (
        items.some(
          (i) => i.id !== item.id && pathIdentity(i.path) === pathIdentity(replacement.path),
        )
      )
        throw new Error("duplicate");
      return items.map((i) =>
        i.id === item.id
          ? {
              ...i,
              ...replacement,
              ...(i.appearance.privacy === "hidden" ? { title: "", detail: "", author: "" } : {}),
              id: i.id,
              appearance: i.appearance,
            }
          : i,
      );
    });
    feedback = null;
    drawNotice();
  }
  async function openItem(item) {
    try {
      if (await open(item)) {
        feedback = null;
        drawNotice();
        return;
      }
    } catch {
      /* The underlying open operation can fail after a disk move. */
    }
    say("shelfUnavailable", { label: "shelfLocate", run: () => void guard(relink(item)) });
  }
  async function move(id, target) {
    if (sort.value !== "manual" || id === target) return;
    const ids = visible.filter((i) => i.path).map((i) => i.id);
    await catalogue.change((items) => moveVisible(items, id, target, ids));
    focus(id);
  }
  function tile(item) {
    const node = element("div", "library-item");
    node.dataset.id = item.id;
    node.dataset.type = item.type;
    const button = element("button", "library-open");
    button.type = "button";
    button.title = displayName(item);
    button.setAttribute("aria-label", displayName(item) + " · " + t("shelf" + item.type));
    button.append(shelfObject(item, t));
    button.addEventListener("click", () => void openItem(item));
    const tools = element("div", "library-tools");
    tools.append(
      actionIcon("✎", t("shelfAppearance"), () =>
        editAppearance(
          item,
          t,
          (a, type) => changeAppearance(item, a, type),
          () => focus(item.id),
        ),
      ),
    );
    if (item.path && sort.value === "manual") {
      const pos = visible.filter((i) => i.path).findIndex((i) => i.id === item.id);
      const neighbours = visible.filter((i) => i.path);
      const grip = actionIcon("⠿", t("shelfGrip"), () => {});
      grip.className = "library-grip";
      grip.addEventListener("pointerdown", (e) => {
        if (e.button !== 0 || moving) return;
        moving = {
          id: item.id,
          pointer: e.pointerId,
          x: e.clientX,
          y: e.clientY,
          target: null,
          dragging: false,
        };
        grip.setPointerCapture?.(e.pointerId);
        e.preventDefault();
      });
      grip.addEventListener("keydown", (e) => {
        const rtl = document.documentElement.dir === "rtl";
        const step = {
          ArrowUp: -1,
          ArrowDown: 1,
          ArrowLeft: rtl ? 1 : -1,
          ArrowRight: rtl ? -1 : 1,
        }[e.key];
        if (step) {
          e.preventDefault();
          const to = neighbours[pos + step];
          if (to) void guard(move(item.id, to.id));
        }
      });
      tools.append(grip);
      const prev = actionIcon(
        "−1",
        t("shelfEarlier"),
        () => void guard(move(item.id, neighbours[pos - 1].id)),
      );
      const next = actionIcon(
        "+1",
        t("shelfLater"),
        () => void guard(move(item.id, neighbours[pos + 1].id)),
      );
      prev.disabled = pos <= 0;
      next.disabled = pos >= neighbours.length - 1;
      tools.append(prev, next);
    }
    tools.append(
      actionIcon(
        "×",
        t(item.path ? "shelfRemove" : "shelfDiscard"),
        () => void guard(remove(item)),
      ),
    );
    node.append(button, tools);
    return node;
  }
  function render() {
    if (state.activeDocumentId) return;
    visible = listing().filter(
      (i) =>
        (!filter.value || i.type === filter.value) &&
        searchKey(
          i.appearance.privacy === "hidden"
            ? t("shelfPrivate")
            : [displayName(i), i.path, i.author, i.detail].join(" "),
        ).includes(searchKey(search.value)),
    );
    if (sort.value !== "manual")
      visible.sort((a, b) =>
        sort.value === "type"
          ? t("shelf" + a.type).localeCompare(t("shelf" + b.type), state.locale) ||
            displayName(a).localeCompare(displayName(b), state.locale)
          : displayName(a).localeCompare(displayName(b), state.locale),
      );
    // Do not discard keyboard focus or an expanded deck on an unchanged engine refresh.
    const key = JSON.stringify([state.locale, sort.value, filter.value, search.value, visible]);
    if (key === currentKey) return;
    currentKey = key;
    const focused = document.activeElement?.closest(".library-item")?.dataset.id;
    menu.close();
    grid.replaceChildren();
    for (const group of packNotes(visible)) {
      const slot = element("div", "library-slot");
      slot.append(...group.map(tile));
      grid.append(slot);
    }
    const slot = element("div", "library-slot");
    slot.append(menu.host);
    grid.append(slot);
    document.getElementById("shelf-no-results").hidden =
      Boolean(visible.length) || (!filter.value && !search.value);
    if (focused) focus(focused);
  }
  function translate() {
    const f = filter.value,
      s = sort.value;
    function options(el, values, keys) {
      el.replaceChildren(
        ...values.map((v, i) => {
          const o = element("option", "", t(keys[i]));
          o.value = v;
          return o;
        }),
      );
    }
    options(filter, ["", ...TYPES], ["shelfAll", ...TYPES.map((v) => "shelf" + v)]);
    options(sort, ["manual", "name", "type"], ["shelfManual", "shelfName", "shelfType"]);
    filter.value = f;
    sort.value = s || "manual";
    menu.translate();
    drawNotice();
    render();
  }
  function stopDrag(commit) {
    const p = moving;
    moving = null;
    grid.querySelector(".is-target")?.classList.remove("is-target");
    if (commit && p?.dragging && p.target) void guard(move(p.id, p.target));
  }
  document.addEventListener("pointermove", (e) => {
    if (e.pointerId !== moving?.pointer) return;
    moving.dragging ||= Math.hypot(e.clientX - moving.x, e.clientY - moving.y) > 6;
    if (!moving.dragging) return;
    const target = document.elementFromPoint(e.clientX, e.clientY)?.closest(".library-item");
    grid.querySelector(".is-target")?.classList.remove("is-target");
    moving.target =
      target && grid.contains(target) && visible.find((i) => i.id === target.dataset.id)?.path
        ? target.dataset.id
        : null;
    if (moving.target && moving.target !== moving.id) target.classList.add("is-target");
  });
  document.addEventListener("pointerup", (e) => {
    if (e.pointerId === moving?.pointer) stopDrag(true);
  });
  document.addEventListener("pointercancel", (e) => {
    if (e.pointerId === moving?.pointer) stopDrag(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && moving) stopDrag(false);
  });
  window.addEventListener("blur", () => stopDrag(false));
  search.addEventListener("input", render);
  filter.addEventListener("change", render);
  sort.addEventListener("change", render);
  async function initialize(recents) {
    try {
      await catalogue.refresh();
      if (!catalogue.revision && recents.length)
        await catalogue.change((items) =>
          recents.reduce((next, r) => {
            const type = /\.txt$/i.test(r.path)
              ? "note"
              : /\.(?:md|markdown)$/i.test(r.path)
                ? "document"
                : null;
            if (!type || next.some((i) => pathIdentity(i.path) === pathIdentity(r.path)))
              return next;
            return [
              ...next,
              {
                id: newId(),
                path: r.path,
                type,
                title: basename(r.path).slice(0, 240),
                appearance: {},
              },
            ];
          }, items),
        );
    } catch {
      say("shelfReadError", {
        label: "shelfRetry",
        run: () => {
          feedback = null;
          drawNotice();
          void initialize(recents);
        },
      });
    }
  }
  translate();
  return {
    render,
    translate,
    initialize,
    remember,
    rememberBook,
    typeFor: (path) =>
      catalogue.items.find((row) => pathIdentity(row.path) === pathIdentity(path))?.type,
    focusNew: () => menu.trigger.focus(),
    items: () => catalogue.items,
  };
}
