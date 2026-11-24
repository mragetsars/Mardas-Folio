import { spriteIcon } from "../frontend/js/ui/icons.mjs";

export function editorDialog(view, title) {
  const fa = document.documentElement.lang.startsWith("fa");
  const dialog = document.createElement("dialog");
  dialog.className = "cm-editor-dialog";
  dialog.setAttribute("aria-label", title);
  const form = document.createElement("form");
  const header = document.createElement("header");
  const heading = document.createElement("h2");
  heading.textContent = title;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "icon-button";
  close.ariaLabel = fa ? "بستن" : "Close";
  close.append(spriteIcon("close"));
  close.addEventListener("click", () => dialog.close());
  header.append(heading, close);
  const body = document.createElement("div");
  body.className = "cm-editor-dialog-body";
  const footer = document.createElement("footer");
  const message = document.createElement("p");
  message.setAttribute("role", "alert");
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "button secondary";
  cancel.textContent = fa ? "لغو" : "Cancel";
  cancel.addEventListener("click", () => dialog.close());
  const apply = document.createElement("button");
  apply.type = "submit";
  apply.className = "button primary";
  apply.textContent = fa ? "اعمال" : "Apply";
  footer.append(message, cancel, apply);
  form.append(header, body, footer);
  dialog.append(form);
  dialog.addEventListener("close", () => {
    dialog.remove();
    if (view.dom.isConnected) view.contentDOM.focus({ preventScroll: true });
  });
  return {
    dialog,
    body,
    apply,
    message,
    open(submit) {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (submit() !== false) dialog.close();
      });
      document.body.append(dialog);
      dialog.showModal();
    },
  };
}
