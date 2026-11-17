/** Owns this feature's DOM interactions; cross-feature actions are injected. */
export function createNotifications({ query: $ }) {
  const TOAST_LIMIT = 3;
  const TOAST_TTL = 4200;

  function dismissToast(element) {
    if (!element) return;
    clearTimeout(Number(element.dataset.toastTimer || 0));
    element.remove();
  }

  function toast(message, kind = "info") {
    const region = $("#toast-region");
    if (!region) return;
    const text = String(message ?? "");

    // A repeat counts up on the notice already standing rather than adding
    // another copy of it.
    const repeat = [...region.children].find(
      (item) => item.dataset.toastMessage === text && item.dataset.toastKind === kind,
    );
    if (repeat) {
      const count = Number(repeat.dataset.toastCount || "1") + 1;
      repeat.dataset.toastCount = String(count);
      const badge = repeat.querySelector(".toast-count");
      if (badge) {
        badge.textContent = `\u00d7${count}`;
        badge.hidden = false;
      }
      clearTimeout(Number(repeat.dataset.toastTimer || 0));
      repeat.dataset.toastTimer = String(setTimeout(() => dismissToast(repeat), TOAST_TTL));
      return;
    }

    // Nothing is learned from a fourth card; the oldest makes room.
    while (region.children.length >= TOAST_LIMIT) dismissToast(region.firstElementChild);

    const element = document.createElement("div");
    element.className = `toast ${kind}`;
    element.setAttribute("role", kind === "error" ? "alert" : "status");
    element.setAttribute("aria-atomic", "true");
    element.dataset.toastMessage = text;
    element.dataset.toastKind = kind;
    element.dataset.toastCount = "1";
    const label = document.createElement("span");
    label.className = "toast-text";
    // A notice can be either language: an engine or filesystem message arrives in
    // English even when the interface is Persian, and in an RTL container its
    // full stop was drawn at the head of the sentence. The run decides its own
    // direction.
    label.dir = "auto";
    label.textContent = text;
    const badge = document.createElement("span");
    badge.className = "toast-count";
    badge.hidden = true;
    element.append(label, badge);
    region.append(element);
    element.dataset.toastTimer = String(setTimeout(() => dismissToast(element), TOAST_TTL));
  }
  return { toast };
}
