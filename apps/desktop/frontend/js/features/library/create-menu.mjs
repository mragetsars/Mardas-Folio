import { TYPES } from "./catalog.mjs";
import { element } from "./objects.mjs";

export function createTypeMenu({ t, create, boundary }) {
  const host = element("div", "library-deck");
  const trigger = element("button", "library-add", "+");
  trigger.id = "shelf-add";
  trigger.type = "button";
  trigger.setAttribute("aria-haspopup", "menu");
  const label = element("span", "library-add-label");
  const menu = element("div");
  menu.id = "shelf-type-list";
  menu.setAttribute("role", "menu");
  trigger.setAttribute("aria-controls", menu.id);
  let open = false,
    pinned = false;
  const buttons = TYPES.map((type, i) => {
    const b = element("button", "library-choice");
    b.type = "button";
    b.setAttribute("role", "menuitem");
    b.style.setProperty("--rest", [-14, -7, 0, 6, 12][i] + "deg");
    b.style.setProperty("--offset", [-6, -3, 0, 2, 5][i] + "px");
    const icon = element("span", "library-mini");
    icon.dataset.type = type;
    icon.setAttribute("aria-hidden", "true");
    b.append(icon, element("span"));
    b.addEventListener("click", () => {
      close(true);
      create(type);
    });
    menu.append(b);
    return b;
  });
  host.append(menu, trigger, label);
  function layout() {
    if (!open || !host.isConnected) return;
    const box = host.getBoundingClientRect(),
      edge = boundary.getBoundingClientRect();
    const left = Math.max(0, edge.left) + 5,
      right = Math.min(window.innerWidth, edge.right) - 5;
    const top = Math.max(0, edge.top) + 5,
      bottom = Math.min(window.innerHeight, edge.bottom) - 5;
    const span = Math.min(230, right - left, bottom - top),
      card = Math.min(60, Math.max(26, span * 0.255));
    const radius = Math.max(0, (span - card - 6) / 2),
      x = box.left + box.width / 2,
      y = box.top + box.height / 2;
    const cx = Math.max(left + span / 2, Math.min(right - span / 2, x)) - x;
    const cy = Math.max(top + span / 2, Math.min(bottom - span / 2, y)) - y;
    const rtl = document.documentElement.dir === "rtl";
    for (const [key, v] of Object.entries({ cx, cy, span, card }))
      host.style.setProperty("--" + key, v + "px");
    buttons.forEach((b, i) => {
      const angle = ((i * 72 - 90) * Math.PI) / 180;
      b.style.setProperty("--dx", cx + Math.cos(angle) * radius * (rtl ? -1 : 1) + "px");
      b.style.setProperty("--dy", cy + Math.sin(angle) * radius + "px");
    });
  }
  function show(focus = false) {
    open = true;
    host.dataset.open = "true";
    menu.inert = false;
    menu.removeAttribute("aria-hidden");
    trigger.setAttribute("aria-expanded", "true");
    layout();
    if (focus) buttons[0].focus();
  }
  function close(focus = false) {
    if (focus) trigger.focus({ preventScroll: true });
    open = false;
    pinned = false;
    host.dataset.open = "false";
    menu.inert = true;
    menu.setAttribute("aria-hidden", "true");
    trigger.setAttribute("aria-expanded", "false");
  }
  menu.addEventListener("keydown", (e) => {
    const i = buttons.indexOf(document.activeElement);
    let pos;
    if (e.key === "Escape") {
      e.preventDefault();
      close(true);
      return;
    }
    if (e.key === "Tab") {
      close(true);
      return;
    }
    const rtl = document.documentElement.dir === "rtl";
    const step = { ArrowDown: 1, ArrowUp: -1, ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1 }[
      e.key
    ];
    if (step) pos = (i + step + buttons.length) % buttons.length;
    else if (e.key === "Home") pos = 0;
    else if (e.key === "End") pos = buttons.length - 1;
    if (pos !== undefined) {
      e.preventDefault();
      buttons[pos].focus();
    }
  });
  host.addEventListener("pointerover", (e) => {
    if (e.pointerType !== "touch" && (trigger.contains(e.target) || open)) show();
  });
  host.addEventListener("pointerleave", () => {
    if (!pinned && !menu.contains(document.activeElement)) close();
  });
  trigger.addEventListener("click", (e) => {
    if (pinned) {
      close();
      return;
    }
    pinned = true;
    show(e.detail === 0);
  });
  trigger.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close(true);
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      pinned = true;
      show(true);
    }
  });
  host.addEventListener("focusout", (e) => {
    if (e.relatedTarget && !host.contains(e.relatedTarget)) close();
  });
  document.addEventListener("pointerdown", (e) => {
    if (open && !host.contains(e.target)) close();
  });
  boundary.addEventListener("scroll", layout, { passive: true });
  window.addEventListener("resize", layout);
  function translate() {
    label.textContent = t("shelfNew");
    trigger.setAttribute("aria-label", label.textContent);
    menu.setAttribute("aria-label", label.textContent);
    buttons.forEach((b, i) => {
      b.lastChild.textContent = t("shelf" + TYPES[i]);
    });
  }
  translate();
  close();
  return { host, trigger, translate, close, layout };
}
