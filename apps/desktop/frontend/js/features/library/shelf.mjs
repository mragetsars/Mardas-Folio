import { captureDrafts, orderedShelf, promoteDraft } from "./draft-order.mjs";
import { basename } from "../../core/path-names.mjs";
import { pathIdentity } from "../../core/path-identity.mjs";
import { readLibrary, writeLibrary } from "../../adapters/library-api.mjs";
import {
  createCatalogue,
  describe,
  moveVisible,
  newId,
  packNotes,
  privatePreview,
  searchKey,
  TYPES,
  upsert,
} from "./catalog.mjs";
import { editAppearance } from "./appearance.mjs";
import { createTypeMenu } from "./create-menu.mjs";
import { element, shelfObject, libraryIcon } from "./objects.mjs";
import { installShelfDrag, shelfGeometry } from "./shelf-layout.mjs";

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
  const scroller = document.getElementById("library-view");
  const menu = createTypeMenu({ t, create, boundary: scroller });
  const moveMenu = element("div", "library-move-menu");
  moveMenu.id = "shelf-move-menu";
  moveMenu.hidden = true;
  moveMenu.setAttribute("role", "menu");
  document.body.append(moveMenu);
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
  const pinKey = "mardas.desktop.shelf-draft-order.v1";
  let pins = [];
  try {
    const stored = JSON.parse(localStorage.getItem(pinKey) || "[]");
    if (Array.isArray(stored)) pins = stored.filter((p) => typeof p?.id === "string");
  } catch {
    /* Local settings can be unavailable in a restricted profile. */
  }
  function rememberPins(next) {
    pins = next;
    try {
      localStorage.setItem(pinKey, JSON.stringify(pins));
    } catch {
      /* Keep this session usable. */
    }
  }
  let visible = [],
    moveGrip = null,
    touchItem = null,
    filterType = "",
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
      ...d,
      ...(hidden ? privatePreview() : {}),
      appearance,
    };
  }
  function remember(model) {
    if (!model?.path) return;
    let promoted = null;
    return guard(
      catalogue
        .change((items) => {
          const existing = items.find((i) => pathIdentity(i.path) === pathIdentity(model.path));
          // A chapter is represented by its project unless explicitly catalogued on its own.
          if (
            model.projectPath &&
            !existing &&
            state.project?.book?.chapters?.some((c) => c.path === model.projectRelativePath)
          )
            return items;
          const entry = record(model, existing);
          if (!entry) return items;
          if (!existing && pins.some((p) => p.id === entry.id)) {
            promoted = promoteDraft(items, entry, pins);
            return promoted.rows;
          }
          promoted = null;
          return upsert(items, entry);
        })
        .then(() => {
          if (promoted) {
            rememberPins(promoted.pins);
            render();
          }
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
  function shelfDrafts() {
    return state.documents
      .filter((model) => !model.path)
      .map((model) => record(model))
      .filter(Boolean);
  }
  function listing() {
    const records = new Map(
      state.documents.filter((m) => m.path).map((m) => [pathIdentity(m.path), m]),
    );
    const saved = catalogue.items.map((item) => {
      const model = records.get(pathIdentity(item.path));
      return model && item.type !== "book" ? { ...item, ...record(model, item) } : item;
    });
    return orderedShelf(saved, shelfDrafts(), pins);
  }
  function displayName(item) {
    return item.appearance.privacy === "hidden"
      ? t("shelfPrivate")
      : item.appearance.label || item.title || t("shelf" + item.type);
  }
  function focus(id, selector = ".library-open", scroll = false) {
    const item = [...grid.querySelectorAll(".library-item")].find((node) => node.dataset.id === id);
    if (scroll) item?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    (item?.querySelector(selector) || item?.querySelector(".library-open"))?.focus({
      preventScroll: true,
    });
  }
  function actionIcon(symbol, label, run) {
    const button = element("button");
    button.append(libraryIcon(symbol));
    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.addEventListener("click", run);
    return button;
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
        return appearance.privacy === "hidden" ? { ...updated, ...privatePreview() } : updated;
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
              ...(i.appearance.privacy === "hidden" ? privatePreview() : {}),
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
  function movableIds() {
    return visible.map((item) => item.id);
  }
  async function move(id, target, ids, side, keyboard = false) {
    if (sort.value !== "manual" || id === target) return;
    let nextPins = null;
    await catalogue.change((items) => {
      const ordered = orderedShelf(items, shelfDrafts(), pins);
      const next = moveVisible(ordered, id, target, ids, side);
      nextPins = null;
      if (next === ordered) return items;
      const savedIds = new Set(items.map((row) => row.id));
      nextPins = captureDrafts(next, savedIds);
      const persisted = next.filter((row) => savedIds.has(row.id));
      return persisted.every((row, i) => items[i] === row) ? items : persisted;
    });
    if (nextPins) {
      rememberPins(nextPins);
      render();
      say("shelfMoveDone");
    }
    focus(id, keyboard ? ".library-grip" : ".library-open", true);
  }
  function moveBy(id, direction) {
    const ids = movableIds();
    const position = ids.indexOf(id);
    const target =
      direction === "first" ? 0 : direction === "last" ? ids.length - 1 : position + direction;
    if (ids[target]) void guard(move(id, ids[target], ids, undefined, true));
  }
  function closeMove(restore = false) {
    if (!moveGrip) return;
    moveGrip.setAttribute("aria-expanded", "false");
    moveGrip.closest(".library-item")?.classList.remove("menu-open");
    if (restore) moveGrip.focus({ preventScroll: true });
    moveGrip = null;
    moveMenu.hidden = true;
  }
  function positionMove() {
    if (!moveGrip) return;
    const anchor = moveGrip.getBoundingClientRect();
    const edge = scroller.getBoundingClientRect();
    if (anchor.bottom <= edge.top || anchor.top >= edge.bottom) return closeMove();
    const { width, height } = moveMenu.getBoundingClientRect();
    const left = document.documentElement.dir === "rtl" ? anchor.right - width : anchor.left;
    moveMenu.style.left =
      Math.max(8, Math.min(left, document.documentElement.clientWidth - width - 8)) + "px";
    moveMenu.style.top =
      Math.max(
        8,
        anchor.bottom + height + 14 <= window.innerHeight
          ? anchor.bottom + 6
          : anchor.top - height - 6,
      ) + "px";
  }
  function showMove(id, grip) {
    if (moveGrip === grip) return closeMove(true);
    closeMove();
    menu.close();
    const ids = movableIds();
    const pos = ids.indexOf(id);
    moveGrip = grip;
    grip.setAttribute("aria-expanded", "true");
    grip.closest(".library-item").classList.add("menu-open");
    const actions = [
      ["shelfEarlier", -1, pos === 0],
      ["shelfLater", 1, pos === ids.length - 1],
      ["shelfFirst", "first", pos === 0],
      ["shelfLast", "last", pos === ids.length - 1],
    ];
    moveMenu.replaceChildren(
      ...actions.map(([label, direction, disabled]) => {
        const button = element("button", "", t(label));
        button.type = "button";
        button.tabIndex = -1;
        button.disabled = disabled;
        button.setAttribute("role", "menuitem");
        button.addEventListener("click", () => {
          closeMove(true);
          moveBy(id, direction);
        });
        return button;
      }),
    );
    moveMenu.hidden = false;
    positionMove();
    moveMenu.querySelector("button:enabled")?.focus({ preventScroll: true });
  }
  moveMenu.addEventListener("keydown", (event) => {
    if (event.key === "Escape" || event.key === "Tab") {
      if (event.key === "Escape") event.preventDefault();
      closeMove(true);
      return;
    }
    const options = [...moveMenu.querySelectorAll("button:enabled")];
    const index = options.indexOf(document.activeElement);
    const next = { ArrowUp: index - 1, ArrowDown: index + 1, Home: 0, End: options.length - 1 }[
      event.key
    ];
    if (next === undefined) return;
    event.preventDefault();
    options[(next + options.length) % options.length]?.focus();
  });
  moveMenu.addEventListener("focusout", (event) => {
    if (
      event.relatedTarget &&
      event.relatedTarget !== moveGrip &&
      !moveMenu.contains(event.relatedTarget)
    )
      closeMove();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!moveMenu.contains(event.target) && !moveGrip?.contains(event.target)) closeMove();
    if (touchItem && !touchItem.contains(event.target)) {
      touchItem.classList.remove("tools-open");
      touchItem = null;
    }
  });
  scroller.addEventListener("scroll", positionMove, { passive: true });
  window.addEventListener("resize", positionMove);
  function tile(item) {
    const node = element("div", "library-item");
    node.dataset.id = item.id;
    node.dataset.type = item.type;
    node.setAttribute("role", "listitem");
    const button = element("button", "library-open");
    button.type = "button";
    const name = displayName(item);
    button.title = name;
    button.setAttribute("aria-label", name + " · " + t("shelf" + item.type));
    const specimen = element("span", "library-specimen");
    specimen.append(shelfObject(item, t));
    button.append(specimen);
    let pointerType;
    button.addEventListener("pointerdown", (event) => {
      pointerType = event.pointerType;
    });
    button.addEventListener("click", (event) => {
      if (event.detail && pointerType === "touch" && touchItem !== node) {
        touchItem?.classList.remove("tools-open");
        touchItem = node;
        node.classList.add("tools-open");
        return;
      }
      void openItem(item);
    });
    const tools = element("div", "library-tools");
    tools.setAttribute("role", "group");
    tools.setAttribute("aria-label", t("shelfTools") + " " + name);
    tools.append(
      actionIcon("edit", t("shelfAppearance"), () =>
        editAppearance(
          item,
          t,
          (a, type) => changeAppearance(item, a, type),
          () => focus(item.id),
        ),
      ),
    );
    if (sort.value === "manual") {
      node.dataset.movable = "";
      const grip = actionIcon("grip", t("shelfGrip"), () => showMove(item.id, grip));
      grip.className = "library-grip";
      grip.setAttribute("aria-haspopup", "menu");
      grip.setAttribute("aria-expanded", "false");
      grip.setAttribute("aria-controls", moveMenu.id);
      grip.disabled = movableIds().length < 2;
      grip.addEventListener("keydown", (event) => {
        const rtl = document.documentElement.dir === "rtl";
        const direction = {
          ArrowUp: -1,
          ArrowDown: 1,
          ArrowLeft: rtl ? 1 : -1,
          ArrowRight: rtl ? -1 : 1,
          Home: "first",
          End: "last",
        }[event.key];
        if (direction === undefined) return;
        event.preventDefault();
        moveBy(item.id, direction);
      });
      tools.append(grip);
    }
    const removeButton = actionIcon(
      "trash",
      t(item.path ? "shelfRemove" : "shelfDiscard"),
      () => void guard(remove(item)),
    );
    removeButton.className = "library-remove";
    tools.append(removeButton);
    node.append(button, tools);
    return node;
  }
  function sizeShelf() {
    if (!grid.clientWidth || !grid.childElementCount) {
      menu.layout();
      return;
    }
    const { columns, scale, gap } = shelfGeometry(grid.clientWidth, grid.childElementCount);
    grid.style.setProperty("--columns", columns);
    grid.style.setProperty("--desk-scale", scale.toFixed(5));
    grid.style.setProperty("--shelf-gap", gap + "px");
    menu.layout();
  }
  function render() {
    if (document.body.dataset.view !== "library" || drag.active()) return;
    const items = listing();
    const count = filter.querySelector(".library-filter-count");
    if (count) count.textContent = new Intl.NumberFormat(state.locale).format(items.length);
    visible = items.filter(
      (i) =>
        (!filterType || i.type === filterType) &&
        searchKey(
          i.appearance.privacy === "hidden"
            ? t("shelfPrivate")
            : [
                displayName(i),
                i.path,
                i.author,
                i.detail,
                i.organization,
                i.summary,
                i.skills,
              ].join(" "),
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
    const key = JSON.stringify([state.locale, sort.value, filterType, search.value, visible]);
    if (key === currentKey) return;
    currentKey = key;
    const active = document.activeElement;
    const focused = active?.closest(".library-item")?.dataset.id;
    const gripFocused = active?.matches(".library-grip");
    closeMove();
    menu.close();
    touchItem = null;
    grid.replaceChildren();
    for (const group of packNotes(visible)) {
      const slot = element("div", "library-slot");
      slot.setAttribute("role", "presentation");
      if (group[0].type === "note") slot.classList.add("library-note-slot");
      slot.append(...group.map(tile));
      grid.append(slot);
    }
    const slot = element("div", "library-slot library-add-slot");
    slot.setAttribute("role", "listitem");
    slot.append(menu.host);
    grid.append(slot);
    sizeShelf();
    document.getElementById("shelf-no-results").hidden =
      Boolean(visible.length) || (!filterType && !search.value);
    if (focused) focus(focused, gripFocused ? ".library-grip" : ".library-open");
  }
  function selectFilter(type) {
    filterType = type;
    for (const button of filter.children)
      button.setAttribute("aria-pressed", String(button.value === type));
    render();
  }
  function translate() {
    const order = sort.value || "manual";
    filter.replaceChildren(
      ...["", ...TYPES].map((type) => {
        const button = element("button", "library-filter", t(type ? "shelf" + type : "shelfAll"));
        button.type = "button";
        button.value = type;
        button.setAttribute("aria-pressed", String(type === filterType));
        if (!type) button.append(element("span", "library-filter-count"));
        button.addEventListener("click", () => selectFilter(type));
        return button;
      }),
    );
    sort.replaceChildren(
      ...["manual", "name", "type"].map((value) => {
        const key = "shelf" + value[0].toUpperCase() + value.slice(1);
        const option = element("option", "", t(key));
        option.value = value;
        return option;
      }),
    );
    sort.value = order;
    menu.translate();
    drawNotice();
    render();
  }
  const drag = installShelfDrag({
    grid,
    scroller,
    closeMenus: () => {
      closeMove();
      menu.close();
    },
    move: (id, target, ids, side) => void guard(move(id, target, ids, side)),
    settled: render,
  });
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(sizeShelf).observe(grid);
  else window.addEventListener("resize", sizeShelf);
  document.getElementById("shelf-reset").addEventListener("click", () => {
    search.value = "";
    selectFilter("");
    search.focus();
  });
  search.addEventListener("input", render);
  document.addEventListener("keydown", (event) => {
    if (
      event.defaultPrevented ||
      event.key !== "/" ||
      event.altKey ||
      event.ctrlKey ||
      event.metaKey ||
      !grid.clientWidth ||
      document.querySelector("dialog[open]") ||
      event.target.closest?.("input, textarea, select, [contenteditable]")
    )
      return;
    event.preventDefault();
    search.focus();
  });
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
    openNew: menu.open,
    focusNew: () => menu.trigger.focus(),
    items: () => catalogue.items,
  };
}
