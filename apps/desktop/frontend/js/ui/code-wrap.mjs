import { spriteIcon } from "./icons.mjs";

export function createCodeWrapButton(document, defaultWrapped, onChange) {
  const button = document.createElement("button");
  const persian = document.documentElement.lang.startsWith("fa");
  button.type = "button";
  button.className = "code-wrap-button";
  const paint = (wrapped) => {
    button.title = persian ? "شکستن خطوط کد" : "Wrap code lines";
    button.setAttribute("aria-label", button.title);
    button.setAttribute("aria-pressed", String(wrapped));
  };
  paint(defaultWrapped);
  button.append(spriteIcon("code-wrap", document));
  button.addEventListener("click", () => {
    const wrapped = button.getAttribute("aria-pressed") !== "true";
    paint(wrapped);
    onChange(wrapped);
  });
  return button;
}
