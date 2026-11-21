import { updateResumeFields } from "../documents/json-source.mjs";
import { enableDialogBackdrop } from "../../ui/dialog-backdrop.mjs";
import { resumeData } from "./catalog.mjs";
import { element } from "./objects.mjs";

const fields = ["name", "label", "email", "summary"];
export function updateBasics(source, values) {
  return resumeData(source) ? updateResumeFields(source, values) : null;
}
export function editResume(model, t, apply, restore) {
  const source = model.content;
  const data = resumeData(source);
  const dialog = element("dialog", "library-form"),
    form = element("form");
  const title = element("h2", "", t("shelfResumeFields"));
  title.id = "resume-fields-heading";
  dialog.setAttribute("aria-labelledby", title.id);
  const body = element("div", "library-form-fields");
  const error = element("p", "library-form-error");
  error.setAttribute("role", "alert");
  const values = {};
  if (data)
    for (const key of fields) {
      const field = element(key === "summary" ? "textarea" : "input");
      const label = element("label", "wide");
      field.value = typeof data.basics[key] === "string" ? data.basics[key] : "";
      field.dir = "auto";
      field.addEventListener("input", () => {
        values[key] = field.value;
      });
      label.append(element("span", "", t("resume" + key)), field);
      body.append(label);
    }
  else error.textContent = t("shelfResumeInvalid");
  const cancel = element("button", "library-action", t("cancel"));
  cancel.type = "button";
  cancel.onclick = () => dialog.close();
  const submit = element("button", "button primary", t("shelfApply"));
  submit.type = "submit";
  submit.disabled = !data;
  const actions = element("div", "library-form-actions");
  actions.append(cancel, submit);
  form.append(title, body, error, actions);
  dialog.append(form);
  document.body.append(dialog);
  dialog.addEventListener(
    "close",
    () => {
      dialog.remove();
      restore();
    },
    { once: true },
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const content = updateBasics(source, values);
    if (content === null || model.content !== source || !apply(content)) {
      error.textContent = t("shelfResumeChanged");
      return;
    }
    dialog.close();
  });
  enableDialogBackdrop(dialog);
  dialog.showModal();
}
