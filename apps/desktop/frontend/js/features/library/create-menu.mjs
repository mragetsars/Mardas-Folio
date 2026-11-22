import { TYPES } from "./catalog.mjs";
import { element, libraryIcon } from "./objects.mjs";

const icons = {
  book: "book",
  document: "metadata",
  note: "note",
  resume: "resume",
  article: "article",
};
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

export function createTypeMenu({ t, create, boundary }) {
  const host = element("div", "library-deck");
  const trigger = element("button", "library-add");
  const stack = element("span", "library-add-stack");
  const label = element("strong", "library-add-label");
  const hint = element("small", "library-add-hint");
  const plus = element("span", "library-deck-plus");
  plus.append(libraryIcon("plus"));
  trigger.id = "shelf-add";
  trigger.type = "button";
  stack.setAttribute("aria-hidden", "true");
  trigger.append(stack, label, hint);
  host.append(trigger);
  const menu = element("div", "library-type-deck");
  menu.id = "shelf-type-list";
  menu.setAttribute("role", "menu");
  trigger.setAttribute("aria-haspopup", "menu");
  trigger.setAttribute("aria-controls", menu.id);
  let open = false;
  let pinned = false;
  let area;
  let closeTimer;
  const buttons = TYPES.map((type) => {
    const button = element("button", "library-choice");
    button.type = "button";
    button.tabIndex = -1;
    button.setAttribute("role", "menuitem");
    const face = element("span", "library-deck-face");
    const icon = element("span", "library-mini");
    icon.dataset.type = type;
    icon.append(libraryIcon(icons[type]));
    icon.setAttribute("aria-hidden", "true");
    const text = element("span", "library-choice-label");
    face.append(icon, text);
    button.append(face);
    button.addEventListener("click", () => {
      close(true);
      create(type);
    });
    return button;
  });
  buttons.at(-1).append(plus);
  menu.append(...buttons);
  document.body.append(menu);

  function layout() {
    const box = stack.getBoundingClientRect();
    const edge = boundary.getBoundingClientRect();
    const width = document.documentElement.clientWidth;
    const height = window.innerHeight;
    if (
      !box.width ||
      box.bottom <= Math.max(0, edge.top) ||
      box.top >= Math.min(height, edge.bottom)
    ) {
      if (open) close(false);
      menu.hidden = true;
      return false;
    }
    menu.hidden = false;
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    menu.style.left = x + "px";
    menu.style.top = y + "px";
    const radius = 84;
    const clearance = 48;
    const padding = 8;
    const scale = clamp(
      (Math.min(Math.min(width, edge.right) - Math.max(0, edge.left), height) - 2 * padding) /
        (2 * (radius + clearance)),
      0.01,
      1,
    );
    const rtl = document.documentElement.dir === "rtl";
    const offsets = TYPES.map((_, index) => {
      const angle = ((index * 72 - 90) * Math.PI) / 180;
      return {
        x: Math.cos(angle) * radius * scale * (rtl ? -1 : 1),
        y: Math.sin(angle) * radius * scale,
      };
    });
    const margin = clearance * scale + padding;
    const minX = Math.min(...offsets.map((p) => p.x)) - margin;
    const maxX = Math.max(...offsets.map((p) => p.x)) + margin;
    const minY = Math.min(...offsets.map((p) => p.y)) - margin;
    const maxY = Math.max(...offsets.map((p) => p.y)) + margin;
    const centerX = clamp(x, Math.max(0, edge.left) - minX, Math.min(width, edge.right) - maxX);
    const centerY = clamp(y, -minY, height - maxY);
    menu.style.setProperty("--orbit-scale", scale);
    buttons.forEach((button, index) => {
      const point = offsets[index];
      button.style.setProperty("--orbit-x", centerX - x + point.x + "px");
      button.style.setProperty("--orbit-y", centerY - y + point.y + "px");
    });
    area = {
      left: Math.min(x - 45, centerX + minX),
      right: Math.max(x + 45, centerX + maxX),
      top: Math.min(y - 35, centerY + minY),
      bottom: Math.max(y + 35, centerY + maxY),
    };
    return true;
  }
  function show(focus = false) {
    clearTimeout(closeTimer);
    closeTimer = undefined;
    if (!layout()) return;
    open = true;
    menu.dataset.pose = "fan";
    menu.inert = false;
    menu.removeAttribute("aria-hidden");
    trigger.setAttribute("aria-expanded", "true");
    if (focus) buttons[0].focus({ preventScroll: true });
  }
  function close(focus = false) {
    clearTimeout(closeTimer);
    closeTimer = undefined;
    if (focus) trigger.focus({ preventScroll: true });
    open = false;
    pinned = false;
    menu.dataset.pose = "stack";
    menu.inert = true;
    menu.setAttribute("aria-hidden", "true");
    trigger.setAttribute("aria-expanded", "false");
  }
  menu.addEventListener("keydown", (event) => {
    if (event.key === "Escape" || event.key === "Tab") {
      if (event.key === "Escape") event.preventDefault();
      close(true);
      return;
    }
    const index = buttons.indexOf(document.activeElement);
    const rtl = document.documentElement.dir === "rtl";
    const step = { ArrowDown: 1, ArrowUp: -1, ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1 }[
      event.key
    ];
    const position = step
      ? (index + step + buttons.length) % buttons.length
      : { Home: 0, End: buttons.length - 1 }[event.key];
    if (position === undefined) return;
    event.preventDefault();
    buttons[position].focus({ preventScroll: true });
  });
  trigger.addEventListener("pointerenter", (event) => {
    if (event.pointerType !== "touch" && !pinned && !open) show();
  });
  trigger.addEventListener("click", (event) => {
    if (pinned) return close();
    pinned = event.detail === 0 || event.pointerType !== "mouse";
    show(event.detail === 0);
  });
  trigger.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      close(true);
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      pinned = true;
      show(true);
    }
  });
  for (const node of [trigger, menu]) {
    node.addEventListener("focusout", (event) => {
      if (
        event.relatedTarget &&
        !trigger.contains(event.relatedTarget) &&
        !menu.contains(event.relatedTarget)
      )
        close();
    });
  }
  document.addEventListener("pointermove", (event) => {
    if (!open || pinned || menu.contains(document.activeElement) || event.pointerType === "touch")
      return;
    const inside =
      event.clientX >= area.left &&
      event.clientX <= area.right &&
      event.clientY >= area.top &&
      event.clientY <= area.bottom;
    if (inside) {
      clearTimeout(closeTimer);
      closeTimer = undefined;
    } else if (closeTimer === undefined) closeTimer = setTimeout(close, 130);
  });
  document.addEventListener("pointerdown", (event) => {
    if (open && !trigger.contains(event.target) && !menu.contains(event.target)) close();
  });
  boundary.addEventListener("scroll", layout, { passive: true });
  window.addEventListener("resize", layout);
  function translate() {
    label.textContent = t("shelfNew");
    hint.textContent = t("shelfPickType");
    trigger.setAttribute("aria-label", label.textContent);
    menu.setAttribute("aria-label", label.textContent);
    buttons.forEach((button, index) => {
      button.querySelector(".library-choice-label").textContent = t("shelf" + TYPES[index]);
    });
  }
  menu.hidden = true;
  translate();
  close();
  return {
    host,
    trigger,
    translate,
    close,
    layout,
    open() {
      trigger.focus();
      pinned = true;
      show(true);
    },
  };
}
