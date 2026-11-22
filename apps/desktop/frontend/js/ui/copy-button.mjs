import { spriteIcon } from "./icons.mjs";

export function createCopyButton(document, { read, labels, className }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "geist-copy-button " + className;
  button.setAttribute("aria-label", labels.copy);
  button.title = labels.copy;
  const icon = spriteIcon("duplicate", document);
  const status = document.createElement("span");
  status.className = "sr-only";
  status.setAttribute("role", "status");
  button.append(icon, status);
  let timer;
  let attempt = 0;
  const show = (symbol, message) => {
    icon.firstElementChild.setAttribute("href", "#icon-" + symbol);
    status.textContent = message;
    button.title = message || labels.copy;
  };
  button.addEventListener("click", async () => {
    const content = read();
    if (content == null) return;
    const current = ++attempt;
    let success = true;
    try {
      await document.defaultView.navigator.clipboard.writeText(content);
    } catch {
      success = false;
    }
    if (current !== attempt || !button.isConnected) return;
    clearTimeout(timer);
    show(success ? "check" : "alert", success ? labels.copied : labels.failed);
    timer = setTimeout(() => show("duplicate", ""), 1800);
  });
  return button;
}
