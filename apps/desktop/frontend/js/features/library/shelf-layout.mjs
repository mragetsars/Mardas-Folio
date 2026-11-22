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
  const mark = element("div", "library-insert-mark");
  mark.setAttribute("aria-hidden", "true");
  mark.hidden = true;
  document.body.append(mark);
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
    const nodes = drag.nodes.filter((node) => node !== item);
    if (hit?.closest(".library-add-slot")) {
      const target = nodes.at(-1);
      return target && { target, side: "after" };
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
    return { target, side };
  }
  function paintMark(anchor) {
    mark.hidden = !anchor;
    if (!anchor) return;

    // Resolve both edges of an insertion to its one position in the remaining order.
    const nodes = drag.nodes.filter((node) => node !== drag.item);
    const index = nodes.indexOf(anchor.target) + Number(anchor.side === "after");
    const previous = nodes[index - 1];
    const next = nodes[index];
    const before = previous?.getBoundingClientRect();
    const after = next?.getBoundingClientRect();
    const viewport = scroller.getBoundingClientRect();
    const rtl = document.documentElement.dir === "rtl";
    const firstEdge = (box) => (rtl ? box.right : box.left);
    const lastEdge = (box) => (rtl ? box.left : box.right);
    const previousSlot = previous?.parentElement.getBoundingClientRect();
    const nextSlot = next?.parentElement.getBoundingClientRect();
    const stacked = previous && next && previous.parentElement === next.parentElement;
    const nextRow = before && after && nextSlot.top > previousSlot.top + 1;

    if (stacked || nextRow) {
      const left = stacked ? Math.max(before.left, after.left) : nextSlot.left;
      const right = stacked ? Math.min(before.right, after.right) : nextSlot.right;
      const y = stacked
        ? (before.bottom + after.top) / 2
        : (previousSlot.bottom + nextSlot.top) / 2;
      mark.hidden = y < viewport.top || y > viewport.bottom;
      mark.style.cssText = `left:${left}px;top:${y - 1}px;width:${right - left}px;height:2px`;
      return;
    }

    const x =
      before && after
        ? (lastEdge(before) + firstEdge(after)) / 2
        : before
          ? lastEdge(before) + (rtl ? -11 : 11)
          : firstEdge(after) + (rtl ? 11 : -11);
    const top = Math.max(
      viewport.top,
      Math.min(before?.top ?? Infinity, after?.top ?? Infinity) + 7,
    );
    const bottom = Math.min(viewport.bottom, Math.max(before?.bottom ?? 0, after?.bottom ?? 0) - 7);
    mark.hidden = bottom <= top;
    mark.style.cssText = `left:${x - 1}px;top:${top}px;width:2px;height:${bottom - top}px`;
  }
  function paint() {
    drag.ghost.style.transform = `translate3d(${drag.x - drag.grabX}px, ${drag.y - drag.grabY}px, 0)`;
    drag.anchor = dropAt(drag);
    paintMark(drag.anchor);
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
    mark.hidden = true;
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
    const handle = event.target.closest(".library-open");
    const item = handle?.closest(".library-item[data-movable]");
    if (!item || drag || event.button !== 0 || !event.isPrimary) return;
    const nodes = [...grid.querySelectorAll(".library-item[data-movable]")];
    if (nodes.length < 2) return;
    const ids = nodes.map((node) => node.dataset.id);
    const { clientX: x, clientY: y, pointerId: pointer } = event;
    const touchReadyAt = event.pointerType === "touch" ? performance.now() + 240 : 0;
    drag = {
      item,
      handle,
      ids,
      nodes,
      pointer,
      x,
      y,
      startX: x,
      startY: y,
      frame: 0,
      touchReadyAt,
    };
  });
  grid.addEventListener(
    "touchmove",
    (event) => {
      if (event.touches.length !== 1) {
        stop(false);
        return;
      }
      if (drag?.ghost && event.cancelable) event.preventDefault();
    },
    { passive: false },
  );
  document.addEventListener(
    "pointermove",
    (event) => {
      if (event.pointerId !== drag?.pointer) return;
      drag.x = event.clientX;
      drag.y = event.clientY;
      if (!drag.ghost) {
        if (Math.hypot(drag.x - drag.startX, drag.y - drag.startY) < 6) return;
        if (!drag.item.isConnected || performance.now() < drag.touchReadyAt) return stop(false);
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
