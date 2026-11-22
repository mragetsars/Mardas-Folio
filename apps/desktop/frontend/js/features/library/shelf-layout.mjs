import { element } from "./objects.mjs";

export function shelfGeometry(width, slots) {
  const gap = width < 550 ? 18 : 32;
  const minWidth = width < 550 ? 132 : 178;
  const capacity = Math.min(5, Math.max(1, Math.floor((width + gap) / (minWidth + gap))));
  const rows = Math.max(1, Math.ceil(slots / capacity));
  const columns = Math.max(1, Math.ceil(slots / rows));
  return { columns, gap, scale: Math.min(1, (width - gap * (columns - 1)) / (columns * 196)) };
}

export function installShelfDrag({ grid, scroller, closeMenus, move, settled }) {
  let drag;
  let suppressClickUntil = 0;
  function dropAt({ item, ids, x, y }) {
    const bounds = grid.getBoundingClientRect();
    const viewport = scroller.getBoundingClientRect();
    if (
      x < Math.max(viewport.left, bounds.left - 12) ||
      x > Math.min(viewport.right, bounds.right + 12) ||
      y < Math.max(viewport.top, bounds.top - 15) ||
      y > Math.min(viewport.bottom, bounds.bottom + 15)
    )
      return null;
    const hit = document.elementFromPoint(x, y);
    const nodes = [...grid.querySelectorAll(".library-item[data-movable]")];
    if (hit?.closest(".library-add-slot")) {
      const target = nodes.filter((node) => node !== item).at(-1);
      return target && { target, side: "after", axis: "x" };
    }
    let target = hit?.closest(".library-item");
    if (target && !target.hasAttribute("data-movable")) return null;
    if (!target || !grid.contains(target)) {
      let nearest = 56 ** 2;
      for (const node of nodes) {
        const box = node.getBoundingClientRect();
        const distance =
          Math.max(box.left - x, 0, x - box.right) ** 2 +
          Math.max(box.top - y, 0, y - box.bottom) ** 2;
        if (distance >= nearest) continue;
        nearest = distance;
        target = node;
      }
    }
    if (!target || target === item) return null;
    const box = target.getBoundingClientRect();
    const stacked = target.dataset.type === "note" && target.parentElement.childElementCount === 2;
    const rtl = document.documentElement.dir === "rtl";
    const progress = stacked
      ? (y - box.top) / box.height
      : (rtl ? box.right - x : x - box.left) / box.width;
    const after = ids.indexOf(item.dataset.id) < ids.indexOf(target.dataset.id);
    const side = progress < 0.31 ? "before" : progress > 0.69 || after ? "after" : "before";
    return { target, side, axis: stacked ? "y" : "x" };
  }
  function clearMark() {
    if (!drag.anchor) return;
    delete drag.anchor.target.dataset.insert;
    delete drag.anchor.target.dataset.axis;
  }
  function paint() {
    drag.ghost.style.transform = `translate3d(${drag.x - drag.grabX}px, ${drag.y - drag.grabY}px, 0)`;
    const anchor = dropAt(drag);
    if (drag.anchor?.target === anchor?.target && drag.anchor?.side === anchor?.side) return;
    clearMark();
    drag.anchor = anchor;
    if (anchor) {
      anchor.target.dataset.insert = anchor.side;
      anchor.target.dataset.axis = anchor.axis;
    }
  }
  function frame() {
    drag.frame = 0;
    const { top, bottom, height } = scroller.getBoundingClientRect();
    const zone = Math.min(68, height * 0.14);
    const speed =
      drag.y < top + zone
        ? -Math.min(16, (top + zone - drag.y) * 0.23)
        : drag.y > bottom - zone
          ? Math.min(16, (drag.y - bottom + zone) * 0.23)
          : 0;
    const previous = scroller.scrollTop;
    if (speed) scroller.scrollTop += speed;
    paint();
    if (scroller.scrollTop !== previous) drag.frame = requestAnimationFrame(frame);
  }
  function start() {
    closeMenus();
    const box = drag.item.getBoundingClientRect();
    const ghost = element("div", "library-drag-image");
    ghost.dataset.type = drag.item.dataset.type;
    ghost.setAttribute("aria-hidden", "true");
    ghost.style.width = box.width + "px";
    ghost.style.height = box.height + "px";
    ghost.style.setProperty(
      "--desk-scale",
      getComputedStyle(grid).getPropertyValue("--desk-scale"),
    );
    ghost.append(drag.item.querySelector(".library-specimen").cloneNode(true));
    document.body.append(ghost);
    drag.ghost = ghost;
    drag.grabX = drag.startX - box.left;
    drag.grabY = drag.startY - box.top;
    drag.item.classList.add("is-drag-source");
    grid.classList.add("is-dragging");
    try {
      drag.handle.setPointerCapture(drag.pointer);
    } catch {
      // Pointer listeners on the document still handle the gesture.
    }
  }
  function stop(commit) {
    if (!drag) return;
    const { ghost, item, frame: queued, handle, pointer, anchor, ids } = drag;
    clearMark();
    drag = null;
    if (!ghost) return;
    if (queued) cancelAnimationFrame(queued);
    ghost.remove();
    item.classList.remove("is-drag-source");
    grid.classList.remove("is-dragging");
    if (handle.hasPointerCapture?.(pointer)) handle.releasePointerCapture(pointer);
    suppressClickUntil = performance.now() + 170;
    settled();
    if (commit && anchor) move(item.dataset.id, anchor.target.dataset.id, ids, anchor.side);
  }

  grid.addEventListener("pointerdown", (event) => {
    suppressClickUntil = 0;
    const handle = event.target.closest(".library-open, .library-grip");
    const item = handle?.closest(".library-item[data-movable]");
    if (
      !item ||
      drag ||
      event.button !== 0 ||
      !event.isPrimary ||
      (event.pointerType === "touch" && !handle.matches(".library-grip"))
    )
      return;
    const ids = [...grid.querySelectorAll(".library-item[data-movable]")].map(
      (node) => node.dataset.id,
    );
    if (ids.length < 2) return;
    const { clientX: x, clientY: y, pointerId: pointer } = event;
    drag = { item, handle, ids, pointer, x, y, startX: x, startY: y, frame: 0 };
  });
  document.addEventListener(
    "pointermove",
    (event) => {
      if (event.pointerId !== drag?.pointer) return;
      drag.x = event.clientX;
      drag.y = event.clientY;
      if (!drag.ghost) {
        if (Math.hypot(drag.x - drag.startX, drag.y - drag.startY) < 6) return;
        if (!drag.item.isConnected) return stop(false);
        start();
      }
      event.preventDefault();
      if (!drag.frame) drag.frame = requestAnimationFrame(frame);
    },
    { passive: false },
  );
  document.addEventListener("pointerup", (event) => {
    if (event.pointerId !== drag?.pointer) return;
    if (drag.ghost) {
      drag.x = event.clientX;
      drag.y = event.clientY;
      paint();
    }
    stop(true);
  });
  for (const name of ["pointercancel", "lostpointercapture"]) {
    document.addEventListener(name, (event) => {
      if (
        drag?.pointer === event.pointerId &&
        (name === "pointercancel" || event.target === drag.handle)
      )
        stop(false);
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !drag) return;
    event.preventDefault();
    stop(false);
  });
  grid.addEventListener(
    "click",
    (event) => {
      if (!event.detail || performance.now() >= suppressClickUntil) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    },
    true,
  );
  window.addEventListener("blur", () => stop(false));
  return { active: () => Boolean(drag?.ghost) };
}
