import { enableDialogBackdrop } from "../../ui/dialog-backdrop.mjs";
import { defaults, element } from "./objects.mjs";
import { choices } from "./appearance-options.mjs";
const fields = {
  book: ["variant", "color", "texture", "pattern", "mark", "picture", "logo"],
  document: ["color", "fastener", "mark", "logo"],
  note: ["material", "color"],
  resume: ["avatar", "picture"],
  article: ["color", "binding", "pattern", "picture"],
};
async function thumbnail(file) {
  if (
    !file ||
    file.size > 10 * 1024 * 1024 ||
    !["image/jpeg", "image/png", "image/webp"].includes(file.type)
  )
    throw new Error("image");
  const url = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  const img = new Image();
  img.src = url;
  await img.decode();
  const scale = Math.min(1, 280 / Math.max(img.naturalWidth, img.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  const data = canvas.toDataURL("image/jpeg", 0.74);
  if (data.length > 98304 || !data.startsWith("data:image/jpeg;")) throw new Error("image");
  return data;
}
export function editAppearance(item, t, save, restore) {
  let type = item.type;
  const dialog = element("dialog", "library-form");
  const form = element("form");
  const title = element("h2", "", t("shelfAppearance"));
  title.id = "shelf-appearance-heading";
  dialog.setAttribute("aria-labelledby", title.id);
  const body = element("div", "library-form-fields"),
    values = { ...item.appearance };
  const error = element("div", "library-form-error");
  error.setAttribute("role", "alert");
  const actions = element("div", "library-form-actions"),
    reset = element("button", "library-action", t("shelfAuto")),
    cancel = element("button", "library-action", t("cancel")),
    apply = element("button", "button primary", t("save"));
  reset.type = cancel.type = "button";
  apply.type = "submit";
  let busy = 0,
    saving = false;
  function disabled() {
    apply.disabled = Boolean(busy) || saving;
    reset.disabled = Boolean(busy) || saving;
    cancel.disabled = saving;
  }
  function control(key) {
    const label = element("label");
    label.append(element("span", "", t("sf" + key)));
    let input;
    const value = values[key] ?? defaults(type)[key];
    if (choices[key]) {
      input = element("select");
      for (const v of choices[key]) {
        const o = element("option", "", t("sv" + v));
        o.value = v;
        input.append(o);
      }
      input.value = value;
      input.addEventListener("change", () => {
        values[key] = input.value;
      });
    } else if (key === "picture" || key === "logo") {
      label.className = "wide";
      input = element("input");
      input.type = "file";
      input.accept = "image/jpeg,image/png,image/webp";
      input.addEventListener("change", async () => {
        if (!input.files[0]) return;
        busy++;
        disabled();
        error.textContent = "";
        input.disabled = true;
        try {
          values[key] = await thumbnail(input.files[0]);
        } catch {
          error.textContent = t("shelfImageError");
        } finally {
          busy--;
          disabled();
          input.disabled = false;
        }
      });
    } else {
      input = element("input");
      input.type = key === "color" ? "color" : "text";
      if (key === "label") {
        label.className = "wide";
        input.maxLength = 180;
        input.dir = "auto";
        input.placeholder = item.title || "";
      }
      input.value = value || "";
      input.addEventListener("input", () => {
        if (input.value) values[key] = input.value;
        else delete values[key];
      });
    }
    label.append(input);
    return label;
  }
  function build() {
    body.replaceChildren(...["label", ...fields[type], "privacy"].map(control));
    if (item.type === "article" || item.type === "document") {
      const label = element("label", "wide"),
        select = element("select");
      for (const value of ["document", "article"]) {
        const option = element("option", "", t("shelf" + value));
        option.value = value;
        select.append(option);
      }
      select.value = type;
      select.disabled = Boolean(busy);
      select.addEventListener("change", () => {
        type = select.value;
        build();
        body.querySelector("select").focus();
      });
      label.append(element("span", "", t("shelfItemType")), select);
      body.prepend(label);
    }
  }
  reset.addEventListener("click", () => {
    for (const key of Object.keys(values)) delete values[key];
    build();
  });
  cancel.addEventListener("click", () => dialog.close());
  dialog.addEventListener("cancel", (event) => {
    if (saving) event.preventDefault();
  });
  dialog.addEventListener(
    "close",
    () => {
      dialog.remove();
      restore();
    },
    { once: true },
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || saving) return;
    saving = true;
    disabled();
    try {
      await save(values, type);
      dialog.close();
    } catch {
      error.textContent = t("shelfWriteError");
    } finally {
      saving = false;
      disabled();
    }
  });
  build();
  actions.append(reset, cancel, apply);
  form.append(title, body, error, actions);
  dialog.append(form);
  document.body.append(dialog);
  enableDialogBackdrop(dialog, () => !saving);
  dialog.showModal();
}
